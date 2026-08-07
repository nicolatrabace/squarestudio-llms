#!/usr/bin/env python3
"""Idempotent: Shonga client + Keetus project + Oct quote on Invoice Ninja.

Uses real Ninja fields/tabs — not note dumps.

  Client  → name Shonga; Custom Fields: Brand=Keetus, Engagement=Retainer
  Project → Overview: budgeted_amount/hours, due_date; Custom Fields; short BUDGET note
  Quote   → linked project_id, due_date, amount 6k, Custom Fields pipeline

Requires: export INVOICE_NINJA_TOKEN='…'
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

API = "https://admin.squarestudio.design/api/v1"
TOKEN = os.environ.get("INVOICE_NINJA_TOKEN", "").strip()
if not TOKEN:
    raise SystemExit("Set INVOICE_NINJA_TOKEN env var")

HEADERS = {
    "X-Api-Token": TOKEN,
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/json",
    "Accept": "application/json",
}


def api(method: str, path: str, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(API + path, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read()
            return r.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:2000]}
        return e.code, payload


def list_all(path: str, status: str | None = "active"):
    out, page = [], 1
    while True:
        q = f"{path}?per_page=100&page={page}"
        if status:
            q += f"&status={status}"
        st, d = api("GET", q)
        if st != 200:
            raise RuntimeError(f"list {path} failed {st} {d}")
        out.extend(d["data"])
        if page >= d["meta"]["pagination"]["total_pages"]:
            break
        page += 1
    return out


def ensure_custom_field_labels():
    st, d = api("GET", "/companies")
    if st != 200:
        raise RuntimeError(f"companies {st} {d}")
    co = d["data"][0]
    cf = dict(co.get("custom_fields") or {})
    wanted = {
        "client1": "Productive ID",
        "client2": "Brand",
        "client3": "Engagement",
        "project1": "Productive ID",
        "project2": "Brand",
        "project3": "Type",
        "project4": "Month status",
        "quote1": "Productive ID",
        "quote2": "Brand",
        "quote3": "Pipeline",
    }
    if all(cf.get(k) == v for k, v in wanted.items()):
        return {"step": "custom_field_labels", "status": "ok"}
    cf.update(wanted)
    st, d = api("PUT", f"/companies/{co['id']}", {"custom_fields": cf})
    if st not in (200, 201):
        raise RuntimeError(f"custom_fields update failed {st} {d}")
    return {"step": "custom_field_labels", "status": "updated"}


def main():
    report = {"actions": [ensure_custom_field_labels()]}

    clients = list_all("/clients", "active") + list_all("/clients", "archived")
    by_name = {(c.get("name") or "").strip().lower(): c for c in clients}
    client = by_name.get("shonga") or by_name.get("keetus")

    client_body = {
        "name": "Shonga",
        "display_name": "Shonga",
        "vat_number": "",
        "settings": {"currency_id": "3"},
        "custom_value1": "",
        "custom_value2": "Keetus",
        "custom_value3": "Retainer",
        "custom_value4": "",
        "public_notes": "",
        "private_notes": "Keetus brand still without VAT — bill Shonga.",
    }
    if client:
        st, d = api("PUT", f"/clients/{client['id']}", client_body)
        action = "updated"
    else:
        st, d = api(
            "POST",
            "/clients",
            {
                **client_body,
                "contacts": [
                    {
                        "first_name": "",
                        "last_name": "",
                        "email": "",
                        "phone": "",
                        "is_primary": True,
                        "send_email": False,
                    }
                ],
            },
        )
        action = "created"
    if st not in (200, 201):
        raise SystemExit(f"client {action} failed {st} {d}")
    client = d["data"]
    report["actions"].append(
        {"step": "client", "status": action, "id": client["id"], "name": client.get("name")}
    )
    client_id = client["id"]

    projects = list_all("/projects", "active") + list_all("/projects", "archived")
    project = next(
        (
            p
            for p in projects
            if (p.get("name") or "").strip().lower() == "keetus"
            and p.get("client_id") == client_id
        ),
        None,
    ) or next(
        (p for p in projects if (p.get("name") or "").strip().lower() == "keetus"),
        None,
    )

    project_body = {
        "name": "Keetus",
        "client_id": client_id,
        "budgeted_amount": 4000,
        "budgeted_hours": 0,
        "task_rate": 0,
        "due_date": "2026-08-31",
        "assigned_user_id": "VolejRejNm",
        "custom_value1": "",
        "custom_value2": "Keetus",
        "custom_value3": "Retainer forfait",
        "custom_value4": "2026-08 confirmed; 2026-09 STOP",
        "public_notes": "BUDGET: 4.000,00 EUR — forfait",
        "private_notes": "",
    }
    if project:
        st, d = api("PUT", f"/projects/{project['id']}", project_body)
        action = "updated"
    else:
        st, d = api("POST", "/projects", project_body)
        action = "created"
    if st not in (200, 201):
        raise SystemExit(f"project {action} failed {st} {d}")
    project = d["data"]
    report["actions"].append(
        {
            "step": "project",
            "status": action,
            "id": project["id"],
            "due_date": project.get("due_date"),
            "budgeted_amount": project.get("budgeted_amount"),
        }
    )

    st, qd = api("GET", f"/quotes?client_id={client_id}&per_page=100")
    if st != 200:
        raise SystemExit(f"list quotes failed {st} {qd}")
    quote = None
    for q in qd.get("data", []):
        if q.get("project_id") == project["id"] and float(q.get("amount") or 0) == 6000:
            quote = q
            break
        blob = " ".join(
            [
                q.get("custom_value3") or "",
                q.get("public_notes") or "",
                " ".join(li.get("notes") or "" for li in (q.get("line_items") or [])),
            ]
        ).lower()
        if "october" in blob or "ott+" in blob or "oct+" in blob:
            quote = q
            break

    quote_body = {
        "client_id": client_id,
        "project_id": project["id"],
        "date": "2026-08-07",
        "due_date": "2026-10-31",
        "custom_value1": "",
        "custom_value2": "Keetus",
        "custom_value3": "Oct+ negotiation",
        "custom_value4": "",
        "public_notes": "",
        "private_notes": "",
        "line_items": [
            {
                "product_key": "Framer website",
                "notes": "Monthly retainer (from October 2026)",
                "cost": 6000,
                "quantity": 1,
                "discount": 0,
                "is_amount_discount": True,
                "tax_name1": "EXO",
                "tax_rate1": 0,
                "type_id": "1",
            }
        ],
        "uses_inclusive_taxes": False,
    }
    if quote:
        st, d = api("PUT", f"/quotes/{quote['id']}", quote_body)
        action = "updated"
    else:
        quote_body["status_id"] = "1"
        st, d = api("POST", "/quotes", quote_body)
        action = "created"
    if st not in (200, 201):
        raise SystemExit(f"quote {action} failed {st} {d}")
    quote = d["data"]
    report["actions"].append(
        {
            "step": "quote",
            "status": action,
            "id": quote["id"],
            "number": quote.get("number"),
            "amount": quote.get("amount"),
            "project_id": quote.get("project_id"),
            "due_date": quote.get("due_date"),
        }
    )

    report["verify"] = {
        "client": {
            "id": client_id,
            "name": client.get("name"),
            "brand_custom_value2": client.get("custom_value2"),
        },
        "project": {
            "id": project["id"],
            "due_date": project.get("due_date"),
            "budgeted_amount": project.get("budgeted_amount"),
            "custom_value2": project.get("custom_value2"),
            "custom_value4": project.get("custom_value4"),
            "public_notes": project.get("public_notes"),
        },
        "quote": {
            "id": quote["id"],
            "number": quote.get("number"),
            "amount": quote.get("amount"),
            "project_id": quote.get("project_id"),
            "due_date": quote.get("due_date"),
        },
        "urls": {
            "client": f"https://admin.squarestudio.design/#/clients/{client_id}/edit",
            "project": f"https://admin.squarestudio.design/#/projects/{project['id']}/edit",
            "quote": f"https://admin.squarestudio.design/#/quotes/{quote['id']}/edit",
        },
    }

    out = Path(__file__).resolve().parent / "report_keetus_create.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

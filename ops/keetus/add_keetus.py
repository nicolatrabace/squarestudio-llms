#!/usr/bin/env python3
"""Idempotent: create/update Keetus on Invoice Ninja (admin.squarestudio.design).

Requires: export INVOICE_NINJA_TOKEN='…'
  (UI → Settings → API Tokens)

What this models for Square Studio sync Productive ↔ admin:
  1. CRM client
  2. Active project = lavoro corrente (forfait Agosto 4k)
  3. Draft quote = deal/negoziazione (Ottobre+ target 6k)
  4. September STOP stays in notes (no invoice, no recurring assumption)
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

CLIENT_PRIVATE = (
    "Sorgente: Productive (manuale sync ago 2026)\n"
    "=== BUDGET / RETAINER ===\n"
    "- Ago 2026: 4.000 EUR — mese singolo confermato (retainer forfait)\n"
    "- Set 2026: STOP / pausa\n"
    "- Ott 2026+: negoziazione retainer mensile — target 6.000 EUR/mese\n"
    "=== FINE BUDGET / RETAINER ===\n"
    "Nota: per ora solo agosto è confermato; non assumere ricorrenza automatica."
)

PROJECT_PUBLIC = (
    "BUDGET: 4.000,00 EUR — forfait\n"
    "Retainer mensile — solo Agosto 2026 confermato.\n"
    "Settembre: stop. Da ottobre: negoziazione verso 6.000 EUR/mese."
)

PROJECT_PRIVATE = (
    "tipo: retainer forfait (non a ore)\n"
    "confermato: 2026-08 = 4.000 EUR (singolo mese)\n"
    "settembre: STOP / nessuna fatturazione prevista\n"
    "ottobre+: negoziazione retainer ricorrente — spingere a 6.000 EUR/mese\n"
    "sync: creato in admin per allineamento con Productive\n"
    "fattura agosto: da emettere quando pronto (riga flat, non Invoice Project da timer)"
)


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


def main():
    report = {"actions": []}

    clients = list_all("/clients", "active") + list_all("/clients", "archived")
    client = next(
        (c for c in clients if (c.get("name") or "").strip().lower() == "keetus"),
        None,
    )
    if client:
        st, d = api(
            "PUT",
            f"/clients/{client['id']}",
            {
                "name": "Keetus",
                "display_name": "Keetus",
                "settings": {"currency_id": "3"},
                "private_notes": CLIENT_PRIVATE,
            },
        )
        if st not in (200, 201):
            raise SystemExit(f"client update failed {st} {d}")
        client = d["data"]
        report["actions"].append({"step": "client", "status": "updated", "id": client["id"]})
    else:
        st, d = api(
            "POST",
            "/clients",
            {
                "name": "Keetus",
                "display_name": "Keetus",
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
                "settings": {"currency_id": "3"},
                "private_notes": CLIENT_PRIVATE,
            },
        )
        if st not in (200, 201):
            raise SystemExit(f"client create failed {st} {d}")
        client = d["data"]
        report["actions"].append(
            {"step": "client", "status": "created", "id": client["id"], "name": client.get("name")}
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
    )
    project_body = {
        "name": "Keetus",
        "client_id": client_id,
        "budgeted_amount": 4000,
        "budgeted_hours": 0,
        "task_rate": 0,
        "public_notes": PROJECT_PUBLIC,
        "private_notes": PROJECT_PRIVATE,
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
    report["actions"].append({"step": "project", "status": action, "id": project["id"]})

    st, qd = api("GET", f"/quotes?client_id={client_id}&per_page=100")
    if st != 200:
        raise SystemExit(f"list quotes failed {st} {qd}")
    quote = None
    for q in qd.get("data", []):
        blob = " ".join(
            [
                q.get("public_notes") or "",
                q.get("private_notes") or "",
                " ".join(li.get("notes") or "" for li in (q.get("line_items") or [])),
            ]
        ).lower()
        if "retainer" in blob and ("ottobre" in blob or "6.000" in blob or "6000" in blob):
            quote = q
            break

    if quote:
        report["actions"].append(
            {
                "step": "quote",
                "status": "exists",
                "id": quote["id"],
                "number": quote.get("number"),
                "amount": quote.get("amount"),
            }
        )
    else:
        st, d = api(
            "POST",
            "/quotes",
            {
                "client_id": client_id,
                "date": "2026-08-07",
                "status_id": "1",
                "line_items": [
                    {
                        "product_key": "Framer website",
                        "notes": "Keetus — Retainer mensile da Ottobre 2026 (target negoziazione)",
                        "cost": 6000,
                        "quantity": 1,
                        "discount": 0,
                        "is_amount_discount": True,
                        "tax_name1": "EXO",
                        "tax_rate1": 0,
                        "type_id": "1",
                    }
                ],
                "public_notes": (
                    "Deal / negoziazione: Keetus retainer da Ottobre 2026 — target 6.000 EUR/mese"
                ),
                "private_notes": (
                    "pipeline: negoziazione post-agosto\n"
                    "contesto: agosto 4k confermato; settembre STOP; "
                    "da ottobre spingere retainer a 6k/mese\n"
                    "stato: Draft finché non firmato/confermato\n"
                    "quando vinto: Approve quote + aggiornare progetto BUDGET a 6.000"
                ),
                "uses_inclusive_taxes": False,
            },
        )
        if st not in (200, 201):
            raise SystemExit(f"quote create failed {st} {d}")
        quote = d["data"]
        report["actions"].append(
            {
                "step": "quote",
                "status": "created",
                "id": quote["id"],
                "number": quote.get("number"),
                "amount": quote.get("amount"),
            }
        )

    report["verify"] = {
        "client": {"id": client_id, "name": client.get("name")},
        "project": {
            "id": project["id"],
            "budgeted_amount": project.get("budgeted_amount"),
            "public_notes_first_line": (project.get("public_notes") or "").split("\n")[0],
        },
        "quote": {
            "id": quote["id"],
            "number": quote.get("number"),
            "amount": quote.get("amount"),
            "status_id": quote.get("status_id"),
        },
        "urls": {
            "client": f"https://admin.squarestudio.design/#/clients/{client_id}",
            "project": f"https://admin.squarestudio.design/#/projects/{project['id']}",
            "quote": f"https://admin.squarestudio.design/#/quotes/{quote['id']}",
        },
    }

    out = Path(__file__).resolve().parent / "report_keetus_create.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

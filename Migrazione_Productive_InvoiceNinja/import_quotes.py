#!/usr/bin/env python3
"""Stage: idempotent quote import from quote_deal.json → Invoice Ninja."""

from __future__ import annotations

import os
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent
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

ALIASES = {
    "omer poizner": "Omer Pozner",
    "the arc / flourishlab": "The Arc / FlourishLab",
    "april™": "April™",
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
    out = []
    page = 1
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


def extract_pid(entity: dict) -> str:
    cv = (entity.get("custom_value1") or "").strip()
    if cv:
        return cv
    for field in ("private_notes", "public_notes"):
        for line in (entity.get(field) or "").splitlines():
            if line.startswith("productive_id:"):
                return line.split(":", 1)[1].strip()
    return ""


def main():
    currency_map = json.load(open(BASE / "schema" / "currency_map.json"))
    deals = json.load(open(BASE / "quote_deal.json"))
    clients = list_all("/clients", status="active")
    by_name = {c["name"].strip().lower(): c for c in clients}
    by_pid = {}
    for c in clients:
        pid = extract_pid(c)
        if pid:
            by_pid[pid] = c
        cv = (c.get("custom_value1") or "").strip()
        if cv:
            by_pid[cv] = c

    existing = {}
    for status in ("active", "archived"):
        for q in list_all("/quotes", status=status):
            pid = extract_pid(q)
            if pid:
                existing[pid] = q

    report = {
        "created": [],
        "skipped_existing": [],
        "skipped_no_client": [],
        "errors": [],
        "marked": [],
    }

    for deal in deals:
        pid = str(deal.get("id") or "")
        if pid in existing:
            report["skipped_existing"].append(
                {
                    "productive_id": pid,
                    "invoice_ninja_id": existing[pid]["id"],
                    "name": deal.get("name"),
                }
            )
            continue

        cname = (deal.get("company_name") or "").strip()
        target = ALIASES.get(cname.lower(), cname)
        client = by_name.get(target.lower()) or by_pid.get(str(deal.get("company_id") or ""))
        if not client:
            report["skipped_no_client"].append(
                {"productive_id": pid, "name": deal.get("name"), "company": cname}
            )
            continue

        amount = float(deal.get("deal_value_total") or deal.get("budget_total") or 0)
        currency = (deal.get("currency") or "EUR").upper()
        currency_id = currency_map.get(currency, "3")
        prob = deal.get("probability")
        closed = bool(deal.get("sales_closed_at") or deal.get("closed_at"))

        # Draft always on create; then mark approved if won
        # Won: probability 100 + closed. Lost: probability 0 + closed → keep draft + note
        line = {
            "product_key": "",
            "notes": deal.get("name") or "Deal Productive",
            "cost": amount,
            "quantity": 1,
            "discount": 0,
            "is_amount_discount": True,
            "tax_name1": "",
            "tax_rate1": 0,
            "tax_name2": "",
            "tax_rate2": 0,
            "tax_name3": "",
            "tax_rate3": 0,
            "type_id": "1",
        }

        private = (
            f"productive_id: {pid}\n"
            f"productive_company_id: {deal.get('company_id')}\n"
            f"probability: {prob}\n"
            f"sales_closed_at: {deal.get('sales_closed_at')}\n"
            f"closed_at: {deal.get('closed_at')}\n"
            f"lost_comment: {deal.get('lost_comment')}\n"
            f"man_day_minutes: {deal.get('man_day_minutes')}"
        )
        if closed and (prob == 0 or prob == 0.0):
            private += "\nstatus_note: deal chiuso/perso in Productive (probability=0)"

        body = {
            "client_id": client["id"],
            "date": (deal.get("date") or "")[:10] or None,
            "due_date": (deal.get("end_date") or "")[:10] or None,
            "number": "",
            "status_id": "1",
            "line_items": [line],
            "custom_value1": pid,
            "public_notes": f"Deal Productive: {deal.get('name')}",
            "private_notes": private,
            "uses_inclusive_taxes": False,
        }
        if not body["date"]:
            del body["date"]
        if not body["due_date"]:
            del body["due_date"]

        # Set client currency via quote? Usually inherited from client.
        st, d = api("POST", "/quotes", body)
        if st not in (200, 201):
            report["errors"].append(
                {"productive_id": pid, "name": deal.get("name"), "status": st, "error": d}
            )
            continue

        quote = d["data"]
        entry = {
            "productive_id": pid,
            "invoice_ninja_id": quote["id"],
            "number": quote.get("number"),
            "name": deal.get("name"),
            "client": client["name"],
            "amount": amount,
            "probability": prob,
            "closed": closed,
            "marked": None,
        }

        # Approve won deals (prob 100)
        if closed and prob == 100:
            st2, d2 = api(
                "POST",
                f"/quotes/bulk",
                {"action": "mark_sent", "ids": [quote["id"]]},
            )
            st3, d3 = api(
                "POST",
                f"/quotes/bulk",
                {"action": "approve", "ids": [quote["id"]]},
            )
            entry["marked"] = {
                "mark_sent": st2,
                "approve": st3,
            }
            report["marked"].append(entry["productive_id"])

        report["created"].append(entry)
        existing[pid] = quote
        time.sleep(0.08)

    out = BASE / "report_quotes_import.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(
        json.dumps(
            {
                "created": len(report["created"]),
                "skipped_existing": len(report["skipped_existing"]),
                "skipped_no_client": len(report["skipped_no_client"]),
                "errors": len(report["errors"]),
                "approved_attempts": len(report["marked"]),
                "report": str(out),
            },
            indent=2,
        )
    )
    if report["errors"][:3]:
        print("ERRORS", json.dumps(report["errors"][:3], indent=2)[:2000])
    if report["skipped_no_client"]:
        print(
            "NO CLIENT",
            json.dumps(report["skipped_no_client"], indent=2, ensure_ascii=False),
        )


if __name__ == "__main__":
    main()

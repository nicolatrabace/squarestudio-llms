#!/usr/bin/env python3
"""Import remaining invoices from fatture_productive.json (idempotent)."""

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

TAX_MAP = {
    "TVA LUX": ("LUX", 17.0),
    "LUX": ("LUX", 17.0),
    "EXO": ("EXO", 0.0),
}

# Invoice company_name typos → client productive_id / name aliases
NAME_ALIASES = {
    "omer poizner": "omer pozner",
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


def list_all(path: str, status: str | None = None):
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


def map_tax(tax_name, tax_rate_pct):
    name = (tax_name or "").strip()
    if name in TAX_MAP:
        return TAX_MAP[name]
    if tax_rate_pct is not None and float(tax_rate_pct) == 17.0:
        return "LUX", 17.0
    if tax_rate_pct is not None and float(tax_rate_pct) == 0.0:
        return "EXO", 0.0
    if name:
        return name, float(tax_rate_pct or 0)
    return "", float(tax_rate_pct or 0)


def build_line_items(src_lines):
    items = []
    for li in src_lines or []:
        tax_name, tax_rate = map_tax(li.get("tax_name"), li.get("tax_rate_pct"))
        items.append(
            {
                "product_key": "",
                "notes": li.get("description") or "",
                "cost": float(li.get("unit_price") or 0),
                "quantity": float(li.get("quantity") or 0),
                "tax_name1": tax_name,
                "tax_rate1": tax_rate,
                "discount": 0,
                "is_amount_discount": True,
            }
        )
    return items


def index_clients(clients):
    by_pid = {}
    by_name = {}
    for c in clients:
        pid = (c.get("custom_value1") or "").strip()
        if pid:
            by_pid[pid] = c
        name = (c.get("name") or "").strip().lower()
        if name:
            by_name[name] = c
        notes = c.get("private_notes") or ""
        # productive_id: XXX in notes
        for line in notes.splitlines():
            if line.startswith("productive_id:"):
                by_pid[line.split(":", 1)[1].strip()] = c
    return by_pid, by_name


def resolve_client(src, by_pid, by_name):
    pid = str(src.get("company_productive_id") or "").strip()
    if pid and pid in by_pid:
        return by_pid[pid], "productive_id"
    name = (src.get("company_name") or "").strip().lower()
    name = NAME_ALIASES.get(name, name)
    if name in by_name:
        return by_name[name], "name"
    return None, None


def main():
    currency_map = json.load(open(BASE / "schema" / "currency_map.json"))
    sources = json.load(open(BASE / "fatture_productive.json"))
    sources.sort(
        key=lambda x: (
            x.get("company_name") or "",
            x.get("invoiced_on") or "",
            x.get("number") or "",
        )
    )

    clients = list_all("/clients", status="active")
    by_pid, by_name = index_clients(clients)
    existing_invoices = list_all("/invoices")
    existing_by_number = {}
    for inv in existing_invoices:
        if inv.get("is_deleted"):
            continue
        key = ((inv.get("number") or "").strip(), inv.get("client_id"))
        existing_by_number[key] = inv
        # also track by number alone for reporting
        existing_by_number.setdefault(("__num__", (inv.get("number") or "").strip()), inv)

    report = {
        "created": [],
        "skipped": [],
        "errors": [],
        "warnings": [],
        "source_total": len(sources),
    }

    for src in sources:
        number = (src.get("number") or "").strip()
        company = src.get("company_name")
        if not number:
            report["errors"].append(
                {"company": company, "error": "missing number", "productive_id": src.get("productive_id")}
            )
            continue

        if src.get("number_is_fictitious"):
            report["skipped"].append(
                {
                    "number": number,
                    "company": company,
                    "reason": "fictitious_number_needs_nicola_confirmation",
                    "productive_id": src.get("productive_id"),
                    "amount_total": src.get("amount_total"),
                }
            )
            report["warnings"].append(
                {
                    "number": number,
                    "company": company,
                    "warning": "SKIPPED fictitious number — confirm before import",
                }
            )
            print(f"SKIP {company} {number} fictitious — needs confirmation")
            continue

        client, how = resolve_client(src, by_pid, by_name)
        if not client:
            report["errors"].append(
                {
                    "number": number,
                    "company": company,
                    "company_productive_id": src.get("company_productive_id"),
                    "error": "client_not_found",
                }
            )
            print(f"ERROR {company} {number}: client not found")
            continue

        key = (number, client["id"])
        if key in existing_by_number:
            report["skipped"].append(
                {
                    "number": number,
                    "company": company,
                    "client_id": client["id"],
                    "reason": "already_exists",
                    "existing_id": existing_by_number[key]["id"],
                }
            )
            print(f"SKIP {company} {number} already exists")
            continue

        currency = src.get("currency") or "EUR"
        if currency not in currency_map:
            report["errors"].append(
                {"number": number, "company": company, "error": f"unmapped currency {currency}"}
            )
            continue

        line_items = build_line_items(src.get("line_items"))
        if not line_items:
            report["errors"].append(
                {"number": number, "company": company, "error": "no line items"}
            )
            continue

        payload = {
            "client_id": client["id"],
            "number": number,
            "date": src.get("invoiced_on"),
            "due_date": src.get("pay_on") or "",
            "po_number": src.get("purchase_order_number") or "",
            "public_notes": src.get("subject") or "",
            "private_notes": (
                f"productive_id: {src.get('productive_id')}\n"
                f"subject: {src.get('subject') or ''}\n"
                f"company_match: {how}"
            ),
            "custom_value1": str(src.get("productive_id") or ""),
            "line_items": line_items,
        }

        st, resp = api("POST", "/invoices", payload)
        if st not in (200, 201):
            report["errors"].append(
                {
                    "number": number,
                    "company": company,
                    "status": st,
                    "response": resp,
                }
            )
            print(f"ERROR create {company} {number}: {st} {json.dumps(resp)[:400]}")
            continue

        inv = resp["data"]
        iid = inv["id"]
        existing_by_number[key] = inv

        st_s, resp_s = api("POST", "/invoices/bulk", {"action": "mark_sent", "ids": [iid]})
        if st_s not in (200, 201):
            report["errors"].append(
                {"number": number, "company": company, "error": "mark_sent_failed", "response": resp_s}
            )
            print(f"ERROR mark_sent {number}")
            continue

        st_g, invd = api("GET", f"/invoices/{iid}")
        inv = invd["data"]
        created_amount = float(inv.get("amount") or 0)
        expected_total = float(src.get("amount_total") or 0)
        amount_ok = abs(created_amount - expected_total) < 0.02

        payment_id = None
        if src.get("payment_status") == "paid":
            pay_amount = float(src.get("amount_paid") or expected_total)
            pay_date = src.get("paid_on") or src.get("invoiced_on")
            st_p, pay = api(
                "POST",
                "/payments",
                {
                    "client_id": client["id"],
                    "amount": pay_amount,
                    "date": pay_date,
                    "payment_type_id": "1",
                    "private_notes": f"productive_invoice_id: {src.get('productive_id')}",
                    "invoices": [{"invoice_id": iid, "amount": pay_amount}],
                },
            )
            if st_p not in (200, 201):
                report["errors"].append(
                    {
                        "number": number,
                        "company": company,
                        "error": "payment_failed",
                        "status": st_p,
                        "response": pay,
                    }
                )
                print(f"ERROR payment {company} {number}: {st_p}")
            else:
                payment_id = pay["data"]["id"]

        st_g, invd = api("GET", f"/invoices/{iid}")
        inv = invd["data"]
        entry = {
            "number": number,
            "company": company,
            "client_name": client.get("name"),
            "client_id": client["id"],
            "invoice_ninja_id": iid,
            "status_id": inv.get("status_id"),
            "amount": inv.get("amount"),
            "balance": inv.get("balance"),
            "paid_to_date": inv.get("paid_to_date"),
            "expected_total": expected_total,
            "amount_match": amount_ok,
            "source_payment_status": src.get("payment_status"),
            "payment_id": payment_id,
            "currency": currency,
        }
        if not amount_ok:
            report["warnings"].append(
                {
                    "number": number,
                    "company": company,
                    "warning": f"amount mismatch IN={created_amount} vs source={expected_total}",
                }
            )
        report["created"].append(entry)
        print(
            f"OK  {company} {number} amount={inv.get('amount')} bal={inv.get('balance')} "
            f"paid={inv.get('paid_to_date')} status={inv.get('status_id')} match={amount_ok}"
        )
        time.sleep(0.15)

    out = BASE / "report_invoices_rest.json"
    json.dump(report, open(out, "w"), indent=2, ensure_ascii=False)
    print("\n=== SUMMARY ===")
    print(
        f"created={len(report['created'])} skipped={len(report['skipped'])} "
        f"errors={len(report['errors'])} warnings={len(report['warnings'])}"
    )
    print(f"report: {out}")
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

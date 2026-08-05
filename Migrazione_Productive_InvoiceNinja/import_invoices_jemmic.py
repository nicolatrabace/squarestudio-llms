#!/usr/bin/env python3
"""Stage 3a: import jemmic invoices only (test), with payments when paid."""

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

# Productive tax label → Invoice Ninja tax_name1 / rate
TAX_MAP = {
    "TVA LUX": ("LUX", 17.0),
    "LUX": ("LUX", 17.0),
    "EXO": ("EXO", 0.0),
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


def map_tax(tax_name: str | None, tax_rate_pct):
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


def build_line_items(src_lines: list) -> list:
    items = []
    for li in src_lines:
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


def find_client_jemmic(clients):
    for c in clients:
        if (c.get("name") or "").strip().lower() == "jemmic":
            return c
        if (c.get("custom_value1") or "").strip() == "1194238":
            return c
    return None


def existing_invoice_numbers_for_client(invoices, client_id):
    return {
        (inv.get("number") or "").strip()
        for inv in invoices
        if inv.get("client_id") == client_id and not inv.get("is_deleted")
    }


def main():
    currency_map = json.load(open(BASE / "schema" / "currency_map.json"))
    sources = [
        i
        for i in json.load(open(BASE / "fatture_productive.json"))
        if (i.get("company_name") or "").lower() == "jemmic"
        or str(i.get("company_productive_id")) == "1194238"
    ]
    sources.sort(key=lambda x: (x.get("invoiced_on") or "", x.get("number") or ""))

    clients = list_all("/clients", status="active")
    jemmic = find_client_jemmic(clients)
    if not jemmic:
        raise SystemExit("jemmic client not found in Invoice Ninja")

    existing_invoices = list_all("/invoices")  # includes all statuses
    existing_numbers = existing_invoice_numbers_for_client(
        existing_invoices, jemmic["id"]
    )

    report = {
        "client": {
            "name": jemmic["name"],
            "id": jemmic["id"],
            "vat_number": jemmic.get("vat_number"),
        },
        "created": [],
        "skipped": [],
        "errors": [],
        "warnings": [],
        "source_count": len(sources),
    }

    print(
        f"jemmic id={jemmic['id']} vat={jemmic.get('vat_number')!r} "
        f"source_invoices={len(sources)}"
    )

    for src in sources:
        number = (src.get("number") or "").strip()
        if not number:
            report["errors"].append(
                {"productive_id": src.get("productive_id"), "error": "missing number"}
            )
            continue
        if src.get("number_is_fictitious"):
            report["warnings"].append(
                {
                    "number": number,
                    "warning": "number_is_fictitious=true — ask Nicola before using",
                }
            )
            # For jemmic all are false, but refuse fictitious in this test
            report["skipped"].append(
                {"number": number, "reason": "fictitious_number_needs_confirmation"}
            )
            print(f"SKIP {number} fictitious")
            continue
        if number in existing_numbers:
            report["skipped"].append({"number": number, "reason": "already_exists"})
            print(f"SKIP {number} already exists")
            continue

        currency = src.get("currency") or "EUR"
        currency_id = currency_map.get(currency)
        if not currency_id:
            report["errors"].append(
                {"number": number, "error": f"unmapped currency {currency}"}
            )
            continue

        line_items = build_line_items(src.get("line_items") or [])
        if not line_items:
            report["errors"].append({"number": number, "error": "no line items"})
            continue

        notes_parts = [
            f"productive_id: {src.get('productive_id')}",
            f"subject: {src.get('subject') or ''}",
        ]
        payload = {
            "client_id": jemmic["id"],
            "number": number,
            "date": src.get("invoiced_on"),
            "due_date": src.get("pay_on") or "",
            "po_number": src.get("purchase_order_number") or "",
            "public_notes": src.get("subject") or "",
            "private_notes": "\n".join(notes_parts),
            "custom_value1": str(src.get("productive_id") or ""),
            "line_items": line_items,
            # Ensure client currency context; IN derives from client usually
        }

        st, resp = api("POST", "/invoices", payload)
        if st not in (200, 201):
            report["errors"].append(
                {"number": number, "status": st, "response": resp, "payload": payload}
            )
            print(f"ERROR create {number}: {st} {json.dumps(resp)[:500]}")
            continue

        inv = resp["data"]
        iid = inv["id"]
        existing_numbers.add(number)

        # Mark sent (needed so balance is due and payments apply)
        st_s, resp_s = api("POST", "/invoices/bulk", {"action": "mark_sent", "ids": [iid]})
        if st_s not in (200, 201):
            report["errors"].append(
                {"number": number, "error": "mark_sent_failed", "response": resp_s}
            )
            print(f"ERROR mark_sent {number}: {st_s}")
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
                    "client_id": jemmic["id"],
                    "amount": pay_amount,
                    "date": pay_date,
                    "payment_type_id": "1",  # Bank Transfer
                    "private_notes": f"productive_invoice_id: {src.get('productive_id')}",
                    "invoices": [{"invoice_id": iid, "amount": pay_amount}],
                },
            )
            if st_p not in (200, 201):
                report["errors"].append(
                    {
                        "number": number,
                        "error": "payment_failed",
                        "status": st_p,
                        "response": pay,
                    }
                )
                print(f"ERROR payment {number}: {st_p} {json.dumps(pay)[:400]}")
            else:
                payment_id = pay["data"]["id"]

        st_g, invd = api("GET", f"/invoices/{iid}")
        inv = invd["data"]
        entry = {
            "number": number,
            "invoice_ninja_id": iid,
            "status_id": inv.get("status_id"),
            "amount": inv.get("amount"),
            "balance": inv.get("balance"),
            "paid_to_date": inv.get("paid_to_date"),
            "date": inv.get("date"),
            "due_date": inv.get("due_date"),
            "expected_total": expected_total,
            "amount_match": amount_ok,
            "source_payment_status": src.get("payment_status"),
            "payment_id": payment_id,
            "tax_on_lines": [
                (li.get("tax_name1"), li.get("tax_rate1"), li.get("tax_amount"))
                for li in inv.get("line_items") or []
            ],
        }
        if not amount_ok:
            report["warnings"].append(
                {
                    "number": number,
                    "warning": f"amount mismatch IN={created_amount} vs source={expected_total}",
                }
            )
        report["created"].append(entry)
        print(
            f"OK  {number} amount={inv.get('amount')} balance={inv.get('balance')} "
            f"paid_to_date={inv.get('paid_to_date')} status={inv.get('status_id')} "
            f"match={amount_ok} paid={bool(payment_id)}"
        )
        time.sleep(0.2)

    out = BASE / "report_invoices_jemmic.json"
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

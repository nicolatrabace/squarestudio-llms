#!/usr/bin/env python3
"""Stage: idempotent expense import from expense_productive.json → Invoice Ninja."""

from __future__ import annotations

import os
import json
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime
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


def parse_date(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10])
    except Exception:
        return None


def find_duplicate_suspects(sources):
    groups = defaultdict(list)
    for e in sources:
        key = (
            (e.get("name") or e.get("description") or "").strip().lower(),
            round(float(e.get("amount_with_tax") or 0), 2),
            e.get("currency"),
        )
        groups[key].append(e)
    suspects = []
    for items in groups.values():
        if len(items) < 2:
            continue
        items = sorted(items, key=lambda x: x.get("date") or "")
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                d1, d2 = parse_date(items[i].get("date")), parse_date(
                    items[j].get("date")
                )
                if d1 and d2 and abs((d2 - d1).days) <= 7:
                    suspects.append(
                        {
                            "name": items[i].get("name"),
                            "amount": items[i].get("amount_with_tax"),
                            "currency": items[i].get("currency"),
                            "date_a": items[i].get("date"),
                            "date_b": items[j].get("date"),
                            "days_apart": abs((d2 - d1).days),
                            "productive_id_a": items[i].get("productive_id"),
                            "productive_id_b": items[j].get("productive_id"),
                            "vendor_a": items[i].get("vendor_name"),
                            "vendor_b": items[j].get("vendor_name"),
                        }
                    )
    return suspects


def main():
    currency_map = json.load(open(BASE / "schema" / "currency_map.json"))
    sources = json.load(open(BASE / "expense_productive.json"))

    vendors = list_all("/vendors", status="active")
    by_vpid = {}
    by_vname = {}
    for v in vendors:
        pid = (v.get("custom_value1") or "").strip()
        if pid:
            by_vpid[pid] = v
        notes = v.get("private_notes") or ""
        for line in notes.splitlines():
            if line.startswith("productive_id:"):
                by_vpid[line.split(":", 1)[1].strip()] = v
        name = (v.get("name") or "").strip().lower()
        if name:
            by_vname[name] = v

    existing = list_all("/expenses", status="active") + list_all(
        "/expenses", status="archived"
    )
    existing_by_pid = {}
    for e in existing:
        pid = (e.get("custom_value1") or "").strip()
        if pid:
            existing_by_pid[pid] = e
        notes = e.get("private_notes") or ""
        for line in notes.splitlines():
            if line.startswith("productive_id:"):
                existing_by_pid[line.split(":", 1)[1].strip()] = e

    report = {
        "created": [],
        "skipped": [],
        "errors": [],
        "warnings": [],
        "vendor_unmatched": [],
        "duplicate_suspects": find_duplicate_suspects(sources),
        "source_total": len(sources),
    }

    print(f"Source expenses: {len(sources)}")
    print(f"Existing expenses: {len(existing)}")
    print(f"Duplicate suspects: {len(report['duplicate_suspects'])}")

    unmatched_vendor_names = set()

    for src in sources:
        pid = str(src.get("productive_id") or "")
        if not pid:
            report["errors"].append({"error": "missing productive_id", "src": src})
            continue
        if pid in existing_by_pid:
            report["skipped"].append(
                {
                    "productive_id": pid,
                    "name": src.get("name"),
                    "reason": "already_exists",
                    "existing_id": existing_by_pid[pid]["id"],
                }
            )
            continue

        currency = src.get("currency") or "EUR"
        currency_id = currency_map.get(currency)
        if not currency_id:
            report["errors"].append(
                {
                    "productive_id": pid,
                    "name": src.get("name"),
                    "error": f"unmapped currency {currency}",
                }
            )
            continue

        vendor_id = ""
        vendor_how = None
        vpid = str(src.get("vendor_productive_id") or "").strip()
        vname = (src.get("vendor_name") or "").strip()
        if vpid and vpid in by_vpid:
            vendor_id = by_vpid[vpid]["id"]
            vendor_how = "vendor_productive_id"
        elif vname and vname.lower() in by_vname:
            vendor_id = by_vname[vname.lower()]["id"]
            vendor_how = "vendor_name"
        elif vname:
            unmatched_vendor_names.add(vname)
            report["vendor_unmatched"].append(
                {
                    "productive_id": pid,
                    "name": src.get("name"),
                    "vendor_name": vname,
                    "vendor_productive_id": vpid or None,
                }
            )

        amount = float(src.get("amount_with_tax") or src.get("amount") or 0)
        notes = [
            f"productive_id: {pid}",
            f"productive_name: {src.get('name') or ''}",
        ]
        if src.get("description") and src.get("description") != src.get("name"):
            notes.append(f"description: {src.get('description')}")
        if vname:
            notes.append(f"vendor_name_source: {vname}")
        if vendor_how:
            notes.append(f"vendor_match: {vendor_how}")
        elif vname:
            notes.append("vendor_match: NONE (imported without vendor_id)")
        if src.get("invoiced"):
            notes.append("invoiced_in_productive: true")
        if src.get("reimbursable"):
            notes.append("reimbursable: true")

        payload = {
            "amount": amount,
            "currency_id": str(currency_id),
            "date": (src.get("date") or "")[:10],
            "payment_date": (src.get("date") or "")[:10],
            "public_notes": src.get("name") or src.get("description") or "",
            "private_notes": "\n".join(notes),
            "custom_value1": pid,
            "should_be_invoiced": bool(src.get("invoiced")),
            "uses_inclusive_taxes": True,
        }
        if vendor_id:
            payload["vendor_id"] = vendor_id

        st, resp = api("POST", "/expenses", payload)
        if st not in (200, 201):
            report["errors"].append(
                {
                    "productive_id": pid,
                    "name": src.get("name"),
                    "status": st,
                    "response": resp,
                }
            )
            print(f"ERROR {src.get('name')!r}: {st} {json.dumps(resp)[:300]}")
            continue

        created = resp["data"]
        existing_by_pid[pid] = created
        entry = {
            "productive_id": pid,
            "invoice_ninja_id": created["id"],
            "number": created.get("number"),
            "name": src.get("name"),
            "amount": created.get("amount"),
            "currency_id": created.get("currency_id"),
            "vendor_id": created.get("vendor_id") or "",
            "vendor_name": vname or None,
            "vendor_matched": bool(vendor_id),
            "invoiced": bool(src.get("invoiced")),
            "date": created.get("date"),
        }
        report["created"].append(entry)
        print(
            f"OK  {created.get('number')} {src.get('name')!r} "
            f"amount={created.get('amount')} vendor={vname or '-'} matched={bool(vendor_id)}"
        )
        time.sleep(0.08)

    # dedupe unmatched list for summary
    report["vendor_unmatched_unique"] = sorted(unmatched_vendor_names)

    out = BASE / "report_expenses_import.json"
    json.dump(report, open(out, "w"), indent=2, ensure_ascii=False)
    print("\n=== SUMMARY ===")
    print(
        f"created={len(report['created'])} skipped={len(report['skipped'])} "
        f"errors={len(report['errors'])} "
        f"vendor_unmatched_rows={len(report['vendor_unmatched'])} "
        f"duplicate_suspects={len(report['duplicate_suspects'])}"
    )
    print("unmatched vendors:", report["vendor_unmatched_unique"])
    print(f"report: {out}")
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

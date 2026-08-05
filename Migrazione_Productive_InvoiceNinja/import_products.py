#!/usr/bin/env python3
"""Stage: idempotent product/rate import from servizi_e_tariffe_productive.json."""

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
    for line in (entity.get("notes") or "").splitlines():
        if line.startswith("productive_id:"):
            return line.split(":", 1)[1].strip()
    return ""


def product_key(svc: dict) -> str:
    company = (svc.get("company_name") or "Client").strip()
    name = (svc.get("name") or "Service").strip()
    key = f"{company} — {name}"
    if len(key) > 100:
        key = key[:97] + "..."
    return key


def main():
    services = json.load(open(BASE / "servizi_e_tariffe_productive.json"))
    existing = {}
    for status in ("active", "archived"):
        for p in list_all("/products", status=status):
            pid = extract_pid(p)
            if pid:
                existing[pid] = p

    report = {"created": [], "skipped_existing": [], "errors": []}

    for svc in services:
        pid = str(svc.get("productive_id") or "")
        if pid in existing:
            report["skipped_existing"].append(
                {
                    "productive_id": pid,
                    "invoice_ninja_id": existing[pid]["id"],
                    "product_key": existing[pid].get("product_key"),
                }
            )
            continue

        unit = (svc.get("unit") or "").strip()
        qty = float(svc.get("quantity") or 1) or 1
        price = float(svc.get("unit_price") or 0)
        notes_parts = [
            (svc.get("description") or "").strip(),
            f"Unità: {unit}" if unit else "",
            f"Deal: {svc.get('deal_name')}" if svc.get("deal_name") else "",
            f"Cliente Productive: {svc.get('company_name')}",
            f"productive_id: {pid}",
            f"deal_id: {svc.get('deal_id')}",
        ]
        notes = "\n".join(p for p in notes_parts if p)

        body = {
            "product_key": product_key(svc),
            "notes": notes,
            "price": price,
            "cost": price,
            "quantity": qty,
            "custom_value1": pid,
            "custom_value2": str(svc.get("company_id") or ""),
            "custom_value3": unit,
            "custom_value4": str(svc.get("deal_id") or ""),
        }

        st, d = api("POST", "/products", body)
        if st in (200, 201):
            p = d["data"]
            report["created"].append(
                {
                    "productive_id": pid,
                    "invoice_ninja_id": p["id"],
                    "product_key": p.get("product_key"),
                    "price": price,
                    "company": svc.get("company_name"),
                }
            )
            existing[pid] = p
        else:
            report["errors"].append(
                {
                    "productive_id": pid,
                    "name": svc.get("name"),
                    "status": st,
                    "error": d,
                }
            )
        time.sleep(0.05)

    out = BASE / "report_products_import.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(
        json.dumps(
            {
                "created": len(report["created"]),
                "skipped_existing": len(report["skipped_existing"]),
                "errors": len(report["errors"]),
                "report": str(out),
            },
            indent=2,
        )
    )
    if report["errors"][:3]:
        print("ERRORS", json.dumps(report["errors"][:3], indent=2)[:1500])


if __name__ == "__main__":
    main()

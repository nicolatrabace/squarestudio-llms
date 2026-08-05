#!/usr/bin/env python3
"""Stage: append Productive budgets into client private_notes (idempotent)."""

from __future__ import annotations

import os
import json
import time
import urllib.error
import urllib.request
from collections import defaultdict
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

MARKER_BEGIN = "=== BUDGET PRODUCTIVE ==="
MARKER_END = "=== FINE BUDGET PRODUCTIVE ==="

# Productive company_name → Invoice Ninja client name
ALIASES = {
    "omer poizner": "Omer Pozner",
    "jemmic": "jemmic",
    "ristorante la caserma": "Ristorante La Caserma",
    "the arc / flourishlab": "The Arc / FlourishLab",
    "april™": "April™",
    "seadog design": "Seadog Design",
    "tinkr": None,  # skip — no client / cancelled
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


def fmt_money(v, currency="EUR"):
    try:
        return f"{float(v):,.2f} {currency}".replace(",", "X").replace(".", ",").replace(
            "X", "."
        )
    except Exception:
        return f"{v} {currency}"


def strip_old_block(notes: str) -> str:
    if MARKER_BEGIN not in notes:
        return notes.rstrip()
    before, rest = notes.split(MARKER_BEGIN, 1)
    if MARKER_END in rest:
        _, after = rest.split(MARKER_END, 1)
        return (before.rstrip() + "\n" + after.lstrip()).strip()
    return before.rstrip()


def main():
    budgets = json.load(open(BASE / "budget_clienti.json"))
    clients = list_all("/clients", status="active")
    by_name = {c["name"].strip().lower(): c for c in clients}
    by_pid = {}
    for c in clients:
        cv = (c.get("custom_value1") or "").strip()
        if cv:
            by_pid[cv] = c
        for line in (c.get("private_notes") or "").splitlines():
            if line.startswith("productive_id:"):
                by_pid[line.split(":", 1)[1].strip()] = c

    grouped: dict[str, list] = defaultdict(list)
    skipped = []
    for b in budgets:
        cname = (b.get("company_name") or "").strip()
        key = cname.lower()
        if key in ALIASES and ALIASES[key] is None:
            skipped.append({"budget": b.get("name"), "reason": "excluded client", "company": cname})
            continue
        target = ALIASES.get(key, cname)
        if target is None:
            continue
        grouped[str(target)].append(b)

    report = {"updated": [], "skipped": skipped, "errors": [], "unmatched": []}

    for client_name, items in grouped.items():
        client = by_name.get(client_name.lower())
        if not client:
            # try company_id from first budget
            cid = str(items[0].get("company_id") or "")
            client = by_pid.get(cid)
        if not client:
            report["unmatched"].append(
                {"client": client_name, "budgets": [i.get("name") for i in items]}
            )
            continue

        lines = [MARKER_BEGIN, "Budget da Productive (riferimento; Invoice Ninja non ha modulo budget):", ""]
        total = 0.0
        for b in sorted(items, key=lambda x: (x.get("date") or "", x.get("name") or "")):
            amount = float(b.get("budget_total") or b.get("deal_value_total") or 0)
            total += amount
            cur = b.get("currency") or "EUR"
            period = ""
            if b.get("date") or b.get("end_date"):
                period = f" | {b.get('date') or '?'} → {b.get('end_date') or 'open'}"
            note = ""
            # DSK correction
            if "dsk" in (b.get("name") or "").lower() and amount == 38016:
                note = " (totale periodo 2025-2026 biennale, NON annuale)"
            lines.append(
                f"- {b.get('name')}: {fmt_money(amount, cur)}{period}{note} [pid:{b.get('id')}]"
            )
        lines.append("")
        lines.append(f"Totale elenco: {fmt_money(total)}")
        lines.append(MARKER_END)

        block = "\n".join(lines)
        base_notes = strip_old_block(client.get("private_notes") or "")
        new_notes = (base_notes + "\n\n" + block).strip() if base_notes else block

        st, d = api("PUT", f"/clients/{client['id']}", {"private_notes": new_notes})
        if st in (200, 201):
            report["updated"].append(
                {
                    "client": client["name"],
                    "client_id": client["id"],
                    "budgets": len(items),
                    "total": total,
                }
            )
        else:
            report["errors"].append(
                {"client": client_name, "status": st, "error": d}
            )
        time.sleep(0.05)

    out = BASE / "report_budgets_notes.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(
        json.dumps(
            {
                "updated": len(report["updated"]),
                "skipped": len(report["skipped"]),
                "unmatched": len(report["unmatched"]),
                "errors": len(report["errors"]),
                "report": str(out),
            },
            indent=2,
        )
    )
    if report["unmatched"]:
        print("UNMATCHED", json.dumps(report["unmatched"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

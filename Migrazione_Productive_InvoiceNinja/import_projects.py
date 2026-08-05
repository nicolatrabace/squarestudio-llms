#!/usr/bin/env python3
"""Stage: idempotent project import from progetti_productive.json → Invoice Ninja."""

from __future__ import annotations

import os
import json
import re
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

# Explicit safe aliases: cleaned project name → client name in Invoice Ninja
SAFE_ALIASES = {
    "jemmic": "jemmic",
    "flourishlab": "The Arc / FlourishLab",
    "la caserma": "Ristorante La Caserma",
    "margin health - project": "Margin Health",
    "margin health": "Margin Health",
    "michael jennings - framer website": "Michael Jennings",
    "omer poizner": "Omer Pozner",
    "unicraft": "Unicraft VC",
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


def clean_project_name(name: str) -> str:
    name = (name or "").strip()
    name = re.sub(r"\s*\[Project\]\s*$", "", name, flags=re.I).strip()
    return name


def should_exclude(src: dict, cleaned: str) -> str | None:
    ptype = (src.get("project_type") or "").lower()
    cl = cleaned.lower()
    original = (src.get("name") or "").strip().lower()

    if ptype == "internal" and cl == "square studio":
        return "internal: Square Studio"
    if ptype == "internal" and cl == "tinkr":
        return "internal: TINKR (import only TINKR [Project])"
    if ptype == "internal" and cl == "test":
        return "internal: Test"
    # test projects by name (even if tagged client)
    if cl in {"deal test", "test 2", "test 3", "test"} or re.search(
        r"\btest\b", original
    ):
        # careful: don't exclude "latest" etc. — \btest\b is fine
        # But "TINKR [Project]" has no test. Good.
        # "Deal test", "Test 2", "Test 3", "Test" covered.
        if "test" in cl:
            return f"test project: {src.get('name')}"
    return None


def resolve_client(cleaned: str, by_name: dict):
    """Return (client, match_reason) or (None, None)."""
    key = cleaned.lower()
    if key in by_name:
        return by_name[key], "exact_name"
    if key in SAFE_ALIASES:
        target = SAFE_ALIASES[key].lower()
        if target in by_name:
            return by_name[target], f"alias:{SAFE_ALIASES[key]}"
    return None, None


def find_existing_project(projects, productive_id: str, name: str, client_id: str):
    pid = str(productive_id or "")
    for p in projects:
        if pid and (p.get("custom_value1") or "").strip() == pid:
            return p, "custom_value1"
        notes = p.get("private_notes") or ""
        if pid and f"productive_id: {pid}" in notes:
            return p, "notes"
        if (
            (p.get("name") or "").strip().lower() == name.strip().lower()
            and p.get("client_id") == client_id
        ):
            return p, "name+client"
    return None, None


def main():
    sources = json.load(open(BASE / "progetti_productive.json"))
    clients = list_all("/clients", status="active")
    by_name = {(c.get("name") or "").strip().lower(): c for c in clients}

    # Include archived projects in existence check too
    existing = list_all("/projects", status="active") + list_all(
        "/projects", status="archived"
    )
    # dedupe by id
    seen_ids = set()
    existing_unique = []
    for p in existing:
        if p["id"] not in seen_ids:
            seen_ids.add(p["id"])
            existing_unique.append(p)
    existing = existing_unique

    report = {
        "created": [],
        "skipped_existing": [],
        "excluded": [],
        "manual_assignment": [],
        "errors": [],
        "archived_after_create": [],
    }

    print(f"Active clients: {len(clients)} | Existing projects: {len(existing)}")
    print(f"Source projects: {len(sources)}")

    for src in sources:
        raw_name = src.get("name") or ""
        cleaned = clean_project_name(raw_name)
        pid = str(src.get("productive_id") or "")

        excl = should_exclude(src, cleaned)
        if excl:
            report["excluded"].append(
                {
                    "name": raw_name,
                    "cleaned": cleaned,
                    "productive_id": pid,
                    "reason": excl,
                }
            )
            print(f"EXCLUDE {raw_name!r} — {excl}")
            continue

        client, how = resolve_client(cleaned, by_name)
        if not client:
            report["manual_assignment"].append(
                {
                    "name": raw_name,
                    "cleaned": cleaned,
                    "productive_id": pid,
                    "project_type": src.get("project_type"),
                    "archived_at": src.get("archived_at"),
                    "reason": "no_safe_client_match",
                }
            )
            print(f"MANUAL {raw_name!r} (clean={cleaned!r}) — no safe client match")
            continue

        existing_p, why = find_existing_project(
            existing, pid, cleaned, client["id"]
        )
        if existing_p:
            report["skipped_existing"].append(
                {
                    "name": raw_name,
                    "cleaned": cleaned,
                    "productive_id": pid,
                    "existing_id": existing_p["id"],
                    "reason": why,
                }
            )
            print(f"SKIP {cleaned!r} already exists via {why}")
            continue

        notes = [
            f"productive_id: {pid}",
            f"productive_name: {raw_name}",
            f"project_type: {src.get('project_type')}",
            f"client_match: {how}",
        ]
        if src.get("number") is not None:
            notes.append(f"productive_number: {src.get('number')}")
        if src.get("archived_at"):
            notes.append(f"productive_archived_at: {src.get('archived_at')}")

        payload = {
            "name": cleaned,
            "client_id": client["id"],
            "custom_value1": pid,
            "private_notes": "\n".join(notes),
        }

        st, resp = api("POST", "/projects", payload)
        if st not in (200, 201):
            report["errors"].append(
                {
                    "name": raw_name,
                    "cleaned": cleaned,
                    "status": st,
                    "response": resp,
                }
            )
            print(f"ERROR {cleaned!r}: {st} {json.dumps(resp)[:400]}")
            continue

        created = resp["data"]
        existing.append(created)
        entry = {
            "name": cleaned,
            "source_name": raw_name,
            "productive_id": pid,
            "invoice_ninja_id": created["id"],
            "number": created.get("number"),
            "client_id": client["id"],
            "client_name": client.get("name"),
            "match": how,
            "archived": False,
        }

        if src.get("archived_at"):
            st_a, _ = api(
                "POST", "/projects/bulk", {"action": "archive", "ids": [created["id"]]}
            )
            if st_a in (200, 201):
                entry["archived"] = True
                report["archived_after_create"].append(cleaned)
            else:
                report["errors"].append(
                    {
                        "name": cleaned,
                        "error": "archive_failed",
                        "status": st_a,
                    }
                )

        report["created"].append(entry)
        print(
            f"OK  {cleaned!r} → client={client.get('name')!r} id={created['id']} "
            f"num={created.get('number')} archived={entry['archived']} via={how}"
        )
        time.sleep(0.12)

    out = BASE / "report_projects_import.json"
    json.dump(report, open(out, "w"), indent=2, ensure_ascii=False)
    print("\n=== SUMMARY ===")
    print(
        f"created={len(report['created'])} "
        f"skipped_existing={len(report['skipped_existing'])} "
        f"excluded={len(report['excluded'])} "
        f"manual={len(report['manual_assignment'])} "
        f"errors={len(report['errors'])}"
    )
    if report["manual_assignment"]:
        print("\nDa assegnare a mano:")
        for m in report["manual_assignment"]:
            print(f"  - {m['name']} (clean={m['cleaned']}, pid={m['productive_id']})")
    print(f"report: {out}")
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

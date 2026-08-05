#!/usr/bin/env python3
"""Stage 1: idempotent client import Productive JSON → Invoice Ninja."""

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

PLACEHOLDER_VATS = {"123456789", "1234567890"}


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


def list_clients(status: str | None = "active"):
    out = []
    page = 1
    while True:
        q = f"/clients?per_page=100&page={page}"
        if status:
            q += f"&status={status}"
        st, d = api("GET", q)
        if st != 200:
            raise RuntimeError(f"list clients failed {st} {d}")
        out.extend(d["data"])
        if page >= d["meta"]["pagination"]["total_pages"]:
            break
        page += 1
    return out


def map_size(estimated_employees):
    if estimated_employees is None:
        return ""
    try:
        n = int(estimated_employees)
    except (TypeError, ValueError):
        return ""
    if n <= 3:
        return "1"
    if n <= 10:
        return "2"
    if n <= 50:
        return "3"
    if n <= 100:
        return "4"
    if n <= 500:
        return "5"
    return "6"


def map_industry(apollo_industry: str | None, industry_map: dict):
    if not apollo_industry:
        return ""
    key = apollo_industry.strip().lower()
    # direct
    if key in industry_map:
        return industry_map[key]
    # fuzzy contains
    for name, iid in industry_map.items():
        if key in name or name in key:
            return iid
    # common apollo → IN mappings
    aliases = {
        "marketing & advertising": "advertising",
        "information technology & services": "computers & hightech",
        "computer software": "computers & hightech",
        "financial services": "banking & finance",
        "management consulting": "business services",
        "design": "business services",
        "internet": "computers & hightech",
    }
    alias = aliases.get(key)
    if alias and alias in industry_map:
        return industry_map[alias]
    return ""


def clean_vat(vat):
    if vat is None:
        return "", False
    vat = str(vat).strip()
    if not vat or vat in PLACEHOLDER_VATS:
        return "", bool(vat)
    return vat, False


def build_private_notes(src: dict, fake_vat: bool) -> str:
    parts = []
    parts.append(f"productive_id: {src.get('productive_id')}")
    if src.get("company_code"):
        parts.append(f"company_code: {src['company_code']}")
    if src.get("productive_type_tag"):
        parts.append("productive_tags: " + ", ".join(src["productive_type_tag"]))
    if src.get("tag_list"):
        parts.append("tags: " + ", ".join(src["tag_list"]))
    billing = src.get("billing_name")
    if billing and billing != src.get("name"):
        parts.append(f"billing_name: {billing}")
    if fake_vat:
        parts.append(
            "ATTENZIONE: partita IVA placeholder Productive '123456789' non importata"
        )
    notes = src.get("notes") or []
    for n in notes:
        if n:
            parts.append(f"nota: {n}")
    apollo = src.get("apollo_enrichment") or {}
    if apollo:
        bits = []
        if apollo.get("industry"):
            bits.append(f"industry={apollo['industry']}")
        if apollo.get("estimated_employees") is not None:
            bits.append(f"employees≈{apollo['estimated_employees']}")
        if apollo.get("founded_year"):
            bits.append(f"founded={apollo['founded_year']}")
        if apollo.get("linkedin_url"):
            bits.append(f"linkedin={apollo['linkedin_url']}")
        if apollo.get("description"):
            bits.append(f"desc={apollo['description']}")
        if bits:
            parts.append("apollo: " + " | ".join(bits))
    return "\n".join(parts)


def build_contacts(src: dict) -> list:
    contacts = []
    named = src.get("named_contacts") or []
    emails = list(src.get("emails") or [])
    phone = (src.get("phones") or [None])[0] or ""

    used_emails = set()
    for i, nc in enumerate(named):
        email = (nc.get("email") or "").strip()
        if email:
            used_emails.add(email.lower())
        contacts.append(
            {
                "first_name": nc.get("first_name") or "",
                "last_name": nc.get("last_name") or "",
                "email": email,
                "phone": phone if i == 0 else "",
                "is_primary": i == 0,
                "send_email": False,
            }
        )

    # remaining emails as additional contacts
    for j, email in enumerate(emails):
        email = (email or "").strip()
        if not email or email.lower() in used_emails:
            continue
        used_emails.add(email.lower())
        contacts.append(
            {
                "first_name": "",
                "last_name": "",
                "email": email,
                "phone": phone if not contacts else "",
                "is_primary": len(contacts) == 0,
                "send_email": False,
            }
        )

    if not contacts:
        # Invoice Ninja requires at least one contact
        contacts.append(
            {
                "first_name": "",
                "last_name": "",
                "email": "",
                "phone": phone,
                "is_primary": True,
                "send_email": False,
            }
        )
    else:
        # ensure primary
        if not any(c.get("is_primary") for c in contacts):
            contacts[0]["is_primary"] = True
        if phone and not any(c.get("phone") for c in contacts):
            contacts[0]["phone"] = phone

    return contacts


def build_payload(src: dict, currency_map: dict, country_map: dict, industry_map: dict):
    vat, fake_vat = clean_vat(src.get("vat"))
    addr = (src.get("addresses") or [None])[0] or {}
    country_name = addr.get("country")
    country_id = ""
    if country_name:
        country_id = str(country_map.get(country_name) or "")
        if not country_id:
            raise ValueError(f"Unmapped country: {country_name!r} for {src.get('name')}")

    currency_code = src.get("default_currency")
    currency_id = ""
    if currency_code:
        currency_id = str(currency_map.get(currency_code) or "")
        if not currency_id:
            raise ValueError(
                f"Unmapped currency: {currency_code!r} for {src.get('name')}"
            )

    apollo = src.get("apollo_enrichment") or {}
    settings = {}
    if currency_id:
        settings["currency_id"] = currency_id
    due_days = src.get("due_days")
    if due_days is not None and due_days != "":
        settings["payment_terms"] = str(int(due_days))

    industry_id = map_industry(apollo.get("industry"), industry_map)
    size_id = map_size(apollo.get("estimated_employees"))
    if industry_id:
        settings["industry_id"] = industry_id
    if size_id:
        settings["size_id"] = size_id

    websites = src.get("websites") or []
    website = websites[0] if websites else ""
    if not website and src.get("domain"):
        website = f"https://{src['domain']}"

    display_name = src.get("name") or ""
    # If billing_name differs, keep legal/display as name; note billing in private_notes
    payload = {
        "name": src.get("name") or "",
        "display_name": display_name,
        "vat_number": vat,
        "website": website or "",
        "phone": (src.get("phones") or [""])[0] or "",
        "address1": addr.get("address") or "",
        "city": addr.get("city") or "",
        "state": addr.get("state") or "",
        "postal_code": addr.get("zipcode") or "",
        "country_id": country_id,
        "private_notes": build_private_notes(src, fake_vat),
        "custom_value1": str(src.get("productive_id") or ""),
        "contacts": build_contacts(src),
        "settings": settings,
    }
    return payload, fake_vat


def find_existing(active_clients, src):
    pid = str(src.get("productive_id") or "")
    name = (src.get("name") or "").strip().lower()
    for c in active_clients:
        if pid and (c.get("custom_value1") or "").strip() == pid:
            return c, "productive_id"
        notes = c.get("private_notes") or ""
        if pid and f"productive_id: {pid}" in notes:
            return c, "notes_productive_id"
        if (c.get("name") or "").strip().lower() == name:
            return c, "name"
    return None, None


def main():
    currency_map = json.load(open(BASE / "schema" / "currency_map.json"))
    country_map = json.load(open(BASE / "schema" / "country_map.json"))
    industry_map = json.load(open(BASE / "schema" / "industry_map.json"))
    sources = json.load(open(BASE / "clienti_e_lead.json"))

    print(f"Active clients before import: {len(list_clients('active'))}")
    active = list_clients("active")

    report = {
        "created": [],
        "skipped": [],
        "errors": [],
        "warnings": [],
    }

    for src in sources:
        name = src.get("name")
        existing, reason = find_existing(active, src)
        if existing:
            report["skipped"].append(
                {
                    "name": name,
                    "productive_id": src.get("productive_id"),
                    "existing_id": existing["id"],
                    "reason": reason,
                }
            )
            print(f"SKIP {name} (already exists via {reason}: {existing['id']})")
            continue

        try:
            payload, fake_vat = build_payload(
                src, currency_map, country_map, industry_map
            )
        except ValueError as e:
            report["errors"].append({"name": name, "error": str(e)})
            print(f"ERROR build {name}: {e}")
            continue

        if fake_vat:
            report["warnings"].append(
                {"name": name, "warning": "placeholder VAT skipped"}
            )
        if not src.get("default_currency"):
            report["warnings"].append(
                {"name": name, "warning": "no default_currency, company default used"}
            )

        st, resp = api("POST", "/clients", payload)
        if st not in (200, 201):
            report["errors"].append(
                {"name": name, "status": st, "response": resp, "payload": payload}
            )
            print(f"ERROR create {name}: {st} {json.dumps(resp)[:500]}")
            continue

        created = resp["data"]
        active.append(created)
        entry = {
            "name": name,
            "productive_id": src.get("productive_id"),
            "invoice_ninja_id": created["id"],
            "number": created.get("number"),
            "vat_number": created.get("vat_number"),
            "currency_id": (created.get("settings") or {}).get("currency_id"),
            "country_id": created.get("country_id"),
            "contacts": [
                {
                    "email": c.get("email"),
                    "first_name": c.get("first_name"),
                    "last_name": c.get("last_name"),
                }
                for c in created.get("contacts", [])
            ],
        }
        report["created"].append(entry)
        print(
            f"OK  {name} → id={created['id']} number={created.get('number')} "
            f"vat={created.get('vat_number')!r} curr={entry['currency_id']}"
        )
        time.sleep(0.15)

    out_path = BASE / "report_clients_import.json"
    json.dump(report, open(out_path, "w"), indent=2, ensure_ascii=False)
    print("\n=== SUMMARY ===")
    print(
        f"created={len(report['created'])} skipped={len(report['skipped'])} "
        f"errors={len(report['errors'])} warnings={len(report['warnings'])}"
    )
    print(f"report: {out_path}")
    return 0 if not report["errors"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

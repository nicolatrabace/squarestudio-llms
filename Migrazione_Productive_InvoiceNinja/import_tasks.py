#!/usr/bin/env python3
"""Stage: idempotent task import from task_productive.json → Invoice Ninja."""

from __future__ import annotations

import os
import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
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

EXCLUDE_PROJECT_IDS = {
    "789324",  # Square Studio
    "799225",  # TINKR
    "799226",  # TINKR [Project]
    "794696",  # Deal test
    "800098",  # Test
    "794697",  # Test 2
    "794706",  # Test 3
    "793085",  # Design system
}

EXCLUDE_NAME_RE = re.compile(
    r"^(square studio|tinkr|deal test|test(?:\s*[23])?|design system)(\s*\[project\])?$",
    re.I,
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


def parse_ts(s: str | None) -> int | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except Exception:
        return None


def build_time_log(task: dict) -> str:
    minutes = int(task.get("worked_minutes") or 0)
    if minutes <= 0:
        return "[]"
    end = parse_ts(task.get("closed_at")) or parse_ts(
        (task.get("due_date") or "") + "T17:00:00+00:00"
    )
    if not end:
        end = int(time.time())
    start = max(0, end - minutes * 60)
    return json.dumps([[start, end, "", True]])


def extract_productive_id(entity: dict) -> str:
    cv = (entity.get("custom_value1") or "").strip()
    if cv:
        return cv
    notes = entity.get("private_notes") or ""
    for line in notes.splitlines():
        if line.startswith("productive_id:"):
            return line.split(":", 1)[1].strip()
    return ""


def main():
    sources = json.load(open(BASE / "task_productive.json"))
    proj_report = json.load(open(BASE / "report_projects_import.json"))

    status_map = {s["name"].lower(): s["id"] for s in list_all("/task_statuses")}
    done_id = status_map.get("done")
    backlog_id = status_map.get("backlog") or status_map.get("ready to do")

    # Map Productive project id → IN project
    by_ppid: dict[str, dict] = {}
    for row in proj_report.get("created", []):
        by_ppid[str(row["productive_id"])] = {
            "id": row["invoice_ninja_id"],
            "client_id": row["client_id"],
            "name": row["name"],
        }
    for row in proj_report.get("manual_resolved", []):
        # need client_id from live project
        st, d = api("GET", f"/projects/{row['id']}")
        if st == 200:
            p = d["data"]
            by_ppid[str(row["productive_id"])] = {
                "id": p["id"],
                "client_id": p["client_id"],
                "name": p["name"],
            }

    # Also scan live projects for productive_id in notes (covers archived)
    for status in ("active", "archived"):
        for p in list_all("/projects", status=status):
            pid = extract_productive_id(p)
            if pid and pid not in by_ppid:
                by_ppid[pid] = {
                    "id": p["id"],
                    "client_id": p["client_id"],
                    "name": p["name"],
                }

    existing = {}
    for status in ("active", "archived"):
        for t in list_all("/tasks", status=status):
            pid = extract_productive_id(t)
            if pid:
                existing[pid] = t

    report = {
        "created": [],
        "skipped_existing": [],
        "skipped_excluded": [],
        "skipped_no_project": [],
        "errors": [],
    }

    for src in sources:
        ppid = str(src.get("productive_id") or "")
        project_id = str(src.get("project_id") or "")
        pname = (src.get("project_name") or "").strip()

        if project_id in EXCLUDE_PROJECT_IDS or EXCLUDE_NAME_RE.match(
            re.sub(r"\s*\[Project\]\s*$", "", pname, flags=re.I).strip()
        ) or EXCLUDE_NAME_RE.match(pname):
            report["skipped_excluded"].append(
                {"productive_id": ppid, "title": src.get("title"), "project": pname}
            )
            continue

        if ppid in existing:
            report["skipped_existing"].append(
                {
                    "productive_id": ppid,
                    "invoice_ninja_id": existing[ppid]["id"],
                    "title": src.get("title"),
                }
            )
            continue

        proj = by_ppid.get(project_id)
        if not proj:
            report["skipped_no_project"].append(
                {
                    "productive_id": ppid,
                    "title": src.get("title"),
                    "project_id": project_id,
                    "project_name": pname,
                }
            )
            continue

        status_id = done_id if src.get("closed") else backlog_id
        body = {
            "client_id": proj["client_id"],
            "project_id": proj["id"],
            "description": (src.get("title") or "").strip() or f"Task {ppid}",
            "custom_value1": ppid,
            "status_id": status_id,
            "time_log": build_time_log(src),
            "date": (src.get("due_date") or src.get("closed_at") or "")[:10] or None,
            "private_notes": (
                f"productive_id: {ppid}\n"
                f"productive_project_id: {project_id}\n"
                f"productive_project: {pname}\n"
                f"closed: {bool(src.get('closed'))}\n"
                f"worked_minutes: {src.get('worked_minutes')}\n"
                f"billable_minutes: {src.get('billable_minutes')}"
            ),
        }
        # drop None date
        if not body["date"]:
            del body["date"]

        st, d = api("POST", "/tasks", body)
        if st in (200, 201):
            t = d["data"]
            report["created"].append(
                {
                    "productive_id": ppid,
                    "invoice_ninja_id": t["id"],
                    "number": t.get("number"),
                    "title": body["description"],
                    "project": proj["name"],
                    "closed": bool(src.get("closed")),
                    "worked_minutes": src.get("worked_minutes") or 0,
                }
            )
            existing[ppid] = t
        else:
            report["errors"].append(
                {"productive_id": ppid, "title": src.get("title"), "status": st, "error": d}
            )
        time.sleep(0.05)

    out = BASE / "report_tasks_import.json"
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(
        json.dumps(
            {
                "created": len(report["created"]),
                "skipped_existing": len(report["skipped_existing"]),
                "skipped_excluded": len(report["skipped_excluded"]),
                "skipped_no_project": len(report["skipped_no_project"]),
                "errors": len(report["errors"]),
                "report": str(out),
            },
            indent=2,
        )
    )
    if report["errors"][:3]:
        print("SAMPLE ERRORS", json.dumps(report["errors"][:3], indent=2)[:1500])
    if report["skipped_no_project"][:5]:
        print(
            "NO PROJECT",
            json.dumps(report["skipped_no_project"][:5], indent=2, ensure_ascii=False),
        )


if __name__ == "__main__":
    main()

"""Render a CI tool's JSON output as a self-contained HTML report.

ruff and pip-audit have no HTML output of their own; mypy, bandit and pytest do and
are not handled here. Standard library only, so CI can run it with plain `python`.

    python scripts/ci_html_report.py ruff      reports/ruff.json      reports/lint.html
    python scripts/ci_html_report.py pip-audit reports/pip-audit.json reports/dependencies.html
"""

from __future__ import annotations

import json
import sys
from html import escape
from pathlib import Path

CSS = """
body{font:14px/1.5 system-ui,sans-serif;margin:2rem;color:#1f2328}
h1{font-size:1.4rem;margin:0 0 .25rem}
.ok{color:#1a7f37}.bad{color:#cf222e}
table{border-collapse:collapse;width:100%;margin-top:1rem}
th,td{border:1px solid #d0d7de;padding:.35rem .6rem;text-align:left;vertical-align:top}
th{background:#f6f8fa}code{font-size:13px}
"""


def page(title: str, summary: str, ok: bool, headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{escape(c)}</td>" for c in r) + "</tr>" for r in rows)
    table = f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>" if rows else ""
    cls = "ok" if ok else "bad"
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{escape(title)}</title>"
        f"<style>{CSS}</style></head><body><h1>{escape(title)}</h1>"
        f"<p class='{cls}'>{escape(summary)}</p>{table}</body></html>"
    )


def ruff(data: list[dict]) -> str:
    rows = [
        [
            f"{d['filename'].split('/backend/')[-1]}:{d['location']['row']}",
            d.get("code") or "",
            d["message"],
        ]
        for d in data
    ]
    summary = "No lint findings." if not rows else f"{len(rows)} lint finding(s)."
    return page("Backend lint (ruff)", summary, not rows, ["Location", "Rule", "Message"], rows)


def pip_audit(data: dict) -> str:
    deps = data.get("dependencies", [])
    rows = [
        [d["name"], d["version"], v["id"], ", ".join(v.get("fix_versions", [])) or "none"]
        for d in deps
        for v in d.get("vulns", [])
    ]
    summary = (
        f"{len(deps)} packages audited, no known vulnerabilities."
        if not rows
        else f"{len(deps)} packages audited, {len(rows)} known vulnerability(ies)."
    )
    return page(
        "Backend dependency audit (pip-audit)",
        summary,
        not rows,
        ["Package", "Version", "Advisory", "Fixed in"],
        rows,
    )


RENDERERS = {"ruff": ruff, "pip-audit": pip_audit}


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[1] not in RENDERERS:
        print(__doc__, file=sys.stderr)
        return 2
    kind, src, dst = sys.argv[1:]
    path = Path(src)
    if not path.exists() or not path.read_text().strip():
        print(f"{src} missing or empty: the tool did not run to completion", file=sys.stderr)
        return 1
    Path(dst).write_text(RENDERERS[kind](json.loads(path.read_text())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

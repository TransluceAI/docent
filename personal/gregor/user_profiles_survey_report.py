#!/usr/bin/env python3
"""
Internal report: export onboarding / survey responses from `user_profiles`.

This intentionally does NOT add any REST endpoints. It connects directly to Postgres
using the existing `DocentDB` configuration and renders either:
- a self-contained HTML file (recommended for browsing), or
- a CSV suitable for analysis.

Usage:
  source .venv/bin/activate
  export DOCENT_PG_HOST=...
  export DOCENT_PG_PORT=...
  export DOCENT_PG_USER=...
  export DOCENT_PG_PASSWORD=...
  export DOCENT_PG_DATABASE=docent

  python scripts/user_profiles_survey_report.py --format html --out /tmp/user_profiles.html
  python scripts/user_profiles_survey_report.py --format csv  --out /tmp/user_profiles.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from html import escape as html_escape
from pathlib import Path
from typing import Any, Iterable, Sequence, cast

import anyio
from sqlalchemy import Select, select

from docent_core._db_service.db import DocentDB
from docent_core.docent.db.schemas.tables import SQLAUser, SQLAUserProfile


@dataclass(frozen=True)
class _MultiSelect:
    selected: tuple[str, ...]
    other: tuple[str, ...]

    def all_values(self) -> tuple[str, ...]:
        return tuple(v for v in (*self.selected, *self.other) if v)


def _parse_iso_datetime(value: str) -> datetime:
    """
    Parse ISO-ish timestamps used in query args.
    Supports plain `YYYY-MM-DD` (treated as midnight) and full ISO strings.
    """
    value = value.strip()
    if len(value) == 10:
        return datetime.fromisoformat(value)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _normalize_multiselect(value: Any) -> _MultiSelect:
    if value is None:
        return _MultiSelect(selected=(), other=())
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return _MultiSelect(selected=(), other=())
    if not isinstance(value, dict):
        return _MultiSelect(selected=(), other=())

    raw = cast(dict[str, Any], value)
    selected_raw = raw.get("selected")
    other_raw = raw.get("other")

    selected_list: Sequence[Any]
    other_list: Sequence[Any]
    if selected_raw is None:
        selected_list = ()
    elif isinstance(selected_raw, list):
        selected_list = cast(list[Any], selected_raw)
    else:
        return _MultiSelect(selected=(), other=())

    if other_raw is None:
        other_list = ()
    elif isinstance(other_raw, list):
        other_list = cast(list[Any], other_raw)
    else:
        return _MultiSelect(selected=(), other=())

    def _clean(items: Sequence[Any]) -> tuple[str, ...]:
        out: list[str] = []
        for it in items:
            if isinstance(it, str):
                s = it.strip()
                if s:
                    out.append(s)
        return tuple(out)

    return _MultiSelect(selected=_clean(selected_list), other=_clean(other_list))


def _safe_str(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    return str(v)


def _maybe_redact_email(email: str, *, redact_email: bool) -> str:
    if not redact_email:
        return email
    if "@" not in email:
        return "<redacted>"
    _, domain = email.split("@", 1)
    return f"<redacted>@{domain}"


def _build_query(
    *, since: datetime | None, until: datetime | None, limit: int
) -> Select[tuple[SQLAUserProfile, str]]:
    stmt = (
        select(SQLAUserProfile, SQLAUser.email)
        .join(SQLAUser, SQLAUser.id == SQLAUserProfile.user_id)
        .order_by(SQLAUserProfile.created_at.desc())
        .limit(limit)
    )
    if since is not None:
        stmt = stmt.where(SQLAUserProfile.created_at >= since)
    if until is not None:
        stmt = stmt.where(SQLAUserProfile.created_at <= until)
    return stmt


@dataclass(frozen=True)
class _Row:
    created_at: datetime
    updated_at: datetime
    user_id: str
    email: str
    institution: str
    task: str
    help_type: str
    discovery_source: str
    frameworks: _MultiSelect
    providers: _MultiSelect


def _to_row(profile: SQLAUserProfile, *, email: str, redact_email: bool) -> _Row:
    return _Row(
        created_at=profile.created_at,
        updated_at=profile.updated_at,
        user_id=profile.user_id,
        email=_maybe_redact_email(email, redact_email=redact_email),
        institution=_safe_str(profile.institution).strip(),
        task=_safe_str(profile.task).strip(),
        help_type=_safe_str(profile.help_type).strip(),
        discovery_source=_safe_str(profile.discovery_source).strip(),
        frameworks=_normalize_multiselect(profile.frameworks),
        providers=_normalize_multiselect(profile.providers),
    )


def _write_csv(rows: Sequence[_Row], *, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "created_at",
                "updated_at",
                "user_id",
                "email",
                "institution",
                "task",
                "help_type",
                "discovery_source",
                "frameworks_selected",
                "frameworks_other",
                "providers_selected",
                "providers_other",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r.created_at.isoformat(),
                    r.updated_at.isoformat(),
                    r.user_id,
                    r.email,
                    r.institution,
                    r.task,
                    r.help_type,
                    r.discovery_source,
                    ", ".join(r.frameworks.selected),
                    ", ".join(r.frameworks.other),
                    ", ".join(r.providers.selected),
                    ", ".join(r.providers.other),
                ]
            )


def _render_counts(title: str, counter: Counter[str]) -> str:
    if not counter:
        return f"<h3>{html_escape(title)}</h3><div class='muted'>No data</div>"
    items = "\n".join(
        f"<tr><td class='mono'>{html_escape(k)}</td><td class='num'>{v}</td></tr>"
        for k, v in counter.most_common()
    )
    return (
        f"<h3>{html_escape(title)}</h3>"
        "<table class='counts'><thead><tr><th>Value</th><th>Count</th></tr></thead>"
        f"<tbody>{items}</tbody></table>"
    )


def _format_cell(text: str) -> str:
    if not text:
        return "<span class='muted'>—</span>"
    return f"<div class='cell'>{html_escape(text)}</div>"


def _format_list(values: Iterable[str]) -> str:
    cleaned: list[str] = [v for v in values if v]
    if not cleaned:
        return "<span class='muted'>—</span>"
    items = "".join(f"<li>{html_escape(v)}</li>" for v in cleaned)
    return f"<ul class='list'>{items}</ul>"


def _write_html(rows: Sequence[_Row], *, out_path: Path, title: str) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    framework_counts = Counter(v for r in rows for v in r.frameworks.all_values())
    provider_counts = Counter(v for r in rows for v in r.providers.all_values())
    discovery_counts = Counter(r.discovery_source for r in rows if r.discovery_source)
    institution_counts = Counter(r.institution for r in rows if r.institution)

    body_rows: list[str] = []
    for r in rows:
        body_rows.append(
            "<tr>"
            f"<td class='mono'>{html_escape(r.created_at.isoformat(sep=' ', timespec='seconds'))}</td>"
            f"<td class='mono'>{html_escape(r.email)}</td>"
            f"<td>{_format_cell(r.institution)}</td>"
            f"<td>{_format_cell(r.task)}</td>"
            f"<td>{_format_cell(r.help_type)}</td>"
            f"<td>{_format_cell(r.discovery_source)}</td>"
            f"<td>{_format_list(r.frameworks.selected)}</td>"
            f"<td>{_format_list(r.frameworks.other)}</td>"
            f"<td>{_format_list(r.providers.selected)}</td>"
            f"<td>{_format_list(r.providers.other)}</td>"
            "</tr>"
        )

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{html_escape(title)}</title>
  <style>
    :root {{
      --bg: #0b0f14;
      --fg: #e8eef6;
      --muted: #9fb0c3;
      --card: #121a23;
      --border: #223043;
      --accent: #7aa2f7;
    }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial;
      background: var(--bg);
      color: var(--fg);
    }}
    .wrap {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
    h1 {{ font-size: 20px; margin: 0 0 12px; }}
    h2 {{ font-size: 16px; margin: 24px 0 10px; }}
    h3 {{ font-size: 14px; margin: 16px 0 8px; color: var(--muted); }}
    .row {{ display: grid; gap: 16px; grid-template-columns: 1fr 1fr; }}
    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
    }}
    .muted {{ color: var(--muted); }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; }}
    .toolbar {{
      display: flex;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      margin: 10px 0 14px;
    }}
    input[type="search"] {{
      width: min(520px, 100%);
      padding: 10px 12px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: #0f1620;
      color: var(--fg);
      outline: none;
    }}
    input[type="search"]:focus {{
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(122, 162, 247, 0.15);
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 12px;
    }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 8px 10px;
      vertical-align: top;
    }}
    th {{
      position: sticky;
      top: 0;
      background: #0f1620;
      text-align: left;
      z-index: 2;
    }}
    .cell {{ white-space: pre-wrap; line-height: 1.35; }}
    .list {{ margin: 0; padding-left: 18px; }}
    .counts th, .counts td {{ padding: 6px 10px; }}
    .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    .meta {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
    }}
    .pill {{
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 4px 10px;
      background: #0f1620;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>{html_escape(title)}</h1>
    <div class="toolbar">
      <input id="q" type="search" placeholder="Filter rows (institution/task/help/framework/provider/email/source)…" />
      <div class="meta">
        <span class="pill">rows: <span class="mono" id="rowCount">{len(rows)}</span></span>
        <span class="pill">generated: <span class="mono">{html_escape(datetime.now().isoformat(sep=' ', timespec='seconds'))}</span></span>
      </div>
    </div>

    <div class="row">
      <div class="card">{_render_counts("Frameworks (selected + other)", framework_counts)}</div>
      <div class="card">{_render_counts("Providers (selected + other)", provider_counts)}</div>
    </div>
    <div class="row">
      <div class="card">{_render_counts("Discovery source", discovery_counts)}</div>
      <div class="card">{_render_counts("Institution", institution_counts)}</div>
    </div>

    <h2>Responses</h2>
    <div class="card" style="overflow:auto; max-height: 70vh;">
      <table id="t">
        <thead>
          <tr>
            <th>Created</th>
            <th>Email</th>
            <th>Institution</th>
            <th>Task</th>
            <th>Help type</th>
            <th>Discovery source</th>
            <th>Frameworks (selected)</th>
            <th>Frameworks (other)</th>
            <th>Providers (selected)</th>
            <th>Providers (other)</th>
          </tr>
        </thead>
        <tbody>
          {"".join(body_rows)}
        </tbody>
      </table>
    </div>
  </div>

  <script>
    const q = document.getElementById('q');
    const t = document.getElementById('t');
    const rowCount = document.getElementById('rowCount');
    const rows = Array.from(t.querySelectorAll('tbody tr'));

    function norm(s) {{
      return (s || '').toLowerCase();
    }}

    function applyFilter() {{
      const needle = norm(q.value.trim());
      let shown = 0;
      for (const r of rows) {{
        const hay = norm(r.innerText);
        const ok = needle === '' || hay.includes(needle);
        r.style.display = ok ? '' : 'none';
        if (ok) shown += 1;
      }}
      rowCount.textContent = String(shown);
    }}

    q.addEventListener('input', applyFilter);
  </script>
</body>
</html>
"""

    out_path.write_text(html, encoding="utf-8")


async def _run(args: argparse.Namespace) -> None:
    db = await DocentDB.init()
    async with db.session() as session:
        stmt = _build_query(since=args.since, until=args.until, limit=args.limit)
        result = await session.execute(stmt)
        pairs: list[tuple[SQLAUserProfile, str]] = [(row[0], row[1]) for row in result.all()]

    rows: list[_Row] = [
        _to_row(p, email=email, redact_email=args.redact_email) for (p, email) in pairs
    ]

    out_path = Path(args.out).expanduser().resolve()
    title = "Docent user_profiles survey results"
    if args.format == "csv":
        _write_csv(rows, out_path=out_path)
        return
    if args.format == "html":
        _write_html(rows, out_path=out_path, title=title)
        return
    raise ValueError(f"Unsupported format: {args.format}")


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Internal report for user_profiles survey results.")
    p.add_argument("--format", choices=["html", "csv"], default="html")
    p.add_argument("--out", required=True, help="Output path, e.g. /tmp/user_profiles.html")
    p.add_argument("--limit", type=int, default=2000, help="Max rows to export")
    p.add_argument(
        "--since",
        type=_parse_iso_datetime,
        default=None,
        help="Only include rows created_at >= since. Formats: YYYY-MM-DD or ISO timestamp.",
    )
    p.add_argument(
        "--until",
        type=_parse_iso_datetime,
        default=None,
        help="Only include rows created_at <= until. Formats: YYYY-MM-DD or ISO timestamp.",
    )
    p.add_argument(
        "--redact-email",
        action="store_true",
        help="Redact email local-part, leaving only domain.",
    )
    return p.parse_args(argv)


def main() -> None:
    args = _parse_args()
    anyio.run(_run, args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Read-only Git workspace global viewer.

Scans a workspace for Git repositories and renders a Markdown dashboard.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Dict, List

IGNORED_DIRS = {"node_modules", "vendor", ".venv", "dist", "build"}
STALE_DAYS = 90


@dataclass
class RepoStatus:
    name: str
    path: Path
    branch: str
    sync_remote: str
    local_changes: str
    last_commit: str
    has_changes: bool
    is_detached: bool
    is_stale: bool


def to_row(repo: RepoStatus) -> Dict[str, Any]:
    return {
        "name": repo.name,
        "branch": repo.branch,
        "sync_remote": repo.sync_remote,
        "local_changes": repo.local_changes,
        "last_commit": repo.last_commit,
        "has_changes": repo.has_changes,
        "is_detached": repo.is_detached,
        "is_stale": repo.is_stale,
    }


def run_git(repo: Path, args: List[str]) -> tuple[int, str]:
    cmd = ["git", "-C", str(repo), *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    return proc.returncode, out if out else err


def rel_depth(root: Path, current: Path) -> int:
    rel = os.path.relpath(current, root)
    if rel == ".":
        return 0
    return rel.count(os.sep) + 1


def discover_repos(root: Path, max_depth: int) -> List[Path]:
    repos: List[Path] = []
    for current, dirs, _ in os.walk(root):
        cur = Path(current)
        depth = rel_depth(root, cur)
        dirs[:] = [d for d in dirs if d not in IGNORED_DIRS]
        if depth > max_depth:
            dirs[:] = []
            continue
        if ".git" in dirs:
            repos.append(cur)
            dirs[:] = []
    return sorted(repos)


def sync_state(repo: Path) -> str:
    code, _ = run_git(repo, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if code != 0:
        return "No upstream"

    code, out = run_git(repo, ["rev-list", "--left-right", "--count", "@{u}...HEAD"])
    if code != 0 or not out:
        return "Unknown"

    parts = out.split()
    if len(parts) != 2:
        return "Unknown"

    behind, ahead = int(parts[0]), int(parts[1])
    if ahead == 0 and behind == 0:
        return "Up to date"
    if ahead > 0 and behind == 0:
        return f"Ahead {ahead}"
    if behind > 0 and ahead == 0:
        return f"Behind {behind}"
    return f"Diverged A{ahead}/B{behind}"


def working_tree(repo: Path) -> tuple[str, bool]:
    code, out = run_git(repo, ["status", "--porcelain"])
    if code != 0:
        return "Unknown", False

    if not out:
        return "🟢 Limpio", False

    modified = 0
    added = 0
    deleted = 0
    untracked = 0

    for line in out.splitlines():
        if line.startswith("??"):
            untracked += 1
            continue

        x = line[0:1]
        y = line[1:2]
        flags = f"{x}{y}"

        if "D" in flags:
            deleted += 1
        elif "A" in flags:
            added += 1
        else:
            modified += 1

    parts = []
    if modified:
        parts.append(f"🔴 M:{modified}")
    if added:
        parts.append(f"🟠 A:{added}")
    if deleted:
        parts.append(f"🟣 D:{deleted}")
    if untracked:
        parts.append(f"🟡 U:{untracked}")

    return " ".join(parts), True


def last_commit(repo: Path) -> tuple[str, bool]:
    code, out = run_git(
        repo,
        ["log", "-1", '--format=%h - %an (%ar): %s'],
    )
    if code != 0 or not out:
        return "No commits", False

    code_ts, ts = run_git(repo, ["log", "-1", "--format=%ct"])
    is_stale = False
    if code_ts == 0 and ts.isdigit():
        commit_date = dt.datetime.fromtimestamp(int(ts), tz=dt.timezone.utc)
        age_days = (dt.datetime.now(tz=dt.timezone.utc) - commit_date).days
        is_stale = age_days >= STALE_DAYS

    return out, is_stale


def branch_state(repo: Path) -> tuple[str, bool]:
    code, out = run_git(repo, ["branch", "--show-current"])
    if code == 0 and out:
        return out, False

    code, head = run_git(repo, ["rev-parse", "--short", "HEAD"])
    if code == 0 and head:
        return f"DETACHED ({head})", True
    return "Unknown", True


def collect_repo_status(repo: Path, root: Path) -> RepoStatus:
    branch, is_detached = branch_state(repo)
    sync_remote_state = sync_state(repo)
    local_changes, has_changes = working_tree(repo)
    latest_commit, is_stale = last_commit(repo)

    display_name = str(repo.relative_to(root)).replace("\\", "/")
    return RepoStatus(
        name=display_name,
        path=repo,
        branch=branch,
        sync_remote=sync_remote_state,
        local_changes=local_changes,
        last_commit=latest_commit,
        has_changes=has_changes,
        is_detached=is_detached,
        is_stale=is_stale,
    )


def render_dashboard(repos: List[RepoStatus], root: Path, max_depth: int) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        "# Dashboard Global Git",
        "",
        f"- Workspace: `{root}`",
        f"- Profundidad maxima: `{max_depth}`",
        f"- Generado: `{now}`",
        "",
        "| Repositorio | Rama Actual | Sync Remoto | Cambios Locales | Ultimo Commit |",
        "|-------------|-------------|-------------|-----------------|---------------|",
    ]

    for repo in repos:
        lines.append(
            f"| `{repo.name}` | `{repo.branch}` | `{repo.sync_remote}` | {repo.local_changes} | `{repo.last_commit}` |"
        )

    warnings: List[str] = []
    detached = [r for r in repos if r.is_detached]
    dirty = [r for r in repos if r.has_changes]
    stale = [r for r in repos if r.is_stale]

    lines.extend(["", "## Alertas de Atencion", ""])

    if not (detached or dirty or stale):
        lines.append("- Sin alertas criticas")
    else:
        if detached:
            lines.append("- Detached HEAD detectado en:")
            for repo in detached:
                lines.append(f"  - `{repo.name}` ({repo.branch})")

        if dirty:
            lines.append("- Repos con cambios locales sin guardar:")
            for repo in dirty:
                lines.append(f"  - `{repo.name}` -> {repo.local_changes}")

        if stale:
            lines.append(f"- Repos potencialmente desactualizados (>= {STALE_DAYS} dias sin commits):")
            for repo in stale:
                lines.append(f"  - `{repo.name}` -> {repo.last_commit}")

    return "\n".join(lines) + "\n"


def render_html_dashboard(repos: List[RepoStatus], root: Path, max_depth: int) -> str:
        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total = len(repos)
        dirty = len([r for r in repos if r.has_changes])
        detached = len([r for r in repos if r.is_detached])
        stale = len([r for r in repos if r.is_stale])

        rows_json = json.dumps([to_row(r) for r in repos], ensure_ascii=False)
        root_text = escape(str(root))

        return f"""<!doctype html>
<html lang=\"es\">
<head>
    <meta charset=\"utf-8\" />
    <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
    <title>Git Workspace Global Viewer</title>
    <style>
        :root {{
            --bg: #f6f7f9;
            --surface: #ffffff;
            --ink: #1a1f2c;
            --muted: #5b667a;
            --ok: #2f8f4e;
            --warn: #d27a00;
            --bad: #b42318;
            --line: #dbe1ea;
            --shadow: 0 8px 24px rgba(18, 28, 45, 0.08);
        }}

        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: radial-gradient(circle at 15% -10%, #e3f2fd, transparent 30%),
                                    radial-gradient(circle at 90% -5%, #ffe8c7, transparent 25%),
                                    var(--bg);
            color: var(--ink);
        }}

        .wrap {{ max-width: 1400px; margin: 0 auto; padding: 20px; }}
        .header {{
            background: var(--surface);
            border: 1px solid var(--line);
            box-shadow: var(--shadow);
            border-radius: 14px;
            padding: 16px 18px;
        }}
        h1 {{ margin: 0 0 6px; font-size: 1.5rem; }}
        .meta {{ color: var(--muted); font-size: 0.92rem; }}

        .kpis {{
            margin-top: 14px;
            display: grid;
            grid-template-columns: repeat(4, minmax(130px, 1fr));
            gap: 10px;
        }}
        .kpi {{
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 12px;
            padding: 10px 12px;
        }}
        .kpi .n {{ font-size: 1.4rem; font-weight: 700; }}
        .kpi .l {{ color: var(--muted); font-size: 0.82rem; }}

        .toolbar {{
            margin-top: 14px;
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 12px;
            padding: 12px;
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 12px;
            align-items: center;
        }}
        .toolbar input[type=\"search\"] {{
            width: 100%;
            padding: 10px 12px;
            border: 1px solid var(--line);
            border-radius: 10px;
            font-size: 0.95rem;
        }}
        .checks {{ display: flex; gap: 12px; flex-wrap: wrap; color: var(--muted); font-size: 0.9rem; }}

        .table-wrap {{
            margin-top: 14px;
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 12px;
            overflow: auto;
            box-shadow: var(--shadow);
        }}
        table {{ width: 100%; border-collapse: collapse; min-width: 1050px; }}
        th, td {{ text-align: left; padding: 10px 12px; border-bottom: 1px solid #edf1f7; vertical-align: top; }}
        th {{
            position: sticky;
            top: 0;
            z-index: 1;
            background: #f1f4f9;
            font-size: 0.84rem;
            letter-spacing: 0.02em;
            text-transform: uppercase;
            color: #344054;
            cursor: pointer;
            user-select: none;
        }}
        tr:hover td {{ background: #f9fbff; }}

        .badge {{
            display: inline-block;
            border-radius: 999px;
            padding: 3px 8px;
            font-size: 0.75rem;
            border: 1px solid var(--line);
            background: #fff;
            color: var(--muted);
        }}
        .state-ok {{ color: var(--ok); border-color: #b2dfc0; background: #effbf3; }}
        .state-warn {{ color: var(--warn); border-color: #f6d39d; background: #fff8eb; }}
        .state-bad {{ color: var(--bad); border-color: #f2b3ad; background: #fff2f1; }}

        .footer {{ margin: 12px 0 4px; color: var(--muted); font-size: 0.82rem; }}

        @media (max-width: 880px) {{
            .kpis {{ grid-template-columns: repeat(2, minmax(130px, 1fr)); }}
            .toolbar {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class=\"wrap\">
        <section class=\"header\">
            <h1>Git Workspace Global Viewer (Read-Only)</h1>
            <div class=\"meta\">Workspace: {root_text} | Profundidad: {max_depth} | Generado: {escape(now)}</div>
            <div class=\"kpis\">
                <div class=\"kpi\"><div class=\"n\">{total}</div><div class=\"l\">Repos detectados</div></div>
                <div class=\"kpi\"><div class=\"n\">{dirty}</div><div class=\"l\">Con cambios locales</div></div>
                <div class=\"kpi\"><div class=\"n\">{detached}</div><div class=\"l\">Detached HEAD</div></div>
                <div class=\"kpi\"><div class=\"n\">{stale}</div><div class=\"l\">Potencialmente desactualizados</div></div>
            </div>
        </section>

        <section class=\"toolbar\">
            <input id=\"search\" type=\"search\" placeholder=\"Buscar repo, rama, commit o estado...\" />
            <div class=\"checks\">
                <label><input id=\"f-dirty\" type=\"checkbox\" /> Solo con cambios</label>
                <label><input id=\"f-detached\" type=\"checkbox\" /> Solo detached</label>
                <label><input id=\"f-stale\" type=\"checkbox\" /> Solo desactualizados</label>
            </div>
        </section>

        <section class=\"table-wrap\">
            <table id=\"repos-table\">
                <thead>
                    <tr>
                        <th data-key=\"name\">Repositorio</th>
                        <th data-key=\"branch\">Rama Actual</th>
                        <th data-key=\"sync_remote\">Sync Remoto</th>
                        <th data-key=\"local_changes\">Cambios Locales</th>
                        <th data-key=\"last_commit\">Ultimo Commit</th>
                        <th data-key=\"flags\">Alertas</th>
                    </tr>
                </thead>
                <tbody></tbody>
            </table>
        </section>

        <div class=\"footer\">Modo solo lectura: no se ejecutan operaciones mutantes de Git.</div>
    </div>

    <script>
        const rows = {rows_json};
        const tableBody = document.querySelector('#repos-table tbody');
        const searchInput = document.getElementById('search');
        const dirtyFilter = document.getElementById('f-dirty');
        const detachedFilter = document.getElementById('f-detached');
        const staleFilter = document.getElementById('f-stale');

        let sortKey = 'name';
        let sortAsc = true;

        function badgeForSync(text) {{
            const t = text.toLowerCase();
            if (t.includes('up to date')) return '<span class="badge state-ok">Up to date</span>';
            if (t.includes('ahead') || t.includes('behind') || t.includes('diverged')) return `<span class="badge state-warn">${{text}}</span>`;
            return `<span class="badge">${{text}}</span>`;
        }}

        function badgeForChanges(row) {{
            if (!row.has_changes) return '<span class="badge state-ok">🟢 Limpio</span>';
            return `<span class="badge state-bad">${{row.local_changes}}</span>`;
        }}

        function flags(row) {{
            const out = [];
            if (row.is_detached) out.push('<span class="badge state-bad">Detached</span>');
            if (row.is_stale) out.push('<span class="badge state-warn">Stale</span>');
            if (!row.is_detached && !row.is_stale) out.push('<span class="badge state-ok">OK</span>');
            return out.join(' ');
        }}

        function getText(row) {{
            return [row.name, row.branch, row.sync_remote, row.local_changes, row.last_commit].join(' ').toLowerCase();
        }}

        function render() {{
            const q = searchInput.value.trim().toLowerCase();
            const filtered = rows
                .filter(r => !q || getText(r).includes(q))
                .filter(r => !dirtyFilter.checked || r.has_changes)
                .filter(r => !detachedFilter.checked || r.is_detached)
                .filter(r => !staleFilter.checked || r.is_stale)
                .sort((a, b) => {{
                    const av = String(a[sortKey] ?? '').toLowerCase();
                    const bv = String(b[sortKey] ?? '').toLowerCase();
                    if (av < bv) return sortAsc ? -1 : 1;
                    if (av > bv) return sortAsc ? 1 : -1;
                    return 0;
                }});

            tableBody.innerHTML = filtered.map(row => `
                <tr>
                    <td>${{row.name}}</td>
                    <td>${{row.branch}}</td>
                    <td>${{badgeForSync(row.sync_remote)}}</td>
                    <td>${{badgeForChanges(row)}}</td>
                    <td>${{row.last_commit}}</td>
                    <td>${{flags(row)}}</td>
                </tr>
            `).join('');
        }}

        searchInput.addEventListener('input', render);
        dirtyFilter.addEventListener('change', render);
        detachedFilter.addEventListener('change', render);
        staleFilter.addEventListener('change', render);

        document.querySelectorAll('th[data-key]').forEach(th => {{
            th.addEventListener('click', () => {{
                const key = th.getAttribute('data-key');
                if (sortKey === key) sortAsc = !sortAsc;
                else {{ sortKey = key; sortAsc = true; }}
                render();
            }});
        }});

        render();
    </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Global Git workspace read-only viewer")
    parser.add_argument("--root", default=".", help="Workspace root path to scan")
    parser.add_argument("--max-depth", type=int, default=3, help="Max folder depth for .git discovery")
    parser.add_argument("--output", default="dashboard/global-git-dashboard.md", help="Markdown output file")
    parser.add_argument(
        "--html-output",
        default="dashboard/global-git-dashboard.html",
        help="Interactive HTML output file",
    )
    parser.add_argument(
        "--mode",
        choices=["md", "html", "both"],
        default="both",
        help="Output mode (default: both)",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    repos = discover_repos(root, args.max_depth)
    statuses = [collect_repo_status(repo, root) for repo in repos]
    md_dashboard = render_dashboard(statuses, root, args.max_depth)
    html_dashboard = render_html_dashboard(statuses, root, args.max_depth)

    if args.mode in {"md", "both"}:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = Path.cwd() / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(md_dashboard, encoding="utf-8")
        print(md_dashboard)
        print(f"Markdown dashboard written to: {output_path}")

    if args.mode in {"html", "both"}:
        html_path = Path(args.html_output)
        if not html_path.is_absolute():
            html_path = Path.cwd() / html_path
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text(html_dashboard, encoding="utf-8")
        print(f"HTML dashboard written to: {html_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

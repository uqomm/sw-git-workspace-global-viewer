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
from typing import Any, Dict, List, Optional

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
    last_activity_ts: Optional[int]
    history_graph: List[str]
    recent_commits: List[Dict[str, Any]]


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
        "last_activity_ts": repo.last_activity_ts,
        "history_graph": repo.history_graph,
        "recent_commits": repo.recent_commits,
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


def last_commit(repo: Path) -> tuple[str, bool, Optional[int]]:
    code, out = run_git(
        repo,
        ["log", "-1", '--format=%h - %an (%ar): %s'],
    )
    if code != 0 or not out:
        return "No commits", False, None

    code_ts, ts = run_git(repo, ["log", "-1", "--format=%ct"])
    is_stale = False
    commit_ts: Optional[int] = None
    if code_ts == 0 and ts.isdigit():
        commit_ts = int(ts)
        commit_date = dt.datetime.fromtimestamp(commit_ts, tz=dt.timezone.utc)
        age_days = (dt.datetime.now(tz=dt.timezone.utc) - commit_date).days
        is_stale = age_days >= STALE_DAYS

    return out, is_stale, commit_ts


def branch_state(repo: Path) -> tuple[str, bool]:
    code, out = run_git(repo, ["branch", "--show-current"])
    if code == 0 and out:
        return out, False

    code, head = run_git(repo, ["rev-parse", "--short", "HEAD"])
    if code == 0 and head:
        return f"DETACHED ({head})", True
    return "Unknown", True


def collect_history_graph(repo: Path, limit: int) -> List[str]:
    code, out = run_git(
        repo,
        ["log", "--graph", "--decorate", "--oneline", f"--max-count={limit}", "--all"],
    )
    if code != 0 or not out:
        return []
    return out.splitlines()


def collect_recent_commits(repo: Path, limit: int, files_limit: int) -> List[Dict[str, Any]]:
    code, out = run_git(
        repo,
        [
            "log",
            "--all",
            "--date=relative",
            "--pretty=format:%H%x1f%h%x1f%an%x1f%ar%x1f%s%x1f%d",
            f"--max-count={limit}",
        ],
    )
    if code != 0 or not out:
        return []

    commits: List[Dict[str, Any]] = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) < 6:
            continue

        full_hash, short_hash, author, rel_time, subject, refs = parts[:6]
        code_files, files_out = run_git(
            repo,
            ["show", "--name-status", "--pretty=format:", "--max-count=1", full_hash],
        )
        changed_files: List[str] = []
        if code_files == 0 and files_out:
            for fline in files_out.splitlines():
                raw = fline.strip()
                if not raw:
                    continue
                fp = raw.split("\t")
                if len(fp) >= 2:
                    changed_files.append(f"{fp[0]} {fp[-1]}")
                else:
                    changed_files.append(raw)

        commits.append(
            {
                "hash": short_hash,
                "full_hash": full_hash,
                "author": author,
                "rel_time": rel_time,
                "subject": subject,
                "refs": refs.strip(),
                "files": changed_files[:files_limit],
                "files_total": len(changed_files),
            }
        )
    return commits


def collect_repo_status(
    repo: Path,
    root: Path,
    graph_limit: int,
    commit_limit: int,
    commit_files_limit: int,
) -> RepoStatus:
    branch, is_detached = branch_state(repo)
    sync_remote_state = sync_state(repo)
    local_changes, has_changes = working_tree(repo)
    latest_commit, is_stale, last_activity_ts = last_commit(repo)
    history_graph = collect_history_graph(repo, graph_limit)
    recent_commits = collect_recent_commits(repo, commit_limit, commit_files_limit)

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
        last_activity_ts=last_activity_ts,
        history_graph=history_graph,
        recent_commits=recent_commits,
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


def render_html_dashboard(
        repos: List[RepoStatus],
        root: Path,
        max_depth: int,
        auto_refresh_sec: int,
) -> str:
        now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        total = len(repos)
        dirty = len([r for r in repos if r.has_changes])
        detached = len([r for r in repos if r.is_detached])
        stale = len([r for r in repos if r.is_stale])

        rows_json = json.dumps([to_row(r) for r in repos], ensure_ascii=False)
        root_text = escape(str(root))
        default_refresh = max(auto_refresh_sec, 0)

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
            --surface-2: #f8fafc;
            --ink: #162033;
            --muted: #56637a;
            --ok: #1f7a46;
            --warn: #995300;
            --bad: #b42318;
            --line: #d8e0ea;
            --shadow: 0 8px 24px rgba(18, 28, 45, 0.08);
            --bg-grad-a: rgba(145, 200, 255, 0.5);
            --bg-grad-b: rgba(255, 214, 153, 0.45);
            --bg-grad-c: rgba(200, 231, 255, 0.35);
            --panel-grad: linear-gradient(180deg, rgba(255, 255, 255, 0.95), rgba(248, 250, 252, 0.95));
            --header-grad: linear-gradient(120deg, rgba(232, 244, 255, 0.9), rgba(255, 247, 232, 0.9));
            --repo-hover: #f7fbff;
            --repo-active: #eef5ff;
            --repo-active-border: #77a5e8;
            --chip-bg: #ffffff;
            --chip-border: var(--line);
            --ok-bg: #effbf3;
            --ok-border: #86cfa3;
            --warn-bg: #fff8ec;
            --warn-border: #e7be84;
            --bad-bg: #fff2f1;
            --bad-border: #e5a09b;
            --graph-bg: #0f1524;
            --graph-ink: #e5edff;
            --commit-bg: #fff;
            --commit-border: #e8edf5;
        }}

        :root[data-theme='dark'] {{
            --bg: #0b1220;
            --surface: #111a2d;
            --surface-2: #0f1828;
            --ink: #e3ebfb;
            --muted: #9fb0cc;
            --ok: #9ef0c4;
            --warn: #ffd39b;
            --bad: #ffb8b2;
            --line: #25344f;
            --shadow: 0 14px 30px rgba(0, 0, 0, 0.35);
            --bg-grad-a: rgba(42, 101, 186, 0.35);
            --bg-grad-b: rgba(171, 118, 27, 0.22);
            --bg-grad-c: rgba(23, 51, 94, 0.5);
            --panel-grad: linear-gradient(180deg, rgba(17, 26, 45, 0.95), rgba(15, 24, 40, 0.95));
            --header-grad: linear-gradient(120deg, rgba(26, 46, 77, 0.85), rgba(64, 41, 18, 0.55));
            --repo-hover: #16233b;
            --repo-active: #1c3152;
            --repo-active-border: #6a9ae4;
            --chip-bg: #152036;
            --chip-border: #31476a;
            --ok-bg: #173629;
            --ok-border: #2f7556;
            --warn-bg: #3d2b16;
            --warn-border: #8d6630;
            --bad-bg: #3d1d1f;
            --bad-border: #915055;
            --graph-bg: #0a1120;
            --graph-ink: #d2e0ff;
            --commit-bg: #101b2f;
            --commit-border: #2a3b59;
        }}

        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: radial-gradient(circle at 10% -8%, #dcefff, transparent 30%),
                                    radial-gradient(circle at 92% -8%, #ffeccf, transparent 24%),
                                    radial-gradient(circle at 50% 110%, var(--bg-grad-c), transparent 45%),
                                    var(--bg);
            color: var(--ink);
            transition: background-color 220ms ease, color 220ms ease;
        }}

        .wrap {{ max-width: 1600px; margin: 0 auto; padding: 18px; }}
        .header {{
            background: var(--header-grad), var(--surface);
            border: 1px solid var(--line);
            border-radius: 14px;
            box-shadow: var(--shadow);
            padding: 14px 16px;
            backdrop-filter: blur(4px);
        }}
        .header h1 {{ margin: 0; font-size: 1.3rem; }}
        .meta {{ margin-top: 5px; color: var(--muted); font-size: 0.9rem; }}

        .kpis {{ margin-top: 12px; display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 10px; }}
        .kpi {{ background: var(--panel-grad); border: 1px solid var(--line); border-radius: 11px; padding: 8px 10px; }}
        .kpi .n {{ font-size: 1.35rem; font-weight: 700; }}
        .kpi .l {{ color: var(--muted); font-size: 0.8rem; }}

        .toolbar {{
            margin-top: 12px;
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 12px;
            background: var(--panel-grad), var(--surface);
            border: 1px solid var(--line);
            border-radius: 12px;
            padding: 10px;
        }}
        .toolbar input[type=\"search\"] {{
            width: 100%;
            border: 1px solid var(--line);
            border-radius: 9px;
            padding: 12px;
            font-size: 0.93rem;
            min-height: 44px;
        }}
        .checks {{ display: flex; flex-wrap: wrap; gap: 10px; color: var(--muted); font-size: 0.86rem; align-items: center; }}
        .checks label {{ display: inline-flex; align-items: center; gap: 6px; min-height: 44px; }}
        .checks input[type=\"checkbox\"] {{ width: 18px; height: 18px; }}
        .checks select {{ min-height: 44px; border: 1px solid var(--line); border-radius: 9px; background: var(--surface); color: var(--ink); padding: 0 8px; }}

        .layout {{
            margin-top: 12px;
            display: grid;
            grid-template-columns: 320px 1fr 420px;
            gap: 12px;
            min-height: 72vh;
        }}
        .panel {{
            background: var(--panel-grad), var(--surface);
            border: 1px solid var(--line);
            border-radius: 12px;
            box-shadow: var(--shadow);
            overflow: hidden;
            display: flex;
            flex-direction: column;
            min-height: 240px;
        }}
        .panel-title {{
            padding: 10px 12px;
            font-size: 0.83rem;
            text-transform: uppercase;
            letter-spacing: 0.03em;
            color: var(--muted);
            border-bottom: 1px solid var(--line);
            background: var(--surface-2);
        }}
        .panel-body {{ padding: 10px; overflow: auto; flex: 1; }}

        .repo-item {{
            padding: 8px;
            border-radius: 8px;
            border: 1px solid transparent;
            margin-bottom: 6px;
            cursor: pointer;
            background: var(--surface-2);
            min-height: 44px;
            display: flex;
            flex-direction: column;
            justify-content: center;
        }}
        .repo-item:hover {{ border-color: var(--line); background: var(--repo-hover); }}
        .repo-item.active {{ border-color: var(--repo-active-border); background: var(--repo-active); }}
        .repo-name {{ font-size: 0.9rem; font-weight: 600; }}
        .repo-meta {{ margin-top: 3px; color: var(--muted); font-size: 0.78rem; }}

        .badge {{
            display: inline-block;
            border-radius: 999px;
            padding: 2px 7px;
            font-size: 0.74rem;
            border: 1px solid var(--chip-border);
            background: var(--chip-bg);
            color: var(--muted);
            margin-right: 4px;
        }}
        .state-ok {{ color: var(--ok); border-color: var(--ok-border); background: var(--ok-bg); }}
        .state-warn {{ color: var(--warn); border-color: var(--warn-border); background: var(--warn-bg); }}
        .state-bad {{ color: var(--bad); border-color: var(--bad-border); background: var(--bad-bg); }}

        .graph {{
            margin-top: 6px;
            font-family: Consolas, 'Courier New', monospace;
            font-size: 0.78rem;
            background: var(--graph-bg);
            color: var(--graph-ink);
            border-radius: 8px;
            padding: 8px;
            max-height: 220px;
            overflow: auto;
            white-space: pre;
        }}

        .commit-item {{
            border: 1px solid var(--commit-border);
            border-radius: 8px;
            padding: 8px;
            margin-top: 8px;
            cursor: pointer;
            background: var(--commit-bg);
            min-height: 44px;
        }}
        .commit-item.active {{ border-color: var(--repo-active-border); background: var(--repo-active); }}
        .commit-head {{ font-family: Consolas, 'Courier New', monospace; font-size: 0.8rem; color: var(--ink); }}
        .commit-subj {{ margin-top: 2px; font-size: 0.86rem; }}
        .commit-meta {{ margin-top: 2px; color: var(--muted); font-size: 0.75rem; }}

        .files-list {{ margin-top: 8px; font-family: Consolas, 'Courier New', monospace; font-size: 0.78rem; }}
        .file-row {{ padding: 2px 0; border-bottom: 1px dashed var(--line); }}

        input:focus-visible,
        select:focus-visible,
        .repo-item:focus-visible,
        .commit-item:focus-visible {{
            outline: 3px solid var(--repo-active-border);
            outline-offset: 2px;
        }}

        .footer {{ margin-top: 8px; color: var(--muted); font-size: 0.8rem; }}

        @media (max-width: 1280px) {{ .layout {{ grid-template-columns: 280px 1fr; }} .panel.right {{ grid-column: 1 / -1; }} }}
        @media (max-width: 860px) {{ .kpis {{ grid-template-columns: repeat(2, minmax(120px, 1fr)); }} .layout {{ grid-template-columns: 1fr; }} .toolbar {{ grid-template-columns: 1fr; }} }}
    </style>
</head>
<body>
    <div class=\"wrap\">
        <section class=\"header\">
            <h1>Git Workspace Global Viewer - Read Only</h1>
            <div class=\"meta\">Workspace: {root_text} | Profundidad: {max_depth} | Generado: {escape(now)}</div>
            <div class=\"kpis\">
                <div class=\"kpi\"><div class=\"n\">{total}</div><div class=\"l\">Repos</div></div>
                <div class=\"kpi\"><div class=\"n\">{dirty}</div><div class=\"l\">Con cambios</div></div>
                <div class=\"kpi\"><div class=\"n\">{detached}</div><div class=\"l\">Detached</div></div>
                <div class=\"kpi\"><div class=\"n\">{stale}</div><div class=\"l\">Stale</div></div>
            </div>
        </section>

        <section class=\"toolbar\">
            <input id=\"search\" type=\"search\" placeholder=\"Buscar repo/rama/commit...\" />
            <div class=\"checks\">
                <label><input id=\"f-dirty\" type=\"checkbox\" /> Solo cambios</label>
                <label><input id=\"f-detached\" type=\"checkbox\" /> Solo detached</label>
                <label><input id=\"f-stale\" type=\"checkbox\" /> Solo stale</label>
                <label><input id=\"theme-dark\" type=\"checkbox\" /> Dark mode</label>
                <label><input id=\"f-autorefresh\" type=\"checkbox\" /> Auto-refresh</label>
                <label for=\"refresh-sec\">Intervalo</label>
                <select id=\"refresh-sec\">
                    <option value=\"15\">15s</option>
                    <option value=\"30\">30s</option>
                    <option value=\"60\">60s</option>
                    <option value=\"120\">120s</option>
                </select>
            </div>
        </section>

        <section class=\"layout\">
            <article class=\"panel\">
                <div class=\"panel-title\">Repositorios</div>
                <div class=\"panel-body\" id=\"repo-list\"></div>
            </article>

            <article class=\"panel\">
                <div class=\"panel-title\" id=\"middle-title\">Timeline</div>
                <div class=\"panel-body\">
                    <div id=\"repo-summary\"></div>
                    <div class=\"graph\" id=\"graph-view\">Sin historial</div>
                    <div id=\"commit-list\"></div>
                </div>
            </article>

            <article class=\"panel right\">
                <div class=\"panel-title\">Detalle Commit</div>
                <div class=\"panel-body\" id=\"commit-detail\">Selecciona un commit para ver detalle.</div>
            </article>
        </section>

        <div class=\"footer\">Modo visor: no hay acciones mutantes de Git (add/commit/push/checkout).</div>
    </div>

    <script>
        const repos = {rows_json};
        const state = {{ selectedRepo: repos[0]?.name ?? null, selectedCommitByRepo: {{}} }};
        let refreshTimer = null;

        const el = {{
            repoList: document.getElementById('repo-list'),
            repoSummary: document.getElementById('repo-summary'),
            graphView: document.getElementById('graph-view'),
            commitList: document.getElementById('commit-list'),
            commitDetail: document.getElementById('commit-detail'),
            middleTitle: document.getElementById('middle-title'),
            search: document.getElementById('search'),
            dirty: document.getElementById('f-dirty'),
            detached: document.getElementById('f-detached'),
            stale: document.getElementById('f-stale'),
            themeDark: document.getElementById('theme-dark'),
            auto: document.getElementById('f-autorefresh'),
            refreshSec: document.getElementById('refresh-sec'),
        }};

        el.refreshSec.value = String({default_refresh} || 30);
        if ({default_refresh} > 0) {{ el.auto.checked = true; }}

        function prefersDark() {{
            return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        }}

        function applyTheme(theme) {{
            const selectedTheme = theme === 'dark' ? 'dark' : 'light';
            document.documentElement.setAttribute('data-theme', selectedTheme);
            el.themeDark.checked = selectedTheme === 'dark';
            try {{ localStorage.setItem('gwgv-theme', selectedTheme); }} catch (_err) {{}}
        }}

        function initTheme() {{
            let saved = null;
            try {{ saved = localStorage.getItem('gwgv-theme'); }} catch (_err) {{}}
            applyTheme(saved || (prefersDark() ? 'dark' : 'light'));
        }}

        function badge(text, klass='') {{ return `<span class=\"badge ${{klass}}\">${{text}}</span>`; }}

        function esc(value) {{
            return String(value ?? '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/\"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }}

        function badgeSync(text) {{
            const t = String(text).toLowerCase();
            if (t.includes('up to date')) return badge('Up to date', 'state-ok');
            if (t.includes('ahead') || t.includes('behind') || t.includes('diverged')) return badge(text, 'state-warn');
            return badge(text);
        }}

        function badgeChanges(r) {{
            if (!r.has_changes) return badge('🟢 Limpio', 'state-ok');
            return badge(r.local_changes, 'state-bad');
        }}

        function searchableText(r) {{
            const commitsText = (r.recent_commits || []).map(c => `${{c.hash}} ${{c.subject}} ${{c.author}}`).join(' ');
            return `${{r.name}} ${{r.branch}} ${{r.sync_remote}} ${{r.local_changes}} ${{r.last_commit}} ${{commitsText}}`.toLowerCase();
        }}

        function filteredRepos() {{
            const q = el.search.value.trim().toLowerCase();
            return repos
                .filter(r => !q || searchableText(r).includes(q))
                .filter(r => !el.dirty.checked || r.has_changes)
                .filter(r => !el.detached.checked || r.is_detached)
                .filter(r => !el.stale.checked || r.is_stale)
                .sort((a, b) => {{
                    const ta = Number(a.last_activity_ts || 0);
                    const tb = Number(b.last_activity_ts || 0);
                    if (tb !== ta) return tb - ta;
                    return a.name.localeCompare(b.name);
                }});
        }}

        function selectRepo(name) {{ state.selectedRepo = name; render(); }}

        function selectCommit(repoName, hash) {{
            state.selectedCommitByRepo[repoName] = hash;
            renderCommitDetail();
            renderCommitList();
        }}

        function getSelectedRepo() {{
            const list = filteredRepos();
            if (!list.length) return null;
            const exists = list.some(r => r.name === state.selectedRepo);
            if (!exists) state.selectedRepo = list[0].name;
            return list.find(r => r.name === state.selectedRepo) || list[0];
        }}

        function renderRepoList() {{
            const list = filteredRepos();
            if (!list.length) {{
                el.repoList.innerHTML = '<div class=\"repo-meta\">No hay repos para los filtros actuales.</div>';
                return;
            }}
            el.repoList.innerHTML = list.map(r => {{
                const flags = [badgeSync(r.sync_remote), badgeChanges(r)];
                if (r.is_detached) flags.push(badge('Detached', 'state-bad'));
                if (r.is_stale) flags.push(badge('Stale', 'state-warn'));
                const cls = r.name === state.selectedRepo ? 'repo-item active' : 'repo-item';
                return `<div class=\"${{cls}}\" role=\"button\" tabindex=\"0\" data-repo=\"${{esc(r.name)}}\" aria-label=\"Abrir repositorio ${{esc(r.name)}}\">\
                    <div class=\"repo-name\">${{esc(r.name)}}</div>\
                    <div class=\"repo-meta\">Rama: ${{esc(r.branch)}}</div>\
                    <div class=\"repo-meta\">${{flags.join(' ')}}</div>\
                </div>`;
            }}).join('');

            el.repoList.querySelectorAll('.repo-item').forEach(node => {{
                node.addEventListener('click', () => selectRepo(node.getAttribute('data-repo')));
                node.addEventListener('keydown', (evt) => {{
                    if (evt.key === 'Enter' || evt.key === ' ') {{
                        evt.preventDefault();
                        selectRepo(node.getAttribute('data-repo'));
                    }}
                }});
            }});
        }}

        function renderTimeline() {{
            const repo = getSelectedRepo();
            if (!repo) {{
                el.middleTitle.textContent = 'Timeline';
                el.repoSummary.innerHTML = '';
                el.graphView.textContent = 'Sin datos';
                el.commitList.innerHTML = '';
                el.commitDetail.innerHTML = 'Sin datos';
                return;
            }}

            el.middleTitle.textContent = `Timeline: ${{repo.name}}`;
            el.repoSummary.innerHTML = `<div class=\"repo-meta\">Rama actual: <b>${{repo.branch}}</b> | ${{badgeSync(repo.sync_remote)}} ${{badgeChanges(repo)}}</div>`;
            el.graphView.textContent = (repo.history_graph || []).join('\\n') || 'Sin historial disponible';

            const commits = repo.recent_commits || [];
            if (!state.selectedCommitByRepo[repo.name] && commits.length) {{
                state.selectedCommitByRepo[repo.name] = commits[0].hash;
            }}

            el.commitList.innerHTML = commits.map(c => {{
                const active = state.selectedCommitByRepo[repo.name] === c.hash ? 'commit-item active' : 'commit-item';
                return `<div class=\"${{active}}\" role=\"button\" tabindex=\"0\" data-h=\"${{esc(c.hash)}}\" aria-label=\"Ver commit ${{esc(c.hash)}}\">\
                    <div class=\"commit-head\">${{esc(c.hash)}}</div>\
                    <div class=\"commit-subj\">${{esc(c.subject)}}</div>\
                    <div class=\"commit-meta\">${{esc(c.author)}} - ${{esc(c.rel_time)}}</div>\
                </div>`;
            }}).join('') || '<div class=\"repo-meta\">Sin commits.</div>';

            el.commitList.querySelectorAll('.commit-item').forEach(node => {{
                node.addEventListener('click', () => selectCommit(repo.name, node.getAttribute('data-h')));
                node.addEventListener('keydown', (evt) => {{
                    if (evt.key === 'Enter' || evt.key === ' ') {{
                        evt.preventDefault();
                        selectCommit(repo.name, node.getAttribute('data-h'));
                    }}
                }});
            }});
        }}

        function renderCommitList() {{
            const repo = getSelectedRepo();
            if (!repo) return;
            const selected = state.selectedCommitByRepo[repo.name] || '';
            el.commitList.querySelectorAll('.commit-item').forEach(item => {{
                item.classList.toggle('active', item.getAttribute('data-h') === selected);
            }});
        }}

        function renderCommitDetail() {{
            const repo = getSelectedRepo();
            if (!repo) {{ el.commitDetail.innerHTML = 'Sin datos'; return; }}

            const commits = repo.recent_commits || [];
            const selectedHash = state.selectedCommitByRepo[repo.name];
            const commit = commits.find(c => c.hash === selectedHash) || commits[0];
            if (!commit) {{ el.commitDetail.innerHTML = 'Sin commits para este repositorio.'; return; }}

            const refs = commit.refs ? `<div class=\"repo-meta\">Refs: ${{esc(commit.refs)}}</div>` : '';
            const files = (commit.files || []).map(f => `<div class=\"file-row\">${{esc(f)}}</div>`).join('');
            const more = commit.files_total > (commit.files || []).length
                ? `<div class=\"repo-meta\">... y ${{commit.files_total - (commit.files || []).length}} archivo(s) mas</div>`
                : '';

            el.commitDetail.innerHTML = `
                <div class=\"commit-head\">${{esc(commit.hash)}} <span class=\"repo-meta\">(${{esc(commit.full_hash)}})</span></div>
                <div class=\"commit-subj\">${{esc(commit.subject)}}</div>
                <div class=\"commit-meta\">Autor: ${{esc(commit.author)}} | Fecha: ${{esc(commit.rel_time)}}</div>
                ${{refs}}
                <div class=\"files-list\">${{files || '<div class=\"repo-meta\">Sin archivos detectados para este commit.</div>'}}</div>
                ${{more}}
            `;
        }}

        function setupAutoRefresh() {{
            if (refreshTimer) {{ clearInterval(refreshTimer); refreshTimer = null; }}
            if (!el.auto.checked) return;
            const seconds = parseInt(el.refreshSec.value, 10) || 30;
            const canReload = window.location.protocol !== 'file:';
            if (!canReload) {{
                console.warn('Auto-refresh deshabilitado en file:// por restricciones del navegador/visor.');
                return;
            }}
            refreshTimer = setInterval(() => window.location.reload(), Math.max(seconds, 10) * 1000);
        }}

        function render() {{
            renderRepoList();
            renderTimeline();
            renderCommitDetail();
        }}

        [el.search, el.dirty, el.detached, el.stale].forEach(node => node.addEventListener('input', render));
        el.themeDark.addEventListener('change', () => applyTheme(el.themeDark.checked ? 'dark' : 'light'));
        el.auto.addEventListener('change', setupAutoRefresh);
        el.refreshSec.addEventListener('change', setupAutoRefresh);

        initTheme();
        render();
        setupAutoRefresh();
    </script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Global Git workspace read-only viewer")
    parser.add_argument("--root", default=".", help="Workspace root path to scan")
    parser.add_argument("--max-depth", type=int, default=3, help="Max folder depth for .git discovery")
    parser.add_argument("--graph-limit", type=int, default=25, help="Max graph lines per repo in HTML")
    parser.add_argument("--commit-limit", type=int, default=8, help="Max recent commits per repo in HTML")
    parser.add_argument("--commit-files-limit", type=int, default=12, help="Max changed files shown per commit")
    parser.add_argument("--auto-refresh-sec", type=int, default=0, help="Default HTML auto-refresh in seconds (0 disables)")
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
    statuses = [
        collect_repo_status(
            repo,
            root,
            graph_limit=args.graph_limit,
            commit_limit=args.commit_limit,
            commit_files_limit=args.commit_files_limit,
        )
        for repo in repos
    ]
    md_dashboard = render_dashboard(statuses, root, args.max_depth)
    html_dashboard = render_html_dashboard(statuses, root, args.max_depth, args.auto_refresh_sec)

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

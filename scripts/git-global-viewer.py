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
    latest_commit, is_stale = last_commit(repo)
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
            --ink: #162033;
            --muted: #56637a;
            --ok: #1f7a46;
            --warn: #b86b00;
            --bad: #b42318;
            --line: #d8e0ea;
            --shadow: 0 8px 24px rgba(18, 28, 45, 0.08);
        }}

        * {{ box-sizing: border-box; }}
        body {{
            margin: 0;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: radial-gradient(circle at 10% -8%, #dcefff, transparent 30%),
                                    radial-gradient(circle at 92% -8%, #ffeccf, transparent 24%),
                                    var(--bg);
            color: var(--ink);
        }}

        .wrap {{ max-width: 1600px; margin: 0 auto; padding: 18px; }}
        .header {{
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 14px;
            box-shadow: var(--shadow);
            padding: 14px 16px;
        }}
        .header h1 {{ margin: 0; font-size: 1.3rem; }}
        .meta {{ margin-top: 5px; color: var(--muted); font-size: 0.9rem; }}

        .kpis {{ margin-top: 12px; display: grid; grid-template-columns: repeat(4, minmax(120px, 1fr)); gap: 10px; }}
        .kpi {{ background: #fbfcfe; border: 1px solid var(--line); border-radius: 11px; padding: 8px 10px; }}
        .kpi .n {{ font-size: 1.35rem; font-weight: 700; }}
        .kpi .l {{ color: var(--muted); font-size: 0.8rem; }}

        .toolbar {{
            margin-top: 12px;
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 12px;
            background: var(--surface);
            border: 1px solid var(--line);
            border-radius: 12px;
            padding: 10px;
        }}
        .toolbar input[type=\"search\"] {{
            width: 100%;
            border: 1px solid var(--line);
            border-radius: 9px;
            padding: 10px;
            font-size: 0.93rem;
        }}
        .checks {{ display: flex; flex-wrap: wrap; gap: 10px; color: var(--muted); font-size: 0.86rem; align-items: center; }}

        .layout {{
            margin-top: 12px;
            display: grid;
            grid-template-columns: 320px 1fr 420px;
            gap: 12px;
            min-height: 72vh;
        }}
        .panel {{
            background: var(--surface);
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
            color: #344054;
            border-bottom: 1px solid #edf1f7;
            background: #f7f9fc;
        }}
        .panel-body {{ padding: 10px; overflow: auto; flex: 1; }}

        .repo-item {{
            padding: 8px;
            border-radius: 8px;
            border: 1px solid transparent;
            margin-bottom: 6px;
            cursor: pointer;
            background: #fbfcfe;
        }}
        .repo-item:hover {{ border-color: #d6e2f3; background: #f7fbff; }}
        .repo-item.active {{ border-color: #77a5e8; background: #eef5ff; }}
        .repo-name {{ font-size: 0.9rem; font-weight: 600; }}
        .repo-meta {{ margin-top: 3px; color: var(--muted); font-size: 0.78rem; }}

        .badge {{
            display: inline-block;
            border-radius: 999px;
            padding: 2px 7px;
            font-size: 0.74rem;
            border: 1px solid var(--line);
            background: #fff;
            color: var(--muted);
            margin-right: 4px;
        }}
        .state-ok {{ color: var(--ok); border-color: #add9bc; background: #effbf3; }}
        .state-warn {{ color: var(--warn); border-color: #f5d8a9; background: #fff8ec; }}
        .state-bad {{ color: var(--bad); border-color: #efb2ae; background: #fff2f1; }}

        .graph {{
            margin-top: 6px;
            font-family: Consolas, 'Courier New', monospace;
            font-size: 0.78rem;
            background: #0f1524;
            color: #e5edff;
            border-radius: 8px;
            padding: 8px;
            max-height: 220px;
            overflow: auto;
            white-space: pre;
        }}

        .commit-item {{
            border: 1px solid #e8edf5;
            border-radius: 8px;
            padding: 8px;
            margin-top: 8px;
            cursor: pointer;
            background: #fff;
        }}
        .commit-item.active {{ border-color: #79a8eb; background: #f2f7ff; }}
        .commit-head {{ font-family: Consolas, 'Courier New', monospace; font-size: 0.8rem; color: #334155; }}
        .commit-subj {{ margin-top: 2px; font-size: 0.86rem; }}
        .commit-meta {{ margin-top: 2px; color: var(--muted); font-size: 0.75rem; }}

        .files-list {{ margin-top: 8px; font-family: Consolas, 'Courier New', monospace; font-size: 0.78rem; }}
        .file-row {{ padding: 2px 0; border-bottom: 1px dashed #eff2f7; }}

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
                <label><input id=\"f-autorefresh\" type=\"checkbox\" /> Auto-refresh</label>
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
            auto: document.getElementById('f-autorefresh'),
            refreshSec: document.getElementById('refresh-sec'),
        }};

        el.refreshSec.value = String({default_refresh} || 30);
        if ({default_refresh} > 0) {{ el.auto.checked = true; }}

        function badge(text, klass='') {{ return `<span class=\"badge ${{klass}}\">${{text}}</span>`; }}

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
                .sort((a, b) => a.name.localeCompare(b.name));
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
                return `<div class=\"${{cls}}\" data-repo=\"${{r.name}}\">\
                    <div class=\"repo-name\">${{r.name}}</div>\
                    <div class=\"repo-meta\">Rama: ${{r.branch}}</div>\
                    <div class=\"repo-meta\">${{flags.join(' ')}}</div>\
                </div>`;
            }}).join('');

            el.repoList.querySelectorAll('.repo-item').forEach(node => {{
                node.addEventListener('click', () => selectRepo(node.getAttribute('data-repo')));
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
            el.graphView.textContent = (repo.history_graph || []).join('\n') || 'Sin historial disponible';

            const commits = repo.recent_commits || [];
            if (!state.selectedCommitByRepo[repo.name] && commits.length) {{
                state.selectedCommitByRepo[repo.name] = commits[0].hash;
            }}

            el.commitList.innerHTML = commits.map(c => {{
                const active = state.selectedCommitByRepo[repo.name] === c.hash ? 'commit-item active' : 'commit-item';
                return `<div class=\"${{active}}\" data-h=\"${{c.hash}}\">\
                    <div class=\"commit-head\">${{c.hash}}</div>\
                    <div class=\"commit-subj\">${{c.subject}}</div>\
                    <div class=\"commit-meta\">${{c.author}} - ${{c.rel_time}}</div>\
                </div>`;
            }}).join('') || '<div class=\"repo-meta\">Sin commits.</div>';

            el.commitList.querySelectorAll('.commit-item').forEach(node => {{
                node.addEventListener('click', () => selectCommit(repo.name, node.getAttribute('data-h')));
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

            const refs = commit.refs ? `<div class=\"repo-meta\">Refs: ${{commit.refs}}</div>` : '';
            const files = (commit.files || []).map(f => `<div class=\"file-row\">${{f}}</div>`).join('');
            const more = commit.files_total > (commit.files || []).length
                ? `<div class=\"repo-meta\">... y ${{commit.files_total - (commit.files || []).length}} archivo(s) mas</div>`
                : '';

            el.commitDetail.innerHTML = `
                <div class=\"commit-head\">${{commit.hash}} <span class=\"repo-meta\">(${{commit.full_hash}})</span></div>
                <div class=\"commit-subj\">${{commit.subject}}</div>
                <div class=\"commit-meta\">Autor: ${{commit.author}} | Fecha: ${{commit.rel_time}}</div>
                ${{refs}}
                <div class=\"files-list\">${{files || '<div class=\"repo-meta\">Sin archivos detectados para este commit.</div>'}}</div>
                ${{more}}
            `;
        }}

        function setupAutoRefresh() {{
            if (refreshTimer) {{ clearInterval(refreshTimer); refreshTimer = null; }}
            if (!el.auto.checked) return;
            const seconds = parseInt(el.refreshSec.value, 10) || 30;
            refreshTimer = setInterval(() => window.location.reload(), Math.max(seconds, 10) * 1000);
        }}

        function render() {{
            renderRepoList();
            renderTimeline();
            renderCommitDetail();
        }}

        [el.search, el.dirty, el.detached, el.stale].forEach(node => node.addEventListener('input', render));
        el.auto.addEventListener('change', setupAutoRefresh);
        el.refreshSec.addEventListener('change', setupAutoRefresh);

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

#!/usr/bin/env python3
"""Read-only Git workspace global viewer.

Scans a workspace for Git repositories and renders a Markdown dashboard.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Global Git workspace read-only viewer")
    parser.add_argument("--root", default=".", help="Workspace root path to scan")
    parser.add_argument("--max-depth", type=int, default=3, help="Max folder depth for .git discovery")
    parser.add_argument("--output", default="dashboard/global-git-dashboard.md", help="Markdown output file")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    repos = discover_repos(root, args.max_depth)
    statuses = [collect_repo_status(repo, root) for repo in repos]
    dashboard = render_dashboard(statuses, root, args.max_depth)

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = Path.cwd() / output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dashboard, encoding="utf-8")

    print(dashboard)
    print(f"Dashboard written to: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

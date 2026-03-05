"""Local MCP server exposing read-only git operations."""

import os
import re
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

COURSERA_ROOT = Path.home() / "base" / "coursera"
FORBIDDEN_CHARS = re.compile(r"[;|&$`\n\r\\]")

mcp = FastMCP("git-tools")


def _validate_repo(repo: str) -> Path:
    if FORBIDDEN_CHARS.search(repo):
        raise ValueError(f"Invalid characters in repo name: {repo}")
    repo_path = (COURSERA_ROOT / repo).resolve()
    if not repo_path.is_relative_to(COURSERA_ROOT):
        raise ValueError(f"Repo must be under {COURSERA_ROOT}")
    if not (repo_path / ".git").is_dir():
        raise ValueError(f"Not a git repo: {repo_path}")
    return repo_path


def _validate_param(value: str, name: str) -> str:
    if FORBIDDEN_CHARS.search(value):
        raise ValueError(f"Invalid characters in {name}: {value}")
    return value


def _run_git(repo_path: Path, args: list[str]) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_path)] + args,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        return f"ERROR: {result.stderr.strip()}"
    return result.stdout.strip() or "(empty output)"


@mcp.tool()
def git_diff_stat(repo: str, branch: str, base: str = "main") -> str:
    """Show file change summary (insertions/deletions) between base and branch."""
    repo_path = _validate_repo(repo)
    _validate_param(branch, "branch")
    _validate_param(base, "base")
    return _run_git(repo_path, ["diff", f"{base}...{branch}", "--stat"])


@mcp.tool()
def git_diff_names(repo: str, branch: str, base: str = "main") -> str:
    """List files changed between base and branch (names only)."""
    repo_path = _validate_repo(repo)
    _validate_param(branch, "branch")
    _validate_param(base, "base")
    return _run_git(repo_path, ["diff", f"{base}...{branch}", "--name-only"])


@mcp.tool()
def git_diff_file(repo: str, branch: str, path: str, base: str = "main") -> str:
    """Show full diff for a specific file between base and branch."""
    repo_path = _validate_repo(repo)
    _validate_param(branch, "branch")
    _validate_param(base, "base")
    _validate_param(path, "path")
    return _run_git(repo_path, ["diff", f"{base}...{branch}", "--", path])


@mcp.tool()
def git_log(repo: str, branch: str, base: str = "main", max_count: int = 50) -> str:
    """Show commit log between base and branch (oneline format)."""
    repo_path = _validate_repo(repo)
    _validate_param(branch, "branch")
    _validate_param(base, "base")
    count = min(max(1, max_count), 200)
    return _run_git(repo_path, ["log", f"{base}..{branch}", "--oneline", f"-{count}"])


@mcp.tool()
def git_show_file(repo: str, ref: str, path: str) -> str:
    """Show file contents at a specific git ref (branch, tag, or commit)."""
    repo_path = _validate_repo(repo)
    _validate_param(ref, "ref")
    _validate_param(path, "path")
    return _run_git(repo_path, ["show", f"{ref}:{path}"])


@mcp.tool()
def git_branches(repo: str, pattern: str = "") -> str:
    """List branches, optionally filtered by pattern."""
    repo_path = _validate_repo(repo)
    args = ["branch", "--list", "--format=%(refname:short)"]
    if pattern:
        _validate_param(pattern, "pattern")
        args.append(pattern)
    return _run_git(repo_path, args)


@mcp.tool()
def git_status(repo: str) -> str:
    """Show working tree status (short format)."""
    repo_path = _validate_repo(repo)
    return _run_git(repo_path, ["status", "--short"])


if __name__ == "__main__":
    mcp.run()

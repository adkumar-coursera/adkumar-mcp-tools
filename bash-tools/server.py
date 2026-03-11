"""Local MCP server exposing bash utilities (grep, tree, sed, find, diff, wc)."""

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

COURSERA_ROOT = Path.home() / "base" / "coursera"

mcp = FastMCP("bash-tools")


def _validate_path(path: str) -> Path:
    resolved = (COURSERA_ROOT / path).resolve()
    if not resolved.is_relative_to(COURSERA_ROOT):
        raise ValueError(f"Path must be under {COURSERA_ROOT}")
    if not resolved.exists():
        raise ValueError(f"Path does not exist: {resolved}")
    return resolved


@mcp.tool()
def grep_text(
    pattern: str,
    path: str = ".",
    include: str = "",
    exclude: str = "",
    ignore_case: bool = False,
    whole_word: bool = False,
    fixed_string: bool = False,
    max_count: int = 0,
    context_lines: int = 0,
    include_hidden: bool = False,
    file_pattern_only: bool = False,
) -> str:
    """Search for text patterns in files under ~/base/coursera.

    Args:
        pattern: The search pattern (regex by default, or literal if fixed_string=True).
        path: Directory or file to search, relative to ~/base/coursera. Defaults to ".".
        include: Glob pattern for files to include (e.g. "*.java", "*.py").
        exclude: Glob pattern for files to exclude (e.g. "*.log", "*.min.js").
        ignore_case: Case-insensitive matching.
        whole_word: Match whole words only.
        fixed_string: Treat pattern as a fixed string, not a regex.
        max_count: Max matches per file (0 = unlimited).
        context_lines: Number of context lines before and after each match.
        include_hidden: Search hidden files/directories too.
        file_pattern_only: Only print file names that contain matches (like grep -l).
    """
    search_path = _validate_path(path)

    args = ["grep", "-rn"]

    if ignore_case:
        args.append("-i")
    if whole_word:
        args.append("-w")
    if fixed_string:
        args.append("-F")
    if file_pattern_only:
        args.append("-l")
    if max_count > 0:
        args.extend(["--max-count", str(max_count)])
    if context_lines > 0:
        args.extend(["-C", str(context_lines)])
    if include:
        args.extend(["--include", include])
    if exclude:
        args.extend(["--exclude", exclude])
    if not include_hidden:
        args.extend(["--exclude-dir", ".*", "--exclude-dir", "node_modules",
                      "--exclude-dir", "__pycache__", "--exclude-dir", "build",
                      "--exclude-dir", ".gradle", "--exclude-dir", ".venv"])

    args.append("--")
    args.append(pattern)
    args.append(str(search_path))

    result = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode == 1:
        return "(no matches found)"
    if result.returncode != 0:
        return f"ERROR: {result.stderr.strip()}"

    output = result.stdout.strip()
    lines = output.split("\n")
    if len(lines) > 500:
        return "\n".join(lines[:500]) + f"\n\n... truncated ({len(lines)} total lines, showing first 500)"
    return output or "(no matches found)"


if __name__ == "__main__":
    mcp.run()

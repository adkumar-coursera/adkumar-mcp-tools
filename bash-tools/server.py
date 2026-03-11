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
    if not output:
        return "(no matches found)"
    return _truncate(output)


def _truncate(output: str, max_lines: int = 500) -> str:
    """Truncate output to max_lines, appending a notice if truncated."""
    lines = output.split("\n")
    if len(lines) > max_lines:
        return "\n".join(lines[:max_lines]) + f"\n\n... truncated ({len(lines)} total lines, showing first {max_lines})"
    return output


@mcp.tool()
def tree(
    path: str = ".",
    max_depth: int = 3,
    include_pattern: str = "",
    exclude_pattern: str = "",
    dirs_only: bool = False,
) -> str:
    """Show a directory tree structure under ~/base/coursera.

    Useful for quickly understanding project layout. Uses the `tree` command
    if available, otherwise falls back to `find`-based output.

    Args:
        path: Directory to tree, relative to ~/base/coursera. Defaults to ".".
        max_depth: Maximum depth to descend. Defaults to 3.
        include_pattern: Glob pattern to include (e.g. "*.java"). Only affects files, not dirs.
        exclude_pattern: Glob pattern to exclude (e.g. "*.class"). Only affects files, not dirs.
        dirs_only: If True, only show directories, not files.
    """
    target = _validate_path(path)

    if shutil.which("tree"):
        args = ["tree", str(target), "-L", str(max_depth), "--charset", "utf-8"]
        if dirs_only:
            args.append("-d")
        if include_pattern:
            args.extend(["-P", include_pattern])
        # Single -I flag combining noisy dirs + user exclusion
        exclude_parts = ".git|node_modules|__pycache__|build|.gradle|.venv"
        if exclude_pattern:
            exclude_parts += f"|{exclude_pattern}"
        args.extend(["-I", exclude_parts])
    else:
        # Fallback: find-based output
        args = ["find", str(target), "-maxdepth", str(max_depth)]
        if dirs_only:
            args.extend(["-type", "d"])
        if include_pattern:
            args.extend(["-name", include_pattern])
        # Prune common noisy dirs
        for d in [".git", "node_modules", "__pycache__", "build", ".gradle", ".venv"]:
            args.extend(["-not", "-path", f"*/{d}/*", "-not", "-name", d])
        args.append("-print")

    result = subprocess.run(args, capture_output=True, text=True, timeout=60)

    if result.returncode != 0:
        return f"ERROR: {result.stderr.strip()}"

    output = result.stdout.strip()
    if not output:
        return "(empty directory)"
    return _truncate(output)


@mcp.tool()
def sed_replace(
    pattern: str,
    path: str,
    include: str = "",
    dry_run: bool = True,
) -> str:
    """Run sed replacement on files under ~/base/coursera.

    Useful for regex-based find-and-replace across files, especially when
    Claude Code's Edit tool fails due to non-unique strings.

    IMPORTANT: Defaults to dry_run=True for safety. In dry-run mode, shows a
    diff of what would change without modifying any files. Set dry_run=False
    to actually apply changes.

    Args:
        pattern: A sed expression, e.g. "s/oldFunc/newFunc/g". Must be a valid
            sed substitution command.
        path: File or directory to operate on, relative to ~/base/coursera.
        include: Glob pattern for files when path is a directory (e.g. "*.java").
            Required when path is a directory.
        dry_run: If True (default), preview changes as a diff without modifying files.
            If False, apply changes in-place.
    """
    target = _validate_path(path)

    # Build list of files to process
    if target.is_dir():
        if not include:
            return "ERROR: 'include' glob is required when path is a directory (e.g. '*.java')"
        find_args = ["find", str(target), "-type", "f", "-name", include]
        find_result = subprocess.run(find_args, capture_output=True, text=True, timeout=60)
        if find_result.returncode != 0:
            return f"ERROR finding files: {find_result.stderr.strip()}"
        files = [f for f in find_result.stdout.strip().split("\n") if f]
        if not files:
            return "(no files matched the include pattern)"
    else:
        files = [str(target)]

    if dry_run:
        # Show diff of what would change
        diffs = []
        for filepath in files:
            # Run sed and capture output (no -i), then diff against original
            sed_result = subprocess.run(
                ["sed", pattern, filepath],
                capture_output=True, text=True, timeout=60,
            )
            if sed_result.returncode != 0:
                diffs.append(f"--- ERROR in {filepath}: {sed_result.stderr.strip()}")
                continue
            # Write sed output to a temp file and diff
            with tempfile.NamedTemporaryFile(mode="w", suffix=".sed_preview", delete=True) as tmp:
                tmp.write(sed_result.stdout)
                tmp.flush()
                diff_result = subprocess.run(
                    ["diff", "-u", filepath, tmp.name],
                    capture_output=True, text=True, timeout=60,
                )
                if diff_result.stdout.strip():
                    diffs.append(diff_result.stdout.strip())

        if not diffs:
            return "(no changes — pattern matched nothing or files are already as expected)"
        return _truncate("\n\n".join(diffs))
    else:
        # Apply in-place (macOS sed uses -i '')
        errors = []
        changed = 0
        for filepath in files:
            result = subprocess.run(
                ["sed", "-i", "", pattern, filepath],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                errors.append(f"{filepath}: {result.stderr.strip()}")
            else:
                changed += 1
        summary = f"Applied to {changed} file(s)."
        if errors:
            summary += "\nErrors:\n" + "\n".join(errors)
        return summary


@mcp.tool()
def find_files(
    path: str = ".",
    name: str = "",
    type: str = "",
    newer_than: str = "",
    size: str = "",
    max_depth: int = 0,
    exclude_dirs: Optional[list[str]] = None,
) -> str:
    """Find files with filters beyond simple glob patterns under ~/base/coursera.

    Wraps the `find` command with convenient defaults. Prunes common noisy
    directories (.git, node_modules, build, etc.) by default.

    Args:
        path: Directory to search in, relative to ~/base/coursera. Defaults to ".".
        name: Glob pattern for file/dir names (e.g. "*.java", "Dockerfile*").
        type: Type filter — "f" for files, "d" for directories, "l" for symlinks.
        newer_than: ISO date string (e.g. "2025-01-15") — only items modified after this date.
        size: Size filter (e.g. "+1M" for >1MB, "-100k" for <100KB). Uses find -size syntax.
        max_depth: Maximum depth to search. 0 means unlimited.
        exclude_dirs: List of directory names to prune. Defaults to
            [".git", "node_modules", "build", ".gradle", "__pycache__", ".venv"].
    """
    target = _validate_path(path)

    if exclude_dirs is None:
        exclude_dirs = [".git", "node_modules", "build", ".gradle", "__pycache__", ".venv"]

    args = ["find", str(target)]

    if max_depth > 0:
        args.extend(["-maxdepth", str(max_depth)])

    # Prune excluded directories
    if exclude_dirs:
        prune_expr = []
        for d in exclude_dirs:
            prune_expr.extend(["-name", d, "-o"])
        # Remove trailing -o, wrap in parens with -prune
        prune_expr = prune_expr[:-1]  # drop last -o
        args.extend(["("] + prune_expr + [")", "-prune", "-o"])

    # Filters (these come after the prune expression)
    filters = []
    if type:
        filters.extend(["-type", type])
    if name:
        filters.extend(["-name", name])
    if newer_than:
        filters.extend(["-newermt", newer_than])
    if size:
        filters.extend(["-size", size])

    args.extend(filters)
    args.append("-print")

    result = subprocess.run(args, capture_output=True, text=True, timeout=60)

    if result.returncode != 0:
        return f"ERROR: {result.stderr.strip()}"

    output = result.stdout.strip()
    if not output:
        return "(no files found)"
    return _truncate(output)


@mcp.tool()
def diff_files(
    file1: str,
    file2: str = "",
    git_ref: str = "",
    context_lines: int = 3,
) -> str:
    """Diff two files or show git diff for a file under ~/base/coursera.

    Two modes:
    - **Two-file mode**: Provide both file1 and file2 to get a unified diff between them.
    - **Git mode**: Provide only file1 (and optionally git_ref) to see git changes.
      Without git_ref, shows unstaged changes. With git_ref (e.g. "HEAD~1", "main"),
      shows diff against that ref.

    Args:
        file1: First file path, relative to ~/base/coursera. In git mode, the file to diff.
        file2: Second file path, relative to ~/base/coursera. If omitted, uses git diff mode.
        git_ref: Git ref to diff against (e.g. "HEAD~1", "main", "abc1234"). Only used in git mode.
        context_lines: Number of context lines around each change. Defaults to 3.
    """
    path1 = _validate_path(file1)

    if file2:
        # Two-file diff mode
        path2 = _validate_path(file2)
        args = ["diff", f"-U{context_lines}", str(path1), str(path2)]
    else:
        # Git diff mode
        args = ["git", "diff"]
        if git_ref:
            args.append(git_ref)
        args.extend([f"-U{context_lines}", "--", str(path1)])

    result = subprocess.run(args, capture_output=True, text=True, timeout=60)

    # diff returns 1 when files differ — that's not an error
    if result.returncode > 1:
        return f"ERROR: {result.stderr.strip()}"

    output = result.stdout.strip()
    if not output:
        return "(no differences found)"
    return _truncate(output)


@mcp.tool()
def wc_stats(
    path: str,
    include: str = "",
) -> str:
    """Get line, word, and character counts for files under ~/base/coursera.

    For a single file, returns its line/word/char counts. For a directory,
    returns per-file counts plus a total. Useful for gauging file sizes or
    finding unexpectedly large files.

    Args:
        path: File or directory, relative to ~/base/coursera.
        include: Glob pattern for files when path is a directory (e.g. "*.py").
            If omitted for a directory, counts all files.
    """
    target = _validate_path(path)

    if target.is_file():
        args = ["wc", str(target)]
    else:
        # Build a find | xargs wc pipeline
        find_args = ["find", str(target), "-type", "f"]
        if include:
            find_args.extend(["-name", include])
        # Prune noisy dirs
        for d in [".git", "node_modules", "build", ".gradle", "__pycache__", ".venv"]:
            find_args.extend(["-not", "-path", f"*/{d}/*"])

        find_result = subprocess.run(find_args, capture_output=True, text=True, timeout=60)
        if find_result.returncode != 0:
            return f"ERROR finding files: {find_result.stderr.strip()}"
        files = find_result.stdout.strip()
        if not files:
            return "(no files found)"

        # Pass file list to wc via xargs
        result = subprocess.run(
            ["xargs", "wc"],
            input=files,
            capture_output=True, text=True, timeout=60,
        )
        output = result.stdout.strip()
        if result.returncode != 0:
            return f"ERROR: {result.stderr.strip()}"
        if not output:
            return "(no output)"
        return _truncate(output)

    result = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        return f"ERROR: {result.stderr.strip()}"
    return result.stdout.strip()


if __name__ == "__main__":
    mcp.run()

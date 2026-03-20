"""Local MCP server for reading large JSON tool results (Google Docs, etc).

When MCP tools like google-workspace return oversized results, they get saved
to .txt files. This server provides tools to extract and chunk-read the content
from those files without needing raw python one-liners in Bash.
"""

import json
from pathlib import Path

from mcp.server.fastmcp import FastMCP

CLAUDE_DIR = Path.home() / ".claude"

mcp = FastMCP("docs-tools")


def _validate_path(path: str) -> Path:
    resolved = Path(path).resolve()
    if not resolved.is_relative_to(CLAUDE_DIR):
        raise ValueError(f"Path must be under {CLAUDE_DIR}")
    if not resolved.exists():
        raise ValueError(f"File does not exist: {resolved}")
    return resolved


def _load_json_content(file_path: Path) -> str:
    """Load a JSON file and extract the 'content' field if present."""
    raw = file_path.read_text(encoding="utf-8")
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "content" in data:
            return data["content"]
        return raw
    except json.JSONDecodeError:
        return raw


@mcp.tool()
def read_doc(
    file_path: str,
    start: int = 0,
    length: int = 7000,
) -> str:
    """Read a chunk of content from an MCP tool result file.

    When google-workspace or other MCP tools produce oversized results, they
    get saved as JSON files under ~/.claude/projects/. This tool extracts the
    'content' field and returns a chunk of it.

    Args:
        file_path: Absolute path to the saved tool result .txt file.
        start: Character offset to start reading from. Defaults to 0.
        length: Number of characters to read. Defaults to 7000.
    """
    path = _validate_path(file_path)
    content = _load_json_content(path)
    chunk = content[start:start + length]
    total = len(content)
    end = min(start + length, total)

    header = f"[chars {start}-{end} of {total}]"
    if end < total:
        header += f" (next: start={end})"
    else:
        header += " (end of document)"

    return f"{header}\n\n{chunk}"


@mcp.tool()
def doc_info(
    file_path: str,
) -> str:
    """Get metadata about an MCP tool result file (title, total length, etc).

    Args:
        file_path: Absolute path to the saved tool result .txt file.
    """
    path = _validate_path(file_path)
    raw = path.read_text(encoding="utf-8")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        lines = raw.count("\n") + 1
        return f"Plain text file: {len(raw)} chars, {lines} lines"

    info_parts = []
    if isinstance(data, dict):
        if "title" in data:
            info_parts.append(f"Title: {data['title']}")
        if "id" in data:
            info_parts.append(f"Doc ID: {data['id']}")
        if "webViewLink" in data:
            info_parts.append(f"Link: {data['webViewLink']}")
        if "content" in data:
            content = data["content"]
            info_parts.append(f"Content length: {len(content)} chars")
            # Suggest chunk count
            chunk_size = 7000
            chunks = (len(content) + chunk_size - 1) // chunk_size
            info_parts.append(f"Suggested reads: {chunks} chunks of {chunk_size} chars")

    return "\n".join(info_parts) if info_parts else f"JSON file: {len(raw)} chars"


@mcp.tool()
def search_doc(
    file_path: str,
    query: str,
    context_chars: int = 500,
    max_results: int = 5,
) -> str:
    """Search for text within an MCP tool result file's content.

    Case-insensitive search. Returns matching snippets with surrounding context.

    Args:
        file_path: Absolute path to the saved tool result .txt file.
        query: Text to search for (case-insensitive).
        context_chars: Number of characters of context around each match. Defaults to 500.
        max_results: Maximum number of matches to return. Defaults to 5.
    """
    path = _validate_path(file_path)
    content = _load_json_content(path)
    content_lower = content.lower()
    query_lower = query.lower()

    results = []
    search_start = 0
    while len(results) < max_results:
        idx = content_lower.find(query_lower, search_start)
        if idx == -1:
            break

        snippet_start = max(0, idx - context_chars)
        snippet_end = min(len(content), idx + len(query) + context_chars)
        snippet = content[snippet_start:snippet_end]

        prefix = "..." if snippet_start > 0 else ""
        suffix = "..." if snippet_end < len(content) else ""

        results.append(f"[match at char {idx}]\n{prefix}{snippet}{suffix}")
        search_start = idx + len(query)

    if not results:
        return f"No matches for '{query}' in document ({len(content)} chars)"

    return f"{len(results)} match(es) found:\n\n" + "\n\n---\n\n".join(results)


if __name__ == "__main__":
    mcp.run()

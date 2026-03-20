"""MCP server for querying SonarCloud issues."""

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("sonar-tools")

SONARCLOUD_BASE = "https://sonarcloud.io/api"

SEVERITY_ORDER = ["BLOCKER", "CRITICAL", "MAJOR", "MINOR", "INFO"]
TYPE_ORDER = ["BUG", "VULNERABILITY", "CODE_SMELL"]
TYPE_LABELS = {"BUG": "Bug", "VULNERABILITY": "Vulnerability", "CODE_SMELL": "Code Smell"}


def _sonar_get(token: str, endpoint: str, params: dict) -> dict:
    url = f"{SONARCLOUD_BASE}/{endpoint}?{urllib.parse.urlencode(params)}"
    credentials = base64.b64encode(f"{token}:".encode()).decode()
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {credentials}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"SonarCloud API error {e.code}: {body}")


def _fetch_all_issues(token: str, base_params: dict) -> list:
    """Fetch all pages of issues and return a flat list."""
    all_issues = []
    page = 1
    while True:
        params = {**base_params, "p": page, "ps": 500}
        data = _sonar_get(token, "issues/search", params)
        issues = data.get("issues", [])
        all_issues.extend(issues)
        total = data.get("paging", {}).get("total", 0)
        if len(all_issues) >= total or not issues:
            break
        page += 1
    return all_issues


def _short_path(component: str) -> str:
    """Strip project-key prefix and shorten deep paths."""
    path = component.split(":", 1)[1] if ":" in component else component
    parts = path.split("/")
    # Keep last 3 segments to stay readable in a table
    if len(parts) > 3:
        return ".../" + "/".join(parts[-2:])
    return path


def _format_issues(issues: list, project_key: str, context: str) -> str:
    if not issues:
        return f"## SonarQube — `{project_key}` ({context})\n\nNo issues found matching the given filters."

    # Group by type
    by_type: dict[str, list] = {t: [] for t in TYPE_ORDER}
    unknown: list = []
    for issue in issues:
        t = issue.get("type", "")
        if t in by_type:
            by_type[t].append(issue)
        else:
            unknown.append(issue)

    severity_rank = {s: i for i, s in enumerate(SEVERITY_ORDER)}

    open_count = sum(
        1 for i in issues if i.get("issueStatus", i.get("status", "")) in ("OPEN", "REOPENED", "CONFIRMED")
    )

    lines = [
        f"## SonarQube — `{project_key}` ({context})",
        "",
        f"**Total:** {len(issues)}  |  **Open:** {open_count}",
        "",
    ]

    for type_name in TYPE_ORDER:
        type_issues = by_type[type_name]
        if not type_issues:
            continue

        label = TYPE_LABELS[type_name]
        lines.append(f"### {label} ({len(type_issues)})")
        lines.append("")
        lines.append("| Sev | File | Line | Rule | Message | Status | Effort |")
        lines.append("|-----|------|------|------|---------|--------|--------|")

        type_issues.sort(key=lambda x: severity_rank.get(x.get("severity", "INFO"), 99))

        for issue in type_issues:
            sev = issue.get("severity", "")
            path = _short_path(issue.get("component", ""))
            line = issue.get("line") or issue.get("textRange", {}).get("startLine", "—")
            rule = issue.get("rule", "")
            msg = issue.get("message", "").replace("|", "\\|").replace("\n", " ")
            if len(msg) > 90:
                msg = msg[:87] + "..."
            status = issue.get("issueStatus") or issue.get("status", "")
            effort = issue.get("effort", "—")

            lines.append(f"| {sev} | `{path}` | {line} | `{rule}` | {msg} | {status} | {effort} |")

        lines.append("")

    if unknown:
        lines.append(f"### Other ({len(unknown)})")
        lines.append("")
        for issue in unknown:
            lines.append(f"- [{issue.get('severity')}] `{_short_path(issue.get('component', ''))}` — {issue.get('message', '')}")
        lines.append("")

    return "\n".join(lines)


@mcp.tool()
def search_issues(
    token: str,
    project_key: str,
    pull_request: Optional[int] = None,
    severities: Optional[str] = None,
    types: Optional[str] = None,
    resolved: bool = False,
    tags: Optional[str] = None,
) -> str:
    """Search SonarCloud issues for a project, with automatic pagination.

    Returns a formatted markdown summary grouped by issue type (BUG,
    VULNERABILITY, CODE_SMELL) and sorted by severity within each group.

    Coursera projects only track SonarQube analysis per pull request,
    not per branch. Always provide pull_request when checking a PR.

    Args:
        token: SonarCloud authentication token.
        project_key: Project key, e.g. "webedx-spark_enterprise-reports-application".
        pull_request: PR number to scope results to a specific pull request.
            If omitted, queries the main branch analysis.
        severities: Comma-separated severity filter.
            Values: BLOCKER, CRITICAL, MAJOR, MINOR, INFO.
        types: Comma-separated type filter.
            Values: BUG, VULNERABILITY, CODE_SMELL.
        resolved: Include resolved/closed issues. Default False (open only).
            Set True only when explicitly requested — resolved issues are rarely useful.
        tags: Comma-separated tag filter, e.g. "security,performance".
    """
    params: dict = {"componentKeys": project_key}

    if pull_request is not None:
        params["pullRequest"] = str(pull_request)
    if severities:
        params["severities"] = severities
    if types:
        params["types"] = types
    if not resolved:
        params["resolved"] = "false"
    if tags:
        params["tags"] = tags

    try:
        issues = _fetch_all_issues(token, params)
    except RuntimeError as e:
        return f"ERROR fetching issues: {e}"

    # Build context string for the header
    context_parts = []
    if pull_request is not None:
        context_parts.append(f"PR #{pull_request}")
    else:
        context_parts.append("main branch")
    if severities:
        context_parts.append(f"severities={severities}")
    if types:
        context_parts.append(f"types={types}")
    if tags:
        context_parts.append(f"tags={tags}")
    if resolved:
        context_parts.append("including resolved")

    return _format_issues(issues, project_key, " | ".join(context_parts))


if __name__ == "__main__":
    mcp.run()

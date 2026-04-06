"""MCP server for analysing JaCoCo XML test coverage reports."""

import xml.etree.ElementTree as ET
from typing import Optional

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("jacoco-tools")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CounterMap = dict[str, dict[str, int]]  # type -> {missed, covered}


def _parse_report(report_path: str) -> ET.Element:
    try:
        tree = ET.parse(report_path)
    except FileNotFoundError:
        raise RuntimeError(f"Report not found: {report_path}")
    except ET.ParseError as e:
        raise RuntimeError(f"Failed to parse XML: {e}")
    return tree.getroot()


def _read_counters(element: ET.Element) -> CounterMap:
    result: CounterMap = {}
    for counter in element.findall("counter"):
        t = counter.attrib["type"]
        result[t] = {
            "missed": int(counter.attrib["missed"]),
            "covered": int(counter.attrib["covered"]),
        }
    return result


def _pct(missed: int, covered: int) -> float:
    total = missed + covered
    return 0.0 if total == 0 else round(covered / total * 100, 1)


def _pct_str(missed: int, covered: int) -> str:
    total = missed + covered
    if total == 0:
        return "N/A"
    pct = _pct(missed, covered)
    return f"{pct:.1f}% ({covered}/{total})"


def _short_pkg(pkg_name: str) -> str:
    """Return the last two segments of a java package path."""
    parts = pkg_name.split("/")
    return "/".join(parts[-2:]) if len(parts) > 2 else pkg_name


def _short_class(class_name: str) -> str:
    """Strip package prefix, return simple class name."""
    return class_name.split("/")[-1]


COUNTER_ORDER = ["INSTRUCTION", "BRANCH", "LINE", "METHOD", "CLASS"]


def _counter_row(counters: CounterMap, types: list[str] = COUNTER_ORDER) -> str:
    cells = []
    for t in types:
        c = counters.get(t)
        if c is None:
            cells.append("N/A")
        else:
            cells.append(_pct_str(c["missed"], c["covered"]))
    return " | ".join(cells)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def get_coverage_summary(report_path: str) -> str:
    """Get the overall coverage summary for a JaCoCo XML report.

    Parses the top-level counters from the report and returns a formatted
    markdown table with INSTRUCTION, BRANCH, LINE, METHOD, and CLASS coverage.

    Typical report locations:
      <repo>/build/reports/jacoco/test/jacocoTestReport.xml
      <repo>/build/reports/jacoco/jacocoTestReportForSonar/report.xml

    Args:
        report_path: Absolute path to the JaCoCo XML report file.
    """
    try:
        root = _parse_report(report_path)
    except RuntimeError as e:
        return f"ERROR: {e}"

    project_name = root.attrib.get("name", "unknown")
    counters = _read_counters(root)

    lines = [
        f"## JaCoCo Coverage — `{project_name}`",
        "",
        f"Report: `{report_path}`",
        "",
        "| Metric | Coverage | Covered | Missed | Total |",
        "|--------|----------|---------|--------|-------|",
    ]

    for t in COUNTER_ORDER:
        c = counters.get(t)
        if c is None:
            continue
        total = c["missed"] + c["covered"]
        pct = _pct(c["missed"], c["covered"])
        bar = _progress_bar(pct)
        lines.append(f"| {t} | {bar} {pct:.1f}% | {c['covered']} | {c['missed']} | {total} |")

    return "\n".join(lines)


def _progress_bar(pct: float, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return "[" + "█" * filled + "░" * (width - filled) + "]"


@mcp.tool()
def get_package_coverage(
    report_path: str,
    metric: str = "LINE",
    min_packages: int = 0,
    sort_ascending: bool = True,
) -> str:
    """Get per-package coverage breakdown from a JaCoCo XML report.

    Returns a markdown table with one row per package, sorted by coverage
    (worst first by default so problem areas jump out immediately).

    Args:
        report_path: Absolute path to the JaCoCo XML report file.
        metric: Coverage metric to sort by. One of: INSTRUCTION, BRANCH, LINE, METHOD, CLASS.
            Defaults to LINE.
        min_packages: If > 0, only show the N worst-covered packages.
        sort_ascending: Sort by coverage ascending (worst first). Default True.
            Set False to see best-covered packages first.
    """
    try:
        root = _parse_report(report_path)
    except RuntimeError as e:
        return f"ERROR: {e}"

    metric = metric.upper()
    project_name = root.attrib.get("name", "unknown")

    rows = []
    for pkg in root.findall("package"):
        pkg_name = pkg.attrib.get("name", "unknown")
        counters = _read_counters(pkg)
        c = counters.get(metric, {"missed": 0, "covered": 0})
        pct = _pct(c["missed"], c["covered"])
        rows.append((pkg_name, counters, pct))

    rows.sort(key=lambda r: r[2], reverse=not sort_ascending)

    if min_packages > 0:
        rows = rows[:min_packages]

    direction = "ascending (worst first)" if sort_ascending else "descending (best first)"
    lines = [
        f"## Package Coverage — `{project_name}` (sorted by {metric} {direction})",
        "",
        f"| Package | {metric} % | INSTRUCTION | BRANCH | LINE | METHOD |",
        f"|---------|-----------|-------------|--------|------|--------|",
    ]

    for pkg_name, counters, pct in rows:
        short = _short_pkg(pkg_name)
        metric_c = counters.get(metric, {"missed": 0, "covered": 0})
        instr = counters.get("INSTRUCTION", {})
        branch = counters.get("BRANCH", {})
        line = counters.get("LINE", {})
        method = counters.get("METHOD", {})

        def fmt(c: dict) -> str:
            if not c:
                return "N/A"
            return f"{_pct(c['missed'], c['covered']):.1f}%"

        lines.append(
            f"| `{short}` | {pct:.1f}% | {fmt(instr)} | {fmt(branch)} | {fmt(line)} | {fmt(method)} |"
        )

    return "\n".join(lines)


@mcp.tool()
def get_class_coverage(
    report_path: str,
    package_filter: Optional[str] = None,
    metric: str = "LINE",
    threshold: Optional[float] = None,
) -> str:
    """Get per-class coverage breakdown from a JaCoCo XML report.

    Returns a markdown table with one row per class, sorted by coverage
    (worst first). Optionally filter to a specific package or by a coverage
    threshold.

    Args:
        report_path: Absolute path to the JaCoCo XML report file.
        package_filter: Substring to match against the package path, e.g. "managers".
            Case-insensitive. If omitted, all packages are included.
        metric: Coverage metric to sort by. One of: INSTRUCTION, BRANCH, LINE, METHOD, CLASS.
            Defaults to LINE.
        threshold: If set, only show classes with coverage below this percentage (0-100).
            Useful for finding under-tested classes, e.g. threshold=80.
    """
    try:
        root = _parse_report(report_path)
    except RuntimeError as e:
        return f"ERROR: {e}"

    metric = metric.upper()
    project_name = root.attrib.get("name", "unknown")

    rows = []
    for pkg in root.findall("package"):
        pkg_name = pkg.attrib.get("name", "")
        if package_filter and package_filter.lower() not in pkg_name.lower():
            continue
        for cls in pkg.findall("class"):
            cls_name = cls.attrib.get("name", "")
            counters = _read_counters(cls)
            c = counters.get(metric, {"missed": 0, "covered": 0})
            pct = _pct(c["missed"], c["covered"])
            if threshold is not None and pct >= threshold:
                continue
            rows.append((pkg_name, cls_name, counters, pct))

    rows.sort(key=lambda r: r[3])

    filter_desc = f" (package contains `{package_filter}`)" if package_filter else ""
    threshold_desc = f" (< {threshold}%)" if threshold is not None else ""
    lines = [
        f"## Class Coverage — `{project_name}`{filter_desc}{threshold_desc}",
        "",
        f"Sorted by {metric} coverage (worst first). Showing {len(rows)} class(es).",
        "",
        "| Class | Package | INSTR | BRANCH | LINE | METHOD | CLASS |",
        "|-------|---------|-------|--------|------|--------|-------|",
    ]

    for pkg_name, cls_name, counters, pct in rows:

        def fmt(t: str) -> str:
            c = counters.get(t, {})
            if not c:
                return "—"
            return f"{_pct(c['missed'], c['covered']):.1f}%"

        short_class = _short_class(cls_name)
        short_pkg = _short_pkg(pkg_name)
        lines.append(
            f"| `{short_class}` | `{short_pkg}` | {fmt('INSTRUCTION')} | {fmt('BRANCH')} | {fmt('LINE')} | {fmt('METHOD')} | {fmt('CLASS')} |"
        )

    return "\n".join(lines)


@mcp.tool()
def find_uncovered_code(
    report_path: str,
    threshold: float = 0.0,
    metric: str = "LINE",
    include_methods: bool = False,
) -> str:
    """Find classes (and optionally methods) with coverage below a threshold.

    By default finds completely uncovered code (threshold=0). Set threshold
    higher (e.g. 50) to find under-tested classes.

    Args:
        report_path: Absolute path to the JaCoCo XML report file.
        threshold: Coverage percentage below which to report. Default 0 (zero coverage only).
            E.g. 50 reports anything with < 50% coverage.
        metric: Coverage metric to apply the threshold to. Default LINE.
        include_methods: If True, also list individual uncovered/low-coverage methods
            within each affected class. Default False to keep output concise.
    """
    try:
        root = _parse_report(report_path)
    except RuntimeError as e:
        return f"ERROR: {e}"

    metric = metric.upper()
    project_name = root.attrib.get("name", "unknown")

    results: list[dict] = []

    for pkg in root.findall("package"):
        pkg_name = pkg.attrib.get("name", "")
        for cls in pkg.findall("class"):
            cls_name = cls.attrib.get("name", "")
            cls_counters = _read_counters(cls)
            c = cls_counters.get(metric, {"missed": 0, "covered": 0})
            pct = _pct(c["missed"], c["covered"])
            if pct > threshold:
                continue

            entry: dict = {
                "pkg": pkg_name,
                "cls": cls_name,
                "counters": cls_counters,
                "pct": pct,
                "methods": [],
            }

            if include_methods:
                for method in cls.findall("method"):
                    m_name = method.attrib.get("name", "")
                    m_line = method.attrib.get("line", "?")
                    m_counters = _read_counters(method)
                    m_c = m_counters.get(metric, {"missed": 0, "covered": 0})
                    m_pct = _pct(m_c["missed"], m_c["covered"])
                    if m_pct <= threshold:
                        entry["methods"].append((m_name, m_line, m_pct))

            results.append(entry)

    results.sort(key=lambda r: r["pct"])

    qualifier = f"= 0%" if threshold == 0 else f"< {threshold}%"
    lines = [
        f"## Uncovered Code — `{project_name}`",
        "",
        f"{metric} coverage {qualifier}. Found **{len(results)}** class(es).",
        "",
    ]

    if not results:
        lines.append("All classes meet the coverage threshold.")
        return "\n".join(lines)

    lines += [
        "| Class | Package | LINE % | INSTR % | BRANCH % | METHOD % |",
        "|-------|---------|--------|---------|----------|----------|",
    ]

    for entry in results:

        def fmt(t: str) -> str:
            c = entry["counters"].get(t, {})
            return f"{_pct(c['missed'], c['covered']):.1f}%" if c else "—"

        lines.append(
            f"| `{_short_class(entry['cls'])}` | `{_short_pkg(entry['pkg'])}` | {fmt('LINE')} | {fmt('INSTRUCTION')} | {fmt('BRANCH')} | {fmt('METHOD')} |"
        )

        if include_methods and entry["methods"]:
            for m_name, m_line, m_pct in entry["methods"]:
                lines.append(f"|   ↳ `{m_name}` (L{m_line}) | | {m_pct:.1f}% | | | |")

    return "\n".join(lines)


@mcp.tool()
def get_missed_lines(
    report_path: str,
    source_file: str,
    package: Optional[str] = None,
) -> str:
    """Get the exact missed line numbers for a specific source file.

    Reads the per-line coverage data from the JaCoCo report and returns which
    lines were not executed during testing. Useful for understanding exactly
    what code paths are untested.

    Line status key:
      - MISSED: line not executed at all
      - PARTIAL: line executed but some branches missed
      - COVERED: fully covered

    Args:
        report_path: Absolute path to the JaCoCo XML report file.
        source_file: Java source file name, e.g. "MyService.java".
            Case-insensitive partial match is supported.
        package: Optional package path substring to disambiguate if multiple
            packages contain a file with the same name, e.g. "managers/program".
    """
    try:
        root = _parse_report(report_path)
    except RuntimeError as e:
        return f"ERROR: {e}"

    project_name = root.attrib.get("name", "unknown")
    source_file_lower = source_file.lower()

    matches: list[tuple[str, ET.Element]] = []
    for pkg in root.findall("package"):
        pkg_name = pkg.attrib.get("name", "")
        if package and package.lower() not in pkg_name.lower():
            continue
        for sf in pkg.findall("sourcefile"):
            sf_name = sf.attrib.get("name", "")
            if source_file_lower in sf_name.lower():
                matches.append((pkg_name, sf))

    if not matches:
        return f"No source file matching `{source_file}` found in report."
    if len(matches) > 1:
        names = [f"`{pkg}/{sf.attrib['name']}`" for pkg, sf in matches]
        return f"Multiple matches found: {', '.join(names)}. Use the `package` parameter to disambiguate."

    pkg_name, sf_elem = matches[0]
    sf_name = sf_elem.attrib["name"]

    line_elems = sf_elem.findall("line")
    counters = _read_counters(sf_elem)

    missed_lines: list[int] = []
    partial_lines: list[tuple[int, int, int]] = []  # (nr, mb, cb)
    covered_lines: list[int] = []

    for line in line_elems:
        nr = int(line.attrib["nr"])
        mi = int(line.attrib["mi"])  # missed instructions
        ci = int(line.attrib["ci"])  # covered instructions
        mb = int(line.attrib["mb"])  # missed branches
        cb = int(line.attrib["cb"])  # covered branches

        if ci == 0 and mi > 0:
            missed_lines.append(nr)
        elif mb > 0:
            partial_lines.append((nr, mb, cb))
        else:
            covered_lines.append(nr)

    def fmt_ranges(line_nums: list[int]) -> str:
        if not line_nums:
            return "none"
        line_nums = sorted(line_nums)
        ranges = []
        start = end = line_nums[0]
        for n in line_nums[1:]:
            if n == end + 1:
                end = n
            else:
                ranges.append(f"{start}" if start == end else f"{start}–{end}")
                start = end = n
        ranges.append(f"{start}" if start == end else f"{start}–{end}")
        return ", ".join(ranges)

    def fmt_counter(c: dict) -> str:
        if not c:
            return "N/A"
        return _pct_str(c["missed"], c["covered"])

    lines = [
        f"## Missed Lines — `{sf_name}`",
        f"Package: `{pkg_name}`  |  Project: `{project_name}`",
        "",
        "### Coverage summary",
        "",
        "| Metric | Coverage |",
        "|--------|----------|",
    ]
    for t in ["INSTRUCTION", "BRANCH", "LINE", "METHOD"]:
        c = counters.get(t)
        if c:
            lines.append(f"| {t} | {fmt_counter(c)} |")

    lines += [
        "",
        f"### Missed lines ({len(missed_lines)})",
        "",
        fmt_ranges(missed_lines),
        "",
        f"### Partial lines ({len(partial_lines)}) — branch not fully covered",
        "",
    ]

    if partial_lines:
        lines.append("| Line | Missed branches | Covered branches |")
        lines.append("|------|-----------------|-----------------|")
        for nr, mb, cb in sorted(partial_lines):
            lines.append(f"| {nr} | {mb} | {cb} |")
    else:
        lines.append("none")

    return "\n".join(lines)


@mcp.tool()
def compare_coverage(
    report_path_a: str,
    report_path_b: str,
    metric: str = "LINE",
    label_a: str = "before",
    label_b: str = "after",
) -> str:
    """Compare coverage between two JaCoCo XML reports (e.g. before and after a change).

    Shows per-package coverage delta, highlighting regressions and improvements.

    Args:
        report_path_a: Path to the first (baseline) report.
        report_path_b: Path to the second (new) report.
        metric: Coverage metric to compare. Default LINE.
        label_a: Label for the first report. Default "before".
        label_b: Label for the second report. Default "after".
    """
    try:
        root_a = _parse_report(report_path_a)
        root_b = _parse_report(report_path_b)
    except RuntimeError as e:
        return f"ERROR: {e}"

    metric = metric.upper()

    def pkg_coverage(root: ET.Element) -> dict[str, float]:
        result: dict[str, float] = {}
        for pkg in root.findall("package"):
            name = pkg.attrib.get("name", "")
            counters = _read_counters(pkg)
            c = counters.get(metric, {"missed": 0, "covered": 0})
            result[name] = _pct(c["missed"], c["covered"])
        return result

    cov_a = pkg_coverage(root_a)
    cov_b = pkg_coverage(root_b)

    all_pkgs = sorted(set(cov_a) | set(cov_b))

    name_a = root_a.attrib.get("name", "A")
    name_b = root_b.attrib.get("name", "B")

    # Overall totals
    def total_counters(root: ET.Element) -> CounterMap:
        return _read_counters(root)

    tc_a = total_counters(root_a).get(metric, {"missed": 0, "covered": 0})
    tc_b = total_counters(root_b).get(metric, {"missed": 0, "covered": 0})
    pct_a = _pct(tc_a["missed"], tc_a["covered"])
    pct_b = _pct(tc_b["missed"], tc_b["covered"])
    delta_total = pct_b - pct_a
    delta_sign = "+" if delta_total >= 0 else ""

    lines = [
        f"## Coverage Comparison — {metric}",
        "",
        f"| | `{label_a}` | `{label_b}` | Delta |",
        f"|---|---|---|---|",
        f"| **Overall** | {pct_a:.1f}% | {pct_b:.1f}% | **{delta_sign}{delta_total:.1f}%** |",
        "",
        "### Per-package delta",
        "",
        f"| Package | {label_a} | {label_b} | Delta |",
        f"|---------|----------|----------|-------|",
    ]

    regressions = []
    improvements = []
    unchanged = []

    for pkg in all_pkgs:
        a = cov_a.get(pkg)
        b = cov_b.get(pkg)
        short = _short_pkg(pkg)

        if a is None:
            lines.append(f"| `{short}` | — (new) | {b:.1f}% | +{b:.1f}% |")
            improvements.append(pkg)
        elif b is None:
            lines.append(f"| `{short}` | {a:.1f}% | — (removed) | — |")
        else:
            delta = b - a
            sign = "+" if delta >= 0 else ""
            marker = " ⚠️" if delta < -1 else (" ✓" if delta > 1 else "")
            lines.append(f"| `{short}` | {a:.1f}% | {b:.1f}% | {sign}{delta:.1f}%{marker} |")
            if delta < -1:
                regressions.append(pkg)
            elif delta > 1:
                improvements.append(pkg)
            else:
                unchanged.append(pkg)

    lines += [
        "",
        f"**Regressions (>1% drop):** {len(regressions)}  |  "
        f"**Improvements (>1% gain):** {len(improvements)}  |  "
        f"**Unchanged:** {len(unchanged)}",
    ]

    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()

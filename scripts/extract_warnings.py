#!/usr/bin/env python3
"""Summarizes pbt-extract's warnings as Markdown for a build's step summary.

    extract_warnings.py LEAGUE LOG

LOG is pbt-extract's stderr. Each "pbt-extract: warning: " line is a warning. Warnings that
differ only in the item they name (an override, a passive, a row, a zoom level) are counted
under one line, with the item shown as "…"; any other warning is its own line. The full list
follows in a collapsed block. Without LOG (pbt-extract did not run) it writes nothing.
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

PREFIX = "pbt-extract: warning: "

# Pattern, then the parts it replaces with "…". Kept loose: a warning no pattern matches still
# shows, as written.
ITEMS = [
    re.compile(r"^override (\S+): "),
    re.compile(r"^ascendancy (\S+): "),
    re.compile(r"^timeless passive (\S+) has no name"),
    re.compile(r"^tree \S+ node (\S+): "),
    re.compile(r"^\S+ sprites at (\S+): "),
    re.compile(r"the buffs of passive (.+) are not carried$"),
    re.compile(r"^.*: named (\".*\"), unused; left out$"),
    re.compile(r"stat row (\d+) repeated"),
]


def parse(log: str) -> list[str]:
    return [line[len(PREFIX):] for line in log.splitlines() if line.startswith(PREFIX)]


def kind(warning: str) -> str:
    for pattern in ITEMS:
        m = pattern.search(warning)
        if m:
            start, end = m.span(1)
            warning = warning[:start] + "…" + warning[end:]
    return warning


def summary(league: str, warnings: list[str]) -> str:
    if not warnings:
        return f"### {league}: no warnings\n"
    counts = Counter(kind(w) for w in warnings)
    lines = [
        f"### {league}: {len(warnings)} warnings",
        "",
        "| Count | Warning |",
        "|--:|---|",
    ]
    for k, n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        lines.append(f"| {n} | {cell(k)} |")
    lines += ["", "<details><summary>Every warning</summary>", "", "```"]
    lines += sorted(warnings)
    lines += ["```", "", "</details>", ""]
    return "\n".join(lines)


def cell(text: str) -> str:
    return text.replace("|", "\\|")


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    league, path = argv[1], Path(argv[2])
    if path.exists():
        sys.stdout.write(summary(league, parse(path.read_text(encoding="utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

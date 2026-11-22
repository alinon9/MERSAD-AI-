#!/usr/bin/env python3
"""Remove legacy query-token propagation from the first-party browser dashboard."""
from __future__ import annotations

import re
from pathlib import Path

DASHBOARD = Path(__file__).resolve().with_name("dashboard.js")
if not DASHBOARD.is_file():
    raise SystemExit(f"FAIL: generated dashboard.js is missing: {DASHBOARD}")

source = DASHBOARD.read_text(encoding="utf-8")

# Remove the complete declaration statement containing the legacy read of
# location.search["k"]. This handles minifier changes in whitespace and in
# whether K and Q are declared together or in a comma-separated const chain.
capture_read = re.compile(
    r"""new\s+URLSearchParams\s*\(\s*location\.search\s*\)\s*\.get\s*\(\s*["']k["']\s*\)""",
    re.IGNORECASE,
)
reads = list(capture_read.finditer(source))
if len(reads) > 1:
    raise SystemExit(f"FAIL: found {len(reads)} reads of the browser k query parameter.")

for match in reversed(reads):
    pos = match.start()
    boundary = max(source.rfind(";", 0, pos), source.rfind("\n", 0, pos))
    declaration_matches = list(
        re.finditer(r"\b(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=", source[boundary + 1:pos])
    )
    if not declaration_matches:
        raise SystemExit("FAIL: found a query-token read but could not identify its containing variable declaration.")
    start = boundary + 1 + declaration_matches[-1].start()
    end = source.find(";", match.end())
    if end < 0:
        raise SystemExit("FAIL: query-token declaration has no terminating semicolon.")
    statement = source[start:end + 1]
    if "URLSearchParams" not in statement or ".get" not in statement:
        raise SystemExit("FAIL: refusing to remove an unexpected JavaScript statement around the query-token read.")
    source = source[:start] + source[end + 1:]
    print("[AUTH] Removed the complete declaration that read the session token from location.search.")

# qSep may already have been made identity by a previous source edit. If it
# still appends Q/K, replace the entire expression-bodied declaration.
qsep_pattern = re.compile(r"""\b(?:const|let|var)\s+qSep\s*=\s*u\s*=>[^;]*;""", re.MULTILINE)
identity_pattern = re.compile(r"""\bconst\s+qSep\s*=\s*u\s*=>\s*u\s*;""")
qsep_matches = list(qsep_pattern.finditer(source))
if len(qsep_matches) == 1:
    source = qsep_pattern.sub("const qSep=u=>u;", source, count=1)
    print("[AUTH] qSep now preserves URLs without appending credentials.")
elif len(qsep_matches) > 1:
    raise SystemExit(f"FAIL: found {len(qsep_matches)} qSep declarations.")
elif len(identity_pattern.findall(source)) == 1:
    print("[AUTH] qSep already uses identity URL handling.")
else:
    raise SystemExit("FAIL: qSep declaration was not found; refusing to patch unknown dashboard source.")

DASHBOARD.write_text(source, encoding="utf-8", newline="")
source = DASHBOARD.read_text(encoding="utf-8")

checks = {
    "literal query token": re.search(r"[?&]k=", source, re.IGNORECASE),
    "location.search token read": capture_read.search(source),
    "token URL encoding": re.search(r"encodeURIComponent\s*\(\s*K\s*\)", source),
    "legacy Q construction": re.search(r"\b(?:const|let|var)\s+Q\s*=\s*K\s*\?", source),
}
remaining = [name for name, match in checks.items() if match]
if remaining:
    # This reports only a short source-code context, never a runtime credential.
    literal = re.search(r"[?&]k=", source, re.IGNORECASE)
    context = ""
    if literal:
        context = repr(source[max(0, literal.start() - 160):min(len(source), literal.end() + 220)])
    raise SystemExit("FAIL: dashboard.js still contains legacy query-token logic: " + ", ".join(remaining) + " " + context)
if len(identity_pattern.findall(source)) != 1:
    raise SystemExit("FAIL: dashboard.js does not contain exactly one qSep identity helper.")

print("[AUTH] PASS: first-party dashboard uses same-origin cookies and never reads or appends a session token in query URLs.")

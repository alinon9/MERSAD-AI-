#!/usr/bin/env python3
"""Remove legacy query-token propagation from the browser dashboard.

The server may continue accepting ?k= for external legacy clients during the
migration window, but the first-party dashboard must rely on the HttpOnly
same-origin session cookie established by the initial redirect.
"""
from __future__ import annotations

import re
from pathlib import Path

DASHBOARD = Path(__file__).resolve().with_name("dashboard.js")
if not DASHBOARD.is_file():
    raise SystemExit(f"FAIL: generated dashboard.js is missing: {DASHBOARD}")

source = DASHBOARD.read_text(encoding="utf-8")

# Remove the whole declaration beginning with K=. The source is minified, and
# Q may be declared in the same const statement; matching to that statement's
# semicolon intentionally removes both values in one operation.
capture_pattern = re.compile(
    r"""(?:const|let|var)\s+K\s*=\s*new\s+URLSearchParams\s*\(\s*location\.search\s*\)\s*\.get\s*\(\s*["']k["']\s*\)[^;]*;""",
    re.MULTILINE,
)
capture_matches = list(capture_pattern.finditer(source))
if len(capture_matches) == 1:
    declaration = capture_matches[0].group(0)
    if "Q=" not in declaration.replace(" ", "") and "Q =" not in declaration:
        raise SystemExit("FAIL: K declaration found but Q query-token construction was not in the same statement.")
    if "?k=" not in declaration or "encodeURIComponent(K)" not in declaration:
        raise SystemExit("FAIL: K declaration did not match the expected legacy query-token construction.")
    source = capture_pattern.sub("", source, count=1)
    print("[AUTH] Removed legacy K/Q session-token capture from the browser URL.")
elif len(capture_matches) > 1:
    raise SystemExit(f"FAIL: found {len(capture_matches)} legacy K query-token declarations.")

# Any expression-bodied qSep helper is replaced with an identity URL helper.
qsep_pattern = re.compile(r"""(?:const|let|var)\s+qSep\s*=\s*u\s*=>[^;]*;""", re.MULTILINE)
identity_pattern = re.compile(r"""const\s+qSep\s*=\s*u\s*=>\s*u\s*;""")
qsep_matches = list(qsep_pattern.finditer(source))
if len(qsep_matches) == 1:
    source = qsep_pattern.sub("const qSep=u=>u;", source, count=1)
    print("[AUTH] Replaced qSep with identity URL handling.")
elif len(qsep_matches) > 1:
    raise SystemExit(f"FAIL: found {len(qsep_matches)} qSep declarations.")
elif len(identity_pattern.findall(source)) == 1:
    print("[AUTH] qSep already uses identity URLs.")
else:
    raise SystemExit("FAIL: qSep declaration was not found; refusing to patch unknown dashboard source.")

DASHBOARD.write_text(source, encoding="utf-8", newline="")
source = DASHBOARD.read_text(encoding="utf-8")

legacy_markers = (
    re.search(r"[?&]k=", source, re.IGNORECASE),
    re.search(r"new\s+URLSearchParams\s*\(\s*location\.search\s*\)\s*\.get\s*\(\s*['\"]k['\"]", source, re.IGNORECASE),
    re.search(r"encodeURIComponent\s*\(\s*K\s*\)", source),
    re.search(r"\b(?:const|let|var)\s+Q\s*=\s*K\s*\?", source),
)
if any(legacy_markers):
    pos = source.lower().find("?k=")
    context = source[max(0, pos - 180):pos + 220] if pos >= 0 else "token-capture marker remains without literal ?k="
    raise SystemExit(f"FAIL: dashboard.js still contains query-token capture/propagation: {context!r}")
if len(identity_pattern.findall(source)) != 1:
    raise SystemExit("FAIL: dashboard.js does not contain exactly one qSep identity helper.")

print("[AUTH] PASS: browser dashboard uses same-origin session cookies and emits no session-token query URLs.")

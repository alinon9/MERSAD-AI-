#!/usr/bin/env python3
"""Remove legacy query-token propagation from the browser dashboard.

The server may continue accepting ?k= for external legacy clients during the
migration window, but the first-party dashboard must rely on the HttpOnly
same-origin session cookie established by the initial redirect.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DASHBOARD = Path(__file__).resolve().with_name("dashboard.js")
if not DASHBOARD.is_file():
    raise SystemExit(f"FAIL: generated dashboard.js is missing: {DASHBOARD}")

source = DASHBOARD.read_text(encoding="utf-8")

# Match the minified query-token capture and URL propagation helper, allowing
# harmless whitespace and either quote style while requiring the full shape.
pattern = re.compile(
    r"""const\s+K\s*=\s*new\s+URLSearchParams\s*\(\s*location\.search\s*\)\s*\.get\s*\(\s*["']k["']\s*\)\s*\|\|\s*["']\s*"""
    r""",\s*Q\s*=\s*K\s*\?\s*["']\?k=["']\s*\+\s*encodeURIComponent\s*\(\s*K\s*\)\s*:\s*["']\s*;\s*"""
    r"""const\s+qSep\s*=\s*u\s*=>\s*Q\s*\?\s*\(\s*u\.includes\s*\(\s*["']\?["']\s*\)\s*\?\s*u\s*\+\s*["']&["']\s*\+\s*Q\.slice\s*\(\s*1\s*\)\s*:\s*u\s*\+\s*Q\s*\)\s*:\s*u\s*;""",
    re.MULTILINE,
)

matches = list(pattern.finditer(source))
identity = re.compile(r"""const\s+qSep\s*=\s*u\s*=>\s*u\s*;""")
if len(matches) == 1:
    source = pattern.sub("const qSep=u=>u;", source, count=1)
    DASHBOARD.write_text(source, encoding="utf-8", newline="")
    print("[AUTH] Removed query-token propagation from qSep; dashboard uses same-origin session cookies.")
elif len(matches) == 0 and len(identity.findall(source)) == 1:
    print("[AUTH] qSep already uses identity URLs; no change required.")
else:
    raise SystemExit(
        f"FAIL: expected one query-token qSep declaration or one identity qSep; "
        f"found propagation={len(matches)}, identity={len(identity.findall(source))}"
    )

source = DASHBOARD.read_text(encoding="utf-8")
legacy_markers = (
    re.search(r"[?&]k=", source, re.IGNORECASE),
    re.search(r"new\s+URLSearchParams\s*\(\s*location\.search\s*\)\s*\.get\s*\(\s*['\"]k['\"]", source, re.IGNORECASE),
    re.search(r"encodeURIComponent\s*\(\s*K\s*\)", source),
)
if any(legacy_markers):
    raise SystemExit("FAIL: dashboard.js still contains query-token capture or URL propagation.")
if len(identity.findall(source)) != 1:
    raise SystemExit("FAIL: dashboard.js does not contain exactly one qSep identity helper.")

print("[AUTH] PASS: browser dashboard no longer places the session token in API, image, stream, or export URLs.")

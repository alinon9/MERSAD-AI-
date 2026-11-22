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

# First remove the token capture/build declaration itself. It can remain
# unused even when qSep has already been switched to an identity helper.
capture_pattern = re.compile(
    r"""const\s+K\s*=\s*new\s+URLSearchParams\s*\(\s*location\.search\s*\)\s*\.get\s*\(\s*["']k["']\s*\)\s*\|\|\s*["']{2}\s*,\s*"""
    r"""Q\s*=\s*K\s*\?\s*["']\?k=["']\s*\+\s*encodeURIComponent\s*\(\s*K\s*\)\s*:\s*["']{2}\s*;""",
    re.MULTILINE,
)
capture_matches = list(capture_pattern.finditer(source))
if len(capture_matches) == 1:
    source = capture_pattern.sub("", source, count=1)
    print("[AUTH] Removed legacy URL query-token capture/build variables K and Q.")
elif len(capture_matches) > 1:
    raise SystemExit(f"FAIL: found {len(capture_matches)} query-token capture declarations; manual review required.")

# Replace the URL helper when it still propagates K/Q, or accept the identity
# form when it has already been patched in a prior build step.
propagation_pattern = re.compile(
    r"""const\s+qSep\s*=\s*u\s*=>\s*Q\s*\?\s*\(\s*u\.includes\s*\(\s*["']\?["']\s*\)\s*\?\s*u\s*\+\s*["']&["']\s*\+\s*Q\.slice\s*\(\s*1\s*\)\s*:\s*u\s*\+\s*Q\s*\)\s*:\s*u\s*;""",
    re.MULTILINE,
)
identity_pattern = re.compile(r"""const\s+qSep\s*=\s*u\s*=>\s*u\s*;""")
propagation_matches = list(propagation_pattern.finditer(source))
if len(propagation_matches) == 1:
    source = propagation_pattern.sub("const qSep=u=>u;", source, count=1)
    print("[AUTH] Replaced query-token qSep with identity URL handling.")
elif len(propagation_matches) > 1:
    raise SystemExit(f"FAIL: found {len(propagation_matches)} query-token qSep helpers.")
elif len(identity_pattern.findall(source)) == 1:
    print("[AUTH] qSep already uses identity URLs.")
else:
    raise SystemExit(
        f"FAIL: expected one query-token qSep or one identity qSep; "
        f"found propagation={len(propagation_matches)}, identity={len(identity_pattern.findall(source))}"
    )

DASHBOARD.write_text(source, encoding="utf-8", newline="")
source = DASHBOARD.read_text(encoding="utf-8")

legacy_markers = (
    re.search(r"[?&]k=", source, re.IGNORECASE),
    re.search(r"new\s+URLSearchParams\s*\(\s*location\.search\s*\)\s*\.get\s*\(\s*['\"]k['\"]", source, re.IGNORECASE),
    re.search(r"encodeURIComponent\s*\(\s*K\s*\)", source),
    re.search(r"\b(?:const|let|var)\s+Q\s*=\s*K\s*\?", source),
)
if any(legacy_markers):
    raise SystemExit("FAIL: dashboard.js still contains query-token capture or URL propagation.")
if len(identity_pattern.findall(source)) != 1:
    raise SystemExit("FAIL: dashboard.js does not contain exactly one qSep identity helper.")

print("[AUTH] PASS: browser dashboard uses same-origin session cookies and emits no session-token query URLs.")

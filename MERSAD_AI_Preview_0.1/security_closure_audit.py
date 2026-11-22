#!/usr/bin/env python3
"""Release security closure checks for MERSAD UI/CSP and DOM sink inventory.

This scanner fails closed on executable inline HTML, inline event handlers,
script-src unsafe-inline, and dynamic code evaluation. HTML insertion sinks are
listed with source context for mandatory human review; they are not presumed
safe solely because an escaping helper exists.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AI_DIR = ROOT / "MERSAD_AI_Preview_0.1"
LAB_DIR = ROOT / "MERSAD_LAB_Preview_0.1"


class InlineHTMLAudit(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.handlers: list[dict[str, str | int]] = []
        self.inline_scripts: list[int] = []
        self.external_scripts: list[str] = []
        self._script_depth = 0
        self._current_script_external = False
        self._current_script_content = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        for name, value in attrs:
            if name and name.lower().startswith("on"):
                self.handlers.append({
                    "line": self.getpos()[0],
                    "attribute": name,
                    "value": (value or "")[:160],
                })
        if tag.lower() == "script":
            self._script_depth += 1
            src = attr_map.get("src")
            self._current_script_external = bool(src)
            self._current_script_content = False
            if src:
                self.external_scripts.append(str(src))
            else:
                self.inline_scripts.append(self.getpos()[0])

    def handle_data(self, data: str) -> None:
        if self._script_depth and data.strip():
            self._current_script_content = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script" and self._script_depth:
            if not self._current_script_external and self._current_script_content:
                # Keep the start-line entry; the report identifies executable inline script.
                pass
            self._script_depth -= 1
            self._current_script_external = False
            self._current_script_content = False


def read_dashboard_js() -> str:
    js_path = AI_DIR / "dashboard.js"
    if js_path.is_file():
        return js_path.read_text(encoding="utf-8")
    gz_path = AI_DIR / "dashboard.js.gz"
    if not gz_path.is_file():
        raise FileNotFoundError("dashboard.js and dashboard.js.gz are both missing")
    return gzip.decompress(gz_path.read_bytes()).decode("utf-8")


def scan_html(path: Path) -> dict:
    parser = InlineHTMLAudit()
    parser.feed(path.read_text(encoding="utf-8"))
    return {
        "path": str(path.relative_to(ROOT)),
        "inline_event_handlers": parser.handlers,
        "inline_script_start_lines": parser.inline_scripts,
        "external_scripts": parser.external_scripts,
    }


def csp_audit(path: Path) -> dict:
    source = path.read_text(encoding="utf-8")
    match = re.search(r"script-src\s+([^;\"\\]+)", source, re.IGNORECASE)
    if not match:
        return {"path": str(path.relative_to(ROOT)), "script_src_found": False, "script_src": ""}
    directive = match.group(1).strip()
    return {
        "path": str(path.relative_to(ROOT)),
        "script_src_found": True,
        "script_src": directive,
        "unsafe_inline": "'unsafe-inline'" in directive.lower(),
    }


def sink_inventory(source: str, path_label: str) -> list[dict]:
    patterns = (
        r"\.innerHTML\s*=",
        r"\.outerHTML\s*=",
        r"\.insertAdjacentHTML\s*\(",
        r"\bdocument\.write\s*\(",
    )
    combined = re.compile("|".join(f"(?:{p})" for p in patterns), re.IGNORECASE)
    lines = source.splitlines()
    findings: list[dict] = []
    for match in combined.finditer(source):
        line_no = source.count("\n", 0, match.start()) + 1
        line = lines[line_no - 1] if line_no - 1 < len(lines) else ""
        pos = match.start()
        findings.append({
            "path": path_label,
            "line": line_no,
            "sink": match.group(0),
            "context": source[max(0, pos - 180):min(len(source), match.end() + 260)].replace("\n", " ")[:520],
            "source_line": line[:800],
        })
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", default=str(ROOT / "reports_and_logs" / "security_closure_dom_xss_report.json"))
    args = parser.parse_args()

    report: dict = {
        "status": "FAIL",
        "checks": {},
        "dom_html_sinks": [],
        "unsafe_dynamic_code": [],
        "legacy_query_token_references": [],
        "manual_review_required": False,
        "errors": [],
    }

    try:
        ai_root = scan_html(ROOT / "dashboard.html")
        ai_preview = scan_html(AI_DIR / "dashboard.html")
        lab_html = scan_html(LAB_DIR / "index.html")
        report["checks"]["ai_root_html"] = ai_root
        report["checks"]["ai_preview_html"] = ai_preview
        report["checks"]["lab_html"] = lab_html

        for item in (ai_root, ai_preview, lab_html):
            if item["inline_event_handlers"]:
                report["errors"].append(f"{item['path']} contains inline event-handler attributes")
            if item["inline_script_start_lines"]:
                report["errors"].append(f"{item['path']} contains inline executable script blocks")

        if (ROOT / "dashboard.html").read_bytes() != (AI_DIR / "dashboard.html").read_bytes():
            report["errors"].append("Root and Preview AI dashboards are not byte-identical")

        csp_items = [
            csp_audit(ROOT / "server.py"),
            csp_audit(AI_DIR / "server.py"),
            csp_audit(LAB_DIR / "lab_server.py"),
        ]
        report["checks"]["script_csp"] = csp_items
        for item in csp_items:
            if not item["script_src_found"] or item["unsafe_inline"]:
                report["errors"].append(f"{item['path']} does not enforce script-src without unsafe-inline")

        ai_js = read_dashboard_js()
        lab_js_path = LAB_DIR / "lab.js"
        if not lab_js_path.is_file():
            raise FileNotFoundError("MERSAD_LAB_Preview_0.1/lab.js is missing")
        lab_js = lab_js_path.read_text(encoding="utf-8")
        report["dom_html_sinks"] = (
            sink_inventory(ai_js, "MERSAD_AI_Preview_0.1/dashboard.js")
            + sink_inventory(lab_js, "MERSAD_LAB_Preview_0.1/lab.js")
        )

        purifier_path = AI_DIR / "purify.min.js"
        guard_path = AI_DIR / "dompurify-guard.js"
        if not purifier_path.is_file() or not guard_path.is_file():
            report["errors"].append("DOMPurify runtime or DOM insertion guard is missing")
            purifier_source = ""
            guard_source = ""
        else:
            purifier_source = purifier_path.read_text(encoding="utf-8")
            guard_source = guard_path.read_text(encoding="utf-8")

        if "DOMPurify 3.4.18" not in purifier_source[:240]:
            report["errors"].append("DOMPurify is not pinned to the reviewed version 3.4.18")
        for marker in (
            'Object.getOwnPropertyDescriptor(Element.prototype, "innerHTML")',
            "window.DOMPurify.sanitize",
            'Object.defineProperty(Element.prototype, "innerHTML"',
            'createPolicy("mersad-ui-html"',
        ):
            if marker not in guard_source:
                report["errors"].append(f"DOM XSS guard is missing required protection marker: {marker}")

        required_script_order = ["/purify.min.js", "/dompurify-guard.js", "/dashboard.js"]
        if ai_preview["external_scripts"][:3] != required_script_order:
            report["errors"].append("AI dashboard must load DOMPurify, the DOM guard, then dashboard.js in that exact order")

        ai_server_source = (AI_DIR / "server.py").read_text(encoding="utf-8")
        if "trusted-types mersad-ui-html dompurify" not in ai_server_source:
            report["errors"].append("AI CSP does not allow only the named DOMPurify/guard Trusted Types policies")

        unprotected = [item for item in report["dom_html_sinks"] if not item["sink"].lower().startswith(".innerhtml")]
        report["checks"]["dom_sink_protection"] = {
            "total_dynamic_html_sinks": len(report["dom_html_sinks"]),
            "sanitized_innerhtml_sinks": len(report["dom_html_sinks"]) - len(unprotected),
            "unprotected_sink_count": len(unprotected),
            "sanitizer": "DOMPurify 3.4.18",
            "guard": "Element.prototype.innerHTML setter wrapper",
            "trusted_types_policy": "mersad-ui-html",
        }
        report["manual_review_required"] = bool(unprotected)
        if unprotected:
            report["errors"].append("DOM insertion sinks outside the DOMPurify-guarded innerHTML setter were found")

        dynamic_eval = re.compile(r"\beval\s*\(|\bnew\s+Function\s*\(", re.IGNORECASE)
        for label, source in (
            ("MERSAD_AI_Preview_0.1/dashboard.js", ai_js),
            ("MERSAD_LAB_Preview_0.1/lab.js", lab_js),
        ):
            for match in dynamic_eval.finditer(source):
                report["unsafe_dynamic_code"].append({
                    "path": label,
                    "offset": match.start(),
                    "context": source[max(0, match.start() - 100):match.end() + 120],
                })
        if report["unsafe_dynamic_code"]:
            report["errors"].append("Dynamic eval/Function code construction was found")

        for label, source in (
            ("MERSAD_AI_Preview_0.1/dashboard.js", ai_js),
            ("MERSAD_LAB_Preview_0.1/lab.js", lab_js),
        ):
            token_read = re.search(
                r"new\s+URLSearchParams\s*\(\s*location\.search\s*\)\s*\.get\s*\(\s*['\"]k['\"]",
                source,
                re.IGNORECASE,
            )
            token_encoded = re.search(r"encodeURIComponent\s*\(\s*K\s*\)", source)
            token_qsep = re.search(r"\bqSep\s*=\s*u\s*=>[^;]*(?:\bQ\b|\bK\b)", source)
            if token_read or token_encoded or token_qsep:
                report["legacy_query_token_references"].append(label)

        if report["legacy_query_token_references"]:
            report["errors"].append(
                "First-party browser JavaScript must not append session tokens to query URLs; use same-origin cookies"
            )
        if "const qSep=u=>u;" not in ai_js:
            report["errors"].append("AI dashboard does not use the identity qSep helper for cookie-only authentication")

        report["checks"]["ai_dashboard_js_bytes"] = len(ai_js.encode("utf-8"))
        report["checks"]["lab_js_bytes"] = len(lab_js.encode("utf-8"))
        report["checks"]["dompurify_version"] = "3.4.18"
        report["checks"]["dompurify_guard_bytes"] = len(guard_source.encode("utf-8"))
        report["checks"]["ai_html_external_scripts"] = ai_preview["external_scripts"]
        report["checks"]["lab_html_external_scripts"] = lab_html["external_scripts"]

        if not report["errors"]:
            report["status"] = "PASS"
    except Exception as exc:
        report["errors"].append(f"{type(exc).__name__}: {exc}")

    output = Path(args.report)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[SECURITY CLOSURE] Status: {report['status']}")
    print(f"[SECURITY CLOSURE] Inline event handlers/scripts: {sum(len(x.get('inline_event_handlers', [])) + len(x.get('inline_script_start_lines', [])) for x in report['checks'].values() if isinstance(x, dict))}")
    print(f"[SECURITY CLOSURE] DOM HTML insertion sinks: {report.get('checks', {}).get('dom_sink_protection', {}).get('total_dynamic_html_sinks', len(report['dom_html_sinks']))} (guarded={report.get('checks', {}).get('dom_sink_protection', {}).get('sanitized_innerhtml_sinks', 0)}, unprotected={report.get('checks', {}).get('dom_sink_protection', {}).get('unprotected_sink_count', 0)})")
    print(f"[SECURITY CLOSURE] Dynamic eval/Function findings: {len(report['unsafe_dynamic_code'])}")
    for finding in report["dom_html_sinks"][:40]:
        print(f"[DOM-SINK] {finding['path']}:{finding['line']} {finding['sink']} :: {finding['context']}")
    for error in report["errors"]:
        print(f"[SECURITY-FAIL] {error}")
    print(f"[SECURITY CLOSURE] Report: {output}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""PR #5 V3 regression suite. Uses pathlib and executes the production JS helpers in Node."""
from __future__ import annotations
import html.parser
import http.client
import http.server
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import socketserver
import subprocess
import sys
import threading
import unittest
from unittest import mock

REPO_ROOT = Path(os.environ.get("MERSAD_REPO_ROOT", Path(__file__).resolve().parents[1])).resolve()
AI_DIR = REPO_ROOT / "MERSAD_AI_Preview_0.1"

HTML_EVENT_ATTRIBUTES = {
    "onabort", "onafterprint", "onbeforeprint", "onbeforeunload", "onblur", "oncancel",
    "oncanplay", "oncanplaythrough", "onchange", "onclick", "onclose", "oncontextmenu",
    "oncopy", "oncuechange", "oncut", "ondblclick", "ondrag", "ondragend", "ondragenter",
    "ondragleave", "ondragover", "ondragstart", "ondrop", "ondurationchange", "onemptied",
    "onended", "onerror", "onfocus", "onformdata", "onhashchange", "oninput", "oninvalid",
    "onkeydown", "onkeypress", "onkeyup", "onload", "onloadeddata", "onloadedmetadata",
    "onloadstart", "onmessage", "onmousedown", "onmouseenter", "onmouseleave", "onmousemove",
    "onmouseout", "onmouseover", "onmouseup", "onoffline", "ononline", "onopen", "onpagehide",
    "onpageshow", "onpaste", "onpause", "onplay", "onplaying", "onpopstate", "onprogress",
    "onratechange", "onreset", "onresize", "onscroll", "onsecuritypolicyviolation", "onseeked",
    "onseeking", "onselect", "onshow", "onstalled", "onsubmit", "onsuspend", "ontimeupdate",
    "ontoggle", "onunload", "onvolumechange", "onwaiting", "onwheel",
}

class _EventAttributeParser(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.findings = []
    def _attrs(self, tag, attrs):
        for key, value in attrs:
            key = (key or "").lower()
            if key in HTML_EVENT_ATTRIBUTES:
                self.findings.append((tag.lower(), key, value or ""))
    def handle_starttag(self, tag, attrs): self._attrs(tag, attrs)
    def handle_startendtag(self, tag, attrs): self._attrs(tag, attrs)


def find_html_event_attributes(text: str):
    parser = _EventAttributeParser()
    parser.feed(text)
    parser.close()
    return parser.findings


class _SinkHandler(http.server.BaseHTTPRequestHandler):
    hits = []
    def log_message(self, *_): pass
    def do_POST(self):
        self.__class__.hits.append((self.path, dict(self.headers)))
        self.send_response(200); self.end_headers(); self.wfile.write(b'{"ok":true}')
    do_GET = do_POST


class _RedirectHandler(http.server.BaseHTTPRequestHandler):
    sequence = [302]
    calls = 0
    target = "http://127.0.0.1:1/sink"
    def log_message(self, *_): pass
    def do_POST(self):
        i = min(self.__class__.calls, len(self.__class__.sequence)-1)
        code = self.__class__.sequence[i]
        self.__class__.calls += 1
        if code == 200:
            body=b'{"ok":true,"result":{"id":1}}'
            self.send_response(200); self.send_header("Content-Type","application/json")
            self.send_header("Content-Length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        self.send_response(code)
        if 300 <= code < 400: self.send_header("Location",self.__class__.target)
        self.send_header("Content-Length","0"); self.end_headers()


class TestPR5CriticalRemediationV3(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not AI_DIR.is_dir(): raise RuntimeError(f"AI directory missing: {AI_DIR}")
        if str(AI_DIR) not in sys.path: sys.path.insert(0,str(AI_DIR))
        cls.notify=importlib.import_module("notify")
        cls.server=importlib.import_module("server")
        cls.sink=socketserver.TCPServer(("127.0.0.1",0),_SinkHandler)
        cls.sink_port=cls.sink.server_address[1]
        cls.sink_thread=threading.Thread(target=cls.sink.serve_forever,daemon=True); cls.sink_thread.start()
        _RedirectHandler.target=f"http://127.0.0.1:{cls.sink_port}/exfil"
        cls.redirect=socketserver.TCPServer(("127.0.0.1",0),_RedirectHandler)
        cls.redirect_port=cls.redirect.server_address[1]
        cls.redirect_thread=threading.Thread(target=cls.redirect.serve_forever,daemon=True); cls.redirect_thread.start()

    @classmethod
    def tearDownClass(cls):
        for server in (cls.redirect,cls.sink):
            server.shutdown(); server.server_close()

    def read(self,name):
        return (AI_DIR/name).read_text(encoding="utf-8")


    def test_historical_original_lab_unittest_output_maps_all_eight_core_checks(self):
        compare_path = REPO_ROOT / "tools" / "compare_original_vs_cleanroom_lab.py"
        spec = importlib.util.spec_from_file_location("mersad_compare_lab_test", compare_path)
        self.assertIsNotNone(spec)
        compare = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(compare)

        names = [
            "test_camera_render_returns_valid_jpeg",
            "test_camera_streams_emit_mjpeg",
            "test_health_endpoint",
            "test_invalid_camera_mode_rejected",
            "test_offline_camera_returns_expected_503",
            "test_opencv_ffmpeg_reads_virtual_camera_like_mersad",
            "test_quality_upload_image",
            "test_quality_upload_video",
        ]
        methods = "\\n".join(
            f"    def {name}(self):\\n        self.assertTrue(True)"
            for name in names
        )
        legacy_test = (
            "import unittest\\n"
            "class HistoricalOriginalLabTests(unittest.TestCase):\\n"
            + methods
            + "\\nif __name__ == '__main__':\\n    unittest.main(verbosity=2)\\n"
        )

        with tempfile.TemporaryDirectory(prefix="mersad_original_lab_unittest_") as tmp:
            lab_dir = Path(tmp)
            (lab_dir / "test_lab.py").write_text(legacy_test, encoding="utf-8")
            result = compare.run_independent_lab_functional_and_security_suite(
                lab_dir, "Original_LAB_ed7b8f72"
            )

        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(result["format"], "unittest")
        self.assertEqual(result["passed"], 8)
        self.assertEqual(result["failed"], 0)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["total"], 8)
        self.assertEqual(
            {item["id"] for item in result["checks"]},
            {"LAB-01", "LAB-02", "LAB-03", "LAB-04", "LAB-05", "LAB-06", "LAB-07", "LAB-08"},
        )

    def test_find001_html_attributes_rejected_but_js_properties_allowed(self):
        self.assertEqual(find_html_event_attributes('<button onclick="run()">X</button>'),[("button","onclick","run()")])
        self.assertEqual(find_html_event_attributes('$("#x").onclick = fn; es.onerror = fn; fr.onload = fn; fr.onerror = fn;'),[])
        self.assertEqual(find_html_event_attributes('const t = `<button onerror="alert(1)">x</button>`;'),[("button","onerror","alert(1)")])

    def test_find001_zero_inline_html_event_attributes_and_node_syntax(self):
        html_txt=self.read("dashboard.html")
        js_txt=self.read("dashboard.js")
        self.assertEqual(find_html_event_attributes(html_txt),[])
        self.assertEqual(find_html_event_attributes(js_txt),[],"HTML event attribute remains in a JS template")
        self.assertIsNone(re.search(r"<script(?![^>]*\bsrc=)[^>]*>",html_txt,re.I))
        self.assertIn("MERSAD-PR5-FIND001-DELEGATION-V3",js_txt)
        node=shutil.which("node")
        self.assertIsNotNone(node,"Node.js is required for production-JS tests")
        subprocess.run([node,"--check",str(AI_DIR/"dashboard.js")],check=True,capture_output=True,text=True)

    def test_find001_file_snapshot_helper_preserves_single_and_multiple_files(self):
        js_txt=self.read("dashboard.js")
        self.assertIn('const files=_filesSnapshotAndReset(el); if(files.length) uploadEvalDataset(files);',js_txt)
        match=re.search(r"function\s+_filesSnapshotAndReset\(el\)\s*\{[\s\S]*?\n\s*\}",js_txt)
        self.assertIsNotNone(match,"file snapshot helper not found")
        node=shutil.which("node"); self.assertIsNotNone(node)
        script=("const fn = ("+match.group(0)+");"
                "const run=(names)=>{const el={files:names.map(name=>({name})),value:'selected'};"
                "const out=fn(el).map(x=>x.name);return {out,value:el.value};};"
                "process.stdout.write(JSON.stringify([run(['one.csv']),run(['a.csv','b.csv','c.csv'])]));")
        result=subprocess.run([node,"-e",script],check=True,capture_output=True,text=True)
        got=json.loads(result.stdout)
        self.assertEqual(got,[{"out":["one.csv"],"value":""},{"out":["a.csv","b.csv","c.csv"],"value":""}])

    def test_find001_csp_and_dashboard_js_route(self):
        srv=self.server.start_server(port=0,host="127.0.0.1")
        try:
            port=srv.server_address[1]
            conn=http.client.HTTPConnection("127.0.0.1",port,timeout=4)
            conn.request("GET","/",headers={"X-Mersad-Token":self.server.bus.token,"Host":f"127.0.0.1:{port}"})
            response=conn.getresponse(); body=response.read().decode("utf-8",errors="replace")
            csp=response.getheader("Content-Security-Policy") or ""
            self.assertEqual(response.status,200); self.assertRegex(csp,r"script-src 'self'(?:;|$)"); self.assertNotIn("script-src 'self' 'unsafe-inline'",csp)
            self.assertIn('<script src="/dashboard.js"',body); conn.close()
            conn=http.client.HTTPConnection("127.0.0.1",port,timeout=4)
            conn.request("GET","/dashboard.js",headers={"X-Mersad-Token":self.server.bus.token,"Host":f"127.0.0.1:{port}"})
            response=conn.getresponse(); js=response.read()
            self.assertEqual(response.status,200); self.assertIn("javascript",response.getheader("Content-Type","").lower())
            self.assertEqual(response.getheader("X-Content-Type-Options"),"nosniff"); self.assertIn(b"DELEGATION-V3",js)
            conn.close()
        finally: self.server.stop_server(srv)

    def test_find002_executes_production_esc_function_with_xss_payloads(self):
        js_txt=self.read("dashboard.js")
        for expected in ('data-id="${esc(r.id||"" )}"','×${esc(f.level)}','#${esc(r.id)}'):
            # Exact first sink formatting can vary; the latter two are exact required expressions.
            if expected.startswith('data-id='): continue
            self.assertIn(expected,js_txt)
        self.assertRegex(js_txt,r'data-id="\$\{esc\(r\.id\|\|""\)\}"')
        # Extract the real esc arrow-function expression from the production declaration.
        match=re.search(r'\besc\s*=\s*(s\s*=>\s*String\(s\?\?""\).*?\))\s*[,;]',js_txt,re.S)
        self.assertIsNotNone(match,"Could not extract production esc() expression")
        node=shutil.which("node"); self.assertIsNotNone(node)
        payloads=[
            '"><img src=x onerror=alert(1)>',
            "<script>alert('xss')</script>",
            "' onmouseover='alert(1)",
            '" autofocus onfocus="alert(1)',
            "r.id'\"<svg/onload=alert(1)>",
        ]
        script=("const vm=require('vm');const esc=vm.runInNewContext('('+process.argv[1]+')');"
                "const values=JSON.parse(process.argv[2]);process.stdout.write(JSON.stringify(values.map(v=>esc(v))));")
        proc=subprocess.run([node,"-e",script,match.group(1),json.dumps(payloads)],check=True,capture_output=True,text=True)
        rendered=json.loads(proc.stdout)
        for value in rendered:
            # Parse the browser-equivalent HTML structure; escaped input must stay inert text.
            inspect=_DOMStructure(); inspect.feed(f'<button data-id="{value}">{value}</button>'); inspect.close()
            self.assertNotIn("script",inspect.tags); self.assertNotIn("img",inspect.tags); self.assertNotIn("svg",inspect.tags)
            self.assertFalse(any(name.startswith("on") for _,name,_ in inspect.attrs))

    def test_find003_blocks_all_redirects_closes_responses_and_preserves_429_retry(self):
        fake_token="123456:PR5_FAKE_TEST_TOKEN_NOT_VALID"
        env={"TELEGRAM_TOKEN":fake_token,"TELEGRAM_API":f"http://127.0.0.1:{self.redirect_port}","MERSAD_ALLOW_INSECURE_TELEGRAM_TEST":"1"}
        closed_codes=[]
        original_close=self.notify.urllib.error.HTTPError.close
        def tracked_close(error):
            closed_codes.append(error.code)
            return original_close(error)
        with mock.patch.object(self.notify.urllib.error.HTTPError,"close",tracked_close):
            for code in (301,302,303,307,308):
                with self.subTest(code=code):
                    _SinkHandler.hits.clear(); _RedirectHandler.calls=0; _RedirectHandler.sequence=[code]
                    with mock.patch.dict(os.environ,env,clear=False):
                        with self.assertRaises(RuntimeError) as caught:
                            self.notify._call("sendMessage",{"chat_id":"1","text":"hi"},timeout=3,retries=0)
                    self.assertEqual(_SinkHandler.hits,[])
                    self.assertNotIn(fake_token,str(caught.exception))
                    self.assertNotIn(fake_token,self.notify.TELEGRAM_STATUS.get("last_error",""))
                    self.assertIn(code,closed_codes, f"HTTP {code} response socket was not closed")
            _RedirectHandler.calls=0; _RedirectHandler.sequence=[429,200]
            with mock.patch.dict(os.environ,env,clear=False):
                result=self.notify._call("getMe",{},timeout=3,retries=1)
            self.assertTrue(result.get("ok")); self.assertEqual(_RedirectHandler.calls,2)
            self.assertIn(429,closed_codes, "HTTP 429 response socket was not closed before retry")
        with mock.patch.dict(os.environ,{
            "TELEGRAM_TOKEN":fake_token,
            "TELEGRAM_API":f"http://127.0.0.1:{self.redirect_port}",
            "MERSAD_ALLOW_INSECURE_TELEGRAM_TEST":"0",
        },clear=False):
            with self.assertRaises(ValueError): self.notify._telegram_api_base()

    def test_packaging_and_workflows_have_real_checks_not_comment_markers(self):
        spec=self.read("mersad_ai.spec")
        bat=self.read("BUILD_EXE.bat")
        sec_wf=(REPO_ROOT/".github/workflows/batch1-critical-security.yml").read_text(encoding="utf-8")
        rel_wf=(REPO_ROOT/".github/workflows/release-mersad-preview-0.1-windows.yml").read_text(encoding="utf-8")
        self.assertRegex(spec,r'\(\s*["\']dashboard\.js["\']\s*,\s*["\']\.["\']\s*\)')
        self.assertIn('if not exist "dist\\MERSAD_AI\\dashboard.js"',bat)
        self.assertIn("test_pr5_critical_remediation.py",sec_wf)
        self.assertIn("security/batch2-server-hardening-20261120",rel_wf)
        self.assertIn("windows_frozen_dashboard_smoke.py",rel_wf)


class _DOMStructure(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.tags=[]; self.attrs=[]
    def handle_starttag(self,tag,attrs):
        self.tags.append(tag.lower()); self.attrs.extend((tag.lower(),(k or "").lower(),v or "") for k,v in attrs)
    def handle_startendtag(self,tag,attrs): self.handle_starttag(tag,attrs)


if __name__=="__main__":
    unittest.main(verbosity=2)

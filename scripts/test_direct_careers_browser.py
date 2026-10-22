"""Explicit local-browser E2E; real documents stay local, no employer is contacted.

The test transport maps one approved hosted identity onto a loopback fixture only
inside this script. Production ATS identity checks and URL admission are untouched.
"""
import argparse
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import sys
import threading
from unittest.mock import patch
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from modules.direct_careers_apply import (application_url, digest, export_applications, load_queue, plan_queue,
                                          run_queue, summarize, text_digest, write_json)
from modules.external_apply import identify_ats, snapshot as production_snapshot
from modules.job_pipeline.models import StageResult, read_artifact, write_artifact

HTML = """<!doctype html><html><head><title>Software Engineer - Inference Platform @ Baseten</title>
<meta name="viewport" content="width=device-width,initial-scale=1"><style>
body{font:16px system-ui;max-width:900px;margin:30px auto;padding:0 25px;color:#172538}header{padding:16px;background:#fff2c5;border:2px solid #d68d00;border-radius:8px}form{display:grid;grid-template-columns:1fr 1fr;gap:17px;margin-top:22px}[hidden]{display:none!important}label,fieldset{display:block;padding:8px;border:1px solid #ccd6e0;border-radius:6px}input:not([type=checkbox]):not([type=radio]),textarea,select{display:block;margin-top:7px;width:95%;padding:8px;font:inherit}fieldset label{border:0;padding:4px}button{background:#174dbd;color:white;padding:14px;font:inherit;border:0;border-radius:5px}textarea{height:75px}h1{font-size:25px}.wide{grid-column:1/-1}#success{padding:30px;background:#e0f6df;margin-top:25px}
</style></head><body><header><b>SYNTHETIC LOCAL ATS TEST — no employer submission</b><br>Real browser controls and local resume attachment. All candidate answers are synthetic.</header>
<h1>Software Engineer - Inference Platform</h1><p>Baseten posting identity represented only by the test transport.</p>
<form id="application"><label>Full name *<input name="_systemfield_name" required></label>
<label>Email *<input name="_systemfield_email" type="email" required></label>
<label class="wide">Resume *<input id="_systemfield_resume" name="_systemfield_resume" type="file" accept=".pdf" required></label>
<label>Preferred location *<select name="location" required><option value="">Select location</option><option>San Francisco</option><option>Remote</option></select></label>
<fieldset><legend>Are you legally authorized to work in the United States? *</legend><label><input type="radio" name="work_authorization" value="yes" required>Yes</label><label><input type="radio" name="work_authorization" value="no" required>No</label></fieldset>
<label>Languages and tools *<select name="tools" multiple required><option>Python</option><option>Kubernetes</option><option>Rust</option></select></label>
<label>Why are you interested? *<textarea name="motivation" required maxlength="500"></textarea></label>
<label class="wide"><input type="checkbox" name="consent" required>I consent to process this synthetic test application.</label>
<button class="wide" type="submit">Submit application</button></form>
<script>window.fixtureSubmissions=0;document.getElementById('application').addEventListener('submit',event=>{event.preventDefault();window.fixtureSubmissions++;history.pushState({},'',location.pathname+'/thanks');document.getElementById('application').hidden=true;const done=document.createElement('h2');done.id='success';done.textContent='Application successfully submitted';document.body.appendChild(done);});</script></body></html>"""


@contextmanager
def fixture_server():
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append({"method": "GET", "path": self.path})
            payload = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        def do_POST(self):
            requests.append({"method": "POST", "path": self.path})
            self.send_error(405, "No applicant data is sent in this fixture")
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def run_one(args, mode, role, base, *, optimized_map=None, generator=None):
    from selenium import webdriver
    directory = base / mode
    directory.mkdir(parents=True, exist_ok=True)
    input_path, queue_path = directory / "verified-role.json", directory / "queue.json"
    write_artifact(StageResult.create("verified_roles", "synthetic-local-browser", "fixture:verify", [role]), input_path)
    queue = plan_queue(input_path, queue_path, args.source_docx, args.source_pdf, resume_mode=mode, optimized_map=optimized_map)
    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-background-networking")
    options.add_argument("--window-size=1280,1250")
    # Chrome itself also cannot connect to any remote employer/API address.
    options.add_argument("--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost, EXCLUDE 127.0.0.1")
    browser = webdriver.Chrome(options=options)
    review_metadata = []
    questions = {"version": 1, "ai": {"enabled": False}, "answers": [
        {"question": "Preferred location", "type": "select", "answer": "San Francisco"},
        {"question": "Are you legally authorized to work in the United States?", "type": "radio", "answer": "Yes"},
        {"question": "Languages and tools", "type": "multiselect", "answer": ["Python", "Kubernetes"]},
        {"question": "Why are you interested?", "type": "textarea", "answer": "Synthetic interest in reliable inference systems and Python APIs."},
        {"question": "I consent to process this synthetic test application.", "type": "checkbox", "answer": True}]}
    try:
        with fixture_server() as (local_origin, requests):
            expected = identify_ats(role["career_url"])
            ats_origin = "https://" + urlparse(role["career_url"]).netloc
            class Transport:
                def get(self, url):
                    assert identify_ats(url).key == expected.key
                    parsed = urlparse(url)
                    browser.get(local_origin + parsed.path)
                def execute_script(self, *arguments):
                    return browser.execute_script(*arguments)
                def quit(self):
                    pass  # Capture final state below; the outer finally owns real browser cleanup.
            transport = Transport()
            def local_snapshot(driver):
                state = production_snapshot(driver)
                assert state["url"].startswith(local_origin + "/")
                state["url"] = ats_origin + state["url"][len(local_origin):]
                return state
            def review(details):
                current = load_queue(queue_path)
                assert details["status"] == "awaiting_review"
                assert not details["manual_questions"], details["manual_questions"]
                assert details["resume_sha256"] == current["records"][0]["resume"]["pdf"]["sha256"]
                assert len(details["answer_preview"]) == 8
                assert details["answer_preview"][0]["type"] == "document"
                assert details["answer_preview"][0]["answer"] == current["records"][0]["resume"]["pdf"]["path"]
                review_metadata.extend(details["question_metadata"])
                browser.execute_script("window.scrollTo(0,0)")
                browser.save_screenshot(str(directory / "prepared-form.png"))
                return "Submit application"  # Authorizes ONLY this local synthetic form.
            with patch("modules.external_apply.snapshot", local_snapshot), patch("modules.ai.resume_optimizer.OpenAI", side_effect=AssertionError("No model call allowed")), patch("modules.ai.resume_optimizer.load_openai_key", side_effect=AssertionError("No legacy key loader")):
                result = run_queue(queue_path, execute=True, browser_factory=lambda: transport,
                                   candidate={"full_name": "Synthetic Test Applicant", "email": "synthetic@example.test"},
                                   review=review, question_config=questions, max_applications=1, max_attempts=1,
                                   generate_resumes=mode == "generated", generate=generator,
                                   selected_role_ids=[role["id"]] if mode == "generated" else [])
            assert result["records"][0]["status"] == "applied", result["records"][0]["attempts"]
            assert browser.execute_script("return window.fixtureSubmissions") == 1
            assert all(request["method"] == "GET" for request in requests)
            browser.execute_script("window.scrollTo(0,0)")
            browser.save_screenshot(str(directory / "confirmed-form.png"))
            write_artifact(export_applications(result), directory / "applications.json")
            summary = {**summarize(result), "browser": browser.capabilities["browserVersion"],
                       "synthetic_local_browser_test": True, "real_employer_submission": False,
                       "network_target": "127.0.0.1 only", "fixture_submission_count": 1,
                       "actual_selected_resume_sha256": result["records"][0]["resume"]["pdf"]["sha256"],
                       "source_sha256_unchanged": digest(args.source_docx) == queue["source_resume"]["docx"]["sha256"],
                       "question_metadata": review_metadata, "http_requests": requests,
                       "ai_calls": 0, "linkedin_search_calls": 0, "all_assertions_passed": True,
                       "generator_invocations": result["invocations"][-1]["generation_count"],
                       "generator_kind": "injected_previously_validated_real_AI_artifact" if mode == "generated" else "not_used"}
            write_json(directory / "browser-e2e-report.json", summary)
            return summary
    finally:
        browser.quit()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--source-docx", required=True)
    parser.add_argument("--source-pdf", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--optimized-pdf")
    parser.add_argument("--optimized-docx")
    parser.add_argument("--match-report")
    parser.add_argument("--exercise-generated", action="store_true", help="Also exercise lazy generation through a safe injected generator using the selected validated artifacts; never calls an API")
    args = parser.parse_args()
    rows = read_artifact(args.input, "verified_roles").records
    role = next(row for row in rows if row.get("title") == "Software Engineer - Inference Platform")
    output = Path(args.output_dir).expanduser().resolve()
    original = run_one(args, "original", role, output)
    results = {"original": original}
    # Original mode must pass first; the same real optimized artifact is tested second.
    if args.optimized_pdf and args.optimized_docx and args.match_report:
        selected = {role["id"]: {"pdf": args.optimized_pdf, "docx": args.optimized_docx,
                                 "report": args.match_report, "job_description_sha256": text_digest(role["description"])}}
        results["optimized"] = run_one(args, "optimized", role, output, optimized_map=selected)
        if args.exercise_generated:
            calls = []
            def fixture_generator(**arguments):
                assert arguments["job_description"] == role["description"]
                assert arguments["job_title"] == role["title"]
                inputs = Path(arguments["resume_path"])
                assert digest(inputs) == digest(args.source_docx)
                assert digest(inputs.with_suffix(".pdf")) == digest(args.source_pdf)
                folder = inputs.parent.parent / "temp"
                folder.mkdir()
                pdf = folder / "fixture-generated.pdf"
                shutil.copyfile(args.optimized_pdf, pdf)
                shutil.copyfile(args.optimized_docx, pdf.with_suffix(".docx"))
                report = json.loads(Path(args.match_report).read_text(encoding="utf-8"))
                report.update(job_id=arguments["job_id"], job_title=arguments["job_title"], output_path=str(pdf))
                pdf.with_suffix(".match_report.json").write_text(json.dumps(report), encoding="utf-8")
                calls.append({"role_id": role["id"], "job_description_sha256": text_digest(arguments["job_description"]),
                              "source_sha256": digest(inputs), "new_paid_api_call": False})
                return str(pdf)
            results["generated"] = run_one(args, "generated", role, output, generator=fixture_generator)
            assert len(calls) == 1
            write_json(output / "generated/generator-fixture-evidence.json", {"calls": calls, "paid_api_calls": 0})
    elif args.exercise_generated:
        parser.error("--exercise-generated needs --optimized-pdf, --optimized-docx and --match-report")
    write_json(output / "browser-validation-summary.json", results)
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()

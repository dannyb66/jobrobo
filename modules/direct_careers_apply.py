"""Direct, reviewed applications from verified careers artifacts; no LinkedIn runtime.

Imports perform no browser, configuration, credential, AI or filesystem work.
Queue files intentionally contain JD/provenance and artifact paths, never answer values.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import uuid
from urllib.parse import urlparse

from modules.external_apply import ExternalApplicationLedger, apply_hosted_application, identify_ats
from modules.job_pipeline.models import StageResult, read_artifact, utc_now

SCHEMA = "direct-careers-queue-v1"
TERMINAL = {"applied", "duplicate", "discarded"}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_json(path, payload):
    """Atomic, private checkpoints; disk failures propagate before a Submit click."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".direct-careers-")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def literal_config(path):
    """Read only literal assignments, without importing the legacy key/browser loaders."""
    result = {}
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            try:
                value = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    result[target.id] = value
    return result


def local_candidate(config_dir):
    """Copy explicit existing candidate values; keys/passwords are never returned."""
    config_dir = Path(config_dir)
    values = {}
    for name in ("personals.py", "questions.py", "secrets.py"):
        values.update(literal_config(config_dir / name))
    names = {"first_name": "first_name", "last_name": "last_name", "phone": "phone_number",
             "linkedin": "linkedIn", "website": "website", "city": "current_city", "street": "street",
             "state": "state", "zipcode": "zipcode", "country": "country", "require_visa": "require_visa",
             "citizenship": "us_citizenship", "years_of_experience": "years_of_experience",
             "desired_salary": "desired_salary", "notice_period": "notice_period", "current_employer": "recent_employer",
             "gender": "gender", "ethnicity": "ethnicity", "disability_status": "disability_status", "veteran_status": "veteran_status",
             "work_authorization": "work_authorization", "github": "github", "summary": "linkedin_summary", "cover_letter": "cover_letter",
             "application_source": "application_source"}
    candidate = {target: values[source] for target, source in names.items()
                 if values.get(source) not in (None, "", "Not Applicable")}
    candidate["full_name"] = " ".join(value for part in ("first_name", "middle_name", "last_name") if (value := str(values.get(part) or "").strip()))
    if isinstance(values.get("username"), str) and "@" in values["username"]:
        candidate["email"] = values["username"]
    return candidate


def _timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Verification time needs a timezone")
    return parsed.astimezone(timezone.utc)


def application_url(url):
    """Open the native form route, preserving the exact same hosted ATS identity."""
    identity = identify_ats(url)
    if identity is None or identity.provider == "greenhouse":
        return url
    parsed = urlparse(url)
    suffix = "application" if identity.provider == "ashby" else "apply"
    path = "/" + identity.board + "/" + identity.job_id + "/" + suffix
    return parsed._replace(path=path, fragment="").geturl()


def readiness(role, *, now=None, freshness_days=7):
    """Inventory admission, never candidate-preference matching or rescoring."""
    now = now or datetime.now(timezone.utc)
    reasons = []
    if role.get("verification_eligible", role.get("eligible")) is not True:
        reasons.append("not_in_verified_engineering_inventory")
    if role.get("status") != "open" or role.get("is_prospect"):
        reasons.append("posting_not_verified_open")
    if not isinstance(role.get("title"), str) or not role["title"].strip():
        reasons.append("missing_job_title")
    if not isinstance(role.get("description"), str) or not role["description"].strip():
        reasons.append("missing_job_description")
    company = role.get("company")
    if not isinstance(company, dict) or not company.get("id") or company["id"] != role.get("company_id") or not company.get("name"):
        reasons.append("missing_company_provenance")
    identity = identify_ats(role.get("career_url"))
    if identity is None:
        reasons.append("unsupported_employer_application_site")
    sources = role.get("sources", [])
    if not isinstance(sources, list) or not any(isinstance(source, dict) and source.get("kind") == "career_verification"
                                               and isinstance(source.get("url"), str) and source["url"].startswith("https://")
                                               and source.get("observed_at") for source in sources):
        reasons.append("missing_official_verification_provenance")
    try:
        verified = _timestamp(role["verified_at"])
        if not now - timedelta(days=freshness_days) <= verified <= now + timedelta(minutes=5):
            reasons.append("verification_stale_or_future")
    except (ValueError, KeyError, TypeError, AttributeError):
        reasons.append("invalid_verification_time")
    return reasons


def verify_resume(source_docx, selected_docx, source_pdf, selected_pdf, expected_pages):
    """Reuse format checks only. No optimizer constructor, generation or API call."""
    from modules.ai.resume_optimizer import ResumeOptimizer
    verifier = ResumeOptimizer.__new__(ResumeOptimizer)
    return verifier.verify_format(str(source_docx), str(selected_docx), str(source_pdf), str(selected_pdf), expected_pages)


def _snapshot_file(source, directory, name):
    source = Path(source).expanduser().resolve()
    if not source.is_file():
        raise ValueError("A selected resume artifact is missing")
    checksum = digest(source)
    target = Path(directory) / checksum / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and digest(target) != checksum:
        raise ValueError("A prior resume snapshot changed; inspect the artifact directory")
    if not target.exists():
        shutil.copyfile(source, target)
        target.chmod(0o600)
    return {"path": str(target.resolve()), "sha256": checksum}


def plan_queue(input_path, queue_path, source_docx, source_pdf, *, resume_mode="original", optimized_map=None,
               expected_pages=2, freshness_days=7, now=None, verifier=verify_resume):
    """Retain every input row in stable supplied order; classify handoffs explicitly."""
    if resume_mode not in {"original", "optimized", "generated"}:
        raise ValueError("Resume mode must be original, optimized or generated")
    if type(expected_pages) is not int or expected_pages < 1 or type(freshness_days) is not int or freshness_days < 1:
        raise ValueError("Page and freshness limits must be positive integers")
    queue_path = Path(queue_path).expanduser().resolve()
    if queue_path.exists():
        raise ValueError("Queue already exists; resume it instead of overwriting checkpoints")
    artifact = read_artifact(input_path, "verified_roles")
    ids = [role.get("id") for role in artifact.records]
    if any(not isinstance(value, str) or not value.strip() for value in ids) or len(set(ids)) != len(ids):
        raise ValueError("Verified role IDs must be nonempty and unique")
    directory = queue_path.parent / (queue_path.stem + "-artifacts")
    source = {"docx": _snapshot_file(source_docx, directory, "source.docx"),
              "pdf": _snapshot_file(source_pdf, directory, "source.pdf")}
    report = verifier(source["docx"]["path"], source["docx"]["path"], source["pdf"]["path"], source["pdf"]["path"], expected_pages)
    if report.get("passed") is not True:
        raise ValueError("Original resume failed independent format verification")
    rows, seen = [], set()
    optimized_map = optimized_map or {}
    if not isinstance(optimized_map, dict) or any(role_id not in ids for role_id in optimized_map):
        raise ValueError("Optimized map must contain only role IDs present in this artifact")
    for index, original in enumerate(artifact.records):
        role = deepcopy(original)
        identity = identify_ats(role.get("career_url"))
        identity_key = "|".join(identity.key) if identity else None
        reasons = readiness(role, now=now, freshness_days=freshness_days)
        resume = {"mode": resume_mode, "pdf": source["pdf"], "docx": source["docx"], "report": None}
        if resume_mode == "generated":
            resume.update(pdf=None, docx=None, generation_attempts=[])
        if identity_key and identity_key in seen:
            reasons.append("duplicate_ats_posting_in_queue")
        if identity_key:
            seen.add(identity_key)
        if resume_mode == "optimized":
            selected = optimized_map.get(role["id"])
            if selected is None:
                reasons.append("no_selected_optimized_resume_for_role")
                resume.update(pdf=None, docx=None)
            else:
                if not isinstance(selected, dict) or not {"pdf", "docx", "report", "job_description_sha256"} <= selected.keys():
                    raise ValueError("Each optimized selection needs pdf, docx, report and job_description_sha256")
                match = json.loads(Path(selected["report"]).expanduser().read_text(encoding="utf-8"))
                normalized = lambda value: " ".join(str(value).casefold().split())
                if (match.get("status") != "accepted" or match.get("format_verification", {}).get("passed") is not True
                    or match.get("source_sha256") != source["docx"]["sha256"]
                    or normalized(match.get("job_title")) != normalized(role["title"])
                    or selected["job_description_sha256"] != text_digest(role["description"])
                    or Path(match.get("output_path", "")).expanduser().resolve() != Path(selected["pdf"]).expanduser().resolve()):
                    raise ValueError("Selected optimized report does not match this source, role/JD or PDF")
                resume.update(pdf=_snapshot_file(selected["pdf"], directory, "optimized.pdf"),
                              docx=_snapshot_file(selected["docx"], directory, "optimized.docx"),
                              report=_snapshot_file(selected["report"], directory, "optimizer-report.json"),
                              review_required=True, effective_mode=match.get("effective_mode"))
                checked = verifier(source["docx"]["path"], resume["docx"]["path"], source["pdf"]["path"], resume["pdf"]["path"], expected_pages)
                if checked.get("passed") is not True:
                    raise ValueError("Selected optimized resume failed independent format verification")
        rows.append({"role_id": role["id"], "position": index + 1, "ats_identity": identity_key,
                     "status": "manual_handoff" if reasons else "queued", "handoff_reasons": reasons,
                     "candidate_filter_warnings": deepcopy(role.get("application_exclusion_reasons", [])),
                     "job_description_sha256": text_digest(role.get("description") or ""),
                     "role": role, "resume": resume, "attempts": []})
    queue = {"schema": SCHEMA, "queue_id": str(uuid.uuid4()), "created_at": utc_now(), "updated_at": utc_now(),
             "input": {"set_name": artifact.set_name, "run_id": artifact.run_id,
                       "artifact_sha256": text_digest(json.dumps(artifact.to_dict(), sort_keys=True)),
                       "input_set_ids": artifact.input_set_ids},
             "source_resume": source, "resume_mode": resume_mode, "expected_pages": expected_pages,
             "freshness_days": freshness_days, "search_performed": False,
             "records": rows, "invocations": []}
    write_json(queue_path, queue)
    return queue


def load_queue(path):
    queue = json.loads(Path(path).read_text(encoding="utf-8"))
    validate_queue(queue)
    return queue


def validate_queue(queue):
    """Validate the role → queue → artifact → result provenance chain."""
    if not isinstance(queue, dict) or queue.get("schema") != SCHEMA or queue.get("search_performed") is not False:
        raise ValueError("Unsupported direct careers queue")
    if queue.get("resume_mode") not in {"original", "optimized", "generated"} or not isinstance(queue.get("records"), list):
        raise ValueError("Invalid direct careers queue contract")
    if any(type(queue.get(key)) is not int or queue[key] < 1 for key in ("expected_pages", "freshness_days")):
        raise ValueError("Invalid queue page/freshness limits")
    if not isinstance(queue.get("invocations"), list) or not isinstance(queue.get("input"), dict) or not queue["input"].get("run_id") or not queue["input"].get("set_name"):
        raise ValueError("Queue input provenance or invocation history is missing")
    if not isinstance(queue.get("source_resume"), dict) or set(queue["source_resume"]) != {"docx", "pdf"}:
        raise ValueError("Queue source artifacts are missing")
    ids = set()
    for index, row in enumerate(queue["records"]):
        role = row.get("role", {})
        if not row.get("role_id") or row["role_id"] in ids or row["role_id"] != role.get("id") or row.get("position") != index + 1:
            raise ValueError("Queue role IDs/order do not match their verified records")
        ids.add(row["role_id"])
        identity = identify_ats(role.get("career_url"))
        expected_identity = "|".join(identity.key) if identity else None
        if row.get("ats_identity") != expected_identity or row.get("job_description_sha256") != text_digest(role.get("description") or ""):
            raise ValueError("Queue posting identity or JD changed")
        if row.get("status") not in {"queued", "manual_handoff", "awaiting_review", "handoff", "discarded", "duplicate", "failed", "submitting", "applied"}:
            raise ValueError("Unknown queue application state")
        if row.get("resume", {}).get("mode") != queue["resume_mode"] or not isinstance(row.get("attempts"), list):
            raise ValueError("Invalid resume mode or attempts")
        if queue["resume_mode"] == "original" and any(row["resume"].get(kind) != queue["source_resume"][kind] for kind in ("pdf", "docx")):
            raise ValueError("Original mode must use the unchanged source artifacts")
        if queue["resume_mode"] == "generated" and row["resume"].get("pdf"):
            bound = row["resume"].get("generation_binding", {})
            expected = {"queue_id": queue["queue_id"], "role_id": row["role_id"], "ats_identity": row["ats_identity"],
                        "job_description_sha256": row["job_description_sha256"],
                        "source_docx_sha256": queue["source_resume"]["docx"]["sha256"],
                        "source_pdf_sha256": queue["source_resume"]["pdf"]["sha256"],
                        "output_pdf_sha256": row["resume"]["pdf"]["sha256"],
                        "output_docx_sha256": row["resume"]["docx"]["sha256"],
                        "optimizer_report_sha256": row["resume"]["report"]["sha256"]}
            if not row["resume"].get("binding") or any(bound.get(key) != value for key, value in expected.items()):
                raise ValueError("Generated resume lost its source/JD/role/artifact binding")
        for attempt in row["attempts"]:
            if attempt.get("role_id") != row["role_id"] or attempt.get("ats_identity") != row["ats_identity"] or attempt.get("job_description_sha256") != row["job_description_sha256"]:
                raise ValueError("An application result lost its verified-role provenance")
            outcome = attempt.get("outcome", {})
            if attempt.get("resume_sha256") != row["resume"].get("pdf", {}).get("sha256"):
                raise ValueError("Application result resume differs from the selected artifact")
            if outcome.get("application_link"):
                actual = identify_ats(outcome["application_link"])
                if actual is None or "|".join(actual.key) != row["ats_identity"]:
                    raise ValueError("Application result posting differs from the verified role")
            if outcome.get("resume_sha256") and outcome["resume_sha256"] != attempt["resume_sha256"]:
                raise ValueError("Application result attachment differs from its selected snapshot")
            if outcome.get("status") == "applied" and (not outcome.get("submitted_at") or not outcome.get("resume_sha256")):
                raise ValueError("Applied status needs confirmed submission and resume evidence")
    return True


def _resume_unchanged(queue, row):
    for record in [*queue["source_resume"].values(), *[row["resume"].get(key) for key in ("pdf", "docx", "report", "binding")]]:
        if record is not None and digest(record["path"]) != record["sha256"]:
            raise ValueError("A selected resume artifact or report changed after planning")
    if row["resume"].get("binding") and json.loads(Path(row["resume"]["binding"]["path"]).read_text(encoding="utf-8")) != row["resume"].get("generation_binding"):
        raise ValueError("Generated resume binding file differs from its queue checkpoint")


def summarize(queue):
    return {"queue_id": queue["queue_id"], "resume_mode": queue["resume_mode"], "search_performed": False,
            "roles": len(queue["records"]), "statuses": dict(Counter(row["status"] for row in queue["records"])),
            "candidate_filter_warnings": sum(bool(row["candidate_filter_warnings"]) for row in queue["records"]),
            "confirmed_applications": sum(row["status"] == "applied" for row in queue["records"])}


def wait_for_form(driver, timeout=15):
    """Allow client-rendered hosted forms to appear before inspecting their contract."""
    from modules.external_apply import snapshot
    deadline = time.monotonic() + timeout
    while True:
        state = snapshot(driver)
        if state.get("challenge") or any(field.get("type") == "file" for field in state.get("fields", [])):
            return
        if time.monotonic() >= deadline:
            return  # The normal hosted flow reports a precise unsupported/closed-page handoff.
        time.sleep(0.1)


def generate_local_resume(**arguments):
    """Lazy reviewed optimizer; its key source is the local environment/.env only."""
    from modules.ai.resume_optimizer import run_resume_optimization
    return run_resume_optimization(**arguments)


def _generate_resume(queue, row, directory, generation, generate, verifier, candidate):
    """Bind a newly accepted optimizer result to the exact inputs passed this invocation."""
    working = Path(directory) / "generation" / generation["id"]
    inputs = working / "source"
    working.mkdir(parents=True, mode=0o700)
    inputs.mkdir(mode=0o700)
    for kind in ("docx", "pdf"):
        target = inputs / ("resume." + kind)
        shutil.copyfile(queue["source_resume"][kind]["path"], target)
        target.chmod(0o600)
    output = generate(job_description=row["role"]["description"], resume_path=str(inputs / "resume.docx"),
                      job_id=generation["id"], job_title=row["role"]["title"],
                      first_name=str(candidate.get("first_name") or "candidate"),
                      last_name=str(candidate.get("last_name") or "resume"))
    if not output:
        raise ValueError("Optimizer did not return an accepted artifact")
    pdf = Path(output).expanduser().resolve()
    docx, report_path = pdf.with_suffix(".docx"), pdf.with_suffix(".match_report.json")
    if pdf.suffix.lower() != ".pdf" or not pdf.is_relative_to(working.resolve()) or not pdf.is_file() or not docx.is_file() or not report_path.is_file():
        raise ValueError("Optimizer artifacts are absent or outside this generation workspace")
    match = json.loads(report_path.read_text(encoding="utf-8"))
    normalized = lambda value: " ".join(str(value).casefold().split())
    strict = isinstance(match,dict) and match.get("rewrite_all_bullets") is True
    complete = isinstance(match,dict) and (match.get("status") == "complete" and match.get("strict_attachment_eligible") is True if strict else match.get("status") == "accepted")
    if (not isinstance(match, dict) or not complete
        or match.get("format_verification", {}).get("passed") is not True
        or match.get("source_sha256") != queue["source_resume"]["docx"]["sha256"]
        or match.get("job_id") != generation["id"]
        or normalized(match.get("job_title")) != normalized(row["role"]["title"])
        or Path(match.get("output_path", "")).expanduser().resolve() != pdf
        or any(digest(inputs / ("resume." + kind)) != queue["source_resume"][kind]["sha256"] for kind in ("docx", "pdf"))):
        raise ValueError("Optimizer report/source inputs do not match this generation")
    _resume_unchanged(queue, row)
    if strict:
        from modules.resume_all_bullets import verify_strict_attachment
        checked={"passed":verify_strict_attachment(pdf,expected_jd=row["role"]["description"],expected_job_id=generation["id"],expected_source_docx=queue["source_resume"]["docx"]["path"])}
    else:
        checked = verifier(queue["source_resume"]["docx"]["path"], str(docx), queue["source_resume"]["pdf"]["path"], str(pdf), queue["expected_pages"])
    if checked.get("passed") is not True:
        raise ValueError("Generated resume failed independent format verification")
    resume = {"mode": "generated", "pdf": _snapshot_file(pdf, directory, "generated.pdf"),
              "docx": _snapshot_file(docx, directory, "generated.docx"),
              "report": _snapshot_file(report_path, directory, "optimizer-report.json"),
              "review_required": True, "effective_mode": match.get("effective_mode"),
              "generation_attempts": row["resume"]["generation_attempts"]}
    binding = {"generation_id": generation["id"], "queue_id": queue["queue_id"], "role_id": row["role_id"],
               "ats_identity": row["ats_identity"], "job_description_sha256": row["job_description_sha256"],
               "source_docx_sha256": queue["source_resume"]["docx"]["sha256"],
               "source_pdf_sha256": queue["source_resume"]["pdf"]["sha256"],
               "output_pdf_sha256": resume["pdf"]["sha256"], "output_docx_sha256": resume["docx"]["sha256"],
               "optimizer_report_sha256": resume["report"]["sha256"], "created_at": utc_now(),
               "binding_method": "direct-reviewed-optimizer-call-v1", "content_review_required": True}
    binding_path = working / "generation-binding.json"
    write_json(binding_path, binding)
    resume.update(binding=_snapshot_file(binding_path, directory, "generation-binding.json"), generation_binding=binding)
    return resume


def run_queue(queue_path, *, execute=False, browser_factory=None, candidate=None, review=None, ledger_path=None,
              max_applications=1, max_attempts=1, selected_role_ids=(), question_config=None,
              enable_question_ai=False, verifier=verify_resume, apply=apply_hosted_application, now=None,
              browser_ready=wait_for_form, generate_resumes=False, generate=None):
    """Execute only after explicit CLI authorization; always retain per-application review.

    The browser and answers are injected so original-resume unit/browser tests need
    neither credentials nor a live employer. A protected uncertain outcome stops all work.
    """
    from modules.search_history import file_lock
    if not execute:
        raise ValueError("Run requires explicit --execute; use plan/status for read-only review")
    if type(max_applications) is not int or max_applications < 1 or type(max_attempts) is not int or max_attempts < 1:
        raise ValueError("Application and attempt limits must be positive integers")
    if browser_factory is None or review is None:
        raise ValueError("A visible browser factory and mandatory application review are required")
    queue_path = Path(queue_path).expanduser().resolve()
    ledger = ExternalApplicationLedger(ledger_path or queue_path.parent / "external-applications.json")
    with file_lock(str(queue_path) + ".lock"):
        queue = load_queue(queue_path)
        selected = set(selected_role_ids)
        if selected - {row["role_id"] for row in queue["records"]}:
            raise ValueError("Selected role IDs are absent from the queue")
        generated_mode = queue["resume_mode"] == "generated"
        if generated_mode and not generate_resumes:
            raise ValueError("Generated mode requires explicit --generate-resume for possible paid local-key optimization")
        if generate_resumes and not generated_mode:
            raise ValueError("--generate-resume requires a queue planned with --resume-mode generated")
        if generated_mode and (len(selected) != 1 or max_attempts != 1 or max_applications != 1):
            raise ValueError("Generated mode requires one explicit --role, one attempt and application cap 1")
        invocation = {"id": str(uuid.uuid4()), "started_at": utc_now(), "max_applications": max_applications,
                      "attempt_count": 0, "confirmed_count": 0, "generation_count": 0, "stop_reason": None}
        queue["invocations"].append(invocation)

        def save():
            queue["updated_at"] = utc_now()
            validate_queue(queue)
            write_json(queue_path, queue)

        # Includes another queue/LinkedIn invocation sharing this explicit ledger.
        if any(row["status"] == "submitting" for row in queue["records"]) or any(
                outcome.get("status") == "submitting" for outcome in ledger._read().values()):
            invocation["stop_reason"] = "submission_uncertain"
            invocation["finished_at"] = utc_now()
            save()
            return queue
        config = deepcopy(question_config or {})
        config.setdefault("ai", {})["enabled"] = bool(enable_question_ai and config.get("ai", {}).get("enabled") is True)
        ai_answerer = None
        if config["ai"]["enabled"]:
            from modules.external_questions import make_local_ai_answerer
            # This entry point never invokes the shared legacy key loader.
            ai_answerer = make_local_ai_answerer(config["ai"], original_local_env=dict(os.environ))
        for row in queue["records"]:
            if selected and row["role_id"] not in selected or row["status"] in TERMINAL:
                continue
            if invocation["confirmed_count"] >= max_applications:
                invocation["stop_reason"] = "application_limit_reached"
                break
            if invocation["attempt_count"] >= max_attempts:
                invocation["stop_reason"] = "attempt_limit_reached"
                break
            if ledger.protected(row["role"]["career_url"]):
                row["status"] = "duplicate"
                row["handoff_reasons"] = ["protected_ats_posting_in_shared_ledger"]
                save()
                continue
            reasons = readiness(row["role"], now=now, freshness_days=queue["freshness_days"])
            if "duplicate_ats_posting_in_queue" in row["handoff_reasons"]:
                reasons.append("duplicate_ats_posting_in_queue")
            if row["resume"].get("pdf") is None and not generated_mode:
                reasons.append("no_selected_optimized_resume_for_role")
            if reasons:
                row["status"], row["handoff_reasons"] = "manual_handoff", reasons
                save()
                continue
            scope_counted = False
            if generated_mode and row["resume"].get("pdf") is None:
                if any(item.get("status") == "submitting" for item in ledger._read().values()):
                    invocation["stop_reason"] = "submission_uncertain"
                    save()
                    break
                try:
                    _resume_unchanged(queue, row)
                except (ValueError, OSError):
                    row["status"], row["handoff_reasons"] = "failed", ["resume_snapshot_changed_or_invalid"]
                    save()
                    continue
                if generate is None:
                    from modules.config_loader import load_runtime_config
                    try:
                        configured_pages = int(load_runtime_config().get("expected_page_count", 2))
                        if configured_pages < 1:
                            raise ValueError("Invalid configured page count")
                    except (ValueError, TypeError, OSError):
                        row["status"], row["handoff_reasons"] = "manual_handoff", ["resume_optimizer_page_config_invalid"]
                        invocation["stop_reason"] = "resume_generation_config_invalid"
                        save()
                        break
                    if configured_pages != queue["expected_pages"]:
                        row["status"], row["handoff_reasons"] = "manual_handoff", ["resume_optimizer_page_count_mismatch"]
                        row["resume"]["generation_preflight"] = {"queue_expected_pages": queue["expected_pages"],
                                                                  "optimizer_expected_pages": configured_pages,
                                                                  "action": "Align runtime expected_page_count with the queue before retrying."}
                        invocation["stop_reason"] = "resume_generation_config_mismatch"
                        save()
                        break
                history = row["resume"]["generation_attempts"]
                if any(item.get("status") == "generating" for item in history):
                    row["status"], row["handoff_reasons"] = "manual_handoff", ["resume_generation_interrupted_review_required"]
                    invocation["stop_reason"] = "resume_generation_interrupted"
                    save()
                    break
                generation = {"id": "direct-" + str(uuid.uuid4()), "started_at": utc_now(), "status": "generating",
                              "role_id": row["role_id"], "job_description_sha256": row["job_description_sha256"],
                              "source_docx_sha256": queue["source_resume"]["docx"]["sha256"]}
                history.append(generation)
                invocation["attempt_count"] += 1
                invocation["generation_count"] += 1
                scope_counted = True
                save()  # Persist possible API spend before entering the optimizer.
                try:
                    _resume_unchanged(queue, row)
                    row["resume"] = _generate_resume(queue, row, queue_path.parent / (queue_path.stem + "-artifacts"),
                                                     generation, generate or generate_local_resume, verifier, candidate or {})
                except OSError:
                    # Filesystem failures can occur after a paid result exists;
                    # preserve the durable in-flight checkpoint for inspection.
                    raise
                except Exception as error:
                    generation.update(status="failed", finished_at=utc_now(), error_type=type(error).__name__)
                    row["resume"] = {"mode": "generated", "pdf": None, "docx": None, "report": None, "generation_attempts": history}
                    row["status"], row["handoff_reasons"] = "manual_handoff", ["resume_generation_failed_no_source_fallback"]
                    invocation["stop_reason"] = "resume_generation_failed"
                    save()
                    break
                generation.update(status="accepted", finished_at=utc_now())
                row["status"], row["handoff_reasons"] = "queued", []
                # A failed accepted-result checkpoint must preserve the durable
                # pre-call `generating` state, not authorize paid regeneration.
                save()
            try:
                _resume_unchanged(queue, row)
                def check_pdf(path):
                    _resume_unchanged(queue, row)
                    if Path(path).resolve() != Path(row["resume"]["pdf"]["path"]).resolve():
                        return False
                    return verifier(queue["source_resume"]["docx"]["path"], row["resume"]["docx"]["path"],
                                    queue["source_resume"]["pdf"]["path"], str(path), queue["expected_pages"]).get("passed") is True
                if not check_pdf(row["resume"]["pdf"]["path"]):
                    raise ValueError("Selected resume failed independent format verification")
            except (ValueError, OSError):
                row["status"], row["handoff_reasons"] = "failed", ["resume_snapshot_changed_or_invalid"]
                save()
                continue
            attempt = {"id": str(uuid.uuid4()), "role_id": row["role_id"], "ats_identity": row["ats_identity"],
                       "job_description_sha256": row["job_description_sha256"], "started_at": utc_now(),
                       "resume_mode": queue["resume_mode"], "resume_sha256": row["resume"]["pdf"]["sha256"],
                       "outcome": {"status": "preparing"}}
            row["attempts"].append(attempt)
            if not scope_counted:
                invocation["attempt_count"] += 1
            save()
            driver = None
            outcome = None
            try:
                driver = browser_factory()
                target_url = application_url(row["role"]["career_url"])
                driver.get(target_url)
                browser_ready(driver)
                def checkpoint(result):
                    # Claim the ATS posting before the queue: a queue disk failure cannot permit retry.
                    if result.status == "submitting" and any(key != row["ats_identity"] and value.get("status") == "submitting"
                                                              for key, value in ledger._read().items()):
                        raise RuntimeError("Another employer submission requires verification")
                    ledger.record(result, row["role_id"])
                    stored = ledger._read().get(row["ats_identity"], {})
                    # A failed local checkpoint may leave a conservative durable claim even
                    # when the hosted flow returns a preparation failure before its click.
                    effective = stored if stored.get("status") in {"applied", "submitting"} else result.to_dict()
                    attempt["outcome"], row["status"] = effective, effective["status"]
                    save()
                context = {}
                if ai_answerer:
                    from modules.external_questions import grounding_context
                    context = grounding_context(queue["source_resume"]["docx"]["path"], job_description=row["role"]["description"])
                def review_selected_resume(details):
                    # Reuse the private review UI, with the exact selected document/report visible.
                    selected = row["resume"]
                    artifact = {"question": "Selected resume for " + row["role"]["title"], "name": "selected_resume",
                                "type": "document", "answer": selected["pdf"]["path"], "source": "explicit_role_resume_selection",
                                "status": "prepared", "reason": "Open and review this PDF before approving Submit application. Mode: " + selected["mode"]}
                    if selected.get("report"):
                        artifact["reason"] += ". Optimizer report: " + selected["report"]["path"] + ". Optimized content requires manual review; format acceptance does not verify claims."
                    return review({**details, "answer_preview": [artifact, *details.get("answer_preview", [])]})
                outcome = apply(driver, target_url, candidate or {}, row["resume"]["pdf"]["path"],
                                verify_pdf=check_pdf, company=row["role"]["company"]["name"], title=row["role"]["title"],
                                official_role_urls=[row["role"]["career_url"]], review=review_selected_resume, on_status=checkpoint,
                                question_config=config, question_context=context, ai_answerer=ai_answerer)
                checkpoint(outcome)
                if row["status"] == "applied":
                    invocation["confirmed_count"] += 1
                elif row["status"] == "submitting":
                    invocation["stop_reason"] = "submission_uncertain"
                elif row["status"] in {"awaiting_review", "handoff"}:
                    invocation["stop_reason"] = "manual_review_open"
                elif any(item.get("status") == "submitting" for item in ledger._read().values()):
                    invocation["stop_reason"] = "submission_uncertain"
            except Exception as error:
                # Preserve an earlier pre-click durable claim even if its later write failed.
                stored = ledger._read().get(row["ats_identity"], {})
                if stored.get("status") == "applied":
                    row["status"], attempt["outcome"] = "applied", stored
                    invocation["confirmed_count"] += 1
                    invocation["stop_reason"] = "tracking_interrupted_after_confirmation"
                else:
                    protected = stored.get("status") == "submitting"
                    row["status"] = "submitting" if protected else "failed"
                    attempt["outcome"] = {"status": row["status"], "reason": "Direct application interrupted: " + type(error).__name__}
                    invocation["stop_reason"] = "submission_uncertain" if protected else "runner_interrupted"
                save()
            finally:
                # A handoff stays visible for the operator. The CLI creates detached Chrome.
                if driver is not None and row["status"] in {"applied", "discarded", "failed", "duplicate"}:
                    try:
                        driver.quit()
                    except Exception:
                        pass  # A browser cleanup failure cannot undo the durable application state.
            save()
            if invocation["stop_reason"]:
                break
        if invocation["stop_reason"] is None:
            invocation["stop_reason"] = "application_limit_reached" if invocation["confirmed_count"] >= max_applications else "attempt_limit_reached" if invocation["attempt_count"] >= max_attempts else "queue_exhausted"
        invocation["finished_at"] = utc_now()
        save()
        return queue


def export_applications(queue):
    validate_queue(queue)
    records = [{"id": attempt["id"], "role_id": row["role_id"], "company_id": row["role"].get("company_id"),
                "career_url": row["role"]["career_url"], "queue_id": queue["queue_id"],
                "verification_run_id": queue["input"]["run_id"], "ats_identity": row["ats_identity"],
                "resume_mode": attempt["resume_mode"], "resume_sha256": attempt["resume_sha256"],
                "job_description_sha256": attempt["job_description_sha256"], **attempt["outcome"]}
               for row in queue["records"] for attempt in row["attempts"]]
    return StageResult.create("applications", "direct-careers:" + queue["input"]["set_name"], queue["queue_id"], records,
                              input_set_ids=["verified_roles:" + queue["input"]["set_name"]])

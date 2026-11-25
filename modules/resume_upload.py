"""Upload a verified optimized resume, with an explicit source-PDF fallback."""

from pathlib import Path
from copy import deepcopy
from contextlib import nullcontext
import hashlib
import re
import shutil
import unicodedata


class ResumeUploadError(RuntimeError):
    """An application cannot continue without its verified resume attachment."""


def verify_source_resume(source_path, pdf_path):
    """Apply the optimizer's format contract to the unchanged source resume."""
    from modules.ai.resume_optimizer import ResumeOptimizer
    from modules.config_loader import load_runtime_config

    source = Path(source_path)
    pdf = Path(pdf_path)
    if not pdf.is_file():
        return False
    docx = str(source) if source.suffix.lower() == ".docx" else ""
    expected_pages = int(load_runtime_config().get("expected_page_count", 2))
    optimizer = ResumeOptimizer.__new__(ResumeOptimizer)
    report = optimizer.verify_format(docx, docx, str(pdf), str(pdf), expected_pages)
    return bool(report["passed"])


def optimized_upload_filename(first_name, last_name, job_title, company_name):
    """Build a filesystem-safe LinkedIn attachment name from job context."""
    def component(value, maximum):
        value = unicodedata.normalize("NFKC", str(value or ""))
        value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', " ", value)
        value = re.sub(r"\s+", " ", value).strip(" .-")
        return value[:maximum].rstrip(" .-")

    first = component(first_name, 40)
    last = component(last_name, 40)
    full_name = component(f"{first} {last}" if first and last else "", 80)
    role = component(job_title, 80)
    company = component(company_name, 60)
    if not all((full_name, role, company)):
        return ""
    return f"{full_name} - {role} - {company}.pdf"


def named_optimized_upload_copy(path, first_name, last_name, job_title, company_name, job_id):
    """Copy a verified optimized PDF to its descriptive LinkedIn upload name."""
    source = Path(path).resolve()
    filename = optimized_upload_filename(first_name, last_name, job_title, company_name)
    if not filename:
        return source
    target = source.with_name(filename)
    if target == source:
        return source

    source_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if target.exists():
        if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == source_digest:
            return target
        job_tag = re.sub(r"[^A-Za-z0-9-]+", "", str(job_id or ""))[:32]
        suffix = f" - {job_tag}" if job_tag else ""
        target = source.with_name(f"{Path(filename).stem}{suffix} - {source_digest[:8]}.pdf")
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() == source_digest:
            return target

    shutil.copy2(source, target)
    if hashlib.sha256(target.read_bytes()).hexdigest() != source_digest:
        target.unlink(missing_ok=True)
        raise ResumeUploadError("Named optimized resume copy failed integrity verification")
    return target


def upload_verified_resume(modal, resume_path, job_description, job_id,
                           job_title="job", first_name="first", last_name="last",
                           *, optimize, verify_source=verify_source_resume, log=None,
                           rewrite_all_bullets=None, rewrite_experience_concurrency=None,
                           source_checks_enabled=None, runtime_config_override=None,
                           on_attached=None, company_name=""):
    """Return success only after Selenium attaches a verified PDF.

    The optimizer's returned path has passed its verifier. If optimization or
    attachment fails, the source PDF must independently pass the same contract.
    A previous LinkedIn attachment is never reported as a successful fallback.
    """
    def report(message):
        if log:
            try:
                log(message)
            except Exception:
                pass

    def attach(path, *, optimized=False):
        if optimized:
            path = named_optimized_upload_copy(path, first_name, last_name, job_title,
                                               company_name, job_id)
            report(f'[Resume {job_id}] LinkedIn attachment filename: {path.name}')
        report(f'[Resume {job_id}] Uploading verified PDF to LinkedIn')
        modal.find_element("name", "file").send_keys(str(path.resolve()))
        if on_attached is not None:
            on_attached(str(path.resolve()))
        report(f'[Resume {job_id}] PDF attached; continuing the application form')
        return True, path.name

    from modules.config_loader import peek_runtime_config
    config=deepcopy(runtime_config_override if runtime_config_override is not None else peek_runtime_config())
    config.setdefault('optimization_mode','full')
    if rewrite_all_bullets is not None:config['rewrite_all_bullets']=rewrite_all_bullets
    if rewrite_experience_concurrency is not None:config['rewrite_experience_concurrency']=rewrite_experience_concurrency
    if source_checks_enabled is not None:config['source_checks_enabled']=source_checks_enabled
    strict=config.get('rewrite_all_bullets',False)
    checks=config.get('source_checks_enabled',True)
    if type(strict) is not bool or type(checks) is not bool:
        return False,'Resume rewrite flags must be booleans'
    if not checks and not strict:
        return False,'Source checks disabled requires all-bullets rewriting'
    overrides = {}
    failure_reason = None
    if rewrite_all_bullets is not None:
        overrides["rewrite_all_bullets"] = rewrite_all_bullets
    if rewrite_experience_concurrency is not None:
        overrides["rewrite_experience_concurrency"] = rewrite_experience_concurrency
    try:
        overrides['runtime_config_override']=deepcopy(config)
        cache = None
        cached = None

        def verify_cached(path):
            from modules.resume_all_bullets import verify_strict_attachment
            return verify_strict_attachment(path, expected_jd=job_description,
                expected_job_id=job_id, expected_source_docx=resume_path,
                expected_source_checks_enabled=checks, expected_config=config)

        if strict and Path(resume_path).suffix.lower() == ".docx" and Path(resume_path).expanduser().is_file():
            from modules.resume_cache import (cache_record_path, load_cached_resume,
                resume_cache_fingerprint, resume_cache_lock, store_cached_resume)
            fingerprint = resume_cache_fingerprint(
                job_id=job_id, job_description=job_description, source_resume=resume_path,
                job_title=job_title, first_name=first_name, last_name=last_name,
                config=config, repo_root=Path(__file__).resolve().parent.parent,
            )
            cache = cache_record_path(resume_path, job_id, fingerprint)

        with (resume_cache_lock(cache) if cache else nullcontext()):
            if cache:
                cached = load_cached_resume(cache, fingerprint, verify_cached)
                if cached:
                    report(f'[Resume {job_id}] Reusing verified job-specific optimized resume; optimizer API calls skipped')
            if cached:
                optimized = str(cached)
            else:
                from modules.resume_progress import ResumeConsoleProgress
                with ResumeConsoleProgress(log, job_id) as progress:
                    if log:
                        overrides['progress_callback'] = progress
                    optimized = optimize(
                        job_description=job_description, resume_path=resume_path, job_id=job_id,
                        job_title=job_title, first_name=first_name, last_name=last_name, **overrides,
                    )
            if optimized:
                path = Path(optimized)
                if path.is_file() and path.suffix.lower() == ".pdf":
                    if strict and not cached:
                        report(f'[Resume {job_id}] Verifying generated PDF against this job and configuration')
                        if not verify_cached(path):
                            report("Strict generated attachment failed completion/artifact binding checks.")
                            return False, "Strict rewrite incomplete"
                        if cache and store_cached_resume(cache, fingerprint, path):
                            report(f'[Resume {job_id}] Saved verified optimized resume for reuse on this exact job and configuration')
                    return attach(path, optimized=True)
        report(f"Optimized resume unavailable for Job ID {job_id}." +
               (" See the optimization failure above." if strict else " Checking the source PDF."))
    except Exception as exc:
        failure_reason = str(exc)
        report(f"Optimized resume failed for Job ID {job_id}: {exc}")

    if strict:
        report(f"No verified job-specific optimized PDF is available for Job ID {job_id}; source fallback is disabled.")
        return False, failure_reason or "No verified job-specific optimized PDF is available"
    source = Path(resume_path)
    fallback = source.with_suffix(".pdf") if source.suffix.lower() == ".docx" else source
    try:
        if fallback.suffix.lower() == ".pdf" and fallback.is_file() and verify_source(source, fallback):
            result = attach(fallback)
            report(f"Uploaded verified source fallback for Job ID {job_id}: {fallback.name}")
            return result
    except Exception as exc:
        report(f"Source resume fallback failed for Job ID {job_id}: {exc}")
    report(f"No verified resume could be uploaded for Job ID {job_id}; application must stop.")
    return False, "No verified resume"

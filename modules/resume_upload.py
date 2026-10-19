"""Upload a verified optimized resume, with an explicit source-PDF fallback."""

from pathlib import Path
from copy import deepcopy


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


def upload_verified_resume(modal, resume_path, job_description, job_id,
                           job_title="job", first_name="first", last_name="last",
                           *, optimize, verify_source=verify_source_resume, log=None,
                           rewrite_all_bullets=None, rewrite_experience_concurrency=None,
                           source_checks_enabled=None, runtime_config_override=None,
                           on_attached=None):
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

    def attach(path):
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
    if rewrite_all_bullets is not None:
        overrides["rewrite_all_bullets"] = rewrite_all_bullets
    if rewrite_experience_concurrency is not None:
        overrides["rewrite_experience_concurrency"] = rewrite_experience_concurrency
    try:
        overrides['runtime_config_override']=deepcopy(config)
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
                if strict:
                    report(f'[Resume {job_id}] Verifying generated PDF against this job and configuration')
                    from modules.resume_all_bullets import verify_strict_attachment
                    if not verify_strict_attachment(path,expected_jd=job_description,expected_job_id=job_id,expected_source_docx=resume_path,
                            expected_source_checks_enabled=checks,expected_config=config):
                        report("Strict generated attachment failed completion/artifact binding checks.")
                        return False, "Strict rewrite incomplete"
                return attach(path)
        report(f"Optimized resume unavailable for Job ID {job_id}; checking the source PDF.")
    except Exception as exc:
        report(f"Optimized resume failed for Job ID {job_id}: {exc}")

    if strict:
        report(f"Strict all-bullets rewrite incomplete for Job ID {job_id}; source fallback is disabled.")
        return False, "Strict rewrite incomplete"
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

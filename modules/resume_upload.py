"""Upload a verified optimized resume, with an explicit source-PDF fallback."""

from pathlib import Path


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
                           *, optimize, verify_source=verify_source_resume, log=None):
    """Return success only after Selenium attaches a verified PDF.

    The optimizer's returned path has passed its verifier. If optimization or
    attachment fails, the source PDF must independently pass the same contract.
    A previous LinkedIn attachment is never reported as a successful fallback.
    """
    def report(message):
        if log:
            log(message)

    def attach(path):
        modal.find_element("name", "file").send_keys(str(path.resolve()))
        return True, path.name

    try:
        optimized = optimize(
            job_description=job_description, resume_path=resume_path, job_id=job_id,
            job_title=job_title, first_name=first_name, last_name=last_name,
        )
        if optimized:
            path = Path(optimized)
            if path.is_file() and path.suffix.lower() == ".pdf":
                return attach(path)
        report(f"Optimized resume unavailable for Job ID {job_id}; checking the source PDF.")
    except Exception as exc:
        report(f"Optimized resume failed for Job ID {job_id}: {exc}")

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

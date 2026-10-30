"""LinkedIn handoff to the same employer submission engine as direct_apply submit."""
import json
from pathlib import Path
from urllib.parse import urlparse

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from .external_apply import ExternalApplicationLedger, ExternalApplicationResult, identify_ats
from .generic_inputs import load_jobs
from .search_history import file_lock
from .direct_careers_apply import write_json


def employer_url(url):
    host = (urlparse(url).hostname or '').lower()
    return urlparse(url).scheme in {'http', 'https'} and host and not (host == 'linkedin.com' or host.endswith('.linkedin.com'))


def open_employer_tab(driver, job_id, *, timeout=20):
    """Click the selected posting's external CTA once; never choose windows[-1]."""
    from .linkedin_job_details import modern_details_root, _url_job_id
    if _url_job_id(driver.current_url) != str(job_id):
        raise ValueError('External Apply control does not belong to the selected LinkedIn job')
    origin, results_url = driver.current_window_handle, driver.current_url
    before = set(driver.window_handles)
    root = modern_details_root(driver, str(job_id))
    roots = [root] if root is not None else driver.find_elements(By.CSS_SELECTOR,
        '.jobs-details__main-content, .jobs-unified-top-card, .job-details-jobs-unified-top-card')
    controls = {}
    for root in roots:
        for node in root.find_elements(By.CSS_SELECTOR, 'a[href], button'):
            labels = [node.text, node.get_attribute('aria-label')]
            if node.is_displayed() and node.is_enabled() and any(' '.join((label or '').lower().split()) in
                    {'apply', 'apply to this job', 'apply on company website'} for label in labels):
                controls[node.id] = node
    if len(controls) != 1:
        raise ValueError('Selected posting lacks one unambiguous external Apply control')
    button = next(iter(controls.values()))
    driver.execute_script('arguments[0].scrollIntoView({block: "center"});', button)
    button.click()

    def destination(browser):
        candidates = [h for h in browser.window_handles if h not in before]
        for handle in candidates + ([origin] if origin in browser.window_handles else []):
            browser.switch_to.window(handle)
            if employer_url(browser.current_url):
                return handle, browser.current_url
        # LinkedIn sometimes asks permission to continue to the company site.
        browser.switch_to.window(origin)
        for dialog in browser.find_elements(By.CSS_SELECTOR, '[role="dialog"]'):
            if not dialog.is_displayed():
                continue
            for node in dialog.find_elements(By.CSS_SELECTOR, 'button, a[href]'):
                if node.is_displayed() and node.is_enabled() and node.text.strip().lower() in {'continue', 'continue applying'}:
                    node.click()
                    return False
        return False

    handle, url = WebDriverWait(driver, timeout).until(destination)
    if handle == origin:
        driver.switch_to.new_window('tab')
        handle = driver.current_window_handle
        driver.get(url)
        driver.switch_to.window(origin)
        driver.get(results_url)
        driver.switch_to.window(handle)
    return handle, url


def import_submission_holds(path, history_root):
    """Protect past direct-command submissions without changing their independent-run policy."""
    candidates = {}
    for source in Path(history_root).glob('*/applications-ledger.json'):
        data = json.loads(source.read_text())
        for key, record in data.items():
            if record.get('status') not in {'applied', 'submitting'}:
                continue
            if key not in candidates or record['status'] == 'applied':
                candidates[key] = record
    path = Path(path)
    with file_lock(path.with_suffix('.lock')):
        existing = ExternalApplicationLedger(path)._read()
        for key, record in candidates.items():
            if key not in existing or existing[key].get('status') != 'applied' and record['status'] == 'applied':
                existing[key] = record
        write_json(path, existing)


def submit_employer_tab(driver, handle, url, *, job_id, title, company, description,
                        state_dir, provenance, checkpoint, pause='never', captcha_solver=True,
                        config_dir=None):
    from .submit_runner import ApplicationTab, run_submissions
    state_dir = Path(state_dir)
    ledger = state_dir/'external'/'applications.json'
    history = state_dir.parent/'direct_submit'
    import_submission_holds(ledger, history)
    job = load_jobs(url=url)[0]
    job.update(id='linkedin:'+str(job_id), title=title, company=company, description=description,
               provenance={'source': 'linkedin_search', 'linkedin_id': str(job_id), **provenance})

    def observe(_job, state):
        # Runs after the direct checkpoint is durable, before the Submit click.
        status = state['status']
        if status == 'applied':
            checkpoint('applied', 'Employer confirmed submission')
        elif status in {'submitting', 'submission_uncertain'} or state.get('verification_after_submit'):
            checkpoint('submitting', 'Employer submission awaiting confirmation')

    result = run_submissions([job], run_dir=history/('linkedin-'+str(job_id)),
        config_dir=config_dir, output_dir=state_dir.parent/'url_preparations',
        pause=pause, max_applications=1, workers=1, ledger_path=ledger,
        captcha_solver=captcha_solver, application_tab=ApplicationTab(driver, handle, observe),
        set_name='linkedin-external-submissions')
    row = result['jobs'][0]
    report_path = row.get('preparation_report')
    report = json.loads(Path(report_path).read_text()) if report_path and Path(report_path).is_file() else {}
    status = row['status']
    mapped = ('applied' if status == 'applied' else 'duplicate' if status == 'duplicate' else
              'submitting' if status in {'submission_uncertain', 'submitting'} or row.get('verification_after_submit') else
              'manual_handoff' if status in {'awaiting_manual_submit', 'awaiting_correction', 'awaiting_email_verification', 'awaiting_review'} else 'failed')
    identity = identify_ats(report.get('resolved_url', url))
    resume = report.get('resume') or {}
    return ExternalApplicationResult(mapped, report.get('resolved_url', url),
        provider=identity.provider if identity else None, ats_job_id=identity.job_id if identity else None,
        reason=row.get('reason') or row.get('stage') or status,
        submitted_at=row.get('submitted_at'), attempt_id=row.get('attempt_id', ''),
        resume_name=Path(resume['pdf']).name if resume.get('pdf') else None, resume_sha256=resume.get('pdf_sha256'),
        preparation_report=report_path, direct_run_id=result['run_id'], direct_run_dir=result['run_dir'],
        direct_status=status, retryable=bool(row.get('retryable')))


def finish_browser(driver, retained_handles):
    """Leave unresolved employer tabs alive; otherwise release the browser normally."""
    retained = set(retained_handles) & set(driver.window_handles)
    if retained:
        driver.switch_to.window(next(iter(retained)))
        driver.service.stop()
        return True
    driver.quit()
    return False

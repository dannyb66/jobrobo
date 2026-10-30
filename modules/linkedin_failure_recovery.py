"""Non-submitting recovery checks and local evidence for isolated job failures."""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import traceback
from uuid import uuid4


def capture_failure(driver, job_id, stage, error, directory):
    """Best-effort evidence must never replace the original application error."""
    report = dict(job_id=str(job_id), stage=stage, error_type=type(error).__name__,
                  error=str(error), traceback=''.join(traceback.format_exception(type(error), error, error.__traceback__)))
    if isinstance(getattr(error, 'navigation_evidence', None), list):
        report['navigation_evidence'] = error.navigation_evidence
    try:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        base = directory / f'{job_id}-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}-{uuid4().hex[:8]}'
        report['report_path'] = str(base.with_suffix('.json'))
        try:
            report['url'] = driver.current_url
            if driver.save_screenshot(str(base.with_suffix('.png'))):
                report['screenshot_path'] = str(base.with_suffix('.png'))
        except Exception as capture_error:
            report['screenshot_error'] = type(capture_error).__name__
        try:
            # Include open shadow-root dialogs, but remove input values and
            # textarea answers from the saved DOM. Screenshots stay local.
            markup = driver.execute_script('''/* jobrobo-failure-dom */
                const roots=[document], out=[];
                for(let i=0;i<roots.length && i<24;i++) {
                    // Application portals can be siblings of main. Capture
                    // the body plus shadow roots so the failed form is kept.
                    const root=roots[i], node=(root.body || root);
                    const clone=node.nodeType===11 ? document.createElement('section') : node.cloneNode(true);
                    if(node.nodeType===11) for(const child of node.childNodes) clone.append(child.cloneNode(true));
                    for(const e of clone.querySelectorAll('script,style')) e.remove();
                    for(const e of clone.querySelectorAll('input,textarea,[contenteditable="true"]')) {
                        e.removeAttribute('value');
                        if(e.tagName!=='INPUT') e.textContent='[omitted]';
                    }
                    out.push(clone.outerHTML || clone.innerHTML || '');
                    for(const e of root.querySelectorAll('*'))
                        if(e.shadowRoot && roots.length<24) roots.push(e.shadowRoot);
                }
                return out.join(String.fromCharCode(10));''')
            if isinstance(markup, str) and markup.strip():
                target = base.with_suffix('.private.html')
                target.write_text(markup, encoding='utf-8')
                target.chmod(0o600)
                report['dom_path'] = str(target)
            else:
                report['dom_error'] = 'No serializable page DOM'
        except Exception as capture_error:
            report['dom_error'] = type(capture_error).__name__
        base.with_suffix('.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    except Exception as capture_error:
        report['capture_error'] = type(capture_error).__name__
    return report


def reconcile_submission(driver, job_id, *, timeout=10, log=lambda _: None):
    """Read only: a delayed receipt or exact posting's submitted status is proof.

    Failure to find a receipt is uncertainty, never proof of non-submission.
    This function never clicks Submit or opens an application form.
    """
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.common.exceptions import StaleElementReferenceException
    from modules.linkedin_easy_apply import job_submission_receipts
    job_id = str(job_id)
    if not re.fullmatch(r'\d+', job_id):
        return False
    try:
        if job_submission_receipts(driver, job_id):
            return True
        # Leave a potentially stale confirmation overlay and check the actual
        # posting. The durable submitting checkpoint already prevents retries.
        driver.get('https://www.linkedin.com/jobs/view/' + job_id + '/')
        proof = WebDriverWait(driver, timeout, poll_frequency=.5,
                             ignored_exceptions=(StaleElementReferenceException,)).until(
            lambda browser: job_submission_receipts(browser, job_id))
        log(f'Application [{job_id}]: submission confirmed on the exact job page')
        return bool(proof)
    except Exception as error:
        log(f'Application [{job_id}]: outcome remains unverified ({type(error).__name__}); held out of retries')
        return False


def role_is_relevant(title, description, spec):
    """Use the engineering-family guard when the configured query requests it."""
    from modules.job_pipeline.careers import classify_engineering_role
    from modules.job_pipeline.linkedin import role_matches
    if spec.pipeline_context or classify_engineering_role(spec.classic_query)['engineering_related']:
        return role_matches(title, description, spec)
    return True

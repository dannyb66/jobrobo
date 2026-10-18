"""Scoped Easy Apply navigation for classic and semantic LinkedIn dialogs.

Navigation stops at the final Submit screen. Only the caller may authorize Submit.
Logs contain step/action names, never field values or application answers.
"""
from __future__ import annotations

import re
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait


class EasyApplyError(RuntimeError):
    pass


class MissingApplicationAnswer(EasyApplyError):
    """A required personal answer is absent; never invent free-text answers."""


DIALOGS = 'dialog[open], .jobs-easy-apply-modal, [role="dialog"], [aria-modal="true"]'
BUTTONS = 'button, [role="button"]'
ERRORS = '.artdeco-inline-feedback--error, [aria-invalid="true"], [role="alert"]'


def _visible(nodes):
    return [node for node in nodes if node.is_displayed()]


def _kind(button):
    kinds = set()
    for label in (button.get_attribute('aria-label'), button.text):
        label = ' '.join((label or '').lower().split())
        if label in {'next', 'continue', 'continue to next step'}:
            kinds.add('next')
        if label in {'review', 'review your application', 'review application'}:
            kinds.add('review')
        if label in {'submit', 'submit application', 'submit your application'}:
            kinds.add('submit')
    if len(kinds) > 1:
        raise EasyApplyError('navigation: button has conflicting action labels')
    return next(iter(kinds), None)


def _enabled(button):
    return (button.is_enabled() and button.get_attribute('aria-disabled') != 'true'
            and button.get_attribute('disabled') is None)


def _modal(driver):
    candidates = []
    for node in _visible(driver.find_elements(By.CSS_SELECTOR, DIALOGS)):
        classic = 'jobs-easy-apply-modal' in (node.get_attribute('class') or '').split()
        heading = (node.get_attribute('aria-label') or '') + ' ' + ' '.join(
            n.text for n in node.find_elements(By.CSS_SELECTOR, 'h1, h2, h3, [role="heading"]'))
        if re.search(r'\bdiscard\b|\bleave application\b|\bsave.*application\b', heading, re.I):
            continue
        actions = any(_kind(b) for b in _visible(node.find_elements(By.CSS_SELECTOR, BUTTONS)))
        # Discard/leave dialogs must never be mistaken for application forms.
        application = bool(re.search(r'\bapply\b|\bapplication\b',
                                    (node.get_attribute('aria-label') or '') + ' ' + node.text, re.I))
        fields = node.find_elements(By.CSS_SELECTOR, 'form, input, textarea, select')
        if classic:
            return node
        if actions and (application or fields):
            candidates.append(node)
    if len(candidates) > 1:
        # Prefer the innermost dialog when semantic wrappers are nested.
        candidates = [node for node in candidates if not any(
            child.id != node.id and driver.execute_script('return arguments[0].contains(arguments[1]);', node, child)
            for child in candidates)]
        if len(candidates) > 1:
            raise EasyApplyError('open: multiple visible application dialogs')
    return candidates[0] if candidates else False


def _wait(driver, condition, timeout):
    return WebDriverWait(driver, timeout, poll_frequency=.1,
                         ignored_exceptions=(StaleElementReferenceException,)).until(condition)


def wait_for_application_modal(driver, *, timeout=10):
    try:
        return _wait(driver, _modal, timeout)
    except TimeoutException as error:
        raise EasyApplyError('open: visible Easy Apply dialog not found (classic or semantic UI)') from error


def _state(driver):
    modal = _modal(driver)
    if not modal:
        return False
    buttons = [(b, _kind(b)) for b in _visible(modal.find_elements(By.CSS_SELECTOR, BUTTONS))]
    # Next takes precedence: never jump to Review while there are more form pages.
    for kind in ('next', 'review', 'submit'):
        found = [b for b, action in buttons if action == kind]
        if len(found) > 1:
            raise EasyApplyError(f'{kind}: ambiguous visible navigation controls')
        if found:
            return modal, kind, found[0]
    return False


def _signature(modal, kind):
    # Compare structural identity and visible text, not DOM instance identity:
    # React may replace a dialog without advancing to the next page.
    fields = tuple((n.get_attribute('id'), n.get_attribute('name'), n.get_attribute('type'))
                   for n in modal.find_elements(By.CSS_SELECTOR, 'input, textarea, select'))
    sections = tuple(n.text for n in modal.find_elements(
        By.CSS_SELECTOR, 'h1, h2, h3, legend, label, [role="heading"], [role="progressbar"]'))
    # SDUI education/work-history steps can contain only paragraph cards:
    # identical Next controls and no editable fields or semantic headings.
    content = tuple(n.text for n in modal.find_elements(
        By.XPATH, ".//*[@data-testid='dialog-content']//p[not(ancestor::*[@role='status' or @role='alert'])]"))
    return kind, sections, fields, content


def advance_to_review(driver, fill_step, *, timeout=10, max_steps=15, on_blocked=None, log=lambda _: None):
    """Fill every form page, await each transition, and return at final Submit.

    fill_step receives a freshly acquired modal, including for one-page forms.
    on_blocked may invite manual field correction; it must not click navigation.
    """
    wait_for_application_modal(driver, timeout=timeout)
    for step in range(1, max_steps + 1):
        try:
            state = _wait(driver, _state, timeout)
        except TimeoutException as error:
            raise EasyApplyError(f'step {step}: no Next, Review or Submit control in application dialog') from error
        modal, kind, button = state
        log(f'Easy Apply step {step}: {kind}')
        # Exceptions from answering/uploading must propagate without any final action.
        try:
            fill_step(modal)
        except MissingApplicationAnswer as error:
            if on_blocked and on_blocked(str(error)):
                continue
            raise
        # Answering or uploading may rerender the dialog; always reacquire controls.
        try:
            modal, current_kind, button = _wait(driver, _state, timeout)
        except TimeoutException as error:
            raise EasyApplyError(f'step {step}: form controls disappeared after filling') from error
        if current_kind != kind:
            raise EasyApplyError(f'step {step}: form changed unexpectedly while filling')
        if kind == 'submit':
            if not _enabled(button):
                raise EasyApplyError('review: Submit application is disabled')
            return modal
        if not _enabled(button):
            reason = f'step {step}: {kind} is disabled; correct required fields'
            if on_blocked and on_blocked(reason):
                continue
            raise EasyApplyError(reason)
        before = _signature(modal, kind)
        driver.execute_script('arguments[0].scrollIntoView({block: "center"});', button)
        try:
            button.click()
        except Exception as error:
            raise EasyApplyError(f'step {step}: {kind} click failed ({type(error).__name__})') from error

        def changed(browser):
            current = _state(browser)
            if not current:
                return False
            root, action, _ = current
            invalid = _visible(root.find_elements(By.CSS_SELECTOR, ERRORS))
            # Alerts can contain unrelated status text; aria-invalid/error class
            # remain authoritative, alert text must indicate a form error.
            invalid = [n for n in invalid if n.get_attribute('aria-invalid') == 'true'
                       or 'error' in (n.get_attribute('class') or '')
                       or re.search(r'required|invalid|please enter|please select|error', n.text, re.I)]
            if invalid:
                return 'validation'
            return 'advanced' if _signature(root, action) != before else False

        try:
            transition = _wait(driver, changed, timeout)
            reason = f'step {step}: {kind} blocked by form validation' if transition == 'validation' else None
        except TimeoutException:
            reason = f'step {step}: {kind} did not advance the form'
        if reason:
            log(reason)
            if on_blocked and on_blocked(reason):
                continue
            raise EasyApplyError(reason)
    raise EasyApplyError(f'navigation: exceeded {max_steps} form steps without reaching review')


def current_submit_button(driver, *, timeout=10):
    """Recheck final state after the user's review; never advance on their behalf."""
    try:
        modal, kind, button = _wait(driver, _state, timeout)
    except TimeoutException as error:
        raise EasyApplyError('review: final application screen unavailable') from error
    if kind != 'submit' or not _enabled(button):
        raise EasyApplyError('review: application is not on an enabled final Submit screen')
    return modal, button


def job_submission_receipts(driver, job_id):
    """Read applied state only inside the pane bound to this exact posting.

    Modern LinkedIn renders a persistent Application status panel outside any
    dialog or live region. Stable tokens omit elapsed time so an old receipt
    cannot become new merely because its timestamp changed.
    """
    from modules.linkedin_job_details import modern_details_root
    try:
        root = modern_details_root(driver, job_id)
        if root is None:
            return set()
        labels = [' '.join(node.text.split()) for node in _visible(root.find_elements(
            By.CSS_SELECTOR, 'p, h2, h3, [role="heading"]'))]
        result = set()
        if any(label.lower() == 'application status' for label in labels):
            if any(re.fullmatch(r'(?:your\s+)?application\s+(?:(?:has been|was)\s+)?(?:sent|submitted)(?:\s+successfully)?',
                                label, re.I) for label in labels):
                result.add(f'job:{job_id}:application-submitted')
        if re.search(r'\bApplied\s+(?:just now|\d+\s+(?:second|minute)s?\s+ago)\b', root.text, re.I):
            result.add(f'job:{job_id}:applied-badge')
        return result
    except (ValueError, StaleElementReferenceException):
        return set()


def submission_receipts(driver, job_id=None):
    """Snapshot receipts before Submit, including the selected job's status."""
    result = set()
    for node in _visible(driver.find_elements(By.CSS_SELECTOR, DIALOGS + ', [role="alert"], [role="status"]')):
        text = node.text.strip()
        if re.search(r'(?:^|\n)(?:your\s+)?application\s+(?:(?:has been|was)\s+)?(?:sent|submitted)\b', text, re.I):
            result.add(text)
    if job_id is not None:
        result.update(job_submission_receipts(driver, job_id))
    return result


def wait_for_submission_confirmation(driver, job_id, *, baseline, timeout=15):
    """Require a new explicit receipt; a successful click alone is not proof."""
    def confirmed(browser):
        return bool(submission_receipts(browser, job_id=job_id) - baseline)
    try:
        return bool(_wait(driver, confirmed, timeout))
    except TimeoutException as error:
        raise EasyApplyError('submit: no LinkedIn confirmation received; submission is uncertain, do not retry automatically') from error

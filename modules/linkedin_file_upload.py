"""Attach a resume through LinkedIn's intercepted native file chooser.

Legacy named file inputs retain their existing Selenium behavior. Modern forms
can create an otherwise absent input only when Chrome intercepts the chooser.
This module never verifies resume content, opens an application, or submits one.

Protocol: https://chromedevtools.github.io/devtools-protocol/tot/Page/#method-setInterceptFileChooserDialog
"""

from pathlib import Path
import math
import re

from modules.resume_upload import ResumeUploadError


FILE_INPUTS = "//input[translate(@type,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='file']"
UPLOAD_BUTTONS = (".//button[not(@disabled) and ("
                  "translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='upload resume' or "
                  "translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='upload resume')]")
SELECTED_RESUMES = ".//*[@role='radio' and @aria-checked='true']"
UPLOAD_PROGRESS = (".//*[translate(normalize-space(text()),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='uploading' "
                   "or contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'uploading resume')]")


def _upload_pending(modal):
    return any(element.is_displayed() for element in modal.find_elements('xpath', UPLOAD_PROGRESS))


def _identity(element):
    value = getattr(element, "id", None)
    return value if isinstance(value, str) and value else id(element)


def _visible(element):
    return element.is_displayed() and element.is_enabled()


def _wait(driver, predicate, timeout, wait):
    from selenium.common.exceptions import StaleElementReferenceException

    def poll(*_):
        try:
            return predicate()
        except StaleElementReferenceException:
            return False

    if wait is not None:
        result = wait(poll)
        if not result:
            raise ResumeUploadError("Resume attachment did not become ready")
        return result
    from selenium.webdriver.support.ui import WebDriverWait
    return WebDriverWait(driver, timeout).until(poll)


def _matching_selected(modal, filename):
    selected = [radio for radio in modal.find_elements("xpath", SELECTED_RESUMES)
                if radio.get_attribute("aria-label") == filename and _visible(radio)]
    # Modern LinkedIn renders a visually hidden native radio alongside a
    # visible label. Its live selected property, rather than ARIA attributes,
    # confirms the selection. Keep the lookup inside the active application.
    for radio in modal.find_elements('xpath', ".//input[@type='radio' and not(ancestor::*[@role='radio'])]"):
        if radio.get_attribute('role') == 'radio' and radio.get_attribute('aria-checked') is not None:
            continue  # The ARIA wrapper/state remains authoritative.
        if radio.get_attribute('aria-label') != filename or not radio.is_enabled() or not radio.is_selected():
            continue
        identity = radio.get_attribute('id')
        labels = radio.find_elements('xpath', './following-sibling::label | ./preceding-sibling::label')
        visible_label = any(_visible(label) and identity and label.get_attribute('for') == identity
                            for label in labels)
        visible_label |= any(_visible(label) for label in radio.find_elements('xpath', './ancestor::label[1]'))
        if radio.is_displayed() or visible_label:
            selected.append(radio)
    return selected


def contact_only_application(modal):
    """Recognize a final form containing only basic contact fields.

    An opt-in for these forms must not bypass an offered, broken upload control
    or a selected older resume. Unknown screening fields remain unsupported.
    """
    if modal.find_elements('xpath', ".//input[@type='file' or @type='radio'] | .//*[@role='radio']"):
        return False
    if modal.find_elements('xpath', ".//*[self::button or self::a][contains(translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'upload resume')]"):
        return False
    if modal.find_elements('xpath', ".//*[self::h1 or self::h2 or self::h3 or self::legend or self::label][translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='resume' or translate(normalize-space(.),'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz')='cv']"):
        return False
    labels = modal.find_elements('xpath', './/label[@for]')
    contact_fields = 0
    for control in modal.find_elements('xpath', './/input | .//select | .//textarea'):
        kind = (control.get_attribute('type') or 'text').casefold()
        if kind == 'hidden':
            continue
        identity = control.get_attribute('id')
        label = next((node.text.strip() for node in labels
                      if identity and node.get_attribute('for') == identity and node.text.strip()), '')
        label = label or control.get_attribute('aria-label') or ''
        if kind == 'checkbox':
            if identity == 'follow-company-checkbox' or re.match(r'^follow\b', label, re.I):
                continue
            return False
        label = ' '.join(label.rstrip('*').strip().casefold().split())
        if not re.fullmatch(r'(?:first name|last name|full name|name|email(?: address)?|mobile(?: phone)?(?: number)?|phone(?: number| country code)?|country code|telephone)', label):
            return False
        contact_fields += 1
    return contact_fields > 0


def _accepts_file(element, suffix):
    if not element.is_enabled():
        return False
    accepted = (element.get_attribute("accept") or "").casefold()
    if not accepted.strip():
        return True
    types = {part.strip() for part in accepted.split(",")}
    mime = {".pdf": "application/pdf", ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}.get(suffix)
    return suffix in types or bool(mime and mime in types) or "*/*" in types


class _ChooserControl:
    def __init__(self, target):
        self.target = target

    def send_keys(self, *values):
        if len(values) != 1 or not isinstance(values[0], (str, Path)):
            raise ResumeUploadError("Attach one local resume file at a time")
        raw = str(values[0])
        if "\n" in raw or "\r" in raw:
            raise ResumeUploadError("Resume path must identify one local file")
        try:
            path = Path(raw).expanduser().resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise ResumeUploadError("Resume file is unavailable") from error
        if not path.is_file():
            raise ResumeUploadError("Resume attachment must be a file")
        from selenium.common.exceptions import StaleElementReferenceException
        attempts=3 if self.target.refresh_modal is not None else 1
        for attempt in range(attempts):
            try:
                return self._attach(path)
            except StaleElementReferenceException:
                if attempt+1==attempts:
                    raise ResumeUploadError('Verified PDF upload could not be confirmed: LinkedIn kept replacing the upload controls') from None

    def _attach(self,path):
        from selenium.common.exceptions import NoSuchElementException, TimeoutException
        target = self.target
        driver, modal = target.driver, target.current_modal(refresh=True)
        try:
            legacy=modal.find_element('name','file')
        except NoSuchElementException:
            pass
        else:
            legacy.send_keys(str(path))
            return
        before = {_identity(element) for element in driver.find_elements("xpath", FILE_INPUTS)}
        selected_before = {_identity(element) for element in _matching_selected(modal, path.name)}
        selection_changed = not selected_before
        original_error = None
        phase = 'locating the Upload resume button'
        try:
            # Set this before clicking: Chrome must suppress the native picker.
            driver.execute_cdp_cmd("Page.setInterceptFileChooserDialog", {"enabled": True})

            def upload_button():
                from selenium.common.exceptions import StaleElementReferenceException
                try:
                    matches = [button for button in target.current_modal().find_elements("xpath", UPLOAD_BUTTONS) if _visible(button)]
                except StaleElementReferenceException:
                    target.current_modal(refresh=True)
                    return False
                if len(matches) > 1:
                    raise ResumeUploadError("Multiple Upload resume buttons in the application dialog")
                return matches[0] if matches else False

            _wait(driver, upload_button, target.timeout, target.wait).click()
            phase = 'waiting for the resume file input'

            def new_file_input():
                matches = [element for element in driver.find_elements("xpath", FILE_INPUTS)
                           if _identity(element) not in before and _accepts_file(element, path.suffix.casefold())]
                if len(matches) > 1:
                    raise ResumeUploadError("Multiple new resume file inputs; attachment is ambiguous")
                return matches[0] if matches else False

            control = _wait(driver, new_file_input, target.timeout, target.wait)
            control.send_keys(str(path))
            phase = 'waiting for the exact uploaded PDF to finish and become selected'
            # Reacquire once after the chooser selection because LinkedIn may
            # replace the upload dialog. Re-running the full semantic modal
            # discovery on every polling tick can stall on this page's large
            # nested dialog tree.
            target.current_modal(refresh=True)

            saw_uploading = False
            def selected_attachment():
                nonlocal selection_changed, saw_uploading
                from selenium.common.exceptions import StaleElementReferenceException
                try:
                    current = target.current_modal()
                    pending = _upload_pending(current)
                    saw_uploading |= pending
                    selected = _matching_selected(current, path.name)
                except StaleElementReferenceException:
                    target.current_modal(refresh=True)
                    return False
                if len(selected) > 1:
                    raise ResumeUploadError("Multiple selected attachments match the resume filename")
                if not selected:
                    selection_changed = True
                    return False
                if pending:
                    return False
                # An already selected attachment with the same name is not
                # proof that this upload completed. Require a newly rendered
                # selection or an observed deselection/reselection transition.
                return selection_changed or _identity(selected[0]) not in selected_before

            try:
                _wait(driver, selected_attachment, target.timeout, target.wait)
            except TimeoutException:
                # Keep waiting for this one upload rather than sending the PDF
                # a second time or regenerating it while LinkedIn is processing.
                if not saw_uploading or target.completion_timeout <= target.timeout:
                    raise
                target.log(f'Resume upload is still processing; extending attachment verification to '
                           f'{target.completion_timeout:g}s total without re-uploading the PDF')
                target.current_modal(refresh=True)
                _wait(driver, selected_attachment, target.completion_timeout-target.timeout, target.wait)
        except TimeoutException:
            error = ResumeUploadError(f'Resume upload timed out while {phase}; '
                f'uploading observed: {locals().get("saw_uploading", False)}. '
                'The verified PDF is retained for retry; no application was submitted.')
            original_error = error
            raise error from None
        except BaseException as error:
            original_error = error
            raise
        finally:
            try:
                driver.execute_cdp_cmd("Page.setInterceptFileChooserDialog", {"enabled": False})
            except Exception as error:
                if original_error is None:
                    raise ResumeUploadError("Could not disable file chooser interception after attachment") from error
                if hasattr(original_error, "add_note"):
                    original_error.add_note("File chooser interception cleanup also failed")


class _ResumeUploadTarget:
    def __init__(self, driver, modal, timeout, wait, refresh_modal=None, completion_timeout=90, log=None):
        self.driver, self.modal, self.timeout, self.wait = driver, modal, timeout, wait
        self.refresh_modal=refresh_modal
        self.completion_timeout=max(timeout, completion_timeout)
        self.log=log or (lambda _: None)

    def current_modal(self, *, refresh=False):
        modal=self.modal
        if refresh and self.refresh_modal is not None:
            modal=self.refresh_modal()
        if modal is None:
            raise ResumeUploadError('Resume upload form is no longer available')
        self.modal=modal
        return modal

    def find_element(self, by, value):
        if by == "name" and value == "file":
            return _ChooserControl(self)
        return self.modal.find_element(by, value)

    def __getattr__(self, name):
        return getattr(self.modal, name)


def resume_upload_target(driver, modal, *, timeout=30, wait=None, refresh_modal=None, completion_timeout=90, log=None):
    """Return an upload target, or None when this form page has no upload UI.

    ``wait`` can inject a bounded polling callable for tests. The proxy preserves
    modal attributes; only ``find_element('name', 'file').send_keys(path)`` changes.
    Legacy named inputs return the modal unchanged unless refresh_modal is given.
    A refresh callback reacquires controls after generation and during selection
    confirmation; stale DOM retries reuse the same file and never regenerate it.
    A modern proxy is returned
    only when a visible enabled Upload resume button exists within this modal.
    Modern success additionally requires a selected filename radio in this modal.
    Resume content verification remains the caller's responsibility.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Resume upload timeout must be positive")
    if isinstance(completion_timeout, bool) or not isinstance(completion_timeout, (int, float)) or not math.isfinite(completion_timeout) or completion_timeout <= 0:
        raise ValueError("Resume upload completion timeout must be positive")
    from selenium.common.exceptions import NoSuchElementException
    try:
        modal.find_element("name", "file")
    except NoSuchElementException:
        if not any(_visible(button) for button in modal.find_elements("xpath", UPLOAD_BUTTONS)):
            return None
        return _ResumeUploadTarget(driver, modal, timeout, wait, refresh_modal, completion_timeout, log)
    return _ResumeUploadTarget(driver,modal,timeout,wait,refresh_modal,completion_timeout,log) if refresh_modal is not None else modal

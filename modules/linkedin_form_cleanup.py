"""Discard an unfinished application using scoped, non-submitting UI actions."""

import math
from time import monotonic

from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait

from modules.linkedin_easy_apply import DIALOGS, BUTTONS, EasyApplyError, wait_for_application_modal, _fit_warning


class ApplicationCleanupError(EasyApplyError):
    """The next job must not start while an application dialog may remain open."""


_QUIET_SECONDS = .3
_CLOSE = {"dismiss", "close", "dismiss application", "close application"}
_DISCARD = {"discard", "discard application"}


def _labels(element):
    return {" ".join(value.casefold().split()) for value in
            (element.get_attribute("aria-label"), element.text) if isinstance(value, str) and value.strip()}


def _visible_dialogs(driver):
    dialogs, seen = [], set()
    for node in driver.find_elements("css selector", DIALOGS):
        if node.is_displayed() and node.id not in seen:
            seen.add(node.id)
            dialogs.append(node)
    if len(dialogs) > 1:
        # Semantic wrappers can surround the actual native/classic dialog.
        dialogs = [node for node in dialogs if not any(
            other.id != node.id and driver.execute_script(
                "return arguments[0].contains(arguments[1]);", node, other) for other in dialogs)]
    return dialogs


def _confirmation(dialog):
    headings = [dialog.get_attribute("aria-label") or ""]
    headings.extend(node.text for node in dialog.find_elements("css selector", "h1, h2, h3, [role='heading']"))
    for identity in (dialog.get_attribute("aria-labelledby") or "").split():
        headings.extend(node.text for node in dialog.find_elements("id", identity))
    import re
    return bool(re.search(r"\b(?:save|discard|leave) (?:(?:your|this|the) )?application\b", " ".join(headings), re.I))


def _action(dialog, allowed, description):
    matches = []
    for button in dialog.find_elements("css selector", BUTTONS):
        if not button.is_displayed() or not button.is_enabled() or button.get_attribute("aria-disabled") == "true":
            continue
        labels = _labels(button)
        if labels & allowed:
            if allowed == _CLOSE and button.find_elements("xpath", (
                    "ancestor::*[@role='status' or @role='alert' or @data-testid='toasts' or "
                    "@data-testid='toast' or contains(@class,'toast')]")):
                continue
            permitted = allowed | ({"x", "×", "✕"} if allowed == _CLOSE else set())
            if not labels.issubset(permitted):
                raise ApplicationCleanupError(f"cleanup: conflicting {description} action labels")
            matches.append(button)
    if allowed == _CLOSE and matches:
        # Uploaded-resume toasts have their own Dismiss controls inside the
        # native application. Prefer the dialog's own direct/header control.
        direct = {node.id for node in dialog.find_elements("xpath", "./button | ./*[@role='button']")}
        header = {node.id for node in dialog.find_elements("xpath", (
            ".//*[@id='dialog-header']//button | .//*[@id='dialog-header']//*[@role='button'] | "
            ".//header//button | .//header//*[@role='button']"))}
        own = [button for button in matches if button.id in direct]
        matches = own or [button for button in matches if button.id in header] or matches
    if len(matches) > 1:
        raise ApplicationCleanupError(f"cleanup: multiple {description} actions")
    return matches[0] if matches else None


def discard_application(driver, timeout=5, *, wait=None):
    """Close a verified application, discard its draft, and await a clear UI.

    Save and Submit are never clicked. Unknown/ambiguous dialogs, missing exact
    discard actions, or a dialog that fails to close raise ApplicationCleanupError.
    A brief dialog-free interval also catches delayed discard confirmations.
    Each completed Dismiss/Discard action starts a fresh bounded phase, so slow
    browser calls cannot consume the final dialog-free verification budget.
    ``wait`` is an optional bounded polling callable for isolated tests.
    """
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Application cleanup timeout must be positive")
    dismissed = discarded = False
    generation = 0
    quiet_since = None
    started = monotonic()
    trace = {"phase": "start", "polls": 0, "last_dialog_count": None,
             "last_confirmation_count": None, "reacquire_errors": 0, "last_poll_seconds": 0}

    def diagnostics(error):
        now = monotonic()
        return dict(trace, elapsed_seconds=round(now - started, 3), timeout_seconds=timeout,
                    dismissed=dismissed, discarded=discarded,
                    quiet_seconds=round(now - quiet_since, 3) if quiet_since is not None else None,
                    cause_type=type(error).__name__)

    def clear(*_):
        nonlocal dismissed, discarded, quiet_since, generation
        poll_started = monotonic()
        trace["polls"] += 1
        try:
            trace["phase"] = "scan_dialogs"
            dialogs = _visible_dialogs(driver)
            trace["last_dialog_count"] = len(dialogs)
            if not dialogs:
                trace["phase"] = "quiet_window"
                now = monotonic()
                if quiet_since is None:
                    quiet_since = now
                    return False
                return now - quiet_since >= _QUIET_SECONDS
            quiet_since = None
            # Cleanup must close the pre-application warning, never Continue applying.
            warning = _fit_warning(driver)
            if warning:
                application, _ = warning
                if any(node.id != application.id for node in dialogs):
                    raise ApplicationCleanupError("cleanup: unrelated dialog remains behind fit warning")
                if dismissed:
                    trace["phase"] = "await_fit_warning_close"
                    return False
                trace["phase"] = "close_fit_warning"
                button = _action(application, _CLOSE, "Dismiss/Close")
                if button is None:
                    application.send_keys(Keys.ESCAPE)
                else:
                    button.click()
                dismissed = True
                generation += 1
                return False
            trace["phase"] = "classify_dialogs"
            confirmations = [dialog for dialog in dialogs if _confirmation(dialog)]
            trace["last_confirmation_count"] = len(confirmations)
            if len(confirmations) > 1:
                raise ApplicationCleanupError("cleanup: multiple discard confirmation dialogs")
            if confirmations:
                if len(dialogs) > 1:
                    # An underlying verified application may remain behind its
                    # confirmation, but an unrelated dialog must not be ignored.
                    try:
                        trace["phase"] = "reacquire_underlying_application"
                        application = wait_for_application_modal(driver, timeout=min(timeout, .2), continue_fit_warning=False)
                    except EasyApplyError:
                        # The underlying form can close after this poll's
                        # dialog snapshot. Recheck the current UI next poll.
                        trace["reacquire_errors"] += 1
                        trace["phase"] = "retry_reacquisition"
                        return False
                    if any(node.id not in {application.id, confirmations[0].id} for node in dialogs):
                        raise ApplicationCleanupError("cleanup: unrelated blocking dialog remains")
                if discarded:
                    trace["phase"] = "await_discard_close"
                    return False
                trace["phase"] = "find_discard"
                button = _action(confirmations[0], _DISCARD, "Discard")
                if button is None:
                    raise ApplicationCleanupError("cleanup: confirmation has no exact Discard action")
                trace["phase"] = "discard_click"
                button.click()
                discarded = True
                generation += 1
                trace["phase"] = "await_discard_close"
                return False
            if dismissed:
                trace["phase"] = "await_dismiss"
                return False
            try:
                trace["phase"] = "reacquire_application"
                application = wait_for_application_modal(driver, timeout=min(timeout, .2), continue_fit_warning=False)
            except EasyApplyError:
                # Reacquisition can race React closing/replacing the form.
                # The outer bounded wait still rejects persistent blockers.
                trace["reacquire_errors"] += 1
                trace["phase"] = "retry_reacquisition"
                return False
            if any(node.id != application.id for node in dialogs):
                raise ApplicationCleanupError("cleanup: unrelated blocking dialog remains")
            trace["phase"] = "find_close"
            button = _action(application, _CLOSE, "Dismiss/Close")
            if button is None:
                trace["phase"] = "escape_application"
                application.send_keys(Keys.ESCAPE)
            else:
                trace["phase"] = "close_click"
                button.click()
            dismissed = True
            generation += 1
            trace["phase"] = "await_dismiss"
            return False
        except StaleElementReferenceException:
            trace["phase"] = "retry_stale_control"
            return False
        finally:
            trace["last_poll_seconds"] = round(monotonic() - poll_started, 3)

    try:
        if wait is not None:
            if not wait(clear):
                raise ApplicationCleanupError("cleanup: application dialog did not clear")
        else:
            # There are at most two completed actions: Dismiss and Discard.
            # Only those actions renew the budget; stale/repeated snapshots
            # cannot keep a stuck or unknown dialog alive indefinitely.
            for phase in range(3):
                observed_generation = generation
                trace["phase_budget"] = phase + 1

                def phase_complete(*args):
                    if clear(*args):
                        return True
                    return "progress" if generation != observed_generation else False

                result = WebDriverWait(driver, timeout, poll_frequency=.1).until(phase_complete)
                if result is True:
                    break
            else:
                raise ApplicationCleanupError("cleanup: application dialog did not clear after bounded phases")
    except ApplicationCleanupError as error:
        error.diagnostics = diagnostics(error)
        raise
    except (EasyApplyError, TimeoutException) as error:
        failure = ApplicationCleanupError("cleanup: could not confirm application and discard dialogs are closed")
        failure.diagnostics = diagnostics(error)
        raise failure from error
    return True

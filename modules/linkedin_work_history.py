"""Recover LinkedIn's work-history editor opened by Next-page validation."""

from pathlib import Path

from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

from modules.linkedin_easy_apply import EasyApplyError, dialog_elements
from modules.resume_experience_dates import best_experience_range, load_experience_ranges


DATE_LABELS = ("From Month", "From Year", "To Month", "To Year")


def repair_incomplete_work_history_summary(driver, modal, source_resume, questions, *, log=lambda _: None, timeout=5):
    """Open only a saved experience card explicitly missing employment dates."""
    result = driver.execute_script('''/* jobrobo-incomplete-work-summary */
      const root=arguments[0];
      for (const button of root.querySelectorAll('button[aria-label="Edit, Work Experience"]')) {
        if (!button.getClientRects().length) continue;
        for (let p=button.parentElement; p && p!==root; p=p.parentElement) {
          if (p.querySelectorAll('button[aria-label="Edit, Work Experience"]').length>1) break;
          const paragraphs=[...p.querySelectorAll('p')];
          const at=paragraphs.findIndex(n=>n.textContent.trim()==='Dates of employment');
          if(at>=0 && paragraphs[at+1] && /^(?:N\\/A|not provided|missing)$/i.test(paragraphs[at+1].textContent.trim()))
            return {button};
        }
      }
      return null;
    ''', modal)
    if not isinstance(result, dict) or result.get('button') is None:
        return False
    if not source_resume or not Path(source_resume).expanduser().is_file():
        raise EasyApplyError('work history: source resume unavailable for incomplete saved entry')
    button=result['button']
    driver.execute_script('arguments[0].scrollIntoView({block:"center"});',button)
    button.click()
    try:
        WebDriverWait(driver,timeout,poll_frequency=.1,
                      ignored_exceptions=(StaleElementReferenceException,)).until(_date_editor)
    except TimeoutException as error:
        raise EasyApplyError('work history: incomplete entry editor did not open') from error
    return repair_work_history_dates(driver,source_resume,questions,log=log,timeout=timeout)


def _date_editor(driver):
    """Require the observed employment editor, never an unrelated application select."""
    found = []
    for dialog in dialog_elements(driver):
        titles = dialog.find_elements(By.CSS_SELECTOR, 'input[aria-label="Your title"]')
        companies = dialog.find_elements(By.CSS_SELECTOR, 'input[aria-label="Company"]')
        if len(titles) != 1 or len(companies) != 1:
            continue
        selects = dialog.find_elements(By.CSS_SELECTOR, "select")
        if len(selects) != 4 or not all(node.is_displayed() for node in selects):
            continue
        placeholders = []
        for node in selects:
            options = node.find_elements(By.CSS_SELECTOR, "option")
            placeholders.append(options[0].text.strip().casefold() if options else "")
        if placeholders != ["month", "year", "month", "year"]:
            continue
        saves = [button for button in dialog.find_elements(By.CSS_SELECTOR, "button")
                 if button.is_displayed() and (button.text or "").strip().casefold() == "save"]
        if len(saves) == 1:
            found.append((dialog, titles[0], selects, saves[0]))
    if len(found) > 1:
        raise EasyApplyError("work history: more than one editable employment entry")
    return found[0] if found else None


def repair_work_history_dates(driver, source_resume, questions, *, log=lambda _: None, timeout=5):
    """Fill missing dates, Save the entry and verify the editor closes.

    LinkedIn may open this editor only after Next validates a summary page.
    Returning True tells navigation to reacquire and retry that summary page.
    """
    editor = _date_editor(driver)
    if editor is None:
        return False
    source = Path(source_resume).expanduser() if source_resume else None
    if source is None or not source.is_file():
        raise EasyApplyError("work history: source resume unavailable for date matching")
    match = best_experience_range(editor[1].get_attribute("value") or "",
                                  load_experience_ranges(source))
    if match is None:
        raise EasyApplyError("work history: source resume has no dated experience range")
    desired = (match.start_month, match.start_year, match.end_month, match.end_year)
    completed = 0
    log("Work history: Next opened an incomplete employment editor; filling missing Month/Year fields")
    for index, (label, value) in enumerate(zip(DATE_LABELS, desired)):
        # Each selection may replace the React controls. Reacquire the editor.
        editor = _date_editor(driver)
        if editor is None:
            raise EasyApplyError("work history: editor disappeared before dates were saved")
        control = Select(editor[2][index])
        previous = control.first_selected_option.text.strip()
        if previous.casefold() not in {"", "month", "year"}:
            continue
        control.select_by_visible_text(value)
        current = _date_editor(driver)
        if current is None or Select(current[2][index]).first_selected_option.text.strip() != value:
            raise EasyApplyError(f"work history: {label} selection did not persist")
        questions.add((label, value, "resume_work_history_date", previous))
        completed += 1
    editor = _date_editor(driver)
    if editor is None:
        raise EasyApplyError("work history: editor disappeared before Save")
    save = editor[3]
    if not save.is_enabled() or save.get_attribute("aria-disabled") == "true":
        raise EasyApplyError("work history: Save is disabled after date selection")
    driver.execute_script('arguments[0].scrollIntoView({block:"center"});', save)
    save.click()
    try:
        WebDriverWait(driver, timeout, poll_frequency=.1,
                      ignored_exceptions=(StaleElementReferenceException,)).until(
                          lambda browser: _date_editor(browser) is None)
    except TimeoutException as error:
        raise EasyApplyError("work history: Save did not close the employment editor") from error
    log(f"Work history: {completed} missing date fields selected; entry saved; retrying Next")
    return True

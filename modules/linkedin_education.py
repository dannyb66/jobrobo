"""Repair a saved education entry revealed by LinkedIn Next-page validation."""
import re
from pathlib import Path

from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait

from modules.linkedin_easy_apply import EasyApplyError, dialog_elements


def _normalize(text):
    return ' '.join(re.findall(r'[a-z0-9]+', text.casefold()))


def source_education(path):
    from docx import Document
    records, active, pending = [], False, None
    for paragraph in Document(str(path)).paragraphs:
        text = ' '.join(paragraph.text.split())
        if text.casefold() == 'education':
            active = True
            continue
        if not active:
            continue
        if text.casefold() in {'skills', 'experience', 'professional experience', 'work experience'}:
            break
        match = re.match(r'(.+?)\s+([A-Z][a-z]+)\s+(\d{4})\s*[-–—]\s*([A-Z][a-z]+)\s+(\d{4})$', text)
        if match:
            school, sm, sy, em, ey = match.groups()
            pending = dict(school=school, start_month=sm, start_year=sy, end_month=em, end_year=ey)
        elif pending and text:
            if re.search(r'\bmba\b|master.*business administration', text, re.I):
                pending.update(degree='Master of Business Administration (MBA)', field_of_study='Business Administration/Management')
            elif re.search(r'bachelor', text, re.I):
                pending.update(degree='Bachelor of Science (B.S)' if 'computer science' in text.casefold() else "Bachelor's Degree",
                               field_of_study='Computer Science' if 'computer science' in text.casefold() else text.split(',')[-1].split('GPA')[0].strip())
            else:
                pending = None
                continue
            records.append(pending)
            pending = None
    return records


def education_match(school, source, overrides):
    """Match the school itself; never borrow another school's degree or dates."""
    key = _normalize(school)
    for name, values in (overrides or {}).items():
        if _normalize(name) == key:
            return dict(values, school=school)
    tokens = set(key.split())
    ranked = []
    for record in source:
        other = set(_normalize(record['school']).split())
        score = len(tokens & other) / max(1, len(tokens | other))
        ranked.append((score, record))
    ranked.sort(key=lambda row: row[0], reverse=True)
    if ranked and ranked[0][0] >= .65:
        if len(ranked) == 1 or ranked[0][0] > ranked[1][0]:
            return ranked[0][1]
    return None


def _label(root, node):
    name = node.get_attribute('aria-label') or ''
    ident = node.get_attribute('id')
    if not name and ident:
        labels = root.find_elements(By.CSS_SELECTOR, 'label[for="' + ident + '"]')
        name = labels[0].text if labels else ''
    return _normalize(name)


def _editor(driver):
    found = []
    for root in dialog_elements(driver):
        selects = [node for node in root.find_elements(By.CSS_SELECTOR, 'select') if node.is_displayed()]
        degree = next((n for n in selects if _label(root, n) == 'education degree'), None)
        study = next((n for n in selects if _label(root, n) == 'education field of study'), None)
        schools = [n for n in root.find_elements(By.CSS_SELECTOR, 'input')
                   if n.is_displayed() and _label(root, n) == 'school']
        saves = [n for n in root.find_elements(By.CSS_SELECTOR, 'button')
                 if n.is_displayed() and n.text.strip().casefold() == 'save']
        if degree is not None and study is not None and len(schools) == len(saves) == 1:
            found.append((len(selects), root, schools[0], degree, study, saves[0]))
    return min(found, key=lambda row: row[0]) if found else None


def _option(select, desired):
    aliases = {'computer science': {'computer science', 'computer and information science'},
               'business administration management': {'business administration management', 'business administration'}}
    key = _normalize(desired)
    allowed = aliases.get(key, {key})
    return next((option.text for option in select.options
                 if _normalize(option.text) in allowed and option.is_enabled()), None)


def repair_education(driver, source_resume, overrides, questions, *, log=lambda _: None, timeout=5, infer=None):
    editor = _editor(driver)
    if editor is None:
        return False
    school = editor[2].get_attribute('value') or ''
    source = source_education(source_resume) if source_resume and Path(source_resume).is_file() else []
    record = education_match(school, source, overrides)
    inferred = False
    if record is None and infer is not None:
        options = {name: [option.text for option in Select(editor[index]).options
                         if option.is_enabled() and _normalize(option.text) not in {'', 'select an option', 'select', 'n a'}]
                   for index, name in [(3, 'degree'), (4, 'field_of_study')]}
        date_controls = [node for node in editor[1].find_elements(By.CSS_SELECTOR, 'select')
                         if node.id not in {editor[3].id, editor[4].id} and node.is_displayed()]
        timeline = [Select(node).first_selected_option.text.strip() for node in date_controls]
        # A two-year entry completed before the source bachelor's starts is
        # pre-university education, not another bachelor's inferred from a name.
        bachelor_starts = [int(row['start_year']) for row in source if re.search(r'bachelor', row.get('degree', ''), re.I)]
        years = [int(text) for text in timeline if re.fullmatch(r'\d{4}', text)]
        if bachelor_starts and len(years) == 2 and years[-1] <= min(bachelor_starts) and 0 < years[-1] - years[0] <= 3:
            earlier_choices = [text for text in options['degree'] if _normalize(text) in {'high school', 'ged'}]
            if earlier_choices:
                options['degree'] = earlier_choices
                first_degree = min((row for row in source if re.search(r'bachelor', row.get('degree', ''), re.I)),
                                   key=lambda row: int(row['start_year']))
                focus = _option(Select(editor[4]), first_degree.get('field_of_study', ''))
                if focus:
                    options['field_of_study'] = [focus]
        record = infer(dict(school=school, existing_dates=timeline, options=options, source_education=source))
        inferred = True
    if record is None:
        raise EasyApplyError('education: degree and field-of-study mapping needed for school ' + school)
    log('Education: Next opened an incomplete education editor; repairing required selections')
    for index, name in [(3, 'degree'), (4, 'field_of_study')]:
        current = _editor(driver)
        if current is None:
            raise EasyApplyError('education: editor disappeared before Save')
        select = Select(current[index])
        previous = select.first_selected_option.text.strip()
        if previous.casefold() not in {'', 'select an option', 'n/a', 'select'}:
            continue
        choice = _option(select, str(record.get(name, '')))
        if not choice:
            raise EasyApplyError('education: no supported ' + name + ' option for school ' + school)
        select.select_by_visible_text(choice)
        current = _editor(driver)
        if current is None or Select(current[index]).first_selected_option.text.strip() != choice:
            raise EasyApplyError('education: selection did not persist: ' + name)
        questions.add((school + ': ' + name, choice, 'ai_inferred_education' if inferred else 'resume_education', previous))
    current = _editor(driver)
    if current is None or not current[5].is_enabled():
        raise EasyApplyError('education: Save unavailable after required selections')
    driver.execute_script('arguments[0].scrollIntoView({block:"center"});', current[5])
    current[5].click()
    try:
        WebDriverWait(driver, timeout, poll_frequency=.1,
                      ignored_exceptions=(StaleElementReferenceException,)).until(lambda d: _editor(d) is None)
    except TimeoutException as error:
        raise EasyApplyError('education: Save did not close the education editor') from error
    log('Education: required selections saved; retrying Next')
    return True

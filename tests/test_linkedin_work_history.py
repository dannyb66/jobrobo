import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from selenium.webdriver.common.by import By

from modules.linkedin_easy_apply import EasyApplyError, advance_to_review
from modules.linkedin_work_history import repair_work_history_dates
from test_linkedin_easy_apply import Browser, form


class NativeSelect:
    def __init__(self, element):
        self.options = element.find_elements(By.CSS_SELECTOR, 'option')

    @property
    def first_selected_option(self):
        return next((node for node in self.options if node.get_attribute('selected') is not None), self.options[0])

    def select_by_visible_text(self, value):
        matching = next(node for node in self.options if node.text == value)
        for node in self.options:
            node.node.attrs.pop('selected', None)
        matching.node.attrs['selected'] = ''


def editor():
    return '''<dialog open><h2>Apply to Example</h2><input aria-label="Your title" value="Software Engineer">
      <input aria-label="Company" value="Example"><p>Dates of employment</p><p>From</p>
      <select><option selected>Month</option><option>January</option><option>February</option></select>
      <select><option selected>Year</option><option>2015</option><option>2016</option></select>
      <p>To</p><select><option selected>Month</option><option>January</option></select>
      <select><option selected>Year</option><option>2017</option><option>2018</option></select>
      <div role="alert">This field is required</div><button>Save</button><button>Next</button></dialog>'''


class WorkHistoryRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'resume.docx'
        doc = Document()
        doc.add_paragraph('Senior Software Engineer January 2016 - January 2018')
        doc.save(self.source)
        select_patch = patch('modules.linkedin_work_history.Select', NativeSelect)
        select_patch.start()
        self.addCleanup(select_patch.stop)

    def test_validation_opens_editor_then_dates_saved_and_next_retried(self):
        saved = []
        fixed = False
        def clicked(node):
            nonlocal fixed
            if node.text == 'Save':
                saved.extend(NativeSelect(control).first_selected_option.text
                             for control in browser.find_elements(By.CSS_SELECTOR, 'select'))
                fixed = True
                browser.page = 0
            elif node.text == 'Next':
                browser.page = 2 if fixed else 1
            browser.render()
        browser = Browser([form('Work experience'), editor(), form('Review', 'Submit application')], on_click=clicked)
        questions = set()
        recovery = lambda reason: repair_work_history_dates(browser, self.source, questions, timeout=.2)
        advance_to_review(browser, lambda modal: None, on_blocked=recovery, timeout=1)
        self.assertEqual(saved, ['January', '2016', 'January', '2018'])
        self.assertEqual(browser.clicks, ['Next', 'Save', 'Next'])
        self.assertEqual(len(questions), 4)
        self.assertEqual(browser.page, 2)

    def test_without_recovery_original_validation_failure_is_reproduced(self):
        browser = Browser([form('Work experience'), editor()])
        with self.assertRaisesRegex(EasyApplyError, 'blocked by form validation'):
            advance_to_review(browser, lambda modal: None, timeout=.01)

    def test_preexisting_dates_preserved(self):
        saved = []
        markup = editor().replace('<option selected>Month</option><option>January</option><option>February</option>',
                                  '<option>Month</option><option>January</option><option selected>February</option>')
        def clicked(node):
            saved.extend(NativeSelect(control).first_selected_option.text
                         for control in browser.find_elements(By.CSS_SELECTOR, 'select'))
            browser.page = 1
            browser.render()
        browser = Browser([markup, form('Work experience')], on_click=clicked)
        questions = set()
        self.assertTrue(repair_work_history_dates(browser, self.source, questions, timeout=.01))
        self.assertEqual(saved, ['February', '2016', 'January', '2018'])
        self.assertEqual(len(questions), 3)

    def test_missing_source_does_not_select_or_save(self):
        browser = Browser([editor()])
        with self.assertRaisesRegex(EasyApplyError, 'source resume unavailable'):
            repair_work_history_dates(browser, self.source.with_name('missing.docx'), set(), timeout=.01)
        self.assertEqual(browser.clicks, [])

    def test_save_must_close_editor(self):
        browser = Browser([editor()], on_click=lambda node: None)
        with self.assertRaisesRegex(EasyApplyError, 'Save did not close'):
            repair_work_history_dates(browser, self.source, set(), timeout=.01)
        self.assertEqual(browser.clicks, ['Save'])

    def test_unrelated_selects_are_not_work_history(self):
        browser = Browser([form('Questions', extra='<select><option>Month</option></select>')])
        self.assertFalse(repair_work_history_dates(browser, self.source, set(), timeout=.01))
        self.assertEqual(browser.clicks, [])


if __name__ == '__main__':
    unittest.main()

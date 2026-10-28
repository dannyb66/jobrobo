import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docx import Document
from selenium.webdriver.common.by import By

from modules.linkedin_easy_apply import EasyApplyError, advance_to_review
from modules.linkedin_education import education_match, source_education, repair_education
from test_linkedin_easy_apply import Browser, form
from test_linkedin_work_history import NativeSelect


def editor(school='Example University'):
    return ('<dialog open><h2>Apply to Example</h2><p>Edit education</p>'
            f'<input aria-label="School" value="{school}">'
            '<select aria-label="Education Degree*"><option selected>Select an option</option>'
            '<option>Bachelor of Science (B.S)</option><option>Master of Business Administration (MBA)</option></select>'
            '<select aria-label="Education Field of Study*"><option selected>Select an option</option>'
            '<option>Computer and Information Science</option><option>Business Administration/Management</option></select>'
            '<div role="alert">This field is required</div><button>Save</button><button>Next</button></dialog>')


class EducationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source.docx'
        doc = Document()
        for text in ['EDUCATION', 'Example University\tAugust 2012 - May 2016',
                     "Bachelor's, Computer Science\tGPA 3.5", 'Other School\tAugust 2018 - May 2020',
                     'MBA', 'SKILLS', 'Computer Science']:
            doc.add_paragraph(text)
        doc.save(self.source)
        p = patch('modules.linkedin_education.Select', NativeSelect)
        p.start()
        self.addCleanup(p.stop)

    def test_parse_source_and_match_school_not_unrelated_entry(self):
        records = source_education(self.source)
        self.assertEqual(len(records), 2)
        self.assertEqual(education_match('Example University', records, {})['field_of_study'], 'Computer Science')
        self.assertIsNone(education_match('Unknown college', records, {}))

    def test_school_override_has_priority(self):
        row = education_match('Unknown college', [], {'Unknown college': {'degree': 'High School'}})
        self.assertEqual(row['degree'], 'High School')

    def test_validation_opens_editor_then_save_and_next_retried(self):
        saved, fixed = [], False
        def clicked(node):
            nonlocal fixed
            if node.text == 'Save':
                saved.extend(NativeSelect(n).first_selected_option.text for n in browser.find_elements(By.CSS_SELECTOR, 'select'))
                fixed = True
                browser.page = 0
            elif node.text == 'Next':
                browser.page = 2 if fixed else 1
            browser.render()
        browser = Browser([form('Education'), editor(), form('Review', 'Submit application')], on_click=clicked)
        questions = set()
        advance_to_review(browser, lambda modal: None, timeout=.01,
            on_blocked=lambda reason: repair_education(browser, self.source, {}, questions, timeout=.01))
        self.assertEqual(saved, ['Bachelor of Science (B.S)', 'Computer and Information Science'])
        self.assertEqual(browser.clicks, ['Next', 'Save', 'Next'])

    def test_unmatched_school_never_borrows_another_degree(self):
        browser = Browser([editor('Unknown College')])
        with self.assertRaisesRegex(EasyApplyError, 'mapping needed'):
            repair_education(browser, self.source, {}, set(), timeout=.01)
        self.assertEqual(browser.clicks, [])

    def test_save_must_close_editor(self):
        browser = Browser([editor()], on_click=lambda _: None)
        with self.assertRaisesRegex(EasyApplyError, 'Save did not close'):
            repair_education(browser, self.source, {}, set(), timeout=.01)

    def test_unrelated_form_ignored(self):
        self.assertFalse(repair_education(Browser([form()]), self.source, {}, set(), timeout=.01))

    def test_unmatched_school_can_use_enabled_ai_choices_and_save(self):
        payloads, questions = [], set()
        def infer(payload):
            payloads.append(payload)
            return dict(degree='Bachelor of Science (B.S)', field_of_study='Computer and Information Science')
        browser = Browser([editor('Unmatched school'), form('Education')])
        self.assertTrue(repair_education(browser, self.source, {}, questions, timeout=.01, infer=infer))
        self.assertEqual(payloads[0]['school'], 'Unmatched school')
        self.assertIn('Bachelor of Science (B.S)', payloads[0]['options']['degree'])
        self.assertTrue(all(q[2] == 'ai_inferred_education' for q in questions))

    def test_explicit_mapping_does_not_call_ai(self):
        def infer(_):
            raise AssertionError('Explicit mapping must win')
        browser = Browser([editor(), form('Education')])
        self.assertTrue(repair_education(browser, self.source, {}, set(), timeout=.01, infer=infer))

    def test_pre_university_timeline_cannot_infer_a_second_bachelors(self):
        payloads = []
        def infer(payload):
            payloads.append(payload)
            return dict(degree='High School', field_of_study='Computer and Information Science')
        markup = editor('Earlier School').replace('<select aria-label="Education Degree*">',
            '<select><option>Month</option></select><select><option>2010</option></select>'
            '<select><option>Month</option></select><select><option>2012</option></select>'
            '<select aria-label="Education Degree*"><option>High School</option>')
        browser = Browser([markup, form('Education')])
        self.assertTrue(repair_education(browser, self.source, {}, set(), timeout=.01, infer=infer))
        self.assertEqual(payloads[0]['options']['degree'], ['High School'])


if __name__ == '__main__':
    unittest.main()

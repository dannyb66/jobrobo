"""Native option captions and completing independent fields before reporting blockers."""
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from selenium.webdriver.common.by import By
from modules.linkedin_easy_apply import MissingApplicationAnswer
import test_linkedin_easy_apply as easy_apply_tests
from test_linkedin_modern_search import DOMBrowser


class NativeChoiceTests(unittest.TestCase):
    def test_captured_native_shape_answers_radio_and_later_experience_field(self):
        markup = (Path(__file__).parent/'fixtures/linkedin_native_radio_questions.html').read_text()
        browser, questions = easy_apply_tests.NavigationTests().answer_native_form(markup, years_of_experience='8')
        self.assertTrue(browser.find_element(By.ID, 'commute-yes').is_selected())
        self.assertFalse(browser.find_element(By.ID, 'commute-no').is_selected())
        self.assertEqual(browser.find_element(By.ID, 'years').get_attribute('value'), '8')
        self.assertTrue(any(q[2] == 'radio' and q[1] == 'Yes' for q in questions))

    def test_sponsorship_uses_configured_no_with_empty_native_labels(self):
        markup = (Path(__file__).parent/'fixtures/linkedin_native_radio_questions.html').read_text()
        markup = markup.replace("Are you comfortable commuting to this job's location?", 'Would you require visa sponsorship?')
        browser, _ = easy_apply_tests.NavigationTests().answer_native_form(markup, require_visa='No', years_of_experience='8')
        self.assertTrue(browser.find_element(By.ID, 'commute-no').is_selected())
        self.assertFalse(browser.find_element(By.ID, 'commute-yes').is_selected())

    def test_unresolved_radio_does_not_prevent_later_text_field_from_being_filled(self):
        markup = '''<dialog open><fieldset aria-label="Required choice" aria-required="true">
          <input type="radio" id="unavailable" disabled><label for="unavailable">Unavailable</label></fieldset>
          <input id="years" type="text" aria-label="Years of experience?" required><button>Next</button></dialog>'''
        observed = []
        original = DOMBrowser.__init__
        def remember(browser, *args, **kwargs):
            original(browser, *args, **kwargs)
            observed.append(browser)
        with patch.object(DOMBrowser, '__init__', remember):
            with self.assertRaises((MissingApplicationAnswer, ValueError)):
                easy_apply_tests.NavigationTests().answer_native_form(markup, years_of_experience='8')
        self.assertEqual(observed[0].find_element(By.ID, 'years').get_attribute('value'), '8')

    def test_native_selection_failure_is_not_silently_accepted(self):
        from test_linkedin_modern_search import DOMElement
        markup = (Path(__file__).parent/'fixtures/linkedin_native_radio_questions.html').read_text()
        with patch.object(DOMElement, 'click', Mock()):
            with self.assertRaisesRegex(MissingApplicationAnswer, 'selection did not persist'):
                easy_apply_tests.NavigationTests().answer_native_form(markup, years_of_experience='8')

    def test_option_caption_lookup_cannot_escape_the_question_group(self):
        from modules.linkedin_form_fields import radio_options
        browser = DOMBrowser('''<div><p>Yes</p><fieldset id="group" aria-label="Question">
          <input id="unlabeled" type="radio"><label for="unlabeled"></label></fieldset></div>''')
        options = radio_options(browser.find_element(By.ID, 'group'))
        self.assertEqual(options[0]['text'], '')

    def test_plain_native_checkbox_captions_choose_configured_no_exclusively(self):
        from test_search_runner import ReceiptRecoveryTests
        browser, ns = ReceiptRecoveryTests().checkbox_form('''<p>Would you require visa sponsorship?*</p><fieldset>
          <div><div><input id="yes" type="checkbox" checked><label for="yes"></label></div><p>Yes</p></div>
          <div><div><input id="no" type="checkbox"><label for="no"></label></div><p>No</p></div>
          </fieldset>''', require_visa='No')
        questions = ns['answer_questions'](browser.find_element(By.CSS_SELECTOR, 'dialog'), set(), 'Bay Area')
        self.assertFalse(browser.find_element(By.ID, 'yes').is_selected())
        self.assertTrue(browser.find_element(By.ID, 'no').is_selected())
        self.assertEqual(browser.clicks, ['yes', 'no'])
        ns['answer_questions'](browser.find_element(By.CSS_SELECTOR, 'dialog'), questions, 'Bay Area')
        self.assertEqual(browser.clicks, ['yes', 'no'])

    def test_plain_native_binary_agreement_still_requires_confirmation(self):
        from test_search_runner import ReceiptRecoveryTests
        browser, ns = ReceiptRecoveryTests().checkbox_form('''<p>Do you agree to sign electronically?*</p><fieldset>
          <div><input id="yes" type="checkbox"><label for="yes"></label><p>Yes</p></div>
          <div><input id="no" type="checkbox"><label for="no"></label><p>No</p></div></fieldset>''')
        with self.assertRaisesRegex(MissingApplicationAnswer, 'needs confirmation'):
            ns['answer_questions'](browser.find_element(By.CSS_SELECTOR, 'dialog'), set(), 'Bay Area')
        self.assertEqual(browser.clicks, [])

    def test_nonbinary_tool_checkboxes_are_not_treated_as_exclusive_choices(self):
        from modules.linkedin_form_fields import fill_binary_checkbox_groups
        browser = DOMBrowser('''<dialog open><fieldset><legend>Which tools have you used?</legend>
          <div><input type="checkbox" checked><label></label><p>Python</p></div>
          <div><input type="checkbox" checked><label></label><p>TypeScript</p></div>
          </fieldset></dialog>''')
        answer, click = Mock(), Mock()
        self.assertEqual(fill_binary_checkbox_groups(browser.find_element(By.CSS_SELECTOR, 'dialog'),
                         answer, click, set()), (set(), 0))
        answer.assert_not_called()
        click.assert_not_called()
        self.assertTrue(all(node.is_selected() for node in browser.find_elements(By.CSS_SELECTOR, 'input')))

    def test_independent_fields_do_not_accept_an_unapproved_agreement(self):
        from test_search_runner import ReceiptRecoveryTests
        browser, ns = ReceiptRecoveryTests().checkbox_form('''
          <div><input id="agreement" type="checkbox" required><label for="agreement">I agree to employment terms*</label></div>
          <div><input id="required" type="checkbox" required><label for="required">Required selection*</label></div>''')
        with self.assertRaisesRegex(MissingApplicationAnswer, 'agreement needs confirmation'):
            ns['answer_questions'](browser.find_element(By.CSS_SELECTOR, 'dialog'), set(), 'Bay Area')
        self.assertFalse(browser.find_element(By.ID, 'agreement').is_selected())
        self.assertTrue(browser.find_element(By.ID, 'required').is_selected())


class ContactOnlyPolicyTests(unittest.TestCase):
    def preparation(self, allowed=False, extra=''):
        from test_search_runner import extract_functions
        from modules.resume_upload import ResumeUploadError
        browser = DOMBrowser('''<dialog open><h2>Apply to Example</h2><h3>Contact info</h3>
          <label for="first">First name*</label><input id="first" type="text" value="Candidate">
          <label for="email">Email address*</label><input id="email" type="email" value="candidate@example.test">
          ''' + extra + '<button>Submit application</button></dialog>')
        modal = browser.find_element(By.CSS_SELECTOR, 'dialog')
        def navigate(driver, fill, **kwargs):
            fill(modal)
            return modal
        ns = dict(driver=browser, By=By, use_AI_for_resume=True,
                  ResumeUploadError=ResumeUploadError,
                  allow_contact_only_easy_apply=allowed, print_lg=Mock(),
                  wait_for_application_modal=lambda _: modal, advance_to_review=navigate,
                  answer_questions=Mock(return_value=set()), resume_upload_target=Mock(return_value=None))
        extract_functions(ns, 'prepare_easy_apply')
        return ns

    def test_default_keeps_contact_only_job_queued_with_specific_reason(self):
        from modules.resume_upload import ResumeUploadError
        ns = self.preparation()
        with self.assertRaisesRegex(ResumeUploadError, 'resume_upload_unavailable'):
            ns['prepare_easy_apply']('123', 'Engineer', 'JD', 'Bay Area')

    def test_explicit_opt_in_allows_contact_only_without_claiming_pdf_uploaded(self):
        ns = self.preparation(True)
        _, _, uploaded, resume = ns['prepare_easy_apply']('123', 'Engineer', 'JD', 'Bay Area')
        self.assertFalse(uploaded)
        self.assertEqual(resume, 'Not requested (contact-only Easy Apply)')

    def test_contact_only_opt_in_does_not_bypass_other_missing_resume_cases(self):
        from modules.resume_upload import ResumeUploadError
        for extra in ('<label for="q">Required personal answer*</label><input id="q" type="text">',
                      '<input type="radio" aria-label="Selected resume" checked>',
                      '<button>Upload resume</button>',
                      '<h3>Resume</h3><button>previous.pdf</button>'):
            with self.subTest(extra=extra):
                ns = self.preparation(True, extra)
                with self.assertRaises(ResumeUploadError):
                    ns['prepare_easy_apply']('123', 'Engineer', 'JD', 'Bay Area')

    def test_opt_in_does_not_bypass_failed_upload(self):
        from modules.resume_upload import ResumeUploadError
        ns = self.preparation(True)
        ns.update(default_resume_docx_path='source.docx', first_name='Test', last_name='Candidate',
                  upload_optimized_resume=Mock(return_value=(False, 'Upload failed')))
        ns['resume_upload_target'].return_value = Mock()
        with self.assertRaisesRegex(ResumeUploadError, 'Upload failed'):
            ns['prepare_easy_apply']('123', 'Engineer', 'JD', 'Bay Area')

"""Exercise real navigation against rerendered classic/semantic form DOMs."""
import unittest
import re
from unittest.mock import Mock
from bs4 import BeautifulSoup
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from modules.linkedin_easy_apply import (
    EasyApplyError, advance_to_review, current_submit_button,
    submission_receipts, wait_for_application_modal, wait_for_submission_confirmation,
)
from modules.application_choices import choose_index, dropdown_placeholder
from test_search_runner import extract_functions
from types import SimpleNamespace


class Node:
    def __init__(self, browser, node):
        self.browser, self.node, self.revision = browser, node, browser.revision
        self.id = f'{self.revision}:{id(node)}'

    def check(self):
        if self.revision != self.browser.revision:
            raise StaleElementReferenceException()

    @property
    def text(self):
        self.check()
        return self.node.get_text(' ', strip=True)

    def get_attribute(self, name):
        self.check()
        value = self.node.get(name)
        return ' '.join(value) if isinstance(value, list) else value

    def is_displayed(self):
        self.check()
        return not any(n.has_attr('hidden') or 'display:none' in n.get('style', '').replace(' ', '')
                       for n in [self.node, *self.node.parents] if hasattr(n, 'attrs'))

    def is_enabled(self):
        return not self.node.has_attr('disabled')

    def find_elements(self, by, selector):
        self.check()
        if by != By.CSS_SELECTOR:
            return []
        return [Node(self.browser, n) for n in self.node.select(selector)]

    def click(self):
        self.check()
        self.browser.clicks.append(self.text)
        if self.browser.on_click:
            self.browser.on_click(self)
        elif self.browser.page + 1 < len(self.browser.pages):
            self.browser.page += 1
            self.browser.render()


class Browser:
    def __init__(self, pages, on_click=None):
        self.pages, self.page, self.revision = pages, 0, 0
        self.clicks, self.on_click = [], on_click
        self.render()

    def render(self):
        self.revision += 1
        self.root = BeautifulSoup(self.pages[self.page], 'html.parser')

    def find_elements(self, by, selector):
        return [Node(self, n) for n in self.root.select(selector)] if by == By.CSS_SELECTOR else []

    def execute_script(self, script, *args):
        if 'contains' in script:
            return args[0].node in args[1].node.parents


def form(heading='Contact info', action='Next', classic=False, extra='', attributes=''):
    root = 'class="jobs-easy-apply-modal"' if classic else 'role="dialog" aria-label="Apply to Example"'
    return f'<div {root}><h2>{heading}</h2><form><label for="field">{heading}</label><input id="{heading}" name="field"></form>{extra}<button {attributes}><span>{action}</span></button></div>'


class NavigationTests(unittest.TestCase):
    def navigate(self, browser, fill=None, **kwargs):
        return advance_to_review(browser, fill or (lambda modal: None), timeout=.01, **kwargs)

    def test_fit_warning_plain_text_classic_modal_continues(self):
        warning='''<div class="artdeco-modal"><p>This job may not be the best fit —
            position yourself to stand out</p><button>Continue applying</button>
            <button>Explore more jobs</button></div>'''
        browser=Browser([warning,form(action='Submit application')])
        self.navigate(browser)
        self.assertEqual(browser.clicks,['Continue applying'])

    def test_fit_warning_semantic_plain_text_without_heading_continues(self):
        warning='''<dialog open><p>This job may not be the best fit — position yourself to stand out</p>
            <button>Continue applying</button><button>Explore more jobs</button></dialog>'''
        browser=Browser([warning,form(action='Submit application')])
        self.navigate(browser)
        self.assertEqual(browser.clicks,['Continue applying'])

    def test_fit_warning_can_be_detected_without_clicking_during_cleanup(self):
        browser=Browser(['<dialog open><h2>This job may not be the best fit</h2>'
            '<button>Continue applying</button></dialog>'])
        with self.assertRaises(EasyApplyError):
            wait_for_application_modal(browser,timeout=.01,continue_fit_warning=False)
        self.assertEqual(browser.clicks,[])

    def test_fit_warning_continues_then_fills_pages_without_submitting(self):
        warning='''<dialog open><h2>This job may not be the best fit — position yourself to stand out</h2>
            <a>Recommended job</a><button>Continue applying</button><button>Explore more jobs</button></dialog>'''
        browser=Browser([warning,form(),form('Questions','Review'),form('Review','Submit application')])
        fill=Mock()
        self.navigate(browser,fill)
        self.assertEqual(browser.clicks,['Continue applying','Next','Review'])
        self.assertEqual(fill.call_count,3)

    def test_fit_warning_waits_for_dismissal_and_clicks_only_once(self):
        warning='''<div role="dialog"><h2>This job may not be the best fit</h2>
            <button>Continue applying</button><button>Explore more jobs</button></div>'''
        browser=Browser([warning+form(action='Submit application')],on_click=lambda _:None)
        fill=Mock()
        with self.assertRaisesRegex(EasyApplyError,'Continue applying did not open'):
            self.navigate(browser,fill)
        self.assertEqual(browser.clicks,['Continue applying'])
        fill.assert_not_called()

    def test_fit_warning_ignores_hidden_and_unrelated_continue_buttons(self):
        browser=Browser(['<button>Continue applying</button><div role="dialog" hidden>'
            '<h2>This job may not be the best fit</h2><button>Continue applying</button></div>'
            +form(action='Submit application')])
        self.navigate(browser)
        self.assertEqual(browser.clicks,[])

    def test_fit_warning_disabled_or_duplicate_continue_never_clicks(self):
        for buttons in ('<button disabled>Continue applying</button>',
                '<button>Continue applying</button><button>Continue applying</button>'):
            browser=Browser(['<dialog open><h2>Position yourself to stand out</h2>'+buttons+'</dialog>'])
            with self.assertRaisesRegex(EasyApplyError,'fit.warning'):
                self.navigate(browser)
            self.assertEqual(browser.clicks,[])

    def test_fit_warning_supports_nested_dialogs_and_accessible_button_labels(self):
        warning='''<div role="dialog"><dialog open><h2>This job may not be\nthe best fit</h2>
            <button aria-label="Continue applying"><span aria-hidden="true">Proceed</span></button>
            <button>Explore more jobs</button></dialog></div>'''
        browser=Browser([warning,form(action='Submit application')])
        self.navigate(browser)
        self.assertEqual(browser.clicks,['Proceed'])

    def test_all_pages_filled_before_next_then_review_and_stop_before_submit(self):
        browser = Browser([form(), form('Resume'), form('Questions', 'Review'), form('Review', 'Submit application')])
        filled = []
        def fill(modal):
            filled.append((modal.find_elements(By.CSS_SELECTOR, 'h2')[0].text, len(browser.clicks)))
        modal = self.navigate(browser, fill)
        self.assertEqual(filled, [('Contact info', 0), ('Resume', 1), ('Questions', 2), ('Review', 3)])
        self.assertEqual(browser.clicks, ['Next', 'Next', 'Review'])
        self.assertEqual(current_submit_button(browser, timeout=.01)[0].id, modal.id)

    def test_classic_dialog_and_one_page_submission(self):
        for classic in (True, False):
            with self.subTest(classic=classic):
                browser = Browser([form(action='Submit application', classic=classic)])
                fill = Mock()
                self.navigate(browser, fill)
                fill.assert_called_once()
                self.assertEqual(browser.clicks, [])

    def test_native_dialog_without_explicit_role_excludes_background_pagination(self):
        # Observed LinkedIn SDUI markup: native <dialog open>, generated classes,
        # header/dialog-content/footer, no role="dialog" or aria-modal attribute.
        browser = Browser(['''<main><button>Next</button></main>
            <dialog open aria-labelledby="dialog-header" data-testid="dialog">
            <header id="dialog-header"><h2>Apply to Example</h2></header>
            <div data-testid="dialog-content"><label for="phone">Phone</label><input id="phone"></div>
            <footer><button>Submit application</button></footer></dialog>'''])
        fill = Mock()
        self.navigate(browser, fill)
        fill.assert_called_once()
        self.assertEqual(browser.clicks, [])

    def test_aria_labeled_continue_and_review(self):
        browser = Browser([form(action='Continue', attributes='aria-label="Continue to next step"'),
                           form(action='Review', attributes='aria-label="Review your application"'),
                           form(action='Submit application')])
        self.navigate(browser)
        self.assertEqual(browser.clicks, ['Continue', 'Review'])

    def test_conflicting_submit_and_next_labels_never_click_before_review(self):
        browser = Browser([form(action='Submit application', attributes='aria-label="Continue to next step"')])
        with self.assertRaisesRegex(EasyApplyError, 'conflicting action labels'):
            self.navigate(browser)
        self.assertEqual(browser.clicks, [])

    def test_no_dialog_reports_open_error(self):
        with self.assertRaisesRegex(EasyApplyError, 'open: visible Easy Apply dialog not found'):
            self.navigate(Browser(['<main><button>Next</button></main>']))

    def test_hidden_and_page_navigation_never_clicked(self):
        browser = Browser(['<button>Next</button><div role="dialog" hidden><button>Review</button></div>' +
                           form(action='Submit application')])
        self.navigate(browser)
        self.assertEqual(browser.clicks, [])

    def test_discard_dialog_is_not_an_application_form(self):
        browser = Browser(['<div role="dialog" aria-label="Discard application?"><button>Continue</button></div>'])
        with self.assertRaisesRegex(EasyApplyError, 'open:'):
            self.navigate(browser)
        self.assertEqual(browser.clicks, [])

    def test_nested_semantic_wrappers_refer_to_one_form(self):
        browser = Browser(['<div role="dialog" aria-label="Apply to Example">' + form(action='Submit application') + '</div>'])
        self.navigate(browser)
        self.assertEqual(browser.clicks, [])

    def test_disabled_next_never_clicked(self):
        for attribute in ('disabled', 'aria-disabled="true"'):
            browser = Browser([form(attributes=attribute)])
            with self.assertRaisesRegex(EasyApplyError, 'next is disabled'):
                self.navigate(browser)
            self.assertEqual(browser.clicks, [])

    def test_visible_validation_stops_without_review(self):
        def invalid(button):
            browser.pages[0] = form(extra='<div class="artdeco-inline-feedback--error">Required</div>')
            browser.render()
        browser = Browser([form()], invalid)
        with self.assertRaisesRegex(EasyApplyError, 'blocked by form validation'):
            self.navigate(browser)
        self.assertEqual(browser.clicks, ['Next'])

    def test_unchanged_page_and_transient_status_are_not_progress(self):
        def busy(button):
            browser.pages[0] = form(extra='<div role="status">Saving...</div>')
            browser.render()
        browser = Browser([form()], busy)
        with self.assertRaisesRegex(EasyApplyError, 'did not advance'):
            self.navigate(browser)
        self.assertEqual(browser.clicks, ['Next'])

    def test_filling_exception_never_advances(self):
        browser = Browser([form()])
        with self.assertRaisesRegex(ValueError, 'answer error'):
            self.navigate(browser, Mock(side_effect=ValueError('answer error')))
        self.assertEqual(browser.clicks, [])

    def test_upload_rerender_reacquires_button(self):
        browser = Browser([form(), form(action='Submit application')])
        def fill(modal):
            browser.render()
        self.navigate(browser, fill)
        self.assertEqual(browser.clicks, ['Next'])

    def test_manual_field_correction_then_navigation_retries(self):
        browser = Browser([form(attributes='disabled'), form(action='Submit application')])
        def correct(reason):
            browser.pages[0] = form()
            browser.render()
            return True
        self.navigate(browser, on_blocked=correct)
        self.assertEqual(browser.clicks, ['Next'])

    def test_step_limit_is_bounded_without_submission(self):
        browser = Browser([form(str(i)) for i in range(4)])
        with self.assertRaisesRegex(EasyApplyError, 'exceeded 2'):
            self.navigate(browser, max_steps=2)
        self.assertEqual(browser.clicks, ['Next', 'Next'])

    def test_review_recheck_rejects_back_navigation(self):
        browser = Browser([form()])
        with self.assertRaisesRegex(EasyApplyError, 'not on an enabled final Submit'):
            current_submit_button(browser, timeout=.01)
        self.assertEqual(browser.clicks, [])

    def test_old_receipt_is_not_confirmation_for_current_job(self):
        browser = Browser(['<div role="status">Your application was submitted</div>'])
        baseline = submission_receipts(browser)
        with self.assertRaisesRegex(EasyApplyError, 'submission is uncertain'):
            wait_for_submission_confirmation(browser, '123', baseline=baseline, timeout=.01)

    def test_new_explicit_receipt_confirms_submission(self):
        browser = Browser([form(action='Submit application'), '<div role="dialog">Your application was sent to Example</div>'])
        baseline = submission_receipts(browser)
        current_submit_button(browser, timeout=.01)[1].click()
        self.assertTrue(wait_for_submission_confirmation(browser, '123', baseline=baseline, timeout=.01))
        self.assertEqual(browser.clicks, ['Submit application'])

    def test_observed_job_status_panel_confirms_without_dialog_or_applied_badge(self):
        from test_linkedin_job_details import DetailDOMBrowser
        from lxml import etree
        browser = DetailDOMBrowser()
        root = browser.root.xpath("//*[@data-view-name='job-detail-page']")[0]
        root.insert(5, etree.fromstring('<div><h2>Application status</h2><p>Application submitted</p><p>5 minutes ago</p><a>View resume</a></div>'))
        self.assertTrue(wait_for_submission_confirmation(browser, '123', baseline=set(), timeout=.01))
        self.assertEqual(browser.clicks, [])

    def test_existing_status_panel_is_not_a_new_submission_even_when_time_changes(self):
        from test_linkedin_job_details import DetailDOMBrowser
        from lxml import etree
        browser = DetailDOMBrowser()
        root = browser.root.xpath("//*[@data-view-name='job-detail-page']")[0]
        panel = etree.fromstring('<div><h2>Application status</h2><p>Application submitted</p><p>1 minute ago</p></div>')
        root.insert(5, panel)
        baseline = submission_receipts(browser, job_id='123')
        self.assertIn('job:123:application-submitted', baseline)
        panel[-1].text = '2 minutes ago'
        with self.assertRaisesRegex(EasyApplyError, 'submission is uncertain'):
            wait_for_submission_confirmation(browser, '123', baseline=baseline, timeout=.01)

    def test_other_job_or_hidden_status_panel_does_not_confirm(self):
        from test_linkedin_job_details import DetailDOMBrowser
        from lxml import etree
        for kind in ('other-job', 'hidden', 'description-only'):
            with self.subTest(kind=kind):
                browser = DetailDOMBrowser()
                root = browser.root.xpath("//*[@data-view-name='job-detail-page']")[0]
                panel = etree.fromstring('<div><h2>Application status</h2><p>Application submitted</p></div>')
                if kind == 'hidden':
                    panel.set('style', 'display:none')
                    root.insert(5, panel)
                elif kind == 'description-only':
                    panel[0].text = 'Example description'
                    root.insert(5, panel)
                else:
                    browser.root.append(panel)
                with self.assertRaisesRegex(EasyApplyError, 'submission is uncertain'):
                    wait_for_submission_confirmation(browser, '123', baseline=set(), timeout=.01)
                self.assertEqual(browser.clicks, [])

    def test_mismatched_job_id_cannot_use_current_status_panel(self):
        from test_linkedin_job_details import DetailDOMBrowser
        from lxml import etree
        browser = DetailDOMBrowser()
        browser.root.xpath("//*[@data-view-name='job-detail-page']")[0].insert(5,
            etree.fromstring('<div><h2>Application status</h2><p>Application submitted</p></div>'))
        with self.assertRaisesRegex(EasyApplyError, 'submission is uncertain'):
            wait_for_submission_confirmation(browser, '999', baseline=set(), timeout=.01)

    def test_click_without_receipt_stays_uncertain(self):
        browser = Browser([form(action='Submit application')])
        baseline = submission_receipts(browser)
        current_submit_button(browser, timeout=.01)[1].click()
        with self.assertRaisesRegex(EasyApplyError, 'submission is uncertain'):
            wait_for_submission_confirmation(browser, '123', baseline=baseline, timeout=.01)
        self.assertEqual(browser.clicks, ['Submit application'])

    def test_textarea_first_does_not_require_text_input_autocomplete_state(self):
        field = Mock()
        values = {'value': ''}
        field.get_attribute.side_effect = lambda key: values.get(key)
        field.send_keys.side_effect = lambda value: values.update(value=value)
        label = SimpleNamespace(text='Summary')
        question = Mock(); modal = Mock(); modal.find_elements.return_value = [question]
        def locate(target, selector, *args):
            if selector == './/textarea':
                return field
            if selector == './/label[@for]':
                return label
            return False
        namespace = dict(By=By, try_xp=locate, driver=Mock(), overwrite_previous_answers=False,
                         linkedin_summary='Configured summary')
        extract_functions(namespace, 'answer_questions')
        result = namespace['answer_questions'](modal, set(), 'Bay Area')
        field.send_keys.assert_called_once_with('Configured summary')
        self.assertEqual(len(result), 1)

    def test_sdui_label_control_pairs_fill_tel_without_treating_resume_as_question(self):
        from test_linkedin_modern_search import DOMBrowser
        from selenium.common.exceptions import NoSuchElementException
        browser = DOMBrowser('''<dialog open><header><h2>Apply to Example</h2></header>
            <div data-testid="dialog-content"><div><label for="phone">Phone*</label>
            <div><input id="phone" type="tel" value="old"></div></div>
            <div role="radio" aria-label="resume.pdf"><input id="resume" type="radio">
            <label for="resume"></label></div></div><footer><button>Next</button></footer></dialog>''')
        modal = browser.find_element(By.CSS_SELECTOR, 'dialog')
        def locate(node, selector, *args):
            try:
                return node.find_element(By.XPATH, selector)
            except NoSuchElementException:
                return False
        namespace = dict(By=By, try_xp=locate, driver=browser, phone_number='5550100',
                         overwrite_previous_answers=True)
        extract_functions(namespace, 'answer_questions')
        questions = namespace['answer_questions'](modal, set(), 'Bay Area')
        self.assertEqual(modal.find_element(By.CSS_SELECTOR, '#phone').get_attribute('value'), '5550100')
        self.assertEqual(len(questions), 1)
        self.assertEqual(next(iter(questions))[0], 'phone*')

    def answer_native_form(self, markup, **configuration):
        from test_linkedin_modern_search import DOMBrowser
        from selenium.common.exceptions import NoSuchElementException
        browser = DOMBrowser(markup)
        browser.chosen = []
        browser.click = lambda node: browser.chosen.append(' '.join(node.itertext()).strip())
        def locate(node, selector, *args):
            try:
                return node.find_element(By.XPATH, selector)
            except NoSuchElementException:
                return False
        def missing_class(*args):
            raise NoSuchElementException()
        actions = SimpleNamespace(move_to_element=lambda node: SimpleNamespace(
            click=lambda: SimpleNamespace(perform=node.click)))
        class NativeSelect:
            def __init__(self, element):
                self.options = element.find_elements(By.TAG_NAME, 'option')
            @property
            def first_selected_option(self):
                return next((node for node in self.options if node.get_attribute('selected') is not None), self.options[0])
            def select_by_index(self, index):
                for node in self.options:
                    node.node.attrib.pop('selected', None)
                self.options[index].node.set('selected', '')
        draft_answer = configuration.pop('_draft_answer', None)
        namespace = dict(By=By, try_xp=locate, driver=browser, re=re,
                         overwrite_previous_answers=configuration.pop('overwrite_previous_answers', False), find_by_class=missing_class,
                         actions=actions, choose_index=choose_index,
                         dropdown_placeholder=dropdown_placeholder, print_lg=lambda *args: None,
                         Select=NativeSelect, NoSuchElementException=NoSuchElementException,
                         **configuration)
        extract_functions(namespace, 'answer_questions', 'answer_common_questions')
        questions = namespace['answer_questions'](browser.find_element(By.CSS_SELECTOR, 'dialog'), set(), 'Bay Area', draft_answer=draft_answer)
        return browser, questions

    def test_native_sponsorship_radios_use_configured_answer(self):
        browser, questions = self.answer_native_form('''<dialog open><fieldset>
            <legend>Will you require visa sponsorship?</legend>
            <input type="radio" id="yes" value="yes"><label for="yes">Yes</label>
            <input type="radio" id="no" value="no"><label for="no">No</label>
            </fieldset></dialog>''', require_visa='No')
        self.assertEqual(browser.chosen, ['No'])
        self.assertEqual(len(questions), 1)

    def test_sdui_radio_question_precedes_fieldset_and_option_aria_repeats_question(self):
        browser, questions = self.answer_native_form('''<dialog open>
            <p>Will you require visa sponsorship?</p><fieldset role="radiogroup">
            <div role="radio" aria-label="Will you require visa sponsorship?">
            <input type="radio" id="yes"><label for="yes"></label><p>Yes</p></div>
            <div role="radio" aria-label="Will you require visa sponsorship?">
            <input type="radio" id="no"><label for="no"> </label><p>No</p></div>
            </fieldset></dialog>''', require_visa='No')
        self.assertEqual(browser.chosen, ['No'])
        self.assertEqual(len(questions), 1)
        question, answer, kind, previous = next(iter(questions))
        self.assertEqual(question, 'Will you require visa sponsorship? [ Yes, No ]')
        self.assertEqual((answer, kind, previous), ('No', 'radio', None))

    def test_sdui_unknown_preceding_radio_question_uses_first_visible_yes_option(self):
        browser, questions = self.answer_native_form('''<dialog open>
            <p>Which interview format do you prefer?</p><fieldset role="radiogroup">
            <div role="radio" aria-label="Which interview format do you prefer?">
            <input type="radio" id="yes"><label for="yes"></label><p>Yes</p></div>
            <div role="radio" aria-label="Which interview format do you prefer?">
            <input type="radio" id="no"><label for="no"></label><p>No</p></div>
            </fieldset></dialog>''')
        self.assertEqual(browser.chosen, ['Yes'])
        self.assertEqual(len(questions), 1)
        self.assertEqual(next(iter(questions))[:3],
                         ('Which interview format do you prefer? [ Yes, No ]', 'Yes', 'radio'))

    def test_unknown_native_radios_use_first_option_and_resume_groups_are_excluded(self):
        browser, questions = self.answer_native_form('''<dialog open>
            <fieldset><legend>Which interview format do you prefer?</legend>
            <input type="radio" id="yes"><label for="yes">Yes</label></fieldset>
            <fieldset><legend>Resume</legend><input type="radio" id="resume">
            <label for="resume">resume.pdf</label></fieldset></dialog>''')
        self.assertEqual(browser.chosen, ['Yes'])
        self.assertEqual(len(questions), 1)

    def test_native_email_address_input_uses_email_instead_of_city(self):
        browser, questions = self.answer_native_form('''<dialog open><div>
            <label for="email">Email address*</label><input id="email" type="email" value="">
            </div></dialog>''', email='candidate@example.invalid')
        self.assertEqual(browser.find_element(By.CSS_SELECTOR, '#email').get_attribute('value'), 'candidate@example.invalid')
        self.assertEqual(len(questions), 1)

    def test_unconfigured_dropdown_uses_first_enabled_non_placeholder_option(self):
        browser, questions = self.answer_native_form('''<dialog open><div>
            <label for="format">Interview format</label><select id="format">
            <option selected disabled value="">Select an option</option>
            <option disabled value="offline">Unavailable</option>
            <option value="video">Video</option><option value="phone">Phone</option>
            </select></div></dialog>''')
        self.assertEqual(browser.find_element(By.CSS_SELECTOR, 'option[selected]').get_attribute('value'), 'video')
        self.assertEqual(next(iter(questions))[1], 'Video')

    def test_unmatched_configured_radio_answer_uses_first_enabled_option(self):
        browser, questions = self.answer_native_form('''<dialog open><fieldset>
            <legend>Will you require visa sponsorship?</legend>
            <input type="radio" disabled id="disabled"><label for="disabled">Unavailable</label>
            <input type="radio" id="yes"><label for="yes">Yes</label>
            <input type="radio" id="no"><label for="no">No</label>
            </fieldset></dialog>''', require_visa='No matching answer')
        self.assertEqual(browser.chosen, ['Yes'])
        self.assertEqual(next(iter(questions))[1], 'Yes')

    def test_native_gender_radios_honor_personal_answer(self):
        browser, questions = self.answer_native_form('''<dialog open><fieldset><legend>Gender</legend>
            <input type="radio" id="female"><label for="female">Female / Woman</label>
            <input type="radio" id="male"><label for="male">Male / Man</label>
            </fieldset></dialog>''', gender='Male')
        self.assertEqual(browser.chosen, ['Male / Man'])

    def test_native_radio_title_can_be_referenced_outside_group(self):
        browser, questions = self.answer_native_form('''<dialog open><p id="q">Will you need visa sponsorship?</p>
            <div role="radiogroup" aria-labelledby="q">
            <input type="radio" id="yes"><label for="yes">Yes</label>
            <input type="radio" id="no"><label for="no">No</label>
            </div></dialog>''', require_visa='No')
        self.assertEqual(browser.chosen, ['No'])

    def test_native_read_only_work_history_and_education_pages_are_distinct_progress(self):
        from test_linkedin_modern_search import DOMBrowser
        from lxml import html
        def page(content, action='Next'):
            return ('<dialog open><header><h2>Apply to Example</h2></header>'
                    '<div data-testid="dialog-content">' + content + '</div>'
                    '<footer><button>' + action + '</button></footer></dialog>')
        pages = [page('<p>Work experience</p><p>Current employer</p>'),
                 page('<p>Education</p><p>Source school and degree</p>'),
                 page('<p>Additional questions</p>', 'Review'),
                 page('<p>Review your application</p>', 'Submit application')]
        browser = DOMBrowser(pages[0])
        browser.page = 0
        def click(node):
            browser.clicks.append(node.text_content())
            browser.page += 1
            replacement = DOMBrowser(pages[browser.page])
            browser.root = replacement.root
        browser.click = click
        advance_to_review(browser, lambda modal: None, timeout=.01)
        self.assertEqual(browser.clicks, ['Next', 'Next', 'Review'])

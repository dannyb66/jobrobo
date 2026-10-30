"""Exercise real navigation against rerendered classic/semantic form DOMs."""
import unittest
import re
from unittest.mock import Mock
from bs4 import BeautifulSoup
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from modules.linkedin_easy_apply import (
    EasyApplyError, MissingApplicationAnswer, advance_to_review, current_submit_button,
    submission_receipts, wait_for_application_modal, wait_for_submission_confirmation, _signature,
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
        # These DOM adapters do multiple parsed queries per poll; 10ms is below
        # normal scheduling jitter when the full suite runs alongside Chrome.
        return advance_to_review(browser, fill or (lambda modal: None), timeout=.2, **kwargs)

    def safety_reminder(self, buttons=None):
        return ('<dialog open data-testid="dialog"><h2>Job search safety reminder</h2>'
            '<h3>Research the company</h3><p>Before you apply, review the employer’s official website.</p>'
            '<h3>Report suspicious jobs</h3><p>Report requests for sensitive information.</p>'
            +(buttons if buttons is not None else '<button>Review job post</button><button>Continue applying</button>')
            +'</dialog>')

    def test_safety_reminder_continues_then_next_review_without_submitting(self):
        browser=Browser([self.safety_reminder(),form(),form('Questions','Review'),form('Review','Submit application')])
        self.navigate(browser)
        self.assertEqual(browser.clicks,['Continue applying','Next','Review'])

    def test_safety_reminder_uses_exact_action_not_rightmost_button(self):
        browser=Browser([self.safety_reminder('<button>Continue applying</button><button>Review job post</button>'),
                         form(action='Submit application')])
        self.navigate(browser)
        self.assertEqual(browser.clicks,['Continue applying'])

    def test_live_safety_reminder_anchor_without_button_role_continues(self):
        reminder=self.safety_reminder('<button>Review job post</button><a href="/jobs/view/123/">Continue applying</a>')
        browser=Browser([reminder,form(action='Submit application')])
        self.navigate(browser)
        self.assertEqual(browser.clicks,['Continue applying'])

    def test_disabled_or_duplicate_continuation_link_is_not_clicked(self):
        for controls in ['<a href="#" aria-disabled="true">Continue applying</a>',
                         '<button>Continue applying</button><a href="#">Continue applying</a>']:
            browser=Browser([self.safety_reminder(controls)])
            with self.assertRaises(EasyApplyError):self.navigate(browser)
            self.assertEqual(browser.clicks,[])

    def test_safety_reminder_and_fit_warning_can_appear_in_sequence(self):
        fit='<dialog open><h2>This job may not be the best fit</h2><button>Continue applying</button></dialog>'
        browser=Browser([self.safety_reminder(),fit,form(action='Submit application')])
        self.navigate(browser)
        self.assertEqual(browser.clicks,['Continue applying','Continue applying'])

    def test_safety_reminder_does_not_repeat_a_slow_continuation_click(self):
        browser=Browser([self.safety_reminder()],on_click=lambda _:None)
        with self.assertRaisesRegex(EasyApplyError,'Continue applying did not open'):
            self.navigate(browser)
        self.assertEqual(browser.clicks,['Continue applying'])

    def test_safety_reminder_disabled_or_ambiguous_continuation_is_not_clicked(self):
        for buttons in ['<button disabled>Continue applying</button>',
                        '<button>Continue applying</button><button>Continue applying</button>']:
            browser=Browser([self.safety_reminder(buttons)])
            with self.assertRaises(EasyApplyError):self.navigate(browser)
            self.assertEqual(browser.clicks,[])

    def test_daily_limit_takes_precedence_over_safety_reminder(self):
        from modules.linkedin_easy_apply import EasyApplyLimitReached
        browser=Browser([self.safety_reminder().replace('</dialog>',
            '<p>You reached today’s Easy Apply limit</p></dialog>')])
        with self.assertRaises(EasyApplyLimitReached):self.navigate(browser)
        self.assertEqual(browser.clicks,[])

    def test_daily_limit_dom_probe_avoids_serializing_large_dialog_text(self):
        from modules.linkedin_easy_apply import EasyApplyLimitReached, check_easy_apply_limit
        browser=Browser([self.safety_reminder()])
        browser.execute_script=Mock(return_value=True)
        with self.assertRaises(EasyApplyLimitReached):check_easy_apply_limit(browser)
        browser.execute_script.assert_called_once()
        self.assertIn('textContent', browser.execute_script.call_args.args[0])

    def test_daily_limit_dom_probe_fast_path_returns_without_text_fallback(self):
        from modules.linkedin_easy_apply import check_easy_apply_limit
        browser=Browser([self.safety_reminder()])
        browser.execute_script=Mock(return_value=False)
        browser.find_elements=Mock(side_effect=AssertionError('expensive text fallback should not run'))
        check_easy_apply_limit(browser)
        browser.execute_script.assert_called_once()
        browser.find_elements.assert_not_called()

    def test_fit_warning_dom_probe_fast_path_skips_large_dialog_button_scan(self):
        from modules.linkedin_easy_apply import _fit_warning
        browser=Browser([self.safety_reminder()])
        browser.execute_script=Mock(return_value=False)
        browser.find_elements=Mock(side_effect=AssertionError('large dialog scan should not run'))
        self.assertFalse(_fit_warning(browser))
        browser.execute_script.assert_called_once()
        browser.find_elements.assert_not_called()

    def test_page_signature_uses_one_bounded_dom_snapshot(self):
        modal=Mock()
        modal.parent=Mock()
        modal.parent.execute_script=Mock(return_value=(['Work history'], [['from-month', None, None]], ['Software Engineer']))
        modal.find_elements=Mock(side_effect=AssertionError('per-element text reads should not run'))
        self.assertEqual(_signature(modal, 'next'),
                         ('next', ('Work history',), (('from-month', None, None),), ('Software Engineer',)))
        modal.parent.execute_script.assert_called_once()
        modal.find_elements.assert_not_called()

    def test_generated_field_ids_and_resume_history_are_not_page_progress(self):
        from test_linkedin_modern_search import DOMBrowser
        def page(suffix, filename):
            return DOMBrowser('<dialog open><h2>Apply to Example</h2><div data-testid="dialog-content">'
                '<p>2/4 pages</p><p>Resume*</p><div><input type="radio" id="_r_' + suffix + '_" '
                'name="radio-group-_r_' + suffix + '_" aria-label="' + filename + '"><label></label>'
                '<p>' + filename + '</p><p>10/29/2026</p></div>'
                '<div role="status"><p>Resume uploaded successfully</p></div></div><button>Next</button></dialog>')
        first, second = page('one', 'old.pdf'), page('two', 'new.pdf')
        self.assertEqual(_signature(first.find_element(By.CSS_SELECTOR, 'dialog'), 'next'),
                         _signature(second.find_element(By.CSS_SELECTOR, 'dialog'), 'next'))

    def test_clipped_footer_action_uses_dom_caption_before_scrolling(self):
        from modules.linkedin_easy_apply import _kind
        button = Mock()
        button.text = ''
        button.get_attribute.side_effect = lambda key: {'textContent': 'Next'}.get(key)
        self.assertEqual(_kind(button), 'next')

    def test_navigation_probe_does_not_read_every_resume_history_button(self):
        from modules.linkedin_easy_apply import _navigation_buttons
        root, driver, next_button = Mock(), Mock(), Mock()
        root.find_elements.side_effect = AssertionError('do not enumerate history over WebDriver')
        driver.execute_script.return_value = [next_button]
        self.assertEqual(_navigation_buttons(driver, root), [next_button])
        driver.execute_script.assert_called_once()
        root.find_elements.assert_not_called()

    def test_page_counter_distinguishes_same_action_without_field_ids(self):
        from test_linkedin_modern_search import DOMBrowser
        markup = '<dialog open><h2>Apply to Example</h2><p>1/4 pages</p><button>Next</button></dialog>'
        first, second = DOMBrowser(markup), DOMBrowser(markup.replace('1/4', '2/4'))
        self.assertNotEqual(_signature(first.find_element(By.CSS_SELECTOR, 'dialog'), 'next'),
                            _signature(second.find_element(By.CSS_SELECTOR, 'dialog'), 'next'))

    def test_safety_reminder_cleanup_detection_never_continues(self):
        browser=Browser([self.safety_reminder()])
        with self.assertRaises(EasyApplyError):
            wait_for_application_modal(browser,timeout=.01,continue_fit_warning=False)
        self.assertEqual(browser.clicks,[])

    def test_pre_application_continuations_are_bounded(self):
        browser=Browser([self.safety_reminder() for _ in range(4)]+[form(action='Submit application')])
        with self.assertRaisesRegex(EasyApplyError,'too many pre-application'):
            self.navigate(browser)
        self.assertEqual(browser.clicks,['Continue applying']*3)

    def test_unknown_dialog_does_not_guess_yes_or_rightmost_action(self):
        browser=Browser(['<dialog open><h2>Confirm agreement</h2><button>Cancel</button><button>Yes</button></dialog>'])
        with self.assertRaises(EasyApplyError):self.navigate(browser)
        self.assertEqual(browser.clicks,[])

    def test_safety_reminder_words_inside_form_do_not_trigger_continuation(self):
        browser=Browser([form(action='Submit application',extra='<p>Job search safety reminder</p><button>Continue applying</button>')])
        self.navigate(browser)
        self.assertEqual(browser.clicks,[])

    def test_safety_reminder_conflicting_submit_label_is_not_clicked(self):
        browser=Browser([self.safety_reminder('<button aria-label="Submit application">Continue applying</button>')])
        with self.assertRaises(EasyApplyError):self.navigate(browser)
        self.assertEqual(browser.clicks,[])

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
        advance_to_review(browser, fill, timeout=1)
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

    def test_review_to_next_during_fill_reacquires_refills_and_never_submits(self):
        browser = Browser([form('Location', 'Review'), form('Location', 'Next'), form('Review', 'Submit application')])
        browser.current_url = 'https://www.linkedin.com/jobs/view/4480536892/'
        filled = []
        messages = []
        def fill(modal):
            filled.append(browser.page)
            if browser.page == 0:
                browser.page = 1
                browser.render()
        self.navigate(browser, fill, log=messages.append)
        self.assertEqual(filled, [0, 1, 2])
        self.assertEqual(browser.clicks, ['Next'])
        self.assertTrue(any('review -> next' in message for message in messages))

    def test_repeated_action_changes_are_bounded_and_keep_structural_evidence(self):
        browser = Browser([form('Location', 'Review')])
        browser.current_url = 'https://www.linkedin.com/jobs/view/123/'
        def fill(modal):
            action = 'Next' if 'Review' in browser.pages[0] else 'Review'
            browser.pages[0] = form('Location', action, extra='<input value="PRIVATE ANSWER">')
            browser.render()
        with self.assertRaisesRegex(EasyApplyError, 'recovery limit') as raised:
            self.navigate(browser, fill)
        self.assertEqual(len(raised.exception.navigation_evidence), 4)
        self.assertNotIn('PRIVATE ANSWER', str(raised.exception.navigation_evidence))
        self.assertEqual(browser.clicks, [])

    def test_job_change_during_fill_stops_without_clicking_navigation(self):
        browser = Browser([form('Location', 'Review')])
        browser.current_url = 'https://www.linkedin.com/jobs/view/123/'
        def fill(modal):
            browser.current_url = 'https://www.linkedin.com/jobs/view/999/'
        with self.assertRaisesRegex(EasyApplyError, 'selected job changed'):
            self.navigate(browser, fill)
        self.assertEqual(browser.clicks, [])

    def test_employer_change_during_fill_cannot_be_recovered_as_same_application(self):
        browser = Browser([form('Location', 'Review')])
        def fill(modal):
            browser.pages[0] = form('Location', 'Next').replace('Apply to Example', 'Apply to Another company')
            browser.render()
        with self.assertRaisesRegex(EasyApplyError, 'application employer changed'):
            self.navigate(browser, fill)
        self.assertEqual(browser.clicks, [])

    def test_state_must_stabilize_before_using_a_transient_review_control(self):
        from unittest.mock import patch
        from modules.linkedin_easy_apply import _settled_state, _state
        transient = Browser([form('Location', 'Review')])
        settled = Browser([form('Location', 'Next')])
        states = [_state(transient), _state(settled), _state(settled)]
        with patch('modules.linkedin_easy_apply._state', side_effect=states):
            state = _settled_state(settled, .1, None, 'apply to example')
        self.assertEqual(state[1], 'next')

    def test_navigation_evidence_failure_does_not_replace_application_processing(self):
        from modules.linkedin_easy_apply import _navigation_snapshot
        modal = Mock()
        modal.parent.execute_script.side_effect = StaleElementReferenceException()
        result = _navigation_snapshot(modal, 'next')
        self.assertEqual(result['capture_error'], 'StaleElementReferenceException')
        self.assertEqual(result['questions'], [])

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
        field.find_elements.return_value = []
        field.send_keys.side_effect = lambda value: None if value == '\ue004' else values.update(value=value)
        label = SimpleNamespace(text='Summary')
        question = Mock(); modal = Mock()
        modal.find_elements.side_effect = lambda by, selector: [question] if selector == './/div[@data-test-form-element]' else []
        def locate(target, selector, *args):
            if selector == './/textarea':
                return field
            if selector == './/label[@for]':
                return label
            return False
        namespace = dict(By=By, try_xp=locate, driver=Mock(), overwrite_previous_answers=False,
                         linkedin_summary='Configured summary')
        extract_functions(namespace, 'answer_questions', 'answer_common_questions', '_bounded_application_answer', '_resume_work_history_dates', '_fill_resume_work_history_dates')
        result = namespace['answer_questions'](modal, set(), 'Bay Area')
        self.assertEqual(field.send_keys.call_args_list[0].args, ('Configured summary',))
        self.assertEqual(field.send_keys.call_args_list[1].args, ('\ue004',))
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
        extract_functions(namespace, 'answer_questions', 'answer_common_questions', '_bounded_application_answer', '_resume_work_history_dates', '_fill_resume_work_history_dates')
        questions = namespace['answer_questions'](modal, set(), 'Bay Area')
        self.assertEqual(modal.find_element(By.CSS_SELECTOR, '#phone').get_attribute('value'), '5550100')
        self.assertEqual(len(questions), 1)
        self.assertEqual(next(iter(questions))[0], 'phone*')

    def answer_native_form(self, markup, **configuration):
        from test_linkedin_modern_search import DOMBrowser
        from selenium.common.exceptions import NoSuchElementException
        browser = DOMBrowser(markup)
        browser.chosen = []
        def click(node):
            browser.chosen.append(' '.join(node.itertext()).strip())
            target = node
            if node.tag == 'label':
                target = browser.root.xpath('//*[@id=$ident]', ident=node.get('for'))[0]
            elif node.get('role') == 'radio':
                target = node.xpath('.//input[@type="radio"]')[0]
            if target.get('type') == 'radio':
                groups = target.xpath('./ancestor::*[self::fieldset or @role="radiogroup"][1]')
                scope = groups[0] if groups else browser.root
                for option in scope.xpath('.//input[@type="radio"]'):
                    option.attrib.pop('checked', None)
                for role in scope.xpath('.//*[@role="radio"]'):
                    role.set('aria-checked', 'false')
                target.set('checked', '')
                for role in target.xpath('./ancestor::*[@role="radio"][1]'):
                    role.set('aria-checked', 'true')
        browser.click = click
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
            def select_by_visible_text(self, text):
                option = next(node for node in self.options if node.text.strip() == text)
                self.select_by_index(self.options.index(option))
        draft_answer = configuration.pop('_draft_answer', None)
        work_location = configuration.pop('_work_location', 'Bay Area')
        namespace = dict(By=By, try_xp=locate, driver=browser, re=re,
                         overwrite_previous_answers=configuration.pop('overwrite_previous_answers', False), find_by_class=missing_class,
                         actions=actions, choose_index=choose_index,
                         dropdown_placeholder=dropdown_placeholder, print_lg=lambda *args: None,
                         Select=NativeSelect, NoSuchElementException=NoSuchElementException,
                         **configuration)
        extract_functions(namespace, 'answer_questions', 'answer_common_questions', '_bounded_application_answer', '_resume_work_history_dates', '_fill_resume_work_history_dates')
        questions = namespace['answer_questions'](browser.find_element(By.CSS_SELECTOR, 'dialog'), set(), work_location, draft_answer=draft_answer)
        return browser, questions

    def test_custom_work_history_end_date_uses_product_role_resume_range(self):
        from test_linkedin_modern_search import DOMBrowser
        from selenium.common.exceptions import NoSuchElementException
        markup = '''<dialog open>
          <section><input value="Product Owner"><textarea>Product planning and customer workflows</textarea>
            <div><p>To</p>
              <div data-test-form-element><button role="combobox" aria-label="To Month">Month</button></div>
              <div data-test-form-element><button role="combobox" aria-label="To Year">Year</button></div>
            </div>
          </section><div role="option">January</div><div role="option">2022</div>
        </dialog>'''
        browser = DOMBrowser(markup)
        modal = browser.find_element(By.CSS_SELECTOR, 'dialog')
        def locate(node, selector, *args):
            try:
                return node.find_element(By.XPATH, selector)
            except NoSuchElementException:
                return False
        class NativeSelect:
            def __init__(self, element): self.options = []
        namespace = dict(By=By, try_xp=locate, driver=browser, re=re,
                         overwrite_previous_answers=False,
                         dropdown_placeholder=dropdown_placeholder, Select=NativeSelect,
                         print_lg=lambda *args: None, default_resume_docx_path='all resumes/default/resume.docx')
        extract_functions(namespace, 'answer_questions', 'answer_common_questions', '_bounded_application_answer', '_resume_work_history_dates', '_fill_resume_work_history_dates')
        result = namespace['answer_questions'](modal, set(), 'Bay Area')
        self.assertEqual([browser.clicks[0][1], browser.clicks[2][1]], ['To Month', 'To Year'])
        self.assertEqual([browser.clicks[1][0], browser.clicks[3][0]], ['option', 'option'])
        self.assertEqual({item[1] for item in result}, {'January', '2022'})

    def test_custom_work_history_fills_both_start_and_end_from_best_resume_match(self):
        markup = '''<dialog open><section>
          <input value="Software Engineer"><textarea>Product Owner, product strategy and product workflows</textarea>
          <div><p>From</p>
            <div data-test-form-element><button aria-label="From Month">Month</button></div>
            <div data-test-form-element><button aria-label="From Year">Year</button></div>
          </div>
          <div><p>To</p>
            <div data-test-form-element><button>Month</button></div>
            <div data-test-form-element><button>Year</button></div>
          </div>
        </section><div role="option">January</div><div role="option">2016</div>
        <div role="option">January</div><div role="option">2018</div></dialog>'''
        browser, questions = self.answer_native_form(markup, default_resume_docx_path='all resumes/default/resume.docx')
        self.assertEqual({item[1] for item in questions if item[2] == 'resume_work_history_date'},
                         {'January', '2016', '2018'})
        self.assertEqual(len(browser.chosen), 8)  # both Month fields and both Year fields were selected

    def test_native_work_history_selects_infer_month_year_from_placeholder_options(self):
        markup = '''<dialog open><section>
          <input value="Software Engineer"><textarea>Product Owner, product strategy and product workflows</textarea>
          <div><p>From</p><select><option selected>Month</option><option>January</option></select>
          <select><option selected>Year</option><option>2016</option></select></div>
          <div><p>To</p><select><option selected>Month</option><option>January</option></select>
          <select><option selected>Year</option><option>2018</option></select></div>
        </section></dialog>'''
        browser, questions = self.answer_native_form(markup, default_resume_docx_path='all resumes/default/resume.docx')
        selected = browser.find_elements(By.XPATH, "//select/option[@selected]")
        self.assertEqual([option.text for option in selected], ['January', '2016', 'January', '2018'])

    def test_work_history_select_order_handles_blank_custom_placeholders(self):
        markup = '''<dialog open><section><p>Dates of employment</p>
          <input value="Software Engineer"><textarea>Software engineering</textarea>
          <div><p>From</p>
            <select><option selected value="">Choose one</option><option>January</option></select>
            <select><option selected value="">Choose one</option><option>2016</option></select>
          </div>
          <div><p>To</p>
            <select><option selected value="">Choose one</option><option>January</option></select>
            <select><option selected value="">Choose one</option><option>2018</option></select>
          </div></section></dialog>'''
        browser, questions = self.answer_native_form(markup, default_resume_docx_path='all resumes/default/resume.docx')
        selected = browser.find_elements(By.XPATH, "//select/option[@selected]")
        self.assertEqual([option.text for option in selected], ['January', '2016', 'January', '2018'])

    def test_sponsorship_radio_overwrites_saved_no_with_configured_yes(self):
        browser, questions = self.answer_native_form('''<dialog open><p>Would you require any sponsorship now or in future to continue your employment?*</p>
          <fieldset role="radiogroup"><div role="radio" aria-checked="false"><input id="y" type="radio"><label for="y"></label><p>Yes</p></div>
          <div role="radio" aria-checked="true"><input id="n" type="radio" checked><label for="n"></label><p>No</p></div></fieldset></dialog>''', require_visa='Yes')
        self.assertEqual(browser.chosen, ['Yes'])
        self.assertEqual([n.get_attribute('id') for n in browser.find_elements(By.CSS_SELECTOR, 'input[checked]')], ['y'])

    def test_sponsorship_select_overwrites_saved_no_with_configured_yes(self):
        browser, _ = self.answer_native_form('''<dialog open><label for="sponsor">Do you need visa sponsorship?</label>
          <select id="sponsor"><option>Yes</option><option selected>No</option></select></dialog>''', require_visa='Yes')
        self.assertEqual([n.text for n in browser.find_elements(By.CSS_SELECTOR,'option[selected]')], ['Yes'])

    def test_current_sponsorship_no_overwrites_saved_yes(self):
        browser, _ = self.answer_native_form('''<dialog open><fieldset><legend>Will you require visa sponsorship?</legend>
          <input type="radio" id="yes" checked><label for="yes">Yes</label>
          <input type="radio" id="no"><label for="no">No</label></fieldset></dialog>''', require_visa='No')
        self.assertEqual(browser.chosen, ['No'])
        self.assertEqual([n.get_attribute('id') for n in browser.find_elements(By.CSS_SELECTOR,'input[checked]')], ['no'])

    def test_immediate_start_date_skips_ai_and_replaces_saved_answer(self):
        provider = Mock(side_effect=AssertionError('Availability must not be drafted'))
        browser, questions = self.answer_native_form('''<dialog open><label for="start">What is your potential start date?*</label>
          <input id="start" type="text" value="30 days" required maxlength="200"></dialog>''',
          available_start_date='Immediate', notice_period='0', ai_descriptive_answers_enabled=True, _draft_answer=provider)
        self.assertEqual(browser.find_element(By.CSS_SELECTOR,'input').get_attribute('value'), 'Immediate')
        provider.assert_not_called()
        self.assertEqual(next(iter(questions))[2], 'configured_availability')

    def test_immediate_availability_select_uses_immediately_option(self):
        browser, _ = self.answer_native_form('''<dialog open><label for="start">Availability</label><select id="start">
          <option selected>30 days</option><option>Immediately</option></select></dialog>''', available_start_date='Immediate')
        self.assertEqual([n.text for n in browser.find_elements(By.CSS_SELECTOR,'option[selected]')], ['Immediately'])

    def test_posting_location_replaces_saved_first_option_before_continuing(self):
        browser, _ = self.answer_native_form('''<dialog open><label for="office">Which location are you applying for?</label>
          <select id="office"><option>Select an option</option><option selected>Los Angeles, CA</option>
          <option>Oakland, CA</option><option>New York, NY</option><option>Toronto</option></select></dialog>''',
          search_location='San Francisco Bay Area', _work_location='Oakland, CA')
        self.assertEqual([n.text for n in browser.find_elements(By.CSS_SELECTOR,'option[selected]')], ['Oakland, CA'])

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

    def test_unmatched_sponsorship_answer_is_not_silently_defaulted(self):
        with self.assertRaisesRegex(MissingApplicationAnswer, 'Configured sponsorship answer is not offered'):
            self.answer_native_form('''<dialog open><fieldset>
            <legend>Will you require visa sponsorship?</legend>
            <input type="radio" disabled id="disabled"><label for="disabled">Unavailable</label>
            <input type="radio" id="yes"><label for="yes">Yes</label>
            <input type="radio" id="no"><label for="no">No</label>
            </fieldset></dialog>''', require_visa='No matching answer')

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
        advance_to_review(browser, lambda modal: None, timeout=.2)
        self.assertEqual(browser.clicks, ['Next', 'Next', 'Review'])

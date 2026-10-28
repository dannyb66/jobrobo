"""Real native reference fields use configured data and preserve manual answers."""
import unittest
from unittest.mock import Mock
import test_linkedin_easy_apply as apply_tests
from modules.linkedin_easy_apply import MissingApplicationAnswer, advance_to_review


class ReferencesTests(unittest.TestCase):
    def answer(self, markup, **config):
        return apply_tests.NavigationTests().answer_native_form(markup, use_AI=False,
            aiClient=None, randomly_answered_questions=set(), **config)

    def test_configured_headline_respects_counter(self):
        browser, _ = self.answer('<dialog open><div><label for="headline">Headline</label>'
            '<div><input id="headline" type="text"><span>0/127</span></div></div></dialog>',
            linkedin_headline='Engineer ' * 22)
        value = browser.find_element('css selector', 'input').get_attribute('value')
        self.assertTrue(value)
        self.assertLessEqual(len(value.encode('utf-16-le')) // 2, 127)

    def test_external_privacy_heading_requires_specific_application_approval(self):
        from test_search_runner import ReceiptRecoveryTests
        markup = ('<section><p>You declare that you have read and agree to the privacy notice of Example.*</p>'
                  '<div role="checkbox" aria-checked="false"><label for="consent"></label>'
                  '<input id="consent" type="checkbox"><p>I consent</p></div></section>')
        browser, ns = ReceiptRecoveryTests().checkbox_form(markup, application_privacy_consent_job_ids=['456'])
        with self.assertRaisesRegex(MissingApplicationAnswer, 'privacy notice'):
            ns['answer_questions'](browser.find_element('css selector', 'dialog'), set(), 'Bay Area', job_id='123')
        browser, ns = ReceiptRecoveryTests().checkbox_form(markup, application_privacy_consent_job_ids=['123'])
        ns['answer_questions'](browser.find_element('css selector', 'dialog'), set(), 'Bay Area', job_id='123')
        self.assertEqual(browser.find_element('css selector', '[role="checkbox"]').get_attribute('aria-checked'), 'true')

    def test_privacy_approval_does_not_approve_other_agreements(self):
        from test_search_runner import ReceiptRecoveryTests
        browser, ns = ReceiptRecoveryTests().checkbox_form('<section><p>Employment agreement*</p><div role="checkbox">'
                '<input id="consent" type="checkbox"><label for="consent">I consent</label></div></section>',
                application_privacy_consent_job_ids=['123'])
        with self.assertRaisesRegex(MissingApplicationAnswer, 'confirmation'):
            ns['answer_questions'](browser.find_element('css selector', 'dialog'), set(), 'Bay Area', job_id='123')

    def test_approved_default_checks_only_recognized_required_privacy_question(self):
        from test_search_runner import ReceiptRecoveryTests
        markup = ('<section><p>You declare that you have read and agree to the privacy notice of Example.*</p>'
                  '<div role="checkbox" aria-checked="false"><input type="checkbox"><p>I consent</p></div></section>')
        browser, ns = ReceiptRecoveryTests().checkbox_form(markup, application_privacy_consent_default=True)
        ns['answer_questions'](browser.find_element('css selector', 'dialog'), set(), 'Bay Area', job_id='789')
        self.assertEqual(browser.find_element('css selector', '[role="checkbox"]').get_attribute('aria-checked'), 'true')
        browser, ns = ReceiptRecoveryTests().checkbox_form('<div><input id="sign" type="checkbox">'
            '<label for="sign">Yes, I agree to sign electronically.*</label></div>', application_privacy_consent_default=True)
        with self.assertRaisesRegex(MissingApplicationAnswer, 'confirmation'):
            ns['answer_questions'](browser.find_element('css selector', 'dialog'), set(), 'Bay Area', job_id='789')

    def test_iherb_privacy_notice_variant_uses_approved_default(self):
        from test_search_runner import ReceiptRecoveryTests
        markup = ('<section><p>We respect the privacy of candidates for employment. The Privacy Notice sets forth '
                  'how we use information when you apply for a position through this career site.*</p>'
                  '<div role="checkbox"><input type="checkbox">'
                  '<p>Yes, I have read and consent to the terms and conditions</p></div></section>')
        browser, ns = ReceiptRecoveryTests().checkbox_form(markup, application_privacy_consent_default=True)
        ns['answer_questions'](browser.find_element('css selector', 'dialog'), set(), 'Bay Area', job_id='123')
        self.assertEqual(browser.find_element('css selector', '[role="checkbox"]').get_attribute('aria-checked'), 'true')

    def test_recruitment_data_privacy_notice_uses_approved_default(self):
        from test_search_runner import ReceiptRecoveryTests
        markup = ('<section><p>Example collects personal information as part of its job application and '
                  'recruitment process. See our Careers Privacy Notice.*</p>'
                  '<div role="checkbox"><input type="checkbox"><p>I consent</p></div></section>')
        browser, ns = ReceiptRecoveryTests().checkbox_form(markup, application_privacy_consent_default=True)
        ns['answer_questions'](browser.find_element('css selector', 'dialog'), set(), 'Bay Area', job_id='123')
        self.assertEqual(browser.find_element('css selector', '[role="checkbox"]').get_attribute('aria-checked'), 'true')

    def test_privacy_link_does_not_approve_employment_contract(self):
        from modules.linkedin_form_fields import is_privacy_notice_choice
        self.assertFalse(is_privacy_notice_choice('i consent',
            'Employment contract. We collect personal information in the recruitment process. Privacy notice.'))

    def test_configured_demographic_opt_out_beats_first_option(self):
        markup = ('<dialog open><select aria-label="Please indicate your gender.">'
                  '<option value="">Select an option</option><option selected>Male</option><option>Not declared</option></select>'
                  '<select aria-label="Please indicate your race/ethnicity."><option>Asian</option>'
                  '<option>I do not wish to answer.</option></select></dialog>')
        browser, _ = self.answer(markup, gender='Decline', ethnicity='Decline', unanswered_choice_policy='first_option')
        selects = browser.find_elements('css selector', 'select')
        self.assertEqual([n.find_element('css selector', 'option[selected]').text for n in selects],
                         ['Not declared', 'I do not wish to answer.'])

    def test_country_select_uses_configured_country(self):
        browser, _ = self.answer('<dialog open><select aria-label="Country"><option>Select an option</option>'
            '<option>Afghanistan</option><option>United States</option></select></dialog>', country='United States')
        self.assertEqual(browser.find_element('css selector', 'option[selected]').text, 'United States')

    def test_country_checkbox_group_uses_config(self):
        from test_search_runner import ReceiptRecoveryTests
        markup = ('<section><p>Please select the country of the position you are applying to.*</p><fieldset>'
                  '<div role="checkbox" aria-checked="false"><input id="us" type="checkbox"><p>United States</p></div>'
                  '<div role="checkbox" aria-checked="false"><input id="ca" type="checkbox"><p>Canada</p></div>'
                  '</fieldset></section>')
        browser, ns = ReceiptRecoveryTests().checkbox_form(markup, country='United States')
        ns['answer_questions'](browser.find_element('css selector', 'dialog'), set(), 'Bay Area')
        self.assertEqual([n.get_attribute('aria-checked') for n in browser.find_elements('css selector', '[role="checkbox"]')], ['true', 'false'])

    def test_empty_configured_relatives_defaults_no_without_inventing_names(self):
        markup = ('<dialog open><select aria-label="Do you have any relatives currently working at iHerb?*">'
                  '<option>Choose an option</option><option selected>Yes</option><option>No</option></select></dialog>')
        browser, _ = self.answer(markup, application_relative_employee_names='')
        self.assertEqual(browser.find_element('css selector', 'option[selected]').text, 'No')
        browser, _ = self.answer(markup, application_relative_employee_names='User-provided relative')
        self.assertEqual(browser.find_element('css selector', 'option[selected]').text, 'Yes')

    def test_native_aria_textarea_uses_reusable_config(self):
        browser, questions = self.answer('''<dialog open><div><label for="elsewhere">Other</label>
            <input id="elsewhere" type="hidden"></div><div><p>3 References (1 Direct Manager)*</p>
            <div><textarea aria-label="3 References (1 Direct Manager)" required></textarea></div>
            </div></dialog>''', references='Manager: User-supplied reference\nPeer: User-supplied reference')
        self.assertIn('Manager: User-supplied reference',
                      browser.find_element('css selector', 'textarea').get_attribute('value'))
        self.assertEqual(len(questions), 1)

    def test_missing_required_references_are_not_invented(self):
        with self.assertRaisesRegex(MissingApplicationAnswer, 'References'):
            self.answer('''<dialog open><div><textarea aria-label="3 References" required>
                </textarea></div></dialog>''', references='')

    def test_sample_references_are_allowed_only_with_submission_disabled(self):
        markup = '<dialog open><textarea aria-label="References" required></textarea></dialog>'
        with self.assertRaises(MissingApplicationAnswer):
            self.answer(markup, references='', test_references='TEST ONLY: Sample Manager', prepare_only_run=False)
        browser, _ = self.answer(markup, references='', test_references='TEST ONLY: Sample Manager', prepare_only_run=True)
        self.assertEqual(browser.find_element('css selector', 'textarea').get_attribute('value'),
                         'TEST ONLY: Sample Manager')

    def test_cover_and_descriptive_textareas_use_context_drafter_independent_of_resume_ai(self):
        draft = Mock(side_effect=['Custom cover letter', 'Grounded experience example'])
        browser, _ = self.answer('''<dialog open><textarea aria-label="Cover letter" required></textarea>
            <textarea aria-label="Describe your relevant experience" maxlength="200" required></textarea>
            </dialog>''', ai_cover_letter_enabled=True, ai_descriptive_answers_enabled=True,
            use_AI_for_resume=False, _draft_answer=draft)
        self.assertEqual([node.get_attribute('value') for node in browser.find_elements('css selector', 'textarea')],
                         ['Custom cover letter', 'Grounded experience example'])
        self.assertEqual(draft.call_args_list[0].args[:2], ('Cover letter', 'cover_letter'))
        self.assertEqual(draft.call_args_list[1].args, ('Describe your relevant experience', 'descriptive', '200'))

    def test_existing_descriptive_answer_is_preserved_without_ai_call(self):
        draft = Mock()
        self.answer('''<dialog open><textarea aria-label="Describe your experience"
            value="Existing reviewed answer" required></textarea></dialog>''',
            ai_descriptive_answers_enabled=True, _draft_answer=draft)
        draft.assert_not_called()

    def test_reference_architecture_question_is_descriptive_not_personal_references(self):
        draft = Mock(return_value='A grounded architecture example')
        browser, _ = self.answer('''<dialog open><textarea
            aria-label="Describe a reference architecture you implemented" required></textarea></dialog>''',
            ai_descriptive_answers_enabled=True, references='Personal referee details', _draft_answer=draft)
        self.assertEqual(browser.find_element('css selector', 'textarea').get_attribute('value'),
                         'A grounded architecture example')
        draft.assert_called_once()

    def test_middle_name_is_not_sent_to_descriptive_drafter(self):
        draft = Mock(side_effect=AssertionError('An empty optional middle name is personal data'))
        browser, _ = self.answer('''<dialog open><input type="text" aria-label="Middle name"></dialog>''',
            middle_name='', ai_descriptive_answers_enabled=True, _draft_answer=draft)
        self.assertEqual(browser.find_element('css selector', 'input').get_attribute('value'), '')
        draft.assert_not_called()

    def test_required_middle_name_without_config_is_reported_as_personal_data_blocker(self):
        with self.assertRaisesRegex(MissingApplicationAnswer, 'middle name'):
            self.answer('''<dialog open><input type="text" aria-label="Middle name" required></dialog>''',
                middle_name='', ai_descriptive_answers_enabled=True,
                _draft_answer=Mock(side_effect=AssertionError('Must not draft identity data')))

    def test_unbounded_single_line_ai_answer_is_capped(self):
        draft = Mock(return_value='x' * 1800)
        browser, _ = self.answer('''<dialog open><input type="text" aria-label="Vector Databases"></dialog>''',
            ai_descriptive_answers_enabled=True, _draft_answer=draft)
        value = browser.find_element('css selector', 'input').get_attribute('value')
        self.assertEqual(len(value), 500)
        draft.assert_called_once_with('Vector Databases', 'descriptive', '500')

    def test_unbounded_years_textarea_gets_short_answer_limit(self):
        draft = Mock(return_value='8 years')
        browser, _ = self.answer('''<dialog open><textarea aria-label="How many years of MLOps experience do you have?"></textarea></dialog>''',
            ai_descriptive_answers_enabled=True, _draft_answer=draft)
        self.assertEqual(browser.find_element('css selector', 'textarea').get_attribute('value'), '8 years')
        draft.assert_called_once_with('How many years of MLOps experience do you have?', 'descriptive', '150')

    def test_optional_other_relationship_is_not_drafted_when_other_is_unselected(self):
        draft = Mock(side_effect=AssertionError('An inapplicable relationship must not be invented'))
        self.answer('''<dialog open><div role="checkbox" aria-checked="false">Other (ie. Contractor)</div>
            <textarea aria-label='If you selected "other", please share your relationship here'></textarea>
            </dialog>''', ai_descriptive_answers_enabled=True, _draft_answer=draft)
        draft.assert_not_called()

    def test_selected_other_relationship_still_requires_an_answer(self):
        draft = Mock(return_value='Explicitly supplied relationship')
        self.answer('''<dialog open><div role="checkbox" aria-checked="true">Other (ie. Contractor)</div>
            <textarea aria-label='If you selected "other", please share your relationship here'></textarea>
            </dialog>''', ai_descriptive_answers_enabled=True, _draft_answer=draft)
        draft.assert_called_once()

    def test_current_company_uses_configured_employer_instead_of_ai_prose(self):
        draft = Mock(side_effect=AssertionError('Known employer belongs to personal configuration'))
        browser, _ = self.answer('''<dialog open><input type="text" aria-label="Current company"
            value="A previously generated long description"></dialog>''',
            recent_employer='Configured Company', ai_descriptive_answers_enabled=True, _draft_answer=draft)
        self.assertEqual(browser.find_element('css selector', 'input').get_attribute('value'), 'Configured Company')
        draft.assert_not_called()

    def test_sibling_aria_controls_each_receive_their_own_answer(self):
        browser, questions = self.answer('''<dialog open><div>
            <input type="text" aria-label="First name" value="">
            <input type="text" aria-label="Last name" value="">
            <textarea aria-label="References" required></textarea>
            </div></dialog>''', first_name='Test', last_name='Candidate', references='Supplied manager')
        self.assertEqual([node.get_attribute('value') for node in
                          browser.find_elements('css selector', 'input, textarea')],
                         ['Test', 'Candidate', 'Supplied manager'])
        self.assertEqual(len(questions), 3)

    def test_existing_text_is_preserved_even_without_configured_replacement(self):
        for overwrite in (False, True):
            with self.subTest(overwrite=overwrite):
                # The fixture stores DOM value as an attribute, as other field fixtures do.
                browser, _ = self.answer('''<dialog open><div><textarea
                    aria-label="References" required value="Manually supplied reference"></textarea>
                    </div></dialog>''', references='', overwrite_previous_answers=overwrite)
                self.assertEqual(browser.find_element('css selector', 'textarea').get_attribute('value'),
                                 'Manually supplied reference')

    def test_missing_answer_never_clicks_review_or_submit(self):
        browser = apply_tests.Browser([apply_tests.form(action='Review')])
        def fill(_):
            raise MissingApplicationAnswer('Required references missing')
        with self.assertRaises(MissingApplicationAnswer):
            advance_to_review(browser, fill, timeout=.01)
        self.assertEqual(browser.clicks, [])

    def test_normal_run_can_request_manual_correction(self):
        browser = apply_tests.Browser([apply_tests.form(action='Submit application')])
        fill = Mock(side_effect=[MissingApplicationAnswer('References missing'), None])
        correction = Mock(return_value=True)
        advance_to_review(browser, fill, on_blocked=correction, timeout=.01)
        correction.assert_called_once_with('References missing')
        self.assertEqual(browser.clicks, [])


if __name__ == '__main__':
    unittest.main()

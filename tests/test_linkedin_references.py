"""Real native reference fields use configured data and preserve manual answers."""
import unittest
from unittest.mock import Mock
import test_linkedin_easy_apply as apply_tests
from modules.linkedin_easy_apply import MissingApplicationAnswer, advance_to_review


class ReferencesTests(unittest.TestCase):
    def answer(self, markup, **config):
        return apply_tests.NavigationTests().answer_native_form(markup, use_AI=False,
            aiClient=None, randomly_answered_questions=set(), **config)

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

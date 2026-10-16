import unittest
from modules.application_choices import choose_index, dropdown_placeholder


class ChoicePolicyTests(unittest.TestCase):
    def test_configured_answer_wins_over_first_option(self):
        self.assertEqual(choose_index([{'text': 'Yes'}, {'text': 'No'}], 'No'), (1, False))

    def test_configured_words_do_not_match_inside_different_words(self):
        self.assertEqual(choose_index([{'text': 'Female / Woman'}, {'text': 'Male / Man'}], 'Male'), (1, False))
        self.assertEqual(choose_index([{'text': 'Not sure'}, {'text': 'No sponsorship required'}], 'No'), (1, False))

    def test_missing_or_unmatched_answer_uses_first_enabled_real_option(self):
        choices = [{'text': 'Select an option', 'placeholder': True},
                   {'text': 'Disabled choice', 'enabled': False},
                   {'text': 'First real choice'}, {'text': 'Later choice'}]
        for requested in (None, '', 'No matching configured answer'):
            with self.subTest(requested=requested):
                self.assertEqual(choose_index(choices, requested), (2, True))

    def test_decline_matches_equivalent_option_without_defaulting(self):
        self.assertEqual(choose_index([{'text': 'Yes'}, {'text': 'Prefer not to answer'}], 'Decline'), (1, False))

    def test_empty_and_disabled_only_options_block(self):
        with self.assertRaises(ValueError):
            choose_index([{'text': ''}, {'text': 'Disabled', 'enabled': False}])

    def test_placeholder_labels_are_excluded_but_real_labels_are_preserved(self):
        for text in ('', 'Select an option', 'Please choose one', 'Select...', 'Choose…'):
            self.assertTrue(dropdown_placeholder(text), text)
        for text in ('No preference', 'None', 'Yes', 'Professional'):
            self.assertFalse(dropdown_placeholder(text), text)

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from modules.education_inference import infer_education_choices
from modules.linkedin_easy_apply import EasyApplyError


class EducationInferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source.docx'
        self.source.write_bytes(b'Original education source')
        self.cache = Path(self.temp.name) / 'cache'
        self.payload = dict(school='Earlier college', existing_dates=['Month', '2010', 'Month', '2012'],
                            source_education=[dict(school='University', start_year='2012', degree='Bachelor')],
                            options=dict(degree=['High School', 'Bachelor'], field_of_study=['Mathematics', 'Computer Science']))
        self.response = dict(degree='High School', field_of_study='Mathematics', inferred=True,
                             rationale='Inferred from the pre-university timeline, not explicitly stated in the CV.')

    def call(self, provider, **extra):
        return infer_education_choices(self.payload, source_resume=self.source, profile='Configured education profile',
                                       cache_dir=self.cache, provider=provider, model='configured-model', **extra)

    def test_valid_choices_cached_with_provenance_without_raw_profile(self):
        provider = Mock(return_value=self.response)
        first = self.call(provider)
        second = self.call(provider)
        self.assertEqual(first, second)
        provider.assert_called_once()
        artifact = Path(first['artifact_path']).read_text()
        self.assertIn('pre-university timeline', artifact)
        self.assertNotIn('Configured education profile', artifact)

    def test_changed_cv_invalidates_cache(self):
        provider = Mock(return_value=self.response)
        self.call(provider)
        self.source.write_bytes(b'Updated education source')
        self.call(provider)
        self.assertEqual(provider.call_count, 2)

    def test_unsupported_choice_never_reaches_form(self):
        for response in [dict(self.response, degree='PhD'), dict(self.response, field_of_study=None)]:
            with self.subTest(response=response), self.assertRaises(EasyApplyError):
                self.call(Mock(return_value=response))
        self.assertFalse(self.cache.exists())

    def test_request_failure_is_retryable_without_raw_error(self):
        with self.assertRaisesRegex(EasyApplyError, 'retained for retry') as caught:
            self.call(Mock(side_effect=RuntimeError('private provider body')))
        self.assertNotIn('private provider body', str(caught.exception))

    def test_single_cv_supported_option_does_not_fail_on_model_label_variation(self):
        self.payload['options']['field_of_study'] = ['Computer and Information Science']
        selected = self.call(Mock(return_value=dict(self.response, field_of_study='Computer Science')))
        self.assertEqual(selected['field_of_study'], 'Computer and Information Science')
        self.assertIn('single CV-supported', selected['selection_adjustments'][0])

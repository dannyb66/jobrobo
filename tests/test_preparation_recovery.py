"""Local regressions for abandoned resume attempts and adaptive retries."""
import json
import os
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from modules.generic_prepare import generated_resume, PreparationResolver
from modules.direct_careers_apply import local_candidate
from modules import resume_all_bullets as bullets
from modules.resume_progress import ResumeConsoleProgress
import test_generic_prepare as generic_tests
from test_resume_all_bullets import inv, config, response


class PreparationRecoveryTests(TestCase):
    def sources(self, root):
        source = root/'source.docx'; source.write_bytes(b'source')
        pdf = source.with_suffix('.pdf'); pdf.write_bytes(b'pdf')
        return source, pdf

    def test_abandoned_generation_is_archived_and_retried_without_overwrite(self):
        with TemporaryDirectory() as tmp, patch('modules.generic_prepare.verify_resume', return_value={'passed': True}):
            root = Path(tmp); source, pdf = self.sources(root)
            out = root/'out'; out.mkdir()
            checkpoint = {'status': 'generating', 'input_hash': 'old', 'started_at': 'old timestamp'}
            (out/'generation.json').write_text(json.dumps(checkpoint))
            old = out/'old-artifact.pdf'; old.write_bytes(b'partial evidence')
            generate = Mock(side_effect=generic_tests.GenericPreparationTests.accepted_generator(source))
            result = generated_resume({'title': 'Engineer', 'description': 'JD'}, out, source, pdf, {}, {}, generate=generate)
            self.assertFalse(result['visual_review_required'])
            self.assertEqual(old.read_bytes(), b'partial evidence')
            archives = list((out/'attempt-history').glob('*.json'))
            self.assertEqual(len(archives), 1)
            self.assertEqual(json.loads(archives[0].read_text()), checkpoint)
            self.assertIn('attempt-', generate.call_args.kwargs['output_root'])

    def test_live_generation_owner_is_not_retried(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp); source, pdf = self.sources(root); out = root/'out'; out.mkdir()
            (out/'generation.json').write_text(json.dumps({'status': 'generating', 'owner_pid': os.getpid()}))
            generate = Mock()
            with self.assertRaisesRegex(ValueError, 'active'):
                generated_resume({'title': 'Engineer', 'description': 'JD'}, out, source, pdf, {}, {}, generate=generate)
            generate.assert_not_called()

    def test_interruption_is_recorded_and_lock_released(self):
        with TemporaryDirectory() as tmp, patch('modules.generic_prepare.verify_resume', return_value={'passed': True}):
            root = Path(tmp); source, pdf = self.sources(root); out = root/'out'
            args = ({'title': 'Engineer', 'description': 'JD'}, out, source, pdf, {}, {})
            with self.assertRaises(KeyboardInterrupt):
                generated_resume(*args, generate=Mock(side_effect=KeyboardInterrupt))
            self.assertEqual(json.loads((out/'generation.json').read_text())['status'], 'interrupted')
            generated_resume(*args, generate=generic_tests.GenericPreparationTests.accepted_generator(source))
            self.assertEqual(json.loads((out/'generation.json').read_text())['status'], 'accepted')

    def test_configured_source_resolves_referral_without_ai(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('personals', 'secrets'): (root/(name+'.py')).write_text('')
            (root/'questions.py').write_text('application_source = "Web search"\n')
            candidate = local_candidate(root)
            answer = PreparationResolver(candidate, {}).resolve({'label': 'How did you hear about Hive?',
                'name': 'source', 'kind': 'multiselect', 'required': True, 'options': ['LinkedIn', 'Other']}, 'lever')
            self.assertEqual(answer.value, ['Other'])

    def test_first_choice_policy_skips_placeholder_and_keeps_profile_priority(self):
        drafts = Mock()
        resolver = PreparationResolver({'country': 'Canada'}, {'unanswered_choice_policy': 'first_option'}, drafts)
        q = {'label': 'Which team?', 'name': 'team', 'kind': 'select', 'required': True,
             'options': ['Select', 'Please choose an option...', 'Engineering', 'Product']}
        answer = resolver.resolve(q, 'generic')
        self.assertEqual(answer.value, 'Engineering')
        self.assertEqual(answer.source, 'user_policy:first_option')
        q.update(label='Country', name='country', options=['United States', 'Canada'])
        self.assertEqual(resolver.resolve(q, 'generic').value, 'Canada')
        drafts.answer.assert_not_called()

    def test_choice_policy_only_acts_on_unambiguous_selectable_controls(self):
        resolver = PreparationResolver({}, {'unanswered_choice_policy': 'first_option'})
        q = {'label': 'Unknown question', 'name': 'q', 'kind': 'radio', 'options': ['First', 'Second']}
        self.assertEqual(resolver.resolve(q, 'generic').value, 'First')
        self.assertEqual(resolver.resolve({**q, 'kind': 'multiselect'}, 'generic').value, ['First'])
        self.assertTrue(resolver.resolve({**q, 'kind': 'checkbox', 'options': []}, 'generic').value)
        self.assertFalse(resolver.resolve({**q, 'ambiguous': True}, 'generic').resolved)
        self.assertFalse(resolver.resolve({**q, 'kind': 'text', 'options': []}, 'generic').resolved)
        self.assertFalse(resolver.resolve({**q, 'kind': 'unsupported'}, 'generic').resolved)

    def test_invalid_explicit_answer_is_not_replaced_by_first_choice(self):
        resolver = PreparationResolver({}, {'unanswered_choice_policy': 'first_option',
            'answers': [{'question': 'Which team?', 'type': 'select', 'answer': 'Missing'}]})
        self.assertFalse(resolver.resolve({'label': 'Which team?', 'name': 'team', 'kind': 'select',
            'options': ['Engineering', 'Product']}, 'generic').resolved)

    def test_first_choice_does_not_replace_supplied_sponsorship_fact(self):
        resolver = PreparationResolver({'require_visa': 'No'}, {'unanswered_choice_policy': 'first_option'}, job_country='US')
        question = {'label': 'Will you now or in the future require company sponsorship to retain or extend your work authorization in the country where the job is located?',
            'name': 'sponsor', 'kind': 'select', 'options': ['Yes, I require sponsorship now.']}
        self.assertFalse(resolver.resolve(question, 'greenhouse').resolved)

    def test_dei_opt_out_overrides_profile_and_first_choice(self):
        resolver = PreparationResolver({'gender': 'Male', 'ethnicity': 'Asian'},
            {'unanswered_choice_policy': 'first_option', 'dei_choice_policy': 'prefer_not_to_answer'})
        for label in ('Gender', 'Which ethnicity do you identify with?', 'Which communities do you belong to?',
                      'Veteran status', 'What is your current age?'):
            q = {'label': label, 'name': 'dei', 'kind': 'radio', 'options': ['Male', 'Asian', 'None of the above', 'Prefer not to answer']}
            answer = resolver.resolve(q, 'generic')
            self.assertEqual(answer.value, 'Prefer not to answer')
            self.assertEqual(answer.source, 'user_policy:dei_opt_out')
        q.update(kind='multiselect', options=['Asian', 'None of the above'])
        self.assertEqual(resolver.resolve(q, 'generic').value, ['None of the above'])
        q['options'] = ['Asian', 'White']
        self.assertFalse(resolver.resolve(q, 'generic').resolved)
        q.update(label='Which engineering team?', kind='radio', options=['Backend', 'Frontend'])
        self.assertEqual(resolver.resolve(q, 'generic').value, 'Backend')
        q.update(label='DEI self-identification', kind='checkbox', options=[], required=False)
        self.assertFalse(resolver.resolve(q, 'generic').value)
        q['required'] = True
        self.assertFalse(resolver.resolve(q, 'generic').resolved)


class AdaptiveRewriteTests(TestCase):
    def test_timeout_retry_splits_only_failed_batch_with_same_context(self):
        source = inv(4, 1); calls = []; events = []
        def provider(stage, payload, timeout):
            calls.append(deepcopy(payload))
            if len(calls) == 1:
                class APITimeoutError(Exception): pass
                raise APITimeoutError()
            return response(payload)
        scheduler = bullets.Scheduler(config(rewrite_bullets_per_request=4), 1, progress=events.append)
        with patch('modules.resume_all_bullets.random.uniform', return_value=0), patch.object(scheduler, 'active', return_value=True):
            # Keep the test deterministic without sleeping through provider backoff.
            original = scheduler.call
            def call(*args):
                scheduler.cooldown = 0
                return original(*args)
            with patch.object(scheduler, 'call', side_effect=call):
                result = bullets.rewrite_inventory(source, 'Python complete JD', 'role', 'grounded', scheduler, provider)
        self.assertEqual([len(p['requested_bullet_ids']) for p in calls], [4, 2, 2])
        self.assertEqual(calls[1]['source_experience'], calls[0]['source_experience'])
        self.assertTrue(all(r['status'] == 'candidate' for r in result))
        self.assertEqual(scheduler.events[0]['error_kind'], 'timeout')
        self.assertTrue(any(e['event'] == 'timeout_split' for e in events))
        self.assertLessEqual(len(calls), scheduler.limit)

    def test_measured_shortening_guidance_applies_to_all_policies(self):
        source = inv(1, 1); group = source['groups'][0]
        for policy in ('grounded', 'review_draft', 'synthetic_jd_test'):
            payload = bullets.compact_payload(source, 'Python', 'role', policy, group, group['bullets'],
                {'0': 'glyph width estimate 540pt exceeds single-line budget 500pt; target at most 75 characters; shorten phrasing without losing facts'})
            row = payload['requested_bullets'][0]
            self.assertLessEqual(row['soft_character_estimate'], 75)
            self.assertLess(row['target_max_characters'], 75)
            self.assertIn('target_characters', payload['acceptance_criteria']['fit'])
            self.assertIn('candidate_word_budgets', payload['acceptance_criteria']['fit'])

    def test_progress_tracks_active_request_age(self):
        clock = Mock(return_value=10); messages = []
        console = ResumeConsoleProgress(messages.append, 'fixture', clock=clock)
        console({'event': 'request_started', 'attempt': 1, 'stage': 'bullets', 'bullet_count': 4})
        clock.return_value = 44
        self.assertIn('1 active', console.active_summary())
        self.assertIn('34s', console.active_summary())
        console({'event': 'request_finished', 'attempt': 1, 'response_received': False, 'error_kind': 'timeout', 'elapsed_seconds': 34})
        self.assertIn('0 active', console.active_summary())
        self.assertIn('timeout', messages[-1])

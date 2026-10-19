"""Offline per-JD rewrite integration: real uploader/runner, mocked external effects."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from modules.resume_upload import ResumeUploadError, upload_verified_resume
import test_search_runner as runner_harness


class LinkedInRewriteIntegrationTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'original.docx'
        self.source.write_bytes(b'original resume fixture')
        self.source.with_suffix('.pdf').write_bytes(b'original PDF fixture')
        self.file_input = Mock()
        self.modal = Mock()
        self.modal.find_element.return_value = self.file_input
        self.config = {'rewrite_all_bullets': True, 'source_checks_enabled': False,
                       'optimization_mode': 'full', 'nested': {'marker': 'original'}}
        self.source_verify = Mock(side_effect=AssertionError('Strict source fallback forbidden'))

    def artifact(self, job_id='123'):
        directory = self.root / str(job_id)
        directory.mkdir(exist_ok=True)
        pdf = directory / 'optimized.pdf'
        pdf.write_bytes(f'generated PDF for {job_id}'.encode())
        (directory / 'match-report.json').write_text(json.dumps({
            'source_content_checks_enabled': False, 'run_id': f'rewrite-{job_id}',
            'effective_config': {'content_policy': 'jd_rewrite'}}))
        return pdf

    def upload(self, optimize, **options):
        return upload_verified_resume(
            self.modal, str(self.source), 'Exact job description', '123',
            optimize=optimize, verify_source=self.source_verify, **options)

    def test_one_deep_snapshot_binds_optimizer_and_verifier_despite_mutation(self):
        pdf = self.artifact()
        original = deepcopy(self.config)
        received = []

        def optimize(**kwargs):
            snapshot = kwargs['runtime_config_override']
            received.append(deepcopy(snapshot))
            # Neither caller mutation nor optimizer mutation may alter verification.
            self.config['source_checks_enabled'] = True
            self.config['nested']['marker'] = 'runtime changed'
            snapshot['source_checks_enabled'] = True
            snapshot['nested']['marker'] = 'optimizer changed'
            return str(pdf)

        with patch('modules.config_loader.peek_runtime_config', return_value=self.config) as peek, \
             patch('modules.resume_all_bullets.verify_strict_attachment', return_value=True) as verify:
            attached = Mock()
            self.assertEqual(self.upload(optimize, on_attached=attached), (True, 'optimized.pdf'))
        peek.assert_called_once_with()
        self.assertEqual(received, [original])
        self.assertEqual(verify.call_args.kwargs['expected_config'], original)
        self.assertIs(verify.call_args.kwargs['expected_source_checks_enabled'], False)
        self.assertEqual(verify.call_args.kwargs['expected_jd'], 'Exact job description')
        self.assertEqual(verify.call_args.kwargs['expected_job_id'], '123')
        self.assertEqual(verify.call_args.kwargs['expected_source_docx'], str(self.source))
        self.file_input.send_keys.assert_called_once_with(str(pdf.resolve()))
        attached.assert_called_once_with(str(pdf.resolve()))
        self.source_verify.assert_not_called()

    def test_explicit_snapshot_and_overrides_precede_runtime_without_mutating_input(self):
        pdf = self.artifact()
        supplied = deepcopy(self.config)
        optimize = Mock(return_value=str(pdf))
        with patch('modules.config_loader.peek_runtime_config') as peek, \
             patch('modules.resume_all_bullets.verify_strict_attachment', return_value=True) as verify:
            result = self.upload(optimize, runtime_config_override=supplied,
                                 source_checks_enabled=True, rewrite_experience_concurrency=3)
        self.assertTrue(result[0])
        peek.assert_not_called()
        expected = {**self.config, 'source_checks_enabled': True, 'rewrite_experience_concurrency': 3}
        self.assertEqual(optimize.call_args.kwargs['runtime_config_override'], expected)
        self.assertEqual(verify.call_args.kwargs['expected_config'], expected)
        self.assertIs(verify.call_args.kwargs['expected_source_checks_enabled'], True)
        self.assertEqual(supplied, self.config)

    def test_invalid_flags_or_disabled_checks_without_full_rewrite_never_start(self):
        for overrides in ({'source_checks_enabled': 'false'}, {'source_checks_enabled': 0},
                          {'source_checks_enabled': None},
                          {'rewrite_all_bullets': 'true'}, {'rewrite_all_bullets': False}):
            with self.subTest(overrides=overrides):
                optimize = Mock()
                config = {**self.config, **overrides}
                result = self.upload(optimize, runtime_config_override=config)
                self.assertFalse(result[0])
                optimize.assert_not_called()
        self.file_input.send_keys.assert_not_called()
        self.source_verify.assert_not_called()

    def test_strict_missing_invalid_or_failed_generation_never_attaches_source(self):
        invalid = self.root / 'invalid.txt'
        invalid.write_text('not a PDF')
        for output in (None, str(self.root / 'missing.pdf'), str(invalid), RuntimeError('generation failed')):
            with self.subTest(output=type(output).__name__):
                optimize = Mock(side_effect=output) if isinstance(output, Exception) else Mock(return_value=output)
                with patch('modules.resume_all_bullets.verify_strict_attachment') as verify:
                    self.assertEqual(self.upload(optimize, runtime_config_override=self.config),
                                     (False, 'Strict rewrite incomplete'))
                    verify.assert_not_called()
        self.file_input.send_keys.assert_not_called()
        self.source_verify.assert_not_called()

    def test_failed_binding_never_attaches_and_failed_send_never_falls_back(self):
        pdf = self.artifact()
        attached = Mock()
        for verification in (False, RuntimeError('invalid manifest')):
            with self.subTest(verification=type(verification).__name__):
                effect = {'side_effect': verification} if isinstance(verification, Exception) else {'return_value': verification}
                with patch('modules.resume_all_bullets.verify_strict_attachment', **effect):
                    self.assertFalse(self.upload(Mock(return_value=str(pdf)),
                                                 runtime_config_override=self.config, on_attached=attached)[0])
        self.file_input.send_keys.assert_not_called()
        self.file_input.send_keys.side_effect = RuntimeError('attachment failed')
        with patch('modules.resume_all_bullets.verify_strict_attachment', return_value=True):
            self.assertFalse(self.upload(Mock(return_value=str(pdf)),
                                         runtime_config_override=self.config, on_attached=attached)[0])
        self.file_input.send_keys.assert_called_once_with(str(pdf.resolve()))
        self.source_verify.assert_not_called()
        attached.assert_not_called()

    def preparation(self, optimize):
        def upload(target, source, jd, job_id, title, first, last, **options):
            return upload_verified_resume(target, source, jd, job_id, title, first, last,
                                          optimize=optimize, verify_source=self.source_verify, **options)

        def advance(browser, fill, **options):
            fill(self.modal)
            fill(self.modal)  # A later Next page must reuse this job's attachment.
            return self.modal

        namespace = {
            'driver': Mock(), 'use_AI_for_resume': True, 'useNewResume': True,
            'ai_cover_letter_enabled': False, 'ai_descriptive_answers_enabled': False,
            'default_resume_docx_path': str(self.source), 'default_resume_path': str(self.source.with_suffix('.pdf')),
            'first_name': 'Test', 'last_name': 'Candidate', 'ResumeUploadError': ResumeUploadError,
            'wait_for_application_modal': Mock(return_value=self.modal),
            'advance_to_review': advance, 'resume_upload_target': Mock(return_value=self.modal),
            'upload_optimized_resume': Mock(side_effect=upload), 'upload_resume': Mock(return_value=(True, 'original.pdf')),
            'answer_questions': Mock(return_value=set()), 'print_lg': Mock(),
        }
        runner_harness.extract_functions(namespace, 'prepare_easy_apply')
        return namespace

    def test_two_pages_reuse_upload_and_next_job_generates_fresh_exact_provenance_without_prose_ai(self):
        outputs = {job: self.artifact(job) for job in ('123', '456')}
        optimize = Mock(side_effect=lambda **kwargs: str(outputs[kwargs['job_id']]))
        ns = self.preparation(optimize)
        with patch('modules.config_loader.peek_runtime_config', return_value=self.config) as peek, \
             patch('modules.resume_all_bullets.verify_strict_attachment', return_value=True):
            for job, jd in (('123', 'First exact JD'), ('456', 'Second exact JD')):
                self.assertTrue(ns['prepare_easy_apply'](job, 'Staff Engineer', jd, 'Bay Area')[2])
                pdf = outputs[job]
                self.assertEqual(ns['resume_artifact_paths'][job], {
                    'pdf': str(pdf.resolve()), 'sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(),
                    'source_checks_enabled': False, 'rewrite_run_id': f'rewrite-{job}', 'content_policy': 'jd_rewrite'})
        self.assertEqual(optimize.call_count, 2)
        self.assertEqual([call.kwargs['job_description'] for call in optimize.call_args_list],
                         ['First exact JD', 'Second exact JD'])
        self.assertEqual(peek.call_count, 2)
        self.assertEqual(ns['resume_upload_target'].call_count, 2)
        self.assertEqual(ns['answer_questions'].call_count, 4)
        self.assertEqual([call.args[0] for call in self.file_input.send_keys.call_args_list],
                         [str(outputs[job].resolve()) for job in ('123', '456')])

    def test_failed_retry_clears_old_same_job_provenance(self):
        ns = self.preparation(Mock(return_value=None))
        ns['resume_artifact_paths'] = {'123': {'pdf': 'stale.pdf'}}
        ns['draft_artifact_paths'] = {'123': {'cover_letter': 'stale.txt'}}
        with patch('modules.config_loader.peek_runtime_config', return_value=self.config):
            with self.assertRaises(ResumeUploadError):
                ns['prepare_easy_apply']('123', 'Engineer', 'Changed JD', 'Bay Area')
        self.assertNotIn('123', ns['resume_artifact_paths'])
        self.assertNotIn('123', ns['draft_artifact_paths'])
        ns['answer_questions'].assert_not_called()

    def test_ai_disabled_attaches_configured_resume_without_optimizer(self):
        optimize = Mock()
        ns = self.preparation(optimize)
        ns['use_AI_for_resume'] = False
        self.assertTrue(ns['prepare_easy_apply']('123', 'Engineer', 'Exact JD', 'Bay Area')[2])
        optimize.assert_not_called()
        ns['upload_optimized_resume'].assert_not_called()
        ns['upload_resume'].assert_called_once_with(self.modal, str(self.source.with_suffix('.pdf')))

    def runner(self, optimize):
        harness = runner_harness.SearchRunnerTests(methodName='test_missing_verified_resume_stops_before_submit_without_consuming_search_quota')
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        harness.modal = self.modal
        harness.namespace.update(self.preparation(optimize))
        harness.namespace.update(driver=harness.browser, advance_to_review=harness.advance_to_review,
                                 print_lg=lambda *args: None)
        # Bind the extracted function to the same globals as the actual runner.
        runner_harness.extract_functions(harness.namespace, 'prepare_easy_apply')
        return harness

    def test_strict_failure_stops_runner_before_pause_submit_and_receipt(self):
        harness = self.runner(Mock(return_value=None))
        search = runner_harness.spec('strict-generation-failed')
        manifest = harness.manifest([search], {search.query_id: [['123']]})
        with patch('modules.config_loader.peek_runtime_config', return_value=self.config):
            harness.execute(manifest)
        self.assertNotIn('confirm', harness.events)
        self.assertNotIn('Submit application', harness.events)
        harness.namespace['wait_for_submission_confirmation'].assert_not_called()
        self.assertEqual(manifest.query(search.query_id)['jobs']['123']['status'], 'failed')
        self.assertEqual(manifest.query(search.query_id)['applied_count'], 0)

    def test_verified_rewrite_keeps_pause_receipt_and_one_job_quota(self):
        pdf = self.artifact()
        harness = self.runner(Mock(return_value=str(pdf)))
        harness.namespace['wait_for_submission_confirmation'].side_effect = (
            lambda *args, **kwargs: harness.events.append('receipt'))
        search = runner_harness.spec('verified-jd-rewrite', quota=1)
        manifest = harness.manifest([search], {search.query_id: [['123', '456']]})
        with patch('modules.config_loader.peek_runtime_config', return_value=self.config), \
             patch('modules.resume_all_bullets.verify_strict_attachment', return_value=True):
            harness.execute(manifest)
        self.assertEqual(harness.events.count('confirm'), 1)
        self.assertEqual(harness.events.count('Submit application'), 1)
        self.assertLess(harness.events.index('confirm'), harness.events.index('Submit application'))
        self.assertLess(harness.events.index('Submit application'), harness.events.index('receipt'))
        harness.namespace['wait_for_submission_confirmation'].assert_called_once_with(
            harness.browser, '123', baseline=set())
        self.assertEqual(harness.namespace['resume_artifact_paths']['123']['pdf'], str(pdf.resolve()))
        self.assertEqual(harness.visited, ['123'])
        self.assertEqual(manifest.query(search.query_id)['applied_count'], 1)
        self.assertEqual(manifest.query(search.query_id)['jobs']['123']['status'], 'applied')

    def test_synthetic_policy_uses_same_pause_submit_receipt_and_quota_flow(self):
        self.config['content_policy'] = 'synthetic_jd_test'
        pdf = self.artifact()
        report_path = pdf.parent / 'match-report.json'
        report = json.loads(report_path.read_text())
        report['effective_config']['content_policy'] = 'synthetic_jd_test'
        report['synthetic_test'] = True
        report_path.write_text(json.dumps(report))
        harness = self.runner(Mock(return_value=str(pdf)))
        harness.namespace['wait_for_submission_confirmation'].side_effect = (
            lambda *args, **kwargs: harness.events.append('receipt'))
        search = runner_harness.spec('verified-synthetic-rewrite', quota=1)
        manifest = harness.manifest([search], {search.query_id: [['123', '456']]})
        with patch('modules.config_loader.peek_runtime_config', return_value=self.config), \
             patch('modules.resume_all_bullets.verify_strict_attachment', return_value=True) as verify:
            harness.execute(manifest)
        self.assertEqual(verify.call_args.kwargs['expected_config']['content_policy'], 'synthetic_jd_test')
        self.assertEqual(harness.events.count('confirm'), 1)
        self.assertEqual(harness.events.count('Submit application'), 1)
        self.assertLess(harness.events.index('confirm'), harness.events.index('Submit application'))
        self.assertLess(harness.events.index('Submit application'), harness.events.index('receipt'))
        self.assertEqual(manifest.query(search.query_id)['applied_count'], 1)
        self.assertEqual(harness.namespace['resume_artifact_paths']['123']['content_policy'], 'synthetic_jd_test')
        harness.namespace['wait_for_submission_confirmation'].assert_called_once_with(
            harness.browser, '123', baseline=set())
        self.assertEqual(harness.namespace['resume_artifact_paths']['123']['pdf'], str(pdf.resolve()))
        self.assertEqual(harness.visited, ['123'])
        self.assertEqual(manifest.query(search.query_id)['applied_count'], 1)
        self.assertEqual(manifest.query(search.query_id)['jobs']['123']['status'], 'applied')

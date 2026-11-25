"""Shared mixed-company queues and metadata-rich retries; no employer calls."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from unittest import TestCase
from unittest.mock import Mock, patch

import direct_apply
from modules.external_apply import ExternalApplicationResult
from modules.generic_inputs import load_jobs
from modules.submit_runner import run_submissions
from modules.submit_state import SubmitRun, build_run_summary, format_run_summary


class MultiCompanyRunTests(TestCase):
    def test_one_configured_cap_applies_across_companies_and_resume(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'config'
            config.mkdir()
            (config / 'search.py').write_text('max_applications_per_run = 2\n')
            source = root / 'jobs.json'
            source.write_text(json.dumps({'jobs': [
                {'url': f'https://example.test/{i}', 'company': 'Nexxa' if i % 2 else 'Stuut'}
                for i in range(4)]}))
            jobs = load_jobs([source], company=['Nexxa', 'Stuut'])
            visited = []

            def prepare(url, **kwargs):
                visited.append(url)
                metadata = kwargs['input_metadata']
                kwargs['ledger'].record_aliases(ExternalApplicationResult(
                    'applied', url, attempt_id=metadata['attempt_id']), [url], metadata['role_id'])
                return {'status': 'applied', 'output_dir': str(root / 'report'), 'resume': {}}

            kwargs = {'services': {'candidate': {}, 'question_config': {}, 'resume_provider': Mock()},
                      'preparer': prepare,
                      'driver_factory': lambda: Mock(browser_backend='local', capabilities={})}
            with redirect_stdout(StringIO()):
                result = run_submissions(jobs, config_dir=config, run_dir=root / 'run',
                    pause='never', workers=4, max_applications=10, **kwargs)
                resumed = run_submissions(resume_dir=root / 'run', **kwargs)
            self.assertEqual(result['counts'], {'applied': 2, 'pending': 2})
            self.assertEqual(resumed['counts'], result['counts'])
            self.assertEqual(len(visited), 2)
            self.assertEqual(result['options']['max_applications'], 2)
            ready = load_jobs([root / 'run/retry-ready.json'], company=['Nexxa', 'Stuut'])
            self.assertEqual([job['url'] for job in ready], ['https://example.test/2', 'https://example.test/3'])

    def test_four_jobs_from_two_companies_overlap_once_and_persist(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'config'
            config.mkdir()
            (config / 'search.py').write_text('max_applications_per_run = 50\n')
            source = root / 'jobs.json'
            source.write_text(json.dumps({'jobs': [
                {'id': str(i), 'url': f'https://example.test/jobs/{i}',
                 'company': 'Nexxa' if i % 2 else 'Stuut'} for i in range(4)]}))
            barrier = threading.Barrier(4)
            lock = threading.Lock()
            visited = []
            active = peak = 0

            def prepare(url, **kwargs):
                nonlocal active, peak
                with lock:
                    active += 1
                    peak = max(peak, active)
                    visited.append(url)
                try:
                    barrier.wait(timeout=10)
                    metadata = kwargs['input_metadata']
                    kwargs['ledger'].record_aliases(ExternalApplicationResult(
                        'applied', url, attempt_id=metadata['attempt_id']), [url], metadata['role_id'])
                    return {'status': 'applied', 'output_dir': str(root / 'report'), 'resume': {}}
                finally:
                    with lock:
                        active -= 1

            def execute(jobs, **kwargs):
                return run_submissions(jobs, **kwargs,
                    services={'candidate': {}, 'question_config': {}, 'resume_provider': Mock()},
                    preparer=prepare, driver_factory=lambda: Mock(browser_backend='local', capabilities={}))

            with patch('modules.submit_runner.run_submissions', side_effect=execute), redirect_stdout(StringIO()):
                code = direct_apply.main(['submit', '--urls-file', str(source),
                    '--company', 'Nexxa', 'Stuut', '--workers', '4', '--limit', '4',
                    '--pause-before-submit', 'never', '--config-dir', str(config),
                    '--run-dir', str(root / 'run')])
            self.assertEqual(code, 0)
            self.assertEqual(peak, 4)
            self.assertCountEqual(visited, [f'https://example.test/jobs/{i}' for i in range(4)])
            progress = json.loads((root / 'run/progress.json').read_text())
            summary = json.loads((root / 'run/summary.json').read_text())
            manifest = json.loads((root / 'run/input.json').read_text())
            for data in [progress, summary, manifest]:
                self.assertEqual(data['selected_companies'], ['Stuut', 'Nexxa'])
            self.assertTrue(all(job['attempts'] == 1 for job in progress['jobs']))
            self.assertEqual({c['company']: c['confirmed_submissions'] for c in summary['company_summaries']},
                             {'Stuut': 2, 'Nexxa': 2})
            with patch('direct_apply.browser_factory') as browser, redirect_stdout(StringIO()):
                resumed = run_submissions(resume_dir=root / 'run')
            browser.assert_not_called()
            self.assertEqual(resumed['selected_companies'], ['Stuut', 'Nexxa'])
            self.assertEqual(resumed['counts'], {'applied': 4})

    def test_retry_ready_excludes_possible_submissions_and_preserves_company(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'jobs.json'
            statuses = ['pending', 'failed_before_submit', 'submission_uncertain',
                        'applied', 'blocked', 'preparing', 'awaiting_email_verification', 'submitting']
            source.write_text(json.dumps({'jobs': [
                {'id': str(i), 'url': f'https://example.test/{i}', 'company': 'Nexxa',
                 'title': status, 'source_tasks': [44]} for i, status in enumerate(statuses)]}))
            jobs = load_jobs([source])
            run = SubmitRun(root / 'run', jobs=jobs)
            try:
                for job, status in zip(jobs, statuses):
                    run.update(job, status=status, retryable=status == 'failed_before_submit')
                progress = run.export()
            finally:
                run.close()
            ready = load_jobs([root / 'run/retry-ready.json'], company=['Nexxa'])
            self.assertEqual([job['id'] for job in ready], ['0', '1'])
            self.assertTrue(all(job['company'] == 'Nexxa' and job['source_tasks'] == [44] for job in ready))
            self.assertTrue(all(job['retry_origins'] for job in ready))
            self.assertTrue(all(not job['admission_blockers'] for job in ready))
            uncertain = load_jobs([root / 'run/retry-submission-uncertain.txt'])
            self.assertEqual([job['url'] for job in uncertain], ['https://example.test/2'])
            self.assertIn('# Status: submission_uncertain',
                          (root / 'run/retry-submission-uncertain.txt').read_text())
            summary = build_run_summary(progress)
            self.assertEqual(summary['retry_ready_count'], 2)
            self.assertEqual(summary['company_summaries'][0]['retry_ready_count'], 2)
            self.assertIn('Retry command:', format_run_summary(progress))
            # The existing safe TXT retains its original scope (no pending jobs).
            self.assertEqual((root / 'run/retry.txt').read_text(), 'https://example.test/1\n')

    def test_zero_ready_jobs_has_clear_footer_and_no_retry_command(self):
        with TemporaryDirectory() as tmp:
            jobs = load_jobs(url='https://example.test/uncertain')
            run = SubmitRun(Path(tmp) / 'run', jobs=jobs)
            try:
                run.update(jobs[0], status='submission_uncertain', retryable=False)
                progress = run.export()
            finally:
                run.close()
            self.assertEqual(json.loads((Path(tmp) / 'run/retry-ready.json').read_text())['jobs'], [])
            footer = format_run_summary(progress)
            self.assertIn('No safe automatic retries', footer)
            self.assertNotIn('Retry command:', footer)

    def test_company_summary_merges_normalized_names_and_retains_unknowns(self):
        summary = build_run_summary({'jobs': [
            {'company': ' Nexxa ', 'status': 'applied'},
            {'company': 'NEXXA', 'status': 'submission_uncertain'},
            {'status': 'pending'}]})
        self.assertEqual(summary['selected_companies'], ['Nexxa'])
        self.assertEqual(len(summary['company_summaries']), 2)
        self.assertEqual(summary['company_summaries'][0]['confirmed_rate_percent'], 50)
        self.assertEqual(summary['company_summaries'][1]['company'], '(unknown)')

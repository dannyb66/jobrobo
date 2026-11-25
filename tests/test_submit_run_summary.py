"""End-of-run status accounting and CLI footer; no browser or employer calls."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
import json

from modules.submit_state import build_run_summary, format_run_summary


class RunSummaryTests(TestCase):
    def progress(self):
        statuses = ['applied', 'submission_uncertain', 'blocked', 'awaiting_email_verification',
                    'awaiting_manual_submit', 'failed_before_submit', 'pending', 'discarded']
        return {'run_id': 'test-run', 'run_dir': '/tmp/test-run', 'total': len(statuses),
                'started_at': '2026-11-03T20:00:00+00:00', 'updated_at': '2026-11-03T20:01:05+00:00',
                'counts': {status: 1 for status in statuses},
                'jobs': [{'status': status, 'worker_id': f'worker-{i % 2 + 1:02}',
                          'retryable': status in {'blocked', 'failed_before_submit'}} for i, status in enumerate(statuses)],
                'options': {'workers': 2, 'browser_backend': 'local', 'pause': 'never',
                            'max_applications': 20, 'captcha_solver': True,
                            'kernel_settings': {'secret': 'must-not-appear'}}}

    def test_mixed_outcomes_and_metadata_do_not_inflate_success(self):
        progress = self.progress()
        summary = build_run_summary(progress)
        self.assertEqual(summary['confirmed_submissions'], 1)
        self.assertEqual(summary['confirmed_rate_percent'], 12.5)
        self.assertEqual(summary['unresolved_submission_count'], 1)
        self.assertEqual(summary['retryable_before_submit_count'], 2)
        self.assertEqual(summary['elapsed_seconds'], 65)
        self.assertEqual(sum(sum(counts.values()) for counts in summary['worker_status_counts'].values()), 8)
        footer = format_run_summary(progress)
        for status in progress['counts']:
            self.assertIn(f'{status}: 1 (12.5%)', footer)
        for expected in ['Confirmed submissions: 1 (12.5%)', 'Workers: 2', 'CAPTCHA solver: enabled',
                         '00:01:05', 'Application cap: 20', '/tmp/test-run/summary.json']:
            self.assertIn(expected, footer)
        self.assertNotIn('must-not-appear', footer)
        self.assertNotIn('must-not-appear', json.dumps(summary))
        self.assertLess(footer.index('Started:'), footer.index('Job status summary'))
        self.assertLess(footer.index('Retry files:'), footer.index('Job status summary'))
        self.assertTrue(footer.rstrip().endswith('submission_uncertain: 1 (12.5%)'))

    def test_empty_and_legacy_progress_have_readable_defaults(self):
        footer = format_run_summary({'jobs': [], 'started_at': None})
        self.assertIn('Jobs: 0', footer)
        self.assertIn('Elapsed since run creation: unknown', footer)
        summary = build_run_summary({'jobs': [{'status': 'submission_uncertain'}]})
        self.assertEqual(summary['status_counts'], {'submission_uncertain': 1})
        self.assertEqual(summary['confirmed_submissions'], 0)
        review = build_run_summary({'jobs': [{'status': 'awaiting_review'}]})
        self.assertEqual(review['manual_review_pending_count'], 1)
        self.assertEqual(review['outcome'], 'complete_with_unresolved_outcomes')

    def test_cli_footer_follows_full_json_and_preserves_exit_status(self):
        import direct_apply
        for status, code in [('applied', 0), ('submission_uncertain', 1)]:
            with self.subTest(status=status), TemporaryDirectory() as tmp:
                jobs = Path(tmp)/'jobs.json'
                jobs.write_text(json.dumps({'jobs': ['https://example.test/job/1']}))
                progress = {'jobs': [{'status': status}], 'run_id': 'footer-run'}
                output = StringIO()
                with patch('modules.submit_runner.run_submissions', return_value=progress), redirect_stdout(output):
                    self.assertEqual(direct_apply.main(['submit', '--urls-file', str(jobs)]), code)
                full_output = output.getvalue()
                json_part, footer = full_output.split('\nDirect apply run summary', 1)
                self.assertEqual(json.loads(json_part), progress)
                self.assertIn(f'{status}: 1 (100.0%)', footer)

    def test_terminal_resume_persists_summary_metadata_without_starting_browser(self):
        from modules.generic_inputs import load_jobs
        from modules.submit_runner import run_submissions
        from modules.submit_state import SubmitRun
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root/'config'
            config.mkdir()
            (config/'search.py').write_text('max_applications_per_run = 50\n')
            jobs = load_jobs(url='https://example.test/job/1')
            run = SubmitRun(root/'run', jobs=jobs, options={'config_dir': str(config),
                           'workers': 2, 'pause': 'never', 'browser_backend': 'local'})
            run.update(jobs[0], status='blocked', worker_id='worker-01', retryable=True)
            run.close()
            with patch('direct_apply.browser_factory') as factory, redirect_stdout(StringIO()):
                run_submissions(resume_dir=root/'run')
            factory.assert_not_called()
            summary = json.loads((root/'run/summary.json').read_text())
            self.assertEqual(summary['status_counts'], {'blocked': 1})
            self.assertEqual(summary['configured_workers'], 2)
            self.assertEqual(summary['worker_status_counts'], {'worker-01': {'blocked': 1}})
            self.assertEqual(summary['confirmed_submissions'], 0)

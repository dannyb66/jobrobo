"""Only provably pre-submit crash checkpoints may be requeued."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock

from modules.external_apply import ExternalApplicationLedger, ExternalApplicationResult
from modules.generic_inputs import load_jobs
from modules.submit_state import SubmitRun
from modules.submit_runner import recover_abandoned_preparations, run_submissions


class AbandonedPreparationTests(TestCase):
    def test_resume_dispatches_abandoned_jobs_but_never_possible_submissions(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            config = root/'config'
            config.mkdir()
            (config/'search.py').write_text('max_applications_per_run = 20\n')
            jobs = sum((load_jobs(url=f'https://example.test/integration/{i}') for i in range(4)), [])
            directory = root/'run'
            saved = SubmitRun(directory, jobs=jobs, options={
                'config_dir': str(config), 'workers': 2, 'pause': 'never', 'browser_backend': 'local'})
            for i in range(3):
                saved.update(jobs[i], status='preparing', attempt_id=f'old-{i}', attempts=1)
            saved.update(jobs[3], status='applied')
            saved.close()
            ledger = ExternalApplicationLedger(directory/'applications-ledger.json')
            ledger.record_aliases(ExternalApplicationResult('submitting', jobs[2]['url'], attempt_id='old-2'),
                                  [jobs[2]['url']], jobs[2]['id'])
            visited = []

            def prepare(url, **kwargs):
                visited.append(url)
                return {'status': 'blocked', 'blockers': ['synthetic stop'],
                        'output_dir': str(root/'report'), 'resume': {}, 'jd_sha256': 'synthetic'}

            driver = Mock()
            driver.browser_backend = 'local'
            driver.capabilities = {'goog:chromeOptions': {}}
            result = run_submissions(resume_dir=directory, driver_factory=Mock(return_value=driver),
                services={'candidate': {}, 'question_config': {}, 'resume_provider': Mock()}, preparer=prepare)
            self.assertCountEqual(visited, [jobs[0]['url'], jobs[1]['url']])
            self.assertEqual(result['counts'], {'blocked': 2, 'submission_uncertain': 1, 'applied': 1})

    def test_recovery_separates_safe_preparation_from_possible_submission(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            jobs = sum((load_jobs(url=f'https://example.test/jobs/{i}') for i in range(8)), [])
            run = SubmitRun(root/'run', jobs=jobs)
            self.addCleanup(run.close)
            ledger = ExternalApplicationLedger(root/'ledger.json')
            for i, job in enumerate(jobs):
                run.update(job, status='preparing', attempt_id=f'attempt-{i}', attempts=1)
            run.update(jobs[1], status='ready')
            ledger.record_aliases(ExternalApplicationResult('submitting', jobs[2]['url'], attempt_id='attempt-2'), [jobs[2]['url']], jobs[2]['id'])
            ledger.record_aliases(ExternalApplicationResult('applied', jobs[3]['url'], attempt_id='attempt-3'), [jobs[3]['url']], jobs[3]['id'])
            run.update(jobs[4], manual_tab={'target_id': 'retained'})
            run.update(jobs[5], status='submission_uncertain')
            ledger.record_aliases(ExternalApplicationResult('applied', jobs[6]['url'], attempt_id='different-attempt'), [jobs[6]['url']], jobs[6]['id'])
            run.update(jobs[7], external_submission_pending=True)
            assert recover_abandoned_preparations(run, ledger) == 2
            states = [state for _, state in run.rows()]
            assert [state['status'] for state in states] == ['pending','pending','submission_uncertain','applied','submission_uncertain','submission_uncertain','duplicate','submission_uncertain']
            assert states[0]['previous_attempt_id'] == 'attempt-0'
            assert states[0]['attempts'] == 1 and states[0]['attempt_id'] is None
            assert states[2]['retryable'] is False
            assert recover_abandoned_preparations(run, ledger) == 0

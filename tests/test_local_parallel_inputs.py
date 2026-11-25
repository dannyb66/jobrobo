"""Offline local-worker concurrency and TXT/JSON CLI contracts."""
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
from modules.submit_state import SubmitRun


class LocalParallelInputTests(TestCase):
    def test_urls_file_routes_txt_and_all_simple_json_shapes(self):
        urls = [f'https://example.test/jobs/{i}' for i in range(4)]
        rows = [{'id': f'role-{i}', 'url': url, 'title': f'Engineer {i}',
                 'source_tasks': [44]} for i, url in enumerate(urls)]
        payloads = [('jobs.txt', '\n'.join(urls)),
                    ('urls.json', json.dumps(urls)),
                    ('rows.json', json.dumps(rows)),
                    ('jobs.json', json.dumps({'jobs': rows}))]
        with TemporaryDirectory() as tmp:
            for name, content in payloads:
                with self.subTest(name=name):
                    source = Path(tmp)/name
                    source.write_text(content)
                    before = source.read_bytes()
                    with patch('modules.submit_runner.run_submissions',
                               return_value={'jobs': [{'status': 'applied'}]}) as runner, redirect_stdout(StringIO()):
                        code = direct_apply.main(['submit', '--urls-file', str(source),
                            '--captcha-solver', '--pause-before-submit', 'never', '--limit', '4', '--workers', '4'])
                    self.assertEqual(code, 0)
                    selected = runner.call_args.args[0]
                    self.assertEqual([job['url'] for job in selected], urls)
                    self.assertEqual(runner.call_args.kwargs['workers'], 4)
                    self.assertTrue(runner.call_args.kwargs['captcha_solver'])
                    self.assertEqual(source.read_bytes(), before)
                    if name in {'rows.json', 'jobs.json'}:
                        self.assertEqual(selected[0]['source_tasks'], [44])
                        self.assertEqual(selected[0]['title'], 'Engineer 0')
                    self.assertEqual(selected[0]['provenance']['source'], str(source.resolve()))

    def test_large_json_deduplicates_before_global_limit_and_preserves_metadata(self):
        rows = [{'id': f'role-{i}', 'url': f'https://example.test/jobs/{i}',
                 'title': f'Engineer {i}', 'source_record_count': 2} for i in range(2801)]
        with TemporaryDirectory() as tmp:
            source = Path(tmp)/'jobs-phase1.json'
            source.write_text(json.dumps({'jobs': [rows[0], *rows]}))
            before = source.read_bytes()
            with patch('modules.submit_runner.run_submissions',
                       return_value={'jobs': [{'status': 'applied'}]}) as runner, redirect_stdout(StringIO()):
                code = direct_apply.main(['submit', '--urls-file', str(source),
                    '--limit', '2801', '--workers', '4'])
            self.assertEqual(code, 0)
            jobs = runner.call_args.args[0]
            self.assertEqual(len(jobs), 2801)
            self.assertEqual(len({job['key'] for job in jobs}), 2801)
            self.assertEqual(jobs[-1]['id'], 'role-2800')
            self.assertEqual(jobs[-1]['source_record_count'], 2)
            self.assertEqual(len(load_jobs([source], limit=4)), 4)
            self.assertEqual(source.read_bytes(), before)

    def test_malformed_input_never_starts_runner_or_browser(self):
        with TemporaryDirectory() as tmp:
            for payload in ('{"jobs":', json.dumps({'jobs': [{'title': 'missing URL'}]})):
                source = Path(tmp)/'invalid.json'
                source.write_text(payload)
                with patch('modules.submit_runner.run_submissions') as runner, \
                     patch('direct_apply.browser_factory') as browser, redirect_stdout(StringIO()):
                    code = direct_apply.main(['submit', '--urls-file', str(source), '--workers', '4'])
                self.assertNotEqual(code, 0)
                runner.assert_not_called()
                browser.assert_not_called()

    def test_four_default_local_workers_overlap_once_and_persist_mixed_outcomes(self):
        self.assert_local_workers_overlap_and_persist(4)

    def test_sixteen_default_local_workers_overlap_once_and_persist_mixed_outcomes(self):
        self.assert_local_workers_overlap_and_persist(16)

    def assert_local_workers_overlap_and_persist(self, worker_count):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root/'config'
            config.mkdir()
            (config/'search.py').write_text('max_applications_per_run = 50\n')
            jobs = load_jobs(url='https://example.test/jobs/0')
            jobs += sum((load_jobs(url=f'https://example.test/jobs/{i}') for i in range(1, worker_count)), [])
            barrier = threading.Barrier(worker_count)
            guard = threading.Lock()
            active = peak = 0
            visited = []
            drivers = []
            factories = []

            def factory(profile_path=None, *, debugger_address=None, worker_index=None):
                self.assertIsNotNone(worker_index)
                with guard:
                    factories.append(worker_index)
                def create():
                    driver = Mock()
                    driver.browser_backend = 'local'
                    driver.capabilities = {'goog:chromeOptions': {
                        'debuggerAddress': f'127.0.0.1:{9200 + worker_index}'}}
                    driver.current_window_handle = f'tab-{worker_index}'
                    with guard:
                        drivers.append(driver)
                    return driver
                create.profile_path = str(profile_path) + f'-w{worker_index}'
                return create

            def prepare(url, **kwargs):
                nonlocal active, peak
                with guard:
                    active += 1
                    peak = max(peak, active)
                    visited.append(url)
                try:
                    barrier.wait(timeout=10)
                    metadata = kwargs['input_metadata']
                    uncertain = url.endswith(f'/{worker_count - 1}')
                    kwargs['ledger'].record_aliases(ExternalApplicationResult(
                        'submitting' if uncertain else 'applied', url,
                        attempt_id=metadata['attempt_id']), [url], metadata['role_id'])
                    return {'status': 'submission_uncertain' if uncertain else 'applied',
                            'output_dir': str(root/'reports'/url.rsplit('/', 1)[-1]),
                            'resume': {'pdf_sha256': 'synthetic'}, 'jd_sha256': 'synthetic'}
                finally:
                    with guard:
                        active -= 1

            with patch('direct_apply.browser_factory', side_effect=factory), redirect_stdout(StringIO()):
                result = run_submissions(jobs, config_dir=config, output_dir=root/'cache',
                    services={'candidate': {}, 'question_config': {}, 'resume_provider': Mock()},
                    preparer=prepare, workers=worker_count, pause='never', max_applications=worker_count,
                    browser_backend='local', run_dir=root/'run')
            self.assertEqual(peak, worker_count, 'all jobs must overlap before any can finish')
            self.assertEqual(sorted(factories), list(range(1, worker_count + 1)))
            self.assertEqual(len({id(driver) for driver in drivers}), worker_count)
            self.assertCountEqual(visited, [job['url'] for job in jobs])
            self.assertEqual(result['counts'], {'applied': worker_count - 1, 'submission_uncertain': 1})
            self.assertEqual(len({job['worker_id'] for job in result['jobs']}), worker_count)
            self.assertTrue(all(job['attempts'] == 1 for job in result['jobs']))
            self.assertTrue(all(job.get('worker_session') for job in result['jobs']))
            self.assertNotIn('debugger_address', result['options'])
            events = [json.loads(line) for line in (root/'run/events.jsonl').read_text().splitlines()]
            reservations = [event for event in events if event.get('stage') == 'worker_reserved' and 'attempts' in event]
            self.assertEqual(len(reservations), worker_count)
            self.assertEqual({event['job_key'] for event in reservations}, {job['key'] for job in jobs})
            reopened = SubmitRun(root/'run')
            try:
                self.assertEqual(reopened.export()['counts'], result['counts'])
                uncertain = [state for _, state in reopened.rows() if state['status'] == 'submission_uncertain']
                self.assertEqual(len(uncertain), 1)
                self.assertFalse(uncertain[0]['retryable'])
            finally:
                reopened.close()
            artifact = json.loads((root/'run/applications.json').read_text())
            self.assertEqual(len(artifact['records']), worker_count)
            self.assertEqual(sum(row['status'] == 'applied' for row in artifact['records']), worker_count - 1)
            retry = json.loads((root/'run/retry.json').read_text())
            self.assertEqual(len(retry['jobs']), 1)
            self.assertFalse(retry['jobs'][0]['retryable'])

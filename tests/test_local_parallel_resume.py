"""Local retained-worker recovery without Chrome, credentials or submissions."""
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from modules.generic_inputs import load_jobs
from modules.submit_runner import run_submissions
from modules.submit_state import SubmitRun


class LocalParallelResumeTests(TestCase):
    def test_resume_reattaches_worker_sixteen(self):
        jobs = self.saved_run(retained=1)
        saved = SubmitRun(self.directory)
        saved.set_options({**saved.options, 'workers': 16})
        saved.update(jobs[0], worker_id='worker-16', worker_session={
            'backend': 'local', 'worker_id': 'worker-16',
            'profile_path': str(self.directory/'chrome-profile-w16'),
            'debugger_address': self.address})
        saved.close()
        driver = self.driver(self.address)
        factory = Mock(return_value=lambda: driver)
        preparer = Mock(side_effect=AssertionError('Retained application must not replay'))
        result, _, _, _ = self.execute(factory, preparer)
        self.assertEqual(result['counts'], {'awaiting_manual_submit': 1})
        self.assertEqual(result['jobs'][0]['worker_id'], 'worker-16')
        factory.assert_called_once_with(str(self.directory/'chrome-profile-w16'),
                                        debugger_address=self.address)
        preparer.assert_not_called()

    def test_invalid_counts_and_kernel_above_four_fail_before_browser_start(self):
        jobs = load_jobs(url='https://example.test/worker-validation')
        for workers, backend, message in [(17, 'local', 'between 1 and 16'),
                                          (0, 'local', 'between 1 and 16'),
                                          (5, 'kernel', 'Kernel worker count')]:
            with self.subTest(workers=workers, backend=backend), \
                 patch('direct_apply.browser_factory') as factory, \
                 patch('modules.kernel_browser.browser_configuration', return_value=(backend, {})), \
                 patch('modules.kernel_browser.kernel_preflight') as preflight:
                with self.assertRaisesRegex(ValueError, message):
                    run_submissions(jobs, run_dir=self.root/f'{backend}-{workers}',
                                    config_dir=self.config, services=self.services,
                                    workers=workers, browser_backend=backend)
                factory.assert_not_called()
                preflight.assert_not_called()

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config'
        self.config.mkdir()
        (self.config / 'search.py').write_text('max_applications_per_run = 20\n')
        self.services = {'candidate': {}, 'question_config': {},
                         'resume_provider': Mock(return_value={})}
        self.directory = self.root / 'run'
        self.profile = str(self.directory / 'chrome-profile-w1')
        self.address = '127.0.0.1:43101'

    def saved_run(self, *, retained=2, pending=0):
        jobs = sum((load_jobs(url=f'https://example.test/resume-{i}')
                    for i in range(retained + pending)), [])
        saved = SubmitRun(self.directory, jobs=jobs, options={
            'config_dir': str(self.config), 'output_dir': str(self.root / 'cache'),
            'pause': 'never', 'max_applications': 20, 'workers': 2,
            'browser_backend': 'local', 'set_name': 'resume-tests'})
        for i, job in enumerate(jobs[:retained]):
            saved.update(job, status='awaiting_manual_submit', stage='manual_tab',
                         worker_id='worker-01', tab_handle=f'saved-tab-{i}',
                         worker_session={'backend': 'local', 'worker_id': 'worker-01',
                                         'profile_path': self.profile,
                                         'debugger_address': self.address},
                         manual_tab={'target_id': f'saved-tab-{i}', 'token': f'attempt-{i}'})
        saved.close()
        return jobs

    def driver(self, address):
        driver = Mock()
        driver.browser_backend = 'local'
        driver.capabilities = {'goog:chromeOptions': {'debuggerAddress': address}}
        driver.current_window_handle = 'new-tab-' + address
        return driver

    def execute(self, factory, preparer, recovery_error=None, **run_options):
        monitors = []
        def monitor_factory(*args, **kwargs):
            monitor = Mock()
            monitor.tabs = {}
            monitor.poll.return_value = False
            monitors.append(monitor)
            return monitor
        with patch('direct_apply.browser_factory', side_effect=factory) as factories, \
             patch('modules.submit_runner.recover_verification_tabs', side_effect=recovery_error) as recover:
            result = run_submissions(resume_dir=self.directory, config_dir=self.config,
                                     services=self.services, preparer=preparer,
                                     tab_monitor_factory=monitor_factory, **run_options)
        return result, factories, recover, monitors

    def test_grouped_tabs_reattach_once_and_retain_local_browser(self):
        jobs = self.saved_run()
        driver = self.driver(self.address)
        factory = Mock(return_value=lambda: driver)
        preparer = Mock(side_effect=AssertionError('Retained jobs must not be replayed'))
        result, factories, recover, monitors = self.execute(factory, preparer)
        factories.assert_called_once_with(self.profile, debugger_address=self.address)
        self.assertEqual(result['counts'], {'awaiting_manual_submit': 2})
        self.assertEqual([c.args[0] for c in driver.switch_to.window.call_args_list],
                         ['saved-tab-0', 'saved-tab-1'])
        self.assertEqual(recover.call_args.kwargs['job_keys'], {j['key'] for j in jobs})
        monitors[0].restore.assert_called_once_with(job_keys={j['key'] for j in jobs})
        monitors[0].close.assert_called_once()
        driver.service.stop.assert_called_once()
        driver.quit.assert_not_called()
        preparer.assert_not_called()

    def test_restored_worker_and_fresh_worker_process_pending_without_profile_collision(self):
        jobs = self.saved_run(pending=2)
        drivers = {}
        def factory(profile, *, debugger_address=None, worker_index=None):
            key = debugger_address or f'worker-{worker_index}'
            drivers[key] = self.driver(debugger_address or '127.0.0.1:43102')
            return lambda: drivers[key]
        barrier = threading.Barrier(2)
        visited = []
        lock = threading.Lock()
        def prepare(url, **kwargs):
            with lock:
                visited.append(url)
            barrier.wait(timeout=5)
            return {'status': 'blocked', 'blockers': ['synthetic stop'],
                    'output_dir': str(self.root / 'prepared' / url.rsplit('/', 1)[-1]),
                    'resume': {'pdf_sha256': 'synthetic'}}
        result, factories, _, _ = self.execute(factory, prepare)
        self.assertEqual(result['counts'], {'awaiting_manual_submit': 2, 'blocked': 2})
        self.assertCountEqual(visited, [j['url'] for j in jobs[2:]])
        attached = [c for c in factories.call_args_list if c.kwargs.get('debugger_address')]
        launched = [c for c in factories.call_args_list if not c.kwargs.get('debugger_address')]
        self.assertEqual(len(attached), 1)
        self.assertEqual(len(launched), 1)
        self.assertEqual(launched[0].kwargs['worker_index'], 2)
        pending_states = result['jobs'][2:]
        self.assertEqual({s['worker_id'] for s in pending_states}, {'worker-01', 'worker-02'})
        restored_state = next(s for s in pending_states if s['worker_id'] == 'worker-01')
        self.assertEqual(restored_state['worker_session']['profile_path'], self.profile)
        drivers[self.address].service.stop.assert_called_once()
        drivers[self.address].quit.assert_not_called()

    def test_unavailable_retained_session_stays_uncertain_without_replay(self):
        self.saved_run()
        def factory(*args, **kwargs):
            def unavailable():
                raise ConnectionError('synthetic unavailable browser')
            return unavailable
        preparer = Mock(side_effect=AssertionError('Never replay an unresolved submission'))
        result, factories, _, _ = self.execute(factory, preparer)
        factories.assert_called_once_with(self.profile, debugger_address=self.address)
        preparer.assert_not_called()
        self.assertEqual(result['counts'], {'submission_uncertain': 2})
        self.assertTrue(all(s['stage'] == 'manual_browser_unavailable' and not s['retryable']
                            for s in result['jobs']))
        saved = SubmitRun(self.directory)
        try:
            self.assertEqual([s['status'] for _, s in saved.rows()],
                             ['submission_uncertain', 'submission_uncertain'])
        finally:
            saved.close()

    def test_restore_failure_stops_attached_driver_without_closing_retained_chrome(self):
        self.saved_run()
        driver = self.driver(self.address)
        preparer = Mock()
        result, _, _, _ = self.execute(
            Mock(return_value=lambda: driver), preparer,
            recovery_error=RuntimeError('synthetic recovery failure'))
        self.assertEqual(result['counts'], {'submission_uncertain': 2})
        driver.service.stop.assert_called_once()
        driver.quit.assert_not_called()
        preparer.assert_not_called()

    def test_attach_configuration_failure_preserves_retained_chrome(self):
        self.saved_run()
        driver = self.driver(self.address)
        driver.set_window_size.side_effect = RuntimeError('synthetic configuration failure')
        preparer = Mock()
        result, _, recover, _ = self.execute(Mock(return_value=lambda: driver), preparer)
        self.assertEqual(result['counts'], {'submission_uncertain': 2})
        driver.service.stop.assert_called_once()
        driver.quit.assert_not_called()
        recover.assert_not_called()
        preparer.assert_not_called()

    def test_retry_failed_reuses_retained_local_endpoint(self):
        jobs = self.saved_run(retained=1)
        saved = SubmitRun(self.directory)
        saved.update(jobs[0], status='blocked', stage='preparation_finished', retryable=True)
        saved.close()
        driver = self.driver(self.address)
        visited = []
        def prepare(url, **kwargs):
            visited.append(url)
            self.assertIs(kwargs['driver'], driver)
            return {'status': 'blocked', 'blockers': ['synthetic retry stop'],
                    'output_dir': str(self.root / 'retry-prepared'),
                    'resume': {'pdf_sha256': 'synthetic'}}
        result, factories, _, _ = self.execute(
            Mock(return_value=lambda: driver), prepare, retry_failed=True)
        factories.assert_called_once_with(self.profile, debugger_address=self.address)
        self.assertEqual(visited, [jobs[0]['url']])
        self.assertEqual(result['counts'], {'blocked': 1})
        self.assertEqual(result['jobs'][0]['worker_session']['debugger_address'], self.address)
        driver.service.stop.assert_called_once()
        driver.quit.assert_not_called()

    def test_unavailable_retry_endpoint_retries_safely_on_fresh_profile(self):
        jobs = self.saved_run(retained=1, pending=1)
        saved = SubmitRun(self.directory)
        saved.update(jobs[0], status='blocked', stage='preparation_finished', retryable=True)
        saved.close()
        visited = []
        fresh = self.driver('127.0.0.1:43102')
        def factory(profile, *, debugger_address=None, worker_index=None):
            if debugger_address:
                def unavailable():
                    raise ConnectionError('retained endpoint unavailable')
                return unavailable
            if worker_index == 1:
                self.assertIn('chrome-recovery-', str(profile))
                self.assertNotEqual(str(profile), self.profile)
            return lambda: self.driver('127.0.0.1:'+str(43101+worker_index))
        def prepare(url, **kwargs):
            visited.append(url)
            return {'status': 'blocked', 'blockers': ['synthetic stop'],
                    'output_dir': str(self.root / 'fresh-prepared'),
                    'resume': {'pdf_sha256': 'synthetic'}}
        result, _, _, _ = self.execute(factory, prepare, retry_failed=True)
        self.assertCountEqual(visited, [j['url'] for j in jobs])
        self.assertEqual(result['counts'], {'blocked': 2})
        self.assertNotEqual(result['jobs'][0]['worker_session']['debugger_address'], self.address)
        self.assertNotEqual(result['jobs'][0]['worker_session']['profile_path'], self.profile)

    def test_mixed_missing_session_retries_safe_job_and_preserves_unresolved_on_next_resume(self):
        jobs = self.saved_run(retained=2)
        saved = SubmitRun(self.directory)
        saved.update(jobs[0], status='blocked', stage='preparation_finished', retryable=True)
        saved.close()
        fresh_address = '127.0.0.1:43109'
        fresh = self.driver(fresh_address)
        def factory(profile, *, debugger_address=None, worker_index=None):
            if debugger_address == self.address:
                raise ConnectionError('prior browser unavailable')
            if worker_index is not None:
                self.assertIn('chrome-recovery-', str(profile))
            return lambda: fresh
        def prepare(url, **kwargs):
            self.assertEqual(url, jobs[0]['url'])
            return {'status': 'blocked', 'blockers': ['synthetic stop'],
                    'output_dir': str(self.root / 'retry-prepared'),
                    'resume': {'pdf_sha256': 'synthetic'}}
        result, _, _, _ = self.execute(factory, prepare, retry_failed=True, workers=1)
        self.assertEqual(result['counts'], {'blocked': 1, 'submission_uncertain': 1})
        unresolved = result['jobs'][1]
        self.assertEqual(unresolved['stage'], 'manual_browser_unavailable')
        self.assertEqual(unresolved['worker_session']['debugger_address'], self.address)
        self.assertEqual(result['jobs'][0]['worker_session']['debugger_address'], fresh_address)
        no_replay = Mock(side_effect=AssertionError('Unresolved or blocked jobs cannot replay'))
        result, factories, _, _ = self.execute(Mock(return_value=lambda: fresh), no_replay, workers=1)
        self.assertEqual(result['counts'], {'blocked': 1, 'submission_uncertain': 1})
        attached = [call for call in factories.call_args_list if call.kwargs.get('debugger_address')]
        self.assertEqual(len(attached), 1)
        self.assertEqual(attached[0].kwargs['debugger_address'], fresh_address)
        no_replay.assert_not_called()

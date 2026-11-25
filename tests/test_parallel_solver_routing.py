"""Concurrent solvers must stay in their owning browser and artifact directory."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from modules import captcha_solver


class ParallelSolverRoutingTests(TestCase):
    def test_four_workers_resolve_distinct_cdp_endpoints_and_artifacts_concurrently(self):
        barrier = threading.Barrier(4)
        lock = threading.Lock()
        calls = []
        active = 0
        peak = 0

        def version(endpoint, **kwargs):
            self.assertEqual(kwargs['timeout'], 5)
            address = endpoint.removeprefix('http://').removesuffix('/json/version')
            return BytesIO(json.dumps({'webSocketDebuggerUrl': f'ws://{address}/devtools/browser/owned'}).encode())

        def sidecar(command, **kwargs):
            nonlocal active, peak
            # All four calls must reach the sidecar simultaneously. A serial
            # implementation fails the bounded barrier instead of passing on
            # merely distinct output filenames.
            with lock:
                active += 1
                peak = max(peak, active)
                calls.append(command)
            try:
                barrier.wait(timeout=5)
                return SimpleNamespace(stdout=json.dumps({'status': 'cleared', 'token_length': 12}), stderr='')
            finally:
                with lock:
                    active -= 1

        with TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            workers = []
            for index in range(4):
                artifacts = root / f'job-{index}'
                artifacts.mkdir()
                driver = SimpleNamespace(
                    capabilities={'goog:chromeOptions': {'debuggerAddress': f'127.0.0.1:{12000 + index}'}},
                    current_url=f'https://example.test/job/{index}')
                workers.append((driver, artifacts))
            with patch.object(captcha_solver, 'enabled', return_value=True), \
                 patch.object(captcha_solver, 'available', return_value=(True, '')), \
                 patch.object(captcha_solver, '_base_url', return_value='https://solver.example.test'), \
                 patch.object(captcha_solver, '_env', return_value=''), \
                 patch('urllib.request.urlopen', side_effect=version), \
                 patch.object(captcha_solver.subprocess, 'run', side_effect=sidecar):
                with ThreadPoolExecutor(max_workers=4) as pool:
                    futures = [pool.submit(captcha_solver.solve, driver, screenshot_dir=artifacts)
                               for driver, artifacts in workers]
                    results = [future.result(timeout=10) for future in futures]
            self.assertEqual(peak, 4)
            self.assertTrue(all(result['status'] == 'cleared' for result in results))
            screenshots = set()
            for command in calls:
                posting = command[command.index('--url') + 1]
                index = int(posting.rsplit('/', 1)[1])
                endpoint = command[command.index('--cdp') + 1]
                self.assertEqual(endpoint, f'ws://127.0.0.1:{12000 + index}/devtools/browser/owned')
                screenshot = Path(command[command.index('--screenshot') + 1])
                self.assertEqual(screenshot.parent, root / f'job-{index}')
                self.assertTrue(screenshot.exists())
                screenshots.add(screenshot)
            self.assertEqual(len(calls), 4)
            self.assertEqual(len(screenshots), 4)

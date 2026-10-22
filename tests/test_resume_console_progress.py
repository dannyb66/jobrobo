"""Visible resume progress without network, browser or private content logging."""
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time
import unittest
from unittest.mock import Mock

from modules.resume_all_bullets import DEFAULTS, ProviderFailure, Scheduler
from modules.resume_progress import ResumeConsoleProgress
from modules.resume_upload import upload_verified_resume


class ResumeProgressTest(unittest.TestCase):
    def scheduler(self, callback):
        options = dict(DEFAULTS, rewrite_requests_per_minute=1000000,
                       rewrite_tokens_per_minute=1000000000)
        return Scheduler(options, 2, progress=callback)

    def test_logs_before_provider_dispatch_and_omits_private_payload(self):
        messages = []
        clock = Mock(return_value=10)
        with ResumeConsoleProgress(messages.append, '123', clock=clock) as progress:
            scheduler = self.scheduler(progress)
            def provider(stage, payload, timeout):
                self.assertIn('API request 1: JD keyword extraction', messages[-1])
                return {'keywords': ['Python']}
            clock.return_value = 25
            scheduler.call(provider, 'keywords', {'job_description': 'PRIVATE JD TEXT'})
        self.assertIn('15s', messages[-1])
        self.assertIn('response received', messages[-1])
        self.assertNotIn('PRIVATE', '\n'.join(messages))
        self.assertFalse(progress.thread.is_alive())

    def test_heartbeat_reports_current_stage_and_stops_on_exception(self):
        messages = []
        heartbeat = threading.Event()
        def log(message):
            messages.append(message)
            if 'Still running: Rendering' in message:
                heartbeat.set()
        progress = ResumeConsoleProgress(log, '123', interval=.01)
        with self.assertRaisesRegex(RuntimeError, 'fixture'):
            with progress:
                progress({'event': 'rendering', 'attempt': 1})
                self.assertTrue(heartbeat.wait(1), 'Missing rendering heartbeat')
                raise RuntimeError('fixture')
        self.assertFalse(progress.thread.is_alive())
        before = len(messages)
        progress({'event': 'request_finished', 'stage': 'keywords'})
        self.assertEqual(len(messages), before)

    def test_rate_wait_logged_once_and_error_body_not_logged(self):
        messages, events = [], []
        with ResumeConsoleProgress(messages.append, '123') as console:
            def progress(value):
                events.append(value)
                console(value)
            scheduler = self.scheduler(progress)
            scheduler.next_request = time.monotonic() + .02
            payload = {'requested_bullet_ids': ['private-id'], 'retry_reasons': {'private-id': 'private reason'}}
            with self.assertRaises(ProviderFailure):
                scheduler.call(Mock(side_effect=RuntimeError('private API body')), 'bullets', payload)
        self.assertEqual(sum(e['event'] == 'rate_wait' for e in events), 1)
        text = '\n'.join(messages)
        self.assertIn('retry', text)
        self.assertIn('failed', text)
        self.assertNotIn('private', text)
        for event in events:
            self.assertIn('requests', event)
            self.assertIn('reserved_cost_usd', event)

    def test_callback_failure_does_not_abort_provider(self):
        scheduler = self.scheduler(Mock(side_effect=RuntimeError('logger unavailable')))
        self.assertEqual(scheduler.call(lambda *args: {'keywords': []}, 'keywords', {}), {'keywords': []})

    def test_uploader_wires_progress_and_keeps_attachment_behavior(self):
        with TemporaryDirectory() as tmp:
            pdf = Path(tmp) / 'optimized.pdf'
            pdf.write_bytes(b'PDF fixture')
            messages, callbacks = [], []
            def optimize(**kwargs):
                callbacks.append(kwargs['progress_callback'])
                kwargs['progress_callback']({'event': 'rendering', 'attempt': 1})
                return str(pdf)
            modal = Mock()
            result = upload_verified_resume(modal, 'source.docx', 'PRIVATE JD', '123',
                optimize=optimize, log=messages.append,
                runtime_config_override={'rewrite_all_bullets': False, 'source_checks_enabled': True})
            self.assertEqual(result, (True, 'optimized.pdf'))
            modal.find_element.return_value.send_keys.assert_called_once_with(str(pdf.resolve()))
            self.assertTrue(callbacks[0].closed.is_set())
            text = '\n'.join(messages)
            self.assertIn('Starting resume optimization', text)
            self.assertIn('Rendering optimized DOCX', text)
            self.assertIn('Uploading verified PDF', text)
            self.assertIn('PDF attached', text)
            self.assertNotIn('PRIVATE JD', text)


if __name__ == '__main__':
    unittest.main()

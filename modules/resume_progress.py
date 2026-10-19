"""Content-free console progress and bounded heartbeats for resume generation."""
import threading
import time


class ResumeConsoleProgress:
    def __init__(self, log, job_id, *, interval=15, clock=time.monotonic):
        self.log, self.job_id, self.interval, self.clock = log, str(job_id), interval, clock
        self.started = clock()
        self.stage = 'Starting resume optimization'
        self.lock = threading.Lock()
        self.closed = threading.Event()
        self.thread = None

    def _write(self, message):
        if self.log:
            try:
                self.log(f'[Resume {self.job_id} | {self.clock()-self.started:.0f}s] {message}')
            except Exception:
                pass  # Logging must not change generation or application behavior.

    def __enter__(self):
        if self.log:
            with self.lock:
                self._write(self.stage)
            self.thread = threading.Thread(target=self._heartbeat, name='resume-progress', daemon=True)
            self.thread.start()
        return self

    def _heartbeat(self):
        while not self.closed.wait(self.interval):
            with self.lock:
                if self.closed.is_set():
                    return
                self._write('Still running: ' + self.stage)

    def __exit__(self, *args):
        self.closed.set()
        if self.thread:
            self.thread.join(timeout=1)

    def __call__(self, event):
        kind = event.get('event')
        messages = {
            'initializing': f"Preparing rewrite (policy: {event.get('policy', 'configured')}, model: {event.get('model', 'configured')})",
            'inventory_started': 'Mapping source bullets and document layout',
            'inventory_ready': f"Inventoried {event.get('total', 0)} bullets across {event.get('groups', 0)} groups; Academic Distinctions preserved",
            'keywords_ready': f"Extracted {event.get('count', 0)} JD keywords; preparing Skills and bullet requests",
            'bullets_started': 'Rewriting eligible bullets',
            'bullets_progress': f"Bullet candidates ready: {event.get('ready', 0)}/{event.get('total', 0)} (final PDF checks pending)",
            'rendering': f"Rendering optimized DOCX to PDF (attempt {event.get('attempt', 1)}/2)",
            'verifying': 'Checking PDF layout, bullet coverage and preserved sections',
            'layout_retry': 'Retrying bullets or Skills that did not fit the rendered document',
            'scoring': 'Calculating JD match report',
            'saving': 'Saving artifacts, comparison and verification report',
            'finished': f"Optimization {event.get('status', 'finished')}: {event.get('accepted', 0)}/{event.get('total', 0)} bullets accepted; upload eligible: {bool(event.get('eligible'))}",
        }
        if kind in {'request_started', 'request_finished', 'rate_wait'}:
            stage = 'JD keyword extraction' if event.get('stage') == 'keywords' else f"bullet batch ({event.get('bullet_count', 0)} bullets)"
            request = event.get('attempt', event.get('requests', 0))
            if kind == 'rate_wait':
                message = f'Waiting for an API request slot: {stage}'
            elif kind == 'request_started':
                message = f'API request {request}: {stage}'
                if event.get('retry'):
                    message += ' — retry'
            else:
                result = 'failed' if event.get('error_kind') or not event.get('response_received') else 'response received'
                message = f'API request {request}: {stage} — {result}'
        else:
            message = messages.get(kind)
        if message:
            with self.lock:
                if not self.closed.is_set():
                    self.stage = message
                    self._write(message)

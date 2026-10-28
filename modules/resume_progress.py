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
        self.active_requests = {}

    def active_summary(self):
        """Caller holds the console lock when used from the heartbeat thread."""
        oldest = max((self.clock() - started for started in self.active_requests.values()), default=0)
        return f'{len(self.active_requests)} active API requests' + (f' (oldest {oldest:.0f}s)' if self.active_requests else '')

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
                self._write('Still running: ' + self.stage + '; ' + self.active_summary())

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
            'timeout_split': f"Retrying timed-out batch with at most {event.get('batch_size', 1)} bullets per request; existing budgets unchanged",
            'source_fallback': f"Keeping {event.get('retained', 0)} original bullets after rewrite failures; verifying the combined PDF",
            'scoring': 'Calculating JD match report',
            'saving': 'Saving artifacts, comparison and verification report',
            'generation_failed': f"Resume generation failed: {event.get('reason', 'unknown error')}",
            'finished': f"Optimization {event.get('status', 'finished')}: {event.get('accepted', 0)}/{event.get('total', 0)} bullets accepted; upload eligible: {bool(event.get('eligible'))}",
        }
        if kind == 'finished' and event.get('source_fallback'):
            messages['finished'] = (f"Optimization {event.get('status', 'finished')}: "
                f"{event.get('accepted', 0)} bullets rewritten; {event['source_fallback']} original bullets retained; "
                f"total {event.get('total', 0)}; upload eligible: {bool(event.get('eligible'))}")
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
                if event.get('error_kind'):
                    result += f" ({event['error_kind']})"
                if event.get('elapsed_seconds') is not None:
                    result += f" after {event['elapsed_seconds']:.0f}s"
                message = f'API request {request}: {stage} — {result}'
        else:
            message = messages.get(kind)
        if message:
            with self.lock:
                if not self.closed.is_set():
                    if kind == 'request_started':
                        self.active_requests[request] = self.clock()
                    elif kind == 'request_finished':
                        self.active_requests.pop(request, None)
                    elif kind == 'finished':
                        self.active_requests.clear()
                    self.stage = message
                    self._write(message)

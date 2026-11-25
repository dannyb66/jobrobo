"""Opt-in cross-run posting protection with atomic claims for concurrent CLIs."""
import json
from pathlib import Path
import sqlite3
from contextlib import contextmanager

from .generic_inputs import posting_key

CONFIRMED = {'applied','duplicate'}
UNCERTAIN = {'preparing','ready','submitting','submission_uncertain','awaiting_email_verification',
             'awaiting_manual_submit','awaiting_correction','awaiting_review'}


class SubmissionHistory:
    def __init__(self, root):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root/'.posting-claims.sqlite3'

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        self.path.chmod(0o600)
        conn.execute('PRAGMA synchronous=FULL')
        conn.execute('CREATE TABLE IF NOT EXISTS claims '
                     '(key TEXT PRIMARY KEY, owner TEXT NOT NULL, run_dir TEXT NOT NULL, status TEXT NOT NULL)')
        try:
            with conn:yield conn
        finally:conn.close()

    def reserve(self, run):
        """Claim pending jobs, or protect earlier outcomes, before browser startup.

        A crashed active claim is intentionally held for explicit resume of its
        original run. It is never guessed stale based on a timeout.
        """
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            evidence = {}
            for path in sorted(self.root.glob('*/progress.json')):
                if path.parent.resolve() == run.directory:
                    continue
                try:
                    data = json.loads(path.read_text())
                    for job in data['jobs']:
                        status = job['status']
                        if status not in CONFIRMED | UNCERTAIN:continue
                        key = posting_key(job['url'], allow_local=True)
                        previous = evidence.get(key)
                        if previous is None or status in CONFIRMED:
                            evidence[key] = (status, str(path.parent), data['run_id'])
                except (OSError, ValueError, KeyError, TypeError) as error:
                    raise ValueError('Cannot verify submission history: ' + str(path)) from error
            for key, owner, directory, status in conn.execute('SELECT key,owner,run_dir,status FROM claims'):
                if owner == run.manifest['id']:continue
                if key not in evidence or status == 'applied':
                    evidence[key] = ('applied' if status == 'applied' else 'submission_uncertain', directory, owner)
            for job, state in run.rows():
                if state['status'] != 'pending':continue
                previous = evidence.get(job['key'])
                if previous:
                    status, directory, owner = previous
                    confirmed = status in CONFIRMED
                    run.update(job,status='duplicate' if confirmed else 'blocked',
                               stage='history_confirmed' if confirmed else 'history_requires_reconciliation',
                               reason='Earlier confirmed application' if confirmed else
                                      'Earlier unresolved attempt or active claim; reconcile or resume its original run',
                               duplicate_source='history' if confirmed else None, retryable=False,
                               history_evidence={'run_id':owner,'run_dir':directory,'status':status})
                else:
                    conn.execute('INSERT OR REPLACE INTO claims VALUES (?,?,?,?)',
                                 (job['key'],run.manifest['id'],str(run.directory),'active'))

    def finish(self, run):
        """Retain confirmed/unresolved claims; release jobs safe to retry."""
        with self._connect() as conn:
            conn.execute('BEGIN IMMEDIATE')
            for job, state in run.rows():
                status = state['status']
                if status in CONFIRMED:
                    value = 'applied'
                elif status in UNCERTAIN | {'preparing','ready'}:
                    value = 'uncertain'
                else:
                    conn.execute('DELETE FROM claims WHERE key=? AND owner=?', (job['key'],run.manifest['id']))
                    continue
                conn.execute('UPDATE claims SET status=? WHERE key=? AND owner=?',
                             (value,job['key'],run.manifest['id']))

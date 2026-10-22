"""Durable submission checkpoints and derived progress/retry exports."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from .direct_careers_apply import write_json
from .generic_inputs import RETRY_SCHEMA


def now():
    return datetime.now(timezone.utc).isoformat()


class SubmitRun:
    def __init__(self, directory, *, jobs=None, options=None, run_id=None):
        self.directory = Path(directory).expanduser().resolve()
        if jobs is None and not (self.directory/'state.sqlite3').is_file():
            raise ValueError('Not a submission run directory: ' + str(self.directory))
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.directory/'state.sqlite3'
        fresh = not path.exists()
        if fresh and jobs is None:
            raise ValueError('Not a submission run directory: ' + str(self.directory))
        if fresh and any(p.name != 'run.lock' for p in self.directory.iterdir()):
            raise ValueError('New run directory must be empty')
        if not fresh and jobs is not None:
            raise ValueError('Run already exists; use submit --resume ' + str(self.directory))
        self.db = sqlite3.connect(path)
        path.chmod(0o600)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS jobs(key TEXT PRIMARY KEY, position INTEGER NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, job_key TEXT, payload TEXT NOT NULL);''')
        if fresh:
            manifest = {'schema': 'direct-submit-run-v1', 'id': run_id or str(uuid.uuid4()), 'created_at': now(), 'options': options or {}, 'jobs': jobs}
            with self.db:
                self.db.execute('INSERT INTO meta VALUES (?,?)', ('manifest', json.dumps(manifest)))
                for index, job in enumerate(jobs):
                    state = {'status': 'pending', 'stage': 'pending', 'attempts': 0, 'updated_at': now()}
                    self.db.execute('INSERT INTO jobs VALUES (?,?,?,?)', (job['key'], index, json.dumps(job), json.dumps(state)))
            write_json(self.directory/'input.json', manifest)
        self.manifest = json.loads(self.db.execute('SELECT value FROM meta WHERE key=?', ('manifest',)).fetchone()[0])
        row = self.db.execute('SELECT value FROM meta WHERE key=?', ('options',)).fetchone()
        self.options = json.loads(row[0]) if row else self.manifest['options']
        self.export()

    def set_options(self, options):
        self.options = options
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('options', json.dumps(options)))
        self.export()

    def rows(self):
        return [(json.loads(p), json.loads(s)) for p, s in self.db.execute('SELECT payload,state FROM jobs ORDER BY position')]

    def update(self, job, *, status=None, stage=None, **fields):
        state = json.loads(self.db.execute('SELECT state FROM jobs WHERE key=?', (job['key'],)).fetchone()[0])
        event = {'status': status or state['status'], 'stage': stage or state['stage'], **fields}
        state.update(event, updated_at=now())
        with self.db:
            self.db.execute('UPDATE jobs SET state=? WHERE key=?', (json.dumps(state), job['key']))
            self.db.execute('INSERT INTO events(at,job_key,payload) VALUES (?,?,?)', (state['updated_at'], job['key'], json.dumps(event)))
        self.export()
        return state

    def browser_event(self,session_id,event):
        """Session diagnostics without assigning unscoped solver events to a job."""
        with self.db:
            self.db.execute('INSERT INTO events(at,job_key,payload) VALUES (?,?,?)',
                (now(),None,json.dumps({'stage':'browser_telemetry','kernel_session_id':session_id,'captcha_event':event})))
            offset=event.get('cursor_offset')
            if self.options.get('kernel_session_id')==session_id and type(offset) is int and offset>=0:
                self.options['kernel_telemetry_offset']=max(self.options.get('kernel_telemetry_offset',0),offset)
                self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('options',json.dumps(self.options)))
        self.export()

    def export(self):
        rows = self.rows()
        counts = Counter(s['status'] for _, s in rows)
        progress = {'schema': 'direct-submit-progress-v1', 'run_id':self.manifest['id'], 'run_dir': str(self.directory), 'updated_at': now(),
                    'options': self.options if hasattr(self, 'options') else {},
                    'total': len(rows), 'counts': dict(counts),
                    'jobs': [{'id': j['id'], 'url': j['url'], 'title':j.get('title',''),
                              'company':j.get('company',''), 'preference_warnings':j.get('preference_warnings',[]), **s} for j, s in rows]}
        write_json(self.directory/'progress.json', progress)
        retry, uncertain, manual = [], [], []
        for job, state in rows:
            if state['status'] in {'awaiting_manual_submit','awaiting_correction'}:
                manual.append({'job':job, **state})
            if state['status'] in {'submission_uncertain', 'submitting'}:
                uncertain.append({'job': job, **state})
            elif state['status'] in {'failed_before_submit', 'blocked', 'interrupted_before_submit', 'deferred'}:
                retry.append({'job': job, 'retryable': bool(state.get('retryable')), **state})
        write_json(self.directory/'retry.json', {'schema': RETRY_SCHEMA, 'source_run_dir': str(self.directory), 'jobs': retry})
        write_json(self.directory/'needs-review.json', {'schema': 'direct-submit-reconciliation-v1', 'jobs': uncertain})
        write_json(self.directory/'manual-review.json', {'schema':'direct-submit-manual-review-v1','jobs':manual})
        self._text('manual-review.txt', ''.join(r['job']['url']+'\n' for r in manual))
        self._text('retry.txt', ''.join(r['job']['url']+'\n' for r in retry if r['retryable']))
        events = [{'sequence': seq, 'at': at, 'job_key': key, **json.loads(event)} for seq, at, key, event in self.db.execute('SELECT * FROM events ORDER BY sequence')]
        self._text('events.jsonl', ''.join(json.dumps(e, ensure_ascii=False)+'\n' for e in events))
        from .submission_tracking import publish_checkpoint
        publish_checkpoint(progress)
        return progress

    def _text(self, name, content):
        import os
        import tempfile
        fd, tmp = tempfile.mkstemp(dir=self.directory, prefix='.submit-')
        try:
            with os.fdopen(fd, 'w') as handle:
                handle.write(content); handle.flush(); os.fsync(handle.fileno())
            os.replace(tmp, self.directory/name)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def close(self):
        self.db.close()


def status(directory):
    path = Path(directory).expanduser().resolve()/'state.sqlite3'
    if not path.is_file():
        raise ValueError('Not a submission run directory')
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as conn:
        rows = [json.loads(r[0]) for r in conn.execute('SELECT state FROM jobs ORDER BY position')]
        manifest=json.loads(conn.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
    return {'run_id':manifest['id'], 'run_dir': str(path.parent), 'total': len(rows), 'counts': dict(Counter(r['status'] for r in rows))}

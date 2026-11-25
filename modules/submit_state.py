"""Durable submission checkpoints and derived progress/retry exports."""
from collections import Counter
from datetime import datetime, timezone
import json
import shlex
from pathlib import Path
import sqlite3
import threading
import uuid

from .direct_careers_apply import write_json
from .generic_inputs import RETRY_SCHEMA, selected_company_names


def retry_ready(state):
    """Only untouched jobs or explicitly retryable failures before Submit."""
    return state.get('status') == 'pending' or (
        state.get('status') in {'blocked', 'failed_before_submit', 'interrupted_before_submit', 'deferred'}
        and bool(state.get('retryable')))


def now():
    return datetime.now(timezone.utc).isoformat()


def retry_command(progress):
    """A fresh retry keeps the effective execution settings, not CLI defaults."""
    options = progress.get('options') or {}
    args = ['python3','direct_apply.py','submit','--urls-file',
            str(Path(progress['run_dir'])/'retry-ready.json')]
    flags = {'workers':'--workers','pause':'--pause-before-submit',
             'config_dir':'--config-dir','browser_backend':'--browser',
             'browser_config':'--browser-config','max_applications':'--max-applications',
             'questions_path':'--questions','output_dir':'--output-dir',
             'db_path':'--db','set_name':'--set','export_path':'--output',
             'discovery_source':'--discovery-source','history_root':'--history-root',
             'captcha_max_requests':'--captcha-max-requests'}
    for name, flag in flags.items():
        if options.get(name) is not None:
            args.extend([flag,str(options[name])])
    # Retained profiles must not be shared by an independent fresh run.
    if options.get('captcha_solver'):args.append('--captcha-solver')
    if not options.get('history_root'):args.append('--independent-run')
    return shlex.join(args)


def build_run_summary(progress, *, generated_at=None):
    """Return concise, durable run totals; only applied is employer-confirmed."""
    jobs = progress.get('jobs') or []
    counts = dict(progress.get('counts') or Counter(job['status'] for job in jobs))
    options = progress.get('options') or {}
    worker_counts = {}
    company_groups = {}
    for job in jobs:
        if job.get('worker_id'):
            worker_counts.setdefault(job['worker_id'], Counter())[job['status']] += 1
        name = job.get('company')
        name = name.strip() if isinstance(name, str) and name.strip() else '(unknown)'
        group = company_groups.setdefault(name.casefold(), {'company': name, 'jobs': []})
        group['jobs'].append(job)
    company_summaries = []
    for group in company_groups.values():
        members = group['jobs']
        statuses = Counter(job['status'] for job in members)
        company_summaries.append({
            'company': group['company'], 'total_jobs': len(members),
            'confirmed_submissions': statuses.get('applied', 0),
            'confirmed_rate_percent': round(100 * statuses.get('applied', 0) / len(members), 1),
            'retry_ready_count': sum(retry_ready(job) for job in members),
            'status_counts': dict(sorted(statuses.items())),
        })
    total = int(progress.get('total', len(jobs)))
    confirmed = int(counts.get('applied', 0))
    uncertain = int(counts.get('submission_uncertain', 0)) + int(counts.get('submitting', 0))
    email_pending = int(counts.get('awaiting_email_verification', 0))
    manual_pending = sum(int(counts.get(status, 0)) for status in
                         ('awaiting_manual_submit', 'awaiting_correction', 'awaiting_review'))
    retryable = sum(1 for job in jobs
                    if job.get('status') in {'blocked', 'failed_before_submit', 'interrupted_before_submit', 'deferred'}
                    and job.get('retryable'))
    unattempted = int(counts.get('pending', 0)) + int(counts.get('preparing', 0))
    elapsed_seconds = None
    try:
        started = datetime.fromisoformat(progress['started_at'].replace('Z', '+00:00'))
        finished = datetime.fromisoformat(progress['updated_at'].replace('Z', '+00:00'))
        elapsed_seconds = max(0, int((finished - started).total_seconds()))
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    if unattempted:
        outcome = 'partial'
    elif uncertain or email_pending or manual_pending:
        outcome = 'complete_with_unresolved_outcomes'
    elif any(counts.get(key, 0) for key in ('blocked', 'failed_before_submit', 'interrupted_before_submit', 'deferred')):
        outcome = 'complete_with_pre_submit_issues'
    else:
        outcome = 'complete'
    return {
        'schema': 'direct-submit-summary-v1',
        'run_id': progress.get('run_id'),
        'run_dir': progress.get('run_dir'),
        'started_at': progress.get('started_at'),
        'observed_at': progress.get('updated_at'),
        'generated_at': generated_at or now(),
        'elapsed_seconds': elapsed_seconds,
        'outcome': outcome,
        'total_jobs': total,
        'attempted_jobs': max(0, total - unattempted),
        'confirmed_submissions': confirmed,
        'confirmed_rate_percent': round(100 * confirmed / total, 1) if total else 0.0,
        'unresolved_submission_count': uncertain,
        'email_verification_pending_count': email_pending,
        'manual_review_pending_count': manual_pending,
        'blocked_count': int(counts.get('blocked', 0)),
        'failed_before_submit_count': int(counts.get('failed_before_submit', 0)),
        'interrupted_before_submit_count': int(counts.get('interrupted_before_submit', 0)),
        'deferred_count': int(counts.get('deferred', 0)),
        'retryable_before_submit_count': retryable,
        'unattempted_count': unattempted,
        'duplicate_count': int(counts.get('duplicate', 0)),
        'status_counts': dict(sorted(counts.items())),
        'browser_backend': options.get('browser_backend', 'local'),
        'configured_workers': options.get('workers') or 1,
        'worker_status_counts': {worker: dict(sorted(counts.items()))
                                 for worker, counts in sorted(worker_counts.items())},
        'selected_companies': selected_company_names(jobs),
        'company_summaries': company_summaries,
        'retry_ready_count': sum(retry_ready(job) for job in jobs),
        'pause_before_submit': options.get('pause'),
        'max_applications': options.get('max_applications'),
        'captcha_solver_enabled': options.get('captcha_solver'),
    }


def format_run_summary(progress):
    """Human-readable CLI footer, sharing totals with the durable summary."""
    summary = build_run_summary(progress)
    total = summary['total_jobs']
    elapsed = summary['elapsed_seconds']
    duration = 'unknown' if elapsed is None else f'{elapsed // 3600:02d}:{elapsed % 3600 // 60:02d}:{elapsed % 60:02d}'
    solver = summary['captcha_solver_enabled']
    solver_label = 'unknown' if solver is None else 'enabled' if solver else 'disabled'
    lines = [
        '\nDirect apply run summary',
        f"Run: {summary['run_id'] or 'unknown'}",
        f"Started: {summary['started_at'] or 'unknown'} | Last checkpoint: {summary['observed_at'] or 'unknown'}",
        f'Elapsed since run creation: {duration}',
        f"Browser: {summary['browser_backend']} | Workers: {summary['configured_workers']} | Pause before submit: {summary['pause_before_submit'] or 'unknown'}",
        f"Application cap: {summary['max_applications'] if summary['max_applications'] is not None else 'none'} | CAPTCHA solver: {solver_label}",
    ]
    if summary['selected_companies']:
        lines.append('Companies: ' + ', '.join(summary['selected_companies']))
    if summary['run_dir']:
        directory = Path(summary['run_dir'])
        lines.extend([f'Run directory: {directory}',
                      f'Saved summary: {directory / "summary.json"}',
                      f'Application results: {directory / "applications.json"}',
                      f'Progress: {directory / "progress.json"}',
                      f'Retry files: {directory / "retry-ready.json"} | {directory / "retry-submission-uncertain.txt"}',
                      f"Ready for a fresh retry run: {summary['retry_ready_count']}"])
        if summary['retry_ready_count']:
            lines.append('Retry command: ' + retry_command(progress))
        else:
            lines.append('No safe automatic retries; inspect unresolved outcomes before retrying.')
    lines.extend([
        '\nJob status summary',
        f"Outcome: {summary['outcome']}",
        f"Jobs: {total} | Confirmed submissions: {summary['confirmed_submissions']} ({summary['confirmed_rate_percent']:.1f}%)",
        f"Retryable before submit: {summary['retryable_before_submit_count']} | Unattempted/in preparation: {summary['unattempted_count']}",
        f"Uncertain: {summary['unresolved_submission_count']} | Email verification: {summary['email_verification_pending_count']} | Manual review: {summary['manual_review_pending_count']}",
    ])
    for company in summary['company_summaries']:
        lines.append(f"  {company['company']}: {company['confirmed_submissions']}/{company['total_jobs']} confirmed; "
                     + ', '.join(f'{status}={count}' for status, count in company['status_counts'].items()))
    for worker, counts in summary['worker_status_counts'].items():
        lines.append(f"  {worker}: " + ', '.join(f'{status}={count}' for status, count in counts.items()))
    lines.append('Statuses:')
    for status, count in summary['status_counts'].items():
        percent = 100 * count / total if total else 0
        lines.append(f'  {status}: {count} ({percent:.1f}%)')
    return '\n'.join(lines)


class SubmitRun:
    def __init__(self, directory, *, jobs=None, options=None, run_id=None):
        self.directory = Path(directory).expanduser().resolve()
        if jobs is None and not (self.directory/'state.sqlite3').is_file():
            raise ValueError('Not a submission run directory: ' + str(self.directory))
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.RLock()
        path = self.directory/'state.sqlite3'
        fresh = not path.exists()
        if fresh and jobs is None:
            raise ValueError('Not a submission run directory: ' + str(self.directory))
        if fresh and any(p.name != 'run.lock' for p in self.directory.iterdir()):
            raise ValueError('New run directory must be empty')
        if not fresh and jobs is not None:
            raise ValueError('Run already exists; use submit --resume ' + str(self.directory))
        # A submission run can have several isolated browser workers. All
        # transitions still serialize through this one durable run database.
        self.db = sqlite3.connect(path, check_same_thread=False)
        path.chmod(0o600)
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS jobs(key TEXT PRIMARY KEY, position INTEGER NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events(sequence INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, job_key TEXT, payload TEXT NOT NULL);''')
        if fresh:
            manifest = {'schema': 'direct-submit-run-v1', 'id': run_id or str(uuid.uuid4()), 'created_at': now(),
                        'selected_companies': selected_company_names(jobs), 'options': options or {}, 'jobs': jobs}
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
        with self._lock:
            self.options = options
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', ('options', json.dumps(options)))
            self.export()

    def rows(self):
        with self._lock:
            return [(json.loads(p), json.loads(s)) for p, s in self.db.execute('SELECT payload,state FROM jobs ORDER BY position')]

    def update(self, job, *, status=None, stage=None, **fields):
        with self._lock:
            state = json.loads(self.db.execute('SELECT state FROM jobs WHERE key=?', (job['key'],)).fetchone()[0])
            event = {'status': status or state['status'], 'stage': stage or state['stage'], **fields}
            event['event_type'] = ('reservation' if fields.get('reservation_id') else
                'transition' if event['status'] != state['status'] or event['stage'] != state['stage'] else 'metadata')
            state.update(event, updated_at=now())
            with self.db:
                self.db.execute('UPDATE jobs SET state=? WHERE key=?', (json.dumps(state), job['key']))
                self.db.execute('INSERT INTO events(at,job_key,payload) VALUES (?,?,?)', (state['updated_at'], job['key'], json.dumps(event)))
            self.export()
            observer = getattr(self, 'on_update', None)
            if observer:
                observer(job, dict(state))
            return state

    def replace_unsubmitted(self, old_key, replacement, *, evidence):
        """Append an explicitly approved replacement, preserving the old input/history."""
        with self._lock:
            return self._replace_unsubmitted(old_key, replacement, evidence=evidence)

    def _replace_unsubmitted(self, old_key, replacement, *, evidence):
        matches=[(j,s) for j,s in self.rows() if j['key']==old_key]
        if len(matches)!=1 or not evidence:
            raise ValueError('Replacement requires one saved job and verification evidence')
        original,previous=matches[0]
        if previous['status'] not in {'pending','blocked','failed_before_submit','interrupted_before_submit','deferred'}:
            raise ValueError('A confirmed or possibly submitted job cannot be replaced')
        if self.options.get('ledger_path'):
            from .external_apply import ExternalApplicationLedger
            if ExternalApplicationLedger(self.options['ledger_path']).protected(original['url']):
                raise ValueError('A protected application cannot be replaced')
        if any(j['key']==replacement['key'] or j['id']==replacement['id'] for j,_ in self.rows()):
            raise ValueError('Replacement already exists in this run')
        at=now();state={'status':'pending','stage':'approved_replacement','attempts':0,'updated_at':at,
                        'replaces_role_id':original['id'],'replacement_evidence':str(evidence)}
        retired={**previous,'status':'discarded','stage':'replaced_before_submit','retryable':False,'updated_at':at,
                 'replacement_role_id':replacement['id'],'replacement_evidence':str(evidence)}
        position=self.db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM jobs').fetchone()[0]
        with self.db:
            self.db.execute('INSERT INTO jobs VALUES (?,?,?,?)',(replacement['key'],position,json.dumps(replacement),json.dumps(state)))
            self.db.execute('UPDATE jobs SET state=? WHERE key=?',(json.dumps(retired),old_key))
            for key,event in ((old_key,retired),(replacement['key'],state)):
                self.db.execute('INSERT INTO events(at,job_key,payload) VALUES (?,?,?)',(at,key,json.dumps(event)))
        self.export()
        return replacement

    def browser_event(self,session_id,event):
        """Session diagnostics without assigning unscoped solver events to a job."""
        with self._lock:
            with self.db:
                self.db.execute('INSERT INTO events(at,job_key,payload) VALUES (?,?,?)',
                    (now(),None,json.dumps({'stage':'browser_telemetry','kernel_session_id':session_id,'captcha_event':event})))
                offset=event.get('cursor_offset')
                if self.options.get('kernel_session_id')==session_id and type(offset) is int and offset>=0:
                    self.options['kernel_telemetry_offset']=offset
                    self.db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)',('options',json.dumps(self.options)))
            self.export()

    def export(self):
        with self._lock:
            return self._export_locked()

    def _export_locked(self):
        rows = self.rows()
        counts = Counter(s['status'] for _, s in rows)
        progress = {'schema': 'direct-submit-progress-v1', 'run_id':self.manifest['id'], 'run_dir': str(self.directory), 'updated_at': now(),
                    'started_at': self.manifest.get('created_at'),
                    'options': self.options if hasattr(self, 'options') else {},
                    'selected_companies': selected_company_names([job for job, _ in rows]),
                    'total': len(rows), 'counts': dict(counts),
                    'active_total':sum(s['status']!='discarded' for _,s in rows),
                    'active_counts':{k:v for k,v in counts.items() if k!='discarded'},
                    'jobs': [{'id': j['id'], 'url': j['url'], 'title':j.get('title',''),
                              'company':j.get('company',''), 'preference_warnings':j.get('preference_warnings',[]), **s} for j, s in rows]}
        write_json(self.directory/'progress.json', progress)
        retry, uncertain, manual = [], [], []
        for job, state in rows:
            if state['status'] in {'awaiting_manual_submit','awaiting_correction','awaiting_email_verification'}:
                manual.append({'job':job, **state})
            if state['status'] in {'submission_uncertain', 'submitting','awaiting_email_verification'}:
                uncertain.append({'job': job, **state})
            elif state['status'] in {'failed_before_submit', 'blocked', 'interrupted_before_submit', 'deferred'}:
                retry.append({'job': job, 'retryable': bool(state.get('retryable')), **state})
        # Every non-success URL stays in the retry export so a later run can pick
        # it up, even when it is not safe to replay automatically. The uncertain
        # ones are marked not retryable, which surfaces them as needing manual
        # resolution rather than silently dropping them.
        tracked = retry + [{'job': r['job'], 'retryable': False, **{k: v for k, v in r.items() if k != 'job'}}
                           for r in uncertain]
        write_json(self.directory/'retry.json', {'schema': RETRY_SCHEMA, 'source_run_dir': str(self.directory),
                                              'source_options':self.options, 'jobs': tracked})
        ready = [{'job': job, **state, 'retryable': True} for job, state in rows if retry_ready(state)]
        write_json(self.directory/'retry-ready.json', {
            'schema': RETRY_SCHEMA, 'source_run_dir': str(self.directory), 'source_options':self.options, 'jobs': ready})
        write_json(self.directory/'retry-uncertain.json', {
            'schema': RETRY_SCHEMA, 'source_run_dir': str(self.directory),
            'source_options':self.options, 'jobs': [dict(r,retryable=False) for r in uncertain]})
        uncertain_lines = ['# Status: submission_uncertain', '# Source run: ' + self.manifest['id']]
        for job, state in rows:
            if state['status'] == 'submission_uncertain':
                label = str(job.get('company', '')) + ' | ' + str(job.get('title') or job['id'])
                uncertain_lines.extend(['# ' + ' '.join(label.splitlines()), job['url']])
        self._text('retry-submission-uncertain.txt', '\n'.join(uncertain_lines) + '\n')
        write_json(self.directory/'needs-review.json', {'schema': 'direct-submit-reconciliation-v1', 'jobs': uncertain})
        write_json(self.directory/'manual-review.json', {'schema':'direct-submit-manual-review-v1','jobs':manual})
        self._text('manual-review.txt', ''.join(r['job']['url']+'\n' for r in manual))
        self._text('retry.txt', ''.join(r['job']['url']+'\n' for r in tracked if r['retryable']))
        self._text('retry-manual.txt', ''.join(r['job']['url']+'\n' for r in tracked if not r['retryable']))
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
        with self._lock:
            self.db.close()


def status(directory):
    path = Path(directory).expanduser().resolve()/'state.sqlite3'
    if not path.is_file():
        raise ValueError('Not a submission run directory')
    with sqlite3.connect(path.as_uri()+'?mode=ro', uri=True) as conn:
        rows = [json.loads(r[0]) for r in conn.execute('SELECT state FROM jobs ORDER BY position')]
        manifest=json.loads(conn.execute("SELECT value FROM meta WHERE key='manifest'").fetchone()[0])
    return {'run_id':manifest['id'], 'run_dir': str(path.parent), 'total': len(rows), 'counts': dict(Counter(r['status'] for r in rows))}

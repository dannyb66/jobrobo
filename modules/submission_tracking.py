"""Reporting-only cross-run application history; never gates or submits jobs."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .direct_careers_apply import write_json
from .search_history import file_lock

REPO = Path(__file__).resolve().parents[1]
UNCERTAIN = {'submission_uncertain', 'submitting', 'awaiting_email_verification'}
MANUAL = {'awaiting_manual_submit', 'awaiting_correction', 'awaiting_review', 'awaiting_email_verification'}
EXCLUDED = {'applied', 'duplicate', *UNCERTAIN}
BEGIN = '<!-- jobrobo-submission-tracking:start -->'
END = '<!-- jobrobo-submission-tracking:end -->'


def job_url(value):
    """Match posting URLs across apply suffixes and attribution parameters."""
    p = urlsplit(value or '')
    host = (p.hostname or '').lower()
    if p.scheme != 'https' or p.username or p.password or not host or host in {'localhost', '127.0.0.1'} or host.endswith(('.test', '.invalid', '.example')):
        return ''
    path = p.path.rstrip('/')
    if host in {'jobs.ashbyhq.com', 'jobs.lever.co'}:
        path = re.sub(r'/(?:application|apply|thanks|thank-you)$', '', path)
        query = ''
    else:
        query = urlencode(sorted((k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k.lower() not in {'source', 'gh_src', 'lever-source'}))
    return urlunsplit((p.scheme, p.netloc.lower(), path, query, ''))


def _path(value, base=REPO):
    p = Path(value).expanduser()
    return (p if p.is_absolute() else base/p).resolve()


def settings(config_dir):
    path = Path(config_dir).expanduser()/'submission_tracking.json'
    if not path.is_file():
        return None
    config = json.loads(path.read_text())
    return config if config.get('enabled') is True else None


def _text(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.submission-tracking-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def run_record(progress):
    directory = _path(progress['run_dir'])
    jobs = []
    for source in progress['jobs']:
        url = job_url(source.get('url'))
        if not url:
            continue
        # Explicit allowlist: never publish browser credentials, profile answers,
        # signed live-view URLs, input options or resume contents in the index.
        job = {k: source[k] for k in ('id', 'title', 'company', 'status', 'stage', 'attempt_id', 'attempts',
                                     'updated_at', 'submitted_at', 'retryable', 'confirmation_verified') if k in source}
        job['url'] = url
        if source.get('preparation_report'):
            job['report_url'] = _path(source['preparation_report']).as_uri()
        jobs.append(job)
    return {'run_id': progress.get('run_id') or directory.name, 'run_dir': str(directory),
            'updated_at': progress.get('updated_at', ''), 'jobs': jobs,
            'progress_url': (directory/'progress.json').as_uri(),
            'events_url': (directory/'events.jsonl').as_uri(),
            'review_url': (directory/'needs-review.json').as_uri()}


def aggregate(runs):
    by_url = {}
    for run in runs.values():
        for job in run['jobs']:
            by_url.setdefault(job['url'], []).append({**job, **{k: run[k] for k in ('run_id', 'run_dir', 'progress_url', 'events_url', 'review_url')}})
    output = {}
    for url, attempts in by_url.items():
        attempts.sort(key=lambda a: (a.get('updated_at', ''), a['run_id']), reverse=True)
        states = {a['status'] for a in attempts}
        # A later failed or pending fresh run cannot erase a confirmed result.
        status = ('applied' if 'applied' in states else 'awaiting_email_verification' if 'awaiting_email_verification' in states else 'submission_uncertain' if states & UNCERTAIN
                  else 'duplicate' if 'duplicate' in states else next((a['status'] for a in attempts if a['status'] != 'pending'), 'pending'))
        output[url] = {'status': status, 'statuses': sorted(states), 'exclude_from_remaining': status in EXCLUDED,
                       'has_uncertain_attempts': bool(states & UNCERTAIN), 'attempts': attempts}
    return output


def _dashboard(index):
    e = lambda value: html.escape(str(value), quote=True)
    rows = []
    for run in sorted(index['runs'].values(), key=lambda r: r['updated_at'], reverse=True):
        jobs = ''.join('<li>'+e(j.get('company', '')+' — '+j.get('title', j['url']))+': <strong>'+e(j['status'])+'</strong>'+
                       (' · <a href="'+e(j['report_url'])+'">Report</a>' if j.get('report_url') else '')+'</li>' for j in run['jobs'])
        counts = dict(Counter(j['status'] for j in run['jobs']))
        rows.append('<tr><td>'+e(run['run_id'])+'</td><td>'+e(run['updated_at'])+'</td><td>'+e(json.dumps(counts))+
                    '</td><td><a href="'+e(run['progress_url'])+'">Progress</a> · <a href="'+e(run['review_url'])+'">Uncertain outcomes</a> · <a href="'+e(run['events_url'])+'">Events</a><details><summary>Jobs and statuses</summary><ul>'+jobs+'</ul></details></td></tr>')
    warnings = ''.join('<li>'+e(w['path'])+': '+e(w['reason'])+'</li>' for w in index.get('warnings', []))
    warning = '<p>Some run files could not be refreshed:</p><ul>'+warnings+'</ul>' if warnings else ''
    return '<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Submission runs</title><style>body{font:15px/1.5 system-ui;margin:24px;color:#172635}table{border-collapse:collapse;width:100%}td,th{padding:12px;border:1px solid #ccd5dd;text-align:left;vertical-align:top;overflow-wrap:anywhere}a{color:#155a8a}table{table-layout:fixed}summary{cursor:pointer}</style><h1>Submission runs</h1><p>Saved at '+e(index['generated_at'])+'. Historical uncertain attempts remain visible even when another run confirms submission. Reload to see saved updates.</p>'+warning+'<table><thead><tr><th>Run</th><th>Last saved</th><th>Statuses</th><th>Evidence</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></html>'


def update_reviews(index, config, history_dir):
    updated = []
    for review in config.get('role_reviews', []):
        source, page = _path(review['input']), _path(review['page'])
        if not source.is_file() or not page.is_file():
            continue
        original = json.loads(source.read_text())
        annotated, remaining = deepcopy(original), deepcopy(original)
        kept = []
        matched = 0
        for role in annotated['records']:
            status = index['by_url'].get(job_url(role.get('career_url')))
            role['submission_tracking'] = status or {'status': 'not_started', 'statuses': [], 'attempts': [], 'exclude_from_remaining': False}
            matched += bool(status)
            if not role['submission_tracking']['exclude_from_remaining']:
                kept.append(role)
        remaining['records'] = kept
        stem = source.stem
        annotated_path = source.with_name(stem+'-with-submissions.json')
        remaining_path = source.with_name(stem+'-remaining.json')
        write_json(annotated_path, annotated)
        write_json(remaining_path, remaining)
        _text(remaining_path.with_suffix('.txt'), ''.join(r['career_url']+'\n' for r in kept))
        updated.extend(str(p) for p in (annotated_path, remaining_path, remaining_path.with_suffix('.txt')))
        block = BEGIN+'\n<script src="'+html.escape((history_dir/'history.js').as_uri(), quote=True)+'"></script>\n'
        block += '<script src="'+html.escape((REPO/'modules/submission_tracking.js').as_uri(), quote=True)+'" data-remaining="'+html.escape(remaining_path.as_uri(), quote=True)+'" data-remaining-urls="'+html.escape(remaining_path.with_suffix('.txt').as_uri(), quote=True)+'"></script>\n'+END
        document = page.read_text()
        if BEGIN in document:
            document = re.sub(re.escape(BEGIN)+'.*?'+re.escape(END), lambda _: block, document, flags=re.S)
        else:
            document = document.replace('</body>', block+'\n</body>')
        _text(page, document)
        updated.append({'page': str(page), 'roles': len(annotated['records']), 'matched_roles': matched, 'remaining_roles': len(kept)})
    return updated


def publish(progress=None, *, config_dir=REPO/'config'):
    config = settings(config_dir)
    if config is None:
        return None
    directory = _path(config['history_dir'])
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if progress is not None:
        record = run_record(progress)
        # Persist each custom-directory checkpoint independently before taking
        # the aggregate lock. A concurrent publisher can pick up this run even
        # if this call cannot acquire the reporting lock.
        name = hashlib.sha256(record['run_dir'].encode()).hexdigest()+'.json'
        saved = directory/'run-snapshots'/name
        with file_lock(saved.with_suffix('.lock')):
            previous = json.loads(saved.read_text()) if saved.is_file() else None
            if previous is None or record['updated_at'] >= previous['updated_at']:
                write_json(saved, record)
    with file_lock(directory/'history.lock'):
        path = directory/'history.json'
        index = json.loads(path.read_text()) if path.is_file() else {'schema': 'direct-submit-history-v1', 'runs': {}}
        records = []
        warnings = []
        for saved in (directory/'run-snapshots').glob('*.json'):
            records.append(json.loads(saved.read_text()))
        for root in config.get('run_roots', []):
            for saved in _path(root).glob('*/progress.json'):
                try:
                    records.append(run_record(json.loads(saved.read_text())))
                except (ValueError, KeyError, TypeError):
                    warnings.append({'path': str(saved), 'reason': 'Invalid run progress; previous indexed state retained'})
        for record in records:
            old = index['runs'].get(record['run_dir'])
            if old is None or record['updated_at'] >= old['updated_at']:
                index['runs'][record['run_dir']] = record
        index['by_url'] = aggregate(index['runs'])
        index['warnings'] = warnings
        index['generated_at'] = datetime.now(timezone.utc).isoformat()
        index['runs_url'] = (directory/'runs.html').as_uri()
        write_json(path, index)
        _text(directory/'history.js', 'window.JOBROBO_SUBMIT_HISTORY='+json.dumps(index, ensure_ascii=True).replace('<', '\\u003c')+';\n')
        _text(directory/'runs.html', _dashboard(index))
        with file_lock(_path(config.get('tracker_lock', str(directory/'tracker.lock')))):
            index['updated_reviews'] = update_reviews(index, config, directory)
        return index


def publish_checkpoint(progress):
    """A failed report refresh must never alter submission/claim semantics."""
    config_dir = progress.get('options', {}).get('config_dir')
    if not config_dir:
        return
    try:
        publish(progress, config_dir=config_dir)
    except Exception as error:
        print('[Tracking] Saved run state; tracker refresh pending ('+type(error).__name__+'). Run python3 -m modules.submission_tracking to refresh.', flush=True)


if __name__ == '__main__':
    result = publish()
    print(json.dumps({'runs': len(result['runs']), 'jobs': len(result['by_url']), 'updated_reviews': result['updated_reviews']} if result else {'enabled': False}, indent=2))

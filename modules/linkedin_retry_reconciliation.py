"""Reconcile retry metadata with durable outcomes; never open or submit a job."""
from collections import Counter
import csv
import json
from pathlib import Path

from modules.linkedin_deferred import DeferredJobs
from modules.search_history import load_applied_job_ids


def _checkpoint_info(data, path, query, job_id, previous):
    job = query['jobs'][job_id]
    status = job['status']
    # An active pre-submit job must not become runnable merely because a
    # reconciliation ran. Specific entry/card failures are retained separately.
    if status == 'in_progress':
        return None
    status = {'prepared': 'ready', 'submitting': 'submission_uncertain'}.get(status, status)
    if status not in {'ready', 'submission_uncertain', 'applied', 'failed', 'skipped', 'collected'}:
        return None
    spec = query['spec']
    context = spec.get('pipeline_context') or {}
    company = context.get('company') or {}
    reason = job.get('reason') or status
    if status == 'failed' and previous.get('run_id') == data['run_id'] and previous.get('status') == 'failed':
        reason = previous.get('reason') or reason
    disabled = previous.get('submission_disabled') if previous.get('run_id') == data['run_id'] else None
    if status == 'ready':
        disabled = True
    elif status in {'applied', 'submission_uncertain'}:
        disabled = False
    elif disabled is None and any(
            j.get('status') in {'applied', 'submitting'} for q in data['queries'] for j in q['jobs'].values()):
        disabled = False
    info = dict(job_id=job_id, status=status, reason=reason,
                run_id=data['run_id'], source_report=str(path), observed_at=job.get('updated_at'),
                query_id=spec['query_id'], query=spec['query_text'],
                profile=spec.get('profile_name'),
                title=previous.get('title'),
                company=previous.get('company') or company.get('name', ''),
                submission_disabled=disabled,
                requires_submission_check=status == 'submission_uncertain')
    if status == 'ready':
        info['submit_enabled'] = True
    elif status == 'applied':
        info['submit_enabled'] = False
    if status == 'failed' and job.get('reason') == 'Application status manually verified on LinkedIn':
        info['verified_submission_outcome'] = 'not_submitted'
    return info


def sync_retry_checkpoint(manifest, spec, job_id, *, submission_disabled=False):
    """Mirror a tracked checkpoint, including eligibility skips and Submit state."""
    job_id = str(job_id)
    path = manifest.path.parent.parent / 'deferred_applications' / 'retry_jobs.json'
    ledger = DeferredJobs(path)
    previous = next((r for r in ledger.records if r['job_id'] == str(job_id)), {})
    query = manifest.query(spec.query_id)
    if not previous and query['jobs'][job_id]['status'] not in {'applied', 'submitting'}:
        return
    info = _checkpoint_info(manifest.data, manifest.path, query, job_id, previous)
    if info is None:
        return
    if info['status'] not in {'applied', 'submission_uncertain', 'ready'}:
        info['submission_disabled'] = bool(submission_disabled)
    ledger.record(info)
    ledger.export_markdown(path.with_suffix('.md'))


def reconcile_retry_ledger(path, state_directory, applied_history=None):
    """Repair tracked jobs from all durable evidence before selecting retries.

    Confirmed application evidence wins over later failures. Unresolved Submit
    checkpoints stay on hold. Latest eligibility skips stop automatic retries.
    Original run files/CSV rows are never rewritten.
    """
    path = Path(path)
    if not path.exists():
        return {'changed': [], 'count': 0}
    ledger = DeferredJobs(path)
    records = {r['job_id']: r for r in ledger.records}
    events = {job_id: [] for job_id in records}
    # Validate all evidence before writing anything; corrupt state fails closed.
    for source in Path(state_directory).glob('*.json'):
        data = json.loads(source.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('queries'), list):
            raise ValueError(f'Invalid search manifest: {source}')
        for query in data['queries']:
            for job_id, job in query['jobs'].items():
                if job_id in events:
                    events[job_id].append((job.get('updated_at') or data.get('last_updated_at', ''), data, source, query))
    confirmed_csv = {}
    if applied_history and Path(applied_history).exists():
        applied_ids = load_applied_job_ids(applied_history)
        with Path(applied_history).open(newline='', encoding='utf-8-sig') as handle:
            for row in csv.DictReader(handle):
                job_id = row.get('Job ID', '').strip()
                if job_id in applied_ids and ('Date Applied' not in row or row['Date Applied'].strip() not in {'', 'Pending'}):
                    confirmed_csv[job_id] = row
    changed = []
    for job_id, previous in records.items():
        candidates = sorted(events[job_id], key=lambda e: e[0], reverse=True)
        applied = next((event for event in candidates if event[3]['jobs'][job_id]['status'] == 'applied'), None)
        uncertain = next((event for event in candidates if event[3]['jobs'][job_id]['status'] == 'submitting'), None)
        chosen = applied or uncertain or (candidates[0] if candidates else None)
        if applied is None and job_id in confirmed_csv:
            row = confirmed_csv[job_id]
            info = dict(job_id=job_id, status='applied', submission_disabled=False,
                        requires_submission_check=False, submit_enabled=False,
                        reason='Confirmed application in applied CSV history',
                        source_report=str(applied_history), run_id=row.get('Search Run ID'),
                        last_seen=row.get('Date Applied'), title=row.get('Title'), company=row.get('Company'))
        elif chosen:
            _, data, source, query = chosen
            info = _checkpoint_info(data, source, query, job_id, previous)
        else:
            info = None
        if info is not None:
            current = ledger.record(info)
            if current != previous:
                changed.append({'job_id': job_id, 'before': previous['status'], 'after': current['status']})
    ledger.export_markdown(path.with_suffix('.md'))
    final = ledger.records
    return {'changed': changed, 'count': len(final),
            'statuses': dict(Counter(r['status'] for r in final)),
            'submission_check_holds': [r['job_id'] for r in final if r.get('requires_submission_check') is True]}

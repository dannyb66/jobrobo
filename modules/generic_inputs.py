"""Read-only inputs shared by direct preparation and submission."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import sqlite3

from .generic_prepare import canonical_url, fingerprint
from .external_apply import identify_ats
from .job_pipeline.models import read_artifact

RETRY_SCHEMA = 'direct-submit-retry-v1'


def posting_key(url, *, allow_local=False):
    identity = identify_ats(url)
    return '|'.join(identity.key) if identity else 'generic|' + fingerprint(canonical_url(url, allow_local=allow_local))


def _role(role, provenance):
    if not isinstance(role, dict) or not role.get('id') or not isinstance(role.get('career_url'), str):
        raise ValueError('Verified roles require stable id and career_url')
    blockers = []
    if role.get('verification_eligible', role.get('eligible')) is not True:
        blockers.append('not_in_verified_engineering_inventory')
    if role.get('status') != 'open' or role.get('is_prospect'):
        blockers.append('posting_not_verified_open')
    if not role.get('title') or not role.get('description'):
        blockers.append('missing_verified_title_or_description')
    company = role.get('company') or {}
    if not isinstance(company, dict) or company.get('id') != role.get('company_id'):
        blockers.append('missing_company_provenance')
        company = company if isinstance(company, dict) else {}
    try:
        observed = datetime.fromisoformat(role['verified_at'].replace('Z', '+00:00'))
        fresh = datetime.now(timezone.utc)-timedelta(days=7) <= observed <= datetime.now(timezone.utc)+timedelta(minutes=5)
    except (KeyError, ValueError, TypeError):
        fresh = False
    return {'id': role['id'], 'url': role['career_url'], 'role': deepcopy(role),
            'title': role.get('title', ''), 'company': company.get('name', ''),
            'description': role.get('description', ''), 'company_id': role.get('company_id'),
            'verification_run_id': role.get('verification_run_id'), 'verified_at': role.get('verified_at'),
            'needs_live_revalidation': not fresh, 'admission_blockers': blockers,
            'preference_warnings': role.get('application_exclusion_reasons', []), 'provenance': deepcopy(provenance)}


def _payload(data, provenance):
    if isinstance(data, dict) and data.get('stage'):
        artifact = read_artifact(data)
        if artifact.stage != 'verified_roles':
            raise ValueError('Direct jobs require verified_roles JSON; run verify careers for companies, or use the LinkedIn lane for linkedin_jobs')
        provenance = {**provenance, 'set_name': artifact.set_name, 'input_run_id': artifact.run_id,
                      'input_set_ids': artifact.input_set_ids}
        return [_role(r, provenance) for r in artifact.records]
    if isinstance(data, dict) and data.get('schema') == 'direct-careers-queue-v1':
        from .direct_careers_apply import validate_queue
        validate_queue(data)
        result = []
        for row in data['records']:
            job = _role(row['role'], {**provenance, **data['input'], 'input_run_id':data['input']['run_id'], 'queue_id': data['queue_id']})
            outcomes = [a.get('outcome', {}).get('status') for a in row.get('attempts', [])]
            states = [row['status'], *outcomes]
            job['prior_status'] = ('applied' if 'applied' in states else 'submission_uncertain'
                if any(s in {'submitting', 'submission_uncertain'} for s in states) else row['status'])
            result.append(job)
        return result
    if isinstance(data, dict) and data.get('schema') == RETRY_SCHEMA:
        result = []
        for row in data.get('jobs', []):
            job = deepcopy(row['job'])
            origins = job.setdefault('retry_origins', [])
            origin = {'run_dir':data['source_run_dir'], 'key':job.get('key')}
            if origin not in origins:
                origins.append(origin)
            if not row.get('retryable'):
                job.setdefault('admission_blockers', []).append('retry_requires_manual_resolution')
            result.append(job)
        return result
    if isinstance(data, dict):
        if set(data) != {'jobs'}:
            raise ValueError('Simple job JSON must be a URL array or an object with a jobs array')
        data = data['jobs']
    if not isinstance(data, list):
        raise ValueError('Job input must contain an array')
    result = []
    for row in data:
        row = {'url': row} if isinstance(row, str) else deepcopy(row)
        if not isinstance(row, dict) or not isinstance(row.get('url'), str):
            raise ValueError('Every job needs a url string')
        if row.get('career_url') and row['career_url'] != row['url']:
            raise ValueError('Conflicting job URL fields')
        result.append({**row, 'provenance': deepcopy(provenance), 'admission_blockers': []})
    return result


def load_jobs(inputs=(), *, url=None, db_path=None, selected_roles=(), limit=None, allow_local=False):
    """Validate the complete input before browser, credentials or durable mutation."""
    jobs = []
    if url:
        jobs.extend(_payload([url], {'source': 'explicit_url'}))
    for value in inputs:
        path = Path(value).expanduser()
        if path.is_file():
            raw = path.read_bytes()
            origin = {'source': str(path.resolve()), 'artifact_sha256': hashlib.sha256(raw).hexdigest()}
            data = json.loads(raw) if path.suffix.lower() == '.json' else [s.strip() for s in raw.decode('utf-8-sig').splitlines() if s.strip() and not s.lstrip().startswith('#')]
        else:
            if str(value).lower().endswith(('.json', '.txt')) or not db_path or not Path(db_path).expanduser().is_file():
                raise ValueError('Input file or existing named-set database not found: ' + str(value))
            name = str(value).removeprefix('verified_roles:')
            with sqlite3.connect(Path(db_path).expanduser().resolve().as_uri() + '?mode=ro', uri=True) as conn:
                rows = conn.execute("SELECT e.record FROM entities e JOIN set_memberships s ON s.stage=e.stage AND s.entity_id=e.entity_id WHERE s.stage='verified_roles' AND s.set_name=? ORDER BY s.first_seen,e.entity_id", (name,)).fetchall()
            if not rows:
                raise ValueError('Unknown or empty verified_roles set: ' + name)
            jobs.extend(_role(json.loads(r[0]), {'source': str(value), 'set_name': name}) for r in rows)
            continue
        jobs.extend(_payload(data, origin))
    if not jobs:
        raise ValueError('At least one job URL is required')
    ids = set(); id_keys = {}
    merged = {}
    for job in jobs:
        job['url'] = canonical_url(job['url'], allow_local=allow_local)
        job['key'] = posting_key(job['url'], allow_local=allow_local)
        job.setdefault('id', 'url:' + fingerprint(job['url'])[:24])
        if not isinstance(job['id'], str) or not job['id']:
            raise ValueError('Job IDs must be nonempty strings')
        if job['id'] in id_keys and id_keys[job['id']] != job['key']:
            raise ValueError('One job ID identifies different postings')
        id_keys[job['id']] = job['key']
        ids.add(job['id'])
        if job['key'] in merged:
            old = merged[job['key']]
            if old.get('description') and job.get('description') and old['description'] != job['description']:
                raise ValueError('Conflicting saved descriptions for the same posting')
            if job.get('role') and not old.get('role'):
                merged[job['key']] = {**job, 'aliases':[old['id'],*old.get('aliases',[])]}
                if old.get('prior_status') in {'applied','submitting','submission_uncertain'}:
                    merged[job['key']]['prior_status']=old['prior_status']
                old=merged[job['key']]
            else:
                old.setdefault('aliases', []).append(job['id'])
            states={old.get('prior_status'),job.get('prior_status')}
            if 'applied' in states: old['prior_status']='applied'
            elif states.intersection({'submitting','submission_uncertain'}): old['prior_status']='submission_uncertain'
        else:
            merged[job['key']] = job
    selected = set(selected_roles)
    if selected - ids:
        raise ValueError('Selected role IDs are absent from the input')
    jobs = [j for j in merged.values() if not selected or selected.intersection([j['id'], *j.get('aliases', [])])]
    return jobs[:limit] if limit else jobs


def job_hint(job):
    return {'title': job.get('title', ''), 'company': job.get('company', ''),
            'description': '' if job.get('needs_live_revalidation') else job.get('description', '')}

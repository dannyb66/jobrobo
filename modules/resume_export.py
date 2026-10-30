"""Export an existing direct-submit resume without generating or submitting anything."""
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

from .submission_tracking import REPO, job_url


def _path(value):
    path = Path(value).expanduser()
    return path if path.is_absolute() else REPO / path


def _read(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError(f'Expected a JSON object: {path}')
    return data


def _time(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError()
        return result
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f'Invalid saved run timestamp: {value!r}') from None


def _progress_paths(config_dir):
    config_path = _path(config_dir) / 'submission_tracking.json'
    config = _read(config_path) if config_path.is_file() else {}
    paths = set()
    for root in config.get('run_roots', ['logs/direct_submit']):
        paths.update(_path(root).glob('*/progress.json'))
    # Custom --run-dir runs are also retained by the reporting index.
    history_path = _path(config.get('history_dir', 'logs/direct_submit_tracking')) / 'history.json'
    if history_path.is_file():
        for record in _read(history_path).get('runs', {}).values():
            paths.add(_path(record['run_dir']) / 'progress.json')
    return sorted(paths)


def _select(url, run_dir, config_dir):
    paths = [_path(run_dir) / 'progress.json'] if run_dir else _progress_paths(config_dir)
    matches = []
    for path in paths:
        # Historical indexes may reference runs that have since been removed.
        if not path.is_file() and not run_dir:
            continue
        progress = _read(path)
        for job in progress.get('jobs', []):
            if job_url(job.get('url')) == url:
                started = _time(progress.get('started_at') or progress.get('updated_at'))
                updated = _time(job.get('updated_at') or progress.get('updated_at'))
                matches.append(((started, updated, str(path)), path.parent, progress, job))
    if not matches:
        raise ValueError('No saved direct-submit run matches this job URL. Use --run-dir for a custom run.')
    _, directory, progress, job = max(matches, key=lambda row: row[0])
    return directory.resolve(), progress, job


def _copy(data, destination, name):
    destination.mkdir(parents=True, exist_ok=True)
    expected = hashlib.sha256(data).digest()
    stem = Path(name).stem
    temporary = None
    try:
        for number in range(10000):
            target = destination / (name if number == 0 else f'{stem} ({number}).pdf')
            if target.exists() or target.is_symlink():
                if not target.is_symlink() and target.is_file() and hashlib.sha256(target.read_bytes()).digest() == expected:
                    return target, False
                continue
            if temporary is None:
                fd, temporary = tempfile.mkstemp(prefix='.jobrobo-resume-', dir=destination)
                with os.fdopen(fd, 'wb') as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
            try:
                # Publish the complete file without replacing an existing destination.
                os.link(temporary, target)
                return target, True
            except FileExistsError:
                continue
        raise ValueError('Too many conflicting destination filenames')
    finally:
        if temporary is not None:
            os.unlink(temporary)


def copy_resume(url, *, run_dir=None, destination=None, config_dir=REPO / 'config'):
    normalized = job_url(url)
    if not normalized:
        raise ValueError('Provide a valid public HTTPS job URL')
    directory, progress, job = _select(normalized, run_dir, config_dir)
    report_value = job.get('preparation_report')
    if not report_value:
        raise ValueError(f'Selected run has no saved resume preparation report: {directory}')
    report_path = _path(report_value)
    report = _read(report_path)
    if not any(job_url(report.get(key)) == normalized for key in ('url', 'input_url', 'resolved_url')):
        raise ValueError('Preparation report does not match the requested job URL')
    resume = report.get('resume') or {}
    attachment = report.get('attachment') or {}
    if not resume.get('pdf') or not resume.get('pdf_sha256'):
        raise ValueError(f'Selected run has no saved optimized PDF: {directory}')
    source = _path(resume['pdf'])
    if source.suffix.lower() != '.pdf':
        raise ValueError('Saved resume artifact is not a PDF')
    data = source.read_bytes()
    sha256 = hashlib.sha256(data).hexdigest()
    for label, expected in [('resume', resume['pdf_sha256']), ('run', job.get('resume_sha256')),
                            ('attachment', attachment.get('sha256'))]:
        if expected and sha256 != expected:
            raise ValueError(f'PDF SHA-256 does not match the saved {label}: {source}')
    if not data.startswith(b'%PDF-'):
        raise ValueError(f'Saved artifact does not contain a PDF header: {source}')
    name = attachment.get('name') or job.get('resume_name')
    if (not isinstance(name, str) or not name.lower().endswith('.pdf') or name in {'.', '..'}
            or '/' in name or '\\' in name or re.search(r'[\x00-\x1f\x7f]', name)):
        raise ValueError('Missing or invalid recorded PDF upload filename')
    target, copied = _copy(data, _path(destination or Path.home() / 'Downloads'), name)
    return {'url': normalized, 'run_id': progress.get('run_id'), 'run_dir': str(directory),
            'application_status': job.get('status'), 'source': str(source.resolve()),
            'destination': str(target.resolve()), 'pdf_sha256': sha256, 'copied': copied}

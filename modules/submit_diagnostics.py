"""Small reproducibility record; never records credentials or full config."""
import hashlib
import importlib.metadata
from pathlib import Path
import platform
import subprocess
from urllib.parse import urlsplit

from .direct_careers_apply import literal_config


def runtime_metadata(config_dir):
    root = Path(__file__).resolve().parents[1]
    sources = ['direct_apply.py','modules/submit_runner.py','modules/submit_state.py',
               'modules/generic_submit.py','modules/generic_prepare.py','modules/generic_form_snapshot.js',
               'modules/portal_outcomes.py','modules/submit_history.py','modules/captcha_solver.py',
               'scripts/captcha_solve.py','modules/pdf_render.py','modules/generic_inputs.py',
               'modules/external_apply.py','modules/manual_tabs.py','modules/generic_form.js',
               'modules/submit_diagnostics.py']
    hashes = {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sources if (root/name).is_file()}
    try:
        revision = subprocess.run(['git','rev-parse','HEAD'],cwd=root,capture_output=True,
                                  text=True,timeout=3,check=True).stdout.strip()
    except (OSError,subprocess.SubprocessError):revision = None
    dependencies = {}
    for name in ['selenium','pdfplumber','pypdfium2','openai']:
        try:dependencies[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:dependencies[name] = 'unavailable'
    path = Path(config_dir)/'secrets.py'
    try:settings = literal_config(path) if path.is_file() else {}
    except (OSError,ValueError,SyntaxError):settings = {}
    try:host = urlsplit(settings.get('llm_api_url') or '').hostname
    except ValueError:host = None
    return {'git_revision':revision,'source_sha256':hashes,'python':platform.python_version(),
            'dependencies':dependencies, 'draft_model':settings.get('llm_model'),
            'draft_provider_host':host, 'egress_ip':'not_measured'}

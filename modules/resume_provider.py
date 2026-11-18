"""Resume-only provider selection, credentials and bounded cross-worker requests."""
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import threading
import time

VENICE_URL = 'https://api.venice.ai/api/v1'
OPENAI_URL = 'https://api.openai.com/v1'
VENICE_MODEL = 'deepseek-v4-1-flash'
_overrides = ContextVar('resume_provider_overrides', default={})
_catalogs, _auth_failures = {}, {}
_catalog_lock = threading.Lock()


class ResumeProviderError(RuntimeError):
    def __init__(self, provider, status, retry_after=None):
        self.status_code = status
        from types import SimpleNamespace
        self.response = SimpleNamespace(headers={'retry-after': retry_after} if retry_after is not None else {})
        super().__init__(f'Resume provider {provider} request failed (HTTP {status}); check its key, access or balance')


def _safe_http_error(error, selected):
    status = getattr(error, 'status_code', None)
    retry_after = getattr(getattr(error, 'response', None), 'headers', {}).get('retry-after')
    return ResumeProviderError(selected['provider'], status, retry_after) if isinstance(status, int) else error


def add_cli_arguments(parser):
    parser.add_argument('--resume-provider', choices=('openai', 'venice'), default=None,
                        help='Resume generation provider; overrides saved optimizer JSON for this run')
    parser.add_argument('--resume-model', default=None, help='Resume model ID for the selected provider')
    parser.add_argument('--resume-reasoning', choices=('none', 'low', 'medium', 'high', 'max', 'xhigh'),
                        default=None, help='Resume reasoning effort (must be supported by the selected model)')


def cli_overrides(args):
    return {key: value for key, value in {
        'provider': getattr(args, 'resume_provider', None),
        'model': getattr(args, 'resume_model', None),
        'reasoning': getattr(args, 'resume_reasoning', None),
    }.items() if value is not None}


@contextmanager
def override_settings(values):
    token = _overrides.set(dict(_overrides.get() if values is None else values))
    try:
        yield
    finally:
        _overrides.reset(token)


def apply_overrides(config):
    config = deepcopy(config)
    values = _overrides.get()
    if 'provider' in values:
        config['rewrite_provider'] = values['provider']
    provider = config.get('rewrite_provider', 'openai')
    if 'model' in values:
        config['rewrite_venice_model' if provider == 'venice' else 'rewrite_model'] = values['model']
    if 'reasoning' in values:
        config['rewrite_reasoning_effort'] = values['reasoning']
    return config


def settings(config):
    provider = config.get('rewrite_provider', 'openai')
    if provider not in {'venice', 'openai'}:
        raise ValueError('rewrite_provider must be openai or venice')
    model = config.get('rewrite_venice_model', VENICE_MODEL) if provider == 'venice' else config.get('rewrite_model', 'gpt-4o')
    if not isinstance(model, str) or not model.strip():
        raise ValueError('Resume model must be a nonempty string')
    effort = config.get('rewrite_reasoning_effort', 'none')
    if effort not in {'none', 'low', 'medium', 'high', 'max', 'xhigh'}:
        raise ValueError('Invalid resume reasoning effort')
    if provider == 'openai' and effort == 'max':
        raise ValueError('OpenAI resume reasoning does not support max; use a supported OpenAI effort')
    maximum = config.get('rewrite_api_concurrency', 4)
    if type(maximum) is not int or not 1 <= maximum <= 16:
        raise ValueError('rewrite_api_concurrency must be an integer from 1 to 16')
    return {'provider': provider, 'model': model.strip(), 'reasoning': effort,
            'base_url': VENICE_URL if provider == 'venice' else OPENAI_URL,
            'concurrency': maximum}


def _credentials(selected):
    from dotenv import dotenv_values
    # Read only the repository dotenv; never provision credentials remotely.
    values = dotenv_values(Path(__file__).resolve().parents[1] / '.env', interpolate=False)
    name = 'VENICE_API_KEY' if selected['provider'] == 'venice' else 'OPENAI_API_KEY'
    key = os.environ[name] if name in os.environ else values.get(name)
    if not key or not key.strip():
        raise ValueError(f'Missing local {name}; no resume API request made')
    if selected['provider'] == 'venice':
        endpoint = os.environ.get('VENICE_BASE_URL') or values.get('VENICE_BASE_URL') or VENICE_URL
        if endpoint.rstrip('/') != VENICE_URL:
            raise ValueError('VENICE_BASE_URL must be https://api.venice.ai/api/v1')
    return key.strip()


def make_client(config):
    from openai import OpenAI
    selected = settings(config)
    return OpenAI(api_key=_credentials(selected), base_url=selected['base_url'], max_retries=0)


def _identity(client, selected):
    # Hash the credential for in-memory isolation, never log or persist it.
    return (selected['provider'], selected['base_url'], hashlib.sha256(client.api_key.encode()).hexdigest())


def preflight(client, selected):
    identity = _identity(client, selected)
    with _catalog_lock:
        if identity in _auth_failures:
            raise _auth_failures[identity]
        if identity not in _catalogs:
            try:
                response = client.with_options(timeout=15, max_retries=0).models.list()
                _catalogs[identity] = {model.id: model for model in response.data}
            except Exception as error:
                safe = _safe_http_error(error, selected)
                if getattr(error, 'status_code', None) in {401, 402, 403}:
                    _auth_failures[identity] = safe
                raise safe from None
        if selected['provider'] != 'venice':
            return
        model = _catalogs[identity].get(selected['model'])
        if model is None:
            raise ValueError('Selected resume model is not in the Venice catalog')
        spec = getattr(model, 'model_spec', {}) or {}
        caps = spec.get('capabilities', {})
        if spec.get('offline'):
            raise ValueError('Selected Venice resume model is offline')
        if not caps.get('supportsResponseSchema'):
            raise ValueError('Selected Venice resume model does not support response schemas')
        if selected['reasoning'] not in caps.get('reasoningEffortOptions', []):
            raise ValueError('Selected Venice resume model does not support the requested reasoning effort')
        return spec


@contextmanager
def request_slot(selected, config, timeout, estimated_tokens):
    """Share concurrency and dispatch pacing across CLI processes, not per job."""
    import fcntl
    from modules.search_history import file_lock
    root = Path.home() / 'Library/Caches/jobrobo/resume-api' / selected['provider']
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    deadline = time.monotonic() + timeout
    slot = None
    try:
        while slot is None:
            if time.monotonic() >= deadline:
                raise TimeoutError('Resume API shared-slot wait exceeded request timeout')
            for index in range(selected['concurrency']):
                handle = (root / f'slot-{index}.lock').open('a+b')
                try:
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    slot = handle
                    break
                except BlockingIOError:
                    handle.close()
            if slot is None:
                time.sleep(.05)
        while True:
            try:
                with file_lock(root / 'pacing.lock'):
                    state = root / 'pacing.json'
                    try:
                        next_at = float(json.loads(state.read_text()).get('next_at', 0))
                    except (OSError, ValueError, TypeError):
                        next_at = 0
                    now = time.time()
                    delay = next_at - now
                    if delay <= 0:
                        rpm = config.get('rewrite_requests_per_minute', 60)
                        tpm = config.get('rewrite_tokens_per_minute', 120000)
                        state.write_text(json.dumps({'next_at': now + max(60 / rpm, 60 * estimated_tokens / tpm)}))
                        break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Resume API shared pacing lock wait exceeded request timeout') from None
                time.sleep(.05)
                continue
            if time.monotonic() + delay >= deadline:
                raise TimeoutError('Resume API shared rate wait exceeded request timeout')
            time.sleep(min(.1, delay))
        yield max(.01, deadline - time.monotonic())
    finally:
        if slot is not None:
            fcntl.flock(slot, fcntl.LOCK_UN)
            slot.close()


def complete(client, config, *, timeout=45, **kwargs):
    selected = settings(config)
    preflight(client, selected)
    kwargs['model'] = selected['model']
    if selected['provider'] == 'venice':
        kwargs.pop('max_tokens', None)
        kwargs['max_completion_tokens'] = config.get('rewrite_max_output_tokens', 6000)
        kwargs['extra_body'] = {'reasoning_effort': selected['reasoning'],
                                'venice_parameters': {'include_venice_system_prompt': False,
                                                      'enable_web_search': 'off'}}
    elif selected['model'].startswith(('gpt-5', 'gpt-6', 'o1', 'o3', 'o4')):
        kwargs['max_completion_tokens'] = kwargs.pop('max_tokens', config.get('rewrite_max_output_tokens', 6000))
        kwargs['extra_body'] = {'reasoning_effort': selected['reasoning']}
    else:
        kwargs.setdefault('max_tokens', config.get('rewrite_max_output_tokens', 6000))
    # Schema enums can be large even for a short question: include the entire
    # request, not only messages, when pacing workers against the token budget.
    tokens = len(json.dumps(kwargs, ensure_ascii=False).encode()) + config.get('rewrite_max_output_tokens', 6000)
    with request_slot(selected, config, timeout, tokens) as remaining:
        # Another worker may have received a permanent auth rejection while
        # this request was waiting for its shared slot.
        identity = _identity(client, selected)
        if identity in _auth_failures:
            raise _auth_failures[identity]
        try:
            return client.with_options(timeout=remaining, max_retries=0).chat.completions.create(**kwargs)
        except Exception as error:
            safe = _safe_http_error(error, selected)
            if getattr(error, 'status_code', None) in {401, 402, 403}:
                with _catalog_lock:
                    _auth_failures[identity] = safe
            raise safe from None


def check_configuration(config=None):
    """Cheap auth/capability check once per provider credential in this process."""
    if config is None:
        from .config_loader import peek_runtime_config
        config = peek_runtime_config()
    selected = settings(config)
    from .resume_provider_prompts import prompt_info
    selected_prompt = prompt_info(config)
    client = make_client(config)
    try:
        preflight(client, selected)
    except Exception as error:
        status = getattr(error, 'status_code', None)
        if status:
            raise ValueError(f"Resume provider {selected['provider']} preflight failed (HTTP {status}); check its key, access or balance") from None
        raise
    finally:
        client.close()
    print(f"[Resume API] Ready: provider={selected['provider']}, model={selected['model']}, reasoning={selected['reasoning']}, shared concurrency={selected['concurrency']}, prompt={Path(selected_prompt['path']).name} ({selected_prompt['sha256'][:12]})", flush=True)
    return selected

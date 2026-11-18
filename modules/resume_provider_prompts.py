"""Provider-specific resume drafting prompts and a short-ID Venice transport."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROMPTS = {'openai': 'config/prompts/resume_bullets.txt',
                   'venice': 'config/prompts/resume_bullets_venice.txt'}


def prompt_path(config, root=None):
    provider = config.get('rewrite_provider', 'openai')
    if provider not in DEFAULT_PROMPTS:
        raise ValueError('Unknown resume prompt provider')
    value = config.get(f'rewrite_{provider}_prompt_path', DEFAULT_PROMPTS[provider])
    if not isinstance(value, str) or not value.strip():
        raise ValueError('Resume prompt path must be a nonempty string')
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (Path(root or ROOT) / path).resolve()


def prompt_info(config):
    path = prompt_path(config)
    text = path.read_text(encoding='utf-8')
    if not text.strip():
        raise ValueError('Resume bullet prompt is empty')
    return {'provider': config.get('rewrite_provider', 'openai'), 'path': str(path),
            'sha256': hashlib.sha256(text.encode()).hexdigest(), 'text': text}


def prompt_matches_report(report, config):
    saved = report.get('bullet_prompt')
    if not saved:
        # Historical OpenAI artifacts predate prompt manifests. Venice's new
        # prompt/transport must not reuse an artifact from its previous flow.
        return config.get('rewrite_provider', 'openai') != 'venice'
    active = prompt_info(config)
    return all(saved.get(key) == active[key] for key in ('provider', 'sha256'))


def _clean_context(value):
    """Keep source/JD evidence while removing opaque routing tokens from prose."""
    if isinstance(value, dict):
        return {key: _clean_context(item) for key, item in value.items()
                if key not in {'bullet_id', 'source_text_hash', 'source_sha256', 'jd_sha256',
                               'experience_id', 'requested_bullet_ids', 'retry_reasons'}}
    if isinstance(value, list):
        return [_clean_context(item) for item in value]
    return value


def venice_request(payload):
    wire = _clean_context(payload)
    wire['candidate_count'] = 3
    wire['requested_bullets'] = []
    mapping = {}
    properties = {}
    for index, original in enumerate(payload['requested_bullets'], 1):
        slot = f'b{index}'
        mapping[slot] = original
        row = _clean_context(original)
        row['slot'] = slot
        estimate = max(24, int(original.get('soft_character_estimate', 130)))
        # Guidance uses the SAME width band for all candidates. The historical
        # 55%-word compact backup could not satisfy an 80%-width hard floor.
        targets = [max(20, round(estimate * ratio)) for ratio in (.95, .90, .85)]
        row['candidate_character_targets'] = targets
        row['candidate_word_budgets'] = [max(8, round(length / 5.5)) for length in targets]
        row['target_min_characters'] = max(18, round(estimate * .80))
        row['target_characters'] = targets[0]
        row['target_max_characters'] = max(targets[0], round(estimate * 1.08))
        row['alternative_character_targets'] = targets[1:]
        reason = payload.get('retry_reasons', {}).get(original['bullet_id'])
        if reason:
            row['repair_reason'] = reason
            row['repair_instruction'] = ('Repair the previous candidate. Keep its strongest JD contribution; '
                'remove a whole lower-priority phrase if too wide, or add a short useful JD phrase if too short.')
        wire['requested_bullets'].append(row)
        text = {'type': 'string', 'minLength': max(18, round(estimate * .65)),
                'maxLength': max(30, round(estimate * 1.10))}
        fields = {name: deepcopy(text) for name in ('primary', 'alternative', 'compact')}
        properties[slot] = {'type': 'object', 'properties': fields,
                            'required': list(fields), 'additionalProperties': False}
    # Keep policy/evidence instructions, replace the old conflicting format and
    # alternative-length guidance for this provider's transport only.
    wire.setdefault('acceptance_criteria', {}).update(
        alternatives='Return primary, alternative and compact for each exact slot; each is a complete professional accomplishment.',
        fit='Aim for candidate_character_targets (95%, 90%, 85%). All three must satisfy the measured 80% minimum and fit one line. Character counts guide drafting; actual glyph width decides acceptance. Never pad or truncate.',
        output='Return only the required JSON object with one property per requested slot. No IDs, hashes, commentary or placeholders.')
    schema = {'type': 'json_schema', 'json_schema': {'name': 'resume_venice_bullets', 'strict': True,
        'schema': {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}}}
    return wire, schema, mapping


def usable_text(value):
    if not isinstance(value, str) or len(value.split()) < 7:
        return ''
    if re.search(r'\b(?:no (?:alternative|bullet)|there is no|how do (?:i|you) love|synthetic test|'
                 r'cannot (?:provide|rewrite)|as an ai|placeholder|not applicable)\b', value, re.I):
        return ''
    return value


def normalize_venice_response(response, payload, mapping):
    raw = response.choices[0].message.content
    class UniqueObject(dict):
        def __init__(self, pairs):
            super().__init__()
            self.duplicates = set()
            for key, value in pairs:
                if key in self:
                    self.duplicates.add(key)
                self[key] = value
    parsed = json.loads(raw, object_pairs_hook=UniqueObject)
    if not isinstance(parsed, dict):
        raise ValueError('Venice bullet response must be an object keyed by requested slots')
    results = []
    for slot, original in mapping.items():
        row = parsed.get(slot)
        if slot in parsed.duplicates or not isinstance(row, dict) or row.duplicates:
            continue  # Missing/invalid slots stay missing, never assigned by position.
        results.append(dict(bullet_id=original['bullet_id'], source_text_hash=original['source_text_hash'],
            status='rewritten', rewritten_text=usable_text(row.get('primary')),
            alternative_texts=[usable_text(row.get('alternative')), usable_text(row.get('compact'))],
            matched_jd_spans=[], preserved_fact_anchors=[], blocked_reason=None,
            change_reason='Venice candidate bound to explicit request slot; normal content and layout checks apply'))
    normalized = {'experience_id': payload['experience_id'], 'results': results}
    # Preserve the exact response and explicit routing map alongside normalized
    # audit content. No inferred IDs/hashes or positional recovery is permitted.
    response.resume_wire_content = raw
    response.resume_wire_mapping = {slot: {'bullet_id': row['bullet_id'], 'source_text_hash': row['source_text_hash']}
                                    for slot, row in mapping.items()}
    response.choices[0].message.content = json.dumps(normalized, ensure_ascii=False)
    return response


def stage_completion(client, config, stage, payload, system, timeout):
    from .resume_provider import complete
    from .resume_all_bullets import provider_response_format, completion_options, validate_options
    options = validate_options(config, config.get('optimization_mode', 'full'))
    mapping = None
    if stage == 'bullets' and config.get('rewrite_provider', 'openai') == 'venice':
        wire, schema, mapping = venice_request(payload)
    else:
        wire, schema = payload, provider_response_format(stage, payload)
    response = complete(client, config, timeout=timeout, **completion_options(options),
        response_format=schema, messages=[{'role': 'system', 'content': system},
                                        {'role': 'user', 'content': json.dumps(wire, ensure_ascii=False)}])
    return normalize_venice_response(response, payload, mapping) if mapping is not None else response

"""Pure CLI company input, scoped queries and pre-application employer checks."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import unicodedata


def normalize_name(value):
    if not isinstance(value, str):
        return ''
    value = unicodedata.normalize('NFKC', value).casefold()
    value = ' '.join(re.findall(r'[^\W_]+', value, re.UNICODE))
    return re.sub(r'(?:\s+(?:incorporated|inc|llc|ltd|corporation|corp))+$', '', value).strip()


def _name(value):
    if (not isinstance(value, str) or not value.strip() or len(value) > 200
            or any(ord(c) < 32 for c in value) or not normalize_name(value)):
        raise ValueError('Company names and aliases must be nonempty text, at most 200 characters, without control characters')
    return ' '.join(unicodedata.normalize('NFKC', value).split())


def load_scope(path=None, companies=(), *, batch_size=10, strict=False):
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError('Company batch size must be a positive integer')
    entries = []
    if path is not None:
        data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
        entries = data.get('companies') if isinstance(data, dict) else data
        if not isinstance(entries, list) or not entries:
            raise ValueError('Company JSON must contain a nonempty companies array or be a nonempty name array')
    entries = [*entries, *companies]
    if not entries:
        raise ValueError('Company options require --companies-file or --company')
    targets = []
    seen = {}
    for entry in entries:
        if isinstance(entry, str):
            name, aliases = _name(entry), []
        elif isinstance(entry, dict):
            name = _name(entry.get('name'))
            aliases = entry.get('aliases', [])
            if not isinstance(aliases, list):
                raise ValueError('Company aliases must be an array of names')
            aliases = [_name(a) for a in aliases]
        else:
            raise ValueError('Each company entry must be a name or an object with name and aliases')
        key = normalize_name(name)
        if key not in seen:
            seen[key] = len(targets)
            targets.append({'name': name, 'aliases': []})
        target = targets[seen[key]]
        known = {normalize_name(target['name']), *(normalize_name(a) for a in target['aliases'])}
        for alias in aliases:
            if normalize_name(alias) not in known:
                target['aliases'].append(alias)
                known.add(normalize_name(alias))
    return {'companies': targets, 'batch_size': batch_size, 'strict': bool(strict)}


def expand_specs(specs, scope):
    if not scope:
        return specs
    result = []
    companies = scope['companies']
    batches = [companies[i:i+scope['batch_size']] for i in range(0, len(companies), scope['batch_size'])]
    for spec in specs:
        for index, batch in enumerate(batches, 1):
            names = [c['name'] for c in batch]
            identity = {'base': spec.query_id, 'scope': scope, 'batch': index}
            digest = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()[:16]
            suffix = ' Only return jobs whose hiring employer is one of these companies: ' + json.dumps(names, ensure_ascii=False) + '.'
            keywords = ' OR '.join('"'+name.replace('"', ' ')+'"' for name in names)
            result.append(replace(spec, query_id=f'{spec.query_id}:companies:{digest}',
                query_text=spec.query_text+suffix,
                classic_query=f'({spec.classic_query}) AND ({keywords})',
                company_scope={**deepcopy(scope), 'batch_names': names, 'batch_index': index, 'batch_count': len(batches)}))
    return result


def employer_allowed(spec, employer):
    scope = spec.company_scope
    if not scope or not scope['strict']:
        return True
    observed = normalize_name(employer)
    if not observed:
        return False
    matches = [c for c in scope['companies'] if observed in
               {normalize_name(c['name']), *(normalize_name(a) for a in c['aliases'])}]
    return len(matches) == 1

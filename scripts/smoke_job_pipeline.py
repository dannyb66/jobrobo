"""Repeat public GET discovery and official ATS verification without LinkedIn or applications."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import search
from modules.job_pipeline.sources import SOURCE_URLS, discover_source, domain_of, stable_id
from modules.job_pipeline.careers import verify_company

OUT = ROOT / "data/job_pipeline/smoke"


def save(name, result):
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / name).write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')


def discover(source):
    result = discover_source(source, {'request_timeout': 10}, limit=3)
    save(source + '-discovery.json', result)
    return {'source': source, 'count': len(result['records']), 'companies': [row['name'] for row in result['records']],
            'errors': [row['code'] for row in result['errors']], 'complete': result['complete']}


def verify(entry):
    name, website = entry
    domain = domain_of(website)
    company = {'id': stable_id('company', domain), 'name': name, 'domain': domain, 'website': website,
               'careers_url': website + '/careers', 'sources': [], 'employee_count': None,
               'funding_stage': None, 'aliases': []}
    result = verify_company(company, search)
    save(name.lower() + '-careers.json', result)
    return {'company': name, 'count': len(result['records']), 'eligible': sum(row['eligible'] for row in result['records']),
            'status': result['status'], 'complete': result['complete'], 'errors': [row['code'] for row in result['errors']]}


if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=4) as pool:
        sources = list(pool.map(discover, SOURCE_URLS))
    with ThreadPoolExecutor(max_workers=3) as pool:
        careers = list(pool.map(verify, [('Modal', 'https://modal.com'), ('Baseten', 'https://www.baseten.co'),
                                       ('Braintrust', 'https://www.braintrust.dev')]))
    summary = {'observed_at': datetime.now(timezone.utc).isoformat(), 'read_only': True, 'sources': sources, 'careers': careers}
    save('adapter-summary.json', summary)
    print(json.dumps(summary, indent=2))

"""Build an opt-in classified catalog from saved evidence; never edits v1."""
import argparse
import copy
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDUSTRIES = ['ai_agents', 'infrastructure_devtools', 'enterprise_software', 'fintech', 'security', 'robotics_industrial', 'healthcare', 'consumer', 'other', 'unknown']
TECH = ['backend_distributed_systems', 'kubernetes_sre', 'ai_agents_rag', 'full_stack', 'ml_infrastructure', 'robotics_software']
STATUSES = ['research', 'qualified_opening_found', 'watchlist', 'identity_needs_verification', 'deprioritized']
# Primary vertical before enabling technology: a bank using AI remains fintech.
RULES = [
 ('healthcare', r'healthcare|health care|clinical|therapeutic|patient|medical|veterinary|biotech|HEALTHCARE & BIO'),
 ('security', r'cybersecurity|security platform|security software|application security|vulnerability management|onchain security|^SECURITY$|data security'),
 ('fintech', r'FINTECH & CRYPTO|financial services|financial infrastructure|financial institution|financial crime|finance automation|modern finance|investment advisor|payments? infrastructure|payment processors|payroll|underwriting|commercial insurance|mortgage|blockchain|web3|bitcoin|trading/client'),
 ('robotics_industrial', r'robotics|autonom(y|ous).*vehicle|industrial vehicles|drone company|defense technology|aviation|DEFENSE, HARDWARE & INDUSTRY|PCB.design|ground station|marine|undersea|manufacturing|electronics|agriculture|construction.*logistics|transportation and logistics'),
 ('infrastructure_devtools', r'developer (platform|tool)|developer experience|observability|telemetry|distributed systems|storage system|data lakehouse|streaming/distributed|query/data systems|inference|MLOps|ML infrastructure|ML infra|research infrastructure|agent infrastructure|Python/AI app.platform|data/AI platform|edge/distributed|VMware for GPUs'),
 ('ai_agents', r'AI research|general.purpose artificial intelligence|AI agent|agentic|AI copilot|AI coworker|enterprise AI|continual.learning AI|^AI$|generative AI|AI platform|AI.native|AI software'),
 ('consumer', r'communities and friend groups|non.native English|user.generated links|rented a house|tennis|pickleball|writing tools authors|prediction markets|streaming/platform|commerce'),
 ('enterprise_software', r'SOFTWARE & MARKETPLACES|revenue excellence|scheduling platform|ERP modernization|SMS revenue|enterprise software|sales insights|product engineering|product platform|internal platforms|software architecture'),
 ('other', r'education|school|universit|assessment platform|pedagog|consulting|consultant')]
TECH_RULES = [
 ('backend_distributed_systems', r'backend|distributed (systems|services)|microservices|storage system|streaming|platform engineer|platform/backend|serverless|API gateway'),
 ('kubernetes_sre', r'kubernetes|\bk8s\b|\bSRE\b|site reliability|DevOps|Dev Ops|DevSecOps'),
 ('ai_agents_rag', r'AI agent|agentic|agent infrastructure|agent harness|\bRAG\b|retrieval|AI coworker'),
 ('full_stack', r'full.stack|frontend.*backend|backend.*frontend|React|TypeScript'),
 ('ml_infrastructure', r'ML infrastructure|ML infra|ML systems|MLOps|ML Ops|inference|model serving|machine learning models to production|research infrastructure|ML platform|AI/ML infrastructure'),
 ('robotics_software', r'robotics|autonomy|autonomous flight|drone company|machine perception')]
# Reviewed exceptions prevent role-stack words from becoming company industries.
INDUSTRY_REVIEW = {
 'AirOps':('enterprise_software','content engineering platform'),
 'Axiamatic':('enterprise_software','ERP modernization'),
 'Braintrust':('infrastructure_devtools','operating system for engineers'),
 'Discord':('consumer','communities and friend groups'),
 'Fable Security':('security','human risk platform'),
 'JustPark':('consumer','parking experience'),
 'OpenAI':('ai_agents','AI research and deployment'),
 'Postscript':('enterprise_software','SMS revenue platform'),
 'Shield AI':('robotics_industrial','protect service members'),
 'Tether':('unknown',None),
}
NOTE_INDUSTRY_ALLOWED = {'Amazon / AWS','Cloudflare','Cohere','Confluent','CVS Health / Aetna','Databricks','Datadog','Disney','Elastic','GE HealthCare','Glean','MongoDB','NVIDIA','Palo Alto Networks','Ramp','Snowflake','Stripe','Target','Together AI','UnitedHealth Group / Optum','Walmart / Global Tech','Charles Schwab'}
CATEGORY = {'FINTECH & CRYPTO':'fintech', 'AI':'ai_agents', 'SECURITY':'security', 'DEFENSE, HARDWARE & INDUSTRY':'robotics_industrial', 'HEALTHCARE & BIO':'healthcare', 'SOFTWARE & MARKETPLACES':'enterprise_software'}

def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def pointer(obj, ptr):
    for k in ptr.strip('/').split('/'):
        if k: obj = obj[int(k)] if isinstance(obj, list) else obj[k]
    return obj

def sources_for(company, sources, manifests):
    evidence = []
    for p in company['provenance']:
        root = sources[p['source_id']]
        r = pointer(root, p['record_pointer'])
        observed = r.get('checked_at') or (root.get('checked_at') or root.get('created_at') if isinstance(root, dict) else None)
        if r.get('sources'): observed = r['sources'][0].get('observed_at') or observed
        fields = [('description', r.get('description')), ('category', r.get('category')), ('acquisition.note', r.get('acquisition', {}).get('note'))]
        # Role titles support only technical-domain tags, not company industries.
        fields += [('roles.title', '; '.join(x['title'] for x in r.get('roles', [])))]
        if isinstance(r.get('ownership_evidence'), str): fields += [('ownership_evidence', r['ownership_evidence'])]
        for field, text in fields:
            if not text or text.strip() == 'A16Z SPEEDRUN STARTUPS': continue
            if 'We help the daring build legendary companies' in text or 'Sequoia-backed company since' in text: continue
            evidence.append({'source_id':p['source_id'], 'record_pointer':p['record_pointer'], 'field':field, 'source_observed_at':observed, 'text':text})
    return evidence

def excerpt(e, pattern=None):
    result = {k:v for k,v in e.items() if k!='text'}
    m = re.search(pattern, e['text'], re.I) if pattern else None
    start = max(0, m.start()-80) if m else 0
    result['excerpt'] = e['text'][start:start+400]
    return result

def classify(c, evidence, now):
    hold = bool(c.get('identity_requires_review'))
    industry = {'value':'unknown', 'confidence':'unknown', 'evidence':[], 'reason':'Insufficient specific saved industry evidence; no name-only inference.'}
    tags = []
    if not hold:
        for e in evidence:
            if e['field']=='category' and e['text'] in CATEGORY:
                industry = {'value':CATEGORY[e['text']], 'confidence':'medium', 'evidence':[excerpt(e)], 'reason':'Mapped saved source category; not freshly verified.'}; break
        if industry['value']=='unknown':
            for value, pattern in RULES:
                found = next((e for e in evidence if e['field']!='roles.title' and (e['field']!='acquisition.note' or c['name'] in NOTE_INDUSTRY_ALLOWED) and re.search(pattern,e['text'],re.I)), None)
                if found:
                    industry = {'value':value, 'confidence':'medium' if found['field']=='description' else 'low', 'evidence':[excerpt(found,pattern)], 'reason':'Conservative text-rule inference from saved source; primary vertical takes precedence over enabling technology.'}; break
        if c['name'] in INDUSTRY_REVIEW:
            value, pattern = INDUSTRY_REVIEW[c['name']]
            found = next((e for e in evidence if pattern and re.search(pattern,e['text'],re.I)),None)
            industry = {'value':value,'confidence':'medium' if found else 'unknown','evidence':[excerpt(found,pattern)] if found else [],'reason':'Reviewed saved product description; role-stack words do not establish company industry.' if found else 'Saved text describes a role, not the employer industry; research required.'}
        for tag, pattern in TECH_RULES:
            found = next((e for e in evidence if re.search(pattern,e['text'],re.I)),None)
            if found: tags.append({'value':tag, 'confidence':'medium', 'evidence':[excerpt(found,pattern)]})
    else: industry['reason']='Existing identity hold preserved; classify only after intended employer is confirmed.'
    status = 'identity_needs_verification' if hold else ('watchlist' if 26 in c['source_tasks'] else 'research')
    return {'classified_at_utc':now, 'method':'saved_source_rules_v1', 'industry':industry,
            'tech_fit':{'assessment':'domain_overlap_only' if tags else 'not_assessed', 'tags':tags, 'reason':'Technical-domain signals only; no resume, seniority, location, sponsorship or live vacancy qualification.'},
            'status':{'value':status,'scope':'company_next_action','reason': 'Preserved explicit identity hold.' if hold else ('Existing Task 26 priority watchlist membership; not a new hiring or application decision.' if status=='watchlist' else 'Research exact employer, current roles and candidate fit before action.'), 'basis_provenance_indices':[i for i,p in enumerate(c['provenance']) if p['task_id']==26] if status=='watchlist' else list(range(len(c['provenance'])))} }

def enum(values):return {'type':'string','enum':values}
def object_schema(properties,required=None):return {'type':'object','properties':properties,'required':required or list(properties),'additionalProperties':False}
def make_schema():
    evidence=object_schema({'source_id':{'type':'string'},'record_pointer':{'type':'string'},'field':enum(['description','category','acquisition.note','roles.title','ownership_evidence']),'source_observed_at':{'type':['string','null']},'excerpt':{'type':'string','minLength':1}})
    public_evidence=object_schema({'url':{'type':'string','format':'uri'},'title':{'type':'string'},'excerpt':{'type':'string','minLength':1},'checked_at_utc':{'type':'string','format':'date-time'}})
    ev={'type':'array','items':{'anyOf':[evidence,public_evidence]}}
    industry=object_schema({'value':enum(INDUSTRIES),'confidence':enum(['high','medium','low','unknown']),'evidence':ev,'reason':{'type':'string'}})
    tag=object_schema({'value':enum(TECH),'confidence':enum(['high','medium','low']),'evidence':dict(ev,minItems=1)})
    cl=object_schema({'classified_at_utc':{'type':'string','format':'date-time'},'method':enum(['saved_source_rules_v1','public_source_review_v1']),'industry':industry,'tech_fit':object_schema({'assessment':enum(['domain_overlap_only','not_assessed','no_supported_tag']),'tags':{'type':'array','items':tag},'reason':{'type':'string'}}),'status':object_schema({'value':enum(STATUSES),'scope':{'const':'company_next_action'},'reason':{'type':'string'},'basis_provenance_indices':{'type':'array','items':{'type':'integer','minimum':0},'uniqueItems':True}})})
    cl['properties']['research_review']=object_schema({'identity':enum(['confirmed','ambiguous']),'rationale':{'type':'string'},'limitations':{'type':'string'},'sources':{'type':'array','items':public_evidence},'checked_at_utc':{'type':'string','format':'date-time'}})
    return {'$schema':'https://json-schema.org/draft/2020-12/schema','title':'Company catalog v2 (opt-in, non-executing)','type':'object','required':['schema_version','derived_from','classification_policy','classification_counts','companies'],'properties':{'schema_version':{'const':2},'derived_from':object_schema({'path':{'const':'data/company_names.json'},'sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'},'schema_version':{'const':1}}),'classification_policy':{'type':'object'},'classification_counts':{'type':'object'},'companies':{'type':'array','minItems':1,'items':{'type':'object','required':['name','aliases','source_tasks','provenance','classification'],'properties':{'name':{'type':'string','minLength':1},'aliases':{'type':'array','items':{'type':'string'}},'source_tasks':{'type':'array','items':{'type':'integer'}},'provenance':{'type':'array','minItems':1,'items':{'type':'object'}},'classification':cl},'additionalProperties':True}}},'additionalProperties':True}

def validate(old,new):
    import jsonschema
    jsonschema.Draft202012Validator(make_schema(),format_checker=jsonschema.FormatChecker()).validate(new)
    assert len(new['companies'])==len(old['companies'])==292
    assert len({unicodedata.normalize('NFKC',c['name']).strip().casefold() for c in new['companies']})==292
    for a,b in zip(old['companies'],new['companies']):
        assert a=={k:v for k,v in b.items() if k!='classification'},a['name']
        cl=b['classification']; assert len({t['value'] for t in cl['tech_fit']['tags']})==len(cl['tech_fit']['tags'])
        assert (cl['industry']['value']=='unknown') == (cl['industry']['confidence']=='unknown')
        assert cl['industry']['value']=='unknown' or cl['industry']['evidence']
        assert bool(cl['tech_fit']['tags'])==(cl['tech_fit']['assessment']=='domain_overlap_only')
        assert all(i<len(b['provenance']) for i in cl['status']['basis_provenance_indices'])
        review=cl.get('research_review')
        if cl['method']=='public_source_review_v1':
            assert review is not None
            if review['identity']=='ambiguous':assert cl['industry']['value']=='unknown' and not cl['tech_fit']['tags'] and cl['status']['value']=='identity_needs_verification'
            if cl['industry']['value']!='unknown':assert review['sources']
        if b.get('identity_requires_review') and not (review and review['identity']=='confirmed'):assert cl['status']['value']=='identity_needs_verification' and not cl['tech_fit']['tags']
    for k,v in old.items():
        if k not in ('schema_version','companies'):assert new[k]==v,k
    assert new['classification_counts']==counts(new['companies'])

def counts(companies):
    return {'companies':len(companies),'industry':dict(sorted(Counter(c['classification']['industry']['value'] for c in companies).items())), 'status':dict(sorted(Counter(c['classification']['status']['value'] for c in companies).items())), 'tech_fit_tags_overlapping':dict(sorted(Counter(t['value'] for c in companies for t in c['classification']['tech_fit']['tags']).items())), 'companies_with_tech_tags':sum(bool(c['classification']['tech_fit']['tags']) for c in companies)}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');parser.add_argument('--rebuild-v2',action='store_true');args=parser.parse_args()
    p=ROOT/'data/company_names.json'; original_hash=digest(p);old=json.loads(p.read_text()); output=ROOT/'data/company_names.v2.json'
    if args.check:
        new=json.loads(output.read_text());validate(old,new);assert new['derived_from']['sha256']==original_hash
        assert json.loads((ROOT/'data/company_names.v2.schema.json').read_text())==make_schema()
        print('PASS: schema, 292 unique names, unchanged legacy data/metadata, original SHA256, counts, identity holds and tag/status invariants'); print(json.dumps(new['classification_counts'],indent=2)); return
    if output.exists() and json.loads(output.read_text()).get('classification_policy',{}).get('method')=='public_source_review_v1':
        raise SystemExit('Refusing to replace public research with initial rules. Use the research integrator and reviewed inputs.')
    assert args.rebuild_v2 or not output.exists(),'Refusing to overwrite existing v2; review and version explicitly.'
    manifests={s['source_id']:s for s in old['source_manifest']}; sources={}; evidence_manifest=[]
    for sid,s in manifests.items():
        path=Path.home()/s['path_from_user_home']; actual=digest(path)
        assert actual==s['sha256'],f'Source changed: {sid}; review before classification'
        sources[sid]=json.loads(path.read_text()); evidence_manifest.append({'source_id':sid,'sha256':actual})
    now=datetime.now(timezone.utc).isoformat();new=copy.deepcopy(old);new['schema_version']=2
    new['derived_from']={'path':'data/company_names.json','sha256':original_hash,'schema_version':1}
    new['classification_policy']={'classified_at_utc':now,'method':'saved_source_rules_v1','scope':'Offline initial enrichment from saved text; no live revalidation or application-history reconciliation. Original generated_at_utc and validation describe v1 only.','industry_precedence':[x[0] for x in RULES],'identity_holds_preserved':True,'runtime_integration':False,'source_hashes_verified':evidence_manifest,'enums':{'industry':INDUSTRIES,'tech_fit':TECH,'company_next_action':STATUSES}}
    for c in new['companies']:c['classification']=classify(c,sources_for(c,sources,manifests),now)
    new['classification_counts']=counts(new['companies']);validate(old,new)
    for path,data in [(output,new),(ROOT/'data/company_names.v2.schema.json',make_schema())]:
        with path.open('w' if args.rebuild_v2 else 'x') as f:json.dump(data,f,indent=2,ensure_ascii=False);f.write('\n')
    assert digest(p)==original_hash
    print(json.dumps(new['classification_counts'],indent=2))
if __name__=='__main__':main()

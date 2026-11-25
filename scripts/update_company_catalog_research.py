"""Integrate reviewed public research, preserving legacy v1; derive quick-view CSV."""
import argparse
import copy
import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
import build_company_catalog_v2 as catalog

ROOT = catalog.ROOT
CSV_FIELDS = ['name','industry','tech_fit_tags','status','confidence','identity','source_tasks','tiers','reference_url','checked_at_utc']

def csv_rows(data):
    rows=[]
    for c in data['companies']:
        cl=c['classification'];review=cl['research_review']
        rows.append({'name':c['name'],'industry':cl['industry']['value'],'tech_fit_tags':' | '.join(t['value'] for t in cl['tech_fit']['tags']),'status':cl['status']['value'],'confidence':cl['industry']['confidence'],'identity':review['identity'],'source_tasks':' | '.join(map(str,c['source_tasks'])),'tiers':' | '.join(sorted({p['tier'] for p in c['provenance'] if p.get('tier')})),'reference_url':review['sources'][0]['url'] if review['sources'] else '', 'checked_at_utc':review['checked_at_utc']})
    return rows

def check_csv(data, text):
    reader=csv.DictReader(io.StringIO(text));assert reader.fieldnames==CSV_FIELDS
    rows=list(reader);assert rows==csv_rows(data);assert len(rows)==292
    assert len({r['name'] for r in rows})==292
    # Refuse spreadsheet formulas rather than changing company names.
    assert all(not v.startswith(('=','+','-','@','\t','\r')) for r in rows for v in r.values())

def integrate(old, current, research):
    names=[c['name'] for c in old['companies']]
    assert len(research)==len(names)==292
    assert len({r['name'] for r in research})==292
    assert {r['name'] for r in research}==set(names)
    by_name={r['name']:r for r in research};new=copy.deepcopy(current)
    now=datetime.now(timezone.utc).isoformat()
    for c in new['companies']:
        r=by_name[c['name']]
        assert r['industry'] in catalog.INDUSTRIES
        assert r['confidence'] in ['high','medium','low','unknown']
        assert r['identity'] in ['confirmed','ambiguous']
        assert len(set(r['tech_tags']))==len(r['tech_tags'])
        assert all(t in catalog.TECH for t in r['tech_tags'])
        sources=copy.deepcopy(r['sources'])
        for source in sources: source['title']=source['title'].replace('\\u2014','-')
        for source in sources:
            assert urlparse(source['url']).scheme in ('https','http')
            assert source['title'] and source['excerpt']
            assert source['checked_at_utc']
        if r['identity']=='confirmed' and r['industry']!='unknown':assert sources
        ambiguous=r['identity']=='ambiguous'
        value='unknown' if ambiguous else r['industry']
        tech=[] if ambiguous else r['tech_tags']
        status='identity_needs_verification' if ambiguous else ('watchlist' if 26 in c['source_tasks'] else 'research')
        checked=max((s['checked_at_utc'] for s in sources),default=now)
        limitations=r.get('limitations','')
        if not isinstance(limitations,str):limitations='; '.join(limitations)
        reason=r['rationale']
        if reason.startswith('Opened official product/company page supports') and sources:reason=sources[0]['excerpt']
        c['classification']={
            'classified_at_utc':now,'method':'public_source_review_v1',
            'industry':{'value':value,'confidence':'unknown' if value=='unknown' else r['confidence'],'evidence':sources if value!='unknown' else [],'reason':reason},
            'tech_fit':{'assessment':'domain_overlap_only' if tech else 'no_supported_tag','tags':[{'value':t,'confidence':'medium' if r['confidence'] in ('unknown','high') else r['confidence'],'evidence':sources} for t in tech],'reason':'Researched technical-domain overlap only, not resume, level, location, sponsorship or current vacancy qualification.'},
            'status':{'value':status,'scope':'company_next_action','reason':'Public research still leaves intended employer identity ambiguous.' if ambiguous else ('Existing Task 26 priority-watchlist membership retained.' if status=='watchlist' else 'Employer researched; check exact current role and candidate fit before action.'),'basis_provenance_indices':list(range(len(c['provenance'])))},
            'research_review':{'identity':r['identity'],'rationale':reason,'limitations':limitations,'sources':sources,'checked_at_utc':checked}}
    new['classification_policy'].update({'classified_at_utc':now,'method':'public_source_review_v1','scope':'All 292 entries reviewed against public sources and saved identity context. Sources and limitations are per company. Technical tags describe domain overlap, not candidate qualification. No application-history reconciliation or employer actions. Original generated_at_utc/validation describe v1 only.','industry_assignment':'Reviewed primary product/customer vertical; not automatic keyword matching. Legacy industry_precedence records only the initial pass.','identity_holds_preserved':True,'identity_resolution_policy':'Original identity_requires_review fields preserved as historical provenance; current resolution is classification.research_review.identity.','runtime_integration':False,'companies_reviewed':292})
    new['classification_counts']=catalog.counts(new['companies'])
    new['classification_policy']['research_coverage']={'with_public_sources':sum(bool(c['classification']['research_review']['sources']) for c in new['companies']),'identity_confirmed':sum(c['classification']['research_review']['identity']=='confirmed' for c in new['companies']),'identity_ambiguous':sum(c['classification']['research_review']['identity']=='ambiguous' for c in new['companies']),'unknown_industry':new['classification_counts']['industry'].get('unknown',0)}
    catalog.validate(old,new)
    return new

def main():
    p=argparse.ArgumentParser();p.add_argument('batches',nargs='*',type=Path);p.add_argument('--check',action='store_true');args=p.parse_args()
    original=ROOT/'data/company_names.json';before=catalog.digest(original)
    old=json.loads(original.read_text());path=ROOT/'data/company_names.v2.json';current=json.loads(path.read_text());csv_path=ROOT/'data/company_names.v2.csv'
    assert before==current['derived_from']['sha256']
    if args.check:
        catalog.validate(old,current);check_csv(current,csv_path.read_text());print('PASS: v1 unchanged; v2 schema/integrity; CSV exact 292-row projection');return
    assert args.batches,'Supply reviewed research batch JSON files'
    research=[]
    for batch in args.batches:research.extend(json.loads(batch.read_text()))
    data=integrate(old,current,research)
    out=io.StringIO(newline='');writer=csv.DictWriter(out,fieldnames=CSV_FIELDS);writer.writeheader();writer.writerows(csv_rows(data));text=out.getvalue();check_csv(data,text)
    # Stage fully validated content; each destination replacement is atomic.
    outputs={path:json.dumps(data,indent=2,ensure_ascii=False)+'\n',ROOT/'data/company_names.v2.schema.json':json.dumps(catalog.make_schema(),indent=2)+'\n',csv_path:text}
    for target,content in outputs.items():
        temp=target.with_name(target.name+'.tmp');temp.write_text(content);temp.replace(target)
    assert catalog.digest(original)==before
    print(json.dumps({'counts':data['classification_counts'],'research_coverage':data['classification_policy']['research_coverage']},indent=2))
if __name__=='__main__':main()

"""Pinned Baseten source/JD, real single assembly/render/geometry, zero network.

Missing pinned inputs or renderer are reported as unavailable, never an E2E pass.
Run exactly: python3 tests/test_resume_all_bullets_e2e.py BasetenAllBulletsE2ETest.test_legacy_fixture_is_partial_under_source_retention_gate -v
"""
import hashlib
import json
import os
import socket
import sys
import threading
import time
import unittest
import uuid
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from modules import resume_all_bullets as m

ROOT=Path(__file__).resolve().parents[1]
INPUT=Path(os.getenv('TASK11_INPUT_ROOT','/Users/deepakbasavaraju/Documents/Codex/2026-10-14/task-2/evidence/baseline'))
OUTPUT=Path(os.getenv('TASK11_OUTPUT_ROOT',str(ROOT.parent/'evidence/task11-e2e')))
EXPECTED={'source/resume.docx':'1a20e99ac92d1d56512accad2179b1e90c138283612f89843d5344ac93b5c968',
          'source/resume.pdf':'9731bc76c1a85199cfac2254fd1590af0b5545763ab05e9f31eabfa4b5791981'}
JD_HASH='50258a5b9ba4efd1cb30f1722d6e890bb2025130972bb3fb3148e9fa5929bacf'


def inputs():
    for name,digest in EXPECTED.items():
        if not (INPUT/name).is_file():raise unittest.SkipTest('unavailable: missing pinned Baseten '+name)
        if m.sha((INPUT/name).read_bytes())!=digest:raise ValueError('pinned input hash mismatch: '+name)
    job=json.loads((INPUT/'target-job.json').read_text())
    assert job['company']['name']=='Baseten' and job['title']=='Software Engineer - Inference Platform'
    assert m.sha(job['description'])==JD_HASH
    return job


class BasetenAllBulletsE2ETest(unittest.TestCase):
    def run_fixture(self,concurrency=2,blocked=None):
        job=inputs();captured=[];lock=threading.Lock()
        replacements=(ROOT/'tests/fixtures/task11/baseten_rewrites.txt').read_text().splitlines()
        self.assertEqual(len(replacements),54)
        def provider(stage,payload,timeout):
            self.assertEqual(payload['job_description'],job['description'])
            with lock:captured.append(deepcopy(payload))
            if stage=='keywords':return {'keywords':['Python','Kubernetes','AWS','LLM','inference','distributed systems','GPU','Terraform']}
            time.sleep(.02 if payload['source_experience']['bullets'][0]['ordinal']%2==0 else .001)
            results=[]
            for b in payload['requested_bullets']:
                self.assertIn({k:b[k] for k in ('bullet_id','ordinal','source_text','source_text_hash','fact_anchors')},payload['source_experience']['bullets'])
                item=dict(bullet_id=b['bullet_id'],source_text_hash=b['source_text_hash'],status='rewritten',
                    rewritten_text=replacements[b['ordinal']],matched_jd_spans=[],preserved_fact_anchors=b['fact_anchors'],
                    change_reason='Historical canned rewrite; current fidelity gate must independently validate its content',blocked_reason=None)
                if b['ordinal']==blocked:item.update(status='unchanged',rewritten_text=b['source_text'],change_reason='deliberate incomplete fixture')
                results.append(item)
            return {'experience_id':payload['experience_id'],'results':list(reversed(results))}
        config=dict(m.DEFAULTS,rewrite_all_bullets=True,rewrite_experience_concurrency=concurrency,
                    rewrite_requests_per_minute=1000000,rewrite_tokens_per_minute=1000000000,
                    content_policy='grounded',replace_job_title=False,max_skills=65,expected_page_count=2)
        output=OUTPUT/(str(uuid.uuid4())+f'-c{concurrency}')
        with patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK FORBIDDEN')):
            result=m.run_all_bullets(job['description'],INPUT/'source/resume.docx','baseten-pinned-fixture',job['title'],
                config,execution_kind='offline_fixture',provider=provider,output_root=output)
        self.assertIsNone(result,'offline fixtures cannot become generated attachments')
        report=json.loads((output/'match-report.json').read_text());coverage=json.loads((output/'rewrite-coverage.json').read_text())
        self.assertEqual(report['ai_execution_kind'],'offline_fixture');self.assertFalse(report['ai_activity']['live_provider_response_observed'])
        self.assertEqual(report['coverage']['inventoried'],47);self.assertEqual(report['coverage']['requested'],47)
        self.assertEqual(len({r['bullet_id'] for r in coverage['bullets']}),47)
        self.assertEqual([r['ordinal'] for r in coverage['bullets']],list(range(47)))
        self.assertEqual(report['preserved_sections']['Academic Distinctions']['bullet_count'],7)
        self.assertTrue(report['format_verification']['checks']['academic_distinctions_preserved'])
        self.assertEqual(report['auto_submission_authorized'],False)
        m.verify_binding(output)
        self.assertIn('Full exact JD',(output/'comparison.html').read_text())
        return report,coverage,output

    def test_legacy_fixture_is_partial_under_source_retention_gate(self):
        first,coverage,path=self.run_fixture(2)
        # Older fixture expectations called54 canned proposals complete. They
        # omit source details and cannot prove faithful full rewriting.
        self.assertEqual(first['status'],'partial')
        self.assertLess(first['coverage']['accepted'],54)
        self.assertTrue(any('source content terms' in (r.get('reason') or '') for r in coverage['bullets']))
        self.assertFalse(first['strict_attachment_eligible'])
        second,second_coverage,path2=self.run_fixture(1)
        self.assertEqual(second['status'],'partial')
        self.assertEqual(coverage,second_coverage)
        for key in ('coverage','match_analysis','pre_optimization','post_optimization','keyword_provenance'):
            self.assertEqual(first[key],second[key])
        print('OFFLINE LEGACY FIXTURE: incomplete drafts blocked; render/provenance checked:',path,path2)

    def test_46_of_47_partial_and_artifact_binding(self):
        report,coverage,path=self.run_fixture(2,46)
        self.assertEqual(report['status'],'partial');self.assertLessEqual(report['coverage']['accepted'],46)
        self.assertNotEqual(coverage['bullets'][46]['status'],'accepted')
        self.assertFalse(report['strict_attachment_eligible'])
        original=(path/'optimized.docx').read_bytes()
        try:
            with (path/'optimized.docx').open('ab') as file:file.write(b'tamper')
            with self.assertRaises(ValueError):m.verify_binding(path)
        finally:
            (path/'optimized.docx').write_bytes(original)
        m.verify_binding(path)


if __name__=='__main__':unittest.main()

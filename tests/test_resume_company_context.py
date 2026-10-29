"""Company payload isolation and immutable catalogue snapshots; no API calls."""
from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from modules.resume_company_context import bind_company_context
from modules import resume_all_bullets as m
from test_resume_all_bullets import inv, config, response


class CompanyContextTest(unittest.TestCase):
    def catalogue(self, root):
        path = root / 'catalogue.json'
        path.write_text(json.dumps({'schema_version': 1, 'profiles': [
            {'id': 'trek', 'aliases': ['TREK HEALTH'], 'context': 'Payer contract intelligence'},
            {'id': 'sybill', 'aliases': ['SYBILL'], 'context': 'Sales conversation intelligence'},
        ]}))
        return {'company_context_enabled': True, 'company_context_path': str(path)}

    def test_enabled_snapshot_and_matching_are_isolated_from_file_and_payload_mutation(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp);cfg = self.catalogue(root);inventory = inv(2,2)
            inventory['groups'][0]['company'] = ' Trek   Health\tSan Francisco'
            inventory['groups'][1]['company'] = 'SYBILL\tMountain View'
            report = bind_company_context(inventory,cfg,root)
            self.assertEqual(len(report['matched_groups']),2)
            self.assertEqual(report['unmatched_groups'],[])
            Path(cfg['company_context_path']).write_text('changed after snapshot')
            for policy in ('synthetic_jd_test','jd_rewrite','grounded','review_draft'):
                group = inventory['groups'][0]
                payload = m.compact_payload(inventory,'Build AI systems','Staff Engineer',policy,group,group['bullets'])
                self.assertEqual(payload['company_context']['profile']['id'],'trek')
                self.assertNotIn('Sales conversation',json.dumps(payload))
                payload['company_context']['profile']['context'] = 'tampered payload'
                self.assertEqual(group['company_context']['profile']['context'],'Payer contract intelligence')
                if policy == 'synthetic_jd_test':
                    self.assertNotIn('original_bullet_reference',payload['requested_bullets'][0])
                    self.assertFalse(payload['fact_policy']['source_evidence_required'])
            self.assertIn('Payer contract',(root/'company-context.json').read_text())

    def test_disabled_and_unmatched_groups_do_not_get_other_company_context(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);inventory=inv(1,1)
            self.assertEqual(bind_company_context(inventory,{},root),{'enabled':False})
            self.assertFalse((root/'company-context.json').exists())
            report=bind_company_context(inventory,self.catalogue(root),root)
            self.assertEqual(len(report['unmatched_groups']),1)
            payload=m.compact_payload(inventory,'JD','Engineer','synthetic_jd_test',inventory['groups'][0],inventory['bullets'])
            self.assertNotIn('company_context',payload)

    def test_invalid_flags_and_ambiguous_catalogue_fail_before_generation(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);cfg=self.catalogue(root)
            for bad in ('true',1,None):
                with self.assertRaises(ValueError):bind_company_context(inv(),{**cfg,'company_context_enabled':bad},root)
            data=json.loads(Path(cfg['company_context_path']).read_text())
            data['profiles'][1]['aliases']=['trek health']
            Path(cfg['company_context_path']).write_text(json.dumps(data))
            with self.assertRaises(ValueError):bind_company_context(inv(),cfg,root)

    def test_parallel_requests_and_retries_keep_their_company(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp);inventory=inv(2,2)
            inventory['groups'][0]['company']='TREK HEALTH'
            inventory['groups'][1]['company']='SYBILL'
            bind_company_context(inventory,self.catalogue(root),root)
            calls=[]
            def provider(stage,payload,timeout):
                calls.append(deepcopy(payload))
                if sum(p['experience_id']==payload['experience_id'] for p in calls)==1:
                    raise ValueError('fixture first-attempt failure')
                return response(payload)
            records=m.rewrite_inventory(inventory,'Python','Engineer','grounded',m.Scheduler(config(),2),provider)
            self.assertTrue(all(r['status']=='candidate' for r in records))
            self.assertEqual(len(calls),4)
            for payload in calls:
                self.assertEqual(payload['company_context']['profile']['id'], 'trek' if payload['experience_id']=='0' else 'sybill')


if __name__=='__main__':unittest.main()

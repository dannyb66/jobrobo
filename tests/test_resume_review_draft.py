"""Unchecked exports remain source-bound by identity, and never become attachments."""
import json
import socket
import threading
import unittest
from copy import deepcopy
from unittest.mock import patch
from modules import resume_all_bullets as m
from modules import resume_review_draft as r
from test_resume_all_bullets import config, inv, response


def source():
    value=inv(8,4)
    for group in value['groups']:
        group.update(section='Experience',company='Source company',historical_title_dates=['Source title'])
        for b in group['bullets']:
            b.update(max_rendered_lines=1,font_runs=[{'font':'Arial','size_pt':10}],soft_character_estimate=100)
    return value


class UncheckedReviewTest(unittest.TestCase):
    def test_schema_all_fields_required_and_no_additional_keys(self):
        for stage in ('keywords','bullets'):
            schema=m.provider_response_format(stage)['json_schema']
            self.assertTrue(schema['strict'])
            root=schema['schema'];self.assertEqual(set(root['required']),set(root['properties']))
            self.assertFalse(root['additionalProperties'])
        item=m.provider_response_format('bullets')['json_schema']['schema']['properties']['results']['items']
        self.assertEqual(len(item['required']),8);self.assertFalse(item['additionalProperties'])

    def test_unsafe_proposal_retained_only_as_unchecked_diagnostic(self):
        original=source();group=original['groups'][0]
        payload=m.compact_payload(original,'Python','Engineer','unchecked_review',group,group['bullets'])
        value=response(payload);value['results'][0]['rewritten_text']='Invented 999 GPU clusters and managed Kubernetes'
        out=r.protocol_proposals(value,group,group['bullets'])
        first=out[group['bullets'][0]['bullet_id']]
        self.assertEqual(first['status'],'unchecked_proposal')
        self.assertEqual(first['strict_validation_status'],'blocked')
        self.assertEqual(first['rewritten_text'],value['results'][0]['rewritten_text'])
        self.assertTrue(first['reason'])
        # Strict path still refuses that exact proposed claim.
        self.assertEqual(m.validate_response(value,group,group['bullets'])[first['bullet_id']]['status'],'blocked')

    def test_protocol_identity_never_bypassed(self):
        original=source();group=original['groups'][0]
        payload=m.compact_payload(original,'Python','Engineer','unchecked_review',group,group['bullets'])
        for mutate in (lambda v:v.update(experience_id='foreign'),lambda v:v['results'].append(v['results'][0]),lambda v:v['results'][0].update(bullet_id='foreign')):
            value=response(payload);mutate(value)
            with self.assertRaises(ValueError):r.protocol_proposals(value,group,group['bullets'])
        value=response(payload);value['results'][0].update(source_text_hash='stale')
        self.assertEqual(r.protocol_proposals(value,group,group['bullets'])[group['bullets'][0]['bullet_id']]['reason'],'source hash mismatch')

    def test_first_wave_precedes_retry_complete_context_and_stable_order(self):
        original=source();calls=[];lock=threading.Lock()
        def provider(stage,payload,timeout):
            with lock:calls.append(deepcopy(payload));first=len(calls)==1
            group=next(g for g in original['groups'] if g['experience_id']==payload['experience_id'])
            self.assertEqual(payload['job_description'],'Python full exact JD')
            self.assertEqual([b['source_text'] for b in payload['source_experience']['bullets']],[b['source_text'] for b in group['bullets']])
            value=response(payload)
            if first:value['results'][0]['rewritten_text']=None
            return value
        scheduler=m.Scheduler(config(),4)
        with patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK FORBIDDEN')):
            records=r.collect_proposals(original,'Python full exact JD','role',scheduler,provider)
        self.assertEqual(len(calls),5)
        self.assertEqual(len({p['experience_id'] for p in calls[:4]}),4)
        # The first dispatched experience is chosen by thread scheduling.
        # Retry exactly its malformed bullet, whichever experience ran first.
        self.assertEqual(calls[-1]['requested_bullet_ids'],calls[0]['requested_bullet_ids'][:1])
        self.assertEqual(calls[-1]['experience_id'],calls[0]['experience_id'])
        self.assertEqual([b['bullet_id'] for b in records],[str(i) for i in range(8)])
        self.assertEqual(sum(b['status']=='unchecked_proposal' for b in records),8)
        self.assertFalse(m.DEFAULTS['rewrite_all_bullets'])


    def test_blocked_null_is_explicit_retained_and_received(self):
        original=source();group=original['groups'][0]
        payload=m.compact_payload(original,'Python','Engineer','unchecked_review',group,group['bullets'])
        value=response(payload);value['results'][0].update(status='blocked',rewritten_text=None,blocked_reason='Source facts cannot fit')
        out=r.protocol_proposals(value,group,group['bullets']);row=out[group['bullets'][0]['bullet_id']]
        self.assertEqual(len(out),len(group['bullets']))
        self.assertEqual(row['reason'],'Source facts cannot fit')
        self.assertEqual(row['status'],'retained_source');self.assertTrue(row['response_received'])

    def test_invalid_protocol_still_counts_actual_transport_coverage(self):
        original=source();scheduler=m.Scheduler(config(),4)
        def provider(stage,payload,timeout):
            value=response(payload);value['results'][0]['bullet_id']='unowned'
            return value
        with patch.object(socket.socket,'connect',side_effect=AssertionError('NETWORK FORBIDDEN')):
            records=r.collect_proposals(original,'Python','role',scheduler,provider)
        self.assertEqual(sum(b['requested'] for b in records),8)
        self.assertEqual(sum(b['response_received'] for b in records),8)
        self.assertEqual(sum(b['status']=='unchecked_proposal' for b in records),0)
        self.assertTrue(all('IDs' in b['reason'] for b in records))

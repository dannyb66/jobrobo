"""Synthetic metric hints are preferences, never restored source checks."""
import unittest
from modules import resume_all_bullets as m, resume_jd_experiment as experiment
from test_resume_all_bullets import inv, response


class SyntheticMetricTest(unittest.TestCase):
    def test_numbers_keep_units_ranges_ratios_and_nearby_context(self):
        text='Scaled to 100+ clients on 5TB+ of data; cut latency by 50%; 14B–30B models at ~$0.52–1.07/hr; passed 25/25 routing.'
        hints=experiment.metric_hints(text)
        numbers=[hint['number'] for hint in hints]
        for value in ('100+','5TB+','50%','14B–30B','~$0.52–1.07','25/25'):
            # Currency and approximation may be adjacent in either source order.
            self.assertTrue(any(value.lstrip('~')==number.lstrip('~') for number in numbers),numbers)
        self.assertTrue(any('clients' in hint['context'] for hint in hints if hint['number']=='100+'))

    def test_technical_identifiers_are_not_misread_as_counts(self):
        self.assertEqual(experiment.metric_hints('Used A10G, L40S, L1–L3 and GPT4 systems'),[])
        self.assertEqual(experiment.metric_hints('Built reliable services'),[])

    def test_payload_uses_soft_hints_but_can_accept_a_rewrite_without_numbers(self):
        inventory=inv(1,1);group=inventory['groups'][0]
        source=group['bullets'][0]
        source.update(source_text='Built APIs for 100+ clients, cutting latency by 50%',source_text_hash='source-hash')
        payload=m.compact_payload(inventory,'Build Rust agents','Engineer',experiment.POLICY,group,[source])
        hints=payload['requested_bullets'][0]['original_metric_hints']
        self.assertEqual([hint['number'] for hint in hints],['100+','50%'])
        self.assertNotIn('source_text',payload['requested_bullets'][0])
        raw=response({'experience_id':group['experience_id'],'requested_bullets':[source]})
        raw['results'][0]['rewritten_text']='Shipped production Rust agents with tracing.'
        result=m.validate_response(raw,group,[source],content_policy=experiment.POLICY)[source['bullet_id']]
        self.assertEqual(result['status'],'candidate')


if __name__=='__main__':unittest.main()

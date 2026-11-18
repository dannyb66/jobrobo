"""Provider prompt isolation, Venice wire identity, candidate and cache contracts."""
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules import resume_provider_prompts as p
from modules.resume_all_bullets import generation_system, SYSTEM
from modules.resume_jd_experiment import POLICY, PROMPT_OVERRIDE
from modules.resume_cache import resume_cache_fingerprint


class ProviderPromptTests(unittest.TestCase):
    def payload(self):
        return {'experience_id': 'experience-full-hash', 'content_policy': POLICY,
            'job_description': 'Build Python APIs', 'candidate_count': 3,
            'requested_bullets': [dict(bullet_id=f'full-id-{i}', source_text_hash=f'hash-{i}',
                source_text='Built Python APIs with evaluation and reliable production deployment.',
                soft_character_estimate=130, candidate_word_budgets=[20, 16, 11]) for i in range(2)],
            'retry_reasons': {'full-id-1': 'glyph width estimate 650pt exceeds single-line budget 540pt; target at most 125 characters'},
            'acceptance_criteria': {'fit': 'old compact guidance'}}

    def response(self, values):
        return SimpleNamespace(id='test-only', choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(values)))])

    def row(self, text='Built reliable Python APIs with evaluation and automated deployment.'):
        return {'primary': text, 'alternative': text, 'compact': text}

    def test_existing_openai_system_is_byte_identical(self):
        before = Path('config/prompts/resume_bullets.txt').read_bytes()
        actual = generation_system(POLICY, {'rewrite_provider': 'openai'})
        self.assertEqual(actual, SYSTEM + PROMPT_OVERRIDE)
        self.assertEqual(Path('config/prompts/resume_bullets.txt').read_bytes(), before)

    def test_venice_selects_separate_prompt_and_appends_same_content_policy(self):
        system = generation_system(POLICY, {'rewrite_provider': 'venice'})
        self.assertIn('You write concise engineering resume accomplishments', system)
        self.assertIn(PROMPT_OVERRIDE, system)
        self.assertNotIn('How do you love it, but how?', system)
        self.assertIn('TRANSPORT AND FIT OVERRIDE', system)

    def test_custom_path_is_configurable_and_empty_prompt_fails(self):
        with TemporaryDirectory() as root:
            path = Path(root) / 'custom.txt'
            path.write_text('custom provider prompt')
            cfg = {'rewrite_provider': 'venice', 'rewrite_venice_prompt_path': str(path)}
            self.assertTrue(generation_system(None, cfg).startswith('custom provider prompt'))
            self.assertEqual(p.prompt_info(cfg)['sha256'], hashlib.sha256(path.read_bytes()).hexdigest())
            path.write_text(' ')
            with self.assertRaisesRegex(ValueError, 'empty'):
                p.prompt_info(cfg)

    def test_venice_attachment_requires_matching_prompt_provenance(self):
        with TemporaryDirectory() as root:
            path = Path(root) / 'venice.txt'; path.write_text('venice v1')
            cfg = {'rewrite_provider':'venice', 'rewrite_venice_prompt_path':str(path)}
            self.assertFalse(p.prompt_matches_report({}, cfg))
            report = {'bullet_prompt':p.prompt_info(cfg)}
            self.assertTrue(p.prompt_matches_report(report, cfg))
            path.write_text('venice v2')
            self.assertFalse(p.prompt_matches_report(report, cfg))
            self.assertTrue(p.prompt_matches_report({}, {'rewrite_provider':'openai'}))

    def test_wire_slots_remove_opaque_ids_and_use_consistent_candidate_lengths(self):
        original = self.payload()
        wire, schema, mapping = p.venice_request(original)
        self.assertEqual(set(mapping), {'b1', 'b2'})
        self.assertNotIn('full-id-', json.dumps(wire))
        self.assertEqual(set(schema['json_schema']['schema']['properties']), {'b1', 'b2'})
        self.assertEqual(wire['requested_bullets'][0]['candidate_character_targets'], [124, 117, 110])
        self.assertGreaterEqual(min(wire['requested_bullets'][0]['candidate_word_budgets']), 20)
        self.assertIn('repair_reason', wire['requested_bullets'][1])
        self.assertEqual(original['requested_bullets'][0]['candidate_word_budgets'], [20, 16, 11])

    def test_results_are_bound_by_slot_not_response_order(self):
        payload = self.payload()
        _, _, mapping = p.venice_request(payload)
        reply = self.response({'b2': self.row(), 'b1': self.row()})
        normalized = p.normalize_venice_response(reply, payload, mapping)
        rows = json.loads(normalized.choices[0].message.content)['results']
        self.assertEqual([r['bullet_id'] for r in rows], ['full-id-0', 'full-id-1'])
        self.assertEqual([r['source_text_hash'] for r in rows], ['hash-0', 'hash-1'])
        self.assertEqual(normalized.resume_wire_mapping['b1']['bullet_id'], 'full-id-0')
        self.assertIn('b2', normalized.resume_wire_content)

    def test_missing_or_unknown_slot_does_not_discard_valid_sibling(self):
        payload = self.payload(); _, _, mapping = p.venice_request(payload)
        reply = self.response({'b2': self.row(), 'unknown': self.row()})
        result = json.loads(p.normalize_venice_response(reply, payload, mapping).choices[0].message.content)
        self.assertEqual([r['bullet_id'] for r in result['results']], ['full-id-1'])

    def test_duplicate_slot_is_rejected_without_discarding_other_slots(self):
        payload = self.payload(); _, _, mapping = p.venice_request(payload)
        row = json.dumps(self.row())
        reply = self.response({})
        reply.choices[0].message.content = '{"b1":'+row+',"b1":'+row+',"b2":'+row+'}'
        result = json.loads(p.normalize_venice_response(reply, payload, mapping).choices[0].message.content)
        self.assertEqual([r['bullet_id'] for r in result['results']], ['full-id-1'])

    def test_placeholder_alternative_is_rejected_before_candidate_ranking(self):
        payload = self.payload(); _, _, mapping = p.venice_request(payload)
        row = self.row(); row['alternative'] = 'There is no bullet.'
        reply = self.response({'b1': row})
        result = json.loads(p.normalize_venice_response(reply, payload, mapping).choices[0].message.content)
        self.assertEqual(result['results'][0]['alternative_texts'][0], '')
        self.assertTrue(result['results'][0]['rewritten_text'])

    def test_editing_inactive_provider_prompt_does_not_invalidate_openai_cache(self):
        with TemporaryDirectory() as root:
            repo = Path(root); (repo/'config/prompts').mkdir(parents=True)
            source = repo/'resume.docx'; source.write_bytes(b'source')
            openai = repo/'config/prompts/resume_bullets.txt'; openai.write_text('openai v1')
            venice = repo/'config/prompts/resume_bullets_venice.txt'; venice.write_text('venice v1')
            common = dict(job_id='1', job_description='Python', source_resume=source, job_title='Engineer',
                          first_name='Test', last_name='Candidate', repo_root=repo)
            cfg = {'rewrite_openai_prompt_path':str(openai), 'rewrite_venice_prompt_path':str(venice)}
            old_openai = resume_cache_fingerprint(config=dict(cfg,rewrite_provider='openai'), **common)
            old_venice = resume_cache_fingerprint(config=dict(cfg,rewrite_provider='venice'), **common)
            venice.write_text('venice v2')
            self.assertEqual(old_openai, resume_cache_fingerprint(config=dict(cfg,rewrite_provider='openai'), **common))
            self.assertNotEqual(old_venice, resume_cache_fingerprint(config=dict(cfg,rewrite_provider='venice'), **common))

    def test_stage_completion_openai_keeps_original_schema_and_payload(self):
        from modules.resume_all_bullets import provider_response_format
        payload = self.payload()
        with patch('modules.resume_provider.complete', return_value=self.response({})) as complete:
            p.stage_completion(Mock(), {}, 'bullets', payload, 'system', 12)
        self.assertEqual(complete.call_args.kwargs['response_format'], provider_response_format('bullets', payload))
        self.assertEqual(json.loads(complete.call_args.kwargs['messages'][1]['content']), payload)


if __name__ == '__main__':
    unittest.main()

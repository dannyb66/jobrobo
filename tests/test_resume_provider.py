"""Resume provider routing contracts; no credentials, browser or network."""
from contextlib import nullcontext
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import threading
import time
import unittest
from unittest.mock import Mock, patch

from modules import resume_provider as p


class ResumeProviderTests(unittest.TestCase):
    def setUp(self):
        p._catalogs.clear()
        p._auth_failures.clear()
        self.config = {'rewrite_provider': 'venice', 'rewrite_venice_model': p.VENICE_MODEL,
                       'rewrite_model': 'gpt-6-luna', 'rewrite_reasoning_effort': 'none'}
        self.client = Mock(api_key='fixture-only')
        self.client.with_options.return_value = self.client
        self.client.models.list.return_value = SimpleNamespace(data=[SimpleNamespace(
            id=p.VENICE_MODEL, model_spec={'capabilities': {'supportsResponseSchema': True,
                        'reasoningEffortOptions': ['none', 'low', 'high', 'max']}})])

    def test_default_file_selects_requested_venice_model_and_keeps_openai(self):
        config = json.loads(Path('config/resume_optimizer_defaults.json').read_text())
        self.assertEqual(p.settings(config)['model'], p.VENICE_MODEL)
        self.assertEqual(p.settings(config)['reasoning'], 'none')
        self.assertEqual(config['rewrite_model'], 'gpt-6-luna')

    def test_override_is_scoped_and_does_not_mutate_saved_config(self):
        original = json.dumps(self.config)
        with p.override_settings({'provider': 'openai', 'reasoning': 'low'}):
            active = p.apply_overrides(self.config)
            self.assertEqual(p.settings(active)['model'], 'gpt-6-luna')
            self.assertEqual(p.settings(active)['provider'], 'openai')
        self.assertEqual(json.dumps(self.config), original)
        self.assertEqual(p.apply_overrides(self.config), self.config)

    def test_model_override_changes_only_selected_provider(self):
        with p.override_settings({'model': 'another-venice-model'}):
            active = p.apply_overrides(self.config)
        self.assertEqual(active['rewrite_model'], 'gpt-6-luna')
        self.assertEqual(active['rewrite_venice_model'], 'another-venice-model')

    def test_preflight_is_cached_once_per_key_but_checks_each_model(self):
        p.preflight(self.client, p.settings(self.config))
        p.preflight(self.client, p.settings(self.config))
        self.client.models.list.assert_called_once()
        with self.assertRaisesRegex(ValueError, 'not in the Venice catalog'):
            p.preflight(self.client, p.settings(dict(self.config, rewrite_venice_model='absent')))

    def test_unsupported_reasoning_or_schema_fails_before_generation(self):
        with self.assertRaisesRegex(ValueError, 'reasoning effort'):
            p.preflight(self.client, p.settings(dict(self.config, rewrite_reasoning_effort='medium')))
        p._catalogs.clear()
        self.client.models.list.return_value.data[0].model_spec['capabilities']['supportsResponseSchema'] = False
        with self.assertRaisesRegex(ValueError, 'response schemas'):
            p.preflight(self.client, p.settings(self.config))
        self.client.chat.completions.create.assert_not_called()

    def test_venice_completion_preserves_schema_and_disables_hidden_retries(self):
        schema = {'type': 'json_schema', 'json_schema': {'name': 'test', 'schema': {'type': 'object'}}}
        with patch.object(p, 'request_slot', return_value=nullcontext(12)):
            p.complete(self.client, self.config, model='gpt-6-luna', max_tokens=20,
                       messages=[{'role': 'user', 'content': 'JSON keywords'}], response_format=schema)
        sent = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(sent['model'], p.VENICE_MODEL)
        self.assertEqual(sent['response_format'], schema)
        self.assertNotIn('max_tokens', sent)
        self.assertEqual(sent['extra_body']['reasoning_effort'], 'none')
        self.assertFalse(sent['extra_body']['venice_parameters']['include_venice_system_prompt'])
        self.client.with_options.assert_called_with(timeout=12, max_retries=0)

    def test_openai_switch_uses_openai_model_and_no_venice_parameters(self):
        cfg = dict(self.config, rewrite_provider='openai')
        with patch.object(p, 'request_slot', return_value=nullcontext(5)):
            p.complete(self.client, cfg, model=p.VENICE_MODEL, max_tokens=20, messages=[])
        sent = self.client.chat.completions.create.call_args.kwargs
        self.assertEqual(sent['model'], 'gpt-6-luna')
        self.assertNotIn('venice_parameters', sent['extra_body'])
        self.assertEqual(sent['max_completion_tokens'], 20)

    def test_auth_rejection_is_not_repeated_for_later_jobs(self):
        error = RuntimeError('fixture auth failure')
        error.status_code = 401
        self.client.chat.completions.create.side_effect = error
        with patch.object(p, 'request_slot', return_value=nullcontext(5)):
            for _ in range(2):
                with self.assertRaises(RuntimeError):
                    p.complete(self.client, self.config, messages=[])
        self.client.chat.completions.create.assert_called_once()

    def test_bad_catalog_key_is_not_retried(self):
        error = RuntimeError('fixture auth failure')
        error.status_code = 401
        self.client.models.list.side_effect = error
        for _ in range(2):
            with self.assertRaises(RuntimeError):
                p.preflight(self.client, p.settings(self.config))
        self.client.models.list.assert_called_once()

    def test_missing_key_and_wrong_endpoint_never_construct_client(self):
        selected = p.settings(self.config)
        with patch.dict(os.environ, {'VENICE_API_KEY': ''}), patch('dotenv.dotenv_values', return_value={}):
            with self.assertRaisesRegex(ValueError, 'Missing local VENICE_API_KEY'):
                p._credentials(selected)
        with patch.dict(os.environ, {'VENICE_API_KEY': 'fixture', 'VENICE_BASE_URL': 'https://example.invalid'}):
            with self.assertRaisesRegex(ValueError, 'VENICE_BASE_URL'):
                p._credentials(selected)

    def test_shared_slot_limit_is_enforced_across_concurrent_jobs(self):
        active = peak = 0
        lock = threading.Lock()
        selected = dict(p.settings(self.config), concurrency=2)
        cfg = {'rewrite_requests_per_minute': 100000000, 'rewrite_tokens_per_minute': 100000000}
        def job(_):
            nonlocal active, peak
            with p.request_slot(selected, cfg, 5, 1):
                with lock:
                    active += 1
                    peak = max(peak, active)
                time.sleep(.04)
                with lock:
                    active -= 1
        with TemporaryDirectory() as root, patch.object(Path, 'home', return_value=Path(root)):
            with ThreadPoolExecutor(max_workers=6) as workers:
                list(workers.map(job, range(6)))
        self.assertEqual(peak, 2)

    def test_cli_linkedin_overrides_reach_runtime_and_are_restored(self):
        import runAiBot as bot
        from modules.config_loader import peek_runtime_config
        observed = []
        with patch.object(bot, 'run_bot', side_effect=lambda: observed.append(p.settings(peek_runtime_config()))):
            bot.cli_main(['--configured-search-and-apply', '--fresh', '--single-search', '5',
                          '--resume-provider', 'openai', '--resume-model', 'gpt-6-luna', '--resume-reasoning', 'low'])
        self.assertEqual(observed[0]['provider'], 'openai')
        self.assertEqual(observed[0]['reasoning'], 'low')
        self.assertEqual(p._overrides.get(), {})

    def test_direct_cli_passes_overrides_and_four_workers_to_shared_runner(self):
        import direct_apply
        observed = []
        def submit(*args, **kwargs):
            from modules.config_loader import peek_runtime_config
            observed.append((kwargs, p.settings(peek_runtime_config())))
            return {'jobs': []}
        with patch('modules.generic_inputs.load_jobs', return_value=[]), \
             patch('modules.submit_runner.run_submissions', side_effect=submit), \
             patch('modules.submit_state.format_run_summary', return_value='test summary'):
            self.assertEqual(direct_apply.main(['submit', '--url', 'https://jobs.ashbyhq.com/example/123',
                '--workers', '4', '--resume-provider', 'venice', '--resume-model', p.VENICE_MODEL,
                '--resume-reasoning', 'none']), 0)
        options, selected = observed[0]
        self.assertEqual(options['workers'], 4)
        self.assertEqual(options['resume_options'], {'provider': 'venice', 'model': p.VENICE_MODEL, 'reasoning': 'none'})
        self.assertEqual(selected['model'], p.VENICE_MODEL)

    def test_provider_changes_cache_fingerprint(self):
        from modules.resume_cache import resume_cache_fingerprint
        with TemporaryDirectory() as root:
            source = Path(root) / 'resume.docx'
            source.write_bytes(b'fixture')
            kwargs = dict(job_id='123', job_description='Python', source_resume=source,
                          job_title='AI Engineer', first_name='Test', last_name='Candidate', repo_root=root)
            self.assertNotEqual(resume_cache_fingerprint(config=self.config, **kwargs),
                resume_cache_fingerprint(config=dict(self.config, rewrite_provider='openai'), **kwargs))

    def test_direct_parent_snapshot_survives_four_worker_contexts(self):
        from modules.generic_prepare import preparation_resume_config
        with p.override_settings({'provider': 'openai', 'model': 'gpt-6-luna', 'reasoning': 'low'}):
            snapshot = preparation_resume_config()
        def worker(_):
            # ContextVars do not inherit into these worker threads. Services
            # therefore capture the resolved config in their parent closure.
            return p.settings(p.apply_overrides(snapshot))
        with ThreadPoolExecutor(max_workers=4) as workers:
            selected = list(workers.map(worker, range(4)))
        self.assertTrue(all(item['provider'] == 'openai' and item['reasoning'] == 'low' for item in selected))

    def test_shared_pacing_respects_timeout_instead_of_unbounded_wait(self):
        selected = p.settings(self.config)
        cfg = {'rewrite_requests_per_minute': 1, 'rewrite_tokens_per_minute': 1000000}
        with TemporaryDirectory() as root, patch.object(Path, 'home', return_value=Path(root)):
            with p.request_slot(selected, cfg, 1, 1):
                pass
            with self.assertRaises(TimeoutError):
                with p.request_slot(selected, cfg, .02, 1):
                    self.fail('A second request must wait for its rate budget')

    def test_http_failure_is_redacted_and_retry_after_is_preserved(self):
        error = RuntimeError('fixture secret must not escape')
        error.status_code = 429
        error.response = SimpleNamespace(headers={'retry-after': '3', 'authorization': 'private'})
        safe = p._safe_http_error(error, p.settings(self.config))
        self.assertNotIn('fixture secret', str(safe))
        self.assertEqual(safe.response.headers, {'retry-after': '3'})

    def test_keyword_schema_bounds_generated_lists(self):
        from modules.resume_all_bullets import provider_response_format
        schema = provider_response_format('keywords', {'expand_skills': True})['json_schema']['schema']
        self.assertEqual(schema['properties']['keywords']['maxItems'], 80)
        self.assertEqual(schema['properties']['skill_candidates']['maxItems'], 150)

    def test_malformed_keyword_output_retries_once_with_existing_budget(self):
        from modules.resume_all_bullets import extract_keywords_with_retry, ProviderFailure
        scheduler = Mock()
        scheduler.call.side_effect = [ProviderFailure('invalid_response'), {'keywords': ['Python']}]
        result = extract_keywords_with_retry(scheduler, Mock(), {'job_description': 'Python'})
        self.assertEqual(result, {'keywords': ['Python']})
        self.assertEqual(scheduler.call.call_count, 2)
        self.assertEqual(scheduler.call.call_args.args[2]['retry_reasons'], {'keywords': 'invalid_response'})
        scheduler.call.reset_mock()
        scheduler.call.side_effect = ProviderFailure('invalid_response')
        with self.assertRaisesRegex(ValueError, 'invalid_response'):
            extract_keywords_with_retry(scheduler, Mock(), {'job_description': 'Python'})
        self.assertEqual(scheduler.call.call_count, 2)

    def test_truncated_json_is_recorded_and_recovered_by_real_scheduler(self):
        from modules.resume_all_bullets import extract_keywords_with_retry, Scheduler, DEFAULTS
        options = dict(DEFAULTS, rewrite_requests_per_minute=1000000, rewrite_tokens_per_minute=1000000000)
        scheduler = Scheduler(options, 1)
        truncated = SimpleNamespace(id='fixture-truncated', usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"keywords": ["Python"'))])
        provider = Mock(side_effect=[truncated, {'keywords': ['Python']}])
        result = extract_keywords_with_retry(scheduler, provider, {'job_description': 'Python'})
        self.assertEqual(result, {'keywords': ['Python']})
        self.assertEqual(len(scheduler.events), 2)
        self.assertEqual(scheduler.events[0]['error_kind'], 'invalid_response')


if __name__ == '__main__':
    unittest.main()

"""Source-checked resume rewriting in bounded experience-entry requests.

Uses the existing optimizer's prompts, validators, layout recovery and reports.
Smaller requests prevent a long multi-employer response from dropping entry
identities, metrics or bullets. Layout retries reuse the validated responses.
"""
from copy import copy, deepcopy
from concurrent.futures import ThreadPoolExecutor
import json

from .resume_optimizer import ResumeOptimizer


class PreparationResumeOptimizer(ResumeOptimizer):
    def __init__(self, api_key):
        super().__init__(api_key)
        self.client = self.client.with_options(timeout=45, max_retries=0)

    def _call_openai_to_rewrite_bullets(self, experience_bullets, job_title, job_description,
                                      optimized_skills=None, guided_keywords=None):
        key = json.dumps([experience_bullets, job_title, job_description, optimized_skills, guided_keywords,
                          self._rewrite_density_context(experience_bullets)], sort_keys=True)
        cache = getattr(self, '_entry_rewrite_cache', {})
        if key in cache:
            return deepcopy(cache[key])

        def rewrite(entry):
            worker = copy(self)
            worker.ai_call_events, worker.ai_rewrite_pairs, worker.last_rewrite_diagnostics = [], [], []
            worker._rewrite_cache = {}
            result = ResumeOptimizer._call_openai_to_rewrite_bullets(worker, [entry], job_title, job_description,
                optimized_skills, guided_keywords)
            return result, worker

        result, failed, errors = [], False, []
        with ThreadPoolExecutor(max_workers=2) as pool:
            for entries, worker in pool.map(rewrite, experience_bullets):
                result.extend(entries)
                self.ai_call_events.extend(worker.ai_call_events)
                self.ai_rewrite_pairs.extend(worker.ai_rewrite_pairs)
                self.last_rewrite_diagnostics = [*getattr(self, 'last_rewrite_diagnostics', []), *worker.last_rewrite_diagnostics]
                failed = failed or worker.last_bullet_provider_failure
                if worker.last_bullet_rewrite_error:
                    errors.append(worker.last_bullet_rewrite_error)
        self.last_bullet_provider_failure = failed
        self.last_bullet_rewrite_error = '; '.join(errors) or None
        self.last_bullet_rewrite_error_kind = 'provider_error' if failed else None
        self._entry_rewrite_cache = {**cache, key: deepcopy(result)}
        return result

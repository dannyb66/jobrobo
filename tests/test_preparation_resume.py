from copy import deepcopy
import json
from types import SimpleNamespace
import unittest

from modules.ai.preparation_resume import PreparationResumeOptimizer
from modules.ai.resume_optimizer import ResumeOptimizer


class PreparationResumeTests(unittest.TestCase):
    def test_entries_are_independent_and_layout_retry_reuses_responses(self):
        optimizer = PreparationResumeOptimizer.__new__(PreparationResumeOptimizer)
        optimizer.ai_call_events, optimizer.ai_rewrite_pairs = [], []
        optimizer.rewrite_response_attempts = 1
        entries = [{'company': f'Company {i}', 'job_title': 'Engineer', 'bullets': [
            'Built reliable cloud services with Python and reviewed application changes for the engineering team.']} for i in range(3)]
        observed = []
        def request(stage, **kwargs):
            user = kwargs['messages'][1]['content']
            entry = next(e for e in entries if e['company'] in user)
            observed.append(user)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({'rewritten_experience': [entry]})))])
        optimizer._request_completion = request
        first = optimizer._call_openai_to_rewrite_bullets(entries, 'Staff Engineer', 'Build cloud systems')
        self.assertEqual(first, entries)
        self.assertEqual(len(observed), 3)
        for user in observed:
            self.assertEqual(sum(e['company'] in user for e in entries), 1)
        optimizer._call_openai_to_rewrite_bullets(entries, 'Staff Engineer', 'Build cloud systems')
        self.assertEqual(len(observed), 3)

    def test_repair_request_contains_failed_assistant_output(self):
        optimizer = ResumeOptimizer.__new__(ResumeOptimizer)
        optimizer.rewrite_response_attempts = 2
        entry = {'company': 'Test', 'job_title': 'Engineer', 'bullets': [
            'Built 10 reliable cloud services with Python and reviewed application changes for the engineering team.']}
        calls = []
        def request(stage, **kwargs):
            calls.append(deepcopy(kwargs['messages']))
            content = 'invalid JSON' if len(calls) == 1 else json.dumps({'rewritten_experience': [entry]})
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
        optimizer._request_completion = request
        optimizer._call_openai_to_rewrite_bullets([entry], 'Staff Engineer', 'Build cloud systems')
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][-2], {'role': 'assistant', 'content': 'invalid JSON'})
        self.assertIsNone(optimizer.last_bullet_rewrite_error)


if __name__ == '__main__':
    unittest.main()

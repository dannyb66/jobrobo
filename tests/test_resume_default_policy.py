"""Saved optimizer defaults remain bounded and cannot authorize application submission."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules import config_loader
from modules.ai.resume_optimizer import ResumeOptimizer


class ResumeDefaultPolicyTests(unittest.TestCase):
    def test_fresh_runtime_loads_full_mode_title_replacement_and_expanded_cap(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / 'runtime' / 'defaults.json'
            with patch.object(config_loader, 'RUNTIME_CONFIG_DIR', runtime.parent), patch.object(config_loader, 'RUNTIME_CONFIG_FILE', runtime):
                saved = config_loader.load_runtime_config()
            self.assertEqual(saved['optimization_mode'], 'full')
            self.assertIs(saved['replace_job_title'], True)
            self.assertEqual(saved['max_skills'], 65)
            self.assertFalse(saved.get('auto_submission_authorized', False))

    def test_explicit_mode_skills_cap_weights_and_extensions_remain_authoritative(self):
        existing = {'optimization_mode': 'skills', 'replace_job_title': False, 'max_skills': 12,
                    'match_weights': {'required': 4, 'preferred': 2, 'context': 1},
                    'layout_extension': {'preserve_lines': True}}
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory) / 'defaults.json'
            runtime.write_text(json.dumps(existing))
            before = runtime.read_bytes()
            with patch.object(config_loader, 'RUNTIME_CONFIG_DIR', runtime.parent), patch.object(config_loader, 'RUNTIME_CONFIG_FILE', runtime):
                saved = config_loader.load_runtime_config()
            for key, value in existing.items():
                self.assertEqual(saved[key], value)
            self.assertEqual(runtime.read_bytes(), before)

    def test_expanded_capacity_is_an_upper_bound_and_does_not_add_unsupported_skills(self):
        optimizer = ResumeOptimizer.__new__(ResumeOptimizer)
        optimizer.content_policy = 'grounded'
        skills = ['Source Tool ' + str(i) for i in range(80)]
        selected = optimizer.optimize_skills(skills, ['Unproven Quantum Tool'], 'Unproven Quantum Tool required', max_count=65,
                                             source_text='; '.join(skills))
        self.assertEqual(len(selected), 65)
        self.assertTrue(set(selected).issubset(skills))
        self.assertNotIn('Unproven Quantum Tool', selected)
        short = optimizer.optimize_skills(['Python', 'AWS'], [], 'Python', max_count=65, source_text='Python AWS')
        self.assertLessEqual(len(short), 2)


if __name__ == '__main__':
    unittest.main()

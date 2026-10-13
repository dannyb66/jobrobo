"""Test the actual session wrapper with pure planning and durable checkpoints."""

import ast
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from modules.ai.search_refinement import make_refiner
from modules.search_history import file_lock
from modules.search_planner import GATE_FIELDS, INTENT_FIELDS, build_search_plan
from modules.search_state import SearchManifest, plan_fingerprint


def session_wrapper(namespace):
    source = Path(__file__).resolve().parents[1] / "runAiBot.py"
    parsed = ast.parse(source.read_text())
    function = next(node for node in parsed.body if isinstance(node, ast.FunctionDef) and node.name == "apply_to_jobs")
    function.returns = None
    for argument in function.args.args:
        argument.annotation = None
    module = ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))
    exec(compile(module, str(source), "exec"), namespace)
    return namespace["apply_to_jobs"]


class SearchSessionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.state_directory = Path(self.temporary.name) / "runs"
        self.profile = SimpleNamespace(
            profile_name="session-test", profile_version="1", dynamic_search_enabled=True,
            ai_query_refinement_enabled=True, resume_search_enabled=True,
            search_state_dir=str(self.state_directory), role_lanes=["Staff AI Engineer"],
            skills=["Python", "distributed systems"],
            manual_searches=[{"id": "platform", "query": "Principal Platform Engineer", "enabled": True, "quota": 2}],
        )
        self.warnings = []
        self.manifests = []
        self.refiner_factory = Mock(return_value=None)
        self.shuffle = Mock(side_effect=lambda rows: rows.reverse())
        self.namespace = dict.fromkeys([*INTENT_FIELDS, *GATE_FIELDS])
        self.namespace.update({
            "search_location": "California", "date_posted": "Past month", "sort_by": "Most recent",
            "job_type": ["Full-time"], "on_site": ["Remote", "Hybrid"], "easy_apply_only": True,
            "bad_words": ["Citizenship required"], "security_clearance": False,
            "current_experience": -1, "did_masters": True,
            "switch_number": 1, "randomize_search_order": False,
            "use_AI": False, "use_AI_for_resume": False,
            "os": SimpleNamespace(path=os.path, getenv=lambda name: None),
            "llm_api_key": "", "llm_api_url": "https://api.openai.com/v1", "llm_model": "configured-model",
            "search_profile": self.profile,
            "build_search_plan": build_search_plan, "plan_fingerprint": plan_fingerprint,
            "file_lock": file_lock, "SearchManifest": SearchManifest,
            "make_refiner": self.refiner_factory, "shuffle": self.shuffle,
            "print_lg": self.warnings.append,
            "execute_search_plan": self.complete,
            "active_manifest": None, "active_search": None,
        })
        self.apply_to_jobs = session_wrapper(self.namespace)

    def complete(self, manifest):
        self.manifests.append(manifest)
        for search in manifest.queries():
            manifest.begin_query(search)
            manifest.finish_query(search, "results_exhausted")

    def interrupt_after_first_query(self, manifest):
        self.manifests.append(manifest)
        first, *remaining = manifest.queries()
        manifest.begin_query(first)
        manifest.record_job(first, "123", "applied", page=3)
        manifest.finish_query(first, "results_exhausted")
        if remaining:
            manifest.begin_query(remaining[0])
            self.namespace["active_search"] = remaining[0]
            manifest.record_job(remaining[0], "456", "in_progress", page=4)
        raise KeyboardInterrupt()

    def persisted(self):
        return [json.loads(path.read_text()) for path in self.state_directory.glob("*.json")]

    def refinement(self, *args):
        return {"queries": [{"role": "Staff AI Systems Engineer", "role_index": 0, "coverage": 0.9}]}

    def test_new_run_combines_manual_legacy_and_current_config_generated_queries(self):
        self.apply_to_jobs(["Principal Backend Engineer"])
        manifest = self.manifests[0]
        searches = [row["spec"] for row in manifest.data["queries"]]
        self.assertEqual([search["source"] for search in searches], ["manual", "legacy", "generated"])
        self.assertEqual(searches[0]["quota"], 2)
        self.assertEqual(searches[1]["quota"], 1)
        self.assertTrue(all(search["filters_snapshot"]["intent"]["search_location"] == "California" for search in searches))
        self.assertTrue(all("Remote, Hybrid" in search["query_text"] for search in searches))
        self.assertEqual(manifest.data["status"], "complete")
        self.assertIsNone(self.namespace["active_manifest"])
        self.assertIsNone(self.namespace["active_search"])

    def test_refinement_runs_independently_of_general_ai_and_resume_ai(self):
        self.refiner_factory.return_value = self.refinement
        self.apply_to_jobs([])
        sources = [row["spec"]["source"] for row in self.manifests[0].data["queries"]]
        self.assertEqual(sources, ["manual", "ai_refined"])
        self.refiner_factory.assert_called_once_with("", "https://api.openai.com/v1", "configured-model", self.namespace["print_lg"])

    def test_missing_key_refinement_warns_and_manual_searches_still_execute(self):
        self.namespace["make_refiner"] = make_refiner
        self.apply_to_jobs([])
        self.assertTrue(any("No OpenAI key" in warning for warning in self.warnings))
        self.assertEqual([row["spec"]["source"] for row in self.manifests[0].data["queries"]], ["manual", "generated"])

    def test_api_failure_keeps_manual_and_legacy_searches_plus_deterministic_fallback(self):
        self.refiner_factory.return_value = Mock(side_effect=RuntimeError("API temporarily unavailable"))
        self.apply_to_jobs(["Principal Backend Engineer"])
        self.assertEqual([row["spec"]["source"] for row in self.manifests[0].data["queries"]], ["manual", "legacy", "generated"])
        self.assertTrue(any("refinement failed" in warning for warning in self.warnings))
        self.assertEqual(self.manifests[0].data["status"], "complete")

    def test_resume_uses_saved_ai_queries_and_random_order_without_refining_again(self):
        self.namespace["randomize_search_order"] = True
        self.refiner_factory.return_value = self.refinement
        self.namespace["execute_search_plan"] = self.interrupt_after_first_query
        with self.assertRaises(KeyboardInterrupt):
            self.apply_to_jobs(["Principal Backend Engineer"])
        interrupted = self.persisted()[0]
        self.assertEqual(interrupted["status"], "interrupted")
        self.assertEqual(interrupted["stop_reason"], "KeyboardInterrupt")
        original_order = [row["spec"]["query_id"] for row in interrupted["queries"]]
        self.assertEqual(interrupted["queries"][0]["spec"]["source"], "ai_refined")
        self.refiner_factory.reset_mock()
        self.shuffle.reset_mock()
        self.namespace["llm_api_key"] = "a-new-key"
        self.namespace["execute_search_plan"] = self.complete
        self.apply_to_jobs(["Principal Backend Engineer"])
        resumed = self.manifests[-1]
        self.assertEqual(resumed.data["run_id"], interrupted["run_id"])
        self.assertEqual([row["spec"]["query_id"] for row in resumed.data["queries"]], original_order)
        self.assertEqual(resumed.data["queries"][0]["jobs"]["123"]["status"], "applied")
        self.assertEqual(resumed.data["queries"][0]["last_page"], 3)
        self.assertEqual(resumed.data["queries"][1]["last_page"], 1)
        self.refiner_factory.assert_not_called()
        self.shuffle.assert_not_called()
        self.assertEqual(len(self.persisted()), 1)

    def test_interruption_clears_active_globals_and_releases_session_lock(self):
        self.namespace["execute_search_plan"] = self.interrupt_after_first_query
        with self.assertRaises(KeyboardInterrupt):
            self.apply_to_jobs([])
        self.assertIsNone(self.namespace["active_manifest"])
        self.assertIsNone(self.namespace["active_search"])
        with file_lock(self.state_directory / ".runner.lock"):
            self.assertEqual(self.persisted()[0]["stop_reason"], "KeyboardInterrupt")

    def test_changed_location_creates_fresh_plan_from_current_config(self):
        self.namespace["execute_search_plan"] = self.interrupt_after_first_query
        with self.assertRaises(KeyboardInterrupt):
            self.apply_to_jobs([])
        original = self.persisted()[0]
        self.namespace["search_location"] = "Seattle"
        self.namespace["execute_search_plan"] = self.complete
        self.apply_to_jobs([])
        fresh = self.manifests[-1]
        self.assertNotEqual(fresh.data["run_id"], original["run_id"])
        self.assertTrue(all("Location: Seattle." in row["spec"]["query_text"] for row in fresh.data["queries"]))
        self.assertTrue(all(row["spec"]["filters_snapshot"]["intent"]["search_location"] == "Seattle" for row in fresh.data["queries"]))
        self.assertEqual(len(self.persisted()), 2)

    def test_profile_edit_preserves_manual_id_and_starts_new_run(self):
        self.namespace["execute_search_plan"] = self.interrupt_after_first_query
        with self.assertRaises(KeyboardInterrupt):
            self.apply_to_jobs([])
        original = self.persisted()[0]
        self.profile.profile_version = "2"
        self.profile.manual_searches[0]["query"] = "Principal Infrastructure Engineer"
        self.namespace["execute_search_plan"] = self.complete
        self.apply_to_jobs([])
        fresh = self.manifests[-1]
        self.assertNotEqual(fresh.data["run_id"], original["run_id"])
        self.assertEqual(fresh.data["queries"][0]["spec"]["query_id"], "manual:platform")
        self.assertIn("Principal Infrastructure Engineer", fresh.data["queries"][0]["spec"]["query_text"])
        self.assertEqual(fresh.data["profile_version"], "2")

    def test_disabling_resume_starts_new_run_without_overwriting_interrupted_run(self):
        self.namespace["execute_search_plan"] = self.interrupt_after_first_query
        with self.assertRaises(KeyboardInterrupt):
            self.apply_to_jobs([])
        original = self.persisted()[0]
        self.profile.resume_search_enabled = False
        self.namespace["execute_search_plan"] = self.complete
        self.apply_to_jobs([])
        self.assertNotEqual(self.manifests[-1].data["run_id"], original["run_id"])
        original_now = next(row for row in self.persisted() if row["run_id"] == original["run_id"])
        self.assertEqual(original_now, original)

    def test_runtime_sort_and_date_changes_are_fingerprinted(self):
        self.namespace["execute_search_plan"] = self.interrupt_after_first_query
        with self.assertRaises(KeyboardInterrupt):
            self.apply_to_jobs([])
        original = self.persisted()[0]
        self.namespace["sort_by"] = "Most relevant"
        self.namespace["date_posted"] = "Past week"
        self.namespace["execute_search_plan"] = self.complete
        self.apply_to_jobs([])
        fresh = self.manifests[-1]
        self.assertNotEqual(fresh.data["configuration_id"], original["configuration_id"])
        intent = fresh.data["queries"][0]["spec"]["filters_snapshot"]["intent"]
        self.assertEqual(intent["sort_by"], "Most relevant")
        self.assertEqual(intent["date_posted"], "Past week")

    def test_disabled_dynamic_and_ai_allow_manual_only_run(self):
        self.profile.dynamic_search_enabled = False
        self.profile.ai_query_refinement_enabled = False
        self.apply_to_jobs([])
        self.assertEqual(len(self.manifests[0].data["queries"]), 1)
        self.assertEqual(self.manifests[0].data["queries"][0]["spec"]["source"], "manual")
        self.refiner_factory.assert_not_called()

    def test_disabling_dynamic_with_exact_legacy_coverage_cannot_resume_old_ai_lanes(self):
        self.refiner_factory.return_value = self.refinement
        self.namespace["execute_search_plan"] = self.interrupt_after_first_query
        legacy = list(self.profile.role_lanes)
        with self.assertRaises(KeyboardInterrupt):
            self.apply_to_jobs(legacy)
        original = self.persisted()[0]
        self.assertIn("ai_refined", [row["spec"]["source"] for row in original["queries"]])
        self.profile.dynamic_search_enabled = False
        self.namespace["execute_search_plan"] = self.complete
        self.apply_to_jobs(legacy)
        fresh = self.manifests[-1]
        self.assertNotEqual(fresh.data["run_id"], original["run_id"])
        self.assertNotEqual(fresh.data["configuration_id"], original["configuration_id"])
        self.assertEqual([row["spec"]["source"] for row in fresh.data["queries"]], ["manual", "legacy"])

    def test_locked_session_prevents_second_runner_before_refinement_or_mutation(self):
        with file_lock(self.state_directory / ".runner.lock"):
            with self.assertRaises(OSError):
                self.apply_to_jobs([])
        self.assertEqual(self.persisted(), [])
        self.assertEqual(self.manifests, [])
        self.refiner_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()

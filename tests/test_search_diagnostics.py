"""A diagnostic reads search cards without application or persistence side effects."""

from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules.search_diagnostics import diagnostic_url, run_diagnostic
from modules.search_planner import SearchSpec
from modules.search_state import SearchManifest


class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "diagnostic.json"
        self.browser = Mock()
        self.browser.current_url = "https://www.linkedin.com/jobs/search-results/?keywords=Staff%20AI&geoId=90000084&f_TPR=r2592000&currentJobId=123&referralSearchId=opaque#details"
        self.bot = SimpleNamespace(
            driver=None, wait=None, actions=None, pause_after_filters=True,
            load_runtime=Mock(), initialize_browser=self.initialize,
            wait_for_search=Mock(), wait_for_search_results=Mock(), apply_filters=Mock(),
            apply_to_jobs=Mock(), execute_search_plan=Mock(), login_LN=Mock(),
        )
        self.result = SimpleNamespace(mode="ai", warnings=["Optional sort unavailable"], fallback_reason=None,
                                      diagnostics=lambda: {"transport": "native_ui", "verified_filters": ["job_type"]})
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.prepare = self.stack.enter_context(patch("modules.linkedin_search.prepare_search", return_value=self.result))
        self.stack.enter_context(patch("modules.linkedin_modern_search.get_search_cards", return_value=["one", "duplicate", "two"]))
        self.stack.enter_context(patch("modules.linkedin_modern_search.read_search_card", side_effect=[
            {"job_id": "123", "title": "Staff AI Engineer", "title_element": Mock()},
            {"job_id": "123", "title": "Staff AI Engineer"},
            {"job_id": "456", "title": "Principal Engineer"},
        ]))

    def initialize(self, **kwargs):
        self.bot.driver = self.browser
        return self.browser

    def test_one_configured_query_reads_unique_cards_and_closes_own_browser(self):
        result = run_diagnostic(self.bot, limit=2, output_path=self.output)
        self.assertEqual(result["errors"], [])
        self.assertEqual([row["job_id"] for row in result["cards"]], ["123", "456"])
        self.assertEqual(result["search"]["mode"], "ai")
        self.bot.load_runtime.assert_called_once_with("search")
        self.prepare.assert_called_once()
        self.bot.apply_to_jobs.assert_not_called()
        self.bot.execute_search_plan.assert_not_called()
        self.bot.login_LN.assert_not_called()
        self.browser.quit.assert_called_once()
        self.assertIsNone(self.bot.driver)
        self.assertTrue(self.bot.pause_after_filters)
        self.assertEqual(json.loads(self.output.read_text())["cards"], result["cards"])
        self.assertNotIn("referralSearchId", result["search"]["url"])
        self.assertNotIn("currentJobId", result["search"]["url"])

    def test_failure_writes_evidence_and_restores_browser_state(self):
        self.prepare.side_effect = ValueError("Exact location unavailable")
        result = run_diagnostic(self.bot, output_path=self.output)
        self.assertEqual(result["errors"][0]["message"], "Exact location unavailable")
        self.assertEqual(result["cards"], [])
        self.browser.quit.assert_called_once()
        self.assertTrue(self.output.exists())

    def test_does_not_close_reused_browser(self):
        self.bot.driver = self.browser
        run_diagnostic(self.bot, limit=1, output_path=self.output)
        self.browser.quit.assert_not_called()

    def test_png_output_path_keeps_json_and_screenshot_separate(self):
        output = self.output.with_suffix(".png")
        def save(path):
            Path(path).write_bytes(b"diagnostic screenshot")
            return True
        self.browser.save_screenshot.side_effect = save
        report = run_diagnostic(self.bot, limit=1, output_path=output)
        self.assertNotEqual(report["output_path"], report["screenshot"])
        self.assertEqual(Path(report["screenshot"]).read_bytes(), b"diagnostic screenshot")
        self.assertEqual(json.loads(output.read_text())["query_id"], report["query_id"])

    def test_rejects_manifest_directory_before_browser_creation(self):
        with patch("config.search_profile.search_state_dir", self.directory.name):
            with self.assertRaisesRegex(ValueError, "manifest"):
                run_diagnostic(self.bot, output_path=self.output)
        self.bot.load_runtime.assert_not_called()

    def test_rejects_application_csv_and_pipeline_database_output_paths(self):
        from config import settings, job_pipeline
        for setting, name in ((settings, "file_name"), (settings, "failed_file_name"), (job_pipeline, "db_path")):
            with self.subTest(name=name), patch.object(setting, name, str(self.output)):
                with self.assertRaisesRegex(ValueError, "history"):
                    run_diagnostic(self.bot, output_path=self.output)
        self.bot.load_runtime.assert_not_called()

    def test_url_retains_encoded_prompt_and_filters_without_tracking(self):
        url = diagnostic_url("https://www.linkedin.com/jobs/search-results/?keywords=AI+%26+ML&f_SAL=x%3Ay%24z%3Aa&origin=tracking&referralSearchId=secret")
        self.assertIn("keywords=AI+%26+ML", url)
        self.assertIn("f_SAL=x%3Ay%24z%3Aa", url)
        self.assertNotIn("secret", url)

    def test_manifest_diagnostics_survive_resume_and_legacy_updates(self):
        spec = SearchSpec("manual:test", "Staff AI", "manual", "ai", "test", "1", {}, 1, "Staff AI")
        manifest = SearchManifest.create(Path(self.directory.name) / "runs", [spec])
        evidence = {"transport": "verified_url", "verified_filters": ["date_posted"],
                    "location_confirmation": {"location": "California", "geography": {"geoId": ["123"]}}}
        manifest.record_mode(spec, "ai", diagnostics=evidence)
        manifest.record_mode(spec, "ai", warnings=["Sort unavailable"])
        manifest.interrupt("KeyboardInterrupt")
        resumed = SearchManifest.find_resume(manifest.path.parent, manifest.data["configuration_id"])
        self.assertEqual(resumed.query(spec.query_id)["search_diagnostics"], evidence)
        self.assertEqual(resumed.query(spec.query_id)["warnings"], ["Sort unavailable"])


if __name__ == "__main__":
    unittest.main()

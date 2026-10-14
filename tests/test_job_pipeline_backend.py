"""Exercise the shared backend with SQLite and mocked runtime/browser operations."""

from contextlib import ExitStack
from copy import deepcopy
import importlib
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from config import search as canonical_search
from modules.job_pipeline.models import LinkedInRunRequest, StageResult
from modules.job_pipeline.store import PipelineStore
from modules.search_state import SearchManifest

from test_job_pipeline_linkedin import NOW, FrozenDatetime, config, job, profile, role


class SharedBackendTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.db = self.directory / "pipeline.sqlite3"
        self.bot = importlib.import_module("runAiBot")
        self.driver = SimpleNamespace(window_handles=["tab"], current_window_handle="tab", get=Mock())
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.multiple(canonical_search, **config()))
        self.stack.enter_context(patch("modules.job_pipeline.linkedin.datetime", FrozenDatetime))
        self.stack.enter_context(patch("modules.job_pipeline.careers.datetime", FrozenDatetime))
        settings = {**profile(), "search_state_dir": str(self.directory / "manifests"),
                    "resume_search_enabled": True, "manual_searches": []}
        self.stack.enter_context(patch.object(self.bot, "search_profile", SimpleNamespace(**settings)))
        self.stack.enter_context(patch.object(self.bot, "driver", self.driver))
        self.stack.enter_context(patch.object(self.bot, "aiClient", None))
        self.stack.enter_context(patch.object(self.bot, "use_AI", False, create=True))
        self.stack.enter_context(patch.object(self.bot, "pause_before_submit", False, create=True))
        self.runtime = self.stack.enter_context(patch.object(self.bot, "load_runtime"))
        self.browser = self.stack.enter_context(patch.object(self.bot, "initialize_browser", return_value=self.driver))
        self.stack.enter_context(patch.object(self.bot, "is_logged_in_LN", return_value=True))
        self.validation = self.stack.enter_context(patch.object(self.bot, "validate_config", create=True))
        self.collect = self.stack.enter_context(patch.object(self.bot, "collect_linkedin_jobs", return_value=([], [])))
        self.apply = self.stack.enter_context(patch.object(self.bot, "apply_to_jobs", return_value=None))

    def artifact(self, stage, records, set_name="input"):
        return StageResult.create(stage, set_name, "import:" + stage + ":" + set_name, records).to_dict()

    def request(self, mode="search", records=None, set_name="output", **kwargs):
        stage = "linkedin_jobs" if mode == "apply" else "verified_roles"
        if records is None:
            records = [job()] if mode == "apply" else [role()]
        return LinkedInRunRequest(mode, [self.artifact(stage, records)], set_name, db_path=str(self.db), **kwargs)

    def test_search_only_persists_matches_and_never_invokes_application_runtime(self):
        candidate = job()

        def collect(specs, **kwargs):
            kwargs["result_sink"](candidate)
            return [candidate], []

        self.collect.side_effect = collect
        result = self.bot.run_pipeline(self.request())
        self.assertEqual(result.stage, "linkedin_jobs")
        self.assertEqual([row["linkedin_id"] for row in result.records], ["123"])
        self.assertEqual(result.records[0]["search_run_id"], result.run_id)
        self.runtime.assert_called_once_with("search")
        self.validation.assert_not_called()
        self.apply.assert_not_called()
        self.assertEqual(len(result.delta), 1)

    def test_apply_uses_only_edited_subset_of_cumulative_named_set(self):
        with PipelineStore(self.db) as store:
            store.import_artifact(self.artifact("linkedin_jobs", [job("123"), job("456")]))
        result = self.bot.run_pipeline(self.request("apply", [job("123")]))
        self.collect.assert_not_called()
        selection = self.apply.call_args.kwargs["selected_jobs"]
        self.assertEqual([row["linkedin_id"] for rows in selection.values() for row in rows], ["123"])
        self.assertEqual(result.stage, "applications")
        self.assertTrue(self.bot.pause_before_submit)
        self.runtime.assert_called_once_with("apply")

    def test_current_closed_parent_overrides_open_parent_embedded_in_old_export(self):
        old_job = job()
        with PipelineStore(self.db) as store:
            closed = role(status="closed", eligible=False)
            store.upsert_many("verified_roles", "current", [closed], "closure-run")
        result = self.bot.run_pipeline(self.request("apply", [old_job]))
        self.browser.assert_not_called()
        self.runtime.assert_not_called()
        self.apply.assert_not_called()
        self.assertEqual(result.records[0]["status"], "skipped")
        self.assertIn("parent", result.records[0]["reason"].lower())

    def test_old_eligible_flag_with_new_current_exclusion_does_not_start_browser(self):
        with patch.object(canonical_search, "bad_words", ["production platform"]):
            result = self.bot.run_pipeline(self.request())
        self.browser.assert_not_called()
        self.assertIn("current_config_exclusion", {row["code"] for row in result.errors})

    def test_imported_application_success_or_uncertainty_is_skipped_across_sets(self):
        for outcome in ("applied", "submitting"):
            with self.subTest(outcome=outcome):
                candidate = job("123" if outcome == "applied" else "456")
                with PipelineStore(self.db) as store:
                    store.import_artifact(self.artifact("applications", [{"id": "old:" + candidate["linkedin_id"], "job_id": candidate["linkedin_id"], "status": outcome}], "old-applications"))
                self.browser.reset_mock()
                self.apply.reset_mock()
                result = self.bot.run_pipeline(self.request("apply", [candidate], set_name="new-applications"))
                self.apply.assert_not_called()
                self.browser.assert_not_called()
                selected_outcome = next(row for row in result.records if row["job_id"] == candidate["linkedin_id"])
                self.assertEqual(selected_outcome["status"], outcome)

    def test_successful_outcome_remains_durable_if_interrupted_after_callback(self):
        def apply(terms, *, prepared_specs, selected_jobs, result_sink, job_limit=None, application_budget=None):
            candidate = next(iter(selected_jobs.values()))[0]
            result_sink({**candidate, "status": "applied", "reason": "Submitted before interruption"})
            raise KeyboardInterrupt()

        self.apply.side_effect = apply
        result = self.bot.run_pipeline(self.request("apply"))
        self.assertEqual(result.records[0]["status"], "applied")
        self.assertIn("KeyboardInterrupt", {row["code"] for row in result.errors})
        with PipelineStore(self.db) as store:
            self.assertEqual(store.application_for_job("123")["status"], "applied")
            self.assertEqual(store.get_run(result.run_id)["status"], "interrupted")

    def test_search_resume_checkpoint_is_reused_between_invocations(self):
        saved = {"fingerprint": "test-query", "processed_ids": ["123"], "last_page": 3, "complete": False}

        def first_collect(specs, **kwargs):
            kwargs["checkpoint_sink"](specs[0].query_id, saved)
            return [], []

        self.collect.side_effect = first_collect
        self.bot.run_pipeline(self.request())
        self.collect.side_effect = None
        self.bot.run_pipeline(self.request())
        self.assertEqual(next(iter(self.collect.call_args.kwargs["checkpoints"].values())), saved)

    def test_real_application_manifest_resumes_with_shared_entrypoint_identity(self):
        # Keep the real apply_to_jobs wrapper; replace only browser execution.
        # Extract the real wrapper to avoid importing any runtime configuration.
        from test_search_runner import extract_functions
        namespace = {
            "active_manifest": None, "active_search": None, "search_profile": self.bot.search_profile,
            "plan_fingerprint": self.bot.plan_fingerprint, "SearchManifest": SearchManifest,
            "file_lock": self.bot.file_lock, "os": self.bot.os, "print_lg": lambda *args: None,
            "randomize_search_order": False, "execute_search_plan": Mock(),
        }
        extract_functions(namespace, "apply_to_jobs")
        from modules.job_pipeline.linkedin import selected_specs
        specs, selected, errors = selected_specs([job()], profile(), config())
        self.assertEqual(errors, [])

        def interruption(manifest, **kwargs):
            manifest.begin_query(manifest.queries()[0])
            manifest.interrupt("entrypoint interruption")

        namespace["execute_search_plan"].side_effect = interruption
        first = namespace["apply_to_jobs"]([], prepared_specs=specs, selected_jobs=selected)
        second = namespace["apply_to_jobs"]([], prepared_specs=deepcopy(specs), selected_jobs=deepcopy(selected))
        self.assertEqual(first.data["run_id"], second.data["run_id"])
        self.assertEqual(first.data["configuration_id"], second.data["configuration_id"])

    def live_reader(self, url="https://www.linkedin.com/jobs/view/123", location="California, United States", employment="Full-time", posted="1 day ago"):
        from modules.job_pipeline.linkedin import prepare_specs
        specs, errors = prepare_specs([role()], profile(), config())
        self.assertEqual(errors, [])
        self.driver.current_url = url
        employer = SimpleNamespace(text="Example AI", get_attribute=lambda attribute: "https://www.linkedin.com/company/example-ai")

        def elements(by, selector):
            if "company-name" in selector:
                return [employer]
            if "primary-description" in selector:
                return [SimpleNamespace(text=location)]
            if "job-insight" in selector:
                return [SimpleNamespace(text="Remote " + employment)]
            if "tertiary-description" in selector or "posted-date" in selector:
                return [SimpleNamespace(text=posted)] if posted else []
            return []

        self.driver.find_elements = Mock(side_effect=elements)
        with patch.object(self.bot, "By", SimpleNamespace(TAG_NAME="tag", CSS_SELECTOR="css"), create=True), \
                patch.object(self.bot, "EC", SimpleNamespace(presence_of_element_located=lambda value: value), create=True), \
                patch.object(self.bot, "WebDriverWait", lambda *args: SimpleNamespace(until=lambda condition: SimpleNamespace(text="Staff AI Platform Engineer")), create=True), \
                patch.object(self.bot, "calculate_date_posted", return_value=NOW, create=True):
            candidate = job()
            details = self.bot.selected_live_details(candidate, specs[0])
        return candidate, details

    def test_actual_live_reader_rejects_redirect_to_unselected_id_before_details(self):
        for url in ("https://www.linkedin.com/jobs/view/456", "https://www.linkedin.com/jobs/search/?currentJobId=456", "https://example.com/jobs/view/123"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.live_reader(url=url)
        self.driver.find_elements.assert_not_called()

    def test_actual_live_reader_retains_known_employment_location_and_posted_date(self):
        candidate, details = self.live_reader()
        self.assertEqual(details[0], "123")
        self.assertFalse(details[-1])
        self.assertEqual(candidate["_live_details"]["employment_type"], "Full-time")
        self.assertEqual(candidate["_live_details"]["workplace_type"], "Remote")
        self.assertEqual(candidate["_live_details"]["locations"], ["California, United States"])
        self.assertEqual(candidate["_live_details"]["published_at"], NOW.isoformat())

    def test_live_employment_location_or_missing_date_changes_are_rejected_by_current_gates(self):
        from modules.job_pipeline.careers import evaluate_role

        for kwargs, expected in (({"employment": "Contract"}, "employment_type_excluded"),
                                 ({"location": "London, United Kingdom"}, "location_excluded"),
                                 ({"posted": ""}, "unknown_posted_date")):
            with self.subTest(kwargs=kwargs):
                candidate, details = self.live_reader(**kwargs)
                live = {**candidate["_live_details"], "title": details[1], "description": role()["description"],
                        "company": role()["company"], "status": "open"}
                result = evaluate_role(live, config())
                self.assertFalse(result["eligible"])
                self.assertIn(expected, result["exclusion_reasons"])


if __name__ == "__main__":
    unittest.main()

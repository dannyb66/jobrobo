"""Frontend safety and real LinkedIn pipeline dispatch regression tests."""

from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
from unittest.mock import Mock, PropertyMock, patch

from modules.search_state import plan_fingerprint

from modules.job_pipeline.models import StageResult, write_artifact


ROOT = Path(__file__).resolve().parents[1]


class PipelineImportSafetyTests(unittest.TestCase):
    """Execute actual entrypoints while forbidding browser/key bootstrap imports."""

    def isolated_frontend(self, body):
        script = """
import importlib.abc
import runpy
import sys

class RuntimeImportGuard(importlib.abc.MetaPathFinder):
    forbidden = {
        'modules.open_chrome',
        'modules.ai.openai_key_loader',
        'modules.ai.openaiConnections',
        'pyautogui',
        'selenium',
        'openai',
        'undetected_chromedriver',
    }

    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.forbidden:
            raise AssertionError('Runtime bootstrap imported: ' + fullname)
        return None

sys.meta_path.insert(0, RuntimeImportGuard())
sys.path.insert(0, sys.argv[1])
""" + body
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                [sys.executable, "-B", "-c", script, str(ROOT)],
                cwd=directory, capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(list(Path(directory).iterdir()), [], "Help/import created runtime state")
            return completed.stdout

    def test_importing_both_frontends_never_loads_browser_or_key_services(self):
        output = self.isolated_frontend("\nimport runAiBot\nimport job_pipeline\nprint('IMPORT_OK')\n")
        self.assertEqual(output.strip(), "IMPORT_OK")

    def test_standalone_help_never_loads_browser_or_key_services(self):
        output = self.isolated_frontend(
            "\nsys.argv = ['job_pipeline', '--help']\nrunpy.run_module('job_pipeline', run_name='__main__')\n"
        )
        self.assertIn("discover", output)
        self.assertIn("linkedin", output.lower())

    def test_bare_standalone_command_prints_help_without_runtime(self):
        output = self.isolated_frontend(
            "\nsys.argv = ['job_pipeline']\nrunpy.run_module('job_pipeline', run_name='__main__')\n"
        )
        self.assertIn("usage:", output.lower())

    def test_legacy_frontend_help_never_loads_browser_or_key_services(self):
        output = self.isolated_frontend(
            "\nsys.argv = ['runAiBot.py', '--help']\nrunpy.run_module('runAiBot', run_name='__main__')\n"
        )
        self.assertIn("--mode", output)
        self.assertIn("search-and-apply", output)

    def test_importing_browser_factory_never_loads_runtime_dependencies(self):
        output = self.isolated_frontend(
            "\nRuntimeImportGuard.forbidden.remove('modules.open_chrome')\n"
            "import modules.open_chrome\nprint('FACTORY_IMPORT_OK')\n"
        )
        self.assertEqual(output.strip(), "FACTORY_IMPORT_OK")


class PipelineFrontendTests(unittest.TestCase):
    """Parse actual commands and preserve the shared request/result contract."""

    def setUp(self):
        import job_pipeline
        import runAiBot

        self.cli, self.bot = job_pipeline, runAiBot
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.db = str(self.root / "pipeline.sqlite3")
        self.output = self.root / "result.json"

    def artifact(self, stage, set_name, records):
        artifact = StageResult.create(stage, set_name, "input-run", records)
        path = self.root / f"{set_name}.json"
        write_artifact(artifact, path)
        return artifact, path

    def invoke(self, arguments, response):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(self.bot, "run_pipeline", return_value=response) as backend:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                status = self.cli.main(arguments)
        return status, stdout.getvalue(), stderr.getvalue(), backend

    def assert_input_identity(self, payload, artifact):
        for field in ("schema_version", "stage", "set_name", "run_id", "created_at", "input_set_ids", "errors"):
            self.assertEqual(payload[field], artifact[field], field)
        self.assertEqual(payload["records"], artifact.records)

    def test_standalone_search_preserves_request_identity_and_exports_response_metadata(self):
        artifact, path = self.artifact("verified_roles", "verified", [{
            "id": "modal-role", "company_id": "modal", "title": "Member of Technical Staff",
            "description": "Build Python inference infrastructure", "eligible": True, "status": "open",
        }])
        response = StageResult.create("linkedin_jobs", "candidates", "collect-run", [{
            "job_id": "123", "verified_role_id": "modal-role", "company_id": "modal",
            "query_id": "manual:modal", "query_text": "Find Modal inference roles.",
            "search_mode": "classic", "search_run_id": "historical-query-run",
        }], input_set_ids=["verified_roles:verified"])
        status, stdout, stderr, backend = self.invoke([
            "search", "linkedin", "--input", str(path), "--set", "candidates",
            "--limit", "3", "--db", self.db, "--output", str(self.output),
        ], response)
        self.assertEqual((status, stderr), (0, ""))
        request = backend.call_args.args[0]
        self.assertEqual(request.mode, "search")
        self.assertEqual(len(request.input_sets), 1)
        self.assert_input_identity(request.input_sets[0], artifact)
        self.assertEqual((request.set_name, request.limit, request.db_path), ("candidates", 3, self.db))
        self.assertEqual(request.output_path, str(self.output))
        self.assertEqual(json.loads(stdout), response.to_dict())
        self.assertEqual(json.loads(self.output.read_text()), response.to_dict())

    def test_apply_receives_only_explicit_input_ids_and_keeps_query_provenance(self):
        artifact, path = self.artifact("linkedin_jobs", "selected", [{
            "id": "123", "job_id": "123", "company_id": "modal",
            "query_id": "generated:original", "query_text": "Find staff inference roles.",
            "search_mode": "ai", "search_run_id": "original-search-run",
        }])
        response = StageResult.create("applications", "reviewed", "apply-run", [{
            **artifact.records[0], "status": "applied",
        }], input_set_ids=["linkedin_jobs:selected"])
        status, stdout, stderr, backend = self.invoke([
            "apply", "linkedin", "--input", str(path), "--set", "reviewed",
            "--limit", "1", "--db", self.db,
        ], response)
        self.assertEqual((status, stderr), (0, ""))
        request = backend.call_args.args[0]
        self.assertEqual(request.mode, "apply")
        self.assertEqual([row["job_id"] for payload in request.input_sets for row in payload["records"]], ["123"])
        self.assertEqual(request.input_sets[0]["records"][0]["query_id"], "generated:original")
        self.assertEqual(json.loads(stdout)["records"][0]["search_run_id"], "original-search-run")

    def test_combined_cli_normalizes_to_shared_search_and_apply_mode(self):
        artifact, path = self.artifact("verified_roles", "verified", [{"id": "modal-role"}])
        response = StageResult.create("applications", "combined", "combined-run", [])
        status, _, _, backend = self.invoke([
            "run", "linkedin", "--input", str(path), "--set", "combined",
            "--db", self.db, "--refresh",
        ], response)
        self.assertEqual(status, 0)
        request = backend.call_args.args[0]
        self.assertEqual(request.mode, "search-and-apply")
        self.assertTrue(request.refresh)
        self.assert_input_identity(request.input_sets[0], artifact)

    def test_repeated_inputs_preserve_both_validated_stage_payloads(self):
        first, first_path = self.artifact("verified_roles", "one", [{"id": "role-one"}])
        second, second_path = self.artifact("verified_roles", "two", [{"id": "role-two"}])
        response = StageResult.create("linkedin_jobs", "merged", "merge-run", [])
        status, _, _, backend = self.invoke([
            "search", "linkedin", "--input", str(first_path), "--input", str(second_path),
            "--set", "merged", "--db", self.db,
        ], response)
        self.assertEqual(status, 0)
        payloads = backend.call_args.args[0].input_sets
        self.assertEqual(len(payloads), 2)
        self.assert_input_identity(payloads[0], first)
        self.assert_input_identity(payloads[1], second)

    def test_wrong_stage_input_never_calls_shared_runtime(self):
        _, path = self.artifact("companies", "companies", [{"id": "modal", "name": "Modal"}])
        response = StageResult.create("applications", "reviewed", "never", [])
        status, _, stderr, backend = self.invoke([
            "apply", "linkedin", "--input", str(path), "--db", self.db,
        ], response)
        self.assertEqual(status, 2)
        self.assertIn("Expected linkedin_jobs artifact", stderr)
        backend.assert_not_called()

    def test_partial_stage_result_still_exports_records_and_errors(self):
        _, path = self.artifact("verified_roles", "verified", [{"id": "role"}])
        response = StageResult.create("linkedin_jobs", "partial", "partial-run", [{"job_id": "123"}],
                                      errors=[{"code": "query_interrupted", "message": "Browser disconnected"}])
        status, stdout, stderr, _ = self.invoke([
            "search", "linkedin", "--input", str(path), "--set", "partial",
            "--db", self.db, "--output", str(self.output),
        ], response)
        self.assertEqual((status, stderr), (1, ""))
        self.assertEqual(json.loads(stdout), response.to_dict())
        self.assertEqual(json.loads(self.output.read_text()), response.to_dict())

    def test_native_empty_arguments_preserve_legacy_bot_dispatch(self):
        with patch.object(self.bot, "run_bot") as legacy, patch.object(self.bot, "run_pipeline") as pipeline:
            self.assertEqual(self.bot.cli_main([]), 0)
        legacy.assert_called_once_with()
        pipeline.assert_not_called()


class SelectedApplicationRunnerTests(unittest.TestCase):
    """Exercise the real Easy Apply loop with only explicitly selected job IDs."""

    def setUp(self):
        import test_search_runner as harness

        self.harness = harness
        self.runner = harness.SearchRunnerTests(methodName="test_ai_mode_records_natural_language_query_in_successful_history")
        self.runner.setUp()
        self.addCleanup(self.runner.doCleanups)
        self.namespace = self.runner.namespace
        self.harness.extract_functions(self.namespace, "application_outcome")
        self.opened, self.revalidated = [], []
        self.runner.browser.get = self.opened.append
        self.namespace["start_search"] = lambda *args: self.fail("Selected application started an unrelated keyword search")
        self.namespace["apply_filters"] = lambda *args: self.fail("Selected application changed the saved search")
        self.namespace["selected_live_details"] = self.live_details
        self.namespace["get_job_description"] = lambda: (
            "Build software platform infrastructure with Python", 1, False, "", "",
        )

    def live_details(self, record, search):
        job_id = record["job_id"]
        self.revalidated.append(job_id)
        self.runner.visited.append(job_id)
        return job_id, "Staff Platform Engineer", "Example", "California", "Remote", False

    def search(self, query_id="original-lane", quota=1):
        search = self.harness.spec(query_id, quota)
        search.mode = "classic"
        search.query_text = "Find staff platform roles in California."
        search.classic_query = "Staff Platform Engineer"
        company = {"id": "example", "name": "Example", "domain": "example.com", "employee_count": 80}
        search.pipeline_context = {
            "company": company, "company_id": "example", "career_job_ids": ["official-platform-role"],
            "career_roles": [{
                "id": "official-platform-role", "company": company, "company_id": "example",
                "title": "Staff Platform Engineer", "description": "Build Python platform systems",
                "status": "open", "eligible": True, "verified_at": datetime.now(timezone.utc).isoformat(),
            }],
        }
        return search

    def selected(self, search, *job_ids):
        return {search.query_id: [{
            "id": job_id, "job_id": job_id, "linkedin_id": job_id,
            "job_link": f"https://www.linkedin.com/jobs/view/{job_id}",
            "url": f"https://www.linkedin.com/jobs/view/{job_id}",
            "query_id": search.query_id, "query_text": search.query_text,
            "search_mode": search.mode, "search_run_id": "original-search-run",
            "company_id": "example", "verified_role_id": "official-platform-role",
            "company": search.pipeline_context["company"], "eligible": True,
            "career_job_ids": search.pipeline_context["career_job_ids"],
            "career_roles": search.pipeline_context["career_roles"],
        } for job_id in job_ids]}

    def execute(self, manifest, selection, sink=None):
        self.namespace["active_manifest"] = manifest
        self.namespace["execute_search_plan"](manifest, selected_jobs=selection, result_sink=sink)
        manifest.finish()

    def test_apply_revisits_selected_id_and_preserves_original_query_metadata(self):
        search = self.search()
        manifest = self.runner.manifest([search], {search.query_id: [["99", "123", "456"]]})
        results = []
        self.execute(manifest, self.selected(search, "123"), results.append)
        self.assertEqual(self.revalidated, ["123"])
        self.assertEqual(self.opened, ["https://www.linkedin.com/jobs/view/123"])
        self.assertEqual(self.runner.events.count("Submit application"), 1)
        row = self.runner.rows()[0]
        self.assertEqual(row["Job ID"], "123")
        self.assertEqual(row["Search Query ID"], search.query_id)
        self.assertEqual(row["Search Query"], "Staff Platform Engineer")
        self.assertEqual(row["Search Mode"], "classic")
        self.assertEqual(manifest.query(search.query_id)["applied_count"], 1)
        self.assertTrue(results)

    def test_revalidation_rejection_never_fills_quota_with_unselected_jobs(self):
        search = self.search(quota=2)
        manifest = self.runner.manifest([search], {search.query_id: [["99", "123", "456"]]})

        def reject(record, spec):
            job_id = record["job_id"]
            self.revalidated.append(job_id)
            return job_id, "Junior Engineer", "Different Company", "California", "Remote", True

        self.namespace["selected_live_details"] = reject
        self.execute(manifest, self.selected(search, "123"))
        self.assertEqual(self.revalidated, ["123"])
        self.assertEqual(self.opened, ["https://www.linkedin.com/jobs/view/123"])
        self.assertNotIn("Submit application", self.runner.events)
        self.assertEqual(manifest.query(search.query_id)["applied_count"], 0)
        self.assertFalse((self.runner.directory / "applied.csv").exists())
        self.assertIn(manifest.query(search.query_id)["jobs"]["123"]["status"], {"skipped", "failed"})

    def test_application_resume_skips_success_and_retries_remaining_selected_id(self):
        search = self.search(quota=2)
        manifest = self.runner.manifest([search], {search.query_id: [["99", "123", "456"]]})
        manifest.record_job(search, "123", "applied", "Saved before interruption")
        manifest.interrupt("KeyboardInterrupt")
        resumed = self.harness.SearchManifest.find_resume(
            self.runner.directory / "state", self.harness.plan_fingerprint([search]),
        )
        self.execute(resumed, self.selected(search, "123", "456"))
        self.assertEqual(self.revalidated, ["456"])
        self.assertEqual(self.opened, ["https://www.linkedin.com/jobs/view/456"])
        self.assertEqual(self.runner.events.count("Submit application"), 1)
        self.assertEqual(resumed.query(search.query_id)["applied_count"], 2)


class SelectedQueryProvenanceTests(unittest.TestCase):
    def test_current_revalidation_filters_do_not_relabel_historical_discovery_query(self):
        from config import search, search_profile
        from modules.job_pipeline.linkedin import mapping, prepare_specs, selected_specs

        company = {"id": "example", "name": "Example", "domain": "example.com", "employee_count": 80}
        role = {
            "id": "official-platform-role", "company": company, "company_id": "example",
            "title": "Staff Platform Engineer", "description": "Build software platform systems",
            "eligible": True, "status": "open", "verified_at": datetime.now(timezone.utc).isoformat(),
            "workplace_type": "Remote", "employment_type": "Full-time", "locations": ["United States"],
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        original, errors = prepare_specs([role], search_profile, search)
        self.assertEqual(errors, [])
        original = original[0]
        original.query_id = "career_verified:historical-query"
        original.mode = "classic"
        job = {
            "id": "linkedin:123", "linkedin_id": "123", "eligible": True,
            "company": company, "company_id": company["id"],
            "career_roles": [role], "career_job_ids": [role["id"]],
            "search_spec": original.to_dict(), "query_id": original.query_id,
            "query_text": original.query_text, "classic_query": original.classic_query,
            "search_source": original.source, "profile_name": original.profile_name,
            "profile_version": original.profile_version, "search_mode": original.mode,
            "search_run_id": "historical-search-run",
        }
        current_config = dict(mapping(search), search_location="Seattle, Washington, United States")
        current_profile = dict(mapping(search_profile), profile_version="next-profile-version")
        prepared, selected, errors = selected_specs([job], current_profile, current_config)
        self.assertEqual(errors, [])
        self.assertEqual(len(prepared), 1)
        restored = prepared[0]
        self.assertEqual(restored.query_id, original.query_id)
        self.assertEqual(restored.query_text, original.query_text)
        self.assertEqual(restored.classic_query, original.classic_query)
        self.assertEqual(restored.mode, "classic")
        self.assertEqual(restored.source, original.source)
        self.assertEqual((restored.profile_name, restored.profile_version),
                         (original.profile_name, original.profile_version))
        self.assertEqual(restored.filters_snapshot["intent"]["search_location"], current_config["search_location"])
        self.assertEqual(list(selected), [original.query_id])
        self.assertEqual(selected[original.query_id][0]["search_run_id"], "historical-search-run")


class CollectionOnlyRunnerTests(unittest.TestCase):
    """Run the actual search collector against browser cards with application guards."""

    def setUp(self):
        import test_search_runner as harness

        self.harness = harness
        self.runner = harness.SearchRunnerTests(methodName="test_ai_mode_records_natural_language_query_in_successful_history")
        self.runner.setUp()
        self.addCleanup(self.runner.doCleanups)
        self.namespace = self.runner.namespace
        harness.extract_functions(self.namespace, "collect_linkedin_jobs")
        self.search = harness.spec("verified-platform-query")
        self.search.pipeline_context = {
            "company": {"id": "example", "name": "Example", "domain": "example.com"},
            "company_id": "example", "career_job_ids": ["official-platform-role"],
            "career_roles": [{"id": "official-platform-role", "title": "Staff Platform Engineer"}],
            "verification_run_ids": ["official-verification-run"], "priority_tier": 1,
        }
        self.namespace.update({
            "plan_fingerprint": plan_fingerprint,
            "get_page_info": lambda: (None, 1),
            "get_job_main_details": self.details,
            "get_job_description": lambda: ("Build software platform infrastructure", 1, False, "", ""),
        })
        self.application_guards = {}
        for name in ("try_xp", "wait_span_click", "upload_optimized_resume", "upload_resume",
                     "answer_questions", "follow_company", "checkpoint_job", "submitted_jobs", "failed_job"):
            guard = Mock(side_effect=AssertionError(f"Application path reached during collection: {name}"))
            self.application_guards[name] = guard
            self.namespace[name] = guard

    def details(self, job, *args, **kwargs):
        self.assertTrue(kwargs.get("read_only"), "Collector did not select the read-only card reader")
        self.runner.visited.append(job.job_id)
        title = "Junior Platform Engineer" if job.job_id == "2" else "Staff Platform Engineer"
        company = "Example Consulting" if job.job_id == "99" else "Example"
        return job.job_id, title, company, "United States", "Remote", False

    def collect(self, ids, **kwargs):
        self.runner.browser.pages = {self.search.query_id: [ids]}
        return self.namespace["collect_linkedin_jobs"]([self.search], **kwargs)

    def test_search_mode_filters_identity_and_level_without_entering_application_paths(self):
        saved, checkpoints = [], {}
        records, errors = self.collect(
            ["1", "99", "2"], limit=25, result_sink=saved.append,
            checkpoint_sink=lambda query_id, value: checkpoints.update({query_id: value}),
        )
        self.assertEqual(errors, [])
        self.assertEqual([row["linkedin_id"] for row in records], ["1"])
        self.assertEqual(saved, records)
        self.assertEqual(records[0]["query_id"], self.search.query_id)
        self.assertEqual(records[0]["search_mode"], "classic")
        self.assertEqual(records[0]["fallback_reason"], "AI search unavailable")
        self.assertEqual(records[0]["career_job_ids"], ["official-platform-role"])
        self.assertEqual(records[0]["search_spec"]["query_id"], self.search.query_id)
        self.assertTrue(checkpoints[self.search.query_id]["complete"])
        self.assertEqual(set(checkpoints[self.search.query_id]["processed_ids"]), {"1", "99", "2"})
        for guard in self.application_guards.values():
            guard.assert_not_called()
        self.assertEqual(self.runner.events, [])
        self.assertFalse((self.runner.directory / "applied.csv").exists())
        self.assertFalse((self.runner.directory / "state").exists())

    def test_partial_collection_resumes_at_page_one_without_recollecting_saved_ids(self):
        checkpoints = {}
        checkpoint_sink = lambda query_id, value: checkpoints.update({query_id: value})
        first, errors = self.collect(["1", "3"], limit=1, checkpoint_sink=checkpoint_sink)
        self.assertEqual(errors, [])
        self.assertEqual([row["linkedin_id"] for row in first], ["1"])
        self.assertFalse(checkpoints[self.search.query_id]["complete"])
        self.runner.visited.clear()
        self.runner.browser.started.clear()
        # The shared backend prepares a fresh planned mode on each invocation.
        self.search.mode = "ai"
        second, errors = self.collect(["1", "3"], limit=25, checkpoints=checkpoints,
                                      checkpoint_sink=checkpoint_sink)
        self.assertEqual(errors, [])
        self.assertEqual([row["linkedin_id"] for row in second], ["3"])
        self.assertEqual(self.runner.visited, ["3"])
        self.assertEqual(self.runner.browser.started, [self.search.query_id])
        self.assertTrue(checkpoints[self.search.query_id]["complete"])
        for guard in self.application_guards.values():
            guard.assert_not_called()


class CrossFrontendCollectionResumeTests(unittest.TestCase):
    def test_repeated_limit_one_advances_past_completed_first_query(self):
        import runAiBot
        from config import search, search_profile
        from modules.job_pipeline.linkedin import prepare_specs
        from modules.job_pipeline.models import LinkedInRunRequest

        collector = CollectionOnlyRunnerTests(methodName="test_search_mode_filters_identity_and_level_without_entering_application_paths")
        collector.setUp()
        self.addCleanup(collector.doCleanups)
        roles = []
        for name in ("one", "two"):
            company = {"id": name, "name": "Example " + name, "domain": name + ".example.com", "employee_count": 80}
            roles.append({
                "id": "role-" + name, "company": company, "company_id": name,
                "title": "Staff Platform Engineer", "description": "Build software platform infrastructure",
                "eligible": True, "status": "open", "verified_at": datetime.now(timezone.utc).isoformat(),
                "workplace_type": "Remote", "employment_type": "Full-time", "locations": ["United States"],
                "published_at": datetime.now(timezone.utc).isoformat(),
            })
        specs, errors = prepare_specs(roles, search_profile, search)
        self.assertEqual(errors, [])
        names = {spec.query_id: spec.pipeline_context["company"]["name"] for spec in specs}
        browser = collector.runner.browser
        browser.pages = {spec.query_id: [[job_id]] for spec, job_id in zip(specs, ("1", "3"))}
        browser.window_handles = ["pipeline-tab"]
        browser.current_window_handle = "pipeline-tab"
        browser.get = Mock()

        def details(job, *args, **kwargs):
            self.assertTrue(kwargs.get("read_only"))
            collector.runner.visited.append(job.job_id)
            return job.job_id, "Staff Platform Engineer", names[browser.query_id], "United States", "Remote", False

        collector.namespace["get_job_main_details"] = details
        with tempfile.TemporaryDirectory() as directory:
            request = LinkedInRunRequest(
                "search", [StageResult.create("verified_roles", "verified", "verification-run", roles).to_dict()],
                "candidates", limit=1, db_path=str(Path(directory) / "pipeline.sqlite3"),
            )
            runtime_patches = {
                "load_runtime": Mock(), "initialize_browser": Mock(), "driver": browser,
                "is_logged_in_LN": Mock(return_value=True), "login_LN": Mock(),
                "collect_linkedin_jobs": collector.namespace["collect_linkedin_jobs"], "aiClient": None,
            }
            with patch.multiple(runAiBot, **runtime_patches):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    first = runAiBot.run_pipeline(request)
                self.assertEqual(first.errors, [])
                self.assertEqual([record["linkedin_id"] for record in first.records], ["1"])
                collector.runner.visited.clear()
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    second = runAiBot.run_pipeline(request)
                self.assertEqual(second.errors, [])
                self.assertEqual(collector.runner.visited, ["3"])
                self.assertEqual({record["linkedin_id"] for record in second.records}, {"1", "3"})
                self.assertEqual([record["linkedin_id"] for record in second.delta], ["3"])
        for guard in collector.application_guards.values():
            guard.assert_not_called()

    def test_standalone_then_native_share_actual_backend_and_resume_saved_collection(self):
        import job_pipeline
        import runAiBot
        from config import search, search_profile
        from modules.job_pipeline.linkedin import prepare_specs

        collector = CollectionOnlyRunnerTests(methodName="test_search_mode_filters_identity_and_level_without_entering_application_paths")
        collector.setUp()
        self.addCleanup(collector.doCleanups)
        company = {"id": "example", "name": "Example", "domain": "example.com", "employee_count": 80}
        role = {
            "id": "official-platform-role", "company": company, "company_id": "example",
            "title": "Staff Platform Engineer", "description": "Build software platform infrastructure",
            "eligible": True, "status": "open", "verified_at": datetime.now(timezone.utc).isoformat(),
            "workplace_type": "Remote", "employment_type": "Full-time", "locations": ["United States"],
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        planned, errors = prepare_specs([role], search_profile, search)
        self.assertEqual(errors, [])
        browser = collector.runner.browser
        browser.pages = {planned[0].query_id: [["1", "3"]]}
        browser.window_handles = ["pipeline-tab"]
        browser.current_window_handle = "pipeline-tab"
        browser.get = Mock()
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source = directory / "verified.json"
            db = str(directory / "pipeline.sqlite3")
            first_output, second_output = directory / "first.json", directory / "second.json"
            write_artifact(StageResult.create("verified_roles", "verified", "verification-run", [role]), source)
            runtime_patches = {
                "load_runtime": Mock(), "initialize_browser": Mock(), "driver": browser,
                "is_logged_in_LN": Mock(return_value=True), "login_LN": Mock(),
                "collect_linkedin_jobs": collector.namespace["collect_linkedin_jobs"], "aiClient": None,
            }
            with patch.multiple(runAiBot, **runtime_patches):
                with patch.object(runAiBot, "run_pipeline", wraps=runAiBot.run_pipeline) as backend:
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        first_status = job_pipeline.main([
                            "search", "linkedin", "--input", str(source), "--set", "candidates",
                            "--db", db, "--limit", "1", "--output", str(first_output),
                        ])
                    first = json.loads(first_output.read_text())
                    self.assertEqual(first_status, 0, first["errors"])
                    self.assertEqual([record["linkedin_id"] for record in first["records"]], ["1"])
                    collector.runner.visited.clear()
                    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                        second_status = runAiBot.cli_main([
                            "--mode", "search", "--input", str(source), "--set", "candidates",
                            "--db", db, "--limit", "25", "--output", str(second_output),
                        ])
                    second = json.loads(second_output.read_text())
                    self.assertEqual(second_status, 0, second["errors"])
                    self.assertEqual(collector.runner.visited, ["3"])
                    self.assertEqual({record["linkedin_id"] for record in second["records"]}, {"1", "3"})
                    self.assertEqual([record["linkedin_id"] for record in second["delta"]], ["3"])
                    self.assertEqual(backend.call_count, 2)
                    first_request, second_request = [call.args[0] for call in backend.call_args_list]
                    self.assertEqual((first_request.mode, first_request.set_name, first_request.db_path),
                                     (second_request.mode, second_request.set_name, second_request.db_path))
                    self.assertNotEqual(first_request.output_path, second_request.output_path)
        for guard in collector.application_guards.values():
            guard.assert_not_called()


class BackendApplicationResumeTests(unittest.TestCase):
    def test_identical_apply_request_resumes_original_manifest_after_partial_success(self):
        self.exercise_apply_resume(limit=2, interrupt_after_first=True)

    def test_repeated_limit_one_advances_selected_ids_using_same_manifest(self):
        self.exercise_apply_resume(limit=1, interrupt_after_first=False)

    def exercise_apply_resume(self, *, limit, interrupt_after_first):
        from types import SimpleNamespace
        import os
        import runAiBot
        import test_search_runner as harness
        from config import search, search_profile
        from modules.job_pipeline.linkedin import mapping, prepare_specs
        from modules.job_pipeline.models import LinkedInRunRequest
        from modules.search_history import file_lock

        runner = SelectedApplicationRunnerTests(methodName="test_apply_revisits_selected_id_and_preserves_original_query_metadata")
        runner.setUp()
        self.addCleanup(runner.doCleanups)
        namespace = runner.namespace
        profile = mapping(search_profile)
        profile["search_state_dir"] = str(runner.runner.directory / "state")
        namespace.update(
            os=os, search_profile=SimpleNamespace(**profile), file_lock=file_lock,
            plan_fingerprint=plan_fingerprint, randomize_search_order=False,
        )
        harness.extract_functions(namespace, "apply_to_jobs")
        company = {"id": "example", "name": "Example", "domain": "example.com", "employee_count": 80}
        role = {
            "id": "official-platform-role", "company": company, "company_id": "example",
            "title": "Staff Platform Engineer", "description": "Build software platform infrastructure",
            "eligible": True, "status": "open", "verified_at": datetime.now(timezone.utc).isoformat(),
            "workplace_type": "Remote", "employment_type": "Full-time", "locations": ["United States"],
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        specs, errors = prepare_specs([role], search_profile, dict(mapping(search), switch_number=2))
        self.assertEqual(errors, [])
        spec = specs[0]
        selected = [{
            "id": "linkedin:" + job_id, "job_id": job_id, "linkedin_id": job_id,
            "eligible": True, "company": company, "company_id": "example",
            "career_roles": [role], "career_job_ids": [role["id"]],
            "query_id": spec.query_id, "query_text": spec.query_text,
            "classic_query": spec.classic_query, "search_mode": spec.mode,
            "search_source": spec.source, "search_spec": spec.to_dict(),
            "profile_name": spec.profile_name, "profile_version": spec.profile_version,
            "search_run_id": "original-discovery-run",
        } for job_id in ("123", "456")]
        request = LinkedInRunRequest(
            "apply", [StageResult.create("linkedin_jobs", "selected", "discovery-run", selected).to_dict()],
            "applications", limit=limit, db_path=str(runner.runner.directory / "pipeline.sqlite3"),
        )
        interrupted = False

        def live_details(record, search_spec):
            nonlocal interrupted
            job_id = record["linkedin_id"]
            if interrupt_after_first and job_id == "456" and not interrupted:
                interrupted = True
                raise KeyboardInterrupt()
            return job_id, "Staff Platform Engineer", "Example", "United States", "Remote", False

        namespace["selected_live_details"] = live_details
        browser = runner.runner.browser
        browser.window_handles = ["pipeline-tab"]
        browser.current_window_handle = "pipeline-tab"
        runtime_patches = {
            "load_runtime": Mock(), "initialize_browser": Mock(), "driver": browser,
            "is_logged_in_LN": Mock(return_value=True), "login_LN": Mock(),
            "validate_config": Mock(), "apply_to_jobs": namespace["apply_to_jobs"],
            "use_AI": False, "aiClient": None,
        }
        with patch.object(search, "switch_number", 2), patch.multiple(runAiBot, create=True, **runtime_patches):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                first = runAiBot.run_pipeline(request)
            state_directory = runner.runner.directory / "state"
            manifest_paths = list(state_directory.glob("*.json"))
            self.assertEqual(len(manifest_paths), 1)
            original = json.loads(manifest_paths[0].read_text())
            self.assertEqual(original["status"], "interrupted")
            self.assertEqual(original["queries"][0]["applied_count"], 1)
            if interrupt_after_first:
                self.assertTrue(any(error["code"] == "KeyboardInterrupt" for error in first.errors))
            else:
                self.assertEqual(first.errors, [])
                self.assertEqual(original["stop_reason"], "work_limit")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                resumed = runAiBot.run_pipeline(request)
            self.assertEqual(len(list(state_directory.glob("*.json"))), 1)
            final = json.loads(manifest_paths[0].read_text())
            self.assertEqual(final["run_id"], original["run_id"])
            self.assertEqual(final["configuration_id"], original["configuration_id"])
            self.assertEqual(final["status"], "complete")
            self.assertEqual(final["queries"][0]["applied_count"], 2)
            self.assertEqual(runner.runner.events.count("Submit application"), 2)
            self.assertEqual({record["job_id"] for record in resumed.records}, {"123", "456"})
            self.assertEqual({record["search_run_id"] for record in resumed.records}, {original["run_id"]})


class BrowserFactoryLifecycleTests(unittest.TestCase):
    def test_failed_factory_can_retry_without_caching_partial_browser_state(self):
        import runAiBot

        rebuilt = Mock(window_handles=["tab"])
        wait, actions = object(), object()
        with patch.multiple(runAiBot, driver=None, wait=None, actions=None, _browser_background=None):
            with patch("modules.open_chrome.create_browser", side_effect=[RuntimeError("startup failed"), (rebuilt, wait, actions)]) as factory:
                with self.assertRaisesRegex(RuntimeError, "startup failed"):
                    runAiBot.initialize_browser(background=False)
                self.assertIsNone(runAiBot.driver)
                self.assertIs(runAiBot.initialize_browser(background=False), rebuilt)
                self.assertIs(runAiBot.wait, wait)
                self.assertIs(runAiBot.actions, actions)
                self.assertEqual(factory.call_count, 2)

    def test_cached_invalid_session_is_disposed_and_recreated(self):
        import runAiBot

        invalid = Mock()
        type(invalid).window_handles = PropertyMock(side_effect=RuntimeError("invalid session id"))
        rebuilt = Mock(window_handles=["tab"])
        with patch.multiple(runAiBot, driver=invalid, wait=object(), actions=object(), _browser_background=False):
            with patch("modules.open_chrome.create_browser", return_value=(rebuilt, object(), object())) as factory:
                self.assertIs(runAiBot.initialize_browser(background=False), rebuilt)
                invalid.quit.assert_called_once_with()
                factory.assert_called_once_with(background=False)

    def test_factory_disposes_started_browser_if_post_creation_setup_fails(self):
        from types import ModuleType, SimpleNamespace
        from config import settings
        from modules.open_chrome import create_browser

        browser = Mock()
        browser.maximize_window.side_effect = RuntimeError("post-start setup failed")
        webdriver = ModuleType("selenium.webdriver")
        webdriver.ChromeOptions = Mock()
        webdriver.Chrome = Mock(return_value=browser)
        selenium = ModuleType("selenium")
        selenium.webdriver = webdriver
        modules = {
            "selenium": selenium, "selenium.webdriver": webdriver,
            "selenium.webdriver.common.action_chains": SimpleNamespace(ActionChains=Mock()),
            "selenium.webdriver.support.ui": SimpleNamespace(WebDriverWait=Mock()),
            "modules.helpers": SimpleNamespace(find_default_profile_directory=lambda: None, make_directories=Mock()),
        }
        with patch.dict(sys.modules, modules), patch.multiple(settings, stealth_mode=False, safe_mode=True,
                                                            run_in_background=False, disable_extensions=False):
            with self.assertRaisesRegex(RuntimeError, "post-start setup failed"):
                create_browser()
        webdriver.Chrome.assert_called_once()
        browser.quit.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

"""CLI validation and delegation without credentials, network, or browser startup."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import job_pipeline
# Keep the service module in the baseline sys.modules snapshot used below.
# Otherwise patch.dict(sys.modules) removes it while leaving a stale package
# attribute, and later patches can accidentally call the real network service.
import modules.job_pipeline.service
from config import job_pipeline as pipeline_config
from modules.job_pipeline.models import StageResult, write_artifact
from modules.job_pipeline.store import PipelineStore


def artifact(stage="verified_roles", set_name="roles"):
    records = [{"id": "role:staff", "title": "Staff AI Engineer", "status": "open", "eligible": True}]
    if stage == "companies":
        records = [{"id": "company:example", "name": "Example", "domain": "example.com"}]
    if stage == "linkedin_jobs":
        records = [{"id": "123", "job_id": "123", "title": "Staff AI Engineer"}]
    return StageResult.create(stage, set_name, "input-run", records)


class CliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.db = self.directory / "pipeline.sqlite3"
        self.stdout, self.stderr = io.StringIO(), io.StringIO()

    def invoke(self, args):
        with redirect_stdout(self.stdout), redirect_stderr(self.stderr):
            return job_pipeline.main(args)

    def test_bare_help_does_not_create_database_or_import_browser_runner(self):
        before = set(sys.modules)
        self.assertEqual(self.invoke([]), 0)
        self.assertIn("discover", self.stdout.getvalue())
        self.assertEqual(set(sys.modules) - before & {"runAiBot", "modules.open_chrome"}, set())
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_all_linkedin_commands_delegate_same_request_contract(self):
        for verb, mode, input_stage, result_stage in (
            ("search", "search", "verified_roles", "linkedin_jobs"),
            ("apply", "apply", "linkedin_jobs", "applications"),
            ("run", "search-and-apply", "verified_roles", "applications"),
        ):
            with self.subTest(verb=verb):
                path = self.directory / (verb + "-input.json")
                output = self.directory / (verb + "-output.json")
                write_artifact(artifact(input_stage), path)
                backend = Mock(return_value=StageResult.create(result_stage, "candidates", "backend-run", []))
                with patch.dict(sys.modules, {"runAiBot": SimpleNamespace(run_pipeline=backend)}):
                    self.assertEqual(self.invoke([verb, "linkedin", "--input", str(path), "--set", "candidates", "--output", str(output), "--limit", "3", "--db", str(self.db)]), 0)
                request = backend.call_args.args[0]
                self.assertEqual(request.mode, mode)
                self.assertEqual(request.limit, 3)
                self.assertEqual(request.set_name, "candidates")
                self.assertEqual(request.db_path, str(self.db))
                self.assertEqual(request.output_path, str(output))
                self.assertEqual(request.input_sets[0]["stage"], input_stage)
                self.assertEqual(json.loads(output.read_text())["stage"], result_stage)

    def test_repeatable_named_sets_are_validated_before_backend(self):
        with PipelineStore(self.db) as store:
            store.import_artifact(artifact("verified_roles", "one"))
            store.import_artifact(artifact("verified_roles", "two"))
        backend = Mock(return_value=StageResult.create("linkedin_jobs", "jobs", "backend", []))
        with patch.dict(sys.modules, {"runAiBot": SimpleNamespace(run_pipeline=backend)}):
            self.assertEqual(self.invoke(["search", "linkedin", "--input", "one", "--input", "verified_roles:two", "--db", str(self.db)]), 0)
        self.assertEqual([item["set_name"] for item in backend.call_args.args[0].input_sets], ["one", "two"])

    def test_wrong_stage_input_never_calls_linkedin_backend(self):
        path = self.directory / "companies.json"
        write_artifact(artifact("companies"), path)
        backend = Mock()
        with patch.dict(sys.modules, {"runAiBot": SimpleNamespace(run_pipeline=backend)}):
            self.assertEqual(self.invoke(["search", "linkedin", "--input", str(path), "--db", str(self.db)]), 2)
        backend.assert_not_called()
        self.assertIn("Expected verified_roles", self.stderr.getvalue())

    def test_malformed_input_never_calls_backend_or_creates_entities(self):
        path = self.directory / "invalid.json"
        path.write_text('{"schema_version": 1}')
        backend = Mock()
        with patch.dict(sys.modules, {"runAiBot": SimpleNamespace(run_pipeline=backend)}):
            self.assertEqual(self.invoke(["apply", "linkedin", "--input", str(path), "--db", str(self.db)]), 2)
        backend.assert_not_called()
        with PipelineStore(self.db) as store:
            self.assertEqual(store.connection.execute("SELECT count(*) FROM entities").fetchone()[0], 0)

    def test_invalid_limits_and_missing_targets_are_parser_errors(self):
        for args in (["search"], ["search", "linkedin", "--limit", "0"],
                     ["apply", "linkedin", "--limit", "-1"], ["run", "linkedin", "--limit", "one"]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                self.invoke(args)
            self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.db.exists())

    def test_apply_does_not_accept_refresh(self):
        with self.assertRaises(SystemExit) as error:
            self.invoke(["apply", "linkedin", "--refresh"])
        self.assertEqual(error.exception.code, 2)

    def test_search_refresh_is_forwarded_to_shared_backend(self):
        backend = Mock(return_value=StageResult.create("linkedin_jobs", "jobs", "backend", []))
        with patch.dict(sys.modules, {"runAiBot": SimpleNamespace(run_pipeline=backend)}):
            self.assertEqual(self.invoke(["search", "linkedin", "--refresh", "--db", str(self.db)]), 0)
        self.assertTrue(backend.call_args.args[0].refresh)

    def test_discovery_and_verification_delegate_to_independent_services(self):
        result = artifact("companies")
        with patch("modules.job_pipeline.service.discover_companies", return_value=result) as discover:
            self.assertEqual(self.invoke(["discover", "companies", "--source", "yc", "--source", "greylock", "--set", "startups", "--limit", "2", "--refresh", "--db", str(self.db)]), 0)
        self.assertEqual(discover.call_args.kwargs, {"sources": ["yc", "greylock"], "refresh": True})
        with patch("modules.job_pipeline.service.verify_careers", return_value=artifact()) as verify:
            self.assertEqual(self.invoke(["verify", "careers", "--input", "startups", "--set", "roles", "--db", str(self.db)]), 0)
        self.assertEqual(verify.call_args.args[:2], (["startups"], "roles"))

    def test_import_only_discovery_explicitly_selects_no_network_sources(self):
        with patch("modules.job_pipeline.service.discover_companies", return_value=artifact("companies")) as discover:
            self.assertEqual(self.invoke(["discover", "companies", "--source", "import", "--input", "companies.json", "--db", str(self.db)]), 0)
        self.assertEqual(discover.call_args.kwargs["sources"], [])

    def test_partial_result_exports_cumulative_artifact_and_returns_nonzero(self):
        result = StageResult.create("linkedin_jobs", "jobs", "backend", [{"id": "123"}], errors=[{"code": "blocked"}])
        output = self.directory / "partial.json"
        with patch.dict(sys.modules, {"runAiBot": SimpleNamespace(run_pipeline=Mock(return_value=result))}):
            self.assertEqual(self.invoke(["search", "linkedin", "--output", str(output), "--db", str(self.db)]), 1)
        saved = json.loads(output.read_text())
        self.assertEqual(saved["records"], [{"id": "123"}])
        self.assertEqual(saved["errors"], [{"code": "blocked"}])

    def test_new_stage_options_are_forwarded_only_when_explicit(self):
        with patch("modules.job_pipeline.service.discover_companies", return_value=artifact("companies")) as discover:
            self.assertEqual(self.invoke([
                "discover", "companies", "--source", "yc", "--no-refresh", "--render-public",
                "--target-companies", "0", "--db", str(self.db),
            ]), 0)
        self.assertEqual(discover.call_args.kwargs, {
            "sources": ["yc"], "refresh": False, "render_enabled": True, "target_companies": 0,
        })
        self.assertIsNone(discover.call_args.args[2])
        with patch("modules.job_pipeline.service.verify_careers", return_value=artifact()) as verify:
            self.assertEqual(self.invoke([
                "verify", "careers", "--refresh", "--no-render-public", "--no-prioritize-established",
                "--db", str(self.db),
            ]), 0)
        self.assertEqual(verify.call_args.kwargs, {
            "refresh": True, "render_enabled": False, "prioritize_established": False,
        })

    def test_omitted_stage_options_defer_to_service_configuration(self):
        with patch("modules.job_pipeline.service.discover_companies", return_value=artifact("companies")) as discover:
            self.assertEqual(self.invoke(["discover", "companies", "--db", str(self.db)]), 0)
        self.assertIsNone(discover.call_args.args[2])
        self.assertEqual(discover.call_args.kwargs, {"sources": None, "refresh": None})
        with patch("modules.job_pipeline.service.verify_careers", return_value=artifact()) as verify:
            self.assertEqual(self.invoke(["verify", "careers", "--db", str(self.db)]), 0)
        self.assertIsNone(verify.call_args.args[2])
        self.assertEqual(verify.call_args.kwargs, {"refresh": None})

    def test_verify_resume_is_forwarded_only_when_requested(self):
        with patch("modules.job_pipeline.service.verify_careers", return_value=artifact()) as verify:
            self.assertEqual(self.invoke(["verify", "careers", "--resume", "resume.docx", "--db", str(self.db)]), 0)
        self.assertEqual(verify.call_args.kwargs, {"refresh": None, "resume_path": "resume.docx"})

    def test_rank_export_is_offline_and_preserves_all_records_without_a_limit(self):
        source = self.directory / "verified.json"
        resume = self.directory / "original-resume.txt"
        output = self.directory / "ranked.json"
        original = artifact()
        original.records[0].update(description="Python software development", published_at="2026-10-14T00:00:00Z",
                                   verified_at="2026-10-14T13:00:00Z", verification_run_id="actual-source-observation")
        write_artifact(original, source)
        resume.write_text("Python software engineer")
        self.assertEqual(self.invoke(["rank", "careers", "--input", str(source), "--resume", str(resume),
                                     "--as-of", "2026-10-15T00:00:00Z", "--output", str(output), "--db", str(self.db)]), 0)
        result = json.loads(output.read_text())
        self.assertFalse(self.db.exists())
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["review_priority"]["tier"], 1)
        self.assertEqual(result["records"][0]["verification_run_id"], "actual-source-observation")
        self.assertEqual(result["records"][0]["verified_at"], "2026-10-14T13:00:00Z")
        with self.assertRaises(SystemExit):
            self.invoke(["rank", "careers", "--limit", "1"])

    def test_rank_invalid_resume_as_of_or_stage_fail_before_database_creation(self):
        source = self.directory / "companies.json"
        write_artifact(artifact("companies"), source)
        for extra, expected in ((["--as-of", "2026-10-15"], "timezone"),
                                (["--resume", str(self.directory / "missing.docx")], "No such file"),
                                ([], "Expected verified_roles")):
            with self.subTest(extra=extra):
                self.stderr = io.StringIO()
                self.assertEqual(self.invoke(["rank", "careers", "--input", str(source), "--db", str(self.db)] + extra), 2)
                self.assertIn(expected, self.stderr.getvalue())
                self.assertFalse(self.db.exists())

    def test_invalid_company_targets_fail_before_service(self):
        for value in ("-1", "one", "1.5"):
            with self.subTest(value=value):
                with patch("modules.job_pipeline.service.discover_companies") as discover:
                    with self.assertRaises(SystemExit) as error:
                        self.invoke(["discover", "companies", "--target-companies", value, "--db", str(self.db)])
                self.assertEqual(error.exception.code, 2)
                discover.assert_not_called()
        self.assertFalse(self.db.exists())

    def test_linkedin_commands_do_not_accept_discovery_or_verification_controls(self):
        for args in (["search", "linkedin", "--render-public"],
                     ["apply", "linkedin", "--target-companies", "3"],
                     ["run", "linkedin", "--no-refresh"],
                     ["search", "linkedin", "--prioritize-established"]):
            with self.subTest(args=args), self.assertRaises(SystemExit) as error:
                self.invoke(args)
            self.assertEqual(error.exception.code, 2)
        self.assertFalse(self.db.exists())

    def test_stage_help_stays_pure_with_public_rendering_enabled_in_config(self):
        script = """
import importlib.abc
import runpy
import sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'runAiBot', 'modules.open_chrome', 'selenium', 'openai', 'pyautogui', 'requests'}:
            raise AssertionError('Runtime import reached during help: ' + fullname)
        return None
sys.meta_path.insert(0, Guard())
sys.path.insert(0, sys.argv[1])
from config import job_pipeline as config
config.discovery_render_enabled = True
config.verification_render_enabled = True
sys.argv = ['job_pipeline', sys.argv[2], sys.argv[3], '--help']
runpy.run_module('job_pipeline', run_name='__main__')
"""
        root = Path(__file__).resolve().parents[1]
        for verb, noun in (("discover", "companies"), ("verify", "careers")):
            with self.subTest(verb=verb):
                completed = subprocess.run([sys.executable, "-B", "-c", script, str(root), verb, noun],
                                           cwd=self.directory, capture_output=True, text=True, timeout=15)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertIn("--render-public", completed.stdout)
                self.assertIn("--no-render-public", completed.stdout)
        self.assertEqual(list(self.directory.iterdir()), [])


class ConfiguredStageCliTests(unittest.TestCase):
    """Run actual services with inert adapters to verify configuration precedence."""

    setUp = CliTests.setUp
    invoke = CliTests.invoke

    def test_invalid_configured_stage_budget_stops_before_adapter_or_database(self):
        with patch.multiple(pipeline_config, create=True, discovery_limit_per_source=0,
                            discovery_render_enabled=False):
            with patch("modules.job_pipeline.sources.discover_source") as adapter:
                self.assertEqual(self.invoke(["discover", "companies", "--source", "yc", "--db", str(self.db)]), 2)
        adapter.assert_not_called()
        self.assertIn("discovery_limit_per_source", self.stderr.getvalue())
        self.assertFalse(self.db.exists())

    def test_discovery_source_budgets_survive_omitted_limit_and_explicit_limit_overrides(self):
        def discover(source, config, **kwargs):
            return {"records": [{"id": source, "name": source, "domain": source + ".example.com"}],
                    "errors": [], "complete": True, "cursor": None}

        controls = {
            "discovery_limit_per_source": 4, "discovery_source_limits": {"yc": 9},
            "discovery_target_companies": None, "discovery_refresh": False, "discovery_render_enabled": False,
        }
        with patch.multiple(pipeline_config, create=True, **controls):
            with patch("modules.job_pipeline.sources.discover_source", side_effect=discover) as adapter:
                self.assertEqual(self.invoke([
                    "discover", "companies", "--source", "yc", "--source", "hn",
                    "--set", "configured", "--db", str(self.db),
                ]), 0)
                self.assertEqual([(call.args[0], call.kwargs["limit"]) for call in adapter.call_args_list], [("yc", 9), ("hn", 4)])
                adapter.reset_mock()
                self.assertEqual(self.invoke([
                    "discover", "companies", "--source", "yc", "--source", "hn", "--limit", "2",
                    "--set", "explicit", "--db", str(self.db),
                ]), 0)
                self.assertEqual([(call.args[0], call.kwargs["limit"]) for call in adapter.call_args_list], [("yc", 2), ("hn", 2)])

    def test_configured_target_stops_discovery_and_zero_flag_disables_it(self):
        def discover(source, config, **kwargs):
            return {"records": [{"id": source, "name": source, "domain": source + ".example.com"}],
                    "errors": [], "complete": True, "cursor": None}

        with patch.multiple(pipeline_config, create=True, discovery_target_companies=1,
                            discovery_source_limits={}, discovery_render_enabled=False, discovery_refresh=False):
            with patch("modules.job_pipeline.sources.discover_source", side_effect=discover) as adapter:
                self.assertEqual(self.invoke([
                    "discover", "companies", "--source", "yc", "--source", "hn",
                    "--set", "target", "--db", str(self.db),
                ]), 0)
                self.assertEqual([call.args[0] for call in adapter.call_args_list], ["yc"])
                adapter.reset_mock()
                self.assertEqual(self.invoke([
                    "discover", "companies", "--source", "yc", "--source", "hn", "--target-companies", "0",
                    "--set", "unbounded", "--db", str(self.db),
                ]), 0)
                self.assertEqual([call.args[0] for call in adapter.call_args_list], ["yc", "hn"])

    def test_no_refresh_overrides_configured_refresh_and_preserves_checkpoint(self):
        with PipelineStore(self.db) as store:
            store.save_checkpoint("discover:yc", "resume", {"complete": True, "cursor": None})
        response = {"records": [{"id": "yc", "name": "YC Example", "domain": "yc.example.com"}],
                    "errors": [], "complete": True, "cursor": None}
        with patch.multiple(pipeline_config, create=True, discovery_refresh=True,
                            discovery_target_companies=None, discovery_render_enabled=False):
            with patch("modules.job_pipeline.sources.discover_source", return_value=response) as adapter:
                self.assertEqual(self.invoke([
                    "discover", "companies", "--source", "yc", "--set", "resume",
                    "--no-refresh", "--db", str(self.db),
                ]), 0)
                adapter.assert_not_called()
                self.assertEqual(self.invoke([
                    "discover", "companies", "--source", "yc", "--set", "resume", "--db", str(self.db),
                ]), 0)
                adapter.assert_called_once()

    def test_verification_budget_and_established_priority_use_config_then_cli(self):
        companies = StageResult.create("companies", "companies", "companies-run", [
            {"id": "a-early", "name": "Early", "domain": "early.example.com", "employee_count": 10},
            {"id": "z-established", "name": "Established", "domain": "established.example.com", "employee_count": 80},
        ])
        source = self.directory / "companies.json"
        write_artifact(companies, source)
        response = {"records": [], "errors": [], "status": "not_hiring", "complete": True}
        controls = {
            "verification_limit_companies": 1, "verification_prioritize_established": True,
            "verification_refresh": False, "verification_render_enabled": False, "established_min_employees": 50,
        }
        with patch.multiple(pipeline_config, create=True, **controls):
            with patch("modules.job_pipeline.careers.verify_company", return_value=response) as adapter:
                self.assertEqual(self.invoke([
                    "verify", "careers", "--input", str(source), "--set", "prioritized", "--db", str(self.db),
                ]), 0)
                self.assertEqual([call.args[0]["id"] for call in adapter.call_args_list], ["z-established"])
                adapter.reset_mock()
                self.assertEqual(self.invoke([
                    "verify", "careers", "--input", str(source), "--set", "insertion", "--limit", "2",
                    "--no-prioritize-established", "--db", str(self.db),
                ]), 0)
                self.assertEqual([call.args[0]["id"] for call in adapter.call_args_list], ["a-early", "z-established"])


if __name__ == "__main__":
    unittest.main()

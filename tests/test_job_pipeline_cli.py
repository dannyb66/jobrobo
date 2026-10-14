"""CLI validation and delegation without credentials, network, or browser startup."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import job_pipeline
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


if __name__ == "__main__":
    unittest.main()

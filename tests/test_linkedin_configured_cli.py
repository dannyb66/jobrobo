"""Configured no-input invocation: mock execution, no credentials or live browser."""
from contextlib import redirect_stderr, redirect_stdout
import io
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_search_runner import extract_functions


class ConfiguredCliTests(unittest.TestCase):
    def setUp(self):
        self.profile = SimpleNamespace(resume_search_enabled=True)
        self.run = Mock()
        self.namespace = {"run_bot": self.run, "search_profile": self.profile}
        extract_functions(self.namespace, "cli_main")

    def invoke(self, args):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return self.namespace["cli_main"](args)

    def test_existing_no_argument_entry_still_runs_configured_bot(self):
        self.assertEqual(self.invoke([]), 0)
        self.run.assert_called_once_with()

    def test_explicit_configured_entry_needs_no_pipeline_artifact_or_database(self):
        self.run.side_effect = lambda: self.assertTrue(self.profile.resume_search_enabled)
        self.assertEqual(self.invoke(["--configured-search-and-apply"]), 0)
        self.run.assert_called_once_with()

    def test_fresh_disables_manifest_resume_for_run_then_restores_setting(self):
        self.run.side_effect = lambda: self.assertFalse(self.profile.resume_search_enabled)
        self.assertEqual(self.invoke(["--configured-search-and-apply", "--fresh"]), 0)
        self.assertTrue(self.profile.resume_search_enabled)

    def test_fresh_restores_setting_after_runner_failure(self):
        self.run.side_effect = RuntimeError("synthetic run failure")
        with self.assertRaisesRegex(RuntimeError, "synthetic run failure"):
            self.invoke(["--configured-search-and-apply", "--fresh"])
        self.assertTrue(self.profile.resume_search_enabled)

    def test_preserves_preexisting_false_resume_setting(self):
        self.profile.resume_search_enabled = False
        self.assertEqual(self.invoke(["--configured-search-and-apply", "--fresh"]), 0)
        self.assertFalse(self.profile.resume_search_enabled)

    def test_incompatible_pipeline_or_diagnostic_flags_fail_before_execution(self):
        for extra in (["--mode", "apply"], ["--input", "jobs.json"], ["--set=jobs"],
                      ["--output", "output.json"], ["--limit", "2"], ["--db=test.sqlite3"],
                      ["--refresh"], ["--diagnose-search"]):
            with self.subTest(extra=extra), self.assertRaises(SystemExit) as error:
                self.invoke(["--configured-search-and-apply", *extra])
            self.assertEqual(error.exception.code, 2)
        self.run.assert_not_called()

    def test_fresh_without_configured_entry_fails_before_execution(self):
        with self.assertRaises(SystemExit) as error:
            self.invoke(["--fresh"])
        self.assertEqual(error.exception.code, 2)
        self.run.assert_not_called()

    def test_help_never_runs_bot(self):
        with self.assertRaises(SystemExit) as error:
            self.invoke(["--configured-search-and-apply", "--fresh", "--help"])
        self.assertEqual(error.exception.code, 0)
        self.run.assert_not_called()

import importlib.util
import json
import sys
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from unittest.mock import Mock, patch

from modules import config_loader


ROOT = Path(__file__).resolve().parents[1]


class RuntimeConfigTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.bundle = self.directory / "defaults.json"
        self.runtime = self.directory / "runtime" / "config.json"
        self.defaults = {
            "optimization_mode": "full",
            "replace_job_title": True,
            "rewrite_bullets": True,
            "max_skills": 50,
            "project_bullet_banks": [
                {"path": "trek.md", "company": "Trek Health", "min_bullets": 7,
                 "max_bullets": 7, "allow_unverified": False},
                {"path": "codex.md", "company": "CODEX SELF-HOSTED", "max_bullets": 5},
            ],
        }
        self.bundle.write_text(json.dumps(self.defaults))
        for name, value in (
            ("APP_BUNDLE_CONFIG_FILE", self.bundle),
            ("RUNTIME_CONFIG_DIR", self.runtime.parent),
            ("RUNTIME_CONFIG_FILE", self.runtime),
        ):
            patcher = patch.object(config_loader, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_runtime(self, config):
        self.runtime.parent.mkdir(parents=True, exist_ok=True)
        self.runtime.write_text(json.dumps(config))

    def test_legacy_modes_and_unknown_values_survive_defaults_merge(self):
        for replace, rewrite, mode in (
            (True, True, "full"), (False, True, "bullets"),
            (True, False, "skills"), (False, False, "skills"),
        ):
            with self.subTest(mode=mode, replace=replace, rewrite=rewrite):
                self.write_runtime({"replace_job_title": replace, "rewrite_bullets": rewrite,
                                    "max_skills": 12, "custom_setting": {"keep": True}})
                config = config_loader.load_runtime_config()
                self.assertEqual(config["optimization_mode"], mode)
                self.assertEqual(config["max_skills"], 12)
                self.assertEqual(config["custom_setting"], {"keep": True})
                self.assertEqual(len(config["project_bullet_banks"]), 2)

    def test_explicit_mode_and_bank_lists_override_defaults_including_empty_list(self):
        for banks in ([], [{"path": "custom.md", "company": "Custom"}]):
            with self.subTest(banks=banks):
                self.write_runtime({"optimization_mode": "skills", "rewrite_bullets": True,
                                    "project_bullet_banks": banks})
                config = config_loader.load_runtime_config()
                self.assertEqual(config["optimization_mode"], "skills")
                self.assertEqual(config["project_bullet_banks"], banks)

    def test_legacy_bank_settings_are_migrated_into_default_project_list(self):
        self.write_runtime({"bullet_bank_path": "custom_trek.md", "bullet_bank_company": "Custom Trek",
                            "max_bank_bullets": 4, "allow_unverified_bullet_terms": True})
        config = config_loader.load_runtime_config()
        trek = config["project_bullet_banks"][0]
        self.assertEqual(trek["path"], "custom_trek.md")
        self.assertEqual(trek["company"], "Custom Trek")
        self.assertEqual(trek["max_bullets"], 4)
        self.assertEqual(trek["min_bullets"], 4)
        self.assertTrue(trek["allow_unverified"])
        self.assertEqual(config["project_bullet_banks"][1], self.defaults["project_bullet_banks"][1])

    def test_partial_save_preserves_unknown_settings_and_persists_new_defaults(self):
        self.write_runtime({"replace_job_title": False, "rewrite_bullets": True,
                            "private_extension": {"enabled": False}})
        config_loader.save_runtime_config({"job_title": "Staff Engineer"})
        saved = json.loads(self.runtime.read_text())
        self.assertEqual(saved["private_extension"], {"enabled": False})
        self.assertEqual(saved["optimization_mode"], "bullets")
        self.assertEqual(saved["job_title"], "Staff Engineer")
        self.assertEqual(saved["max_skills"], 50)

    def test_invalid_runtime_config_is_not_overwritten_on_save(self):
        self.runtime.parent.mkdir()
        self.runtime.write_text("{invalid")
        with self.assertRaises(ValueError):
            config_loader.save_runtime_config({"job_title": "New Title"})
        self.assertEqual(self.runtime.read_text(), "{invalid")

    def test_failed_atomic_save_preserves_original_config(self):
        self.write_runtime({"job_title": "Original"})
        original = self.runtime.read_text()
        with patch.object(config_loader.os, "replace", side_effect=OSError("write failed")):
            with self.assertRaises(OSError):
                config_loader.save_runtime_config({"job_title": "New"})
        self.assertEqual(self.runtime.read_text(), original)
        self.assertFalse(list(self.runtime.parent.glob("resume-optimizer-*.json")))

    def test_concurrent_saves_preserve_independent_settings(self):
        self.write_runtime({"existing": "keep"})
        writing = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()
        real_dump = json.dump

        def slow_first_write(config, stream, **kwargs):
            if "first_setting" in config and "second_setting" not in config:
                writing.set()
                if not release_first.wait(5):
                    raise TimeoutError("test never released first writer")
            return real_dump(config, stream, **kwargs)

        def second_save():
            second_started.set()
            config_loader.save_runtime_config({"second_setting": "second"})

        with patch.object(config_loader.json, "dump", side_effect=slow_first_write):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(config_loader.save_runtime_config, {"first_setting": "first"})
                self.assertTrue(writing.wait(5))
                second = pool.submit(second_save)
                self.assertTrue(second_started.wait(5))
                try:
                    # While the first save is incomplete the next writer must
                    # wait, otherwise it reads stale state and loses an update.
                    with self.assertRaises(FutureTimeoutError):
                        second.result(timeout=0.05)
                finally:
                    release_first.set()
                first.result(timeout=5)
                second.result(timeout=5)
        saved = json.loads(self.runtime.read_text())
        self.assertEqual(saved["first_setting"], "first")
        self.assertEqual(saved["second_setting"], "second")
        self.assertEqual(saved["existing"], "keep")

    def test_first_load_copies_bundled_defaults(self):
        config = config_loader.load_runtime_config()
        self.assertEqual(config, self.defaults)
        self.assertEqual(json.loads(self.runtime.read_text()), self.defaults)


class OptimizerDashboardTest(unittest.TestCase):
    def setUp(self):
        self.optimizer = types.ModuleType("modules.ai.resume_optimizer")
        self.optimizer.run_resume_optimization = Mock(return_value="optimized.pdf")
        self.key_loader = types.ModuleType("modules.ai.openai_key_loader")
        self.key_loader.load_openai_key = Mock()
        spec = importlib.util.spec_from_file_location("jobrobo_dashboard_test", ROOT / "JobRobo.py")
        self.dashboard = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "modules.ai.resume_optimizer": self.optimizer,
            "modules.ai.openai_key_loader": self.key_loader,
            "runAiBot": None,
            "modules.open_chrome": None,
        }):
            spec.loader.exec_module(self.dashboard)

        self.app = self.dashboard.LinkedInApp.__new__(self.dashboard.LinkedInApp)
        self.app.fields = {
            key: Mock(get=Mock(return_value=value)) for key, value in {
                "job_description": "Build agent platforms", "resume_path": "source.docx",
                "job_id": "42", "job_title": "Staff Engineer", "first_name": "Test", "last_name": "User",
            }.items()
        }
        self.app.replace_job_title_var = Mock(get=Mock(return_value=False))
        self.app.rewrite_bullets_var = Mock(get=Mock(return_value=True))
        self.app.optimization_mode_var = Mock(get=Mock(return_value="bullets"))
        self.app.content_policy_var = Mock(get=Mock(return_value="grounded"))
        self.config = {"unknown_setting": {"keep": 1}, "project_bullet_banks": [], "max_skills": 16}
        for name, value in (
            ("load_runtime_config", Mock(side_effect=lambda: dict(self.config))),
            ("save_runtime_config", Mock(side_effect=lambda updated: self.config.update(updated))),
            ("messagebox", Mock()),
        ):
            patcher = patch.object(self.dashboard, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_import_does_not_launch_bot_or_fetch_key(self):
        self.key_loader.load_openai_key.assert_not_called()

    def test_optimizer_callback_preserves_settings_and_reports_success(self):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-only"}):
            self.app.run_resume_optimizer_from_ui()
        self.optimizer.run_resume_optimization.assert_called_once_with(
            "Build agent platforms", "source.docx", "42", "Staff Engineer", "Test", "User", "bullets"
        )
        self.assertEqual(self.config["unknown_setting"], {"keep": 1})
        self.assertEqual(self.config["project_bullet_banks"], [])
        self.assertEqual(self.config["max_skills"], 16)
        self.dashboard.messagebox.showerror.assert_not_called()
        self.dashboard.messagebox.showinfo.assert_called_once()
        self.key_loader.load_openai_key.assert_not_called()

    def test_gui_saves_only_form_fields_preserving_fresh_bank_settings(self):
        latest_banks = [{"company": "New Custom Bank", "path": "new.md"}]
        self.config["project_bullet_banks"] = [{"company": "Old Bank", "path": "old.md"}]

        def save_after_external_bank_edit(updates):
            self.config["project_bullet_banks"] = latest_banks
            self.config.update(updates)

        self.dashboard.save_runtime_config.side_effect = save_after_external_bank_edit
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-only"}):
            self.app.run_resume_optimizer_from_ui()
        updates = self.dashboard.save_runtime_config.call_args.args[0]
        self.assertNotIn("project_bullet_banks", updates)
        self.assertNotIn("unknown_setting", updates)
        self.assertEqual(self.config["project_bullet_banks"], latest_banks)
        self.dashboard.messagebox.showerror.assert_not_called()

    def test_gui_preserves_independent_false_title_flag_and_explicit_draft_policy(self):
        self.app.optimization_mode_var.get.return_value = "full"
        self.app.content_policy_var.get.return_value = "review_draft"
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-only"}):
            self.app.run_resume_optimizer_from_ui()
        self.assertIs(self.config["replace_job_title"], False)
        self.assertEqual(self.config["optimization_mode"], "full")
        self.assertEqual(self.config["content_policy"], "review_draft")

    def test_optimizer_none_result_reports_failure(self):
        self.optimizer.run_resume_optimization.return_value = None
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-only"}):
            self.app.run_resume_optimizer_from_ui()
        self.dashboard.messagebox.showinfo.assert_not_called()
        self.dashboard.messagebox.showerror.assert_called_once()

    def test_strict_manual_review_outcome_does_not_claim_partial_failure(self):
        self.app.rewrite_all_bullets_var=Mock(get=Mock(return_value=True))
        self.app.rewrite_concurrency_var=Mock(get=Mock(return_value=4))
        self.app.content_policy_var.get.return_value='review_draft'
        self.app.rewrite_progress=Mock()
        self.app.root=Mock()
        self.app.root.after.side_effect=lambda delay,callback:callback()
        # A complete manual-review draft intentionally returns no upload PDF.
        self.optimizer.run_resume_optimization.return_value=None
        with patch.object(self.dashboard.threading,'Thread') as thread:
            thread.return_value.start.side_effect=lambda:thread.call_args.kwargs['target']()
            self.app.run_resume_optimizer_from_ui()
        message=self.app.rewrite_progress.set.call_args.args[0]
        self.assertIn('inspect Task11 coverage and comparison',message)
        self.assertIn('No accepted attachment',message)
        self.assertNotIn('Partial/blocked',message)
        self.dashboard.messagebox.showerror.assert_not_called()

    def test_optimizer_loads_missing_key_only_on_action(self):
        with patch.dict("os.environ", {}, clear=True):
            self.app.run_resume_optimizer_from_ui()
        self.key_loader.load_openai_key.assert_called_once()
        self.optimizer.run_resume_optimization.assert_called_once()

    def test_config_save_error_prevents_optimizer_run(self):
        self.dashboard.save_runtime_config.side_effect = OSError("write failed")
        self.app.run_resume_optimizer_from_ui()
        self.optimizer.run_resume_optimization.assert_not_called()
        self.dashboard.messagebox.showinfo.assert_not_called()
        self.dashboard.messagebox.showerror.assert_called_once()

    def test_optimizer_exception_reports_failure(self):
        self.optimizer.run_resume_optimization.side_effect = RuntimeError("conversion failed")
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-only"}):
            self.app.run_resume_optimizer_from_ui()
        self.dashboard.messagebox.showinfo.assert_not_called()
        self.dashboard.messagebox.showerror.assert_called_once()
        self.assertIn("conversion failed", self.dashboard.messagebox.showerror.call_args.args[1])

    def test_run_bot_button_lazily_imports_and_runs_bot(self):
        bot = types.ModuleType("runAiBot")
        bot.run_bot = Mock()
        with patch.dict(sys.modules, {"runAiBot": bot}):
            self.app.run_bot_from_ui()
        bot.run_bot.assert_called_once()


if __name__ == "__main__":
    unittest.main()

import importlib.util
import os
import runpy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]


class ChromeProfileTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)

    def helpers(self):
        spec = importlib.util.spec_from_file_location("profile_test_helpers", ROOT / "modules/helpers.py")
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {
            "pyautogui": types.SimpleNamespace(alert=Mock()),
            "config.settings": types.SimpleNamespace(logs_folder_path=str(self.home)),
        }):
            spec.loader.exec_module(module)
        return module

    def test_mac_chrome_profile_expands_home_and_spaces(self):
        folder = self.home / "Library/Application Support/Google/Chrome"
        folder.mkdir(parents=True)
        with patch.dict(os.environ, {"HOME": str(self.home)}):
            self.assertEqual(self.helpers().find_default_profile_directory(), str(folder))

    def test_mac_chromium_profile_is_detected_when_chrome_is_absent(self):
        folder = self.home / "Library/Application Support/Chromium"
        folder.mkdir(parents=True)
        with patch.dict(os.environ, {"HOME": str(self.home)}):
            self.assertEqual(self.helpers().find_default_profile_directory(), str(folder))

    def test_missing_profiles_return_none(self):
        module = self.helpers()
        with patch.object(module.os.path, "exists", return_value=False):
            self.assertIsNone(module.find_default_profile_directory())

    def start_browser(self, profile, safe=False, fallback=None):
        settings = types.SimpleNamespace(
            run_in_background=False, stealth_mode=False, disable_extensions=False,
            safe_mode=safe, chrome_profile_path=profile, file_name="applied.csv",
            failed_file_name="failed.csv", logs_folder_path=str(self.home / "logs"),
            generated_resume_path=str(self.home / "resumes"),
        )
        helpers = types.SimpleNamespace(
            make_directories=Mock(), find_default_profile_directory=Mock(return_value=fallback),
            critical_error_log=Mock(), print_lg=Mock(),
        )
        driver = Mock()
        with patch.dict(os.environ, {"HOME": str(self.home)}), patch.dict(sys.modules, {
            "config.settings": settings,
            "config.questions": types.SimpleNamespace(default_resume_path="resume.pdf"),
            "modules.helpers": helpers,
        }), patch("selenium.webdriver.Chrome", return_value=driver) as constructor:
            runpy.run_path(str(ROOT / "modules/open_chrome.py"))
        helpers.critical_error_log.assert_not_called()
        driver.maximize_window.assert_called_once()
        return constructor.call_args.kwargs["options"].arguments, helpers

    def test_configured_profile_is_created_and_used_instead_of_default(self):
        arguments, helpers = self.start_browser("~/JobRobo dedicated profile")
        expected = self.home / "JobRobo dedicated profile"
        self.assertTrue(expected.is_dir())
        self.assertIn("--user-data-dir=" + str(expected), arguments)
        helpers.find_default_profile_directory.assert_not_called()

    def test_empty_override_uses_detected_default(self):
        expected = self.home / "detected profile"
        arguments, helpers = self.start_browser("", fallback=str(expected))
        self.assertIn("--user-data-dir=" + str(expected), arguments)
        helpers.find_default_profile_directory.assert_called_once()

    def test_safe_mode_ignores_override_and_profile_detection(self):
        arguments, helpers = self.start_browser("~/unused profile", safe=True)
        self.assertFalse((self.home / "unused profile").exists())
        self.assertFalse(any(arg.startswith("--user-data-dir=") for arg in arguments))
        helpers.find_default_profile_directory.assert_not_called()


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse

from modules.linkedin_search import AI_INPUT_XPATH, apply_configured_filters, start_search
from modules.search_planner import SearchSpec


def spec():
    return SearchSpec("manual:test", "Find AI & ML roles in SF", "manual", "ai", "test", "1", {}, 1, "AI & ML Engineer #Python")


class SearchUITests(unittest.TestCase):
    def field(self, visible=True):
        field = Mock()
        field.is_displayed.return_value = visible
        field.is_enabled.return_value = True
        return field

    def browser(self, fields):
        driver = Mock()
        driver.find_elements.side_effect = lambda by, selector: fields if selector == AI_INPUT_XPATH else []
        return driver

    def test_ai_submits_natural_language_and_waits_for_updated_results(self):
        field = self.field()
        browser = self.browser([field])
        wait, results = Mock(), Mock()
        result = start_search(browser, spec(), wait, results)
        self.assertEqual(result.mode, "ai")
        self.assertIsNone(result.fallback_reason)
        field.clear.assert_called_once()
        self.assertEqual(field.send_keys.call_args_list[0].args, (spec().query_text,))
        self.assertEqual(field.send_keys.call_args_list[1].args, ("\ue007",))
        results.assert_called_once_with([])
        browser.get.assert_called_once_with("https://www.linkedin.com/jobs/")

    def test_ai_control_can_be_exposed_on_results_page(self):
        field = self.field()
        browser = self.browser([])
        discoveries = iter([[], [field]])
        browser.find_elements.side_effect = lambda by, selector: next(discoveries) if selector == AI_INPUT_XPATH else []
        result = start_search(browser, spec(), Mock())
        self.assertEqual(result.mode, "ai")
        url = browser.get.call_args_list[-1].args[0]
        self.assertEqual(parse_qs(urlparse(url).query)["keywords"], [spec().query_text])

    def test_identical_query_already_loaded_does_not_wait_for_card_staleness(self):
        field = self.field()
        field.get_attribute.return_value = spec().query_text
        browser = self.browser([field])
        browser.current_url = "https://www.linkedin.com/jobs/search/?keywords=already-loaded"
        results = Mock()
        result = start_search(browser, spec(), Mock(), results)
        self.assertEqual(result.mode, "ai")
        results.assert_called_once_with([])
        field.clear.assert_not_called()
        field.send_keys.assert_not_called()

    def test_missing_or_hidden_ai_control_falls_back_to_encoded_keywords(self):
        for fields in ([], [self.field(False)]):
            with self.subTest(fields=fields):
                browser = self.browser(fields)
                result = start_search(browser, spec(), Mock())
                self.assertEqual(result.mode, "classic")
                self.assertIn("unavailable", result.fallback_reason)
                url = browser.get.call_args.args[0]
                self.assertEqual(parse_qs(urlparse(url).query)["keywords"], [spec().classic_query])
                self.assertNotIn("#Python", url)

    def test_ai_input_or_result_failure_falls_back_and_records_reason(self):
        for failure_at in ("input", "results"):
            with self.subTest(failure_at=failure_at):
                field = self.field()
                browser = self.browser([field])
                results = Mock()
                if failure_at == "input":
                    field.clear.side_effect = RuntimeError("UI changed")
                else:
                    results.side_effect = TimeoutError("No fresh results")
                result = start_search(browser, spec(), Mock(), results)
                self.assertEqual(result.mode, "classic")
                self.assertIn("failed", result.fallback_reason)
                self.assertEqual(parse_qs(urlparse(browser.get.call_args.args[0]).query)["keywords"], [spec().classic_query])

    def test_classic_navigation_failure_propagates_for_resumable_run(self):
        browser = self.browser([])
        browser.get.side_effect = [None, None, RuntimeError("Browser closed")]
        with self.assertRaisesRegex(RuntimeError, "Browser closed"):
            start_search(browser, spec(), Mock())


class CompatibleFilterTests(unittest.TestCase):
    def test_unavailable_sort_does_not_prevent_other_filters(self):
        attempted = []
        def select(key, value):
            attempted.append((key, value))
            return key != "sort_by"
        warnings = apply_configured_filters({
            "sort_by": "Most recent", "date_posted": "Past month", "job_type": ["Full-time"],
            "on_site": ["Remote", "Hybrid"], "easy_apply_only": True,
        }, select)
        self.assertEqual(len(warnings), 1)
        self.assertIn("sort_by=Most recent", warnings[0])
        self.assertIn(("on_site", "Hybrid"), attempted)
        self.assertIn(("easy_apply_only", "Easy Apply"), attempted)

    def test_filter_exception_is_warning_and_remaining_booleans_still_attempted(self):
        attempted = []
        def select(key, value):
            attempted.append(key)
            if key == "companies":
                raise RuntimeError("No picker")
            return key != "in_your_network"
        warnings = apply_configured_filters({
            "companies": ["Example"], "under_10_applicants": True,
            "in_your_network": True, "fair_chance_employer": True,
        }, select)
        self.assertEqual(len(warnings), 2)
        self.assertIn("RuntimeError", warnings[0])
        self.assertIn("fair_chance_employer", attempted)

    def test_empty_configuration_does_not_click_controls(self):
        select = Mock()
        self.assertEqual(apply_configured_filters({}, select), [])
        select.assert_not_called()


if __name__ == "__main__":
    unittest.main()

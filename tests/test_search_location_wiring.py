"""Location selection and canonical gate wiring without browser side effects."""

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules.linkedin_search import apply_configured_filters
from test_search_runner import MissingElement, extract_functions, spec


DESIRED = "San Francisco Bay Area"


class FilterBrowser:
    def __init__(self, reset_location=False):
        self.location = DESIRED
        self.reset_location = reset_location
        self.filters_opened = False
        self.results_shown = False

    def find_element(self, by, selector):
        def click():
            self.filters_opened = True
        return SimpleNamespace(click=click)

    def find_elements(self, by, selector):
        if "Apply current filters" in selector or "Show results" in selector:
            def click():
                self.results_shown = True
                if self.reset_location:
                    self.location = "New York, United States"
            return [SimpleNamespace(click=click)]
        return []


class LocationWiringTests(unittest.TestCase):
    def setUp(self):
        self.browser = FilterBrowser()
        self.confirmation = {"location": DESIRED, "geography": {"geoId": ["90000084"]}}
        self.namespace = {
            "driver": self.browser, "By": SimpleNamespace(XPATH="xpath"),
            "NoSuchElementException": MissingElement, "buffer": Mock(),
            "search_location": "New York, United States", "pause_after_filters": False,
            "wait_for_search_results": Mock(), "print_lg": Mock(), "try_xp": Mock(),
            "scroll_to_view": Mock(), "company_search_click": Mock(),
            "apply_configured_filters": apply_configured_filters,
            "set_search_location": Mock(return_value=self.confirmation),
        }

    def search(self, mode="classic", location=DESIRED):
        current = spec("location-wiring")
        current.mode = mode
        current.filters_snapshot["intent"] = {"search_location": location}
        return current

    def filters(self, current):
        extract_functions(self.namespace, "apply_filters")
        return self.namespace["apply_filters"](current)

    def test_classic_filter_uses_snapshot_location_and_verifies_commit_after_show_results(self):
        def verify(driver, confirmation, **kwargs):
            self.assertTrue(driver.results_shown)
            self.assertEqual(confirmation, self.confirmation)

        with patch("modules.linkedin_search.verify_search_location", side_effect=verify) as verifier:
            warnings = self.filters(self.search())
        self.namespace["set_search_location"].assert_called_once_with(DESIRED)
        verifier.assert_called_once()
        self.assertEqual(warnings, [])

    def test_classic_uncommitted_location_raises_before_filter_results_can_be_used(self):
        from modules.linkedin_search import LocationSelectionError

        self.namespace["set_search_location"].side_effect = LocationSelectionError("Requested geography was not committed")
        with patch("modules.linkedin_search.verify_search_location") as verifier:
            with self.assertRaises(LocationSelectionError):
                self.filters(self.search())
        self.assertFalse(self.browser.results_shown)
        verifier.assert_not_called()

    def test_ai_missing_location_control_warns_and_keeps_mandatory_gate_requirements(self):
        from modules.linkedin_search import LocationSelectionError

        current = self.search("ai")
        self.namespace["set_search_location"].side_effect = LocationSelectionError("Location picker unavailable in AI search")
        with patch("modules.linkedin_search.verify_search_location") as verifier:
            warnings = self.filters(current)
        self.assertTrue(any("location" in warning.casefold() for warning in warnings))
        self.assertTrue(self.browser.results_shown)
        self.assertEqual(current.filters_snapshot["intent"]["search_location"], DESIRED)
        verifier.assert_not_called()

    def test_filters_resetting_committed_location_are_fatal_in_both_search_modes(self):
        from modules.linkedin_search import LocationSelectionError

        self.browser.reset_location = True

        def verify(driver, confirmation, **kwargs):
            self.assertTrue(driver.results_shown)
            if driver.location != confirmation["location"]:
                raise LocationSelectionError("Show results reset the committed location")

        for mode in ("classic", "ai"):
            with self.subTest(mode=mode), patch("modules.linkedin_search.verify_search_location", side_effect=verify):
                with self.assertRaises(LocationSelectionError):
                    self.filters(self.search(mode))

    def test_empty_snapshot_never_falls_back_to_stale_global_geography(self):
        self.namespace["set_search_location"].return_value = None
        with patch("modules.linkedin_search.verify_search_location") as verifier:
            self.assertEqual(self.filters(self.search(location="")), [])
        for call in self.namespace["set_search_location"].call_args_list:
            self.assertEqual(call.args, ("",))
        verifier.assert_not_called()

    def test_location_wrapper_delegates_explicit_request_and_wait_callback(self):
        extract_functions(self.namespace, "set_search_location")
        with patch("modules.linkedin_search.select_search_location", return_value=self.confirmation) as selector:
            result = self.namespace["set_search_location"](DESIRED)
        self.assertEqual(result, self.confirmation)
        self.assertEqual(selector.call_args.args[:2], (self.browser, DESIRED))
        callback = selector.call_args.args[2] if len(selector.call_args.args) > 2 else selector.call_args.kwargs.get("wait_for_results")
        self.assertIs(callback, self.namespace["wait_for_search_results"])

    def test_direct_location_wrapper_without_argument_uses_current_global_setting(self):
        extract_functions(self.namespace, "set_search_location")
        with patch("modules.linkedin_search.select_search_location", return_value=self.confirmation) as selector:
            self.namespace["set_search_location"]()
        self.assertEqual(selector.call_args.args[:2], (self.browser, self.namespace["search_location"]))

    def test_official_careers_eligibility_uses_the_same_location_reason_helper(self):
        from modules.job_pipeline.careers import evaluate_role

        parent = {"title": "Staff Platform Engineer", "description": "Build production infrastructure",
                  "status": "open", "company": {"name": "Example", "aliases": []},
                  "locations": ["Palo Alto, California"], "workplace_type": "Hybrid", "employment_type": "Full-time"}
        with patch("modules.job_pipeline.careers.location_reasons", return_value=["location_excluded"]) as location:
            result = evaluate_role(parent, {"search_location": DESIRED})
        self.assertFalse(result["eligible"])
        self.assertIn("location_excluded", result["exclusion_reasons"])
        location.assert_called_once()
        self.assertEqual(location.call_args.args[0], parent["locations"])
        self.assertEqual(location.call_args.args[1], "Hybrid")
        self.assertEqual(location.call_args.args[2].casefold(), DESIRED.casefold())


if __name__ == "__main__":
    unittest.main()

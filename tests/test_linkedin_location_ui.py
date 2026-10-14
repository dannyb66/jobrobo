"""Exercise location commits with a fake browser; no live LinkedIn navigation."""

import builtins
import runpy
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from modules.linkedin_search import (
    LOCATION_INPUT_XPATH, LOCATION_LEGACY_ROOT_XPATH, LOCATION_LISTBOX_XPATH,
    LOCATION_OPTIONS_XPATH, RESULT_LOCATION_XPATH, LocationSelectionError,
    select_search_location, verify_search_location,
)


DESIRED = "San Francisco Bay Area, United States"


class Element:
    def __init__(self, browser, kind, text="", *, visible=True, enabled=True):
        self.browser, self.kind, self.text = browser, kind, text
        self.visible, self.enabled = visible, enabled
        self.id = str(id(self))

    def is_displayed(self):
        return self.visible and (self.kind not in {"option", "root"} or self.browser.expanded)

    def is_enabled(self):
        return self.enabled

    def get_attribute(self, name):
        if self.kind == "field":
            return {"id": "jobs-search-box-location-id", "aria-label": "City, state, or zip code",
                    "aria-controls": "location-options" if self.browser.controls else "",
                    "aria-expanded": str(self.browser.expanded).lower(), "value": self.browser.value}.get(name)
        return None

    def find_elements(self, by, selector):
        if self.kind == "root" and selector == LOCATION_OPTIONS_XPATH:
            return self.browser.options
        if self.kind == "field" and selector == LOCATION_LEGACY_ROOT_XPATH:
            return [self.browser.root] if self.browser.legacy else []
        raise AssertionError((self.kind, by, selector))

    def click(self):
        if self.kind == "option":
            self.browser.clicked.append(self.text)
            if self.browser.commit_enabled:
                self.browser.selected = self.text
                self.browser.value = self.text
                self.browser.expanded = False
                if not self.browser.needs_enter:
                    self.browser.update_results()

    def clear(self):
        self.browser.value = ""

    def send_keys(self, value):
        self.browser.keys.append(value)
        if value == "\ue007":
            if not self.browser.selected or self.browser.expanded:
                raise AssertionError("Enter before an exact committed option")
            self.browser.update_results()
        else:
            self.browser.value = value
            self.browser.expanded = True


class Browser:
    def __init__(self, labels=None):
        self.current_url = "https://www.linkedin.com/jobs/search/?" + urlencode({
            "keywords": "Staff Engineer", "geoId": "US", "location": "United States", "f_TPR": "r2592000", "f_WT": "2,3"})
        self.value, self.heading = "United States", "Engineer in United States"
        self.expanded, self.controls, self.listbox, self.legacy = False, True, True, False
        self.commit_enabled, self.needs_enter = True, False
        self.update_geo, self.update_location, self.update_heading = True, True, True
        self.field = Element(self, "field")
        self.hidden = Element(self, "field", visible=False)
        self.disabled = Element(self, "field", enabled=False)
        self.root = Element(self, "root")
        self.options = [Element(self, "option", label) for label in (labels or ["United States", "San Francisco Bay Area"])]
        self.cards = [object(), object()]
        self.keys, self.clicked, self.polls = [], [], 0
        self.fields_available = True

    def find_elements(self, by, selector):
        if selector == LOCATION_INPUT_XPATH:
            return [self.hidden, self.disabled, self.field] if self.fields_available else []
        if by == "id" and selector == "location-options":
            return [self.root]
        if selector == LOCATION_LISTBOX_XPATH:
            return [self.root] if self.listbox else []
        if selector == RESULT_LOCATION_XPATH:
            return [Element(self, "heading", self.heading)] if self.heading else []
        if selector == "//li[@data-occludable-job-id]":
            return self.cards
        raise AssertionError((by, selector))

    def update_results(self):
        parsed = urlparse(self.current_url)
        query = parse_qs(parsed.query)
        if self.update_geo:
            query["geoId"] = ["BAY_AREA"]
        if self.update_location:
            query["location"] = [self.selected]
        if self.update_heading:
            self.heading = "Engineer in " + self.selected
        self.current_url = urlunparse(parsed._replace(query=urlencode(query, doseq=True)))

    def wait(self, predicate):
        for _ in range(4):
            self.polls += 1
            value = predicate(self)
            if value:
                return value
        raise TimeoutError("UI did not establish the requested condition")


class LocationSelectionTests(unittest.TestCase):
    def select(self, browser=None, desired=DESIRED, results=None):
        browser = browser or Browser()
        return select_search_location(browser, desired, results, wait=browser.wait)

    def test_exact_autocomplete_selection_ignores_country_first_and_preserves_other_filters(self):
        browser, results = Browser(), Mock()
        original = parse_qs(urlparse(browser.current_url).query)
        confirmation = self.select(browser, results=results)
        self.assertEqual(browser.clicked, ["San Francisco Bay Area"])
        self.assertNotIn("\ue007", browser.keys)
        self.assertEqual(confirmation["location"], DESIRED)
        self.assertEqual(confirmation["geography"], {"geoId": ["BAY_AREA"], "location": ["San Francisco Bay Area"]})
        for name in ("keywords", "f_TPR", "f_WT"):
            self.assertEqual(parse_qs(urlparse(browser.current_url).query)[name], original[name])
        results.assert_called_once_with(browser.cards)
        self.assertIsNone(verify_search_location(browser, confirmation, wait=browser.wait))

    def test_full_exact_label_wins_over_country_omitted_equivalent(self):
        browser = Browser(["San Francisco Bay Area", "United States", DESIRED])
        self.select(browser)
        self.assertEqual(browser.clicked, [DESIRED])

    def test_case_spacing_and_multiline_country_display_are_normalized(self):
        browser = Browser(["  SAN FRANCISCO BAY AREA\nUnited States  "])
        self.select(browser, " San Francisco   Bay Area, United States ")
        self.assertEqual(len(browser.clicked), 1)

    def test_enter_can_submit_only_after_exact_option_is_committed(self):
        browser = Browser()
        browser.needs_enter = True
        self.select(browser)
        self.assertEqual(browser.clicked, ["San Francisco Bay Area"])
        self.assertEqual(browser.keys[-1], "\ue007")

    def test_hidden_disabled_and_wrong_suggestions_are_never_selected(self):
        browser = Browser(["United States", "San Francisco", "San Francisco Bay Area, India"])
        browser.options.append(Element(browser, "option", DESIRED, visible=False))
        browser.options.append(Element(browser, "option", DESIRED, enabled=False))
        results = Mock()
        with self.assertRaises(LocationSelectionError):
            self.select(browser, results=results)
        self.assertEqual(browser.clicked, [])
        self.assertNotIn("\ue007", browser.keys)
        results.assert_not_called()

    def test_missing_picker_and_ambiguous_exact_suggestions_fail_closed(self):
        missing = Browser()
        missing.fields_available = False
        ambiguous = Browser([DESIRED, DESIRED])
        for browser in (missing, ambiguous):
            with self.subTest(browser=browser), self.assertRaises(LocationSelectionError):
                self.select(browser)
            self.assertEqual(browser.clicked, [])

    def test_typed_text_without_committed_suggestion_is_insufficient(self):
        browser, results = Browser(), Mock()
        browser.commit_enabled = False
        with self.assertRaises(LocationSelectionError):
            self.select(browser, results=results)
        self.assertEqual(browser.value, DESIRED)
        self.assertNotIn("\ue007", browser.keys)
        results.assert_not_called()

    def test_changed_url_with_stale_country_or_other_region_results_is_insufficient(self):
        for stale in ("Engineer in United States", "Engineer in New York"):
            with self.subTest(stale=stale):
                browser, results = Browser(), Mock()
                browser.heading = stale
                browser.update_heading = False
                with self.assertRaises(LocationSelectionError):
                    self.select(browser, results=results)
                self.assertEqual(parse_qs(urlparse(browser.current_url).query)["geoId"], ["BAY_AREA"])
                results.assert_not_called()

    def test_matching_heading_with_unchanged_url_geography_is_insufficient(self):
        browser = Browser()
        browser.update_geo = browser.update_location = False
        with self.assertRaises(LocationSelectionError):
            self.select(browser)

    def test_text_location_url_change_cannot_reuse_the_old_country_geo_id(self):
        browser = Browser()
        browser.update_geo = False
        with self.assertRaises(LocationSelectionError):
            self.select(browser)
        self.assertEqual(parse_qs(urlparse(browser.current_url).query)["geoId"], ["US"])

    def test_stale_suggestion_click_fails_closed_without_enter_or_results_wait(self):
        browser, results = Browser(), Mock()
        browser.options[-1].click = Mock(side_effect=RuntimeError("stale element reference"))
        with self.assertRaises(LocationSelectionError):
            self.select(browser, results=results)
        self.assertNotIn("\ue007", browser.keys)
        results.assert_not_called()

    def test_exact_label_and_new_geography_can_confirm_when_heading_is_absent(self):
        browser = Browser()
        browser.heading, browser.update_heading = "", False
        self.assertEqual(self.select(browser)["geography"]["geoId"], ["BAY_AREA"])

    def test_query_location_mismatch_is_rejected_even_with_new_geo_id_and_heading(self):
        browser = Browser()
        browser.update_location = False
        with self.assertRaises(LocationSelectionError):
            self.select(browser)

    def test_results_callback_runs_after_confirmation_and_valid_empty_results_are_accepted(self):
        browser = Browser()
        browser.cards = []
        seen = []
        def results(previous):
            self.assertEqual(browser.heading, "Engineer in San Francisco Bay Area")
            self.assertEqual(previous, [])
            seen.append("empty results confirmed")
        self.select(browser, results=results)
        self.assertEqual(seen, ["empty results confirmed"])

    def test_failed_results_refresh_propagates_as_location_error(self):
        with self.assertRaises(LocationSelectionError):
            self.select(Browser(), results=Mock(side_effect=TimeoutError("old cards persisted")))

    def test_aria_listbox_and_legacy_typeahead_fallbacks(self):
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                browser = Browser()
                browser.controls, browser.legacy, browser.listbox = False, legacy, not legacy
                self.select(browser)
                self.assertEqual(browser.clicked, ["San Francisco Bay Area"])

    def test_existing_correct_results_are_a_verified_noop_but_input_alone_is_not(self):
        browser, results = Browser(), Mock()
        browser.current_url = "https://www.linkedin.com/jobs/search/?geoId=BAY_AREA"
        browser.heading = "Engineer in San Francisco Bay Area"
        confirmation = self.select(browser, results=results)
        self.assertEqual(confirmation["geography"], {"geoId": ["BAY_AREA"]})
        self.assertEqual(browser.keys, [])
        self.assertEqual(browser.clicked, [])
        results.assert_not_called()
        browser = Browser()
        browser.value = DESIRED
        browser.commit_enabled = False
        with self.assertRaises(LocationSelectionError):
            self.select(browser)

    def test_conflicting_visible_results_geographies_never_become_a_verified_noop(self):
        class ConflictingBrowser(Browser):
            def find_elements(self, by, selector):
                if selector == RESULT_LOCATION_XPATH:
                    return [Element(self, "heading", "Staff Engineer in San Francisco Bay Area"),
                            Element(self, "heading", "Engineer in United States")]
                return super().find_elements(by, selector)
        browser, results = ConflictingBrowser(), Mock()
        browser.current_url = "https://www.linkedin.com/jobs/search/?geoId=US"
        with self.assertRaises(LocationSelectionError):
            self.select(browser, results=results)
        self.assertEqual(browser.clicked, ["San Francisco Bay Area"])
        results.assert_not_called()

    def test_results_selector_does_not_read_arbitrary_job_detail_h1(self):
        self.assertNotIn("//h1 |", RESULT_LOCATION_XPATH)
        self.assertIn("jobs-search-results", RESULT_LOCATION_XPATH)

    def test_job_detail_title_cannot_supply_location_proof_for_country_results(self):
        try:
            from lxml import etree
        except ImportError:
            self.skipTest("DOM XPath verification requires the project's lxml dependency")
        class DOMBrowser(Browser):
            def find_elements(self, by, selector):
                if selector == RESULT_LOCATION_XPATH:
                    dom = etree.HTML('<h1 class="job-details-title">Staff Engineer in San Francisco Bay Area</h1>'
                                     '<div class="jobs-search-results-list__header"><h1 class="jobs-search-results-list__title-heading"></h1></div>')
                    dom.xpath("//h1[@class='jobs-search-results-list__title-heading']")[0].text = self.heading
                    matches = dom.xpath(selector)
                    self.visible_result_labels = ["".join(node.itertext()) for node in matches]
                    return [Element(self, "heading", label) for label in self.visible_result_labels]
                return super().find_elements(by, selector)
        browser = DOMBrowser()
        browser.current_url = "https://www.linkedin.com/jobs/search/?geoId=US"
        self.select(browser)
        self.assertEqual(browser.clicked, ["San Francisco Bay Area"])
        self.assertEqual(browser.visible_result_labels, ["Engineer in San Francisco Bay Area"])

    def test_blank_configuration_is_a_noop_and_module_import_is_side_effect_free(self):
        driver = Mock()
        for value in (None, "", "   "):
            self.assertIsNone(select_search_location(driver, value))
        driver.assert_not_called()
        driver.find_elements.assert_not_called()
        original_import = builtins.__import__
        def guarded_import(name, *args, **kwargs):
            if name.startswith("selenium"):
                raise AssertionError("Selenium imported while loading adapter")
            return original_import(name, *args, **kwargs)
        with patch("builtins.__import__", side_effect=guarded_import):
            runpy.run_path(str(Path(__file__).resolve().parents[1] / "modules/linkedin_search.py"))


class LocationReverificationTests(unittest.TestCase):
    def test_all_filters_reset_of_location_is_rejected(self):
        browser = Browser()
        confirmation = select_search_location(browser, DESIRED, wait=browser.wait)
        browser.current_url = "https://www.linkedin.com/jobs/search/?geoId=US&location=United+States"
        browser.heading = "Engineer in United States"
        with self.assertRaises(LocationSelectionError):
            verify_search_location(browser, confirmation, wait=browser.wait)

    def test_reverification_rejects_stale_heading_even_when_url_is_unchanged(self):
        browser = Browser()
        confirmation = select_search_location(browser, DESIRED, wait=browser.wait)
        browser.heading = "Engineer in United States"
        with self.assertRaises(LocationSelectionError):
            verify_search_location(browser, confirmation, wait=browser.wait)

    def test_missing_or_invalid_prior_confirmation_cannot_use_typed_text_as_proof(self):
        browser = Browser()
        browser.value = DESIRED
        self.assertIsNone(verify_search_location(browser, None, wait=browser.wait))
        for confirmation in ({}, {"location": DESIRED, "geography": {}}, {"location": DESIRED, "geography": "BAY_AREA"}):
            with self.subTest(confirmation=confirmation), self.assertRaises(LocationSelectionError):
                verify_search_location(browser, confirmation, wait=browser.wait)


if __name__ == "__main__":
    unittest.main()

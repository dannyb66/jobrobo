"""Company navigation policy with synthetic controls; never an employer action."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from test_search_runner import extract_functions


class LinkedInRouteGuardTests(unittest.TestCase):
    def namespace(self, easy_only):
        driver = Mock()
        driver.find_element.return_value.text = "No warning"
        driver.current_url = "https://careers.example.com/synthetic"
        driver.window_handles = ["linkedin", "external"]
        namespace = {
            "driver": driver, "wait": Mock(),
            "EC": SimpleNamespace(element_to_be_clickable=lambda locator: locator),
            "By": SimpleNamespace(XPATH="xpath", CLASS_NAME="class"),
            "easy_apply_only": easy_only, "tabs_count": 1,
            "dailyEasyApplyLimitReached": False, "linkedIn_tab": "linkedin", "close_tabs": True,
            "wait_span_click": Mock(), "print_lg": Mock(), "failed_job": Mock(), "failed_count": 0,
        }
        extract_functions(namespace, "external_apply")
        return namespace

    def route(self, ns, pagination=None):
        return ns["external_apply"](pagination, "123", "https://www.linkedin.com/jobs/view/123",
                                    "Pending", "Unknown", "Easy Applied", "Not Available")

    def test_easy_only_blocks_company_navigation_with_or_without_pagination(self):
        for pagination in (None, Mock()):
            with self.subTest(pagination=pagination):
                ns = self.namespace(True)
                self.assertTrue(self.route(ns, pagination)[0])
                ns["wait"].until.assert_not_called()

    def test_easy_only_still_detects_daily_application_limit(self):
        ns = self.namespace(True)
        ns["driver"].find_element.return_value.text = "You have exceeded the daily application limit"
        self.route(ns)
        self.assertTrue(ns["dailyEasyApplyLimitReached"])
        ns["wait"].until.assert_not_called()

    def test_mixed_route_collects_company_url_and_returns_to_linkedin(self):
        ns = self.namespace(False)
        self.assertEqual(self.route(ns), (False, ns["driver"].current_url, 2))
        ns["wait"].until.return_value.click.assert_called_once()
        ns["driver"].switch_to.window.assert_called_with("linkedin")

    def test_modern_company_anchor_is_scoped_to_expected_job(self):
        from lxml import html
        ns = self.namespace(False)
        markup = html.fromstring('''<main><a aria-label="Apply on company website" id="wrong">Apply</a>
          <div data-view-name="job-detail-page"><span aria-label="Company, Example."></span>
          <section id="JobDetails_AboutTheJob_123"></section>
          <a aria-label="Apply on company website" id="correct">Apply</a>
          <button>Submit application</button></div></main>''')
        def locate(locator):
            matches = markup.xpath(locator[1])
            self.assertEqual([node.get("id") for node in matches], ["correct"])
            return Mock()
        ns["wait"].until.side_effect = locate
        self.assertEqual(self.route(ns)[0], False)
        ns["failed_job"].assert_not_called()

    def test_company_ancestor_fallback_does_not_select_unrelated_anchor(self):
        from lxml import html
        ns = self.namespace(False)
        markup = html.fromstring('''<main><a aria-label="Apply on company website" id="wrong">Apply</a>
          <article><span aria-label="Company, Example."></span>
          <section id="JobDetails_AboutTheJob_123"></section>
          <a aria-label="Apply on company website" id="correct">Apply</a></article></main>''')
        def locate(locator):
            self.assertEqual([node.get("id") for node in markup.xpath(locator[1])], ["correct"])
            return Mock()
        ns["wait"].until.side_effect = locate
        self.assertFalse(self.route(ns)[0])
        ns["failed_job"].assert_not_called()

    def test_missing_company_anchor_records_failure_without_navigation(self):
        ns = self.namespace(False)
        ns["wait"].until.side_effect = TimeoutError("Synthetic missing Apply anchor")
        self.assertTrue(self.route(ns)[0])
        ns["failed_job"].assert_called_once()
        self.assertEqual(ns["failed_count"], 1)
        ns["driver"].switch_to.window.assert_not_called()

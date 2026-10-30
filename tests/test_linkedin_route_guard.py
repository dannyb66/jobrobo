"""Routing policy checks; synthetic driver only, never a live application."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules.external_apply import ExternalApplicationResult
from test_search_runner import extract_functions


class LinkedInRouteGuardTests(unittest.TestCase):
    def namespace(self, easy_only, hosted=False):
        handoff = patch('modules.linkedin_external_submit.open_employer_tab',
                        return_value=('external', 'https://jobs.lever.co/example/synthetic/apply'))
        self.handoff = handoff.start()
        self.addCleanup(handoff.stop)
        capture = patch('modules.linkedin_failure_recovery.capture_failure', return_value={})
        capture.start()
        self.addCleanup(capture.stop)
        driver = Mock()
        driver.find_element.return_value.text = "No warning"
        driver.current_url = "https://jobs.lever.co/example/synthetic/apply"
        driver.current_window_handle = "linkedin"
        driver.window_handles = ["linkedin", "external"]
        namespace = {
            "driver": driver, "wait": Mock(),
            "EC": SimpleNamespace(element_to_be_clickable=lambda locator: locator),
            "By": SimpleNamespace(XPATH="xpath", CLASS_NAME="class"),
            "easy_apply_only": easy_only, "external_apply_enabled": hosted,
            "tabs_count": 1, "dailyEasyApplyLimitReached": False,
            "linkedIn_tab": "linkedin", "close_tabs": True,
            "wait_span_click": Mock(), "print_lg": Mock(),
            "failed_job": Mock(), "failed_count": 0,
            "search_profile": SimpleNamespace(search_state_dir='logs/search_runs'),
            "prepare_external_application": Mock(return_value=ExternalApplicationResult(
                "awaiting_review", driver.current_url, reason="Synthetic review only")),
        }
        extract_functions(namespace, "external_apply")
        return namespace

    def run_route(self, namespace, pagination=None):
        return namespace["external_apply"](pagination, "123", "https://www.linkedin.com/jobs/view/123",
                                           "Pending", "Unknown", "Easy Applied", "Not Available",
                                           job_title="Synthetic Engineer", company="Example")

    def test_easy_only_without_pagination_never_clicks_employer_apply(self):
        namespace = self.namespace(True)
        self.assertTrue(self.run_route(namespace)[0])
        namespace["wait"].until.assert_not_called()
        namespace["prepare_external_application"].assert_not_called()
        namespace["failed_job"].assert_not_called()

    def test_easy_only_guard_applies_with_hosted_preparation_enabled(self):
        namespace = self.namespace(True, hosted=True)
        self.assertTrue(self.run_route(namespace)[0])
        namespace["wait"].until.assert_not_called()
        namespace["prepare_external_application"].assert_not_called()

    def test_easy_only_still_detects_daily_limit_before_returning(self):
        namespace = self.namespace(True)
        namespace["driver"].find_element.return_value.text = "You have exceeded the daily application limit"
        self.run_route(namespace)
        self.assertTrue(namespace["dailyEasyApplyLimitReached"])
        namespace["wait"].until.assert_not_called()

    def test_mixed_route_collects_company_link_when_preparation_disabled(self):
        namespace = self.namespace(False)
        result = self.run_route(namespace)
        self.assertEqual(result, (False, namespace["driver"].current_url, 2))
        self.handoff.assert_called_once_with(namespace['driver'], '123')
        namespace["prepare_external_application"].assert_not_called()
        namespace["driver"].switch_to.window.assert_called_with("linkedin")

    def test_mixed_route_dispatches_company_preparation_and_preserves_draft(self):
        namespace = self.namespace(False, hosted=True)
        result = self.run_route(namespace)
        self.assertEqual(result.status, "awaiting_review")
        namespace["prepare_external_application"].assert_called_once_with(
            namespace["driver"].current_url, "123", "Synthetic Engineer", "", "Example")
        namespace["driver"].switch_to.window.assert_called_with("linkedin")

    def test_handoff_is_bound_to_selected_job_and_retains_unresolved_tab(self):
        namespace = self.namespace(False, hosted=True)
        result = self.run_route(namespace)
        self.assertEqual(getattr(result, 'status', None), 'awaiting_review')
        self.handoff.assert_called_once_with(namespace['driver'], '123')
        self.assertIn('external', namespace['retained_external_tabs'])
        namespace['driver'].close.assert_not_called()
        namespace['failed_job'].assert_not_called()


if __name__ == "__main__":
    unittest.main()

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from modules.linkedin_failure_recovery import capture_failure, reconcile_submission, role_is_relevant
from test_search_runner import spec


class FailureRecoveryTests(unittest.TestCase):
    def test_structural_navigation_evidence_is_saved_with_failure(self):
        error = ValueError('Form kept changing')
        error.navigation_evidence = [{'before': {'action':'review','page':'4/6 pages'},
                                      'after': {'action':'next','page':'4/6 pages'}}]
        driver = SimpleNamespace(current_url='https://www.linkedin.com/jobs/view/123/',
            save_screenshot=Mock(return_value=True), execute_script=Mock(return_value='<dialog></dialog>'))
        with TemporaryDirectory() as directory:
            report = capture_failure(driver, '123', 'prepare', error, directory)
            self.assertEqual(json.loads(Path(report['report_path']).read_text())['navigation_evidence'],
                             error.navigation_evidence)

    def test_capture_keeps_screenshot_dom_and_error_even_if_structure_hooks_absent(self):
        with TemporaryDirectory() as directory:
            driver = SimpleNamespace(current_url='https://www.linkedin.com/jobs/view/123/',
                save_screenshot=Mock(return_value=True), execute_script=Mock(return_value='<main>Job form</main>'))
            result = capture_failure(driver, '123', 'prepare', ValueError('Missing upload UI'), directory)
            self.assertIn('screenshot_path', result)
            self.assertEqual(Path(result['dom_path']).read_text(), '<main>Job form</main>')
            self.assertEqual(json.loads(Path(result['report_path']).read_text())['stage'], 'prepare')
            self.assertIn("e.removeAttribute('value')", driver.execute_script.call_args.args[0])

    def test_capture_failure_is_best_effort(self):
        with TemporaryDirectory() as directory:
            driver = SimpleNamespace(current_url='', save_screenshot=Mock(side_effect=RuntimeError()),
                                     execute_script=Mock(side_effect=RuntimeError()))
            result = capture_failure(driver, '123', 'prepare', ValueError('Original'), directory)
            self.assertEqual(result['error'], 'Original')
            self.assertTrue(Path(result['report_path']).is_file())

    def test_reconciliation_checks_posting_without_clicking_anything(self):
        driver = SimpleNamespace(get=Mock())
        with patch('modules.linkedin_easy_apply.job_submission_receipts', side_effect=[set(), {'job:123:application-submitted'}]):
            self.assertTrue(reconcile_submission(driver, '123', timeout=.01))
        driver.get.assert_called_once_with('https://www.linkedin.com/jobs/view/123/')

    def test_absent_receipt_remains_unknown(self):
        driver = SimpleNamespace(get=Mock())
        with patch('modules.linkedin_easy_apply.job_submission_receipts', return_value=set()):
            self.assertFalse(reconcile_submission(driver, '123', timeout=.01))

    def test_engineering_search_rejects_interior_manager(self):
        search = spec('staff')
        search.classic_query = 'Staff AI Platform Engineer'
        self.assertFalse(role_is_relevant('Interior Manager', 'Use AI software for interior work', search))
        self.assertTrue(role_is_relevant('Founding Engineer', 'Build AI systems', search))

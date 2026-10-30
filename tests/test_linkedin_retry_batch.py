import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from modules.linkedin_deferred import DeferredJobs, build_retry_batch
from modules.search_planner import filters_snapshot


class RetryBatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "retry_jobs.json"
        self.profile = {"profile_name": "test", "profile_version": "1"}
        self.config = {"search_location": "San Francisco Bay Area", "easy_apply_only": True}
        self.ledger = DeferredJobs(self.path)

    def tearDown(self):
        self.temp.cleanup()

    def add(self, job_id, status="failed", *, check=False):
        row = self.ledger.record({
            "job_id": job_id,
            "title": "Staff Software Engineer",
            "company": "Example Co",
            "query": "Find Staff Software Engineer roles",
            "status": status,
            "submission_disabled": True,
            "submit_enabled": True,
            "requires_submission_check": check,
        })
        return row

    def test_builds_direct_target_with_current_filters_and_stable_id(self):
        self.add("100")
        specs, selected = build_retry_batch(self.path, self.profile, self.config, 1)
        self.assertEqual(list(selected), [specs[0].query_id])
        self.assertEqual(selected[specs[0].query_id][0]["linkedin_id"], "100")
        self.assertEqual(specs[0].source, "retry")
        self.assertEqual(specs[0].pipeline_context["company"]["name"], "Example Co")
        self.assertEqual(specs[0].filters_snapshot, filters_snapshot(self.config))

    def test_can_select_one_exact_retry_id(self):
        self.add("100")
        self.add("101")
        specs, selected = build_retry_batch(self.path, self.profile, self.config, 5, job_id="100")
        self.assertEqual([job["linkedin_id"] for rows in selected.values() for job in rows], ["100"])

    def test_excludes_applied_and_uncertain_records(self):
        self.add("100", "applied")
        self.add("101", "failed", check=True)
        self.add("102", "failed")
        self.add("103", "failed")
        specs, selected = build_retry_batch(self.path, self.profile, self.config, 1, applied_ids={"103"})
        self.assertEqual([job["linkedin_id"] for rows in selected.values() for job in rows], ["102"])

    def test_refuses_uncertain_only_ledger(self):
        self.add("100", check=True)
        with self.assertRaisesRegex(ValueError, "submission outcome must be checked"):
            build_retry_batch(self.path, self.profile, self.config, 1)

    def test_external_manual_blocker_is_retained_but_not_auto_selected(self):
        for job_id, retryable in [('100', False), ('101', True)]:
            self.add(job_id)
            self.ledger.record({'job_id':job_id, 'status':'failed', 'submission_disabled':False,
                'external_application':{'direct_status':'blocked', 'retryable':retryable}})
        _, selected = build_retry_batch(self.path, self.profile, self.config, 5)
        self.assertEqual([job['linkedin_id'] for rows in selected.values() for job in rows], ['101'])
        self.assertEqual(len(self.ledger.records), 2)

    def test_retry_submission_pause_defaults_on_and_explicit_opt_in_disables_it(self):
        from test_search_runner import extract_functions
        class StopBeforeBrowser(RuntimeError):
            pass
        for options, expected in [({}, True), ({'auto_submit': True}, False), ({'auto_submit': False}, True)]:
            with self.subTest(options=options):
                namespace = dict(load_runtime=Mock(), validate_config=Mock(),
                                 get_applied_job_ids=lambda: set(), current_pipeline_blocked_ids=set(),
                                 aiClient=None, driver=None)
                def initialize(**kwargs):
                    self.assertEqual(namespace['pause_before_submit'], expected)
                    raise StopBeforeBrowser()
                namespace['initialize_browser'] = Mock(side_effect=initialize)
                extract_functions(namespace, 'run_deferred_retries')
                with patch('modules.linkedin_deferred.build_retry_batch', return_value=([], {})):
                    with self.assertRaises(StopBeforeBrowser):
                        namespace['run_deferred_retries']('unused-ledger.json', 1, **options)
                namespace['initialize_browser'].assert_called_once_with(background=False)


if __name__ == "__main__":
    unittest.main()

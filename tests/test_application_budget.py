"""Submission limits distinguish confirmed outcomes from candidate-work limits."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from modules.application_budget import ApplicationBudget
from modules.search_planner import SearchSpec
from modules.search_state import SearchManifest


class ApplicationBudgetTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.spec = SearchSpec("first", "Engineer", "manual", "classic", "test", "1", {}, 3, "Engineer")
        self.manifest = SearchManifest.create(Path(temporary.name), [self.spec])

    def test_invalid_limits_are_rejected(self):
        for limit in (True, False, 0, -1, 1.0, "1", [], {}):
            with self.subTest(limit=limit), self.assertRaisesRegex(ValueError, "positive integer or None"):
                ApplicationBudget(limit)

    def test_unique_confirmed_submissions_reach_cap_and_preserve_pending_work(self):
        budget = ApplicationBudget(2)
        budget.record("1")
        budget.record("1")
        self.assertFalse(budget.stop_if_reached(self.manifest, self.spec))
        budget.record("2")
        self.manifest.begin_query(self.spec)
        self.manifest.record_job(self.spec, "1", "applied")
        self.manifest.record_job(self.spec, "2", "applied")
        self.assertTrue(budget.stop_if_reached(self.manifest, self.spec))
        self.assertEqual(self.manifest.data["stop_reason"], "application_limit_reached")
        self.assertEqual(self.manifest.data["invocation_applied_count"], 2)
        self.assertNotEqual(self.manifest.query("first")["status"], "complete")
        fresh = ApplicationBudget(2)
        self.assertFalse(fresh.stop_if_reached(self.manifest, self.spec))

    def test_uncertain_submission_stops_active_budget_without_claiming_success(self):
        budget = ApplicationBudget(1)
        self.manifest.record_job(self.spec, "1", "submitting")
        self.assertTrue(budget.stop_if_reached(self.manifest, self.spec))
        self.assertEqual(budget.count, 0)
        self.assertFalse(budget.reached)
        self.assertTrue(budget.stopped)
        self.assertEqual(self.manifest.data["stop_reason"], "submission_uncertain")
        self.assertFalse(ApplicationBudget(None).stop_if_reached(self.manifest, self.spec))

    def test_none_disables_overall_cap(self):
        budget = ApplicationBudget(None)
        for job_id in range(10):
            budget.record(job_id)
        self.assertFalse(budget.stopped)
        self.assertFalse(budget.stop_if_reached(self.manifest, self.spec))

    def test_unknown_submission_reserves_one_slot_and_allows_other_jobs(self):
        budget = ApplicationBudget(3)
        self.manifest.record_job(self.spec, 'unknown', 'submitting')
        self.assertFalse(budget.stop_if_reached(self.manifest, self.spec))
        budget.record('confirmed')
        self.assertFalse(budget.stop_if_reached(self.manifest, self.spec))
        self.assertEqual(budget.count, 1)
        self.assertEqual(self.manifest.data['invocation_reserved_count'], 1)
        budget.record('another')
        self.assertTrue(budget.stop_if_reached(self.manifest, self.spec))
        self.assertEqual(budget.count, 2)

    def test_unknown_reservation_survives_a_new_manifest_in_same_invocation(self):
        budget = ApplicationBudget(2)
        self.manifest.record_job(self.spec, 'unknown', 'submitting')
        self.assertFalse(budget.stop_if_reached(self.manifest, self.spec))
        fresh = SearchManifest.create(self.manifest.path.parent, [self.spec])
        budget.record('confirmed')
        self.assertTrue(budget.stop_if_reached(fresh, self.spec))
        self.assertEqual(budget.count, 1)
        self.assertEqual(budget.reserved_ids, {'unknown'})


if __name__ == "__main__":
    unittest.main()

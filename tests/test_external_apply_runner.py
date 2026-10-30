"""Real runner integration with synthetic hosted outcomes; no browser/credentials."""
from datetime import datetime, timezone
import unittest

from modules.application_budget import ApplicationBudget
from modules.external_apply import ExternalApplicationResult
from modules.search_history import load_applied_job_ids

import test_search_runner as harness


class HostedRunnerTests(unittest.TestCase):
    def setUp(self):
        self.runner = harness.SearchRunnerTests(methodName="test_ai_mode_records_natural_language_query_in_successful_history")
        self.runner.setUp()
        self.addCleanup(self.runner.doCleanups)
        self.namespace = self.runner.namespace
        harness.extract_functions(self.namespace, "checkpoint_external_application", "application_outcome")
        self.namespace.update(external_apply_enabled=True, external_applied_count=0, active_result_sink=None)
        self.namespace["try_xp"] = lambda *args: False
        self.calls = []

    def execute(self, status, quota=2):
        first, second = harness.spec("first", quota), harness.spec("second", quota)
        manifest = self.runner.manifest([first, second], {"first": [["1", "2"]], "second": [["3"]]})
        def external(*args, **kwargs):
            self.calls.append((args[1], kwargs))
            return ExternalApplicationResult(status, "https://jobs.lever.co/example/11111111-1111-4111-8111-111111111111/apply",
                                             provider="lever", ats_job_id="11111111-1111-4111-8111-111111111111",
                                             resume_name="synthetic.pdf", filled_fields=["full_name"],
                                             reason="Synthetic hosted outcome", submitted_at=datetime.now(timezone.utc).isoformat() if status == "applied" else None)
        self.namespace["external_apply"] = external
        budget = ApplicationBudget(1)
        self.runner.execute(manifest, budget)
        return manifest, first, budget

    def test_captcha_solver_flag_enables_solver_and_fails_fast_when_unavailable(self):
        """The flag is explicit opt-in; a broken install must not run half-armed."""
        import os
        from unittest import mock
        from modules import captcha_solver
        from modules.submit_runner import run_submissions

        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CAPTCHA_SOLVER", None)
            with mock.patch.object(captcha_solver, "available", return_value=(False, "no venv")):
                with self.assertRaises(ValueError) as caught:
                    run_submissions([], captcha_solver=True)
            self.assertIn("no venv", str(caught.exception))
            # Enabled even though the check failed, so a later call sees it on.
            self.assertTrue(captcha_solver.enabled())

    def test_confirmed_company_submission_uses_global_cap_and_applied_history(self):
        manifest, search, budget = self.execute("applied")
        self.assertEqual(budget.count, 1)
        self.assertEqual(self.runner.visited, ["1"])
        self.assertEqual(manifest.query(search.query_id)["jobs"]["1"]["status"], "applied")
        self.assertEqual(manifest.query(search.query_id)["jobs"]["1"]["external_application"]["provider"], "lever")
        self.assertEqual(self.namespace["external_applied_count"], 1)
        self.assertEqual(self.namespace["external_jobs_count"], 0)
        self.assertEqual(load_applied_job_ids(self.runner.directory / "applied.csv"), {"1"})
        self.assertEqual(manifest.data["stop_reason"], "application_limit_reached")

    def test_uncertain_company_submission_stops_other_jobs_without_counting_success(self):
        manifest, search, budget = self.execute("submitting")
        self.assertEqual(budget.count, 0)
        self.assertEqual(self.runner.visited, ["1"])
        self.assertEqual(manifest.query(search.query_id)["jobs"]["1"]["status"], "submitting")
        self.assertEqual(manifest.data["stop_reason"], "submission_uncertain")
        self.assertFalse((self.runner.directory / "applied.csv").exists())

    def test_draft_handoff_preserves_external_metadata_and_pending_history(self):
        manifest, search, budget = self.execute("awaiting_review", quota=1)
        self.assertEqual(budget.count, 0)
        outcome = manifest.query(search.query_id)["jobs"]["1"]
        self.assertEqual(outcome["status"], "collected")
        self.assertEqual(outcome["external_application"]["status"], "awaiting_review")
        self.assertEqual(load_applied_job_ids(self.runner.directory / "applied.csv"), set())
        self.assertTrue(all(row["Date Applied"] == "Pending" for row in self.runner.rows()))

    def test_duplicate_target_is_skipped_without_application_or_pending_history(self):
        manifest, search, budget = self.execute("duplicate", quota=1)
        self.assertEqual(budget.count, 0)
        self.assertTrue(all(job["status"] == "skipped" for row in manifest.data["queries"] for job in row["jobs"].values()))
        self.assertFalse((self.runner.directory / "applied.csv").exists())

    def test_external_only_inspects_and_skips_easy_apply_without_opening_form(self):
        self.namespace['application_mode'] = 'external_only'
        calls = []
        self.namespace['open_easy_apply'] = lambda *args, **kw: calls.append(kw) or True
        manifest, search, budget = self.execute('applied')
        self.assertEqual(budget.count, 0)
        self.assertEqual(self.calls, [])
        self.assertTrue(all(kw.get('inspect_only') for kw in calls))

    def test_external_failure_continues_to_next_job_and_keeps_retry(self):
        first = harness.spec('first', 2)
        manifest = self.runner.manifest([first], {'first': [['1', '2']]})
        self.namespace['external_apply'] = lambda *a, **kw: ExternalApplicationResult(
            'failed' if a[1] == '1' else 'applied', 'https://example.test/jobs/'+a[1],
            direct_status='failed_before_submit' if a[1] == '1' else 'applied',
            submitted_at=datetime.now(timezone.utc).isoformat() if a[1] == '2' else None)
        budget = ApplicationBudget(2)
        self.runner.execute(manifest, budget)
        self.assertEqual(self.runner.visited, ['1', '2'])
        self.assertEqual(budget.count, 1)
        self.assertEqual(manifest.query('first')['jobs']['1']['status'], 'failed')
        from modules.linkedin_deferred import DeferredJobs
        records = DeferredJobs(self.runner.directory/'deferred_applications'/'retry_jobs.json').records
        self.assertTrue(any(r['job_id'] == '1' and r['status'] == 'failed' for r in records))

    def test_uncertain_employer_attempt_reserves_one_slot_and_continues(self):
        search=harness.spec('first',3)
        manifest=self.runner.manifest([search],{'first':[['1','2']]})
        self.namespace['external_apply']=lambda *a,**kw:ExternalApplicationResult(
            'submitting' if a[1]=='1' else 'applied','https://example.test/jobs/'+a[1],
            submitted_at=datetime.now(timezone.utc).isoformat() if a[1]=='2' else None)
        budget=ApplicationBudget(3)
        self.runner.execute(manifest,budget)
        self.assertEqual(self.runner.visited,['1','2'])
        self.assertEqual(budget.count,1)
        self.assertEqual(budget.reserved_ids,{'1'})
        self.assertEqual(manifest.query('first')['jobs']['1']['status'],'submitting')


if __name__ == "__main__":
    unittest.main()

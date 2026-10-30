import csv
import json
from pathlib import Path
import tempfile
import unittest

from modules.linkedin_deferred import DeferredJobs, build_retry_batch
from modules.linkedin_retry_reconciliation import reconcile_retry_ledger, sync_retry_checkpoint
from modules.search_planner import SearchSpec
from modules.search_state import SearchManifest


class RetryReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.states = self.root / 'search_runs'
        self.path = self.root / 'deferred_applications' / 'retry_jobs.json'
        self.csv = self.root / 'applied.csv'
        self.ledger = DeferredJobs(self.path)
        self.spec = SearchSpec('query', 'Find Staff Engineer roles', 'manual', 'ai', 'test', '1', {}, 1, 'Staff Engineer')

    def add(self, job_id='123', **kwargs):
        return self.ledger.record(dict(job_id=job_id, status='failed', title='Staff Engineer',
            company='Example', submission_disabled=False, requires_submission_check=False, **kwargs))

    def manifest(self, status, *, job_id='123', date='2026-10-25T12:00:00Z', reason='Test outcome'):
        manifest = SearchManifest.create(self.states, [self.spec])
        manifest.record_job(self.spec, job_id, status, reason)
        manifest.query('query')['jobs'][job_id]['updated_at'] = date
        manifest.save()
        return manifest

    def history(self, records):
        with self.csv.open('w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=['Job ID', 'Title', 'Company', 'Date Applied', 'Search Run ID'])
            writer.writeheader()
            for record in records:
                writer.writerow(record)

    def reconcile(self):
        return reconcile_retry_ledger(self.path, self.states, self.csv)

    def test_skipped_eligibility_job_is_removed_from_runnable_retries(self):
        self.add()
        self.manifest('skipped', reason='Live eligibility changed: posted_date_excluded')
        self.reconcile()
        row = DeferredJobs(self.path).records[0]
        self.assertEqual(row['status'], 'skipped')
        self.assertIn('posted_date_excluded', row['reason'])
        with self.assertRaisesRegex(ValueError, 'No unapplied'):
            build_retry_batch(self.path, {}, {}, 1)

    def test_any_confirmed_manifest_outweighs_later_failure(self):
        self.add()
        self.manifest('applied')
        self.manifest('failed', date='2026-10-25T13:00:00Z')
        self.reconcile()
        self.assertEqual(DeferredJobs(self.path).records[0]['status'], 'applied')

    def test_confirmed_csv_repairs_ledger_and_clears_stale_submission_hold(self):
        self.ledger.record(dict(job_id='123', status='failed', title='Staff Engineer', company='Example',
            submission_disabled=False, requires_submission_check=True))
        self.history([{'Job ID': '123', 'Date Applied': '2026-10-25 12:00:00', 'Search Run ID': 'confirmed'}])
        self.reconcile()
        row = DeferredJobs(self.path).records[0]
        self.assertEqual(row['status'], 'applied')
        self.assertEqual(row['run_id'], 'confirmed')
        self.assertFalse(row['requires_submission_check'])

    def test_pending_csv_is_not_submission_confirmation(self):
        self.add()
        self.history([{'Job ID': '123', 'Date Applied': 'Pending'}])
        self.reconcile()
        self.assertEqual(DeferredJobs(self.path).records[0]['status'], 'failed')

    def test_uncertain_submit_remains_blocked_despite_later_preparation(self):
        self.add()
        self.manifest('submitting')
        self.manifest('prepared', date='2026-10-25T13:00:00Z')
        self.reconcile()
        row = DeferredJobs(self.path).records[0]
        self.assertEqual(row['status'], 'submission_uncertain')
        self.assertTrue(row['requires_submission_check'])
        with self.assertRaisesRegex(ValueError, 'submission outcome must be checked'):
            build_retry_batch(self.path, {}, {}, 1)

    def test_latest_failure_not_replaced_by_an_older_in_progress_run(self):
        self.add()
        self.manifest('in_progress')
        self.manifest('failed', date='2026-10-25T13:00:00Z')
        self.reconcile()
        self.assertEqual(DeferredJobs(self.path).records[0]['status'], 'failed')

    def test_active_job_does_not_become_runnable_from_reconciliation(self):
        self.ledger.record(dict(job_id='123', status='started', title='Staff Engineer',
                               company='Example', submission_disabled=False))
        self.manifest('in_progress')
        self.reconcile()
        self.assertEqual(DeferredJobs(self.path).records[0]['status'], 'started')

    def test_same_run_failure_preserves_detailed_filler_error(self):
        self.add()
        manifest = self.manifest('failed', reason='Problem in Easy Applying')
        self.ledger.record(dict(job_id='123', status='failed', submission_disabled=False,
                               run_id=manifest.data['run_id'], reason='Required privacy checkbox is unchecked'))
        self.reconcile()
        self.assertEqual(DeferredJobs(self.path).records[0]['reason'], 'Required privacy checkbox is unchecked')

    def test_failed_preparation_preserves_observed_submission_disabled_flag(self):
        self.add()
        manifest = self.manifest('failed')
        manifest.record_job(self.spec, '456', 'applied', 'Later submitted job in a resumed run')
        self.ledger.record(dict(job_id='123', status='failed', submission_disabled=True,
                               run_id=manifest.data['run_id'], reason='Preparation failed'))
        self.reconcile()
        self.assertTrue(DeferredJobs(self.path).records[0]['submission_disabled'])

    def test_checkpoint_sync_retains_submit_boundary_before_confirmation(self):
        self.add()
        manifest = self.manifest('submitting')
        sync_retry_checkpoint(manifest, self.spec, '123')
        self.assertEqual(DeferredJobs(self.path).records[0]['status'], 'submission_uncertain')
        manifest.record_job(self.spec, '123', 'applied', 'Confirmed by LinkedIn')
        sync_retry_checkpoint(manifest, self.spec, '123')
        row = DeferredJobs(self.path).records[0]
        self.assertEqual(row['status'], 'applied')
        self.assertFalse(row['requires_submission_check'])

    def test_prepared_checkpoint_is_submission_disabled_without_global_flag(self):
        self.add()
        manifest = self.manifest('prepared')
        sync_retry_checkpoint(manifest, self.spec, '123')
        row = DeferredJobs(self.path).records[0]
        self.assertEqual(row['status'], 'ready')
        self.assertTrue(row['submission_disabled'])

    def test_explicitly_verified_not_submitted_outcome_releases_hold(self):
        self.add()
        manifest = self.manifest('submitting')
        sync_retry_checkpoint(manifest, self.spec, '123')
        manifest.resolve_submission('query', '123', 'failed')
        self.reconcile()
        row = DeferredJobs(self.path).records[0]
        self.assertEqual(row['status'], 'failed')
        self.assertFalse(row['requires_submission_check'])
        self.assertEqual(row['verified_submission_outcome'], 'not_submitted')

    def test_reconciliation_is_idempotent_and_preserves_original_sources(self):
        self.add()
        manifest = self.manifest('skipped')
        old_manifest = manifest.path.read_bytes()
        self.reconcile()
        ledger = self.path.read_bytes()
        result = self.reconcile()
        self.assertEqual(result['changed'], [])
        self.assertEqual(self.path.read_bytes(), ledger)
        self.assertEqual(manifest.path.read_bytes(), old_manifest)

    def test_corrupt_manifest_does_not_modify_ledger(self):
        self.add()
        self.manifest('applied')
        before = self.path.read_bytes()
        (self.states / 'corrupt.json').write_text('{invalid')
        with self.assertRaises(ValueError):
            self.reconcile()
        self.assertEqual(self.path.read_bytes(), before)

    def test_missing_ledger_does_not_create_one(self):
        self.reconcile()
        self.assertFalse(self.path.exists())


if __name__ == '__main__':
    unittest.main()

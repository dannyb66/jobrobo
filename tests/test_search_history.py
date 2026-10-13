"""Durable checkpoints and lossless CSV history contracts."""

import csv
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from modules.search_history import SEARCH_FIELDS, append_history, file_lock, load_applied_job_ids, search_metadata
from modules.search_planner import SearchSpec
from modules.search_state import SearchManifest, plan_fingerprint


def spec(query_id="manual:staff", quota=1):
    return SearchSpec(
        query_id=query_id, query_text="Find Staff AI Platform Engineer roles. Location: California.",
        source="manual", mode="ai", profile_name="test-ai-platform", profile_version="2",
        filters_snapshot={"intent": {"search_location": "California"}, "gates": {"bad_words": ["US Citizen"]}},
        quota=quota, classic_query="Staff AI Platform Engineer",
    )


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.path = self.directory / "applied.csv"

    def write_csv(self, fields, rows):
        with self.path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def read_csv(self):
        with self.path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            return reader.fieldnames, list(reader)

    def test_new_applied_and_failed_history_have_exact_search_metadata(self):
        current = spec()
        manifest = SearchManifest.create(self.directory / "runs", [current])
        for filename, mode in (("applied.csv", "ai"), ("failed.csv", "classic")):
            with self.subTest(filename=filename):
                manifest.record_mode(current, mode, "AI search unavailable" if mode == "classic" else None)
                metadata = search_metadata(manifest, current)
                append_history(self.directory / filename, ["Job ID", "Reason"], {"Job ID": "123", "Reason": "test outcome", **metadata})
                with (self.directory / filename).open(newline="") as handle:
                    row = next(csv.DictReader(handle))
                self.assertEqual({key: row[key] for key in SEARCH_FIELDS}, metadata)
                self.assertEqual(row["Search Run ID"], manifest.data["run_id"])
                self.assertEqual(row["Search Query ID"], "manual:staff")
                self.assertEqual(row["Search Query"], current.query_text if mode == "ai" else current.classic_query)
                self.assertEqual(row["Search Mode"], mode)
                self.assertEqual(row["Search Profile"], "test-ai-platform@2")
                self.assertEqual(row["Search Source"], "manual")

    def test_no_active_search_writes_empty_metadata(self):
        self.assertEqual(search_metadata(), dict.fromkeys(SEARCH_FIELDS, ""))
        self.assertEqual(search_metadata(None, spec()), dict.fromkeys(SEARCH_FIELDS, ""))

    def test_old_headers_migrate_preserving_every_row_and_column(self):
        old_fields = ["Title", "Job ID", "Date Applied", "Custom Field"]
        old_rows = [
            {"Title": "Senior Engineer, AI", "Job ID": "101", "Date Applied": "2026-10-11", "Custom Field": "café\nsecond line"},
            {"Title": "Backend Engineer", "Job ID": "102", "Date Applied": "Pending", "Custom Field": "original"},
        ]
        self.write_csv(old_fields, old_rows)
        original = self.path.read_bytes()
        append_history(self.path, ["Job ID", "Title", "Date Applied", "New Field"],
                       {"Job ID": "103", "Title": "New Engineer", "Date Applied": "2026-10-12",
                        "New Field": "new", "Search Run ID": "test-run", "Search Query ID": "manual:staff"})
        fields, rows = self.read_csv()
        self.assertEqual(fields[:len(old_fields)], old_fields)
        self.assertEqual(set(fields), {*old_fields, "New Field", *SEARCH_FIELDS})
        for expected, actual in zip(old_rows, rows[:2]):
            self.assertEqual({key: actual[key] for key in old_fields}, expected)
            self.assertEqual({key: actual[key] for key in SEARCH_FIELDS}, dict.fromkeys(SEARCH_FIELDS, ""))
        self.assertEqual(rows[2]["Search Run ID"], "test-run")
        self.assertEqual(self.path.with_name("applied.csv.bak").read_bytes(), original)
        append_history(self.path, ["Job ID"], {"Job ID": "104"})
        self.assertEqual(self.path.with_name("applied.csv.bak").read_bytes(), original)
        self.assertEqual(len(self.read_csv()[1]), 4)

    def test_migration_replace_failure_leaves_original_file_intact(self):
        self.write_csv(["Job ID", "Title"], [{"Job ID": "101", "Title": "Old"}])
        original = self.path.read_bytes()
        with patch("modules.search_history.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                append_history(self.path, ["Job ID", "Title"], {"Job ID": "102", "Title": "New"})
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(sorted(item.name for item in self.directory.iterdir()), ["applied.csv", "applied.csv.bak", "applied.csv.lock"])

    def test_unrecognized_duplicate_or_malformed_history_is_not_modified(self):
        for contents in (
            "Title,Other\nOld,101\n", "Job ID,Job ID\n101,102\n",
            "Job ID,Title\n101,Old,extra\n", "Job ID,Title\n101\n",
        ):
            with self.subTest(contents=contents):
                self.path.write_text(contents)
                original = self.path.read_bytes()
                with self.assertRaises(ValueError):
                    append_history(self.path, ["Job ID", "Title"], {"Job ID": "102", "Title": "New"})
                self.assertEqual(self.path.read_bytes(), original)

    def test_loading_ids_uses_named_header_and_skips_pending_empty_and_invalid_ids(self):
        self.path.write_text("\ufeffTitle,Date Applied,Job ID\nOne,2026-10-11,123\nTwo,Pending,456\nThree,,789\nFour,2026-10-11,not-numeric\nFive,2026-10-12, 987 \n", encoding="utf-8")
        self.assertEqual(load_applied_job_ids(self.path), {"123", "987"})
        self.assertEqual(load_applied_job_ids(self.directory / "missing.csv"), set())

    def test_loading_historical_ids_without_applied_date(self):
        self.write_csv(["Title", "Job ID"], [{"Title": "Old", "Job ID": "101"}])
        self.assertEqual(load_applied_job_ids(self.path), {"101"})

    def test_loading_unrecognized_header_is_rejected(self):
        self.path.write_text("Title,ID\nOld,101\n")
        with self.assertRaises(ValueError):
            load_applied_job_ids(self.path)

    def test_lock_contention_blocks_concurrent_writes_without_changing_history(self):
        self.write_csv(["Job ID", "Title"], [{"Job ID": "101", "Title": "Old"}])
        original = self.path.read_bytes()
        with file_lock(str(self.path) + ".lock"):
            with self.assertRaises(OSError):
                append_history(self.path, ["Job ID", "Title"], {"Job ID": "102", "Title": "New"})
        self.assertEqual(self.path.read_bytes(), original)
        append_history(self.path, ["Job ID", "Title"], {"Job ID": "102", "Title": "New"})
        self.assertEqual([row["Job ID"] for row in self.read_csv()[1]], ["101", "102"])


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)

    def create(self, specs=None, configuration_id="test-configuration"):
        return SearchManifest.create(self.directory, specs or [spec()], configuration_id)

    def test_creation_is_durable_and_contains_profile_and_query_plan(self):
        current = spec()
        manifest = self.create([current])
        stored = json.loads(manifest.path.read_text())
        self.assertEqual(stored, manifest.data)
        self.assertEqual(stored["profile_name"], current.profile_name)
        self.assertEqual(stored["profile_version"], current.profile_version)
        self.assertEqual(stored["status"], "running")
        self.assertIsNone(stored["current_query_id"])
        self.assertTrue(stored["run_id"])
        self.assertTrue(stored["started_at"])
        self.assertTrue(stored["last_updated_at"])
        row = stored["queries"][0]
        self.assertEqual(row["spec"], current.to_dict())
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["applied_count"], 0)
        self.assertEqual(row["processed_job_ids"], [])
        self.assertEqual(row["last_page"], 1)

    def test_recording_modes_retains_executed_query_fallback_and_warnings(self):
        current = spec()
        manifest = self.create([current])
        manifest.begin_query(current)
        manifest.record_mode(current, "ai", warnings=["Sort control unavailable"])
        self.assertEqual(manifest.query(current.query_id)["executed_query"], current.query_text)
        manifest.record_mode(current, "classic", fallback_reason="AI search unavailable")
        row = json.loads(manifest.path.read_text())["queries"][0]
        self.assertEqual(row["search_mode"], "classic")
        self.assertEqual(row["spec"]["mode"], "classic")
        self.assertEqual(current.mode, "classic")
        self.assertEqual(row["fallback_reason"], "AI search unavailable")
        self.assertEqual(row["executed_query"], current.classic_query)
        self.assertEqual(row["warnings"], ["Sort control unavailable"])

    def test_quota_counts_successes_and_collected_links_not_failed_or_skipped_jobs(self):
        current = spec(quota=2)
        manifest = self.create([current])
        manifest.record_job(current, "101", "failed", "Form rejected", page=2)
        manifest.record_job(current, "102", "skipped", "Security clearance", page=3)
        self.assertFalse(manifest.quota_met(current))
        manifest.record_job(current, "103", "applied", page=3)
        manifest.record_job(current, "103", "applied", page=3)
        self.assertFalse(manifest.quota_met(current))
        manifest.record_job(current, "104", "collected", "External application", page=4)
        self.assertTrue(manifest.quota_met(current))
        row = manifest.query(current.query_id)
        self.assertEqual(row["applied_count"], 1)
        self.assertEqual(row["collected_count"], 1)
        self.assertEqual(row["jobs"]["101"]["reason"], "Form rejected")
        self.assertEqual(row["jobs"]["102"]["reason"], "Security clearance")
        self.assertEqual(row["processed_job_ids"], ["101", "102", "103", "104"])
        self.assertEqual(row["last_page"], 4)
        self.assertEqual(row["last_job_id"], "104")

    def test_post_submit_failure_cannot_erase_or_recount_success(self):
        current = spec()
        manifest = self.create([current])
        manifest.record_job(current, "123", "applied")
        manifest.record_job(current, "123", "failed", "CSV write failed")
        row = manifest.query(current.query_id)
        self.assertEqual(row["jobs"]["123"]["status"], "applied")
        self.assertEqual(row["applied_count"], 1)
        self.assertIn("CSV write failed", row["warnings"][0])
        self.assertTrue(manifest.quota_met(current))

    def test_resume_preserves_completed_queries_ids_counts_and_audit_restarts_page_one(self):
        completed, current, pending = spec("manual:completed"), spec("manual:current", quota=2), spec("manual:pending")
        manifest = self.create([completed, current, pending])
        manifest.begin_query(completed)
        manifest.record_job(completed, "100", "applied", page=5)
        manifest.finish_query(completed, "quota_met")
        manifest.begin_query(current)
        manifest.record_mode(current, "classic", "AI UI unavailable", ["sort unavailable"])
        manifest.record_job(current, "101", "applied", page=4)
        manifest.record_job(current, "102", "failed", "Form error", page=4)
        manifest.record_job(current, "103", "skipped", "Description exclusion", page=5)
        manifest.interrupt("KeyboardInterrupt")
        resumed = SearchManifest.find_resume(self.directory, "test-configuration")
        self.assertEqual(resumed.data["run_id"], manifest.data["run_id"])
        self.assertEqual(resumed.data["status"], "running")
        self.assertIsNone(resumed.data["stop_reason"])
        self.assertEqual([lane.query_id for lane in resumed.queries()], [current.query_id, pending.query_id])
        self.assertEqual(resumed.processed_ids(), {"100", "101", "102", "103"})
        current = resumed.queries()[0]
        resumed.begin_query(current)
        row = resumed.query(current.query_id)
        self.assertEqual(row["last_page"], 1)
        self.assertEqual(row["applied_count"], 1)
        self.assertEqual(row["fallback_reason"], "AI UI unavailable")
        self.assertEqual(row["jobs"]["102"]["reason"], "Form error")
        self.assertEqual(row["jobs"]["103"]["reason"], "Description exclusion")
        self.assertFalse(resumed.quota_met(current))
        resumed.record_job(current, "104", "applied", page=2)
        self.assertTrue(resumed.quota_met(current))

    def test_processed_ids_cover_all_queries_and_duplicate_cross_query_applications_do_not_count(self):
        first, second = spec("manual:first"), spec("manual:second")
        manifest = self.create([first, second])
        manifest.record_job(first, "123", "applied")
        self.assertIn("123", manifest.processed_ids())
        manifest.record_job(second, "123", "applied")
        self.assertEqual(sum(row["applied_count"] for row in manifest.data["queries"]), 1)
        self.assertFalse(manifest.quota_met(second))

    def test_unsubmitted_in_progress_job_can_be_retried_but_submitting_is_conservative(self):
        current = spec()
        manifest = self.create([current])
        manifest.begin_query(current)
        manifest.record_job(current, "123", "in_progress")
        manifest.record_job(current, "456", "submitting")
        manifest.interrupt("process terminated")
        resumed = SearchManifest.find_resume(self.directory, "test-configuration")
        self.assertNotIn("123", resumed.processed_ids())
        self.assertIn("456", resumed.processed_ids())
        self.assertFalse(resumed.quota_met(current))

    def test_complete_runs_are_not_resumed_and_changed_configuration_does_not_match(self):
        current = spec()
        manifest = self.create([current])
        self.assertIsNone(SearchManifest.find_resume(self.directory, "other-configuration"))
        manifest.finish_query(current, "results_exhausted")
        manifest.finish()
        self.assertEqual(manifest.data["status"], "complete")
        self.assertEqual(manifest.data["stop_reason"], "all_queries_complete")
        self.assertIsNone(manifest.data["current_query_id"])
        self.assertIsNone(SearchManifest.find_resume(self.directory, "test-configuration"))

    def test_finish_with_incomplete_queries_records_interruption(self):
        manifest = self.create()
        manifest.finish()
        self.assertEqual(manifest.data["status"], "interrupted")

    def test_corrupt_manifest_is_reported_and_preserved(self):
        path = self.directory / "corrupt.json"
        path.write_text("{not json}")
        with self.assertRaises(json.JSONDecodeError):
            SearchManifest.find_resume(self.directory, "test-configuration")
        self.assertEqual(path.read_text(), "{not json}")

    def test_atomic_checkpoint_failure_preserves_previous_manifest(self):
        manifest = self.create()
        previous = manifest.path.read_bytes()
        manifest.data["stop_reason"] = "changed"
        with patch("modules.search_state.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                manifest.save()
        self.assertEqual(manifest.path.read_bytes(), previous)
        self.assertEqual(list(self.directory.glob(".checkpoint-*")), [])

    def test_fingerprint_includes_queries_quotas_and_current_filter_values(self):
        original = spec()
        copied = deepcopy(original)
        self.assertEqual(plan_fingerprint([original]), plan_fingerprint([copied]))
        for field, value in (("query_text", "Find Backend Engineer roles."), ("quota", 2),
                             ("filters_snapshot", {"intent": {"search_location": "New York"}})):
            with self.subTest(field=field):
                changed = deepcopy(original)
                setattr(changed, field, value)
                self.assertNotEqual(plan_fingerprint([original]), plan_fingerprint([changed]))

    def test_applied_ids_protect_fresh_runs_even_after_csv_logging_failure(self):
        first, second = spec("manual:first"), spec("manual:second")
        old_run = self.create([first], configuration_id="old-config")
        old_run.record_job(first, "100", "applied")
        old_run.record_job(first, "101", "submitting")
        old_run.record_job(first, "102", "collected", "External link")
        old_run.record_job(first, "103", "failed", "Form rejected")
        old_run.record_job(first, "104", "skipped", "Description gate")
        old_run.record_job(first, "105", "in_progress")
        old_run.finish_query(first, "results_exhausted")
        old_run.finish()
        new_run = self.create([second], configuration_id="new-config")
        new_run.record_job(second, "200", "applied")
        self.assertEqual(SearchManifest.applied_ids(self.directory), {"100", "101", "200"})
        self.assertEqual(SearchManifest.applied_ids(self.directory / "missing"), set())
        self.assertIsNone(SearchManifest.find_resume(self.directory, "old-config"))

    def test_invalid_job_status_cannot_modify_checkpoint(self):
        current = spec()
        manifest = self.create([current])
        previous = manifest.path.read_bytes()
        for status in (None, "unknown", "success", ""):
            with self.subTest(status=status), self.assertRaises(ValueError):
                manifest.record_job(current, "123", status)
        self.assertEqual(manifest.path.read_bytes(), previous)
        self.assertEqual(manifest.processed_ids(), set())
        self.assertFalse(manifest.quota_met(current))

    def test_history_scan_does_not_silently_discard_corrupt_application_checkpoint(self):
        (self.directory / "corrupt.json").write_text("{not json}")
        with self.assertRaises(json.JSONDecodeError):
            SearchManifest.applied_ids(self.directory)


if __name__ == "__main__":
    unittest.main()

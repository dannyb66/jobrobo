"""Ranking changes review order, never source truth or inventory membership."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import random
import tempfile
import unittest
from unittest.mock import Mock
import zipfile

from modules.job_pipeline.models import StageResult, write_artifact
from modules.job_pipeline.ranking import (as_of_datetime, load_resume_profile, posting_recency,
                                         profile_from_text, rank_roles, resume_affinity)
from modules.job_pipeline.service import rank_careers, verify_careers
from modules.job_pipeline.store import PipelineStore


NOW = datetime(2026, 10, 15, 12, tzinfo=timezone.utc)


def role(identifier="role:example", age=2, **changes):
    return dict({"id": identifier, "company_id": "company:example", "company": {
        "id": "company:example", "name": "Example", "domain": "example.com"},
        "title": "Software Engineer", "description": "Build Python services with Kubernetes.",
        "status": "open", "eligible": True, "verification_eligible": True,
        "application_eligible": False, "application_exclusion_reasons": ["location_excluded"],
        "verified_at": "2026-10-14T13:00:00+00:00", "verification_run_id": "original-verification",
        "published_at": (NOW - timedelta(days=age)).isoformat(), "priority_tier": 2}, **changes)


class RecencyTests(unittest.TestCase):
    def test_exact_boundaries_and_just_after(self):
        for age, expected in ((0, "past_24_hours"), (1, "past_24_hours"),
                              (1.000001, "past_7_days"), (7, "past_7_days"),
                              (7.000001, "past_30_days"), (30, "past_30_days"), (30.000001, "older")):
            with self.subTest(age=age):
                result = posting_recency((NOW - timedelta(days=age)).isoformat(), NOW)
                self.assertEqual(result["bucket"], expected)

    def test_timezones_are_normalized_before_age_calculation(self):
        self.assertEqual(posting_recency("2026-10-14T05:00:00-07:00", NOW)["age_days"], 1)
        self.assertEqual(posting_recency("2026-10-15T19:00:00+07:00", NOW)["age_days"], 0)

    def test_future_invalid_missing_and_naive_dates_are_explicitly_unknown(self):
        for value, reason in ((None, "missing_posting_date"), ("", "missing_posting_date"),
                              ("next Tuesday", "invalid_posting_date"), (True, "invalid_posting_date"),
                              ("2026-10-14", "posting_date_has_no_timezone"),
                              ("2026-10-16T00:00:00Z", "future_posting_date")):
            with self.subTest(value=value):
                result = posting_recency(value, NOW)
                self.assertEqual(result["bucket"], "unknown")
                self.assertEqual(result["reason"], reason)
                self.assertIsNone(result["age_days"])

    def test_ranking_as_of_requires_a_timezone(self):
        for value in ("2026-10-15", "nope", datetime(2026, 10, 15)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                as_of_datetime(value)


class AffinityTests(unittest.TestCase):
    def test_java_and_rag_never_match_javascript_and_storage(self):
        profile = profile_from_text("Software developer. JavaScript and storage systems.")
        result = resume_affinity(role(description="Java and RAG required"), profile)
        self.assertEqual(result["matched_terms"], [])
        self.assertEqual(result["missing_terms"], ["Java", "RAG"])
        self.assertEqual(result["score"], 20)
        self.assertFalse(result["is_ats_score"])
        self.assertFalse(result["qualification_verified"])

    def test_aliases_and_term_boundaries_are_bounded_and_count_once(self):
        profile = profile_from_text("Machine-learning software engineer. Amazon Web Services, k8s, Python, LLMs.")
        result = resume_affinity(role(title="Machine Learning Engineer", description="AWS AWS Kubernetes LLM Python"), profile)
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["matched_terms"], ["AWS", "Kubernetes", "LLM", "Machine learning", "Python"])
        self.assertEqual(result["job_terms_weight"], 6)

    def test_go_verb_is_not_a_programming_language_match(self):
        self.assertNotIn("Go", profile_from_text("We go to market quickly.").skills)
        self.assertIn("Go", profile_from_text("Languages: Go, Python").skills)
        self.assertIn("Go", profile_from_text("Go programming and Golang services").skills)

    def test_missing_resume_jd_or_vocabulary_is_unknown_instead_of_zero(self):
        profile = profile_from_text("Python software engineer")
        for candidate, supplied, reason in ((role(), None, "resume_not_provided"),
                                            (role(description=""), profile, "missing_job_description"),
                                            (role(description="Build excellent tools."), profile, "no_recognized_job_terms")):
            with self.subTest(reason=reason):
                result = resume_affinity(candidate, supplied)
                self.assertEqual(result["band"], "unknown")
                self.assertIsNone(result["score"])
                self.assertEqual(result["reason"], reason)

    def test_resume_text_name_and_path_are_not_stored_in_metadata(self):
        profile = profile_from_text("Private Person, private@example.com. Python software engineer.")
        encoded = json.dumps(rank_roles([role()], profile, as_of=NOW))
        self.assertNotIn("Private Person", encoded)
        self.assertNotIn("private@example.com", encoded)
        self.assertIn(profile.sha256, encoded)

    def test_docx_reader_preserves_runs_and_hashes_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resume.docx"
            with zipfile.ZipFile(path, "w") as document:
                document.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Java</w:t></w:r><w:r><w:t>Script, Python</w:t></w:r></w:p></w:body></w:document>')
            profile = load_resume_profile(path)
            self.assertEqual(profile.skills, {"JavaScript", "Python"})
            self.assertEqual(len(profile.sha256), 64)

    def test_unreadable_or_empty_resume_fails_instead_of_inventing_affinity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "resume.txt"
            path.write_text("")
            with self.assertRaises(ValueError):
                load_resume_profile(path)
            path = Path(directory) / "resume.docx"
            path.write_text("not a zip")
            with self.assertRaises(ValueError):
                load_resume_profile(path)


class RankingContractTests(unittest.TestCase):
    def test_retains_every_record_and_preserves_all_original_source_decisions(self):
        records = [role(str(index), index, status="closed" if index == 8 else "open") for index in range(90)]
        before = deepcopy(records)
        ranked = rank_roles(records, profile_from_text("Python Kubernetes software engineer"), as_of=NOW)
        self.assertEqual(records, before)
        self.assertEqual(len(ranked), 90)
        self.assertEqual({row["id"] for row in ranked}, {row["id"] for row in before})
        originals = {row["id"]: row for row in before}
        for row in ranked:
            source = {key: value for key, value in row.items() if key != "review_priority"}
            self.assertEqual(source, originals[row["id"]])
        self.assertEqual(next(row for row in ranked if row["id"] == "8")["review_priority"]["tier"], 4)

    def test_tier_matrix_including_unknown_and_ineligible(self):
        profile = profile_from_text("Python Kubernetes software engineer")
        cases = [(role(age=2), 1), (role(age=20), 2), (role(age=40), 2),
                 (role(age=2, description="Rust Scala CUDA"), 2),
                 (role(age=20, description="Rust Scala CUDA"), 3),
                 (role(published_at=None), 3), (role(verification_eligible=False), 4)]
        for candidate, expected in cases:
            with self.subTest(candidate=candidate):
                self.assertEqual(rank_roles([candidate], profile, as_of=NOW)[0]["review_priority"]["tier"], expected)
        self.assertEqual(rank_roles([role()], as_of=NOW)[0]["review_priority"]["tier"], 2)

    def test_stable_ties_and_input_permutations(self):
        records = [role("z"), role("a"), role("b", title="AI Engineer")]
        expected = [row["id"] for row in rank_roles(records, as_of=NOW)]
        for seed in range(12):
            random.Random(seed).shuffle(records)
            self.assertEqual([row["id"] for row in rank_roles(records, as_of=NOW)], expected)

    def test_affinity_precedes_exact_age_within_the_same_recency_bucket(self):
        profile = profile_from_text("Python Kubernetes software engineer")
        ranked = rank_roles([role("new-low", age=1.2, description="Rust Scala"), role("old-high", age=6)], profile, as_of=NOW)
        self.assertEqual([row["id"] for row in ranked], ["old-high", "new-low"])


class OfflineAndCacheTests(unittest.TestCase):
    def test_offline_artifact_ranking_does_not_create_or_import_database(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            db = Path(directory) / "never-created.sqlite3"
            original = StageResult.create("verified_roles", "original", "verified-run", [role()])
            write_artifact(original, source)
            before = source.read_bytes()
            result = rank_careers([source], "ranked", db, as_of=NOW)
            self.assertFalse(db.exists())
            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(result.records[0]["verified_at"], original.records[0]["verified_at"])
            self.assertEqual(result.records[0]["verification_run_id"], "original-verification")
            self.assertEqual(result.delta, [])

    def test_named_set_ranking_does_not_persist_derived_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "pipeline.sqlite3"
            with PipelineStore(db) as store:
                store.upsert_many("verified_roles", "saved", [role()], "save-run")
                before = store.load_set("verified_roles", "saved")
            result = rank_careers(["saved"], "ranked", db, as_of=NOW)
            self.assertIn("review_priority", result.records[0])
            with PipelineStore(db) as store:
                self.assertEqual(store.load_set("verified_roles", "saved"), before)

    def test_fresh_cached_verification_ranks_without_observing_again(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "pipeline.sqlite3"
            now = datetime.now(timezone.utc).isoformat()
            saved = role(verified_at=now, published_at=now)
            with PipelineStore(db) as store:
                store.upsert_many("verified_roles", "saved", [saved], "save-run")
                store.save_checkpoint("verify:company:example", "saved", {"complete": True, "verified_at": now})
            adapter = Mock()
            result = verify_careers(set_name="saved", db_path=db, verify=adapter, render_enabled=False, search_config={})
            adapter.assert_not_called()
            self.assertEqual(result.records[0]["verified_at"], now)
            self.assertEqual(result.records[0]["verification_run_id"], "original-verification")
            self.assertIn("review_priority", result.records[0])
            with PipelineStore(db) as store:
                self.assertNotIn("review_priority", store.load_set("verified_roles", "saved")[0])

    def test_conflicting_duplicate_role_ids_are_not_silently_overwritten(self):
        one = StageResult.create("verified_roles", "one", "one", [role()])
        two = StageResult.create("verified_roles", "two", "two", [role(title="Other Engineer")])
        with self.assertRaisesRegex(ValueError, "Conflicting saved records"):
            rank_careers([one, two], "ranked", as_of=NOW)

    def test_old_open_rank_metadata_cannot_promote_a_saved_closure(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "pipeline.sqlite3"
            opened = rank_roles([role()], profile_from_text("Python Kubernetes software engineer"), as_of=NOW)[0]
            closed = dict(opened, status="closed", verified_at=NOW.isoformat())
            with PipelineStore(db) as store:
                store.upsert_many("verified_roles", "saved", [closed], "closure-run")
                store.upsert_many("verified_roles", "saved", [opened], "stale-import")
            result = rank_careers(["saved"], "ranked", db, as_of=NOW)
            self.assertEqual(result.records[0]["status"], "closed")
            self.assertFalse(result.records[0]["verification_eligible"])
            self.assertEqual(result.records[0]["review_priority"]["tier"], 4)


if __name__ == "__main__":
    unittest.main()

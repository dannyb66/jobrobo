"""Admission validation uses isolated synthetic stage artifacts and SQLite state."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest

from modules.job_pipeline.models import StageResult, write_artifact
from modules.job_pipeline.store import PipelineStore
from scripts.validate_job_pipeline_artifacts import validate


class ArtifactValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = self.root / "pipeline.sqlite3"
        self.company_file = self.root / "companies.json"
        self.role_file = self.root / "roles.json"
        now = datetime.now(timezone.utc).isoformat()
        company = {"id": "example", "name": "Example", "website": "https://example.test", "domain": "example.test",
                   "sources": [{"name": "official_manual_seed", "url": "https://example.test/careers", "observed_at": now}]}
        with PipelineStore(self.db) as store:
            company_run = store.begin_run("companies", "companies")
            companies = store.upsert_many("companies", "companies", [company], company_run)
            store.finish_run(company_run, "complete")
            self.company = companies[0]
            role_run = store.begin_run("verified_roles", "roles", ["companies:companies"])
            role = {"id": "role-example", "company": self.company, "company_id": self.company["id"],
                    "title": "Staff Platform Engineer", "description": "Build Python backend infrastructure systems",
                    "career_url": "https://jobs.lever.co/example/11111111-1111-4111-8111-111111111111", "eligible": True,
                    "status": "open", "workplace_type": "Remote", "employment_type": "Full-time", "locations": ["United States"],
                    "published_at": now, "verified_at": now, "verification_run_id": role_run, "exclusion_reasons": [],
                    "sources": [{"name": "lever", "kind": "career_verification", "url": "https://api.lever.co/v0/postings/example", "observed_at": now}]}
            roles = store.upsert_many("verified_roles", "roles", [role], role_run)
            store.finish_run(role_run, "complete")
        write_artifact(StageResult.create("companies", "companies", company_run, companies, delta=companies), self.company_file)
        write_artifact(StageResult.create("verified_roles", "roles", role_run, roles, delta=roles, input_set_ids=["companies:companies"]), self.role_file)

    def check(self):
        return validate(self.company_file, self.role_file, self.db, search_config={}, freshness_days=7)

    def mutate_role(self, **updates):
        payload = json.loads(self.role_file.read_text())
        payload["records"][0].update(updates)
        self.role_file.write_text(json.dumps(payload))

    def test_valid_isolated_artifacts_are_review_candidates_without_starting_apply(self):
        report = self.check()
        self.assertTrue(report["all_checks_passed"], report["problems"])
        self.assertEqual(report["eligible_open_fresh_role_count"], 1)
        self.assertEqual(report["search_admission"], "review_required")
        self.assertEqual(report["application_admission"], "held_pending_explicit_selected_target_review")

    def test_stale_verification_is_held(self):
        self.mutate_role(verified_at=(datetime.now(timezone.utc) - timedelta(days=8)).isoformat())
        report = self.check()
        self.assertFalse(report["all_checks_passed"])
        self.assertEqual(report["eligible_open_fresh_role_count"], 0)

    def test_eligibility_claim_is_recomputed_from_canonical_filters(self):
        self.mutate_role(title="Customer Success Associate")
        report = self.check()
        self.assertFalse(report["all_checks_passed"])
        self.assertTrue(any(item["check"].startswith("canonical_eligibility:") for item in report["problems"]))

    def test_missing_careers_provenance_is_held(self):
        self.mutate_role(sources=[])
        self.assertFalse(self.check()["all_checks_passed"])

    def test_existing_application_run_fails_pre_application_clean_state_check(self):
        with PipelineStore(self.db) as store:
            run = store.begin_run("applications", "applications")
            store.finish_run(run, "complete")
        self.assertFalse(self.check()["all_checks_passed"])


if __name__ == "__main__":
    unittest.main()

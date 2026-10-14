"""Persistence and orchestration contracts using only temporary SQLite stores."""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from modules.job_pipeline.models import LinkedInRunRequest, StageResult, read_artifact, write_artifact
from modules.job_pipeline.service import discover_companies, load_inputs, verify_careers
from modules.job_pipeline.store import PipelineStore, canonical_domain


def company(ident="company:example", domain="example.com"):
    return {"id": ident, "name": "Example", "domain": domain, "website": "https://" + domain,
            "careers_url": "https://" + domain + "/careers", "aliases": [],
            "sources": [{"name": "yc", "url": "https://www.ycombinator.com/companies/example"}],
            "employee_count": None, "funding_stage": None}


def role(ident="role:staff", employer=None, status="open", verified_at="2026-10-13T10:00:00+00:00"):
    employer = employer or company()
    return {"id": ident, "company_id": employer["id"], "company": employer,
            "title": "Staff AI Engineer", "description": "Build AI infrastructure",
            "career_url": "https://example.com/careers/staff-ai", "locations": ["California"],
            "workplace_type": "Remote", "employment_type": "Full-time", "eligible": status == "open",
            "exclusion_reasons": [], "status": status, "verified_at": verified_at,
            "priority_tier": 1, "sources": []}


def artifact(stage="companies", records=None, set_name="startup", run_id="import-run", created_at="2026-10-12T10:00:00+00:00"):
    return StageResult(stage, set_name, run_id, created_at, [], records if records is not None else [company()], [], []).to_dict()


class ModelsTests(unittest.TestCase):
    def test_versioned_artifact_roundtrips_and_supports_mapping_access(self):
        result = StageResult.from_dict(artifact())
        self.assertEqual(result.get("stage"), "companies")
        self.assertEqual(dict(result), result.to_dict())
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "companies.json"
            write_artifact(result, path)
            self.assertEqual(read_artifact(path).to_dict(), result.to_dict())

    def test_bad_versions_shapes_and_wrong_stages_fail(self):
        for field, value in (("schema_version", 2), ("schema_version", True), ("records", [1]),
                             ("delta", {}), ("errors", "failed"), ("created_at", "yesterday"),
                             ("stage", "unknown"), ("set_name", ""), ("input_set_ids", [123])):
            with self.subTest(field=field), self.assertRaises(ValueError):
                StageResult.from_dict({**artifact(), field: value})
        with self.assertRaises(ValueError):
            StageResult.from_dict(artifact(), "linkedin_jobs")
        with self.assertRaises(ValueError):
            StageResult.from_dict({**artifact(), "extra": True})

    def test_request_modes_limits_and_inputs_are_validated(self):
        for mode in ("search", "apply", "search-and-apply"):
            request = LinkedInRunRequest(mode, [artifact("verified_roles", [role()])], "roles")
            self.assertEqual(request.db_path, "data/job_pipeline/pipeline.sqlite3")
            self.assertEqual(request.limit, 25)
        for kwargs in ({"mode": "run"}, {"limit": 0}, {"limit": True}, {"input_sets": [{}]}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                LinkedInRunRequest(**{"mode": "search", "input_sets": [], "set_name": "jobs", **kwargs})

    def test_export_replace_failure_preserves_previous_artifact(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "export.json"
            path.write_text("old export")
            with patch("os.replace", side_effect=OSError("disk full")), self.assertRaises(OSError):
                write_artifact(artifact(), path)
            self.assertEqual(path.read_text(), "old export")
            self.assertEqual(list(path.parent.glob(".pipeline-export-*")), [])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "pipeline.sqlite3"
        self.store = PipelineStore(self.path)
        self.addCleanup(self.store.close)

    def test_cumulative_entities_sets_and_observations_survive_reopening(self):
        run = self.store.begin_run("companies", "startups", [], {"sources": ["yc"]})
        first = self.store.upsert_many("companies", "startups", [company()], run)
        self.assertEqual(len(first), 1)
        self.assertEqual(self.store.upsert_many("companies", "startups", [company()], run), [])
        updated = {**company(), "employee_count": 75, "sources": [{"name": "greylock", "url": "https://greylock.com/portfolio/"}]}
        self.assertEqual(len(self.store.upsert_many("companies", "other", [updated], run)), 1)
        self.assertEqual(self.store.load_set("companies", "startups")[0]["employee_count"], 75)
        self.assertEqual(len(self.store.load_set("companies", "startups")[0]["sources"]), 2)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM observations").fetchone()[0], 2)
        self.store.finish_run(run, "partial", [{"code": "restricted"}])
        with PipelineStore(self.path) as reopened:
            self.assertEqual(reopened.load_set("companies", "other"), self.store.load_set("companies", "startups"))
            self.assertEqual(reopened.get_run(run)["status"], "partial")
            self.assertEqual(reopened.get_run(run)["configuration"], {"sources": ["yc"]})

    def test_importing_same_artifact_is_idempotent_including_observations(self):
        payload = artifact()
        self.store.import_artifact(payload, "companies")
        self.store.import_artifact(payload, "companies")
        self.assertEqual(len(self.store.load_set("companies", "startup")), 1)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM observations").fetchone()[0], 1)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM runs").fetchone()[0], 1)

    def test_old_import_cannot_revive_closed_role_or_reverse_eligibility(self):
        closed = role(status="closed")
        self.store.upsert_many("verified_roles", "roles", [closed], "new-run")
        old = role(status="open", verified_at="2026-10-01T10:00:00+00:00")
        imported = self.store.import_artifact(artifact("verified_roles", [old], "roles", created_at="2026-10-01T10:00:00+00:00"))
        self.assertEqual(imported.records[0]["status"], "closed")
        saved = self.store.load_set("verified_roles", "roles")[0]
        self.assertEqual(saved["status"], "closed")
        self.assertFalse(saved["eligible"])
        self.assertEqual(saved["verified_at"], closed["verified_at"])

    def test_same_timestamp_import_cannot_reopen_without_newer_evidence(self):
        closed = role(status="closed")
        self.store.upsert_many("verified_roles", "roles", [closed], "closed-run")
        imported = load_inputs(self.store, [artifact("verified_roles", [role()], "roles")], "verified_roles")
        self.assertEqual(imported[0].records[0]["status"], "closed")
        self.assertFalse(imported[0].records[0]["eligible"])

    def test_old_artifact_timestamp_protects_records_without_verification_timestamp(self):
        closed = role(status="closed")
        del closed["verified_at"]
        self.store.upsert_many("verified_roles", "roles", [closed], "new-run", "2026-10-13T10:00:00+00:00")
        old = {**closed, "status": "open", "eligible": True}
        self.store.import_artifact(artifact("verified_roles", [old], "roles", created_at="2026-10-01T10:00:00+00:00"))
        self.assertEqual(self.store.load_set("verified_roles", "roles")[0]["status"], "closed")

    def test_unknown_role_evidence_does_not_erase_closed_status(self):
        self.store.upsert_many("verified_roles", "roles", [role(status="closed")], "new-run")
        unknown = role(status="unknown", verified_at="2026-10-14T10:00:00+00:00")
        self.store.upsert_many("verified_roles", "roles", [unknown], "unknown-run")
        self.assertEqual(self.store.load_set("verified_roles", "roles")[0]["status"], "closed")

    def test_domain_alias_merge_preserves_company_sets_role_and_job_refs(self):
        old, renamed = company("old", "old.example.com"), company("renamed", "new.example.com")
        self.store.upsert_many("companies", "old-set", [old], "old-run")
        self.store.upsert_many("companies", "new-set", [renamed], "new-run")
        linked = role(employer=renamed)
        self.store.upsert_many("verified_roles", "roles", [linked], "role-run")
        self.store.upsert_many("linkedin_jobs", "jobs", [{"id": "linkedin:123", "job_id": "123", "company_id": renamed["id"]}], "job-run")
        merge = {**old, "aliases": ["www.old.example.com", "https://new.example.com"]}
        self.store.upsert_many("companies", "old-set", [merge], "merge-run")
        self.assertEqual(self.store.load_set("companies", "new-set")[0]["id"], "old")
        self.assertEqual(self.store.load_set("verified_roles", "roles")[0]["company_id"], "old")
        self.assertEqual(self.store.load_set("verified_roles", "roles")[0]["company"]["id"], "old")
        self.assertEqual(self.store.load_set("linkedin_jobs", "jobs")[0]["company_id"], "old")
        self.store.upsert_many("verified_roles", "roles", [linked], "reimport")
        self.assertEqual(len(self.store.load_set("verified_roles", "roles")), 1)

    def test_colliding_roles_merge_when_company_aliases_join(self):
        first, second = company("first", "first.example.com"), company("second", "second.example.com")
        self.store.upsert_many("verified_roles", "first-roles", [role("one", first)], "one")
        self.store.upsert_many("verified_roles", "second-roles", [role("two", second)], "two")
        self.store.upsert_many("linkedin_jobs", "jobs", [{"id": "linkedin:123", "role_id": "two", "role_ids": ["one", "two"]}], "jobs")
        self.store.upsert_many("companies", "companies", [{**first, "aliases": ["second.example.com"]}], "join")
        self.assertEqual(self.store.load_set("verified_roles", "first-roles")[0]["id"], self.store.load_set("verified_roles", "second-roles")[0]["id"])
        winner = self.store.load_set("verified_roles", "first-roles")[0]["id"]
        self.assertEqual(self.store.load_set("linkedin_jobs", "jobs")[0]["role_id"], winner)
        self.assertEqual(self.store.load_set("linkedin_jobs", "jobs")[0]["role_ids"], [winner])

    def test_application_success_is_preserved_with_later_failed_attempt_in_observations(self):
        applied = {"id": "application:123", "job_id": "123", "status": "applied"}
        self.store.upsert_many("applications", "applications", [applied], "applied-run")
        self.store.upsert_many("applications", "applications", [{**applied, "status": "failed", "reason": "Later CSV failure"}], "failed-run")
        self.assertEqual(self.store.load_set("applications", "applications")[0]["status"], "applied")
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM observations WHERE stage='applications'").fetchone()[0], 2)

    def test_uncertain_submission_survives_failed_or_skipped_import_without_verified_resolution(self):
        pending = {"id": "application:123", "job_id": "123", "status": "submitting"}
        self.store.upsert_many("applications", "applications", [pending], "submitting-run")
        for status in ("failed", "skipped"):
            self.store.upsert_many("applications", "applications", [{**pending, "status": status}], status + "-run")
            self.assertEqual(self.store.resolve_record("applications", pending["id"])["status"], "submitting")
        resolved = {**pending, "status": "failed", "submission_resolution": {"verified": True, "reason": "User confirmed application was not submitted"}}
        self.store.upsert_many("applications", "applications", [resolved], "resolution-run")
        self.assertEqual(self.store.resolve_record("applications", pending["id"])["status"], "failed")

    def test_import_canonicalizes_selected_ids_without_adding_other_saved_members(self):
        first = {"id": "123", "job_id": "123", "title": "Staff AI Engineer"}
        second = {"id": "456", "job_id": "456", "title": "Principal Backend Engineer"}
        self.store.import_artifact(artifact("linkedin_jobs", [first, second], "jobs"))
        selected = load_inputs(self.store, [artifact("linkedin_jobs", [first], "jobs")], "linkedin_jobs")
        self.assertEqual([record["job_id"] for record in selected[0].records], ["123"])
        self.assertEqual(len(self.store.load_set("linkedin_jobs", "jobs")), 2)
        named = load_inputs(self.store, ["jobs"], "linkedin_jobs")
        self.assertEqual({record["job_id"] for record in named[0].records}, {"123", "456"})

    def test_partial_imported_role_ids_remain_distinct_until_identity_is_known(self):
        first = artifact("verified_roles", [{"id": "role-one"}], "one", "import-one")
        second = artifact("verified_roles", [{"id": "role-two"}], "two", "import-two")
        imported = load_inputs(self.store, [first, second], "verified_roles")
        self.assertEqual([record["id"] for value in imported for record in value.records], ["role-one", "role-two"])
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM entities WHERE stage='verified_roles'").fetchone()[0], 2)

    def test_application_lookup_is_global_across_sets_and_imported_alias_ids(self):
        applied = {"id": "application:original", "job_id": "123", "status": "applied"}
        self.store.import_artifact(artifact("applications", [applied], "first", "applied-run"))
        alias = {"id": "application:imported", "linkedin_id": "123", "status": "failed"}
        self.store.import_artifact(artifact("applications", [alias], "second", "failed-run"))
        self.assertEqual(self.store.application_for_job("123")["status"], "applied")
        self.assertEqual(self.store.load_set("applications", "first")[0]["id"], self.store.load_set("applications", "second")[0]["id"])
        self.assertEqual(self.store.resolve_record("applications", alias["id"])["id"], applied["id"])
        self.assertIsNone(self.store.application_for_job("456"))

    def test_application_lookup_accepts_minimal_numeric_and_linkedin_ids(self):
        self.store.upsert_many("applications", "one", [{"id": "linkedin:123", "status": "submitting"}], "one")
        self.store.upsert_many("applications", "two", [{"id": "456", "status": "applied"}], "two")
        self.assertEqual(self.store.application_for_job(123)["status"], "submitting")
        self.assertEqual(self.store.application_for_job("456")["status"], "applied")

    def test_new_set_membership_appears_in_delta_even_for_unchanged_global_entity(self):
        self.store.upsert_many("companies", "old", [company()], "old-run")
        added = self.store.upsert_many("companies", "new", [company()], "new-run")
        self.assertEqual([record["id"] for record in added], [company()["id"]])
        self.assertEqual(self.store.upsert_many("companies", "new", [company()], "repeat-run"), [])

    def test_observed_dictionary_aliases_are_preserved_and_deduplicated(self):
        alias = {"name": "Example AI", "domain": "old.example.com", "source": "company_website"}
        employer = {**company(), "aliases": [alias, deepcopy(alias)]}
        self.store.upsert_many("companies", "companies", [employer], "companies-run")
        self.assertEqual(self.store.load_set("companies", "companies")[0]["aliases"].count(alias), 1)
        imported = self.store.import_artifact(artifact("verified_roles", [role(employer=employer)], "roles"))
        self.assertEqual(imported.records[0]["company"]["aliases"].count(alias), 1)
        self.assertIn("old.example.com", imported.records[0]["company"]["aliases"])
        self.store.upsert_many("companies", "old-alias", [company("old-id", "old.example.com")], "old-run")
        self.assertEqual(self.store.load_set("companies", "old-alias")[0]["id"], employer["id"])

    def test_newer_eligibility_evidence_clears_previous_exclusion_reasons(self):
        blocked = {**role(verified_at="2026-10-10T10:00:00+00:00"), "eligible": False, "exclusion_reasons": ["description_exclusion:US Citizen"], "unverified_preferences": ["old"]}
        self.store.upsert_many("verified_roles", "roles", [blocked], "blocked-run")
        refreshed = {**role(verified_at="2026-10-12T10:00:00+00:00"), "eligible": True, "exclusion_reasons": [], "unverified_preferences": []}
        self.store.upsert_many("verified_roles", "roles", [refreshed], "refreshed-run")
        current = self.store.load_set("verified_roles", "roles")[0]
        self.assertTrue(current["eligible"])
        self.assertEqual(current["exclusion_reasons"], [])
        self.assertEqual(current["unverified_preferences"], [])

    def test_old_alias_bridge_preserves_newest_company_and_role_chronology(self):
        old_company = {**company("company:old", "old.example.com"), "employee_count": 20}
        new_company = {**company("company:new", "new.example.com"), "employee_count": 100}
        self.store.upsert_many("companies", "old", [old_company], "old-run", "2026-10-10T10:00:00+00:00")
        self.store.upsert_many("companies", "new", [new_company], "new-run", "2026-10-12T10:00:00+00:00")
        self.store.upsert_many("verified_roles", "old-roles", [role("old-role", old_company, verified_at="2026-10-10T10:00:00+00:00")], "old-role-run")
        self.store.upsert_many("verified_roles", "new-roles", [role("new-role", new_company, status="closed", verified_at="2026-10-12T10:00:00+00:00")], "new-role-run")
        bridge = {**old_company, "aliases": [new_company["domain"]]}
        self.store.upsert_many("companies", "bridge", [bridge], "bridge-run", "2026-10-09T10:00:00+00:00")
        self.store.upsert_many("companies", "middle", [{**old_company, "employee_count": 35}], "middle-run", "2026-10-11T10:00:00+00:00")
        self.store.upsert_many("verified_roles", "old-roles", [role("old-role", old_company, verified_at="2026-10-11T10:00:00+00:00")], "middle-role-run")
        self.assertEqual(self.store.load_set("companies", "old")[0]["employee_count"], 100)
        self.assertEqual(self.store.load_set("verified_roles", "old-roles")[0]["status"], "closed")

    def test_role_alias_merge_rewrites_career_job_ids_and_embedded_parents(self):
        first, second = company("first", "first.example.com"), company("second", "second.example.com")
        old_parent, duplicate_parent = role("one", first), role("two", second)
        self.store.upsert_many("verified_roles", "first-roles", [old_parent], "first-run")
        self.store.upsert_many("verified_roles", "second-roles", [duplicate_parent], "second-run")
        selected_job = {"id": "linkedin:123", "linkedin_id": "123", "company": second, "company_id": second["id"],
                        "career_job_ids": [duplicate_parent["id"]], "career_roles": [duplicate_parent]}
        self.store.upsert_many("linkedin_jobs", "selected", [selected_job], "selected-run")
        self.store.upsert_many("applications", "applications", [{**selected_job, "status": "failed"}], "failed-run")
        self.store.upsert_many("companies", "companies", [{**first, "aliases": [second["domain"]]}], "alias-run")
        canonical = self.store.resolve_record("verified_roles", duplicate_parent["id"])
        for stage, set_name in (("linkedin_jobs", "selected"), ("applications", "applications")):
            saved = self.store.load_set(stage, set_name)[0]
            self.assertEqual(saved["career_job_ids"], [canonical["id"]])
            self.assertEqual(saved["career_roles"][0]["id"], canonical["id"])
            self.assertEqual(saved["company_id"], first["id"])
        reimported = self.store.import_artifact(artifact("linkedin_jobs", [selected_job], "selected"))
        self.assertEqual(reimported.records[0]["career_job_ids"], [canonical["id"]])
        self.assertEqual(reimported.records[0]["career_roles"][0]["id"], canonical["id"])

    def test_domain_normalization_deduplicates_source_specific_ids(self):
        self.assertEqual(canonical_domain("HTTPS://WWW.Example.COM/path"), "example.com")
        self.store.upsert_many("companies", "companies", [company("yc:one"), company("portfolio:one", "www.example.com")], "run")
        self.assertEqual(len(self.store.load_set("companies", "companies")), 1)
        self.assertIsNone(canonical_domain("Example Company"))

    def test_invalid_batch_rolls_back_entities_memberships_and_observations(self):
        with self.assertRaises(ValueError):
            self.store.upsert_many("companies", "companies", [company(), {"id": "invalid"}], "run")
        self.assertEqual(self.store.load_set("companies", "companies"), [])
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM observations").fetchone()[0], 0)

    def test_checkpoint_roundtrip_and_independent_set_identity(self):
        self.store.save_checkpoint("yc", "one", {"page": 2, "complete": False})
        self.assertEqual(self.store.get_checkpoint("yc", "one"), {"page": 2, "complete": False})
        self.assertIsNone(self.store.get_checkpoint("yc", "two"))
        self.store.save_checkpoint("yc", "one", None)
        self.assertIsNone(self.store.get_checkpoint("yc", "one"))

    def test_invalid_import_is_validated_before_any_persistence(self):
        with self.assertRaises(ValueError):
            self.store.import_artifact(artifact(), "verified_roles")
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM runs").fetchone()[0], 0)
        with self.assertRaises(ValueError):
            load_inputs(self.store, [artifact(), {"invalid": True}], "companies")
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM runs").fetchone()[0], 0)


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "pipeline.sqlite3"

    def test_discovery_limit_is_per_source_and_failures_are_partial(self):
        def discover(source, config, **kwargs):
            if source == "blocked":
                raise OSError("blocked")
            self.assertEqual(kwargs["limit"], 2)
            return {"records": [company(source + ":1", source + "1.example.com"), company(source + ":2", source + "2.example.com")], "errors": [], "cursor": {"page": 2}, "complete": False}
        result = discover_companies(limit=2, db_path=self.path, sources=["yc", "greylock", "blocked"], discover=discover)
        self.assertEqual(len(result.records), 4)
        self.assertEqual(len(result.errors), 1)
        with PipelineStore(self.path) as store:
            self.assertEqual(store.get_run(result.run_id)["status"], "partial")
            self.assertEqual(store.get_checkpoint("discover:yc", "startup-companies")["cursor"], {"page": 2})

    def test_discovery_resume_and_refresh_use_saved_cursors(self):
        discover = Mock(return_value={"records": [company()], "errors": [], "cursor": "page2", "complete": False})
        discover_companies(db_path=self.path, sources=["yc"], discover=discover)
        discover_companies(db_path=self.path, sources=["yc"], discover=discover)
        self.assertEqual(discover.call_args.kwargs["cursor"], "page2")
        discover_companies(db_path=self.path, sources=["yc"], refresh=True, discover=discover)
        self.assertIsNone(discover.call_args.kwargs["cursor"])

    def test_complete_careers_refresh_closes_vanished_roles_and_retains_audit(self):
        verify = Mock(return_value={"records": [role()], "errors": [], "status": "hiring", "complete": True})
        first = verify_careers([artifact()], "roles", db_path=self.path, verify=verify)
        self.assertEqual(first.records[0]["status"], "open")
        verify.return_value = {"records": [], "errors": [], "status": "not_hiring", "complete": True}
        refreshed = verify_careers([artifact()], "roles", db_path=self.path, refresh=True, verify=verify)
        self.assertEqual(refreshed.records[0]["status"], "closed")
        self.assertFalse(refreshed.records[0]["eligible"])
        self.assertEqual(len(refreshed.delta), 1)

    def test_complete_refresh_into_new_set_closes_globally_known_company_roles(self):
        verify = Mock(return_value={"records": [role()], "errors": [], "status": "hiring", "complete": True})
        first = verify_careers([artifact()], "old-roles", db_path=self.path, verify=verify)
        self.assertEqual(first.records[0]["verification_run_id"], first.run_id)
        with PipelineStore(self.path) as store:
            other_company = company("other", "other.example.com")
            other = role("other-role", other_company)
            store.upsert_many("verified_roles", "other-roles", [other], "other-run")
        verify.return_value = {"records": [], "errors": [], "status": "not_hiring", "complete": True}
        refreshed = verify_careers([artifact()], "new-roles", db_path=self.path, refresh=True, verify=verify)
        with PipelineStore(self.path) as store:
            old = store.load_set("verified_roles", "old-roles")[0]
            self.assertEqual(old["status"], "closed")
            self.assertFalse(old["eligible"])
            self.assertEqual(old["verification_run_id"], refreshed.run_id)
            self.assertEqual(store.load_set("verified_roles", "other-roles")[0]["status"], "open")
            self.assertEqual(len(store.roles_for_company(company()["id"])), 1)
        self.assertEqual(refreshed.records[0]["status"], "closed")

    def test_unknown_refresh_into_different_set_preserves_global_open_roles(self):
        verify = Mock(return_value={"records": [role()], "errors": [], "status": "hiring", "complete": True})
        verify_careers([artifact()], "old-roles", db_path=self.path, verify=verify)
        verify.return_value = {"records": [], "errors": [{"code": "blocked"}], "status": "unknown", "complete": False}
        partial = verify_careers([artifact()], "new-roles", db_path=self.path, refresh=True, verify=verify)
        self.assertTrue(partial.errors)
        with PipelineStore(self.path) as store:
            self.assertEqual(store.load_set("verified_roles", "old-roles")[0]["status"], "open")

    def test_cached_verification_retains_previous_verification_run_id(self):
        verify = Mock(return_value={"records": [role()], "errors": [], "status": "hiring", "complete": True})
        first = verify_careers([artifact()], "roles", db_path=self.path, verify=verify)
        cached = verify_careers([artifact()], "roles", db_path=self.path, verify=verify)
        self.assertEqual(verify.call_count, 1)
        self.assertEqual(cached.records[0]["verification_run_id"], first.run_id)

    def test_incomplete_careers_response_preserves_known_open_role_and_partial_status(self):
        verify = Mock(return_value={"records": [role()], "errors": [], "status": "hiring", "complete": True})
        verify_careers([artifact()], "roles", db_path=self.path, verify=verify)
        verify.return_value = {"records": [], "errors": [{"code": "blocked"}], "status": "unknown", "complete": False}
        partial = verify_careers([artifact()], "roles", db_path=self.path, refresh=True, verify=verify)
        self.assertEqual(partial.records[0]["status"], "open")
        with PipelineStore(self.path) as store:
            self.assertEqual(store.get_run(partial.run_id)["status"], "partial")

    def test_verification_freshness_skips_recent_and_rechecks_expired(self):
        verify = Mock(return_value={"records": [role()], "errors": [], "status": "hiring", "complete": True})
        verify_careers([artifact()], "roles", db_path=self.path, verify=verify)
        verify_careers([artifact()], "roles", db_path=self.path, verify=verify)
        self.assertEqual(verify.call_count, 1)
        with PipelineStore(self.path) as store:
            store.save_checkpoint("verify:company:example", "roles", {"complete": True, "verified_at": "2024-01-01T00:00:00+00:00"})
        verify_careers([artifact()], "roles", db_path=self.path, verify=verify)
        self.assertEqual(verify.call_count, 2)

    def test_entire_discovery_failure_is_durable_failed_run(self):
        failed = discover_companies(db_path=self.path, sources=["yc"], discover=Mock(side_effect=OSError("offline")))
        self.assertEqual(failed.records, [])
        with PipelineStore(self.path) as store:
            self.assertEqual(store.get_run(failed.run_id)["status"], "failed")
            self.assertIsNone(store.get_checkpoint("discover:yc", "startup-companies"))

    def test_interruption_preserves_successful_source_cursor_and_audit_run(self):
        def discover(source, config, **kwargs):
            if source == "greylock":
                raise KeyboardInterrupt()
            return {"records": [company()], "errors": [], "cursor": "next-page", "complete": False}
        with self.assertRaises(KeyboardInterrupt):
            discover_companies(db_path=self.path, sources=["yc", "greylock"], discover=discover)
        with PipelineStore(self.path) as store:
            self.assertEqual(store.connection.execute("SELECT status FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()[0], "interrupted")
            self.assertEqual(len(store.load_set("companies", "startup-companies")), 1)
            self.assertEqual(store.get_checkpoint("discover:yc", "startup-companies")["cursor"], "next-page")


if __name__ == "__main__":
    unittest.main()

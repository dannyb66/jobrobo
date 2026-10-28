"""Pure LinkedIn preparation contracts: no browser, credentials, or network."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from modules.job_pipeline.linkedin import (
    company_matches, fresh_role, prepare_specs, priority_tier, role_matches, selected_specs,
)
from modules.search_state import plan_fingerprint


NOW = datetime(2026, 10, 13, 12, 0, tzinfo=timezone.utc)


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)


def config(**overrides):
    values = {
        "search_location": "California", "switch_number": 1, "sort_by": "Most recent",
        "date_posted": "Past month", "salary": "", "easy_apply_only": True,
        "experience_level": [], "job_type": ["Full-time"], "on_site": ["Remote", "Hybrid"],
        "companies": [], "location": [], "industry": [], "job_function": [], "job_titles": [],
        "benefits": [], "commitments": [], "under_10_applicants": False,
        "in_your_network": False, "fair_chance_employer": False,
        "about_company_bad_words": ["Staffing"], "about_company_good_words": [],
        "bad_words": ["US Citizen"], "security_clearance": False,
        "did_masters": True, "current_experience": -1,
    }
    values.update(overrides)
    return values


def profile():
    return {"profile_name": "staff-principal-platform", "profile_version": "2",
            "skills": ["Python", "distributed systems"], "role_lanes": ["Staff AI Platform Engineer"],
            "dynamic_search_enabled": True, "ai_query_refinement_enabled": True}


def company(ident="company:example", name="Example AI", **overrides):
    value = {"id": ident, "name": name, "domain": "example.ai", "website": "https://example.ai",
             "description": "Build AI infrastructure", "aliases": ["Example AI Corporation"],
             "employee_count": 100, "funding_stage": "Series B",
             "sources": [{"name": "company_website", "url": "https://example.ai/about", "observed_at": NOW.isoformat()}]}
    value.update(overrides)
    return value


def role(ident="role:staff", title="Staff AI Platform Engineer", employer=None, **overrides):
    employer = employer or company()
    value = {"id": ident, "title": title, "company": employer, "company_id": employer.get("id"),
             "description": "Build production platform systems with Python.",
             "career_url": "https://example.ai/jobs/" + ident.split(":")[-1],
             "locations": ["California, United States"], "workplace_type": "Remote",
             "employment_type": "Full-time", "published_at": NOW.isoformat(), "sources": [],
             "verified_at": NOW.isoformat(), "verification_run_id": "careers-run",
             "status": "open", "eligible": True, "exclusion_reasons": []}
    value.update(overrides)
    return value


def job(ident="123", parent=None, **overrides):
    parent = parent or role()
    value = {"id": ident, "linkedin_id": ident, "job_id": ident, "eligible": True,
             "title": parent["title"], "company": deepcopy(parent["company"]),
             "company_id": parent["company_id"], "career_roles": [deepcopy(parent)],
             "career_job_ids": [parent["id"]], "query_id": "manual:original-query",
             "query_text": "Find staff AI infrastructure at Example AI.", "search_mode": "ai",
             "classic_query": "Example AI Staff Infrastructure Engineer", "search_source": "manual",
             "search_run_id": "original-search-run"}
    value.update(overrides)
    return value


class LinkedInPreparationTests(unittest.TestCase):
    def setUp(self):
        frozen = patch("modules.job_pipeline.linkedin.datetime", FrozenDatetime)
        frozen.start()
        self.addCleanup(frozen.stop)
        frozen_careers = patch("modules.job_pipeline.careers.datetime", FrozenDatetime)
        frozen_careers.start()
        self.addCleanup(frozen_careers.stop)

    def specs(self, roles=None, search=None, *, application=True):
        return prepare_specs(roles if roles is not None else [role()], profile(), search or config(), application=application)

    def test_freshness_accepts_seven_day_boundary_and_rejects_missing_stale_future(self):
        self.assertTrue(fresh_role(role(verified_at=(NOW - timedelta(days=7)).isoformat())))
        self.assertTrue(fresh_role(role(verified_at=NOW.replace(tzinfo=None).isoformat())))
        for timestamp in (None, "invalid", (NOW - timedelta(days=7, seconds=1)).isoformat(), (NOW + timedelta(hours=1)).isoformat()):
            with self.subTest(timestamp=timestamp):
                self.assertFalse(fresh_role(role(verified_at=timestamp)))

    def test_company_identity_uses_exact_normalized_names_aliases_and_saved_urls(self):
        employer = company(linkedin_url="https://www.linkedin.com/company/example-ai/")
        self.assertTrue(company_matches(employer, "Example AI, Inc."))
        self.assertTrue(company_matches(employer, "Example AI Corporation"))
        self.assertFalse(company_matches(employer, "Example AI Staffing"))
        self.assertFalse(company_matches(employer, "Example"))
        self.assertTrue(company_matches(employer, "Renamed Company", "https://www.linkedin.com/company/example-ai"))
        self.assertFalse(company_matches(employer, "Example AI", "https://www.linkedin.com/company/unrelated"))
        for tab in ("life", "about", "jobs"):
            self.assertTrue(company_matches(employer, "Example AI", "https://www.linkedin.com/company/example-ai/" + tab + "/"))
        self.assertFalse(company_matches(employer, "Example AI", "https://unrelated.example/company/example-ai/life/"))
        self.assertFalse(company_matches(employer, "Example AI", "https://www.linkedin.com/company/unrelated/life/"))

    def test_current_config_renders_scoped_queries_snapshots_and_parent_traceability(self):
        settings = config()
        primary, second = role(), role("role:another-location")
        specs, errors = self.specs([primary, second], settings)
        self.assertEqual(errors, [])
        self.assertEqual(len(specs), 1)
        current = specs[0]
        self.assertIn("Companies: Example AI", current.query_text)
        self.assertNotIn("California", current.query_text)
        self.assertNotIn("Full-time", current.query_text)
        self.assertNotIn("Use Easy Apply", current.query_text)
        self.assertEqual(current.filters_snapshot["intent"]["search_location"], "California")
        self.assertEqual(current.filters_snapshot["intent"]["on_site"], ["Remote", "Hybrid"])
        self.assertTrue(current.filters_snapshot["intent"]["easy_apply_only"])
        self.assertEqual(current.filters_snapshot["intent"]["companies"], ["Example AI"])
        self.assertEqual(current.pipeline_context["career_job_ids"], [primary["id"], second["id"]])
        self.assertEqual(current.pipeline_context["verification_run_ids"], ["careers-run"])
        self.assertEqual(settings["companies"], [])
        self.assertEqual(current.quota, 1)

    def test_module_configuration_and_deeply_independent_context_are_supported(self):
        parent = role()
        specs, _ = prepare_specs([parent], SimpleNamespace(**profile()), SimpleNamespace(**config()))
        specs[0].pipeline_context["career_roles"][0]["company"]["aliases"].append("Mutation")
        self.assertNotIn("Mutation", parent["company"]["aliases"])

    def test_canonical_company_restriction_is_not_replaced_by_role_scope(self):
        specs, _ = self.specs(search=config(companies=["Other Company"]))
        self.assertEqual(specs, [])
        specs, _ = self.specs(search=config(companies=["Example AI Corporation"]))
        self.assertEqual(len(specs), 1)

    def test_closed_ineligible_and_stale_parents_never_create_search_targets(self):
        parents = [role("closed", status="closed"), role("ineligible", eligible=False, workplace_type="On-site"),
                   role("stale", verified_at=(NOW - timedelta(days=8)).isoformat())]
        specs, errors = self.specs(parents)
        self.assertEqual(specs, [])
        self.assertIn("stale_verification", {error["code"] for error in errors})

    def test_broadened_filters_reevaluate_fresh_cached_role_eligibility(self):
        previously_excluded = role(eligible=False, workplace_type="On-site", exclusion_reasons=["workplace_type_excluded"])
        old_specs, _ = self.specs([previously_excluded])
        self.assertEqual(old_specs, [])
        broadened, errors = self.specs([previously_excluded], config(on_site=["Remote", "Hybrid", "On-site"]))
        self.assertEqual(errors, [])
        self.assertEqual(len(broadened), 1)
        self.assertTrue(broadened[0].pipeline_context["career_roles"][0]["eligible"])
        self.assertEqual(broadened[0].pipeline_context["career_roles"][0]["exclusion_reasons"], [])

    def test_parent_company_id_mismatch_is_rejected(self):
        specs, errors = self.specs([role(company_id="company:unrelated")])
        self.assertEqual(specs, [])
        self.assertTrue(errors)

    def test_missing_parent_identity_does_not_start_search(self):
        specs, errors = self.specs([role(employer={"name": "Example AI"}, company_id=None)])
        self.assertEqual(specs, [])
        self.assertTrue(errors)

    def test_current_filters_revalidate_old_eligible_flag(self):
        invalid = [
            role(description="Requires US Citizen status"),
            role(workplace_type="On-site"), role(employment_type="Contract"),
            role(locations=["London, United Kingdom"]),
            role(description="Active security clearance required"),
        ]
        for parent in invalid:
            with self.subTest(parent=parent):
                specs, _ = self.specs([parent])
                self.assertEqual(specs, [])

    def test_related_engineering_titles_and_mts_preserve_implicit_levels(self):
        specs, _ = self.specs([role(title="Principal Platform Engineer")])
        current = specs[0]
        for title in ("Principal Systems Engineer", "Member of Technical Staff - Inference Runtime",
                      "Member of Technical Staff - Machines", "Principal Member of Technical Staff - Systems",
                      "AI Engineer", "Platform Engineer", "Sales Engineer", "Support Engineer", "SRE", "Engineering Manager"):
            with self.subTest(title=title):
                self.assertTrue(role_matches(title, "Build production services", current))
        for title in ("Staff Platform Engineer", "Senior Software Engineer", "Junior AI Engineer",
                      "Senior Member of Technical Staff - Systems", "Staff Member of Technical Staff - Systems",
                      "Software Engineering Intern", "Recruiter"):
            with self.subTest(title=title):
                self.assertFalse(role_matches(title, "Build AI platform infrastructure", current))

    def test_priority_order_uses_company_evidence_and_keeps_unknowns_unknown(self):
        cases = [
            (company(employee_count=50, funding_stage=None), "Staff Engineer", 1),
            (company(employee_count=None, funding_stage="Series C"), "Principal Engineer", 1),
            (company(employee_count="51-200", funding_stage=None), "Staff Engineer", 1),
            (company(), "Platform Engineer", 2), (company(), "Founding Engineer", 3),
            (company(employee_count=12, funding_stage="Seed"), "Staff Engineer", 3),
            (company(employee_count=None, funding_stage=None), "Staff Engineer", 4),
        ]
        for employer, title, expected in cases:
            with self.subTest(employer=employer, title=title):
                self.assertEqual(priority_tier(employer, title), expected)
        parents = [role("unknown", employer=company("unknown", "Unknown", employee_count=None, funding_stage=None)),
                   role("founding", title="Founding Engineer"), role("principal", title="Principal Platform Engineer")]
        specs, errors = self.specs(parents)
        self.assertEqual(errors, [])
        self.assertEqual([current.pipeline_context["priority_tier"] for current in specs], [1, 3, 4])

    def test_saved_query_provenance_is_restored_without_old_filters_or_parents(self):
        saved = job(search_mode="classic", search_spec={"filters_snapshot": {"intent": {"search_location": "London"}}})
        specs, selected, errors = selected_specs([saved], profile(), config())
        self.assertEqual(errors, [])
        self.assertEqual(len(specs), 1)
        current = specs[0]
        self.assertEqual(current.query_id, saved["query_id"])
        self.assertEqual(current.query_text, saved["query_text"])
        self.assertEqual(current.classic_query, saved["classic_query"])
        self.assertEqual(current.source, "manual")
        self.assertEqual(current.mode, "classic")
        self.assertEqual(current.filters_snapshot["intent"]["search_location"], "California")
        self.assertEqual(current.pipeline_context["career_job_ids"], ["role:staff"])
        self.assertEqual(selected[current.query_id][0]["search_run_id"], "original-search-run")

    def test_only_selected_ids_are_returned_and_invalid_records_are_excluded(self):
        jobs = [job("123"), job("456", eligible=False), job("invalid-id"),
                job("789", career_job_ids=["unrelated-parent"])]
        specs, selected, _ = selected_specs(jobs, profile(), config())
        self.assertEqual(len(specs), 1)
        self.assertEqual([record["linkedin_id"] for records in selected.values() for record in records], ["123"])

    def test_stale_selected_parent_and_employer_mismatch_cannot_be_applied(self):
        for selected_job in (job(parent=role(verified_at=(NOW - timedelta(days=8)).isoformat())),
                             job(company_id="company:other"), job(company=company(name="Other Company"))):
            with self.subTest(selected_job=selected_job):
                specs, selected, errors = selected_specs([selected_job], profile(), config())
                self.assertEqual(specs, [])
                self.assertEqual(selected, {})
                self.assertTrue(errors)

    def test_one_saved_query_id_cannot_mix_companies_or_query_texts(self):
        conflict = job("456", query_text="Different saved query")
        specs, selected, errors = selected_specs([job(), conflict], profile(), config())
        self.assertEqual([record["linkedin_id"] for rows in selected.values() for record in rows], ["123"])
        self.assertIn("conflicting_query", {row["code"] for row in errors})

    def test_one_query_id_cannot_relabel_other_jobs_search_mode_or_classic_query(self):
        for changed in ({"search_mode": "classic"}, {"classic_query": "Different original keywords"}, {"search_source": "generated"}):
            with self.subTest(changed=changed):
                specs, selected, errors = selected_specs([job(), job("456", **changed)], profile(), config())
                self.assertEqual([record["linkedin_id"] for rows in selected.values() for record in rows], ["123"])
                self.assertIn("conflicting_query", {row["code"] for row in errors})

    def test_invalid_search_mode_does_not_execute_selected_job(self):
        specs, selected, errors = selected_specs([job(search_mode="unsupported")], profile(), config())
        self.assertEqual(specs, [])
        self.assertEqual(selected, {})
        self.assertIn("invalid_search_metadata", {row["code"] for row in errors})

    def test_resume_fingerprint_changes_with_filters_and_current_parent_verification(self):
        first, _ = self.specs()
        changed_filters, _ = self.specs(search=config(salary="$200,000+"))
        changed_parent, _ = self.specs([role(verification_run_id="new-verification-run")])
        self.assertNotEqual(plan_fingerprint(first, profile()), plan_fingerprint(changed_filters, profile()))
        self.assertNotEqual(plan_fingerprint(first, profile()), plan_fingerprint(changed_parent, profile()))
        copied = deepcopy(first)
        self.assertEqual(plan_fingerprint(first, profile()), plan_fingerprint(copied, profile()))


if __name__ == "__main__":
    unittest.main()

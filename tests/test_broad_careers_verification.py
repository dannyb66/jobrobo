"""Broad official engineering inventory stays separate from application requirements."""

from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from modules.job_pipeline.careers import classify_engineering_role, evaluate_role, evaluate_verification_role, verify_company
from modules.job_pipeline.linkedin import prepare_specs, selected_specs
from modules.job_pipeline.models import StageResult
from modules.job_pipeline.service import verify_careers
from modules.job_pipeline.store import PipelineStore
from test_job_pipeline_careers import ASHBY_URL, Client, ashby_job, company as official_company
from test_job_pipeline_linkedin import NOW, FrozenDatetime, company, config, job, profile, role


class BroadVerificationTests(unittest.TestCase):
    def setUp(self):
        for module in ("careers", "linkedin", "service"):
            frozen = patch("modules.job_pipeline." + module + ".datetime", FrozenDatetime)
            frozen.start()
            self.addCleanup(frozen.stop)

    def test_engineering_and_science_title_matrix(self):
        titles = (
            "Software Engineer - Dedicated Inference", "AI Engineer", "Cloud Platform Engineer",
            "Engineering Manager, Cloud Platform", "Engineering Manager Runtime - Storage",
            "Forward Deployed Engineer", "Frontend Engineer", "IT Support / Operations Engineer",
            "IT/Support Operations Engineer (NY)", "Security Engineer", "Site Reliability Engineer", "SRE",
            "DevOps Engineer", "ML Research Engineer", "Post-Training Research Scientist",
            "Post-Training Applied Researcher", "Product Data Scientist", "Data Scientist (Analytics)",
            "Data Engineer", "Hardware Engineer", "Firmware Engineer", "FPGA Engineer", "Robotics Engineer",
            "QA Automation Engineer", "Member of Technical Staff - Storage", "MTS, Runtime",
            "Technical Staff, Inference", "Senior Technical Staff", "Director of Engineering", "VP Engineering",
            "ML Research Intern", "Applied Scientist", "IT Ops Specialist",
        )
        for title in titles:
            with self.subTest(title=title):
                self.assertTrue(classify_engineering_role(title)["engineering_related"])

    def test_adjacent_occupations_require_review_and_product_manager_precedes_developer_token(self):
        titles = ("Sales Engineer", "Solutions Engineer", "Solutions Architect", "GTM Engineer", "Developer Advocate",
                  "Design Engineer (Brand Team)", "Support Engineer", "Field Application Engineer",
                  "Sales Engineering Manager", "Head of Sales Engineering", "Marketing Engineer",
                  "Business Development Engineer", "Product Manager, Developer Experience",
                  "Product Manager, Developer Tools", "Technical Program Manager, Developer Infrastructure",
                  "Technical Program Manager, Model Performance")
        for title in titles:
            with self.subTest(title=title):
                classification = classify_engineering_role(title)
                self.assertEqual(classification["family"], "engineering_adjacent")
                self.assertEqual(classification["confidence"], "review")
                self.assertTrue(classification["requires_review"])
        self.assertEqual(classify_engineering_role("Software Engineering Manager")["family"], "engineering_management")

    def test_actual_occupation_overrides_technical_company_boilerplate(self):
        description = "Our engineers build software AI infrastructure, Kubernetes operators and ML models."
        titles = ("Engineering Recruiter", "Recruiter, Software Engineering", "Technical Recruiter",
                  "Engineering Marketing Manager", "Developer Marketing Manager", "Technical Sales Recruiter",
                  "Executive Assistant to Head of Engineering", "Account Executive - AI Native",
                  "Sales Development Representative", "Product Marketing Manager, Solutions", "Social Media Manager",
                  "Revenue Analyst", "Office Manager", "HR Business Partner", "Brand Designer", "Motion Designer (Brand Team)")
        for title in titles:
            with self.subTest(title=title):
                self.assertFalse(classify_engineering_role(title, description, "EPD", "Engineering")["engineering_related"])

    def test_contextual_roles_use_evidence_without_department_becoming_blanket_inclusion(self):
        for context in ("Infrastructure", {"name": "Infrastructure"}, [{"name": "Infrastructure"}], None, 3):
            with self.subTest(context=context):
                result = classify_engineering_role("Storage Manager", department=context)
                self.assertTrue(result["requires_review"])
        self.assertTrue(classify_engineering_role("AI Engineer", department="G&A")["engineering_related"])
        self.assertFalse(classify_engineering_role("Brand Designer", department="EPD")["engineering_related"])
        self.assertTrue(classify_engineering_role("Global Capacity Manager", "This is an engineering role building Kubernetes operators.")["requires_review"])
        self.assertFalse(classify_engineering_role("Global Capacity Manager", "Our engineers build Kubernetes software.")["engineering_related"])
        fellowship = classify_engineering_role("Base Labs Fellowship", "FELLOWSHIP OVERVIEW: 3 months of full-time research.")
        self.assertEqual(fellowship["family"], "technical_research")
        self.assertFalse(classify_engineering_role("Community Fellowship", "Our company builds AI software.")["engineering_related"])

    def test_candidate_constraints_are_visible_notes_in_inventory_and_strict_at_application(self):
        parent = role(title="Security Engineer", locations=["San Francisco, California, United States"], workplace_type="On-site",
                      employment_type="Temporary", published_at="2020-01-01T00:00:00+00:00",
                      description="Requires US Citizen status and security clearance with 12 years experience.")
        settings = config(current_experience=3)
        inventory = evaluate_verification_role(deepcopy(parent), settings)
        self.assertTrue(inventory["eligible"])
        self.assertTrue(inventory["verification_eligible"])
        self.assertEqual(inventory["exclusion_reasons"], [])
        self.assertFalse(inventory["application_eligible"])
        expected = {"workplace_type_excluded", "employment_type_excluded", "posted_date_excluded", "security_clearance_required", "experience_excluded", "description_exclusion:US Citizen"}
        self.assertTrue(expected.issubset(inventory["application_exclusion_reasons"]))
        self.assertTrue(expected.issubset(inventory["review_notes"]))
        strict = evaluate_role(deepcopy(inventory), settings)
        self.assertFalse(strict["eligible"])
        self.assertEqual(strict["evaluation_scope"], "application_requirements")

    def test_configured_geography_controls_inventory_without_widening_remote_scope(self):
        cases = [
            (["San Francisco"], "Hybrid", True, None),
            (["Palo Alto, California"], "On-site", True, None),
            (["New York", "San Francisco"], "Unknown", True, None),
            (["United States"], "Remote", True, None),
            (["California, United States"], "Remote", True, None),
            (["New York, United States"], "Hybrid", False, "location_excluded"),
            (["Stockholm", "New York"], "Unknown", False, "location_excluded"),
            (["Germany"], "Remote", False, "location_excluded"),
            (["Remote", "New York City", "Seattle"], "Remote", False, "location_excluded"),
            (["Remote"], "Remote", False, "unknown_location"),
            ([], "Unknown", False, "unknown_location"),
        ]
        for locations, workplace, included, reason in cases:
            with self.subTest(locations=locations, workplace=workplace):
                result = evaluate_verification_role(role(locations=locations, workplace_type=workplace), config(search_location="San Francisco Bay Area, United States"))
                self.assertEqual(result["eligible"], included)
                self.assertEqual(result["verification_eligible"], included)
                self.assertEqual(result["verification_exclusion_reasons"], [reason] if reason else [])
                self.assertEqual(result["exclusion_reasons"], [reason] if reason else [])
                self.assertEqual(result["verification_policy_version"], 3)

    def test_location_config_changes_and_empty_config_are_respected(self):
        parent = role(locations=["New York, United States"], workplace_type="Hybrid")
        self.assertFalse(evaluate_verification_role(deepcopy(parent), config())["eligible"])
        self.assertTrue(evaluate_verification_role(deepcopy(parent), config(search_location="New York, United States"))["eligible"])
        self.assertTrue(evaluate_verification_role(deepcopy(parent), config(search_location=""))["eligible"])
        self.assertFalse(prepare_specs([parent], profile(), config())[0])

    def test_cached_geography_recomputed_after_config_change_without_refetch(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "pipeline.sqlite3")
            parent = role(locations=["New York, United States"], workplace_type="Hybrid", verification_run_id="original-run")
            parent = evaluate_verification_role(parent, config(search_location="New York, United States"))
            with PipelineStore(db) as store:
                store.upsert_many("verified_roles", "roles", [parent], "old-run")
                store.save_checkpoint("verify:" + parent["company_id"], "roles", {"complete": True, "verified_at": NOW.isoformat()})
            incoming = StageResult.create("companies", "companies", "input", [parent["company"]])
            adapter = Mock()
            with patch("config.search.search_location", "San Francisco Bay Area, United States"):
                result = verify_careers([incoming], "roles", db_path=db, verify=adapter)
            adapter.assert_not_called()
            saved = result.records[0]
            self.assertFalse(saved["verification_eligible"])
            self.assertEqual(saved["verification_exclusion_reasons"], ["location_excluded"])
            self.assertEqual(saved["verified_at"], parent["verified_at"])
            self.assertEqual(saved["verification_run_id"], "original-run")

    def test_missing_jd_stays_in_official_inventory_but_cannot_prepare_application(self):
        parent = evaluate_verification_role(role(description=""), config())
        self.assertTrue(parent["eligible"])
        self.assertFalse(parent["application_eligible"])
        self.assertIn("missing_full_description", parent["review_notes"])
        specs, errors = prepare_specs([parent], profile(), config())
        self.assertEqual((len(specs), errors), (1, []))
        specs, selected, errors = selected_specs([job(parent=parent)], profile(), config())
        self.assertEqual((specs, selected), ([], {}))
        self.assertTrue(errors)

    def test_search_preparation_keeps_inventory_despite_current_candidate_exclusions(self):
        parent = role(title="Support Engineer", workplace_type="On-site", eligible=False)
        specs, errors = prepare_specs([parent], profile(), config(companies=["Another Company"]))
        self.assertEqual((len(specs), errors), (1, []))
        current = specs[0].pipeline_context["career_roles"][0]
        self.assertTrue(current["eligible"])
        self.assertFalse(current["application_eligible"])
        self.assertIn("workplace_type_excluded", current["review_notes"])
        self.assertIn("company_excluded", current["review_notes"])
        self.assertEqual(specs[0].filters_snapshot["intent"]["on_site"], ["Remote", "Hybrid"])

    def test_forged_flags_never_override_status_identity_freshness_or_application_requirements(self):
        cases = [role(status="closed"), role(status="unknown"), role(is_prospect=True), role(title="Engineering Recruiter"),
                 role(description=""), role(workplace_type="On-site"), role(description="US Citizen required"),
                 role(company_id="company:other"), role(verified_at=(NOW - timedelta(days=8)).isoformat())]
        for parent in cases:
            parent.update(eligible=True, application_eligible=True, verification_eligible=True, exclusion_reasons=[])
            with self.subTest(parent=parent):
                specs, selected, _ = selected_specs([job(parent=parent)], profile(), config())
                self.assertEqual((specs, selected), ([], {}))
        for parent in cases[:4] + cases[-2:]:
            with self.subTest(inventory=parent):
                self.assertEqual(prepare_specs([parent], profile(), config())[0], [])

    def test_generic_official_html_traversal_keeps_sre_and_requires_real_detail_evidence(self):
        board, detail = "https://example.test/careers", "https://example.test/jobs/sre"
        pages = {board: '<h1>Engineering</h1><a href="/jobs/sre">SRE</a>',
                 detail: '<h1>SRE</h1><div class="job-description">Build reliable infrastructure.</div><a href="/apply">Apply now</a>'}
        result = verify_company(official_company(board), config(), client=Client(pages))
        self.assertEqual([r["title"] for r in result["records"]], ["SRE"])
        self.assertFalse(result["records"][0]["verification_eligible"])
        self.assertIn("unknown_location", result["records"][0]["verification_exclusion_reasons"])
        empty = verify_company(official_company(board), config(), client=Client({board: '<h1>Engineering</h1><a href="/apply">Apply</a>'}))
        self.assertEqual(empty["records"], [])
        pages[detail] = '<h1>SRE</h1><button>Apply now</button>'
        missing = verify_company(official_company(board), config(), client=Client(pages))
        self.assertFalse(missing["records"][0]["eligible"])
        self.assertIn("missing_full_description", missing["records"][0]["review_notes"])
        self.assertFalse(missing["complete"])

    def test_ashby_department_team_and_duplicate_titles_survive_store_export(self):
        rows = [ashby_job(id=str(i), title="AI Engineer", department="G&A", team="Data and Analytics",
                         jobUrl="https://jobs.ashbyhq.com/example/" + str(i)) for i in range(2)]
        result = verify_company(official_company(), config(search_location="San Francisco Bay Area, United States"), client=Client({ASHBY_URL: {"jobs": rows}}))
        self.assertEqual(len(result["records"]), 2)
        with PipelineStore(":memory:") as store:
            store.upsert_many("verified_roles", "test", result["records"], "test-run")
            payload = StageResult.create("verified_roles", "test", "export", store.load_set("verified_roles", "test")).to_dict()
        for saved in payload["records"]:
            self.assertEqual((saved["department"], saved["team"]), ("G&A", "Data and Analytics"))
            self.assertTrue(saved["verification_eligible"])

    def test_lever_department_and_team_context_are_preserved(self):
        url = "https://api.lever.co/v0/postings/example?mode=json&limit=100&skip=0"
        posting = {"id": "pm", "text": "Product Manager", "hostedUrl": "https://jobs.lever.co/example/pm",
                   "descriptionPlain": "Lead the product roadmap.",
                   "categories": {"location": "California", "commitment": "Full-time",
                                  "department": "Product", "team": "Developer Infrastructure"}}
        result = verify_company(official_company("https://jobs.lever.co/example"), config(), client=Client({url: [posting]}))
        saved = result["records"][0]
        self.assertEqual((saved["department"], saved["team"]), ("Product", "Developer Infrastructure"))
        self.assertTrue(saved["eligible"])
        self.assertEqual(saved["role_classification"]["family"], "engineering_adjacent")

    def test_cached_old_policy_is_recomputed_without_refetch_or_freshness_inflation(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "pipeline.sqlite3")
            parent = role(title="SRE", eligible=False, exclusion_reasons=["outside_role_families"], verification_run_id="original-run")
            with PipelineStore(db) as store:
                store.upsert_many("verified_roles", "roles", [parent], "old-run")
                store.save_checkpoint("verify:" + parent["company_id"], "roles", {"complete": True, "verified_at": NOW.isoformat()})
            incoming = StageResult.create("companies", "companies", "input", [parent["company"]])
            adapter = Mock()
            result = verify_careers([incoming], "roles", db_path=db, verify=adapter, search_config=config())
            adapter.assert_not_called()
            saved = result.records[0]
            self.assertTrue(saved["eligible"])
            self.assertEqual(saved["exclusion_reasons"], [])
            self.assertEqual(saved["verification_policy_version"], 3)
            self.assertEqual(saved["verified_at"], parent["verified_at"])
            self.assertEqual(saved["verification_run_id"], "original-run")

    def test_newer_legacy_closure_import_clears_previous_application_flags(self):
        with PipelineStore(":memory:") as store:
            store.upsert_many("verified_roles", "test", [evaluate_verification_role(role(), config())], "open")
            closure = role(status="closed", eligible=False, verified_at=(NOW + timedelta(hours=1)).isoformat())
            store.upsert_many("verified_roles", "test", [closure], "legacy-closed")
            saved = store.load_set("verified_roles", "test")[0]
            self.assertEqual(saved["status"], "closed")
            for key in ("eligible", "verification_eligible", "application_eligible"):
                self.assertFalse(saved[key])
            self.assertIn("role_closed", saved["application_exclusion_reasons"])

    def test_new_evidence_clears_derived_diagnostics_and_stale_open_cannot_revive_legacy_closure(self):
        with PipelineStore(":memory:") as store:
            parent = evaluate_verification_role(role(workplace_type="On-site"), config())
            store.upsert_many("verified_roles", "test", [parent], "first")
            current = evaluate_verification_role(role(), config())
            store.upsert_many("verified_roles", "test", [current], "second")
            saved = store.load_set("verified_roles", "test")[0]
            self.assertTrue(saved["application_eligible"])
            self.assertEqual(saved["application_exclusion_reasons"], [])
            self.assertEqual(saved["review_notes"], [])
        with PipelineStore(":memory:") as store:
            closed = role(status="closed", eligible=False, exclusion_reasons=["role_closed"])
            store.upsert_many("verified_roles", "test", [closed], "closed")
            store.upsert_many("verified_roles", "test", [current], "stale-open")
            saved = store.load_set("verified_roles", "test")[0]
            self.assertEqual(saved["status"], "closed")
            for key in ("eligible", "verification_eligible", "application_eligible"):
                self.assertFalse(saved[key])
            self.assertIn("role_closed", saved["verification_exclusion_reasons"])
            self.assertIn("role_closed", saved["application_exclusion_reasons"])
            self.assertEqual(prepare_specs([saved], profile(), config())[0], [])


if __name__ == "__main__":
    unittest.main()

import json
from datetime import datetime, timedelta, timezone
import unittest
from unittest.mock import Mock

from modules.job_pipeline.careers import evaluate_role, priority_tier, role_record, verify_company
from modules.job_pipeline.sources import stable_id


class Response:
    def __init__(self, body, url, status=200):
        self.text = body if isinstance(body, str) else json.dumps(body)
        self.url, self.status_code = url, status


class Client:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, timeout=None):
        self.calls.append((url, timeout))
        body = self.pages[url]
        if isinstance(body, Exception):
            raise body
        return body if isinstance(body, Response) else Response(body, url)


def company(career="https://jobs.ashbyhq.com/example", **overrides):
    return {"id": stable_id("company", "example.test"), "name": "Example", "domain": "example.test",
            "website": "https://example.test", "careers_url": career, "sources": [{"name": "vc", "url": "https://vc.test/company/example"}],
            "employee_count": 80, "funding_stage": "Series C", "aliases": [], "description": "Builds developer infrastructure", **overrides}


def config(**overrides):
    return {"search_location": "San Francisco Bay Area, United States", "on_site": ["Remote", "Hybrid"],
            "job_type": ["Full-time"], "date_posted": "Past month", "bad_words": ["US Citizen"],
            "about_company_bad_words": ["Staffing"], "about_company_good_words": [],
            "security_clearance": False, "current_experience": -1, "did_masters": False, **overrides}


def ashby_job(**overrides):
    return {"id": "posting-1", "title": "Staff Backend Engineer", "location": "San Francisco, CA, United States",
            "workplaceType": "Hybrid", "employmentType": "FullTime", "isListed": True,
            "descriptionPlain": "Build distributed systems with Python and production reliability.",
            "publishedAt": datetime.now(timezone.utc).isoformat(),
            "jobUrl": "https://jobs.ashbyhq.com/example/posting-1", **overrides}


ASHBY_URL = "https://api.ashbyhq.com/posting-api/job-board/example?includeCompensation=true"


class CareerAdapterTests(unittest.TestCase):
    def test_ashby_official_board_preserves_full_description_metadata_and_stable_url_id(self):
        job = ashby_job(descriptionPlain="Full first paragraph. Full requirements paragraph. Full compensation paragraph.")
        client = Client({ASHBY_URL: {"jobs": [job]}})
        result = verify_company(company(), config(), client=client)
        self.assertTrue(result["complete"])
        self.assertEqual(result["status"], "hiring")
        role = result["records"][0]
        self.assertEqual(role["description"], job["descriptionPlain"])
        self.assertEqual(role["workplace_type"], "Hybrid")
        self.assertEqual(role["employment_type"], "Full-time")
        self.assertTrue(role["eligible"])
        self.assertEqual(role["priority_tier"], 1)
        self.assertEqual(role["company_id"], company()["id"])
        self.assertEqual(role["sources"][-1]["name"], "ashby")
        self.assertTrue(role["verified_at"])
        self.assertEqual(client.calls, [(ASHBY_URL, 12)])
        changed = verify_company(company(), config(), client=Client({ASHBY_URL: {"jobs": [dict(job, title="Principal Backend Engineer")]}}))
        self.assertEqual(changed["records"][0]["id"], role["id"])

    def test_unlisted_ashby_postings_are_not_public_discovery_records(self):
        result = verify_company(company(), config(), client=Client({ASHBY_URL: {"jobs": [ashby_job(isListed=False)]}}))
        self.assertEqual(result["records"], [])
        self.assertEqual(result["status"], "not_hiring")
        self.assertTrue(result["complete"])

    def test_empty_public_ats_board_is_not_hiring_but_inaccessible_or_malformed_board_is_unknown(self):
        cases = [({"jobs": []}, "not_hiring", True, None),
                 (Response("Forbidden", ASHBY_URL, 403), "unknown", False, "restricted"),
                 (TimeoutError("network"), "unknown", False, "network"),
                 ({"error": "not a board"}, "unknown", False, "schema_changed")]
        for body, status, complete, code in cases:
            with self.subTest(status=status, code=code):
                render = Mock()
                result = verify_company(company(), config(), client=Client({ASHBY_URL: body}), render=render)
                self.assertEqual(result["status"], status)
                self.assertEqual(result["complete"], complete)
                if code:
                    self.assertEqual(result["errors"][0]["code"], code)
                render.assert_not_called()

    def test_official_site_link_to_ashby_is_followed_once_despite_many_apply_links(self):
        page = "https://example.test/careers"
        html = '<h1>Careers</h1>' + ''.join(f'<a href="https://jobs.ashbyhq.com/example/job-{n}">Apply</a>' for n in range(30))
        client = Client({page: html, ASHBY_URL: {"jobs": [ashby_job()]}})
        result = verify_company(company(page), config(), client=client)
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual([url for url, _ in client.calls], [page, ASHBY_URL])

    def test_meta_refresh_career_page_is_followed_to_public_company_page(self):
        page, target = "https://example.test/careers", "https://example.test/company"
        client = Client({page: '<meta http-equiv="refresh" content="0;url=/company#careers">',
                         target: '<a href="https://jobs.ashbyhq.com/example">Open positions</a>',
                         ASHBY_URL: {"jobs": [ashby_job()]}})
        result = verify_company(company(page), config(), client=client)
        self.assertEqual(result["status"], "hiring")
        self.assertEqual([url for url, _ in client.calls], [page, target, ASHBY_URL])

    def test_greenhouse_board_requests_full_content_and_marks_unknown_posting_date_honestly(self):
        url = "https://boards-api.greenhouse.io/v1/boards/example/jobs?content=true"
        job = {"id": 42, "title": "Principal Infrastructure Engineer", "location": {"name": "San Francisco, CA"},
               "absolute_url": "https://job-boards.greenhouse.io/example/jobs/42",
               "content": "&lt;p&gt;Full-time hybrid engineering role.&lt;/p&gt;&lt;p&gt;Complete requirements.&lt;/p&gt;",
               "updated_at": datetime.now(timezone.utc).isoformat()}
        result = verify_company(company("https://job-boards.greenhouse.io/example"), config(), client=Client({url: {"jobs": [job]}}))
        role = result["records"][0]
        self.assertEqual(role["description"], "Full-time hybrid engineering role. Complete requirements.")
        self.assertEqual(role["workplace_type"], "Hybrid")
        self.assertEqual(role["employment_type"], "Full-time")
        self.assertIn("unknown_posted_date", role["exclusion_reasons"])
        self.assertFalse(role["eligible"])
        self.assertEqual(result["status"], "hiring")

    def test_lever_full_description_combines_requirements_and_additional_sections(self):
        url = "https://api.lever.co/v0/postings/example?mode=json&limit=100&skip=0"
        job = {"id": "lever-42", "text": "Software Engineer, Systems", "hostedUrl": "https://jobs.lever.co/example/lever-42",
               "categories": {"location": "Remote - United States", "commitment": "Full-time"},
               "descriptionPlain": "Build runtime systems.", "additionalPlain": "Benefits and team details.",
               "lists": [{"text": "Requirements", "content": "<ul><li>Python and Kubernetes</li></ul>"}]}
        result = verify_company(company("https://jobs.lever.co/example"), config(date_posted="Any time"), client=Client({url: [job]}))
        role = result["records"][0]
        self.assertTrue(role["eligible"])
        self.assertEqual(role["workplace_type"], "Remote")
        self.assertIn("Benefits and team details", role["description"])
        self.assertIn("Requirements Python and Kubernetes", role["description"])
        self.assertEqual(role["priority_tier"], 2)

    def test_lever_pagination_failure_keeps_first_page_and_cannot_claim_empty_or_complete(self):
        first = "https://api.lever.co/v0/postings/example?mode=json&limit=100&skip=0"
        second = first.replace("skip=0", "skip=100")
        jobs = [{"id": str(n), "text": "Staff Software Engineer", "hostedUrl": f"https://jobs.lever.co/example/{n}",
                 "categories": {"location": "San Francisco", "commitment": "Full-time"},
                 "descriptionPlain": "Hybrid engineering role with a complete description."} for n in range(100)]
        result = verify_company(company("https://jobs.lever.co/example"), config(date_posted="Any time"),
                                client=Client({first: jobs, second: TimeoutError("Page two timed out")}))
        self.assertEqual(len(result["records"]), 100)
        self.assertEqual(result["status"], "hiring")
        self.assertFalse(result["complete"])
        self.assertEqual(result["errors"][0]["code"], "network")

    def test_generic_jsonld_full_role_and_expired_role_are_distinct_from_company_closure(self):
        page = "https://example.test/careers/staff"
        job = {"@type": "JobPosting", "title": "Staff AI Engineer", "description": "<p>Complete role description.</p>",
               "jobLocation": {"address": {"addressLocality": "San Francisco", "addressRegion": "CA"}},
               "jobLocationType": "HYBRID", "employmentType": "FULL_TIME", "datePosted": datetime.now(timezone.utc).isoformat()}
        html = '<script type="application/ld+json">' + json.dumps(job) + "</script>"
        result = verify_company(company(page), config(), client=Client({page: html}))
        self.assertEqual(result["status"], "hiring")
        self.assertTrue(result["records"][0]["eligible"])
        job["validThrough"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        expired = '<script type="application/ld+json">' + json.dumps(job) + "</script>"
        result = verify_company(company(page), config(), client=Client({page: expired}))
        self.assertEqual(result["records"][0]["status"], "closed")
        self.assertIn("role_closed", result["records"][0]["exclusion_reasons"])
        self.assertEqual(result["status"], "unknown")

    def test_generic_html_listing_follows_detail_and_reads_full_description(self):
        board, detail = "https://example.test/careers", "https://example.test/careers/staff-systems"
        html = ('<main data-location="San Francisco" data-employment-type="Full-time" data-workplace-type="Hybrid">'
                '<h1>Staff Systems Engineer</h1><div class="job-description"><p>Full responsibilities.</p><p>Full requirements.</p></div>'
                '<a href="/apply">Apply now</a></main>')
        client = Client({board: '<a href="/careers/staff-systems">Staff Systems Engineer</a>', detail: html})
        result = verify_company(company(board), config(date_posted="Any time"), client=client)
        self.assertEqual(result["records"][0]["description"], "Full responsibilities. Full requirements.")
        self.assertEqual(result["records"][0]["career_url"], detail)
        self.assertTrue(result["records"][0]["eligible"])
        self.assertEqual(result["status"], "hiring")

    def test_malformed_posting_in_generic_board_keeps_valid_role_but_forbids_complete_closure(self):
        page = "https://example.test/careers"
        jobs = [{"@type": "JobPosting", "title": "Staff Backend Engineer", "description": "Complete description.", "url": page + "/one"},
                {"@type": "JobPosting", "title": "Principal Systems Engineer", "description": "No public role URL was provided."}]
        html = '<script type="application/ld+json">' + json.dumps(jobs) + "</script>"
        result = verify_company(company(page), config(), client=Client({page: html}))
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["status"], "hiring")
        self.assertFalse(result["complete"])
        self.assertEqual(result["errors"][0]["code"], "malformed_posting")

    def test_explicit_no_openings_is_proof_but_js_shell_and_inaccessible_sites_remain_unknown(self):
        page = "https://example.test/careers"
        cases = [("<p>No open positions at this time.</p>", "not_hiring", True),
                 ('<div id="app"></div>', "unknown", False),
                 (Response("Forbidden", page, 403), "unknown", False)]
        for body, status, complete in cases:
            with self.subTest(body=body):
                result = verify_company(company(page), config(), client=Client({page: body}))
                self.assertEqual(result["status"], status)
                self.assertEqual(result["complete"], complete)

    def test_public_renderer_is_optional_and_never_used_for_an_access_challenge(self):
        page = "https://example.test/careers"
        render = Mock(return_value='<p>No open positions.</p>')
        result = verify_company(company(page), config(), client=Client({page: '<div id="app"></div>'}), render=render)
        self.assertEqual(result["status"], "not_hiring")
        render.assert_called_once_with(page)
        render.reset_mock()
        result = verify_company(company(page), config(), client=Client({page: Response("Forbidden", page, 403)}), render=render)
        self.assertEqual(result["status"], "unknown")
        render.assert_not_called()

    def test_missing_official_site_and_unrelated_external_job_links_are_not_verified(self):
        result = verify_company(company(None, website=None), config(), client=Client({}))
        self.assertEqual(result["errors"][0]["code"], "missing_official_site")
        page = "https://example.test/careers"
        client = Client({page: '<a href="https://unrelated.test/jobs">Sponsored jobs</a>'})
        result = verify_company(company(page), config(), client=client)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(client.calls, [(page, 12)])


class CanonicalGateTests(unittest.TestCase):
    def role(self, **overrides):
        return role_record(company(), ashby_job(**overrides), ASHBY_URL)

    def test_bay_area_remote_us_and_hybrid_are_eligible_but_remote_europe_and_onsite_are_excluded(self):
        cases = [({"location": "Remote - United States", "workplaceType": "Remote"}, True, None),
                 ({"location": "Palo Alto", "workplaceType": "Hybrid"}, True, None),
                 ({"location": "Remote - Germany", "workplaceType": "Remote"}, False, "location_excluded"),
                 ({"location": "San Francisco", "workplaceType": "OnSite"}, False, "workplace_type_excluded"),
                 ({"location": "Remote", "workplaceType": "Remote"}, False, "unknown_location")]
        for fields, eligible, reason in cases:
            with self.subTest(fields=fields):
                role = evaluate_role(self.role(**fields), config())
                self.assertEqual(role["eligible"], eligible)
                if reason:
                    self.assertIn(reason, role["exclusion_reasons"])

    def test_unknown_arrangement_employment_and_missing_description_cannot_claim_eligibility(self):
        role = evaluate_role(self.role(workplaceType=None, employmentType=None, descriptionPlain=""), config())
        self.assertFalse(role["eligible"])
        self.assertIn("unknown_workplace_type", role["exclusion_reasons"])
        self.assertIn("unknown_employment_type", role["exclusion_reasons"])
        self.assertIn("missing_full_description", role["exclusion_reasons"])

    def test_explicit_hybrid_arrangement_takes_precedence_over_legacy_remote_boolean(self):
        role = evaluate_role(self.role(location="New York, United States", workplaceType="Hybrid", isRemote=True), config())
        self.assertEqual(role["workplace_type"], "Hybrid")
        self.assertIn("location_excluded", role["exclusion_reasons"])

    def test_technical_remote_cloud_words_and_employee_benefits_are_not_role_policy(self):
        role = evaluate_role(self.role(workplaceType=None, employmentType=None, isRemote=None,
                                      descriptionPlain="Build hybrid cloud and remote execution systems. Full-time employees receive benefits."), config())
        self.assertEqual(role["workplace_type"], "Unknown")
        self.assertEqual(role["employment_type"], "Unknown")
        self.assertFalse(role["eligible"])

    def test_changed_canonical_city_filter_cannot_match_only_a_shared_country(self):
        role = evaluate_role(self.role(location="New York, United States"), config(search_location="Seattle, United States"))
        self.assertIn("location_excluded", role["exclusion_reasons"])
        role = evaluate_role(self.role(location="Seattle, United States"), config(search_location="Seattle, United States"))
        self.assertTrue(role["eligible"])

    def test_description_citizenship_clearance_and_experience_gates_use_existing_values(self):
        role = evaluate_role(self.role(descriptionPlain="US Citizens must have security clearance and 8 years of experience."), config(current_experience=5))
        self.assertIn("description_exclusion:US Citizen", role["exclusion_reasons"])
        self.assertIn("security_clearance_required", role["exclusion_reasons"])
        self.assertIn("experience_excluded", role["exclusion_reasons"])
        allowed = evaluate_role(self.role(descriptionPlain="A master's degree and 7 years of experience."), config(current_experience=5, did_masters=True))
        self.assertTrue(allowed["eligible"])

    def test_company_exclusion_honors_existing_good_word_exceptions(self):
        employer = company(description="Example is a staffing agency for technology companies")
        role = role_record(employer, ashby_job(), ASHBY_URL)
        evaluated = evaluate_role(role, config())
        self.assertIn("company_description_exclusion:Staffing", evaluated["exclusion_reasons"])
        evaluated = evaluate_role(role_record(employer, ashby_job(), ASHBY_URL), config(about_company_good_words=["technology companies"]))
        self.assertTrue(evaluated["eligible"])

    def test_old_or_unknown_posting_date_does_not_satisfy_configured_recent_filter(self):
        old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        self.assertIn("posted_date_excluded", evaluate_role(self.role(publishedAt=old), config())["exclusion_reasons"])
        self.assertIn("unknown_posted_date", evaluate_role(self.role(publishedAt=None), config())["exclusion_reasons"])

    def test_expanded_modal_style_titles_are_allowed_and_sales_is_not(self):
        for title in ("Member of Technical Staff, Systems", "Member of Technical Staff, Inference", "Software Engineer, SDK", "Founding Engineer", "Principal Infrastructure Engineer"):
            with self.subTest(title=title):
                self.assertTrue(evaluate_role(self.role(title=title), config())["eligible"])
        self.assertIn("outside_role_families", evaluate_role(self.role(title="Strategic Account Executive"), config())["exclusion_reasons"])

    def test_company_size_and_confirmed_funding_priority_do_not_guess_unknown_stage(self):
        self.assertEqual(priority_tier(company(employee_count=50, funding_stage=None), "Staff Engineer"), 1)
        self.assertEqual(priority_tier(company(employee_count=None, funding_stage="Series B"), "Systems Engineer"), 2)
        self.assertEqual(priority_tier(company(employee_count="51-200", funding_stage=None), "Principal Engineer"), 1)
        self.assertEqual(priority_tier(company(employee_count=12, funding_stage="Seed"), "Founding Engineer"), 3)
        self.assertEqual(priority_tier(company(employee_count=None, funding_stage="Growth"), "Staff Engineer"), 4)
        self.assertEqual(priority_tier(company(), "Member of Technical Staff, Systems"), 2)
        self.assertEqual(priority_tier(company(), "Founding Engineer"), 3)

    def test_company_allowlist_supports_observed_name_aliases_but_never_matches_domain_aliases(self):
        employer = company(aliases=[{"name": "Example AI", "url": "https://example.test"}, "example.test", {"domain": "other.test"}])
        role = role_record(employer, ashby_job(), ASHBY_URL)
        self.assertTrue(evaluate_role(role, config(companies=["Example AI"]))["eligible"])
        role = role_record(employer, ashby_job(), ASHBY_URL)
        self.assertIn("company_excluded", evaluate_role(role, config(companies=["example.test"]))["exclusion_reasons"])

    def test_functional_role_url_is_stable_when_tracking_query_changes(self):
        first = self.role(jobUrl="https://jobs.ashbyhq.com/example/posting-1?utm_source=vc")
        second = self.role(jobUrl="https://jobs.ashbyhq.com/example/posting-1?utm_source=other")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["career_url"], "https://jobs.ashbyhq.com/example/posting-1")


if __name__ == "__main__":
    unittest.main()

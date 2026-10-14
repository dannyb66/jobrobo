"""Synthetic fixtures model each source's public, documented HTML/JSON format."""

import json
import unittest
from unittest.mock import Mock

from modules.job_pipeline.http import Document, FetchError, Page, embedded_json, fetch_page, public_url
from modules.job_pipeline.sources import SOURCE_URLS, discover_source, parse_companies


class Response:
    def __init__(self, value, url, status=200):
        self.text = value if isinstance(value, str) else json.dumps(value)
        self.url, self.status_code = url, status


class Client:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, timeout=None):
        self.calls.append((url, timeout))
        value = self.pages[url]
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, Response) else Response(value, url)


class SourceTests(unittest.TestCase):
    def discover(self, source, body, config=None, **kwargs):
        url = SOURCE_URLS[source]
        client = kwargs.pop("client", Client({url: body}))
        return discover_source(source, {"enrich_profiles": False, **(config or {})}, client=client, **kwargs)

    def test_greylock_public_company_cards_follow_profile_for_official_site(self):
        url = SOURCE_URLS["greylock"]
        profile = "https://greylock.com/jobs/portfolio-jobs/example-ai/"
        client = Client({
            url: '<a href="/jobs/portfolio-jobs/example-ai/"><span>Example AI</span><p>AI infrastructure company</p></a>',
            profile: '<h1>Example AI</h1><a href="https://example-ai.test/">Website</a>',
        })
        result = discover_source("greylock", {}, client=client)
        company = result["records"][0]
        self.assertEqual(company["name"], "Example AI")
        self.assertEqual(company["website"], "https://example-ai.test/")
        self.assertEqual(company["domain"], "example-ai.test")
        self.assertIsNone(company["employee_count"])
        self.assertIsNone(company["funding_stage"])
        self.assertEqual(company["sources"][0]["name"], "greylock")
        self.assertEqual(company["sources"][0]["url"], profile)
        self.assertEqual([url for url, _ in client.calls], [url, profile])

    def test_a16z_react_flight_company_data_keeps_provided_funding_and_headcount(self):
        payload = ["$", "Component", None, {"companies": [{"name": "Example Infra", "domain": "infra.test", "headcount": 84, "stage": "Series C", "id": "public-company-1"}]}]
        # Real Flight text frames can contain newlines immediately before JSON rows.
        flight = "1:Ta,Hello\nWorld2:" + json.dumps(payload) + "\n"
        html = "<script>self.__next_f.push(" + json.dumps([1, flight]) + ")</script>"
        result = self.discover("a16z", html)
        company = result["records"][0]
        self.assertEqual(company["name"], "Example Infra")
        self.assertEqual(company["employee_count"], 84)
        self.assertEqual(company["funding_stage"], "Series C")
        self.assertEqual(company["sources"][0]["external_id"], "public-company-1")

    def test_sequoia_portfolio_cards_are_companies_not_navigation_or_description(self):
        html = ('<a href="./our-companies">Our Companies</a>'
                '<a href="./companies/example"><h3>Example</h3><p>Builds AI systems</p></a>')
        result = self.discover("sequoia", html)
        self.assertEqual([record["name"] for record in result["records"]], ["Example"])
        self.assertEqual(result["records"][0]["profile_url"], "https://sequoiacap.com/companies/example")
        self.assertTrue(result["complete"])

    def test_yc_directory_uses_public_jobs_inertia_payload_then_company_profile(self):
        url, jobs = SOURCE_URLS["yc"], "https://www.ycombinator.com/jobs"
        profile = "https://www.ycombinator.com/companies/example"
        data = {"props": {"jobPostings": [{"id": 42, "companyName": "Example", "companyUrl": "/companies/example", "companyOneLiner": "Developer tools"}]}}
        html = '<div data-page=\'' + json.dumps(data) + "'></div>"
        company = {"props": {"company": {"name": "Example", "website": "https://example.test", "team_size": 72}}}
        client = Client({url: '<div id="app"></div>', jobs: html,
                         profile: '<div data-page=\'' + json.dumps(company) + "'></div>"})
        result = discover_source("yc", {}, client=client)
        self.assertEqual(result["records"][0]["domain"], "example.test")
        self.assertEqual(result["records"][0]["employee_count"], 72)
        self.assertEqual(result["records"][0]["description"], "Developer tools")
        self.assertEqual(len(client.calls), 3)

    def test_yc_rotating_sample_resumes_snapshot_without_repeating_offset_into_new_feed(self):
        url, jobs = SOURCE_URLS["yc"], "https://www.ycombinator.com/jobs"
        body = {"props": {"jobPostings": [{"companyName": "First", "companyUrl": "/companies/first"},
                                            {"companyName": "Second", "companyUrl": "/companies/second"}]}}
        client = Client({url: '<div id="app"></div>', jobs: '<div data-page=\'' + json.dumps(body) + "'></div>"})
        first = discover_source("yc", {"enrich_profiles": False}, limit=1, client=client)
        self.assertEqual(first["errors"][0]["code"], "partial_public_feed")
        self.assertTrue(first["cursor"]["sample_feed"])
        client.pages[jobs] = '<script type="application/json">{"companies":[{"name":"Changed","domain":"changed.test"}]}</script>'
        second = discover_source("yc", {"enrich_profiles": False}, limit=1, client=client, cursor=first["cursor"])
        self.assertEqual([first["records"][0]["name"], second["records"][0]["name"]], ["First", "Second"])
        self.assertEqual(len(client.calls), 2)
        self.assertFalse(second["complete"])
        self.assertIsNone(second["cursor"])

    def test_declared_larger_public_catalog_requires_rendering_instead_of_false_completion(self):
        html = ('<meta name="description" content="Browse 61 companies hiring now">'
                '<a href="/jobs/portfolio-jobs/example/"><h2>Example</h2></a>')
        result = self.discover("greylock", html)
        self.assertFalse(result["complete"])
        self.assertEqual(result["errors"][0]["code"], "partial_public_page")
        self.assertTrue(result["cursor"]["requires_render"])

    def test_hn_reads_latest_hiring_thread_and_preserves_comment_cursor(self):
        listing = {"hits": [{"title": "Ask HN: Who is hiring? (October)", "objectID": "100"}]}
        thread = {"children": [
            {"id": 101, "text": "Thread rules"},
            {"id": 102, "text": 'Example | REMOTE | <a href="https://example.test">Website</a> <a href="https://jobs.ashbyhq.com/example">Careers</a>'},
            {"id": 103, "text": 'Second | SF | <a href="https://second.test/careers">Jobs</a>'},
        ]}
        client = Client({SOURCE_URLS["hn"]: listing, "https://hn.algolia.com/api/v1/items/100": thread})
        first = discover_source("hn", {}, limit=1, client=client)
        self.assertEqual(first["records"][0]["name"], "Example")
        self.assertEqual(first["records"][0]["careers_url"], "https://jobs.ashbyhq.com/example")
        self.assertEqual(first["cursor"], {"thread_id": "100", "offset": 2})
        second = discover_source("hn", {}, cursor=first["cursor"], limit=1, client=client)
        self.assertEqual(second["records"][0]["name"], "Second")
        self.assertTrue(second["complete"])
        self.assertIsNone(second["cursor"])
        self.assertEqual([url for url, _ in client.calls].count(SOURCE_URLS["hn"]), 1)

    def test_hn_company_name_does_not_include_location_or_funding_notes(self):
        thread = {"children": [{"id": 101, "text": '<p>Example (Series B) | 75 employees | Remote US | <a href="https://example.test">Website</a></p>'}]}
        client = Client({"https://hn.algolia.com/api/v1/items/100": thread})
        result = discover_source("hn", {"thread_id": "100"}, client=client)
        self.assertEqual(result["records"][0]["name"], "Example")
        self.assertEqual(result["records"][0]["funding_stage"], "Series B")
        self.assertEqual(result["records"][0]["employee_count"], "75")

    def test_hiringcafe_public_jobposting_jsonld_discovers_hiring_organization(self):
        row = {"@type": "JobPosting", "title": "Staff Software Engineer", "hiringOrganization": {"@type": "Organization", "name": "Example", "url": "https://example.test"}}
        result = self.discover("hiringcafe", '<script type="application/ld+json">' + json.dumps(row) + "</script>")
        self.assertEqual(result["records"][0]["name"], "Example")
        self.assertEqual(result["records"][0]["domain"], "example.test")

    def test_wellfound_public_company_cards_strip_logo_decoration(self):
        html = '<a href="/company/example"><img alt="Avatar for Company logo for Example"><p>AI development tools</p></a>'
        result = self.discover("wellfound", html)
        self.assertEqual(result["records"][0]["name"], "Example")
        self.assertIsNone(result["records"][0]["domain"])

    def test_crunchbase_public_jsonld_preserves_known_count_without_guessing_stage(self):
        data = {"@type": "Organization", "name": "Example", "url": "https://example.test", "numberOfEmployees": {"value": "51-100"}}
        result = self.discover("crunchbase", '<script type="application/ld+json">' + json.dumps(data) + "</script>")
        self.assertEqual(result["records"][0]["employee_count"], "51-100")
        self.assertIsNone(result["records"][0]["funding_stage"])

    def test_restricted_sources_do_not_invoke_renderer_or_return_fake_empty_completion(self):
        for source in ("wellfound", "crunchbase", "hiringcafe"):
            with self.subTest(source=source):
                render = Mock(return_value="<div>Would bypass challenge</div>")
                result = self.discover(source, Response("Forbidden", SOURCE_URLS[source], 403), render=render)
                self.assertEqual(result["errors"][0]["code"], "restricted")
                self.assertFalse(result["complete"])
                self.assertEqual(result["records"], [])
                render.assert_not_called()

    def test_public_page_can_use_injected_renderer_when_structure_requires_js(self):
        render = Mock(return_value='<script type="application/json">{"companies":[{"name":"Example","domain":"example.test"}]}</script>')
        result = self.discover("sequoia", '<div id="app"></div>', render=render)
        self.assertEqual(result["records"][0]["name"], "Example")
        render.assert_called_once_with(SOURCE_URLS["sequoia"])

    def test_source_page_offset_and_next_link_resume_without_repeating_selected_companies(self):
        url = SOURCE_URLS["a16z"]
        second_url = url + "?page=2"
        client = Client({url: {"companies": [{"name": "First", "domain": "first.test"}, {"name": "Second", "domain": "second.test"}], "next_url": second_url},
                         second_url: {"companies": [{"name": "Third", "domain": "third.test"}]}})
        first = self.discover("a16z", None, client=client, limit=1)
        second = self.discover("a16z", None, client=client, limit=1, cursor=first["cursor"])
        third = self.discover("a16z", None, client=client, limit=1, cursor=second["cursor"])
        self.assertEqual([part["records"][0]["name"] for part in (first, second, third)], ["First", "Second", "Third"])
        self.assertTrue(third["complete"])
        self.assertEqual(len({part["records"][0]["id"] for part in (first, second, third)}), 3)

    def test_profile_failure_keeps_discovered_company_and_explicit_partial_error(self):
        url = SOURCE_URLS["sequoia"]
        profile = "https://sequoiacap.com/companies/example"
        client = Client({url: '<a href="/companies/example"><h3>Example</h3></a>', profile: TimeoutError("profile timed out")})
        result = discover_source("sequoia", {}, client=client)
        self.assertEqual(result["records"][0]["name"], "Example")
        self.assertEqual(result["errors"][0]["code"], "network")
        self.assertFalse(result["complete"])

    def test_company_id_survives_later_profile_enrichment_without_domain_only_duplicates(self):
        url = SOURCE_URLS["wellfound"]
        profile = "https://wellfound.com/company/example"
        listing = '<a href="/company/example"><h2>Example</h2></a>'
        first = discover_source("wellfound", {}, client=Client({url: listing, profile: Response("Forbidden", profile, 403)}))
        second = discover_source("wellfound", {}, client=Client({url: listing, profile: '<a href="https://example.test">Website</a>'}))
        self.assertEqual(first["records"][0]["id"], second["records"][0]["id"])
        self.assertIsNone(first["records"][0]["domain"])
        self.assertEqual(second["records"][0]["domain"], "example.test")

    def test_rate_limit_preserves_cursor_for_retry(self):
        cursor = {"url": SOURCE_URLS["yc"], "offset": 4}
        result = self.discover("yc", Response("Slow down", SOURCE_URLS["yc"], 429), cursor=cursor)
        self.assertEqual(result["cursor"], cursor)
        self.assertTrue(result["errors"][0]["retryable"])
        self.assertEqual(result["errors"][0]["code"], "rate_limited")

    def test_no_schema_is_unknown_and_source_and_limit_are_validated(self):
        result = self.discover("wellfound", "<h1>Sign in</h1>")
        self.assertEqual(result["errors"][0]["code"], "import_required")
        self.assertFalse(result["complete"])
        self.assertEqual(discover_source("unsupported", {})["errors"][0]["code"], "unsupported_source")
        with self.assertRaises(ValueError):
            discover_source("yc", {}, limit=0)

    def test_duplicate_rendered_cards_and_structured_records_keep_richer_company(self):
        html = ('<script type="application/json">{"companies":[{"name":"Example","domain":"example.test","headcount":75}]}</script>'
                '<a href="/companies/example"><h2>Example</h2></a><a href="/jobs/other">2,491 jobs</a>')
        result = self.discover("a16z", html)
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["employee_count"], 75)


class PublicHTTPTests(unittest.TestCase):
    def test_requests_are_bounded_and_access_challenge_is_restricted(self):
        url = "https://public.test/companies"
        client = Client({url: "<title>Just a moment...</title>"})
        with self.assertRaises(FetchError) as raised:
            fetch_page(url, client, timeout=7)
        self.assertEqual(raised.exception.code, "restricted")
        self.assertEqual(client.calls, [(url, 7)])

    def test_private_urls_credentials_and_invalid_ports_are_rejected(self):
        for url in ("file:///tmp/secrets", "https://localhost/x", "https://127.0.0.1/x", "https://10.0.0.1/x", "https://foo.internal/x", "https://u:p@public.test", "https://public.test:bad"):
            with self.subTest(url=url):
                self.assertIsNone(public_url(url))
                with self.assertRaises(FetchError):
                    fetch_page(url, Client({}))

    def test_embedded_json_is_read_as_data_and_never_evaluates_scripts(self):
        text = '<script>window.companyData={"companies":[{"name":"Example","domain":"example.test"}]}; throw new Error("Never execute")</script>'
        values = embedded_json(Document(text))
        self.assertEqual(values[0]["companies"][0]["name"], "Example")


if __name__ == "__main__":
    unittest.main()

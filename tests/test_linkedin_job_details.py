"""Sanitized modern detail fixtures; readers never open application forms."""

from datetime import datetime, timezone
from types import SimpleNamespace
import re
import unittest
from unittest.mock import Mock
from selenium.common.exceptions import StaleElementReferenceException

from modules.linkedin_job_details import (
    DETAIL_ROOT, EASY_APPLY, modern_details_ready, modern_details_root,
    modern_easy_apply_button, read_modern_company, read_modern_description, read_modern_details, modern_description_ready,
)
from test_search_runner import extract_functions, spec
from test_linkedin_modern_search import DOMBrowser, DOMElement
from lxml import etree


class Node:
    def __init__(self, text="", *, attrs=None, children=None, visible=True, enabled=True):
        self.text = text
        self.attrs = dict(attrs or {})
        self.children = dict(children or {})
        self.visible, self.enabled = visible, enabled
        self.click = Mock()

    def get_attribute(self, name):
        return self.attrs.get(name)

    def find_elements(self, by, selector):
        return self.children.get(selector, [])

    def is_displayed(self):
        return self.visible

    def is_enabled(self):
        return self.enabled


class HeaderComparisonTests(unittest.TestCase):
    def test_whitespace_difference_preserves_identity(self):
        from modules.linkedin_job_details import header_identity_matches
        self.assertTrue(header_identity_matches({'title': 'Principal Engineer  - GPUaaS ', 'company': 'CyberCoders'},
                                                'Principal Engineer - GPUaaS', 'CyberCoders'))

    def test_real_title_or_employer_difference_is_rejected(self):
        from modules.linkedin_job_details import header_identity_matches
        header = {'title': 'Principal Engineer', 'company': 'CyberCoders'}
        self.assertFalse(header_identity_matches(header, 'Staff Engineer', 'CyberCoders'))
        self.assertFalse(header_identity_matches(header, 'Principal Engineer', 'Another company'))


class DetailBrowser:
    """Keep only observed semantic hooks, excluding all account/tracking data."""

    def __init__(self, job_id="123", location="San Francisco, CA"):
        self.current_url = "https://www.linkedin.com/jobs/view/" + job_id + "/"
        self.has_view_marker = True
        self.hidden_exclusion = Node("", attrs={"textContent": "US Citizen required. Security clearance required."})
        self.box = Node("Build production infrastructure… more", attrs={"textContent": "Build production infrastructure. US Citizen required. Security clearance required. … more"}, children={
            "p": [Node("Build production infrastructure.", attrs={"textContent": "Build production infrastructure."}), self.hidden_exclusion],
        })
        self.job = Node(attrs={"id": "JobDetails_AboutTheJob_" + job_id}, children={"[data-testid='expandable-text-box']": [self.box]})
        self.company = Node("About the company\nExample", attrs={"textContent": "About the company Example Staffing and Recruiting. Full employer description."})
        anchor = Node("Example", attrs={"href": "https://www.linkedin.com/company/example/life/", "componentkey": "auto-binding-fixture-" + job_id})
        self.label = Node(attrs={"aria-label": "Company, Example."}, children={"ancestor::a[1]": [anchor]})
        self.apply = Node("Easy Apply")
        self.root = Node(children={
            "[id^='JobDetails_AboutTheJob_']": [self.job],
            "[id^='JobDetails_AboutTheCompany_']": [self.company],
            "[aria-label^='Company,']": [self.label],
            "p": [Node("Example"), Node("Staff Platform Engineer"), Node(location + " · 1 week ago · Over 100 applicants"), Node("Promoted by hirer")],
            "a[href]": [Node(value, attrs={"href": self.current_url}) for value in ("Hybrid", "Full-time")],
            EASY_APPLY: [self.apply],
        })
        self.job.children["ancestor::*[.//*[starts-with(@aria-label,'Company,')]][1]"] = [self.root]

    def find_elements(self, by, selector):
        if selector == DETAIL_ROOT:
            return [self.root] if self.has_view_marker else []
        if selector == "[id^='JobDetails_AboutTheJob_']":
            return [self.job]
        if selector == "[data-view-name='job-detail-page'], [id^='JobDetails_AboutTheJob_']":
            return [self.root, self.job] if self.has_view_marker else [self.job]
        return []


class ModernDetailReaderTests(unittest.TestCase):
    def setUp(self):
        self.browser = DetailBrowser()

    def test_header_uses_semantic_company_label_paragraphs_and_exact_job_chips_without_h1(self):
        details = read_modern_details(self.browser, "123")
        self.assertEqual({key: value for key, value in details.items() if key != "root"}, {
            "id": "123", "title": "Staff Platform Engineer", "company": "Example",
            "company_url": "https://www.linkedin.com/company/example/life/", "location": "San Francisco, CA",
            "workplace_type": "Hybrid", "employment_type": "Full-time", "posted_text": "1 week ago",
        })

    def test_collapsed_description_reads_hidden_paragraph_exclusions_without_clicking_more(self):
        description = read_modern_description(self.browser, "123")
        self.assertIn("US Citizen required", description)
        self.assertIn("Security clearance required", description)
        self.assertNotIn("more", description)
        self.box_click_not_reached()

    def box_click_not_reached(self):
        self.browser.box.click.assert_not_called()
        self.browser.apply.click.assert_not_called()

    def test_employer_gate_receives_entire_scoped_company_section(self):
        company, root = read_modern_company(self.browser, "123")
        self.assertIn("Staffing and Recruiting", company)
        self.assertIs(root, self.browser.root)

    def test_full_description_preserves_all_list_table_and_hidden_block_text(self):
        self.browser.box.attrs["innerHTML"] = """<p>Build infrastructure.</p>
            <ul><li style="display:none">US Citizen required.</li><li>Security <strong>clearance</strong> required.</li></ul>
            <table><tr><td>Experience</td><td>10 years required</td></tr></table>
            <div>Develop reliable platforms.</div><p>Master&#39;s degree preferred.</p>
            <button data-testid="expandable-text-button"><span>… more</span></button>"""
        description = read_modern_description(self.browser, "123")
        self.assertIn("US Citizen required.", description)
        self.assertIn("Security clearance required.", description)
        self.assertIn("Experience 10 years required", description)
        self.assertIn("Develop reliable platforms.", description)
        self.assertIn("Master's degree preferred.", description)
        self.assertNotIn("more", description)
        self.assertIn("infrastructure.\nUS Citizen", description)

    def test_stale_job_id_and_ambiguous_panes_fail_before_reading_or_applying(self):
        for reader in (read_modern_details, read_modern_description, read_modern_company, modern_easy_apply_button):
            with self.subTest(reader=reader), self.assertRaises(ValueError):
                reader(self.browser, "999")
        self.assertFalse(modern_details_ready(self.browser, "999"))
        self.browser.find_elements = lambda *_: [self.browser.root, self.browser.root]
        with self.assertRaises(ValueError):
            modern_details_root(self.browser)
        self.browser.apply.click.assert_not_called()

    def test_missing_full_description_or_company_evidence_is_not_a_match(self):
        self.browser.job.children.clear()
        with self.assertRaises(ValueError):
            read_modern_description(self.browser)
        self.browser.root.children["[id^='JobDetails_AboutTheCompany_']"] = []
        with self.assertRaises(ValueError):
            read_modern_company(self.browser)

    def test_description_readiness_waits_for_text_after_easy_apply_is_available(self):
        boxes = self.browser.job.children.pop("[data-testid='expandable-text-box']")
        self.assertTrue(modern_easy_apply_button(self.browser, '123'))
        self.assertFalse(modern_description_ready(self.browser, '123'))
        self.browser.job.children["[data-testid='expandable-text-box']"] = boxes
        self.assertIn('Build production infrastructure', modern_description_ready(self.browser, '123'))
        self.assertFalse(modern_description_ready(self.browser, '999'))
        self.browser.apply.click.assert_not_called()

    def test_company_identity_requires_linkedin_company_url(self):
        self.browser.label.children["ancestor::a[1]"][0].attrs["href"] = "https://example.com/company/example"
        with self.assertRaises(ValueError):
            read_modern_details(self.browser)

    def test_plain_employer_logo_is_bound_to_exact_job_and_header_name(self):
        self.browser.root.children["[aria-label^='Company,']"] = []
        self.browser.root.children["[aria-label^='Company logo for,']"] = [
            Node(attrs={'aria-label': 'Company logo for, Example.'})]
        details = read_modern_details(self.browser, '123')
        self.assertEqual(details['company'], 'Example')
        self.assertIsNone(details['company_url'])
        self.browser.root.children['p'][0] = Node('Unrelated Employer')
        with self.assertRaises(ValueError):
            read_modern_details(self.browser, '123')

    def test_header_for_another_job_cannot_pass_with_a_retained_description_section(self):
        self.browser.label.children["ancestor::a[1]"][0].attrs["componentkey"] = "auto-binding-fixture-999"
        self.assertFalse(modern_details_ready(self.browser, "123"))
        with self.assertRaises(ValueError):
            read_modern_details(self.browser, "123")

    def test_stale_header_paragraph_retries_on_next_poll_without_matching_another_job(self):
        class StaleOnceParagraph(Node):
            def __init__(self, value):
                self.value, self.reads = value, 0

            @property
            def text(self):
                self.reads += 1
                if self.reads == 1:
                    raise StaleElementReferenceException("React replaced the header paragraph")
                return self.value

        self.browser.root.children["p"][0] = StaleOnceParagraph("Example")
        self.assertFalse(modern_details_ready(self.browser, "123"))
        self.assertEqual(modern_details_ready(self.browser, "123")["id"], "123")
        self.assertFalse(modern_details_ready(self.browser, "999"))

    def test_header_reader_does_not_touch_hydrating_description_or_promotion_paragraphs(self):
        class UnrelatedHydratingParagraph:
            @property
            def text(self):
                raise AssertionError("Reader touched an unrelated paragraph")

        self.browser.root.children["p"] = self.browser.root.children["p"][:3] + [UnrelatedHydratingParagraph()]
        self.assertEqual(read_modern_details(self.browser, "123")["title"], "Staff Platform Engineer")

    def test_readiness_does_not_hide_unrelated_browser_errors(self):
        self.browser.find_elements = Mock(side_effect=RuntimeError("Unexpected driver failure"))
        with self.assertRaisesRegex(RuntimeError, "Unexpected driver failure"):
            modern_details_ready(self.browser, "123")

    def test_similar_job_chips_cannot_supply_selected_jobs_missing_metadata(self):
        for href in ("https://www.linkedin.com/jobs/view/999/",
                     "https://www.linkedin.com/jobs/search-results/?currentJobId=999",
                     "https://www.linkedin.com/jobs/search/?currentJobId=999"):
            with self.subTest(href=href):
                self.browser.root.children["a[href]"] = [Node(value, attrs={"href": href}) for value in ("Remote", "Full-time")]
                details = read_modern_details(self.browser)
                self.assertEqual(details["workplace_type"], "Unknown")
                self.assertEqual(details["employment_type"], "Unknown")

    def test_same_job_search_route_badges_supply_workplace_and_employment(self):
        for route in ("search-results", "search"):
            with self.subTest(route=route):
                link = "https://www.linkedin.com/jobs/" + route + "/?keywords=platform&currentJobId=123"
                self.browser.root.children["a[href]"] = [Node(value, attrs={"href": link}) for value in ("Remote", "Full-time")]
                details = read_modern_details(self.browser, "123")
                self.assertEqual((details["workplace_type"], details["employment_type"]), ("Remote", "Full-time"))

    def test_offsite_or_unrelated_routes_cannot_supply_badge_evidence(self):
        self.browser.root.children["a[href]"] = [
            Node("Remote", attrs={"href": "https://example.com/jobs/search-results/?currentJobId=123"}),
            Node("Full-time", attrs={"href": "https://www.linkedin.com/feed/?currentJobId=123"}),
        ]
        details = read_modern_details(self.browser, "123")
        self.assertEqual((details["workplace_type"], details["employment_type"]), ("Unknown", "Unknown"))

    def test_easy_apply_reader_is_scoped_enabled_and_never_clicks(self):
        self.assertIs(modern_easy_apply_button(self.browser, "123"), self.browser.apply)
        self.browser.apply.enabled = False
        self.assertIsNone(modern_easy_apply_button(self.browser, "123"))
        self.browser.apply.click.assert_not_called()

    def test_stripped_instrumentation_uses_selected_section_and_bounded_header(self):
        self.browser.has_view_marker = False
        self.assertEqual(read_modern_details(self.browser, "123")["company"], "Example")
        self.assertIn("US Citizen", read_modern_description(self.browser, "123"))
        self.assertIn("Staffing", read_modern_company(self.browser, "123")[0])
        self.assertIs(modern_easy_apply_button(self.browser, "123"), self.browser.apply)
        self.browser.apply.click.assert_not_called()


class ModernDetailRunnerTests(unittest.TestCase):
    def setUp(self):
        self.browser = DetailBrowser(location="Covington, LA")
        self.namespace = {
            "driver": self.browser, "re": re, "By": SimpleNamespace(CSS_SELECTOR="css selector", XPATH="xpath"),
            "print_lg": Mock(), "scroll_to_view": Mock(), "buffer": Mock(), "click_gap": 0,
            "WebDriverWait": lambda browser, *_: SimpleNamespace(until=lambda predicate: predicate(browser)),
            "calculate_date_posted": lambda *_: datetime(2026, 10, 7, tzinfo=timezone.utc),
        }

    def test_modern_card_click_revalidates_exact_live_header_instead_of_saved_card_location(self):
        control = Node()
        self.namespace["read_search_card"] = lambda card: {"id": "123", "title": "Staff Platform Engineer", "company": "Example",
            "location": "San Francisco, CA", "workplace_type": "Hybrid", "title_element": control}
        extract_functions(self.namespace, "get_job_main_details")
        card = SimpleNamespace(get_dom_attribute=lambda *_: None)
        details = self.namespace["get_job_main_details"](card, set(), set(), read_only=True)
        self.assertEqual(details[3:5], ("Covington, LA", "Hybrid"))
        control.click.assert_called_once()
        self.browser.apply.click.assert_not_called()

    def test_selected_live_reader_uses_modern_metadata_and_preserves_eligibility_inputs(self):
        extract_functions(self.namespace, "selected_live_details")
        search = spec("selected")
        search.pipeline_context = {"company": {"id": "example", "name": "Example", "aliases": []}}
        search.filters_snapshot["intent"] = {"on_site": ["Hybrid", "Remote"]}
        record = {"linkedin_id": "123"}
        details = self.namespace["selected_live_details"](record, search)
        self.assertEqual(details[3:5], ("Covington, LA", "Hybrid"))
        self.assertEqual(record["_live_details"]["employment_type"], "Full-time")
        self.assertEqual(record["_live_details"]["locations"], ["Covington, LA"])
        self.browser.apply.click.assert_not_called()

    def test_existing_description_exclusion_detects_collapsed_hidden_requirement(self):
        self.namespace.update(bad_words=["US Citizen"], security_clearance=False, did_masters=True,
                              current_experience=-1, extract_years_of_experience=lambda *_: 0)
        extract_functions(self.namespace, "get_job_description")
        description, _, skip, reason, _ = self.namespace["get_job_description"]()
        self.assertTrue(skip)
        self.assertEqual(reason, "Found a Bad Word in About Job")
        self.assertIn("US Citizen", description)

    def test_runner_waits_for_description_instead_of_skipping_hydrating_job(self):
        self.namespace.update(bad_words=[], security_clearance=True, did_masters=False,
                              current_experience=-1, extract_years_of_experience=lambda *_: 0)
        boxes = self.browser.job.children.pop("[data-testid='expandable-text-box']")
        def wait(browser, timeout):
            def until(predicate):
                self.assertFalse(predicate(browser))
                browser.job.children["[data-testid='expandable-text-box']"] = boxes
                return predicate(browser)
            return SimpleNamespace(until=until)
        self.namespace['WebDriverWait'] = wait
        extract_functions(self.namespace, 'get_job_description')
        description, _, skip, _, _ = self.namespace['get_job_description']()
        self.assertIn('Build production infrastructure', description)
        self.assertFalse(skip)

    def test_runner_readers_detect_modern_details_without_view_instrumentation(self):
        self.browser.has_view_marker = False
        self.namespace.update(bad_words=["US Citizen"], security_clearance=False, did_masters=True,
                              current_experience=-1, extract_years_of_experience=lambda *_: 0)
        extract_functions(self.namespace, "get_job_description", "selected_live_details")
        self.assertTrue(self.namespace["get_job_description"]()[2])
        search = spec("selected")
        search.pipeline_context = {"company": {"id": "example", "name": "Example", "aliases": []}}
        record = {"linkedin_id": "123"}
        details = self.namespace["selected_live_details"](record, search)
        self.assertEqual(details[3], "Covington, LA")
        self.assertEqual(record["_live_details"]["workplace_type"], "Hybrid")
        self.browser.apply.click.assert_not_called()

    def test_missing_modern_description_skips_instead_of_reusing_unknown_legacy_text(self):
        self.namespace.update(bad_words=[], security_clearance=False, did_masters=True,
                              current_experience=-1, extract_years_of_experience=lambda *_: 0)
        self.browser.job.children.clear()
        extract_functions(self.namespace, "get_job_description")
        self.assertEqual(self.namespace["get_job_description"]()[2:4], (True, "Full modern job description unavailable"))

    def test_company_exclusion_uses_full_modern_section_and_existing_exception_rules(self):
        self.namespace.update(about_company_bad_words=["Staffing"], about_company_good_words=[])
        extract_functions(self.namespace, "check_blacklist")
        rejected, companies = set(), set()
        with self.assertRaises(ValueError):
            self.namespace["check_blacklist"](rejected, "123", "Example", companies)
        self.assertEqual(rejected, {"123"})
        self.assertEqual(companies, {"Example"})
        self.namespace["about_company_good_words"] = ["Example"]
        self.namespace["check_blacklist"](set(), "123", "Example", set())


class DetailDOMElement(DOMElement):
    def get_attribute(self, name):
        if name == "textContent":
            return "".join(self.node.itertext())
        return super().get_attribute(name)


class DetailDOMBrowser(DOMBrowser):
    def __init__(self):
        # Minimized from the observed React DOM. XML preserves its existing
        # nested anchors/paragraphs instead of reparsing them as new HTML.
        self.root = etree.fromstring("""<main>
          <div data-view-name="job-detail-page">
            <div id="JobDetails_ManageJobBanner_123"/>
            <a componentkey="auto-binding-fixture-123" href="https://www.linkedin.com/company/example/life/">
              <div aria-label="Company, Example."><p><a href="https://www.linkedin.com/company/example/life/">Example</a></p></div>
            </a>
            <p>Staff Platform Engineer<span> </span><a href="#"><span aria-label="Verified job"/></a></p>
            <p><span>San Francisco, CA</span> · <span>1 week ago</span> · <span>Over 100 applicants</span></p>
            <a href="https://www.linkedin.com/jobs/view/123/"><span>Hybrid</span></a>
            <a href="https://www.linkedin.com/jobs/view/123/"><span>Full-time</span></a>
            <button data-view-name="job-apply-button" aria-label="Easy Apply to this job">Easy Apply</button>
            <div id="JobDetails_AboutTheJob_123"><h2>About the job</h2><p>
              <span data-testid="expandable-text-box"><p>Build production infrastructure.</p>
                <p style="display:none">US Citizen required after the collapsed preview.</p>
                <button data-testid="expandable-text-button" aria-hidden="true">… more</button>
              </span></p></div>
            <div id="JobDetails_AboutTheCompany_123"><h2>About the company</h2>
              <p>Staffing and Recruiting</p><span data-testid="expandable-text-box">Full employer description.</span></div>
          </div>
          <aside><p>Another employer</p><a href="https://www.linkedin.com/jobs/view/999/">Remote</a></aside>
        </main>""")
        self.current_url = "https://www.linkedin.com/jobs/view/123/"
        self.clicks, self.navigations = [], []
        for index, node in enumerate(self.root.iter()):
            node.set("data-fixture-id", str(index))

    def query(self, root, by, selector):
        return [DetailDOMElement(self, element.node) for element in super().query(root, by, selector)]


class ObservedModernDetailDOMTests(unittest.TestCase):
    def test_observed_semantic_selectors_read_header_full_description_and_employer_without_actions(self):
        browser = DetailDOMBrowser()
        details = read_modern_details(browser, "123")
        self.assertEqual((details["company"], details["title"], details["location"]),
                         ("Example", "Staff Platform Engineer", "San Francisco, CA"))
        self.assertEqual(details["workplace_type"], "Hybrid")
        self.assertIn("US Citizen", read_modern_description(browser, "123"))
        self.assertNotIn("more", read_modern_description(browser, "123"))
        self.assertIn("Staffing", read_modern_company(browser, "123")[0])
        self.assertIsNotNone(modern_easy_apply_button(browser, "123"))
        self.assertEqual(browser.clicks, [])
        self.assertEqual(browser.navigations, [])

    def test_retained_description_with_new_employer_header_is_unready_in_actual_dom(self):
        browser = DetailDOMBrowser()
        browser.root.xpath("//*[@componentkey]")[0].set("componentkey", "auto-binding-fixture-999")
        self.assertFalse(modern_details_ready(browser, "123"))
        self.assertEqual(browser.clicks, [])

    def test_same_job_search_pane_badge_links_are_read_from_actual_dom(self):
        browser = DetailDOMBrowser()
        browser.current_url = "https://www.linkedin.com/jobs/search-results/?keywords=platform&currentJobId=123"
        for anchor in browser.root.xpath("//a[contains(@href,'/jobs/view/123/')]"):
            anchor.set("href", browser.current_url)
        details = read_modern_details(browser, "123")
        self.assertEqual((details["workplace_type"], details["employment_type"]), ("Hybrid", "Full-time"))
        self.assertEqual(browser.clicks, [])

    def test_stripping_all_view_markers_keeps_semantic_detail_readers_scoped(self):
        browser = DetailDOMBrowser()
        for node in browser.root.iter():
            node.attrib.pop("data-view-name", None)
        self.assertEqual(browser.root.xpath("//*[@data-view-name]"), [])
        details = read_modern_details(browser, "123")
        self.assertEqual((details["id"], details["company"], details["workplace_type"]), ("123", "Example", "Hybrid"))
        self.assertIn("US Citizen", read_modern_description(browser, "123"))
        self.assertIn("Staffing", read_modern_company(browser, "123")[0])
        self.assertIsNotNone(modern_easy_apply_button(browser, "123"))
        self.assertFalse(modern_details_ready(browser, "999"))
        self.assertEqual(browser.clicks, [])

    def test_requirements_in_hidden_lists_outside_paragraphs_reach_existing_exclusion_gates(self):
        for stripped in (False, True):
            with self.subTest(stripped=stripped):
                browser = DetailDOMBrowser()
                box = browser.root.xpath("//*[@data-testid='expandable-text-box']")[0]
                for child in list(box):
                    box.remove(child)
                box.append(etree.fromstring("""<div><p>Build infrastructure.</p>
                  <ul><li style="display:none">US Citizen required.</li><li>Security clearance required.</li></ul>
                  <table><tr><td>Experience</td><td>10 years required</td></tr></table>
                  <button data-testid="expandable-text-button">… more</button></div>"""))
                for index, node in enumerate(browser.root.iter()):
                    node.set("data-fixture-id", str(index))
                    if stripped:
                        node.attrib.pop("data-view-name", None)
                namespace = dict(driver=browser, bad_words=["US Citizen"], security_clearance=False,
                                 did_masters=True, current_experience=-1, extract_years_of_experience=lambda *_: 10,
                                 WebDriverWait=lambda driver, *_: SimpleNamespace(until=lambda condition: condition(driver)),
                                 print_lg=Mock())
                extract_functions(namespace, "get_job_description")
                description, _, skip, reason, _ = namespace["get_job_description"]()
                self.assertIn("US Citizen required.", description)
                self.assertIn("Security clearance required.", description)
                self.assertIn("Experience 10 years required", description)
                self.assertNotIn("more", description)
                self.assertTrue(skip)
                self.assertEqual(reason, "Found a Bad Word in About Job")
                namespace["bad_words"] = []
                self.assertEqual(namespace["get_job_description"]()[3], "Asking for Security clearance")
                self.assertEqual(browser.clicks, [])


if __name__ == "__main__":
    unittest.main()

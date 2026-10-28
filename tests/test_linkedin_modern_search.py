"""Replay semantic LinkedIn search DOM, without browser or application actions.

Install fixture dependencies with ``pip install -r requirements-dev.txt``.
XPath/CSS selectors run against sanitized markup. Click hooks change public UI
state; they do not match selector strings or fabricate successful verification.
"""

from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
import unittest

from bs4 import BeautifulSoup
from lxml import html, etree

from modules.search_planner import SearchSpec

FIXTURES = Path(__file__).parent / "fixtures"


class DOMElement:
    def __init__(self, browser, node):
        self.browser, self.node = browser, node
        self.id = node.get("data-fixture-id")

    @property
    def text(self):
        return " ".join(self.node.itertext()).strip()

    def get_attribute(self, name):
        if name in {"innerHTML", "outerHTML"}:
            return etree.tostring(self.node, encoding="unicode", method="html")
        return self.node.get(name)

    get_dom_attribute = get_attribute

    def is_displayed(self):
        if self.node.get("data-display-contents") == "true":
            return False
        return not any(n.get("hidden") is not None or "display:none" in n.get("style", "").replace(" ", "")
                       for n in [self.node, *self.node.iterancestors()])

    def is_enabled(self):
        return self.node.get("disabled") is None and self.node.get("aria-disabled") != "true"

    def is_selected(self):
        # The observed role control is authoritative; its native child is not.
        return self.node.get("checked") is not None

    def find_elements(self, by, selector):
        return self.browser.query(self.node, by, selector)

    def find_element(self, by, selector):
        found = self.find_elements(by, selector)
        if not found:
            from selenium.common.exceptions import NoSuchElementException
            raise NoSuchElementException(selector)
        return found[0]

    def click(self):
        self.browser.click(self.node)

    def clear(self):
        self.node.set("value", "")
        self.node.text = "" if self.node.get("contenteditable") else self.node.text

    def send_keys(self, *keys):
        self.browser.type_into(self.node, "".join(keys))


class DOMBrowser:
    def __init__(self, markup=None):
        self.root = html.fromstring(markup or (FIXTURES / "linkedin_modern_results.html").read_text())
        self.current_url = "https://www.linkedin.com/jobs/search-results/?keywords=old&geoId=90000084"
        self.session_id = "fixture-session"
        self.clicks, self.navigations = [], []
        for index, node in enumerate(self.root.iter()):
            if isinstance(node.tag, str):
                node.set("data-fixture-id", str(index))

    def query(self, root, by, selector):
        if by == "xpath":
            nodes = root.xpath(selector)
        elif by == "css selector":
            soup = BeautifulSoup(etree.tostring(root, encoding="unicode"), "html.parser")
            ids = [node.get("data-fixture-id") for node in soup.select(selector)]
            nodes = [n for n in root.iter() if n.get("data-fixture-id") in ids]
        elif by == "tag name":
            nodes = root.findall(".//" + selector)
        elif by == "id":
            nodes = root.xpath(".//*[@id=$wanted]", wanted=selector)
        else:
            raise AssertionError(f"Unsupported fixture locator: {by}")
        return [DOMElement(self, node) for node in nodes if isinstance(node, etree._Element)]

    def find_elements(self, by, selector):
        return self.query(self.root, by, selector)

    def find_element(self, by, selector):
        return DOMElement(self, self.root).find_element(by, selector)

    def execute_script(self, script, *args):
        if "document.documentElement.lang" in script:
            return "en-US"
        if "click" in script and args:
            return args[0].click()
        if "textContent" in script and args:
            return args[0].text
        return None

    def click(self, node):
        self.clicks.append((node.get("role"), node.get("aria-label"), node.get("data-view-name")))

    def type_into(self, node, value):
        if value == '\ue004':  # Tab blurs a field; it is not literal form data.
            return
        if value == "\ue00c":
            for submit in self.root.xpath("//a[normalize-space(.)='Show results']"):
                if DOMElement(self, submit).is_displayed():
                    menus = submit.xpath("ancestor::*[.//*[@role='radio' or @role='checkbox'][not(starts-with(@aria-label,'Filter by '))]][1]")
                    if menus:
                        menus[0].set("hidden", "")
            return
        if value in {"\ue03da", "\ue009a"}:
            self._select_all = node
            return
        if value == "\ue003" and getattr(self, "_select_all", None) is node:
            node.set("value", "")
            node.text = ""
            self._select_all = None
            return
        node.set("value", node.get("value", "") + value.replace("\ue007", ""))
        if "\ue007" in value:
            parsed = urlsplit(self.current_url)
            params = parse_qs(parsed.query)
            params["keywords"] = [node.get("value")]
            self.current_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params, doseq=True), ""))

    def get(self, url):
        self.navigations.append(url)
        self.current_url = url
        prompt = self.root.xpath("//*[@componentkey='semanticSearchBox']")
        if prompt:
            prompt[0].set("value", parse_qs(urlsplit(url).query).get("keywords", [""])[0])


class FilterBrowser(DOMBrowser):
    """A replay server whose URL changes only after actual control commits."""
    def __init__(self, strip_views=False):
        super().__init__((FIXTURES / "linkedin_modern_filters.html").read_text())
        self.current_url = "https://www.linkedin.com/jobs/search-results/?keywords=old&geoId=103644278&origin=tracking&currentJobId=999"
        self.fail_commit = False
        self.strip_views = strip_views
        if strip_views:
            for node in self.root.xpath("//*[@data-view-name]"):
                del node.attrib["data-view-name"]

    def picker(self):
        return self.root.xpath("//*[@role='button'][.//*[@aria-label and starts-with(@aria-label,'Location ')]]")[0]

    def set_params(self, **values):
        parsed = urlsplit(self.current_url)
        params = parse_qs(parsed.query)
        params.update({key: [value] for key, value in values.items()})
        self.current_url = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(params, doseq=True), ""))

    def type_into(self, node, value):
        super().type_into(node, value)
        if "\ue007" in value and node.get("componentkey") == "semanticSearchBox":
            parsed = urlsplit(self.current_url)
            self.current_url = urlunsplit((parsed.scheme, parsed.netloc, "/jobs/search-results/", parsed.query, ""))
            # Rendered native URLs can retain an adaptive facet unrelated to
            # requested controls, plus selection/tracking state.
            self.set_params(f_ADAPT="unrequested", origin="tracking", currentJobId="999")

    def get(self, url):
        super().get(url)
        if urlsplit(url).path == "/jobs/":
            for node in self.root.xpath("//*[@aria-checked]"):
                node.set("aria-checked", "true" if node.get("aria-label") in {"Any time", "Part-time"} else "false")
            for menu in self.root.xpath("//*[@id]"):
                menu.set("hidden", "")
            picker = self.picker()
            picker.set("aria-expanded", "false")
            picker.xpath(".//*[@aria-label]")[0].set("aria-label", "Location United States")
            picker.xpath(".//p")[0].text = "United States"

    def click(self, node):
        super().click(node)
        label, role, view = node.get("aria-label"), node.get("role"), node.get("data-view-name")
        children = node.xpath(".//*[@aria-label]")
        if not label and children:
            label = children[0].get("aria-label").removeprefix("Filter by ")
        if role == "button" and node is self.picker():
            node.set("aria-expanded", "true")
            self.root.xpath("//*[@id='location-popup']")[0].attrib.pop("hidden", None)
        elif node.tag == "a" and "geoId=" in node.get("href", ""):
            if not self.fail_commit:
                self.set_params(geoId=parse_qs(urlsplit(node.get("href")).query)["geoId"][0])
                picker = self.picker()
                picker.set("aria-expanded", "false")
                picker.xpath(".//*[@aria-label]")[0].set("aria-label", "Location " + node.text_content())
                picker.xpath(".//p")[0].text = node.text_content()
                self.root.xpath("//*[@id='location-popup']")[0].set("hidden", "")
        elif role == "button" and label in {"Date posted", "Past month", "Job type", "Employment type", "On-site/remote", "Workplace type"}:
            menu_id = {"Date posted": "date-menu", "Past month": "date-menu", "Job type": "job-menu", "Employment type": "job-menu", "On-site/remote": "work-menu", "Workplace type": "work-menu"}[label]
            menu = self.root.xpath("//*[@id=$menu]", menu=menu_id)[0]
            if menu.get("hidden") is None:
                menu.set("hidden", "")
            else:
                menu.attrib.pop("hidden", None)
        elif role in {"checkbox", "radio"}:
            current = node.get("aria-checked") == "true"
            if role == "radio":
                for sibling in node.getparent().xpath(".//*[@role='radio']"):
                    sibling.set("aria-checked", "false")
            node.set("aria-checked", "false" if current else "true")
            if label == "Filter by Easy Apply":
                self.set_params(f_AL="true" if not current else "false")
            if label == "Filter by Remote":
                self.set_params(f_WT="2" if not current else "")
        elif node.tag == "a" and node.text_content().strip() == "Show results":
            menu = node.getparent()
            selected = [n.get("aria-label") for n in menu.xpath(".//*[@aria-checked='true']")]
            if menu.get("id") == "date-menu":
                self.set_params(f_TPR="r2592000" if "Past month" in selected else "")
            elif menu.get("id") == "job-menu":
                self.set_params(f_SAL="$".join({"Full-time": "f_SA_id_226001:272015", "Part-time": "f_SA_id_226001:272016"}[label] for label in selected))
            elif menu.get("id") == "work-menu":
                self.set_params(f_WT=",".join({"Remote": "2", "Hybrid": "3", "On-site": "1"}[label] for label in selected))
            menu.set("hidden", "")


class StalePromptElement(DOMElement):
    def get_attribute(self, name):
        if self.browser.prompt_stale and name in {"value", "textContent"}:
            from selenium.common.exceptions import StaleElementReferenceException
            raise StaleElementReferenceException("React replaced the search prompt")
        return super().get_attribute(name)

    @property
    def text(self):
        if self.browser.prompt_stale:
            from selenium.common.exceptions import StaleElementReferenceException
            self.browser.prompt_stale = False
            self.browser.stale_text_reads += 1
            raise StaleElementReferenceException("Detached prompt text during filter hydration")
        return super().text


class StalePromptBrowser(FilterBrowser):
    def __init__(self):
        super().__init__()
        self.prompt_stale = False
        self.stale_text_reads = 0
        self.prompt_locates = 0
        self.locates_at_transition = None

    def query(self, root, by, selector):
        elements = super().query(root, by, selector)
        result = []
        for element in elements:
            if element.node.get("componentkey") == "semanticSearchBox":
                self.prompt_locates += 1
                result.append(StalePromptElement(self, element.node))
            else:
                result.append(element)
        return result

    def click(self, node):
        super().click(node)
        if node.tag == "a" and node.text_content().strip() == "Show results" and node.getparent().get("id") == "job-menu":
            self.prompt_stale = True
            self.locates_at_transition = self.prompt_locates


class StaleLocationAnchor(DOMElement):
    def click(self):
        from selenium.common.exceptions import StaleElementReferenceException
        self.browser.anchor_click_attempts += 1
        if not self.browser.detached_anchor_once:
            self.browser.detached_anchor_once = True
            if self.browser.commit_before_stale:
                super().click()
            raise StaleElementReferenceException("Location suggestion was replaced during click")
        super().click()


class StaleLocationBrowser(FilterBrowser):
    def __init__(self, commit_before_stale=False):
        super().__init__()
        self.commit_before_stale = commit_before_stale
        self.detached_anchor_once = False
        self.anchor_click_attempts = 0
        self.anchor_locates = 0

    def query(self, root, by, selector):
        elements = super().query(root, by, selector)
        result = []
        for element in elements:
            if element.node.tag == "a" and parse_qs(urlsplit(element.node.get("href", "")).query).get("geoId") == ["90000084"]:
                self.anchor_locates += 1
                result.append(StaleLocationAnchor(self, element.node))
            else:
                result.append(element)
        return result


def immediate(predicate):
    for _ in range(5):
        result = predicate(None)
        if result:
            return result
    from selenium.common.exceptions import TimeoutException
    raise TimeoutException("Fixture state not ready")


def make_spec(**overrides):
    intent = {"search_location": "San Francisco Bay Area, United States", "date_posted": "Past month",
              "job_type": ["Full-time"], "on_site": ["Remote", "Hybrid"], "easy_apply_only": True}
    intent.update(overrides)
    return SearchSpec("manual:fixture", "Staff AI & ML Engineer + infrastructure", "manual", "ai", "fixture", "1",
                      {"intent": intent, "gates": {}}, 1, "Staff AI Engineer")


class ModernResultsDOMTests(unittest.TestCase):
    def test_hydrated_cards_without_anchors_have_stable_ids_and_metadata(self):
        from modules.linkedin_modern_search import get_search_cards, search_card_id, read_search_card
        browser = DOMBrowser()
        self.assertEqual(browser.find_elements("xpath", "//a"), [])
        cards = get_search_cards(browser)
        self.assertEqual([search_card_id(card) for card in cards], ["4472829614", "4440983509"])
        details = read_search_card(cards[0])
        self.assertIn("Voice Agents", details["title"])
        self.assertEqual(details["title"].count("Voice Agents"), 1)
        self.assertEqual(details["company"], "Skyrocket Ventures")
        self.assertIn("San Francisco", details["location"])

    def test_modern_prompt_and_location_do_not_require_classic_inputs(self):
        from modules.linkedin_modern_search import detect_modern_ui, modern_prompt
        browser = DOMBrowser()
        self.assertTrue(detect_modern_ui(browser))
        self.assertEqual(modern_prompt(browser).get_attribute("placeholder"), "Describe the job you want")

    def test_all_view_markers_removed_preserves_card_identity_metadata_and_capability(self):
        from modules.linkedin_modern_search import detect_modern_ui, modern_prompt, get_search_cards, read_search_card, search_results_ready
        browser = DOMBrowser((FIXTURES / "linkedin_modern_results_unmarked.html").read_text())
        self.assertEqual(browser.find_elements("xpath", "//*[@data-view-name]"), [])
        self.assertTrue(detect_modern_ui(browser))
        self.assertIsNotNone(modern_prompt(browser))
        self.assertEqual(search_results_ready(browser), "jobs")
        cards = get_search_cards(browser)
        self.assertEqual(len(cards), 2)
        row = read_search_card(cards[0])
        self.assertEqual(row["job_id"], "4472829614")
        self.assertEqual(row["company"], "Skyrocket Ventures")
        self.assertEqual(row["workplace_type"], "Hybrid")
        self.assertEqual(row["title"].count("Voice Agents"), 1)

    def test_display_contents_cards_and_facets_use_visible_actionable_descendants(self):
        from modules.linkedin_modern_search import get_search_cards
        browser = DOMBrowser()
        for node in browser.root.xpath("//*[@data-view-name='job-search-job-card']"):
            node.set("data-display-contents", "true")
        self.assertTrue(all(not element.is_displayed() for element in browser.find_elements("xpath", "//*[@data-view-name='job-search-job-card']")))
        self.assertEqual(len(get_search_cards(browser)), 2)

    def test_job_state_ready_with_repeated_card_ids(self):
        from modules.linkedin_modern_search import get_search_cards, search_results_ready
        browser = DOMBrowser()
        card = browser.root.xpath("//*[@data-view-name='job-search-job-card']")[0]
        from copy import deepcopy
        card.getparent().append(deepcopy(card))
        self.assertEqual(search_results_ready(browser), "jobs")
        self.assertEqual(len(get_search_cards(browser)), 2)

    def test_malformed_or_offsite_card_links_do_not_create_a_job_identity(self):
        from modules.linkedin_modern_search import get_search_cards, search_results_ready
        browser = DOMBrowser('<html><body><main><div data-view-name="job-search-job-card">'
                             '<div role="button" componentkey="job-card-component-ref-opaque">'
                             '<a href="https://example.com/jobs/view/123">Staff Engineer</a>'
                             '</div></div></main></body></html>')
        self.assertEqual(get_search_cards(browser), [])
        self.assertFalse(search_results_ready(browser))

    def test_auth_redirect_is_never_reported_as_empty_or_jobs(self):
        from modules.linkedin_modern_search import search_results_ready
        from modules.linkedin_search import SearchUIError
        browser = DOMBrowser()
        browser.current_url = "https://www.linkedin.com/checkpoint/challenge/"
        with self.assertRaises(SearchUIError) as caught:
            search_results_ready(browser)
        self.assertEqual(caught.exception.stage, "auth_required")

    def test_loading_keeps_retained_cards_unready(self):
        from modules.linkedin_modern_search import search_results_ready
        browser = DOMBrowser()
        busy = html.fromstring('<div data-view-name="job-search-results-loading" aria-busy="true"></div>')
        browser.root.xpath("//main")[0].append(busy)
        self.assertFalse(search_results_ready(browser))

    def test_explicit_empty_state_is_ready_but_missing_cards_is_not(self):
        from modules.linkedin_modern_search import search_results_ready
        browser = DOMBrowser('<html><body><main><p>No matching jobs found</p></main></body></html>')
        self.assertEqual(search_results_ready(browser), "empty")
        browser.root.xpath("//p")[0].text = "Loading jobs"
        self.assertFalse(search_results_ready(browser))

    def test_observed_date_popup_ignores_selected_topbar_radios_and_native_child_state(self):
        from modules.linkedin_modern_search import _filter
        browser = DOMBrowser((FIXTURES / "linkedin_modern_date_popup.html").read_text())
        past_month = browser.find_elements("xpath", "//*[@role='radio' and @aria-label='Past month']")[0]
        self.assertEqual(past_month.get_attribute("aria-checked"), "true")
        self.assertFalse(past_month.find_elements("xpath", ".//input")[0].is_selected())
        self.assertTrue(_filter(browser, "date_posted", ["Past month"], verify_only=True, wait=immediate))

    def test_classic_fallback_submits_visible_native_keyword_control(self):
        from modules.linkedin_search import prepare_search
        browser = DOMBrowser('<html><body><main><input id="jobs-search-box-keyword-fixture" value="old">'
                             '<li data-occludable-job-id="321"><a href="/jobs/view/321">Engineer</a></li>'
                             '</main></body></html>')
        browser.current_url = "https://www.linkedin.com/jobs/search/?keywords=old"
        configured = []
        result = prepare_search(browser, make_spec(), lambda: None, lambda _: None,
                                lambda current: configured.append(current.query_id) or [], wait=immediate)
        self.assertEqual(result.mode, "classic")
        self.assertEqual(result.ui_variant, "legacy_classic")
        self.assertEqual(parse_qs(urlsplit(browser.current_url).query)["keywords"], [make_spec().classic_query])
        self.assertEqual(configured, [make_spec().query_id])
        self.assertEqual(browser.navigations, [])

    def test_absent_supported_native_control_does_not_invent_search_url(self):
        from modules.linkedin_search import prepare_search, SearchUIError
        browser = DOMBrowser('<html><body><main><p>Jobs page is loading</p></main></body></html>')
        browser.current_url = "https://www.linkedin.com/jobs/"
        with self.assertRaises(SearchUIError) as caught:
            prepare_search(browser, make_spec(), lambda: None, lambda _: None, lambda current: [], wait=immediate)
        self.assertEqual(caught.exception.stage, "discover_ui")
        self.assertEqual(browser.navigations, ["https://www.linkedin.com/jobs/"])
        self.assertTrue(all("keywords=" not in url for url in browser.navigations))


class ModernFilterReplayTests(unittest.TestCase):
    def setUp(self):
        from modules.linkedin_modern_search import clear_recipe_cache
        clear_recipe_cache()
        self.addCleanup(clear_recipe_cache)
        self.browser = FilterBrowser()

    def prepare(self, spec=None):
        from modules.linkedin_modern_search import prepare_modern_search
        return prepare_modern_search(self.browser, spec or make_spec(), wait=immediate, timeout=0.1)

    def test_native_date_annotation_keeps_cards_and_full_filter_verification(self):
        original_click = self.browser.click

        def annotated_date(node):
            original_click(node)
            if node.tag == "a" and node.text_content().strip() == "Show results" and node.getparent().get("id") == "date-menu":
                prompt = self.browser.root.xpath("//*[@componentkey='semanticSearchBox']")[0]
                prompt.set("value", make_spec().query_text + " posted in the past month")
            if node.get("aria-label") == "Filter by Easy Apply":
                prompt = self.browser.root.xpath("//*[@componentkey='semanticSearchBox']")[0]
                prompt.set("value", make_spec().query_text + " Easy Apply posted in the past month")
            if node.tag == "a" and node.text_content().strip() == "Show results" and node.getparent().get("id") == "job-menu":
                prompt = self.browser.root.xpath("//*[@componentkey='semanticSearchBox']")[0]
                prompt.set("value", make_spec().query_text + " full-time Easy Apply posted in the past month")

        self.browser.click = annotated_date
        result = self.prepare()
        self.assertEqual(result.results_state, "jobs")
        self.assertIn("date_posted", result.verified_filters)
        self.assertIn("easy_apply_only", result.verified_filters)
        self.assertEqual(result.executed_query, make_spec().query_text)
        self.assertEqual(result.diagnostics()["result_card_count"], 1)

    def test_post_filter_readiness_rejects_unrelated_text_or_wrong_url_query(self):
        from modules.linkedin_modern_search import _settle
        from modules.linkedin_search import SearchUIError
        spec = make_spec()
        for prompt, url_query in (("Unrelated marketing jobs", spec.query_text),
                                  (spec.query_text + " unrelated words", spec.query_text),
                                  (spec.query_text + " posted in the past month", "Wrong query")):
            with self.subTest(prompt=prompt, url_query=url_query):
                self.browser.get("https://www.linkedin.com/jobs/search-results/?" + urlencode({"keywords": url_query}))
                self.browser.root.xpath("//*[@componentkey='semanticSearchBox']")[0].set("value", prompt)
                with self.assertRaises(SearchUIError) as caught:
                    _settle(self.browser, spec.query_text, after_filters=True, wait=immediate)
                self.assertIn("readiness", caught.exception.diagnostics())

    def test_initial_query_does_not_accept_filter_annotation(self):
        from modules.linkedin_modern_search import _settle
        from modules.linkedin_search import SearchUIError
        spec = make_spec()
        self.browser.get("https://www.linkedin.com/jobs/search-results/?" + urlencode({"keywords": spec.query_text}))
        self.browser.root.xpath("//*[@componentkey='semanticSearchBox']")[0].set("value", spec.query_text + " posted in the past month")
        with self.assertRaises(SearchUIError):
            _settle(self.browser, spec.query_text, wait=immediate)

    def test_easy_apply_pill_can_disappear_during_filter_hydration(self):
        from unittest.mock import patch
        from modules import linkedin_modern_search as modern
        original = modern._facet
        disappeared = []

        def transient(driver, key, desired=()):
            facet = original(driver, key, desired)
            if key == "easy_apply_only" and modern._selected(facet) is True and not disappeared:
                disappeared.append(True)
                return None
            return facet

        with patch.object(modern, "_facet", side_effect=transient):
            result = self.prepare()
        self.assertEqual(disappeared, [True])
        self.assertIn("easy_apply_only", result.verified_filters)

    def test_learned_url_replay_accepts_observed_date_annotation(self):
        original_get = self.browser.get

        def annotated_replay(url):
            original_get(url)
            params = parse_qs(urlsplit(url).query)
            if params.get("f_TPR") == ["r2592000"]:
                prompt = self.browser.root.xpath("//*[@componentkey='semanticSearchBox']")[0]
                prompt.set("value", params["keywords"][0] + " full-time Easy Apply posted in the past month")

        self.browser.get = annotated_replay
        self.prepare()
        second = make_spec()
        second.query_text = "Principal AI Platform Engineer"
        result = self.prepare(second)
        self.assertEqual(result.transport, "verified_url")
        self.assertIn("easy_apply_only", result.verified_filters)
        self.assertEqual(result.executed_query, second.query_text)
        self.assertEqual(result.diagnostics()["rendered_prompt"], second.query_text + " full-time Easy Apply posted in the past month")

    def test_native_controls_verify_exact_options_and_do_not_narrow_remote_hybrid(self):
        result = self.prepare()
        self.assertEqual(result.mode, "ai")
        self.assertEqual(result.transport, "native")
        self.assertEqual(set(result.verified_filters), {"date_posted", "job_type", "easy_apply_only", "search_location"})
        params = parse_qs(urlsplit(self.browser.current_url).query)
        self.assertEqual(params["keywords"], [make_spec().query_text])
        self.assertEqual(params["geoId"], ["90000084"])
        self.assertEqual(params["f_TPR"], ["r2592000"])
        self.assertEqual(params["f_SAL"], ["f_SA_id_226001:272015"])
        self.assertEqual(params["f_AL"], ["true"])
        self.assertNotIn("f_WT", params)
        self.assertFalse(any(label == "Filter by Remote" for _, label, _ in self.browser.clicks))
        self.assertEqual(result.filter_report["on_site"]["status"], "unavailable")

    def test_display_contents_facet_wrappers_verify_through_actionable_children(self):
        wrappers = self.browser.root.xpath("//*[@data-view-name='job-search-facet-dropdown' or @data-view-name='job-search-facet-pill']")
        for node in wrappers:
            node.set("data-display-contents", "true")
        self.assertTrue(all(not DOMElement(self.browser, node).is_displayed() for node in wrappers))
        result = self.prepare()
        self.assertIn("date_posted", result.verified_filters)
        self.assertIn("job_type", result.verified_filters)
        self.assertIn("easy_apply_only", result.verified_filters)

    def test_filter_hydration_refinds_prompt_after_stale_attributes_and_text(self):
        self.browser = StalePromptBrowser()
        result = self.prepare()
        self.assertEqual(self.browser.stale_text_reads, 1)
        self.assertGreaterEqual(self.browser.prompt_locates, self.browser.locates_at_transition + 2)
        self.assertEqual(result.results_state, "jobs")
        self.assertIn("job_type", result.verified_filters)
        self.assertEqual(parse_qs(urlsplit(self.browser.current_url).query)["f_SAL"], ["f_SA_id_226001:272015"])

    def test_stale_exact_location_anchor_is_refound_before_clicking(self):
        self.browser = StaleLocationBrowser()
        result = self.prepare()
        self.assertEqual(self.browser.anchor_click_attempts, 2)
        self.assertGreaterEqual(self.browser.anchor_locates, 2)
        self.assertEqual(result.location_confirmation["geography"]["geoId"], ["90000084"])
        actual_clicks = [event for event in self.browser.clicks if event[2] == "job-search-location-tyah-result"]
        self.assertEqual(len(actual_clicks), 1)

    def test_location_stale_after_successful_commit_does_not_click_again(self):
        self.browser = StaleLocationBrowser(commit_before_stale=True)
        result = self.prepare()
        self.assertEqual(self.browser.anchor_click_attempts, 1)
        self.assertEqual(result.location_confirmation["selected_label"], "San Francisco Bay Area")
        self.assertEqual(parse_qs(urlsplit(self.browser.current_url).query)["geoId"], ["90000084"])

    def test_wrong_country_location_suggestion_is_never_clicked(self):
        from modules.linkedin_search import SearchUIError
        self.browser.root.xpath("//a[contains(@href,'geoId=90000084')]")[0].text = "San Francisco Bay Area, India"
        with self.assertRaises(SearchUIError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.stage, "location")
        self.assertFalse(any(event[2] == "job-search-location-tyah-result" for event in self.browser.clicks))

    def test_auth_redirect_during_filter_hydration_is_not_retried_as_stale(self):
        from modules.linkedin_search import SearchUIError
        original_click = self.browser.click

        def auth_on_filter_commit(node):
            original_click(node)
            if node.tag == "a" and node.text_content().strip() == "Show results" and node.getparent().get("id") == "job-menu":
                self.browser.current_url = "https://www.linkedin.com/checkpoint/challenge/"

        self.browser.click = auth_on_filter_commit
        with self.assertRaises(SearchUIError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.stage, "auth_required")

    def test_wait_does_not_suppress_arbitrary_runtime_errors(self):
        from modules.linkedin_modern_search import _wait

        def broken(*_):
            raise RuntimeError("Unexpected parsing failure")

        with self.assertRaisesRegex(RuntimeError, "Unexpected parsing failure"):
            _wait(self.browser, broken, wait=immediate)

    def test_missing_easy_apply_control_stops_without_claiming_search_verified(self):
        from modules.linkedin_search import SearchUIError
        pill = self.browser.root.xpath("//*[@aria-label='Filter by Easy Apply']/..")[0]
        pill.getparent().remove(pill)
        with self.assertRaises(SearchUIError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.stage, "filter_validation")
        self.assertEqual(parse_qs(urlsplit(self.browser.current_url).query)["f_AL"], ["true"])

    def install_adaptive_easy_apply_response(self, selected):
        from copy import deepcopy
        pill = self.browser.root.xpath("//*[@aria-label='Filter by Easy Apply']/..")[0]
        template = deepcopy(pill)
        pill.getparent().remove(pill)
        original_get = self.browser.get

        def adaptive_response(url):
            original_get(url)
            if parse_qs(urlsplit(url).query).get("f_AL") == ["true"]:
                revealed = deepcopy(template)
                revealed.xpath(".//*[@aria-label='Filter by Easy Apply']")[0].set("aria-checked", "true" if selected else "false")
                self.browser.root.xpath("//main")[0].append(revealed)

        self.browser.get = adaptive_response

    def test_adaptive_easy_apply_candidate_is_accepted_only_after_selected_facet_renders(self):
        self.install_adaptive_easy_apply_response(selected=True)
        result = self.prepare()
        self.assertIn("easy_apply_only", result.verified_filters)
        self.assertIn("f_AL", result.diagnostics()["parameter_owners"]["easy_apply_only"])
        self.assertTrue(any(parse_qs(urlsplit(url).query).get("f_AL") == ["true"] for url in self.browser.navigations))

    def test_candidate_url_with_unselected_easy_apply_facet_is_rejected(self):
        from modules.linkedin_search import SearchUIError
        self.install_adaptive_easy_apply_response(selected=False)
        with self.assertRaises(SearchUIError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.stage, "filter_validation")

    def test_uncommitted_location_stops_before_verified_recipe(self):
        from modules.linkedin_search import SearchUIError
        from modules.linkedin_modern_search import get_recipe_cache
        self.browser.fail_commit = True
        with self.assertRaises(SearchUIError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.stage, "location")
        self.assertEqual(get_recipe_cache(self.browser), {})

    def test_learned_recipe_preserves_opaque_filters_and_encodes_new_query_without_tracking(self):
        first = self.prepare()
        query = make_spec()
        query.query_text = "Principal R&D + AI / ML Engineer"
        second = self.prepare(query)
        self.assertEqual(second.transport, "verified_url")
        replay_url = self.browser.navigations[-1]
        params = parse_qs(urlsplit(replay_url).query)
        self.assertEqual(params["keywords"], [query.query_text])
        self.assertEqual(params["f_SAL"], ["f_SA_id_226001:272015"])
        self.assertEqual(params["f_TPR"], ["r2592000"])
        self.assertEqual(params["f_AL"], ["true"])
        self.assertNotIn("origin", params)
        self.assertNotIn("currentJobId", params)
        self.assertNotIn("f_ADAPT", params)
        self.assertEqual(set(first.verified_filters), set(second.verified_filters))

    def test_config_change_rebuilds_native_instead_of_replaying_old_filter_recipe(self):
        self.prepare()
        changed = make_spec(date_posted="Any time")
        result = self.prepare(changed)
        self.assertEqual(result.transport, "native")
        self.assertTrue(all(url == "https://www.linkedin.com/jobs/" for url in self.browser.navigations))

    def test_disabling_easy_apply_does_not_replay_or_keep_old_enabled_filter(self):
        self.prepare()
        result = self.prepare(make_spec(easy_apply_only=False))
        self.assertEqual(result.transport, "native")
        self.assertNotIn("easy_apply_only", result.verified_filters)
        self.assertNotIn("f_AL", parse_qs(urlsplit(self.browser.current_url).query))

    def test_native_preselected_remote_only_is_cleared_for_remote_or_hybrid_intent(self):
        original_type = self.browser.type_into

        def query_with_remote_selected(node, value):
            original_type(node, value)
            if "\ue007" in value and node.get("componentkey") == "semanticSearchBox":
                self.browser.root.xpath("//*[@aria-label='Filter by Remote']")[0].set("aria-checked", "true")
                self.browser.set_params(f_WT="2")

        self.browser.type_into = query_with_remote_selected
        result = self.prepare()
        self.assertEqual(self.browser.root.xpath("//*[@aria-label='Filter by Remote']")[0].get("aria-checked"), "false")
        self.assertNotIn("f_WT", parse_qs(urlsplit(self.browser.current_url).query))
        self.assertEqual(result.filter_report["on_site"]["status"], "unavailable")

    def test_workplace_multiselect_applies_remote_and_hybrid_when_available(self):
        trigger = self.browser.root.xpath("//*[@aria-label='On-site/remote']")[0]
        trigger.set("aria-label", "Workplace type")
        trigger.text = "Workplace type"
        result = self.prepare()
        self.assertEqual(result.filter_report["on_site"]["status"], "verified")
        self.assertEqual(set(parse_qs(urlsplit(self.browser.current_url).query)["f_WT"][0].split(",")), {"2", "3"})

    def test_hybrid_and_onsite_only_do_not_treat_remote_pill_as_workplace_dropdown(self):
        for arrangement in ("Hybrid", "On-site"):
            with self.subTest(arrangement=arrangement):
                self.browser = FilterBrowser()
                result = self.prepare(make_spec(on_site=[arrangement]))
                self.assertEqual(result.filter_report["on_site"]["status"], "unavailable")
                self.assertEqual(result.filter_report["on_site"]["requested"], [arrangement])
                self.assertFalse(any(label == "Filter by Remote" for _, label, _ in self.browser.clicks))
                self.assertNotIn("f_WT", parse_qs(urlsplit(self.browser.current_url).query))

    def test_supported_workplace_dropdown_can_select_hybrid_without_remote_pill(self):
        trigger = self.browser.root.xpath("//*[@aria-label='On-site/remote']")[0]
        trigger.set("aria-label", "Workplace type")
        trigger.text = "Workplace type"
        result = self.prepare(make_spec(on_site=["Hybrid"]))
        self.assertEqual(result.filter_report["on_site"]["status"], "verified")
        self.assertEqual(parse_qs(urlsplit(self.browser.current_url).query)["f_WT"], ["3"])
        self.assertFalse(any(label == "Filter by Remote" for _, label, _ in self.browser.clicks))

    def test_single_hybrid_or_onsite_native_clears_preselected_remote_pill(self):
        for arrangement in ("Hybrid", "On-site"):
            with self.subTest(arrangement=arrangement):
                self.browser = FilterBrowser()
                original_type = self.browser.type_into

                def preselected(node, value):
                    original_type(node, value)
                    if "\ue007" in value and node.get("componentkey") == "semanticSearchBox":
                        self.browser.root.xpath("//*[@aria-label='Filter by Remote']")[0].set("aria-checked", "true")
                        self.browser.set_params(f_WT="2")

                self.browser.type_into = preselected
                result = self.prepare(make_spec(on_site=[arrangement]))
                self.assertEqual(result.filter_report["on_site"]["status"], "unavailable")
                self.assertEqual(self.browser.root.xpath("//*[@aria-label='Filter by Remote']")[0].get("aria-checked"), "false")
                self.assertNotIn("f_WT", parse_qs(urlsplit(self.browser.current_url).query))
                self.assertEqual(sum(label == "Filter by Remote" for _, label, _ in self.browser.clicks), 1)

    def test_single_hybrid_or_onsite_replay_rejects_preselected_remote_pill(self):
        for arrangement in ("Hybrid", "On-site"):
            with self.subTest(arrangement=arrangement):
                self.browser = FilterBrowser()
                selected = make_spec(on_site=[arrangement])
                self.prepare(selected)
                self.browser.root.xpath("//*[@aria-label='Filter by Remote']")[0].set("aria-checked", "true")
                result = self.prepare(selected)
                self.assertEqual(result.transport, "native")
                self.assertEqual(result.diagnostics()["replay_rejected"]["stage"], "filter_validation")
                self.assertEqual(self.browser.root.xpath("//*[@aria-label='Filter by Remote']")[0].get("aria-checked"), "false")

    def test_workplace_dropdown_before_active_remote_pill_cannot_hide_narrowing(self):
        trigger = self.browser.root.xpath("//*[@aria-label='On-site/remote']")[0]
        trigger.set("aria-label", "Workplace type")
        trigger.text = "Workplace type"
        dropdown = trigger.getparent()
        remote_pill = self.browser.root.xpath("//*[@aria-label='Filter by Remote']/..")[0]
        container = dropdown.getparent()
        container.remove(dropdown)
        container.insert(container.index(remote_pill), dropdown)
        original_type = self.browser.type_into

        def preselected(node, value):
            original_type(node, value)
            if "\ue007" in value and node.get("componentkey") == "semanticSearchBox":
                self.browser.root.xpath("//*[@aria-label='Filter by Remote']")[0].set("aria-checked", "true")
                self.browser.set_params(f_WT="2")

        self.browser.type_into = preselected
        result = self.prepare(make_spec(on_site=["Hybrid"]))
        self.assertEqual(result.filter_report["on_site"]["status"], "verified")
        self.assertEqual(self.browser.root.xpath("//*[@aria-label='Filter by Remote']")[0].get("aria-checked"), "false")
        self.assertEqual(parse_qs(urlsplit(self.browser.current_url).query)["f_WT"], ["3"])
        self.assertEqual(sum(label == "Filter by Remote" for _, label, _ in self.browser.clicks), 1)

    def test_replay_selected_remote_only_is_rejected_for_remote_or_hybrid_intent(self):
        self.prepare()
        self.browser.root.xpath("//*[@aria-label='Filter by Remote']")[0].set("aria-checked", "true")
        result = self.prepare()
        self.assertEqual(result.transport, "native")
        self.assertEqual(result.diagnostics()["replay_rejected"]["stage"], "filter_validation")
        self.assertEqual(self.browser.root.xpath("//*[@aria-label='Filter by Remote']")[0].get("aria-checked"), "false")

    def test_stale_selected_filter_rejects_url_and_rebuilds_native_controls(self):
        self.prepare()
        full_time = self.browser.root.xpath("//*[@aria-label='Full-time']")[0]
        full_time.set("aria-checked", "false")
        result = self.prepare()
        self.assertEqual(result.transport, "native")
        self.assertIn("replay_rejected", result.diagnostics())
        self.assertEqual(full_time.get("aria-checked"), "true")

    def test_replay_geoid_cannot_override_wrong_rendered_location(self):
        self.prepare()
        picker = self.browser.root.xpath("//*[@data-view-name='job-search-location-picker']")[0]
        picker.xpath(".//p")[0].text = "New York, United States"
        picker.xpath(".//*[@aria-label]")[0].set("aria-label", "Location New York, United States")
        result = self.prepare()
        self.assertEqual(result.transport, "native")
        self.assertEqual(result.diagnostics()["replay_rejected"]["stage"], "replay_location")
        self.assertEqual(result.location_confirmation["selected_label"], "San Francisco Bay Area")

    def test_locale_and_session_changes_do_not_reuse_learned_recipe(self):
        self.prepare()
        self.browser.root.set("lang", "fr-FR")
        self.assertEqual(self.prepare().transport, "native")
        self.browser.session_id = "new-fixture-session"
        self.assertEqual(self.prepare().transport, "native")
        self.assertTrue(all(url == "https://www.linkedin.com/jobs/" for url in self.browser.navigations))

    def test_easy_apply_radio_variant_uses_aria_state_over_unchecked_native_child(self):
        self.browser.root.xpath("//*[@aria-label='Filter by Easy Apply']")[0].set("role", "radio")
        result = self.prepare()
        self.assertIn("easy_apply_only", result.verified_filters)
        control = self.browser.root.xpath("//*[@aria-label='Filter by Easy Apply']")[0]
        self.assertEqual(control.get("aria-checked"), "true")
        self.assertIsNone(control.xpath(".//input")[0].get("checked"))

    def test_replay_auth_challenge_stops_without_native_fallback(self):
        from modules.linkedin_search import SearchUIError
        self.prepare()
        original_get = self.browser.get

        def challenge(url):
            original_get(url)
            self.browser.current_url = "https://www.linkedin.com/checkpoint/challenge/"

        self.browser.get = challenge
        clicks_before = len(self.browser.clicks)
        navigations_before = len(self.browser.navigations)
        with self.assertRaises(SearchUIError) as caught:
            self.prepare()
        self.assertEqual(caught.exception.stage, "auth_required")
        self.assertEqual(len(self.browser.clicks), clicks_before)
        self.assertEqual(len(self.browser.navigations), navigations_before + 1)


class ModernUnmarkedReplayTests(unittest.TestCase):
    prepare = ModernFilterReplayTests.prepare

    def setUp(self):
        from modules.linkedin_modern_search import clear_recipe_cache
        clear_recipe_cache()
        self.addCleanup(clear_recipe_cache)
        self.browser = FilterBrowser(strip_views=True)
        for old, label in (("Date posted", "Past month"), ("Job type", "Employment type")):
            trigger = self.browser.root.xpath("//*[@role='button' and @aria-label=$label]", label=old)[0]
            del trigger.attrib["aria-label"]
            trigger.text = None
            child = etree.SubElement(trigger, "div", {"aria-label": "Filter by " + label})
            etree.SubElement(child, "p").text = label
        self.browser.root.xpath("//*[@aria-label='Filter by Easy Apply']")[0].set("role", "radio")

    def test_native_controls_and_location_verify_after_every_marker_is_removed(self):
        result = self.prepare()
        self.assertEqual(self.browser.root.xpath("//*[@data-view-name]"), [])
        self.assertEqual(set(result.verified_filters), {"date_posted", "job_type", "easy_apply_only", "search_location"})
        self.assertEqual(result.location_confirmation["geography"]["geoId"], ["90000084"])
        self.assertEqual(result.results_state, "jobs")

    def test_verified_recipe_replays_unmarked_controls_without_reintroducing_markers(self):
        self.prepare()
        second = make_spec()
        second.query_text = "Principal AI & reliability + infrastructure"
        result = self.prepare(second)
        self.assertEqual(result.transport, "verified_url")
        self.assertEqual(self.browser.root.xpath("//*[@data-view-name]"), [])
        self.assertEqual(parse_qs(urlsplit(self.browser.current_url).query)["keywords"], [second.query_text])
        self.assertIn("easy_apply_only", result.verified_filters)
        self.assertEqual(result.location_confirmation["selected_label"], "San Francisco Bay Area")

    def test_unmarked_stale_selected_options_reject_recipe_and_rebuild(self):
        self.prepare()
        self.browser.root.xpath("//*[@aria-label='Full-time']")[0].set("aria-checked", "false")
        result = self.prepare()
        self.assertEqual(result.transport, "native")
        self.assertIn("replay_rejected", result.diagnostics())
        self.assertEqual(self.browser.root.xpath("//*[@data-view-name]"), [])


class ModernPaginationTests(unittest.TestCase):
    def browser(self):
        browser = DOMBrowser()
        browser.root.xpath("//*[@componentkey='semanticSearchBox']")[0].set("value", "old")
        browser.root.xpath("//main")[0].append(html.fromstring('<div role="radio" aria-label="Filter by Easy Apply" aria-checked="true"><p>Easy Apply</p></div>'))
        pagination = html.fromstring('<div aria-label="Pagination"><div role="button" aria-label="Page 1" aria-current="page">1</div>'
                                    '<div role="button" aria-label="Page 2">2</div></div>')
        browser.root.xpath("//main")[0].append(pagination)
        return browser

    def test_same_card_ids_can_remain_while_async_page_selection_commits(self):
        from modules.linkedin_modern_search import next_search_page, get_search_pagination, get_search_cards, search_card_id
        browser = self.browser()
        before_ids = [search_card_id(card) for card in get_search_cards(browser)]
        polls, states = [], []

        def delayed(predicate):
            for _ in range(5):
                polls.append(len(polls) + 1)
                if len(polls) == 2:
                    browser.root.xpath("//*[@aria-label='Page 1']")[0].attrib.pop("aria-current", None)
                    browser.root.xpath("//*[@aria-label='Page 2']")[0].set("aria-current", "page")
                ready = predicate(None)
                states.append(bool(ready))
                if ready:
                    return ready
            raise AssertionError("Fixture pagination never committed")

        self.assertTrue(next_search_page(browser, 1, wait=delayed, timeout=.1))
        self.assertFalse(states[0])
        self.assertEqual(get_search_pagination(browser)[1], 2)
        self.assertEqual([search_card_id(card) for card in get_search_cards(browser)], before_ids)
        self.assertTrue(any(label == "Page 2" for _, label, _ in browser.clicks))

    def test_unchanged_page_with_repeated_cards_does_not_claim_next_page_success(self):
        from modules.linkedin_modern_search import next_search_page
        from modules.linkedin_search import SearchUIError
        with self.assertRaises(SearchUIError) as caught:
            next_search_page(self.browser(), 1, wait=immediate, timeout=.1)
        self.assertEqual(caught.exception.stage, "pagination")

    def test_classic_page_commit_does_not_require_modern_prompt_or_facets(self):
        from modules.linkedin_modern_search import next_search_page, get_search_pagination
        browser = DOMBrowser('<html><body><main><input id="jobs-search-box-keyword-fixture" value="Engineer">'
                             '<li data-occludable-job-id="321"><a href="/jobs/view/321">Engineer</a></li>'
                             '<div aria-label="Pagination"><button aria-label="Page 1" aria-current="page">1</button>'
                             '<button aria-label="Page 2">2</button></div></main></body></html>')
        browser.current_url = "https://www.linkedin.com/jobs/search/?keywords=Engineer"
        polls = []

        def delayed(predicate):
            for _ in range(5):
                polls.append(1)
                if len(polls) == 2:
                    browser.root.xpath("//*[@aria-label='Page 1']")[0].attrib.pop("aria-current", None)
                    browser.root.xpath("//*[@aria-label='Page 2']")[0].set("aria-current", "page")
                result = predicate(None)
                if result:
                    return result
            raise AssertionError("Classic selected page never committed")

        self.assertTrue(next_search_page(browser, 1, wait=delayed, timeout=.1))
        self.assertEqual(get_search_pagination(browser)[1], 2)
        self.assertEqual(len(polls), 2)


if __name__ == "__main__":
    unittest.main()

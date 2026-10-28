"""Read modern LinkedIn job details through semantic, job-scoped DOM hooks.

These readers never click controls. Full description text comes from the scoped
expandable DOM, including paragraphs hidden by the visual collapsed preview.
"""

import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse


DETAIL_ROOT = "[data-view-name='job-detail-page']"
DETAIL_SECTION = "[id^='JobDetails_AboutTheJob_']"
EASY_APPLY = "button[aria-label='Easy Apply to this job'], a[aria-label='Easy Apply to this job']"


class _DescriptionText(HTMLParser):
    """Read every text node while preserving ordinary HTML block boundaries."""

    blocks = {"p", "div", "section", "article", "li", "ul", "ol", "table", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "dl", "dt", "dd"}
    voids = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.ignored_depth = [], 0

    def handle_starttag(self, tag, attrs):
        if self.ignored_depth:
            if tag not in self.voids:
                self.ignored_depth += 1
            return
        attributes = dict(attrs)
        if tag in {"script", "style"} or tag == "button" and attributes.get("data-testid") == "expandable-text-button":
            self.ignored_depth = 1
            return
        if tag in self.blocks or tag in {"br", "hr"}:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if self.ignored_depth:
            if tag not in self.voids:
                self.ignored_depth -= 1
            return
        if tag in self.blocks:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" ")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.voids:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if not self.ignored_depth:
            self.parts.append(data)

    def text(self):
        return "\n".join(line for line in (" ".join(value.split()) for value in "".join(self.parts).splitlines()) if line)


def _visible(element):
    try:
        return element.is_displayed()
    except Exception:
        return False


def header_identity_matches(header, title, company):
    """Formatting differences are harmless; title/employer differences are not."""
    normalize = lambda value: ' '.join(value.split()).casefold()
    return (normalize(header['title']) == normalize(title)
            and normalize(header['company']) == normalize(company))


def _text(element, *, full=False):
    value = element.get_attribute("textContent") if full else element.text
    return value.strip() if isinstance(value, str) else ""


def _url_job_id(url):
    parsed = urlparse(url)
    if parsed.hostname not in {"linkedin.com", "www.linkedin.com"}:
        return None
    match = re.search(r"/jobs/view/(?:[^/]*-)?(\d+)/?", parsed.path)
    if match:
        return match.group(1)
    if parsed.path.rstrip("/") in {"/jobs/search-results", "/jobs/search"}:
        return (parse_qs(parsed.query).get("currentJobId") or [None])[0]
    return None


def modern_details_root(driver, expected_job_id=None):
    roots = [root for root in driver.find_elements("css selector", DETAIL_ROOT) if _visible(root)]
    if not roots:
        # LinkedIn can remove instrumentation hooks after a normal navigation.
        # Bound the fallback to the selected job section's nearest ancestor
        # containing its employer header, rather than reading the whole page.
        expected = str(expected_job_id) if expected_job_id is not None else _url_job_id(driver.current_url)
        sections = [section for section in driver.find_elements("css selector", DETAIL_SECTION)
                    if _visible(section) and (not expected or section.get_attribute("id") == "JobDetails_AboutTheJob_" + expected)]
        seen = set()
        for section in sections:
            parents = section.find_elements("xpath", "ancestor::*[.//*[starts-with(@aria-label,'Company,')]][1]")
            if not parents:
                parents = section.find_elements("xpath", "ancestor::*[.//*[starts-with(@aria-label,'Company logo for,')]][1]")
            for parent in parents:
                identity = getattr(parent, "id", None) or id(parent)
                if _visible(parent) and identity not in seen:
                    roots.append(parent)
                    seen.add(identity)
        if sections and not roots:
            raise ValueError("Modern job section lacks a bounded employer header")
    if not roots:
        return None
    if len(roots) != 1:
        raise ValueError("Multiple visible modern job-detail panes")
    root = roots[0]
    sections = root.find_elements("css selector", "[id^='JobDetails_AboutTheJob_']")
    ids = {section.get_attribute("id").removeprefix("JobDetails_AboutTheJob_")
           for section in sections if isinstance(section.get_attribute("id"), str)}
    if len(ids) != 1 or not next(iter(ids)).isdigit():
        raise ValueError("Modern detail pane lacks one verified job ID")
    job_id = next(iter(ids))
    expected = str(expected_job_id) if expected_job_id is not None else _url_job_id(driver.current_url)
    if expected and job_id != expected:
        raise ValueError("Modern detail pane does not match the selected LinkedIn job ID")
    return root


def read_modern_description(driver, expected_job_id=None):
    root = modern_details_root(driver, expected_job_id)
    if root is None:
        raise ValueError("Modern job details are unavailable")
    sections = root.find_elements("css selector", "[id^='JobDetails_AboutTheJob_']")
    boxes = sections[0].find_elements("css selector", "[data-testid='expandable-text-box']")
    if len(boxes) != 1:
        raise ValueError("Full modern job description is unavailable")
    markup = boxes[0].get_attribute("innerHTML")
    if isinstance(markup, str) and markup.strip():
        parser = _DescriptionText()
        parser.feed(markup)
        parser.close()
        description = parser.text()
    else:
        description = re.sub(r"\s*…\s*more\s*$", "", _text(boxes[0], full=True), flags=re.I).strip()
    if not description:
        raise ValueError("Full modern job description is empty")
    return description


def read_modern_company(driver, expected_job_id=None):
    root = modern_details_root(driver, expected_job_id)
    if root is None:
        raise ValueError("Modern job details are unavailable")
    sections = root.find_elements("css selector", "[id^='JobDetails_AboutTheCompany_']")
    if len(sections) != 1:
        raise ValueError("Modern employer description is unavailable")
    value = _text(sections[0], full=True)
    if not value or value == "About the company":
        raise ValueError("Modern employer description is empty")
    return value, root


def read_modern_details(driver, expected_job_id=None):
    root = modern_details_root(driver, expected_job_id)
    if root is None:
        return None
    section = root.find_elements("css selector", "[id^='JobDetails_AboutTheJob_']")[0]
    job_id = section.get_attribute("id").removeprefix("JobDetails_AboutTheJob_")
    labels = root.find_elements("css selector", "[aria-label^='Company,']")
    if labels:
        company = re.sub(r"^Company,\s*|\.$", "", labels[0].get_attribute("aria-label")).strip()
        anchors = labels[0].find_elements("xpath", "ancestor::a[1]")
        company_url = anchors[0].get_attribute("href") if anchors else None
        company_key = anchors[0].get_attribute("componentkey") if anchors else None
        if not isinstance(company_key, str) or not company_key.endswith("-" + job_id):
            raise ValueError("Modern employer header does not match the selected LinkedIn job ID")
        parsed_company = urlparse(company_url or "")
        if not company or parsed_company.hostname not in {"linkedin.com", "www.linkedin.com"} or not parsed_company.path.startswith("/company/"):
            raise ValueError("Modern employer identity lacks a canonical company link")
    else:
        logos = root.find_elements("css selector", "[aria-label^='Company logo for,']")
        if len(logos) != 1 or _url_job_id(driver.current_url) != job_id:
            raise ValueError("Modern employer identity is unavailable")
        company = re.sub(r"^Company logo for,\s*|\.$", "", logos[0].get_attribute('aria-label')).strip()
        company_url = None  # This posting has no linked LinkedIn company page.
        links = root.find_elements('css selector', 'a[href]')
        if not any(_url_job_id(link.get_attribute('href') or '') == job_id for link in links):
            raise ValueError('Unlinked employer header lacks matching posting links')
    # The observed header publishes company, title, and location in its first
    # three paragraphs. Reading the entire hydrated pane can touch unrelated
    # JD, employer, and promotional nodes while React replaces them.
    paragraphs = [_text(paragraph) for paragraph in root.find_elements("css selector", "p")[:3]]
    paragraphs = [text for text in paragraphs if text]
    if len(paragraphs) < 3 or paragraphs[0] != company:
        raise ValueError("Modern job header is incomplete or ambiguous")
    title, metadata = paragraphs[1:3]
    location = metadata.split("·", 1)[0].strip()
    chips = [_text(anchor) for anchor in root.find_elements("css selector", "a[href]")
             if _url_job_id(anchor.get_attribute("href") or "") == job_id]
    style = next((value for value in ("Remote", "Hybrid", "On-site") if value in chips), "Unknown")
    employment = next((value for value in ("Full-time", "Part-time", "Contract", "Temporary", "Internship") if value in chips), "Unknown")
    posted = re.search(r"(?:\d+\s+(?:minute|hour|day|week|month)s? ago|today|just now)", metadata, re.I)
    return dict(id=job_id, title=title, company=company, company_url=company_url,
                location=location, workplace_type=style, employment_type=employment,
                posted_text=posted.group() if posted else None, root=root)


def modern_details_ready(driver, expected_job_id):
    from selenium.common.exceptions import StaleElementReferenceException
    try:
        return read_modern_details(driver, expected_job_id) or False
    except (ValueError, StaleElementReferenceException):
        return False


def modern_description_ready(driver, expected_job_id=None):
    """Wait predicate: the header and Easy Apply can precede JD hydration."""
    from selenium.common.exceptions import StaleElementReferenceException
    try:
        return read_modern_description(driver, expected_job_id)
    except (ValueError, StaleElementReferenceException):
        return False


def modern_easy_apply_button(driver, expected_job_id=None):
    root = modern_details_root(driver, expected_job_id)
    if root is None:
        return None
    buttons = [button for button in root.find_elements("css selector", EASY_APPLY)
               if _visible(button) and button.is_enabled() and button.get_attribute("aria-disabled") != "true"]
    if len(buttons) > 1:
        raise ValueError("Multiple modern Easy Apply controls")
    return buttons[0] if buttons else None


class JobDetailsUnavailable(RuntimeError):
    """Selected-job readiness exhausted; this job has not reached application entry."""

    def __init__(self, job_id, diagnostics):
        self.diagnostics = diagnostics
        super().__init__(f"job_details_ready [{job_id}]: {diagnostics.get('predicate_error', 'readiness timed out')}; "
                         f"evidence: {diagnostics.get('report_path', 'not saved')}")


def wait_for_modern_details(driver, expected_job_id, *, reselect=None, timeout=15,
                            wait_factory=None, diagnostics_dir=None, log=lambda _: None):
    """Wait, then reselect the same verified job once; never open an application.

    Capture the actual predicate failure instead of losing it inside a bare
    TimeoutException. Evidence contains the scoped details pane, never form data.
    """
    from datetime import datetime, timezone
    from pathlib import Path
    import json
    import traceback
    import uuid
    from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
    from selenium.webdriver.support.ui import WebDriverWait
    wait_factory = wait_factory or WebDriverWait
    job_id = str(expected_job_id)
    diagnostic = dict(stage='job_details_ready', job_id=job_id, attempts=0,
                      predicate_error='Selected job details did not become ready')

    def ready(browser):
        try:
            value = read_modern_details(browser, job_id)
            if not value:
                diagnostic['predicate_error'] = 'Modern detail pane not present'
            return value or False
        except (ValueError, StaleElementReferenceException) as error:
            diagnostic['predicate_error'] = f'{type(error).__name__}: {error}'
            return False

    def capture():
        if diagnostics_dir is None:
            return
        directory = Path(diagnostics_dir)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
        base = directory / f'{job_id}-{stamp}'
        try:
            directory.mkdir(parents=True, exist_ok=True)
            diagnostic['report_path'] = str(base.with_suffix('.json'))
            try:
                driver.save_screenshot(str(base.with_suffix('.png')))
                diagnostic['screenshot_path'] = str(base.with_suffix('.png'))
            except Exception as error:
                diagnostic['screenshot_error'] = type(error).__name__
            try:
                roots = driver.find_elements('css selector', DETAIL_ROOT)
                markup = '\n'.join(root.get_attribute('outerHTML') or '' for root in roots[:2])
                if not markup.strip():
                    roots = driver.find_elements('css selector', 'main')
                    markup = '\n'.join(root.get_attribute('outerHTML') or '' for root in roots[:1])
                if not markup.strip():
                    raise ValueError('No page DOM available for job-detail diagnostics')
                base.with_suffix('.private.html').write_text(markup, encoding='utf-8')
                diagnostic['dom_path'] = str(base.with_suffix('.private.html'))
            except Exception as error:
                diagnostic['dom_error'] = type(error).__name__
            base.with_suffix('.json').write_text(json.dumps(diagnostic, indent=2) + '\n', encoding='utf-8')
        except Exception as error:
            diagnostic['capture_error'] = type(error).__name__
            log(f'Job details [{job_id}]: diagnostic save failed ({type(error).__name__})')

    for attempt in range(1, 3):
        diagnostic['attempts'] = attempt
        try:
            return wait_factory(driver, timeout).until(ready)
        except TimeoutException as error:
            diagnostic['exception_type'] = type(error).__name__
            diagnostic['traceback'] = traceback.format_exc()
            capture()
            log(f"Job details [{job_id}]: readiness timed out (attempt {attempt}/2): {diagnostic['predicate_error']}")
            if attempt == 1 and reselect is not None:
                try:
                    reselect()
                    log(f'Job details [{job_id}]: same job reselected; retrying readiness')
                    continue
                except Exception as recovery_error:
                    diagnostic['recovery_error'] = f'{type(recovery_error).__name__}: {recovery_error}'
                    diagnostic['recovery_traceback'] = traceback.format_exc()
                    capture()
            raise JobDetailsUnavailable(job_id, diagnostic) from error

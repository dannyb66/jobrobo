"""Read modern LinkedIn job details through semantic, job-scoped DOM hooks.

These readers never click controls. Full description text comes from the scoped
expandable DOM, including paragraphs hidden by the visual collapsed preview.
"""

import re
from urllib.parse import parse_qs, urlparse


DETAIL_ROOT = "[data-view-name='job-detail-page']"
DETAIL_SECTION = "[id^='JobDetails_AboutTheJob_']"
EASY_APPLY = "button[aria-label='Easy Apply to this job']"


def _visible(element):
    try:
        return element.is_displayed()
    except Exception:
        return False


def _text(element, *, full=False):
    value = element.get_attribute("textContent") if full else element.text
    return value.strip() if isinstance(value, str) else ""


def _url_job_id(url):
    parsed = urlparse(url)
    if parsed.hostname not in {"linkedin.com", "www.linkedin.com"}:
        return None
    match = re.search(r"/jobs/view/(?:[^/]*-)?(\d+)/?", parsed.path)
    return match.group(1) if match else (parse_qs(parsed.query).get("currentJobId") or [None])[0]


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
    paragraphs = boxes[0].find_elements("css selector", "p")
    description = "\n".join(_text(paragraph, full=True) for paragraph in paragraphs).strip()
    if not paragraphs:
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
    if not labels:
        raise ValueError("Modern employer identity is unavailable")
    company = re.sub(r"^Company,\s*|\.$", "", labels[0].get_attribute("aria-label")).strip()
    anchors = labels[0].find_elements("xpath", "ancestor::a[1]")
    company_url = anchors[0].get_attribute("href") if anchors else None
    company_key = anchors[0].get_attribute("componentkey") if anchors else None
    if not isinstance(company_key, str) or not company_key.endswith("-" + job_id):
        raise ValueError("Modern employer header does not match the selected LinkedIn job ID")
    parsed_company = urlparse(company_url or "")
    if not company or parsed_company.hostname not in {"linkedin.com", "www.linkedin.com"} or not parsed_company.path.startswith("/company/"):
        raise ValueError("Modern employer identity lacks a canonical company link")
    # The observed header publishes company, title, and location in its first
    # three paragraphs. Reading the entire hydrated pane can touch unrelated
    # JD, employer, and promotional nodes while React replaces them.
    paragraphs = [_text(paragraph) for paragraph in root.find_elements("css selector", "p")[:3]]
    paragraphs = [text for text in paragraphs if text]
    if len(paragraphs) < 3 or paragraphs[0] != company:
        raise ValueError("Modern job header is incomplete or ambiguous")
    title, metadata = paragraphs[1:3]
    location = metadata.split("·", 1)[0].strip()
    chips = [_text(anchor) for anchor in root.find_elements("css selector", "a[href*='/jobs/view/']")
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


def modern_easy_apply_button(driver, expected_job_id=None):
    root = modern_details_root(driver, expected_job_id)
    if root is None:
        return None
    buttons = [button for button in root.find_elements("css selector", EASY_APPLY)
               if _visible(button) and button.is_enabled()]
    if len(buttons) > 1:
        raise ValueError("Multiple modern Easy Apply controls")
    return buttons[0] if buttons else None

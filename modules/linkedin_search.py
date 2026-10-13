"""LinkedIn search UI adapter. Selectors are capability checks, not API flags."""

from dataclasses import dataclass, field
from urllib.parse import urlencode


# Match explicit natural-language search labels, never the generic classic keyword box.
AI_INPUT_XPATH = (
    "//*[self::input or self::textarea][not(@disabled) and ("
    "contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'describe') or "
    "contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'describe') or "
    "contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'ai-powered') or "
    "contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'ai-powered')"
    ")]"
)


@dataclass
class SearchResult:
    mode: str
    fallback_reason: str = None
    warnings: list = field(default_factory=list)


def start_search(driver, spec, wait_for_search, wait_for_results=None):
    """Submit via the AI UI when exposed; otherwise use the classic keyword route."""
    fallback = None
    try:
        driver.get("https://www.linkedin.com/jobs/")
        wait_for_search()
        fields = driver.find_elements("xpath", AI_INPUT_XPATH)
        field = next((item for item in fields if item.is_displayed() and item.is_enabled()), None)
        if field is None:
            # Some accounts expose the AI field only on the results page.
            driver.get("https://www.linkedin.com/jobs/search/?" + urlencode({"keywords": spec.query_text}))
            wait_for_search()
            fields = driver.find_elements("xpath", AI_INPUT_XPATH)
            field = next((item for item in fields if item.is_displayed() and item.is_enabled()), None)
        if field is None:
            fallback = "Natural-language search control unavailable"
        else:
            current_url = getattr(driver, "current_url", "")
            if (isinstance(current_url, str) and "/jobs/search/" in current_url
                    and field.get_attribute("value") == spec.query_text):
                # The results URL already submitted this query. Re-submitting identical
                # text may reuse the same cards, so waiting for them to go stale is wrong.
                if wait_for_results:
                    wait_for_results([])
                return SearchResult("ai")
            previous = driver.find_elements("xpath", "//li[@data-occludable-job-id]")
            field.clear()
            field.send_keys(spec.query_text)
            field.send_keys("\ue007")  # Selenium ENTER
            if wait_for_results:
                wait_for_results(previous)
            else:
                wait_for_search()
            return SearchResult("ai")
    except Exception as error:
        fallback = f"Natural-language search failed ({type(error).__name__})"
    driver.get("https://www.linkedin.com/jobs/search/?" + urlencode({"keywords": spec.classic_query}))
    wait_for_search()
    return SearchResult("classic", fallback)


def apply_configured_filters(config, select_option):
    """Try each configured filter independently, reporting missing UI controls."""
    warnings = []
    for key in ("sort_by", "date_posted", "salary", "experience_level", "job_type", "on_site",
                "companies", "location", "industry", "job_function", "job_titles", "benefits", "commitments"):
        values = config.get(key)
        for value in values if isinstance(values, list) else ([values] if values else []):
            try:
                if not select_option(key, value):
                    warnings.append(f"Filter unavailable: {key}={value}")
            except Exception as error:
                warnings.append(f"Filter failed: {key}={value} ({type(error).__name__})")
    for key, label in {"easy_apply_only": "Easy Apply", "under_10_applicants": "Under 10 applicants",
                       "in_your_network": "In your network", "fair_chance_employer": "Fair Chance Employer"}.items():
        if config.get(key):
            try:
                if not select_option(key, label):
                    warnings.append(f"Filter unavailable: {key}")
            except Exception as error:
                warnings.append(f"Filter failed: {key} ({type(error).__name__})")
    return warnings

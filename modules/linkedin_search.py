"""LinkedIn search UI adapter. Selectors are capability checks, not API flags."""

from dataclasses import dataclass, field
from copy import deepcopy
import re
import unicodedata
from urllib.parse import parse_qs, urlencode, urlparse


# Match explicit natural-language search labels, never the generic classic keyword box.
AI_INPUT_XPATH = (
    "//*[self::input or self::textarea or @contenteditable='true'][not(@disabled) and ("
    "contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'describe') or "
    "contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'describe') or "
    "contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'description') or "
    "contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'natural language') or "
    "contains(translate(@placeholder, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'ai-powered') or "
    "contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'ai-powered')"
    ")]"
)

LOCATION_INPUT_XPATH = (
    "//input[not(@disabled) and (contains(@id, 'jobs-search-box-location') or "
    "contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'location') or "
    "(contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'city') and "
    "(contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'state') or "
    "contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'zip'))))]"
)
LOCATION_OPTIONS_XPATH = (
    ".//*[@role='option'] | .//li[contains(@class, 'basic-typeahead__selectable') or "
    "contains(@class, 'jobs-search-box__typeahead-suggestion')]"
)
LOCATION_LISTBOX_XPATH = "//*[@role='listbox']"
LOCATION_LEGACY_ROOT_XPATH = (
    "ancestor::*[contains(@class, 'jobs-search-box__input--location') or "
    "contains(@class, 'jobs-search-box__typeahead')][1]"
)
RESULT_LOCATION_XPATH = (
    "//*[contains(@class, 'jobs-search-results-list__title-heading') or "
    "contains(@class, 'jobs-search-results-list__subtitle')] | "
    "//*[contains(@class, 'jobs-search-results-list__header') or "
    "contains(@class, 'jobs-search-results__header')]//*[self::h1 or self::h2 or @role='heading']"
)


class LocationSelectionError(ValueError):
    """Configured LinkedIn geography could not be verified in the results UI."""


class SearchUIError(ValueError):
    def __init__(self, message, *, stage="search", details=None):
        super().__init__(message)
        self.stage, self.details = stage, details or {}

    def diagnostics(self):
        return {"stage": self.stage, **deepcopy(self.details)}


def _location_normalize(value):
    return re.sub(r"[\s,]+", " ", unicodedata.normalize("NFKC", value).casefold()).strip()


def _location_parts(value):
    value = _location_normalize(value)
    # Country omission is a display convention, never permission to accept a
    # different explicitly named country or a merely similar city/region.
    countries = {"united states of america": "us", "united states": "us", "u.s.a.": "us", "usa": "us", "u.s.": "us", "us": "us",
                 "united kingdom": "uk", "uk": "uk", "canada": "ca", "india": "in", "germany": "de",
                 "france": "fr", "australia": "au", "netherlands": "nl", "singapore": "sg", "ireland": "ie"}
    for suffix in sorted(countries, key=len, reverse=True):
        if value == suffix:
            return "", countries[suffix]
        if value.endswith(" " + suffix):
            return value[:-len(suffix)].strip(), countries[suffix]
    return value, None


def _location_matches(label, desired):
    if not isinstance(label, str) or not label.strip():
        return False
    label_region, label_country = _location_parts(label)
    desired_region, desired_country = _location_parts(desired)
    return (label_region == desired_region and (not label_country or not desired_country or label_country == desired_country)
            and (bool(label_region) or label_country == desired_country))


def _location_attribute(element, name):
    try:
        value = element.get_attribute(name)
        return value if isinstance(value, str) else ""
    except Exception:
        return ""


def _location_visible(element):
    try:
        return element.is_displayed() and element.is_enabled()
    except Exception:
        return False


def _location_input(driver):
    fields = [field for field in driver.find_elements("xpath", LOCATION_INPUT_XPATH) if _location_visible(field)]
    preferred = [field for field in fields if "jobs-search-box-location" in _location_attribute(field, "id")
                 or "city" in _location_attribute(field, "aria-label").casefold()]
    fields = preferred or fields
    if len(fields) > 1:
        raise LocationSelectionError("Multiple visible LinkedIn location pickers; selection is ambiguous")
    return fields[0] if fields else None


def _location_options(driver, field):
    roots = []
    controls = (_location_attribute(field, "aria-controls") or _location_attribute(field, "aria-owns")).split()
    for control in controls:
        roots.extend(driver.find_elements("id", control))
    if not controls:
        roots = driver.find_elements("xpath", LOCATION_LISTBOX_XPATH)
        roots.extend(field.find_elements("xpath", LOCATION_LEGACY_ROOT_XPATH))
    options, seen = [], set()
    for root in roots:
        if not _location_visible(root):
            continue
        for option in root.find_elements("xpath", LOCATION_OPTIONS_XPATH):
            identity = getattr(option, "id", None)
            identity = identity if isinstance(identity, str) else id(option)
            if identity not in seen and _location_visible(option) and _location_attribute(option, "aria-disabled") != "true":
                seen.add(identity)
                options.append(option)
    return options


def _location_geography(driver):
    url = urlparse(driver.current_url)
    if url.hostname not in {"linkedin.com", "www.linkedin.com"} or not url.path.startswith("/jobs/"):
        return {}
    query = parse_qs(url.query)
    return {key: sorted(value for value in query.get(key, []) if value.strip())
            for key in ("geoId", "location") if any(value.strip() for value in query.get(key, []))}


def _location_geography_changed(driver, original):
    current = _location_geography(driver)
    if not current:
        return False
    # Updating only a location text parameter while retaining the old country
    # geoId is not proof that LinkedIn applied a different geographic filter.
    if original.get("geoId") and current.get("geoId"):
        return current["geoId"] != original["geoId"]
    return current != original


def _location_headings(driver):
    labels = []
    for heading in driver.find_elements("xpath", RESULT_LOCATION_XPATH):
        if not _location_visible(heading):
            continue
        text = heading.text if isinstance(heading.text, str) else ""
        line = " ".join(text.split())
        match = re.search(r"\bin\s+(.+)$", line, re.I)
        label = match.group(1) if match else line
        label = re.sub(r"\s+\d[\d,.]*\+?\s+(?:jobs|results)\b.*$", "", label, flags=re.I)
        if match or _location_parts(label)[0] == "":
            labels.append((label, True))
        elif line.strip():
            # Bare location headings are accepted only by exact matching.
            labels.append((line, False))
    return labels


def _location_display_matches(driver, desired, *, heading_only=False):
    geography = _location_geography(driver)
    if not geography:
        return False
    if geography.get("location") and not all(_location_matches(value, desired) for value in geography["location"]):
        return False
    headings = _location_headings(driver)
    explicit_headings = [label for label, explicit in headings if explicit]
    if explicit_headings and not all(_location_matches(label, desired) for label in explicit_headings):
        return False
    if any(_location_matches(label, desired) for label, _ in headings):
        return True
    # Explicit geographic headings take precedence over a field containing
    # freshly typed text, including a stale "Engineer in United States" heading.
    if heading_only or any(explicit for _, explicit in headings):
        return False
    field = _location_input(driver)
    return bool(field is not None and _location_matches(_location_attribute(field, "value"), desired)
                and _location_attribute(field, "aria-expanded") != "true" and not _location_options(driver, field))


def _location_wait(driver, predicate, timeout, wait):
    if wait is not None:
        result = wait(predicate)
    else:
        from selenium.webdriver.support.ui import WebDriverWait
        result = WebDriverWait(driver, timeout).until(predicate)
    if not result:
        raise LocationSelectionError("Configured LinkedIn location could not be confirmed before timeout")
    return result


def select_search_location(driver, location, wait_for_results=None, *, timeout=10, wait=None):
    """Commit an exact public-UI suggestion and verify geographic results changed.

    ``wait`` is an optional callable that polls a predicate (with or without the
    browser argument). No keyword/filter URL is rebuilt and no default region
    is accepted when the configured location cannot be confirmed.
    """
    if location is None or isinstance(location, str) and not location.strip():
        return None
    if not isinstance(location, str):
        raise LocationSelectionError("LinkedIn search location must be text")
    desired = " ".join(location.split())
    try:
        original = _location_geography(driver)
        if original and _location_display_matches(driver, desired, heading_only=True):
            return {"location": desired, "geography": original}
        field = _location_wait(driver, lambda *_: _location_input(driver), timeout, wait)
        field.click()
        field.clear()
        field.send_keys(desired)

        def exact_suggestion(*_):
            matches = [option for option in _location_options(driver, field)
                       if isinstance(option.text, str) and _location_matches(option.text, desired)]
            exact = [option for option in matches if _location_normalize(option.text) == _location_normalize(desired)]
            matches = exact or matches
            if len(matches) > 1:
                raise LocationSelectionError("Multiple exact LinkedIn location suggestions; refusing an ambiguous selection")
            return matches[0] if matches else False

        option = _location_wait(driver, exact_suggestion, timeout, wait)
        previous = driver.find_elements("xpath", "//li[@data-occludable-job-id]")
        option.click()

        def committed(*_):
            if _location_geography_changed(driver, original) and _location_display_matches(driver, desired, heading_only=True):
                return True
            current = _location_input(driver)
            return bool(current is not None and _location_matches(_location_attribute(current, "value"), desired)
                        and _location_attribute(current, "aria-expanded") != "true" and not _location_options(driver, current))

        _location_wait(driver, committed, timeout, wait)
        if not _location_geography_changed(driver, original):
            # Enter is safe only after clicking the exact option and observing
            # its committed label with the autocomplete picker closed.
            _location_input(driver).send_keys("\ue007")
        _location_wait(driver, lambda *_: bool(_location_geography_changed(driver, original)
                                             and _location_display_matches(driver, desired)), timeout, wait)
        confirmation = {"location": desired, "geography": _location_geography(driver)}
        if wait_for_results:
            wait_for_results(previous)
        verify_search_location(driver, confirmation, timeout=timeout, wait=wait)
        return confirmation
    except LocationSelectionError:
        raise
    except Exception as error:
        raise LocationSelectionError(f"Could not commit LinkedIn search location {desired!r} ({type(error).__name__})") from error


def verify_search_location(driver, confirmation, *, timeout=10, wait=None):
    """Recheck a committed geography after applying other LinkedIn filters."""
    if confirmation is None:
        return None
    if (not isinstance(confirmation, dict) or not isinstance(confirmation.get("location"), str)
            or not confirmation["location"].strip() or not isinstance(confirmation.get("geography"), dict)
            or not confirmation["geography"]):
        raise LocationSelectionError("A committed LinkedIn location confirmation is required")
    try:
        _location_wait(driver, lambda *_: bool(_location_geography(driver) == confirmation["geography"]
                                             and _location_display_matches(driver, confirmation["location"])), timeout, wait)
    except LocationSelectionError:
        raise
    except Exception as error:
        raise LocationSelectionError(f"Committed LinkedIn search location could not be reverified ({type(error).__name__})") from error


@dataclass
class SearchResult:
    mode: str
    fallback_reason: str = None
    warnings: list = field(default_factory=list)
    ui_variant: str = "legacy"
    transport: str = "native"
    verified_filters: list = field(default_factory=list)
    filter_report: dict = field(default_factory=dict)
    location_confirmation: dict = None
    results_state: str = None
    executed_query: str = None
    notes: dict = field(default_factory=dict)

    def diagnostics(self):
        return deepcopy(dict(ui_variant=self.ui_variant, transport=self.transport,
                             verified_filters=self.verified_filters, filter_report=self.filter_report,
                             location_confirmation=self.location_confirmation, results_state=self.results_state,
                             executed_query=self.executed_query, **self.notes))


CLASSIC_INPUT_XPATH = "//input[contains(@id, 'jobs-search-box-keyword') and not(@disabled)]"


def start_search(driver, spec, wait_for_search, wait_for_results=None, *, timeout=30, wait=None):
    """Use detected native controls; never invent a classic keyword URL."""
    from . import linkedin_modern_search as modern
    modern.check_access(driver)
    if not modern.find_prompt(driver) and not any(_location_visible(item) for item in driver.find_elements("xpath", CLASSIC_INPUT_XPATH)):
        driver.get("https://www.linkedin.com/jobs/")
        modern.check_access(driver)
        wait_for_search()
    if modern.detect_modern_ui(driver):
        return modern.start_modern_search(driver, spec, wait_for_results=wait_for_results, timeout=timeout, wait=wait)
    fields = driver.find_elements("xpath", AI_INPUT_XPATH)
    prompt = next((item for item in fields if _location_visible(item)), None)
    if prompt is not None:
        query, mode = spec.query_text, "ai"
        variant, fallback = "legacy_prompt", None
    else:
        fields = driver.find_elements("xpath", CLASSIC_INPUT_XPATH)
        prompt = next((item for item in fields if _location_visible(item)), None)
        if prompt is None:
            raise SearchUIError("No supported hydrated LinkedIn jobs search control", stage="discover_ui")
        query, mode = spec.classic_query, "classic"
        variant, fallback = "legacy_classic", "Natural-language search control unavailable; using visible native keyword input"
    current = getattr(driver, "current_url", "")
    current = current if isinstance(current, str) else ""
    if ("/jobs/search" not in current or _location_attribute(prompt, "value") != query
            or parse_qs(urlparse(current).query).get("keywords") != [query]):
        previous = get_search_cards(driver)
        modern.fill_text(prompt, query)
        prompt.send_keys("\ue007")
    else:
        previous = []
    if wait_for_results:
        wait_for_results(previous)
    else:
        wait_for_search()
    modern.check_access(driver)
    return SearchResult(mode, fallback, ui_variant=variant, executed_query=query)


def prepare_search(driver, spec, wait_for_search, wait_for_results, classic_filter_callback, *, timeout=30, wait=None):
    """Return a search whose query, modern filters, and location are verified."""
    from . import linkedin_modern_search as modern
    modern.check_access(driver)
    if modern.get_recipe_cache(driver) or modern.detect_modern_ui(driver):
        return modern.prepare_modern_search(driver, spec, wait_for_search=wait_for_search,
                                            wait_for_results=wait_for_results, timeout=timeout, wait=wait)
    result = start_search(driver, spec, wait_for_search, wait_for_results, timeout=timeout, wait=wait)
    # The jobs landing prompt can hydrate into the modern interface only after
    # submission. Re-detect it before choosing the filter implementation.
    if result.ui_variant != "modern_prompt" and modern.detect_modern_ui(driver):
        result = modern.start_modern_search(driver, spec, wait_for_results=wait_for_results, timeout=timeout, wait=wait)
    if result.ui_variant == "modern_prompt":
        return modern.finish_modern_search(driver, spec, result, wait_for_results=wait_for_results, timeout=timeout, wait=wait)
    spec.mode = result.mode
    if classic_filter_callback:
        result.warnings.extend(classic_filter_callback(spec) or [])
    result.results_state = modern.search_results_ready(driver) or None
    return result


def get_search_cards(driver):
    from .linkedin_modern_search import get_search_cards as implementation
    return implementation(driver)


def search_card_id(card):
    from .linkedin_modern_search import search_card_id as implementation
    return implementation(card)


def read_search_card(card):
    from .linkedin_modern_search import read_search_card as implementation
    return implementation(card)


def search_results_ready(driver):
    from .linkedin_modern_search import search_results_ready as implementation
    return implementation(driver)


def get_search_pagination(driver):
    from .linkedin_modern_search import get_search_pagination as implementation
    return implementation(driver)


def next_search_page(driver, page):
    from .linkedin_modern_search import next_search_page as implementation
    return implementation(driver, page)


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

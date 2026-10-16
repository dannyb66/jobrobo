"""Hydrated LinkedIn jobs UI and session-only, rendered-state-verified URL recipes.

Opaque filter parameters are learned from committed native controls. They are
never inferred from parameter names and never persisted beside run manifests.
"""

from copy import deepcopy
import hashlib
import json
import re
import sys
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

from .linkedin_search import AI_INPUT_XPATH, CLASSIC_INPUT_XPATH, SearchResult, SearchUIError, LocationSelectionError, _location_matches, _location_normalize


PROMPT_XPATH = "//*[self::input or self::textarea or @contenteditable='true'][@data-view-name='job-search-tyah' or @componentkey='semanticSearchBox']"
MODERN_CARD_XPATH = "//*[@data-view-name='job-search-job-card'] | //*[@role='button' and starts-with(@componentkey,'job-card-component-ref-') and not(ancestor::*[@data-view-name='job-search-job-card'])]"
LEGACY_CARD_XPATH = "//li[@data-occludable-job-id]"
FACET_XPATH = "//*[@data-view-name='job-search-facet-dropdown' or @data-view-name='job-search-facet-pill'] | //*[@role='button'][.//*[@aria-label and starts-with(@aria-label,'Filter by ')]] | //*[@role='radio' or @role='checkbox'][starts-with(@aria-label,'Filter by ')]"
LOCATION_PICKER_XPATH = "//*[@data-view-name='job-search-location-picker'] | //*[@role='button'][.//*[@aria-label and starts-with(@aria-label,'Location ')]]"
LOCATION_EDITOR_XPATH = "//*[@role='textbox' and @contenteditable='true' and not(@componentkey='semanticSearchBox')] | //input[contains(translate(@aria-label,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'location')]"
MENU_OPTION_XPATH = ".//*[@role='radio' or @role='checkbox' or @role='menuitemradio' or @role='menuitemcheckbox'][not(starts-with(@aria-label,'Filter by ')) and not(@data-view-name='search-filter-top-bar-select')]"
MENU_SUBMIT_XPATH = "//*[@data-view-name='search-filter-top-bar-menu-submit'] | //a[normalize-space(.)='Show results' and contains(@href,'/jobs/search-results/')]"
EMPTY_XPATH = "//main//*[self::p or self::h1 or self::h2 or @role='status'][contains(normalize-space(.),'No jobs found') or contains(normalize-space(.),'No matching jobs') or contains(normalize-space(.),'No results found') or normalize-space(.)='0 jobs'] | //*[contains(@class,'jobs-search-no-results')]"
LOADING_XPATH = "//main//*[@aria-busy='true' or @role='progressbar'] | //*[@data-view-name='job-search-results-loading']"
PAGINATION_XPATH = "//*[contains(@class,'jobs-search-pagination') or contains(@class,'artdeco-pagination') or @data-view-name='job-search-pagination' or @aria-label='Pagination']"
_SESSION_RECIPES = {}

FILTER_LABELS = {
    "date_posted": ("Date posted", "Any time", "Past 24 hours", "Past week", "Past month"),
    "job_type": ("Employment type", "Job type", "Full-time", "Part-time", "Contract", "Temporary", "Internship", "Volunteer"),
    "experience_level": ("Experience level", "Internship", "Entry level", "Associate", "Mid-Senior level", "Director", "Executive"),
    "companies": ("Company", "Companies"), "sort_by": ("Sort by", "Most recent", "Most relevant"),
    "on_site": ("Remote", "Workplace type", "Hybrid", "On-site"), "salary": ("Salary",),
    "easy_apply_only": ("Easy Apply",), "under_10_applicants": ("Under 10 applicants",),
    "in_your_network": ("In my network", "In your network"), "fair_chance_employer": ("Fair chance",),
}
BOOLEAN_FILTERS = {"easy_apply_only", "under_10_applicants", "in_your_network", "fair_chance_employer"}


def _find(root, selector, by="xpath"):
    try:
        return root.find_elements(by, selector)
    except Exception as error:
        if type(error).__name__ in {"StaleElementReferenceException", "NoSuchElementException"}:
            return []
        raise


def _attribute(element, name):
    try:
        value = element.get_attribute(name)
        return value if isinstance(value, str) else ""
    except Exception:
        return ""


def _visible(element):
    try:
        if element.is_displayed():
            return bool(element.is_enabled())
        if _attribute(element, "data-display-contents") == "true":
            # A display:contents wrapper has no rendered box. Its actual card
            # button or facet control can still be visible and interactable.
            return any(child.is_displayed() and child.is_enabled() for child in _find(
                element, ".//*[@role='button' or @role='radio' or @role='checkbox'] | .//input | .//a"))
        return False
    except Exception:
        return False


def _text(element):
    value = getattr(element, "text", "")
    return " ".join(value.split()) if isinstance(value, str) else ""


def _first(elements):
    return next((element for element in elements if _visible(element)), None)


def _url(driver):
    value = getattr(driver, "current_url", "")
    return value if isinstance(value, str) else ""


def check_access(driver):
    parsed = urlparse(_url(driver))
    if re.search(r"/(?:login|checkpoint|authwall|challenge)(?:/|$)", parsed.path):
        raise SearchUIError("LinkedIn authentication or access challenge requires attention", stage="auth_required")
    restricted = _first(_find(driver, "//input[@type='password'] | //iframe[contains(@title,'challenge') or contains(@title,'CAPTCHA')]"))
    if restricted is not None:
        raise SearchUIError("LinkedIn authentication or access challenge requires attention", stage="auth_required")


def find_prompt(driver):
    return _first(_find(driver, PROMPT_XPATH)) or _first(_find(driver, AI_INPUT_XPATH))


modern_prompt = find_prompt


def detect_modern_ui(driver):
    path = urlparse(_url(driver)).path
    return (path.startswith("/jobs/search-results") or _first(_find(driver, PROMPT_XPATH)) is not None
            or _first(_find(driver, FACET_XPATH)) is not None)


def fill_text(element, value):
    element.click()
    if _attribute(element, "contenteditable").casefold() == "true":
        element.send_keys("\ue03d" if sys.platform == "darwin" else "\ue009", "a")
        element.send_keys("\ue003")
    else:
        element.clear()
    element.send_keys(value)


def _wait(driver, predicate, timeout=30, wait=None):
    from selenium.common.exceptions import StaleElementReferenceException
    def poll(*args):
        try:
            return predicate(*args)
        except StaleElementReferenceException:
            # React can replace an element between the locator and text/ARIA
            # read. The next poll must locate it again; other errors still fail.
            return False
    if wait is not None:
        result = wait(poll)
        if not result:
            raise SearchUIError("LinkedIn UI state did not become ready", stage="wait")
        return result
    from selenium.webdriver.support.ui import WebDriverWait
    return WebDriverWait(driver, timeout).until(poll)


def get_search_cards(driver):
    cards = [card for card in _find(driver, MODERN_CARD_XPATH) if _visible(card)]
    if not cards:
        cards = [card for card in _find(driver, LEGACY_CARD_XPATH) if _visible(card)]
    unique, seen = [], set()
    for card in cards:
        job_id = search_card_id(card)
        if job_id and job_id not in seen:
            unique.append(card)
            seen.add(job_id)
    return unique


def search_card_id(card):
    for name in ("data-occludable-job-id", "data-job-id"):
        value = _attribute(card, name)
        if value.isdigit():
            return value
    for key in [_attribute(card, "componentkey")]:
        match = re.fullmatch(r"job-card-component-ref-(\d+)", key)
        if match:
            return match[1]
    for element in _find(card, ".//*[starts-with(@componentkey,'job-card-component-ref-')]"):
        match = re.fullmatch(r"job-card-component-ref-(\d+)", _attribute(element, "componentkey"))
        if match:
            return match[1]
    for anchor in _find(card, ".//a[contains(@href,'/jobs/view/')]"):
        parsed = urlparse(urljoin("https://www.linkedin.com", _attribute(anchor, "href")))
        if parsed.hostname not in {"linkedin.com", "www.linkedin.com"}:
            continue
        match = re.search(r"/jobs/view/(?:[^/]*-)?(\d+)(?:/|$)", parsed.path)
        if match:
            return match[1]
    return ""


def read_search_card(card):
    job_id = search_card_id(card)
    modern = (_attribute(card, "data-view-name") == "job-search-job-card"
              or _attribute(card, "componentkey").startswith("job-card-component-ref-"))
    if modern:
        paragraphs = _find(card, ".//p")
        title = ""
        if paragraphs:
            visible_title = _find(paragraphs[0], ".//span[@aria-hidden='true'][not(ancestor::span[@aria-hidden='true'])]")
            # The sampled card publishes both screen-reader and visible title.
            title = _text(visible_title[0]) if visible_title else _text(paragraphs[0])
        dismiss = _find(card, ".//*[@data-view-name='dismiss-job']")
        if dismiss:
            label = _attribute(dismiss[0], "aria-label")
            if label.startswith("Dismiss ") and label.endswith(" job"):
                title = label[8:-4].strip()
        title = re.sub(r"\s*\(Verified job\)\s*$", "", title).strip()
        company = _text(paragraphs[1]) if len(paragraphs) > 1 else ""
        location = _text(paragraphs[2]) if len(paragraphs) > 2 else ""
        targets = _find(card, ".//*[@role='button' and starts-with(@componentkey,'job-card-component-ref-')]")
        target = card if _attribute(card, "role") == "button" else _first(targets)
    else:
        anchors = _find(card, ".//a[contains(@href,'/jobs/view/')]") or _find(card, ".//a")
        target = _first(anchors)
        title = _text(target) if target is not None else ""
        subtitles = _find(card, ".//*[contains(@class,'artdeco-entity-lockup__subtitle') or contains(@class,'job-card-container__primary-description')]")
        subtitle = _text(subtitles[0]) if subtitles else ""
        company, _, location = subtitle.partition(" · ")
        if not location:
            locations = _find(card, ".//*[contains(@class,'artdeco-entity-lockup__caption') or contains(@class,'job-card-container__metadata')]")
            location = _text(locations[0]) if locations else ""
    workplace = next((value for value in ("Hybrid", "Remote", "On-site") if re.search(r"\b" + value + r"\b", location, re.I)), "Unknown")
    location = re.sub(r"\((?:Remote|Hybrid|On-site)\)", "", location, flags=re.I).strip()
    return {"id": job_id, "job_id": job_id, "title": title, "company": company, "location": location,
            "workplace_type": workplace, "link": "https://www.linkedin.com/jobs/view/" + job_id if job_id else "",
            **({"title_element": target} if target is not None else {})}


def search_results_ready(driver):
    check_access(driver)
    if _first(_find(driver, LOADING_XPATH)) is not None:
        return False
    cards = _find(driver, MODERN_CARD_XPATH) or _find(driver, LEGACY_CARD_XPATH)
    if any(_visible(card) and search_card_id(card) for card in cards):
        return "jobs"
    if _first(_find(driver, EMPTY_XPATH)) is not None:
        return "empty"
    return False


def _prompt_text(driver):
    prompt = find_prompt(driver)
    if prompt is None:
        return ""
    return _attribute(prompt, "value") or _attribute(prompt, "textContent") or _text(prompt)


def _query_text(value):
    return " ".join(value.split())


def _settle(driver, query, *, timeout=30, wait=None):
    consecutive = 0
    def ready(*_):
        nonlocal consecutive
        parsed = urlparse(_url(driver))
        query_committed = parse_qs(parsed.query).get("keywords") == [query]
        prompt = _prompt_text(driver)
        state = search_results_ready(driver)
        hydrated = (_first(_find(driver, LOCATION_PICKER_XPATH)) is not None
                    and _first(_find(driver, FACET_XPATH)) is not None)
        if query_committed and _query_text(prompt) == _query_text(query) and state and hydrated:
            consecutive += 1
            return state if consecutive >= 2 else False
        consecutive = 0
        return False
    try:
        return _wait(driver, ready, timeout, wait)
    except SearchUIError:
        raise
    except Exception as error:
        raise SearchUIError("Submitted LinkedIn query did not produce verified results", stage="query_results", details={"error_type": type(error).__name__}) from error


def start_modern_search(driver, spec, *, wait_for_results=None, timeout=30, wait=None):
    check_access(driver)
    try:
        prompt = _wait(driver, lambda *_: find_prompt(driver), timeout, wait)
        query = spec.query_text
        current = parse_qs(urlparse(_url(driver)).query).get("keywords")
        previous = get_search_cards(driver)
        if current != [query] or _query_text(_prompt_text(driver)) != _query_text(query):
            fill_text(prompt, query)
            prompt.send_keys("\ue007")
        else:
            previous = []
        state = _settle(driver, query, timeout=timeout, wait=wait)
        if wait_for_results:
            wait_for_results(previous)
        return SearchResult("ai", ui_variant="modern_prompt", transport="native", results_state=state, executed_query=query)
    except SearchUIError:
        raise
    except Exception as error:
        raise SearchUIError("Native LinkedIn prompt submission failed", stage="submit_prompt", details={"error_type": type(error).__name__}) from error


def _values(value):
    return list(value) if isinstance(value, (list, tuple)) else [value] if value not in (None, "", False) else []


def _selected(element):
    for attribute in ("aria-checked", "aria-pressed", "aria-selected"):
        value = _attribute(element, attribute)
        if value in {"true", "false"}:
            return value == "true"
    for child in _find(element, ".//*[@role='checkbox' or @role='radio' or @role='switch'] | .//input"):
        for attribute in ("aria-checked", "aria-pressed", "aria-selected"):
            value = _attribute(child, attribute)
            if value in {"true", "false"}:
                return value == "true"
        try:
            if _attribute(child, "type") in {"checkbox", "radio"}:
                return bool(child.is_selected())
        except Exception:
            pass
    return None


def _facet(driver, key, desired=()):
    names = {_location_normalize(value) for value in (*FILTER_LABELS.get(key, ()), *desired) if isinstance(value, str)}
    matches = []
    for facet in _find(driver, FACET_XPATH):
        if not _visible(facet):
            continue
        if key == "on_site" and set(desired) != {"Remote"} and _is_pill(facet):
            # The modern Remote-only pill is not a Hybrid/On-site menu.
            # Unsupported arrangements stay in the prompt without narrowing.
            continue
        labels = [_text(facet), _attribute(facet, "aria-label")]
        labels.extend(_attribute(child, "aria-label") for child in _find(facet, ".//*[@aria-label]"))
        labels = [re.sub(r"^Filter by\s+", "", label, flags=re.I) for label in labels]
        if any(_location_normalize(label) in names for label in labels):
            matches.append(facet)
    if key == "on_site" and set(desired) == {"Remote"}:
        # Prefer the actual Remote pill when a separate workplace dropdown is
        # also present, so the narrowing guard observes the independent toggle.
        for facet in matches:
            label = re.sub(r"^Filter by\s+", "", _attribute(facet, "aria-label"), flags=re.I)
            if _is_pill(facet) and any(_location_normalize(value) == "remote" for value in (label, _text(facet))):
                return facet
    return matches[0] if matches else None


def _click_target(element):
    target = _first(_find(element, ".//*[@role='button' or @role='checkbox' or @role='radio'] | .//button | .//a"))
    return target if target is not None else element


def _is_pill(element):
    return (_attribute(element, "data-view-name") == "job-search-facet-pill"
            or _attribute(element, "role") in {"radio", "checkbox", "switch"}
            and _attribute(element, "aria-label").startswith("Filter by "))


def _menu_options(driver):
    submit = _first(_find(driver, MENU_SUBMIT_XPATH))
    if submit is None:
        return []
    roots = _find(submit, "ancestor::*[.//*[@role='radio' or @role='checkbox' or @role='menuitemradio' or @role='menuitemcheckbox'][not(starts-with(@aria-label,'Filter by '))]][1]")
    if not roots:
        return []
    return [option for option in _find(roots[0], MENU_OPTION_XPATH) if _visible(option)
            and _text(option) and _attribute(option, "aria-disabled") != "true"]


def _dismiss_menu(driver, trigger, *, timeout=30, wait=None):
    dismiss = _first(_find(driver, "//*[@data-view-name='search-filter-top-bar-menu-cancel'] | //button[@aria-label='Dismiss' or @aria-label='Close']"))
    if dismiss is not None:
        dismiss.click()
    else:
        _click_target(trigger).send_keys("\ue00c")
    _wait(driver, lambda *_: _first(_find(driver, MENU_SUBMIT_XPATH)) is None, timeout, wait)


def _record_parameter_change(driver, key, before, owners):
    if owners is not None:
        after = parse_qs(urlparse(_url(driver)).query)
        owners.setdefault(key, [])
        owners[key] = sorted(set(owners[key]) | {name for name in after if name.startswith("f_") and after[name] != before.get(name)})


def _bootstrap_easy_apply(driver, *, timeout=30, wait=None, owners=None):
    """Try the observed Easy Apply parameter, accepting only rendered selection."""
    parsed = urlparse(_url(driver))
    if parsed.hostname not in {"linkedin.com", "www.linkedin.com"} or parsed.path != "/jobs/search-results/":
        return False
    before = parse_qs(parsed.query)
    query = (before.get("keywords") or [None])[0]
    if not query:
        return False
    owned = {name for names in (owners or {}).values() for name in names}
    parameters = {name: values for name, values in before.items() if name in owned or name in {"keywords", "geoId"}}
    # This candidate was observed through this UI's Easy Apply control. Unlike
    # employment parameters it is not an opaque semantic identifier; rendering
    # must still prove the search facet selected before the candidate is trusted.
    parameters["f_AL"] = ["true"]
    driver.get("https://www.linkedin.com/jobs/search-results/?" + urlencode(parameters, doseq=True))
    _settle(driver, query, timeout=timeout, wait=wait)
    facet = _facet(driver, "easy_apply_only")
    if facet is None or _selected(facet) is not True:
        return False
    _record_parameter_change(driver, "easy_apply_only", before, owners)
    return True


def _filter(driver, key, desired, *, verify_only=False, timeout=30, wait=None, owners=None):
    trigger = _facet(driver, key, desired)
    if trigger is None:
        if key == "easy_apply_only" and not verify_only:
            return _bootstrap_easy_apply(driver, timeout=timeout, wait=wait, owners=owners)
        return False
    before = parse_qs(urlparse(_url(driver)).query)
    if key in BOOLEAN_FILTERS or key == "on_site" and desired == ["Remote"] and _is_pill(trigger):
        selected = _selected(trigger)
        if selected is not True:
            if verify_only:
                return False
            _click_target(trigger).click()
            _wait(driver, lambda *_: _selected(_facet(driver, key, desired)) is True, timeout, wait)
            query = (before.get("keywords") or [_prompt_text(driver)])[0]
            _settle(driver, query, timeout=timeout, wait=wait)
            _record_parameter_change(driver, key, before, owners)
        return True
    _click_target(trigger).click()
    try:
        options = _wait(driver, lambda *_: _menu_options(driver), timeout, wait)
        wanted = {_location_normalize(value) for value in desired}
        selected = {_location_normalize(_text(option)) for option in options if _selected(option) is True}
        available = {_location_normalize(_text(option)) for option in options}
        if not wanted.issubset(available):
            _dismiss_menu(driver, trigger, timeout=timeout, wait=wait)
            return False
        if verify_only:
            _dismiss_menu(driver, trigger, timeout=timeout, wait=wait)
            return selected == wanted
        if selected == wanted:
            _dismiss_menu(driver, trigger, timeout=timeout, wait=wait)
            return True
        for option in options:
            label, is_selected = _location_normalize(_text(option)), _selected(option)
            if label in wanted and is_selected is not True:
                option.click()
            elif label not in wanted and is_selected is True and _attribute(option, "role") in {"checkbox", "menuitemcheckbox"}:
                option.click()
        submit = _wait(driver, lambda *_: _first(_find(driver, MENU_SUBMIT_XPATH)), timeout, wait)
        submit.click()
        # Re-open to confirm actual committed options, not just a changed URL.
        query = (before.get("keywords") or [_prompt_text(driver)])[0]
        _settle(driver, query, timeout=timeout, wait=wait)
        _record_parameter_change(driver, key, before, owners)
        if not _filter(driver, key, desired, verify_only=True, timeout=timeout, wait=wait):
            raise SearchUIError(f"Committed LinkedIn filter does not match {key}", stage="filter_validation", details={"filter": key})
        return True
    except SearchUIError:
        raise
    except Exception as error:
        raise SearchUIError(f"LinkedIn filter {key} could not be verified", stage="filter", details={"filter": key, "error_type": type(error).__name__}) from error


def _location_label(driver):
    picker = _first(_find(driver, LOCATION_PICKER_XPATH))
    if picker is None or _attribute(picker, "aria-expanded") == "true":
        return ""
    paragraphs = _find(picker, ".//p")
    return _text(paragraphs[0]) if paragraphs else _text(picker)


def verify_modern_location(driver, desired):
    label = _location_label(driver)
    if not label or not _location_matches(label, desired):
        return None
    if not search_results_ready(driver):
        return None
    query = parse_qs(urlparse(_url(driver)).query)
    if query.get("location") and not all(_location_matches(value, desired) for value in query["location"]):
        return None
    return {"location": desired, "selected_label": label, "evidence": "committed_location_picker",
            "geography": {key: query[key] for key in ("geoId", "location") if query.get(key)}}


def _set_location(driver, desired, *, timeout=30, wait=None):
    proof = verify_modern_location(driver, desired)
    if proof and proof["geography"].get("geoId"):
        return proof
    try:
        picker = _wait(driver, lambda *_: _first(_find(driver, LOCATION_PICKER_XPATH)), timeout, wait)
        picker.click()
        editor = _wait(driver, lambda *_: _first(_find(driver, LOCATION_EDITOR_XPATH)), timeout, wait)
        fill_text(editor, desired)
        expected_geo, clicked = None, False
        def commit_suggestion(*_):
            nonlocal expected_geo, clicked
            check_access(driver)
            committed = verify_modern_location(driver, desired)
            if committed and (clicked or expected_geo):
                if not expected_geo or committed["geography"].get("geoId") == expected_geo:
                    return committed
            if clicked:
                return False
            options = [option for option in _find(driver, "//a[contains(@href,'geoId=')] | //*[@role='option']")
                       if _visible(option) and _location_matches(_text(option), desired)]
            exact = [option for option in options if _location_normalize(_text(option)) == _location_normalize(desired)]
            options = exact or options
            if len(options) > 1:
                raise LocationSelectionError("Multiple matching LinkedIn location suggestions")
            if not options:
                return False
            option = options[0]
            href = _attribute(option, "href")
            if href:
                destination = urlparse(urljoin(_url(driver), href))
                if destination.hostname not in {"linkedin.com", "www.linkedin.com"} or not destination.path.startswith("/jobs/"):
                    raise LocationSelectionError("Location suggestion leaves the LinkedIn jobs interface")
                expected_geo = parse_qs(destination.query).get("geoId")
            # A refreshed suggestion can detach between locating and clicking.
            # _wait retries only Selenium staleness, re-finding the exact label
            # and checking its destination each time. A committed selection is
            # recognized on the next poll without clicking a second time.
            option.click()
            clicked = True
            return False
        return _wait(driver, commit_suggestion, timeout, wait)
    except SearchUIError:
        raise
    except Exception as error:
        raise SearchUIError("Configured modern LinkedIn location was not committed", stage="location", details={"location": desired, "error_type": type(error).__name__}) from error


def _apply_filters(driver, intent, *, verify_only=False, expected=None, timeout=30, wait=None, owners=None):
    report, verified, warnings = {}, [], []
    arrangements = _values(intent.get("on_site"))
    if arrangements and set(arrangements) != {"Remote"}:
        remote = _facet(driver, "on_site", ["Remote"])
        if remote is not None and _is_pill(remote) and _selected(remote) is True:
            if verify_only:
                raise SearchUIError("Remote-only filter narrows configured work arrangements", stage="filter_validation", details={"filter": "on_site"})
            _click_target(remote).click()
            _wait(driver, lambda *_: _selected(_facet(driver, "on_site", ["Remote"])) is False, timeout, wait)
            query = (parse_qs(urlparse(_url(driver)).query).get("keywords") or [_prompt_text(driver)])[0]
            _settle(driver, query, timeout=timeout, wait=wait)
    wanted_keys = list(expected) if expected is not None else list(intent)
    for key in wanted_keys:
        value = intent.get(key)
        if not _values(value) or key == "search_location":
            continue
        desired = _values(value)
        if key == "on_site" and len(desired) > 1:
            # A Remote-only toggle would discard configured Hybrid results.
            report[key] = {"status": "prompt_only", "requested": desired}
            warnings.append("Work arrangement remains in the prompt; Remote and Hybrid are not narrowed to Remote only")
            continue
        if key not in FILTER_LABELS:
            report[key] = {"status": "unavailable", "requested": desired}
            warnings.append(f"Filter unavailable in modern search: {key}={value}")
            continue
        matched = _filter(driver, key, desired, verify_only=verify_only, timeout=timeout, wait=wait, owners=owners)
        report[key] = {"status": "verified" if matched else "unavailable", "requested": desired}
        if matched:
            verified.append(key)
        elif verify_only or key == "easy_apply_only":
            raise SearchUIError(f"Required LinkedIn filter state is unverified: {key}", stage="filter_validation", details={"filter": key, "filter_report": report})
        else:
            warnings.append(f"Filter unavailable in modern search: {key}={value}")
    return report, verified, warnings


def _verify_work_arrangement(driver, intent):
    arrangements = _values(intent.get("on_site"))
    if arrangements and set(arrangements) != {"Remote"}:
        remote = _facet(driver, "on_site", ["Remote"])
        if remote is not None and _is_pill(remote) and _selected(remote) is True:
            raise SearchUIError("Remote-only filter narrows configured work arrangements", stage="filter_validation", details={"filter": "on_site"})


def _locale(driver):
    elements = _find(driver, "//html")
    return _attribute(elements[0], "lang") if elements else ""


def get_recipe_cache(driver):
    session = getattr(driver, "session_id", None)
    key = session if isinstance(session, str) and session else driver
    return _SESSION_RECIPES.setdefault(key, {})


def clear_recipe_cache(driver=None):
    if driver is None:
        _SESSION_RECIPES.clear()
    else:
        get_recipe_cache(driver).clear()


def _recipe_key(driver, intent):
    fingerprint = hashlib.sha256(json.dumps(intent, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return (_locale(driver), "modern_prompt", fingerprint)


def _learn_recipe(driver, intent, result):
    parsed = urlparse(_url(driver))
    if parsed.hostname not in {"linkedin.com", "www.linkedin.com"} or parsed.path != "/jobs/search-results/":
        return
    owned = {name for names in result.notes.get("parameter_owners", {}).values() for name in names}
    parameters = {key: values for key, values in parse_qs(parsed.query).items() if key == "geoId" or key in owned}
    # Whole-intent cache only; opaque f_* names never determine semantic labels.
    get_recipe_cache(driver)[_recipe_key(driver, intent)] = {
        "route": parsed.path, "parameters": parameters, "verified_filters": list(result.verified_filters),
        "filter_report": deepcopy(result.filter_report), "warnings": list(result.warnings),
    }


def finish_modern_search(driver, spec, result, *, wait_for_results=None, timeout=30, wait=None):
    intent = spec.filters_snapshot.get("intent", {})
    owners = {}
    report, verified, warnings = _apply_filters(driver, intent, timeout=timeout, wait=wait, owners=owners)
    location = intent.get("search_location") or ""
    if location:
        result.location_confirmation = _set_location(driver, location, timeout=timeout, wait=wait)
        verified.append("search_location")
    result.filter_report, result.verified_filters = report, verified
    result.warnings.extend(warnings)
    result.results_state = _settle(driver, spec.query_text, timeout=timeout, wait=wait)
    _verify_work_arrangement(driver, intent)
    final_report, final_verified, _ = _apply_filters(driver, intent, verify_only=True,
                                                     expected=[key for key in verified if key != "search_location"], timeout=timeout, wait=wait)
    result.filter_report.update(final_report)
    result.verified_filters = final_verified + (["search_location"] if location else [])
    result.results_state = _settle(driver, spec.query_text, timeout=timeout, wait=wait)
    if location and not verify_modern_location(driver, location):
        raise SearchUIError("Location was reset by modern LinkedIn filters", stage="location_validation")
    result.notes["parameter_owners"] = owners
    _learn_recipe(driver, intent, result)
    return result


def prepare_modern_search(driver, spec, *, wait_for_search=None, wait_for_results=None, timeout=30, wait=None):
    check_access(driver)
    intent = spec.filters_snapshot.get("intent", {})
    key, cache = _recipe_key(driver, intent), get_recipe_cache(driver)
    recipe, replay_failure = cache.get(key), None
    if recipe:
        parameters = {**recipe["parameters"], "keywords": [spec.query_text]}
        try:
            if recipe.get("route") != "/jobs/search-results/":
                raise SearchUIError("Learned LinkedIn route is unsupported", stage="replay_route")
            driver.get("https://www.linkedin.com" + recipe["route"] + "?" + urlencode(parameters, doseq=True))
            check_access(driver)
            result = SearchResult("ai", ui_variant="modern_prompt", transport="verified_url", executed_query=spec.query_text)
            result.results_state = _settle(driver, spec.query_text, timeout=timeout, wait=wait)
            _verify_work_arrangement(driver, intent)
            expected = [item for item in recipe["verified_filters"] if item != "search_location"]
            report, verified, _ = _apply_filters(driver, intent, verify_only=True, expected=expected, timeout=timeout, wait=wait)
            location = intent.get("search_location") or ""
            if location:
                result.location_confirmation = verify_modern_location(driver, location)
                if result.location_confirmation is None:
                    raise SearchUIError("URL replay did not apply configured location", stage="replay_location")
                verified.append("search_location")
            result.filter_report = {**deepcopy(recipe["filter_report"]), **report}
            result.verified_filters, result.warnings = verified, list(recipe["warnings"])
            result.results_state = _settle(driver, spec.query_text, timeout=timeout, wait=wait)
            if location and not verify_modern_location(driver, location):
                raise SearchUIError("Replayed location changed during filter verification", stage="replay_location")
            return result
        except SearchUIError as error:
            if error.stage == "auth_required":
                raise
            replay_failure = error.diagnostics()
        except Exception as error:
            replay_failure = {"stage": "replay", "error_type": type(error).__name__}
        cache.pop(key, None)
    driver.get("https://www.linkedin.com/jobs/")
    check_access(driver)
    if wait_for_search:
        wait_for_search()
    result = start_modern_search(driver, spec, wait_for_results=wait_for_results, timeout=timeout, wait=wait)
    if replay_failure:
        result.notes["replay_rejected"] = replay_failure
        result.warnings.append("Learned URL state was stale; rebuilt and verified through native search controls")
    return finish_modern_search(driver, spec, result, wait_for_results=wait_for_results, timeout=timeout, wait=wait)


def _active_page(pagination):
    active = _first(_find(pagination, ".//*[@aria-current='page' or @aria-current='true' or @aria-pressed='true' or @aria-checked='true' or contains(@class,'active')]"))
    digits = re.search(r"\d+", _text(active) or _attribute(active, "aria-label")) if active is not None else None
    return int(digits.group()) if digits else None


def get_search_pagination(driver):
    pagination = _first(_find(driver, PAGINATION_XPATH))
    if pagination is None:
        return None, 1
    return pagination, _active_page(pagination) or 1


def next_search_page(driver, page, *, timeout=30, wait=None):
    pagination, _ = get_search_pagination(driver)
    if pagination is None:
        return False
    label = "Page " + str(page + 1)
    options = _find(pagination, ".//button | .//a | .//*[@role='button']")
    next_button = next((item for item in options if _visible(item) and (
        _attribute(item, "aria-label") == label or _text(item) == str(page + 1)
        or _attribute(item, "aria-label").casefold() in {"next", "next page", "view next page"})), None)
    if next_button is None or _attribute(next_button, "aria-disabled") == "true":
        return False
    before = parse_qs(urlparse(_url(driver)).query)
    next_button.click()
    def committed(*_):
        check_access(driver)
        current_pagination, _ = get_search_pagination(driver)
        if current_pagination is None:
            return False
        selected = _active_page(current_pagination)
        query = parse_qs(urlparse(_url(driver)).query)
        if selected is not None:
            moved = selected == page + 1
        else:
            moved = False
            for key in ("start", "page", "pageNum"):
                old, new = (before.get(key) or ["0"])[0], (query.get(key) or ["0"])[0]
                if old.isdigit() and new.isdigit() and int(new) > int(old):
                    moved = True
        return bool(moved and search_results_ready(driver))
    try:
        _wait(driver, committed, timeout, wait)
        legacy_classic = (_first(_find(driver, CLASSIC_INPUT_XPATH)) is not None
                          and _first(_find(driver, PROMPT_XPATH)) is None)
        if detect_modern_ui(driver) and not legacy_classic:
            query = (before.get("keywords") or [_prompt_text(driver)])[0]
            _settle(driver, query, timeout=timeout, wait=wait)
    except SearchUIError:
        raise
    except Exception as error:
        raise SearchUIError("LinkedIn next page did not commit", stage="pagination", details={"requested_page": page + 1, "error_type": type(error).__name__}) from error
    return True

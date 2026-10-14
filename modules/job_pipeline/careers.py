"""Verify employer careers through public ATS APIs or official structured pages."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import parse_qsl, quote, urlencode, urlparse

from .http import Document, FetchError, PublicHTTPClient, embedded_json, error, fetch_page, now, objects, plain_text, public_url, render_page
from .sources import ATS_HOSTS, domain_of, provenance, setting, stable_id
from .settings import company_maturity


BAY_AREA_CITIES = (
    "san francisco", "bay area", "san jose", "oakland", "berkeley", "palo alto",
    "mountain view", "sunnyvale", "santa clara", "menlo park", "redwood city",
    "san mateo", "foster city", "south san francisco", "burlingame", "cupertino",
    "fremont", "san carlos", "millbrae", "emeryville", "walnut creek", "pleasanton",
)
TECH_TITLE = re.compile(r"\b(?:software|systems?|inference|sdk|infrastructure|platform|backend|back-end|machine learning|ml|ai|distributed|founding|full.?stack|frontend|front-end|data|developer tools)\b", re.I)
OCCUPATION = re.compile(r"\b(?:engineer|engineering|developer|architect|mts|member(?: of)? technical staff|research scientist)\b", re.I)
NO_OPENINGS = re.compile(r"\b(?:no (?:current |open |available )?(?:positions|openings|jobs)|not currently hiring|we are not hiring|position (?:is )?no longer available|job (?:has )?expired|role has been filled)\b", re.I)
NO_COMPANY_OPENINGS = re.compile(r"\b(?:no (?:current |open |available )?(?:positions|openings|jobs)|not currently hiring|we are not hiring)\b", re.I)


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=timezone.utc) if result.tzinfo is None else result
    except ValueError:
        return None


def _strings(value):
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_strings(item))
        return result
    if isinstance(value, dict):
        if isinstance(value.get("location"), str):
            return [value["location"]]
        if isinstance(value.get("name"), str):
            return [value["name"]]
        address = value.get("address", value.get("postalAddress", value))
        return [", ".join(str(address[key]) for key in ("addressLocality", "addressRegion", "addressCountry") if address.get(key))] if isinstance(address, dict) else []
    return []


def _employment(value, description=""):
    normalized = re.sub(r"[^a-z]", "", str(value or "").casefold())
    mapping = {"fulltime": "Full-time", "parttime": "Part-time", "contract": "Contract", "temporary": "Temporary", "intern": "Internship", "internship": "Internship", "volunteer": "Volunteer"}
    if normalized in mapping:
        return mapping[normalized]
    match = re.search(r"\b(full[ -]?time|part[ -]?time|contract|internship|temporary)\b"
                      r"(?=\s+(?:(?!employees?\b|benefits?\b)\w+\s+){0,3}(?:role|position|job|employment)\b)", description, re.I)
    if match is None:
        match = re.search(r"(?:employment(?: type)?|job type|commitment)\s*:\s*(full[ -]?time|part[ -]?time|contract|internship|temporary)\b", description, re.I)
        return _employment(match.group(1)) if match else "Unknown"
    return _employment(match.group(0)) if match else "Unknown"


def _workplace(value, locations, description="", remote=None):
    normalized = re.sub(r"[^a-z]", "", str(value or "").casefold())
    if normalized in {"remote", "telecommute"}:
        return "Remote"
    if normalized == "hybrid":
        return "Hybrid"
    if normalized in {"onsite", "office"}:
        return "On-site"
    if remote is True:
        return "Remote"
    location_text = " ".join(locations)
    if re.search(r"\bhybrid\b", location_text, re.I):
        return "Hybrid"
    if re.search(r"\bremote\b", location_text, re.I):
        return "Remote"
    if re.search(r"\b(?:on.site|onsite|in.person|office.based|in.office)\b", location_text, re.I):
        return "On-site"
    # A technical reference to hybrid cloud or remote execution is not work policy.
    policy = description.casefold()
    hybrid = re.search(r"\bhybrid\s+(?!cloud\b)(?:\w+\s+){0,3}(?:role|position|job|work|working|schedule|arrangement|model)\b|\b(?:role|position|workplace)\s+(?:is\s+)?hybrid\b", policy)
    remote_policy = re.search(r"\b(?:fully\s+)?remote\s+(?!execution\b|access\b)(?:\w+\s+){0,3}(?:role|position|job|working|arrangement)\b|\b(?:role|position)\s+is\s+(?:fully\s+)?remote\b|\bwork remotely\b", policy)
    onsite = re.search(r"\b(?:on.site|onsite|in.person|office.based|in.office)\s+(?:\w+\s+){0,3}(?:role|position|job|work|working|schedule)\b|\b(?:role|position)\s+is\s+(?:on.site|onsite|in.person)\b", policy)
    if hybrid:
        return "Hybrid"
    if remote_policy and not onsite:
        return "Remote"
    if onsite and not remote_policy:
        return "On-site"
    return "Unknown"


def priority_tier(company, title, config=None):
    if re.search(r"\bfounding\b", title, re.I):
        return 3
    maturity = company_maturity(company, config)
    if maturity == "established":
        leveled_title = re.sub(r"\bmember(?: of)? technical staff\b", "", title, flags=re.I)
        return 1 if re.search(r"\b(?:staff|principal)\b", leveled_title, re.I) else 2
    if maturity == "early":
        return 3
    return 4


def role_record(company, row, origin, kind="official_careers"):
    title = row.get("title") or row.get("name") or row.get("text")
    if not isinstance(title, str) or not title.strip():
        return None
    description = plain_text(row.get("descriptionPlain") or row.get("descriptionHtml") or row.get("description") or row.get("content") or "")
    url = public_url(row.get("jobUrl") or row.get("absolute_url") or row.get("hostedUrl") or row.get("url") or row.get("@id") or row.get("applyLink"), origin)
    if not url:
        return None
    parsed = urlparse(url)
    query = [(key, value) for key, value in parse_qsl(parsed.query) if not key.lower().startswith(("utm_", "lever-source", "gh_src"))]
    url = parsed._replace(query=urlencode(query)).geturl()
    locations = _strings(row.get("locations") or row.get("location") or row.get("jobLocation"))
    locations.extend(_strings(row.get("secondaryLocations")))
    locations.extend(_strings(row.get("applicantLocationRequirements")))
    locations = list(dict.fromkeys(location for location in locations if location.strip()))
    workplace = _workplace(row.get("workplaceType") or row.get("workplace_type") or row.get("jobLocationType"), locations, description, row.get("isRemote"))
    employment = _employment(row.get("employmentType") or row.get("employment_type"), description)
    valid_through = _date(row.get("validThrough"))
    status = row.get("status", "open")
    if status not in {"open", "closed", "unknown"}:
        status = "unknown"
    if valid_through and valid_through < datetime.now(timezone.utc) or NO_OPENINGS.search(description):
        status = "closed"
    is_prospect = row.get("is_prospect") is True
    if is_prospect:
        status = "unknown"
    return {
        "id": stable_id("role", url), "company_id": company["id"], "company": deepcopy(company),
        "title": plain_text(title), "description": description, "career_url": url,
        "locations": locations, "workplace_type": workplace, "employment_type": employment,
        "eligible": False, "exclusion_reasons": [], "status": status, "verified_at": now(),
        "is_prospect": is_prospect,
        "priority_tier": priority_tier(company, title),
        "sources": [*deepcopy(company.get("sources", [])), provenance(kind, origin, row.get("id"), "career_verification")],
        "published_at": row.get("publishedAt") or row.get("datePosted"),
        "salary": deepcopy(row.get("compensation") or row.get("baseSalary")),
    }


def location_reasons(locations, workplace_type, configured_location):
    """Shared geographic gate for official roles and LinkedIn application jobs."""
    desired = str(configured_location or "").casefold()
    if not desired:
        return []
    locations = " ".join(locations).casefold()
    if "bay area" in desired or "san francisco" in desired:
        located = any(city in locations for city in BAY_AREA_CITIES)
        us_remote = workplace_type == "Remote" and bool(re.search(r"\b(?:united states|usa|us|u\.s\.|north america|worldwide|global|california)\b", locations))
        matched = located or us_remote
    else:
        terms = [term.strip() for term in desired.split(",") if term.strip()]
        matched = bool(locations and terms and terms[0] in locations)
        if workplace_type == "Remote" and terms:
            country = terms[-1] if len(terms) > 1 else terms[0]
            matched = matched or country in locations or bool(re.search(r"\b(?:worldwide|global)\b", locations))
    if matched:
        return []
    return ["unknown_location" if not locations or locations.strip() in {"remote", "hybrid", "unknown", "n/a", "not available"} else "location_excluded"]


def evaluate_role(role, search_config):
    """Apply canonical requirements without claiming missing evidence is a match."""
    reasons = []
    title, description = role["title"], role["description"]
    lowered = description.casefold()
    if role["status"] != "open":
        reasons.append("role_closed" if role["status"] == "closed" else "unverified_open_status")
    if role.get("is_prospect") is True:
        reasons.append("prospect_post_not_verified_vacancy")
    if lowered.strip() in {"", "unknown", "n/a", "not available", "notavailable"}:
        reasons.append("missing_full_description")
        # Failed live selectors cannot disprove exclusions established from a full JD.
        reasons.extend(reason for reason in role.get("exclusion_reasons", [])
                       if reason.startswith("description_exclusion:") or reason in {"security_clearance_required", "experience_excluded"})
    if not OCCUPATION.search(title) or not (TECH_TITLE.search(title) or re.search(r"\b(?:mts|member(?: of)? technical staff)\b", title, re.I)):
        reasons.append("outside_role_families")
    preferences = setting(search_config, "on_site", []) or []
    if preferences and role["workplace_type"] not in preferences:
        reasons.append("unknown_workplace_type" if role["workplace_type"] == "Unknown" else "workplace_type_excluded")
    job_types = setting(search_config, "job_type", []) or []
    if job_types and role["employment_type"] not in job_types:
        reasons.append("unknown_employment_type" if role["employment_type"] == "Unknown" else "employment_type_excluded")
    reasons.extend(location_reasons(role["locations"], role["workplace_type"], setting(search_config, "search_location", "")))
    companies = setting(search_config, "companies", []) or []
    names = [role["company"]["name"]]
    aliases = role["company"].get("aliases", [])
    for alias in aliases if isinstance(aliases, list) else []:
        name = alias.get("name") if isinstance(alias, dict) else alias
        if isinstance(name, str) and name.strip() and not re.search(r"https?://|^[a-z0-9-]+\.[a-z]{2,}$", name.strip(), re.I):
            names.append(name)
    if companies and not any(name.casefold() == value.casefold() for name in names for value in companies):
        reasons.append("company_excluded")
    company_text = str(role["company"].get("description") or "").casefold()
    good_words = setting(search_config, "about_company_good_words", []) or []
    if not any(word.casefold() in company_text for word in good_words):
        for word in setting(search_config, "about_company_bad_words", []) or []:
            if word.casefold() in company_text:
                reasons.append("company_description_exclusion:" + word)
    for word in setting(search_config, "bad_words", []) or []:
        if word.casefold() in lowered:
            reasons.append("description_exclusion:" + word)
    if setting(search_config, "security_clearance", True) is False and re.search(r"security clearance|polygraph", lowered):
        reasons.append("security_clearance_required")
    years = setting(search_config, "current_experience", -1)
    if type(years) is int and years >= 0:
        required = [int(value) for value in re.findall(r"\b(\d+)(?:\s*[-–]\s*\d+)?\+?\s+years?\b", lowered)]
        allowance = 2 if setting(search_config, "did_masters", False) and "master" in lowered else 0
        if required and max(required) > years + allowance:
            reasons.append("experience_excluded")
        if not required:
            reasons.append("unknown_required_experience")
    posted = setting(search_config, "date_posted", "")
    windows = {"Past 24 hours": 1, "Past week": 7, "Past month": 30}
    if posted in windows:
        date = _date(role.get("published_at"))
        if date is None:
            reasons.append("unknown_posted_date")
        elif date < datetime.now(timezone.utc) - timedelta(days=windows[posted]):
            reasons.append("posted_date_excluded")
    # LinkedIn-only preferences are preserved for that later stage, never claimed here.
    role["unverified_preferences"] = [key for key in (
        "salary", "experience_level", "location", "industry", "job_function", "job_titles", "benefits", "commitments",
        "under_10_applicants", "in_your_network", "fair_chance_employer", "easy_apply_only",
    ) if setting(search_config, key)]
    role["exclusion_reasons"] = list(dict.fromkeys(reasons))
    role["eligible"] = not reasons
    return role


def _ats(url):
    safe = public_url(url)
    if not safe:
        return None
    parsed = urlparse(safe)
    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return None
    if parsed.hostname == "jobs.ashbyhq.com":
        return "ashby", parts[0]
    if parsed.hostname in {"boards.greenhouse.io", "job-boards.greenhouse.io"}:
        return "greenhouse", parts[0]
    if parsed.hostname in {"jobs.lever.co", "jobs.eu.lever.co"}:
        return "lever_eu" if parsed.hostname == "jobs.eu.lever.co" else "lever", parts[0]
    return None


def _board_url(url):
    board = _ats(url)
    if not board:
        return url
    parsed = urlparse(url)
    return parsed._replace(path="/" + board[1], params="", query="", fragment="").geturl()


def _board(company, board, client, timeout, max_pages):
    kind, slug = board
    rows, errors = [], []
    slug = quote(slug, safe="")
    if kind == "ashby":
        url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    elif kind == "greenhouse":
        url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    else:
        host = "api.eu.lever.co" if kind == "lever_eu" else "api.lever.co"
        url = f"https://{host}/v0/postings/{slug}?mode=json&limit=100&skip=0"
    complete = True
    for page_number in range(max_pages):
        try:
            page = fetch_page(url, client, timeout)
            if kind in {"ashby", "greenhouse"}:
                if not isinstance(page.data, dict) or not isinstance(page.data.get("jobs"), list):
                    raise FetchError("schema_changed", "Public ATS response has no jobs array", page.url)
                jobs = page.data["jobs"]
            else:
                if not isinstance(page.data, list):
                    raise FetchError("schema_changed", "Public Lever response is not a postings array", page.url)
                jobs = page.data
        except FetchError as exc:
            errors.append(error(kind, exc.code, exc, exc.url, exc.retryable))
            return rows, errors, False
        for job in jobs:
            if not isinstance(job, dict):
                errors.append(error(kind, "malformed_posting", "ATS posting is not an object", page.url))
                continue
            if kind == "ashby" and job.get("isListed") is False:
                continue
            row = dict(job)
            if kind.startswith("lever"):
                categories = job.get("categories") or {}
                if not isinstance(categories, dict):
                    errors.append(error(kind, "malformed_posting", "Lever categories is not an object", page.url))
                    continue
                row["location"] = categories.get("allLocations") or categories.get("location")
                row["employmentType"] = categories.get("commitment")
                sections = [job.get("descriptionPlain") or job.get("description") or "", job.get("additionalPlain") or job.get("additional") or ""]
                sections.extend(str(section.get("text", "")) + " " + str(section.get("content", "")) for section in job.get("lists", []) if isinstance(section, dict))
                row["description"] = " ".join(section for section in sections if isinstance(section, str))
                row["descriptionPlain"] = plain_text(row["description"])
            row["is_prospect"] = kind == "greenhouse" and "internal_job_id" in job and job["internal_job_id"] is None
            row["status"] = "unknown" if row["is_prospect"] else "open"
            role = role_record(company, row, page.url, kind)
            if role:
                rows.append(role)
            else:
                errors.append(error(kind, "malformed_posting", "ATS posting lacks a title or public URL", page.url))
        if not kind.startswith("lever") or len(jobs) < 100:
            break
        if page_number + 1 == max_pages:
            complete = False
            errors.append(error(kind, "pagination_limit", "Lever board exceeded bounded page limit", page.url, True))
        url = re.sub(r"skip=\d+", f"skip={(page_number + 1) * 100}", url)
    if any(role.get("is_prospect") for role in rows):
        errors.append(error(kind, "unverified_vacancies", "Prospect posts do not verify current vacancies; prior roles cannot be retired from this observation", url))
        complete = False
    return rows, errors, complete and not errors


def _career_links(page):
    document = Document(page.text)
    candidates = []
    for node in document.nodes():
        if node.tag in {"a", "iframe"}:
            value = node.attrs.get("href") if node.tag == "a" else node.attrs.get("src")
            url = public_url(value, page.url)
            label = plain_text(node.text()).casefold()
            if url and (_ats(url) or re.search(r"/(?:careers?|jobs|join(?:-us)?)(?:/|$)", urlparse(url).path) or label in {"careers", "jobs", "join us", "open positions", "view open roles"}):
                candidates.append(url)
        if node.tag == "meta" and node.attrs.get("http-equiv", "").casefold() == "refresh":
            match = re.search(r"url\s*=\s*['\"]?([^'\"]+)", node.attrs.get("content", ""), re.I)
            if match:
                url = public_url(match.group(1), page.url)
                if url:
                    candidates.append(url)
    # Employer SSR payloads often include ATS apply links before hydration.
    for value in embedded_json(document):
        for row in objects(value):
            for key in ("href", "src", "url", "jobUrl", "applyUrl", "applyLink", "hostedUrl", "careersUrl"):
                url = public_url(row.get(key), page.url) if isinstance(row.get(key), str) else None
                if url and _ats(url):
                    candidates.append(url)
    return sorted(dict.fromkeys(_board_url(url) for url in candidates), key=lambda url: _ats(url) is None), document


def _generic_roles(company, page):
    document = Document(page.text)
    roles, postings, issues = [], [], []
    for value in ([page.data] if page.data is not None else embedded_json(document)):
        for row in objects(value):
            types = row.get("@type", [])
            types = [types] if isinstance(types, str) else types if isinstance(types, list) else []
            if "JobPosting" in types:
                postings.append(row)
    for row in postings:
        url = row.get("url") or row.get("@id") or (page.url if len(postings) == 1 else None)
        role = role_record(company, dict(row, url=url), page.url)
        if role:
            roles.append(role)
        else:
            issues.append(error(company["name"], "malformed_posting", "Published JobPosting lacks a title or distinct public role URL", page.url))
    if not roles:
        headings = document.nodes("h1")
        title = plain_text(headings[0].text()) if len(headings) == 1 else ""
        descriptions = [node for node in document.nodes() if (
            node.attrs.get("itemprop") == "description" or re.search(r"job[-_]description", node.attrs.get("class", "") + " " + node.attrs.get("id", "")))]
        description = plain_text(descriptions[0].text()) if descriptions else ""
        active = any(plain_text(node.text()).casefold() in {"apply", "apply now", "apply for this job", "apply for this role"}
                     for node in document.nodes() if node.tag in {"button", "a"})
        closed = bool(NO_OPENINGS.search(document.root.text()))
        if OCCUPATION.search(title) and description:
            properties = {}
            for node in document.nodes():
                key = node.attrs.get("itemprop")
                if key in {"jobLocation", "jobLocationType", "employmentType", "datePosted", "validThrough"}:
                    properties[key] = node.attrs.get("content") or plain_text(node.text())
                for attribute, key in {"data-location": "location", "data-employment-type": "employmentType", "data-workplace-type": "workplaceType"}.items():
                    if node.attrs.get(attribute):
                        properties[key] = node.attrs[attribute]
            role = role_record(company, dict(properties, title=title, description=description, url=page.url,
                                            status="closed" if closed else "open" if active else "unknown"), page.url)
            if role:
                roles.append(role)
    return roles, document, issues


def verify_company(company, search_config, client=None, render=None):
    if not isinstance(company, dict) or not company.get("id") or not company.get("name"):
        raise ValueError("Verification requires a company record with id and name")
    timeout = setting(search_config, "request_timeout", 12)
    max_pages = setting(search_config, "max_career_pages", 10)
    if type(max_pages) is not int or max_pages < 1:
        raise ValueError("max_career_pages must be a positive integer")
    client = client or PublicHTTPClient(timeout=timeout)
    career = public_url(company.get("careers_url"))
    website = public_url(company.get("website"))
    queue = [_board_url(career or website)] if career or website else []
    if not queue:
        return {"records": [], "errors": [error(company["name"], "missing_official_site", "No official website or careers URL is known")], "status": "unknown", "complete": False}
    rows, errors, visited, boards = [], [], set(), set()
    trusted_empty = False
    parsed_any = False
    complete = True
    while queue and len(visited) < max_pages:
        url = queue.pop(0)
        if url in visited:
            continue
        visited.add(url)
        board = _ats(url)
        try:
            if board:
                if board in boards:
                    continue
                boards.add(board)
                found, issues, board_complete = _board(company, board, client, timeout, max_pages)
                rows.extend(found)
                errors.extend(issues)
                parsed_any = True
                trusted_empty = trusted_empty or not found and board_complete
                complete = complete and board_complete
                if board_complete:
                    queue = [candidate for candidate in queue if _ats(candidate) and _ats(candidate) not in boards]
                continue
            page = fetch_page(url, client, timeout)
            links, document = _career_links(page)
            found, _, issues = _generic_roles(company, page)
            errors.extend(issues)
            if not found and not links and render is not None and not NO_OPENINGS.search(document.root.text()):
                page = render_page(page.url, render)
                links, document = _career_links(page)
                found, _, issues = _generic_roles(company, page)
                errors.extend(issues)
            if found:
                parsed_any = True
                for role in found:
                    if not role["description"]:
                        detail = fetch_page(role["career_url"], client, timeout)
                        detail_roles, _, detail_issues = _generic_roles(company, detail)
                        errors.extend(detail_issues)
                        role = next((item for item in detail_roles if item["career_url"] == role["career_url"]), role)
                    rows.append(role)
            official = domain_of(company.get("website"))
            for link in links:
                if _ats(link) or domain_of(link) == official or domain_of(link) == domain_of(page.url):
                    if link not in visited and link not in queue:
                        queue.append(link)
            if not links and NO_COMPANY_OPENINGS.search(document.root.text()):
                parsed_any = trusted_empty = True
            # Plain official job lists require reading job detail pages for full text.
            for anchor in document.nodes("a"):
                title = plain_text(anchor.text())
                link = public_url(anchor.attrs.get("href"), page.url)
                if (link and domain_of(link) == domain_of(page.url) and TECH_TITLE.search(title) and OCCUPATION.search(title)
                        and re.search(r"/(?:careers|jobs)/[^/]+", urlparse(link).path)
                        and link not in visited and link not in queue):
                    queue.append(link)
            if not found and not links and not parsed_any and not trusted_empty and not queue:
                complete = False
        except FetchError as exc:
            errors.append(error(company["name"], exc.code, exc, exc.url, exc.retryable))
            complete = False
    if queue:
        errors.append(error(company["name"], "pagination_limit", "Career traversal exceeded bounded page limit", queue[0], True))
        complete = False
    deduplicated = {}
    for row in rows:
        previous = deduplicated.get(row["id"])
        if previous is None or len(row["description"]) > len(previous["description"]):
            deduplicated[row["id"]] = evaluate_role(row, search_config)
    records = sorted(deduplicated.values(), key=lambda role: (role["priority_tier"], role["title"].casefold(), role["id"]))
    for role in records:
        if not role["description"]:
            errors.append(error(company["name"], "missing_full_description", "Posting exists but its full description could not be verified", role["career_url"]))
            complete = False
    if records and not boards:
        entry = company.get("careers_url") or company.get("website") or ""
        path = urlparse(entry).path.rstrip("/").casefold()
        if path not in {"/careers", "/career", "/jobs", "/join-us", "/join"}:
            errors.append(error(company["name"], "incomplete_coverage", "A job detail verifies its role, not the employer's entire careers board", entry))
            complete = False
    if any(role["status"] == "open" for role in records):
        status = "hiring"
    elif trusted_empty and complete and not errors:
        status = "not_hiring"
    else:
        status = "unknown"
    if not parsed_any and not errors:
        errors.append(error(company["name"], "needs_render", "Official pages expose no verifiable public job board; render normally or supply an authorized export", company.get("careers_url") or company.get("website")))
        complete = False
    return {"records": records, "errors": errors, "status": status, "complete": complete and not errors}

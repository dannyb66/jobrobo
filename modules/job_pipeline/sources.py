"""Public company discovery with source provenance and resumable page offsets."""

from copy import deepcopy
import hashlib
import re
from urllib.parse import quote, urlparse

from .http import Document, FetchError, PublicHTTPClient, embedded_json, error, fetch_page, now, objects, plain_text, public_url, render_page


SOURCE_URLS = {
    "greylock": "https://greylock.com/jobs/portfolio-jobs/companies/",
    "sequoia": "https://sequoiacap.com/our-companies",
    "a16z": "https://jobs.a16z.com/companies",
    "yc": "https://www.ycombinator.com/companies",
    "hiringcafe": "https://hiringcafe.com/",
    "wellfound": "https://wellfound.com/discover/startups",
    "crunchbase": "https://www.crunchbase.com/discover/organization.companies",
    "hn": "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&query=Who%20is%20hiring&hitsPerPage=3",
}
DEFAULT_SOURCES = tuple(SOURCE_URLS)
ATS_HOSTS = {"jobs.ashbyhq.com", "boards.greenhouse.io", "job-boards.greenhouse.io", "jobs.lever.co", "jobs.eu.lever.co"}
SOCIAL_HOSTS = {"linkedin.com", "twitter.com", "x.com", "youtube.com", "facebook.com", "github.com", "instagram.com"}


def stable_id(kind, value):
    normalized = " ".join(str(value).strip().casefold().split())
    return f"{kind}:" + hashlib.sha256(normalized.encode()).hexdigest()[:24]


def domain_of(url):
    url = public_url(url)
    return (urlparse(url).hostname or "").lower().removeprefix("www.") if url else None


def setting(config, key, default=None):
    return config.get(key, default) if isinstance(config, dict) else getattr(config, key, default)


def provenance(source, url, external_id=None, kind="public_discovery"):
    return {"name": source, "url": url, "observed_at": now(), "kind": kind, "external_id": str(external_id) if external_id is not None else None}


def _first(row, keys):
    return next((row[key] for key in keys if row.get(key) not in (None, "", [])), None)


def company_record(row, source, source_url):
    """Normalize facts provided by the source; unknown headcount/funding stay unknown."""
    name = _first(row, ("companyName", "company_name", "name", "display_name", "post_title"))
    if not isinstance(name, str) or not name.strip():
        return None
    name = plain_text(name).strip()
    website = _first(row, ("website", "website_url", "websiteUrl", "external_url", "companyWebsite", "websiteLink"))
    domain = _first(row, ("domain", "companyDomain", "company_domain"))
    raw_url = row.get("url")
    if not website and domain:
        website = public_url(domain)
    if not website and isinstance(raw_url, str) and public_url(raw_url, source_url):
        candidate = public_url(raw_url, source_url)
        if domain_of(candidate) != domain_of(source_url) and urlparse(candidate).hostname not in ATS_HOSTS:
            website = candidate
    website = public_url(website) if isinstance(website, str) else None
    domain = domain_of(website) if website else None
    if domain and (domain == domain_of(source_url) or domain in SOCIAL_HOSTS or urlparse(website).hostname in ATS_HOSTS):
        website = domain = None
    profile_url = _first(row, ("profile_url", "companyUrl", "company_url", "permalink"))
    if not profile_url and source == "greylock" and isinstance(row.get("slug"), str):
        profile_url = SOURCE_URLS["greylock"].removesuffix("companies/") + quote(row["slug"], safe="") + "/"
    profile_url = public_url(profile_url, source_url) if isinstance(profile_url, str) else None
    careers_url = _first(row, ("careers_url", "careersUrl", "career_url", "jobBoardUrl", "jobsUrl"))
    careers_url = public_url(careers_url, website or source_url) if isinstance(careers_url, str) else None
    count = _first(row, ("employee_count", "employeeCount", "headcount", "team_size", "teamSize", "numberOfEmployees"))
    if isinstance(count, dict):
        count = count.get("value")
    if not isinstance(count, (str, int)) or isinstance(count, bool):
        count = None
    stage = _first(row, ("funding_stage", "fundingStage", "stage"))
    aliases = row.get("aliases", [])
    if isinstance(aliases, str):
        aliases = [aliases]
    aliases = [alias for alias in aliases if isinstance(alias, str) and alias.strip()] if isinstance(aliases, list) else []
    description = _first(row, ("description", "companyOneLiner", "one_liner", "website_description", "short_description"))
    career_identity = None
    if careers_url and urlparse(careers_url).hostname in ATS_HOSTS:
        parsed = urlparse(careers_url)
        slug = parsed.path.strip("/").split("/", 1)[0]
        if slug:
            career_identity = parsed.hostname + "/" + slug
    return {
        "id": stable_id("company", profile_url or career_identity or domain or f"{source}:{name}"), "name": name, "domain": domain,
        "website": website, "careers_url": careers_url, "profile_url": profile_url,
        "sources": [provenance(source, profile_url or source_url, row.get("id"))],
        "employee_count": count, "funding_stage": stage if isinstance(stage, str) else None,
        "aliases": aliases, "description": plain_text(description),
    }


def _looks_like_company(row):
    if row.get("companyName") or row.get("company_name"):
        return True
    types = row.get("@type", [])
    types = [types] if isinstance(types, str) else types if isinstance(types, list) else []
    if "JobPosting" in types or "WebSite" in types or "WebPage" in types or "BreadcrumbList" in types:
        return False
    return bool(row.get("name") and (
        "Organization" in types or any(key in row for key in (
            "domain", "website", "website_url", "websiteUrl", "external_url", "headcount", "team_size", "funding_stage", "company_url"))
        or "slug" in row and "jobCount" in row))


def _name_from_node(node):
    for child in node.walk():
        text = plain_text(child.text())
        if child.tag in {"h1", "h2", "h3", "h4", "strong"} and text and not re.fullmatch(r"[\d,]+ jobs?", text, re.I):
            return text
    for child in node.walk():
        if child.tag == "img" and child.attrs.get("alt"):
            name = re.sub(r"^(?:Avatar for )?(?:Company )?logo for ", "", child.attrs["alt"], flags=re.I)
            return name.removesuffix(" logo").strip()
    for child in node.walk():
        leaves = [value.strip() for value in child.children if isinstance(value, str) and value.strip()]
        if leaves and len(leaves[0]) < 80 and not re.fullmatch(r"[\d,]+ jobs?", leaves[0], re.I):
            return leaves[0]
    return plain_text(node.text())[:120]


def _profile_link(source, path):
    patterns = {
        "greylock": r"/jobs/portfolio-jobs/([^/]+)/?$",
        "sequoia": r"/companies/([^/]+)/?$",
        "a16z": r"/(?:companies|jobs)/([^/]+)/?$",
        "yc": r"/companies/([^/]+)/?$",
        "wellfound": r"/company/([^/]+)/?$",
        "crunchbase": r"/organization/([^/]+)/?$",
    }
    match = re.search(patterns.get(source, r"(?!)"), path)
    return bool(match and match.group(1) not in {"companies", "jobs", "andreessen-horowitz", "greylock"})


def parse_companies(page, source):
    document = Document(page.text)
    values = [page.data] if page.data is not None else embedded_json(document)
    records = []
    for value in values:
        for row in objects(value):
            if _looks_like_company(row):
                company = company_record(row, source, page.url)
                if company and company["name"].casefold() not in {"greylock", "greylock partners", "andreessen horowitz", "a16z", "sequoia capital", "y combinator"}:
                    records.append(company)
    structured_a16z = source == "a16z" and any(company.get("domain") for company in records)
    for anchor in [] if structured_a16z else document.nodes("a"):
        href = public_url(anchor.attrs.get("href"), page.url)
        if not href or domain_of(href) != domain_of(page.url) or not _profile_link(source, urlparse(href).path):
            continue
        name = _name_from_node(anchor)
        if not name or name.casefold() in {"companies", "jobs", "learn more", "apply"} or re.fullmatch(r"[\d,]+ jobs?", name, re.I):
            continue
        company = company_record({"name": name, "profile_url": href}, source, page.url)
        if company:
            records.append(company)
    # Prefer richer structured rows over duplicate link cards.
    result, seen_names, seen_profiles = [], set(), set()
    for company in sorted(records, key=lambda row: row["website"] is None):
        key = company["name"].casefold()
        profile = company["profile_url"]
        if key in seen_names or profile and profile in seen_profiles:
            continue
        seen_names.add(key)
        if profile:
            seen_profiles.add(profile)
        result.append(company)
    return result, document, values


def _next_page(document, values, base):
    for anchor in document.nodes("a"):
        rel = (anchor.attrs.get("rel") or "").split()
        text = plain_text(anchor.text()).casefold()
        label = (anchor.attrs.get("aria-label") or "").casefold()
        if "next" in rel or text in {"next", "next page", "older", "more"} or label == "next page":
            value = public_url(anchor.attrs.get("href"), base)
            if value and domain_of(value) == domain_of(base):
                return value
    for value in values:
        for row in objects(value):
            candidate = _first(row, ("next_url", "nextUrl", "next_page_url"))
            if isinstance(candidate, str):
                candidate = public_url(candidate, base)
                if candidate and domain_of(candidate) == domain_of(base):
                    return candidate
    return None


def _partial_catalog(source, document, count, values=()):
    # Some boards include their sponsoring VC in the published total. It is
    # intentionally filtered as a target, but still proves catalog coverage.
    catalog_ids = {str(row.get("id") or row["slug"]) for value in values for row in objects(value)
                   if row.get("name") and row.get("slug") and "jobCount" in row}
    observed_count = max(count, len(catalog_ids))
    for meta in document.nodes("meta"):
        if meta.attrs.get("name") != "description":
            continue
        match = re.search(r"\b([\d,]+)\s+(?:\w+\s+){0,3}companies\b", meta.attrs.get("content") or "", re.I)
        if match and int(match.group(1).replace(",", "")) > observed_count:
            return True
    text = plain_text(document.root.text()).casefold()
    return source == "sequoia" and "spotlights" in text and "all companies" in text


def _enrich_company(company, source, client, timeout):
    url = company.get("profile_url")
    if company.get("website") or not url:
        return company, None
    try:
        page = fetch_page(url, client, timeout)
        document = Document(page.text)
        matches, _, _ = parse_companies(page, source)
        match = next((row for row in matches if row["website"] and row["name"].casefold() == company["name"].casefold()), None)
        website = match["website"] if match else None
        for anchor in document.nodes("a"):
            candidate = public_url(anchor.attrs.get("href"), page.url)
            label = plain_text(anchor.text()).casefold()
            if (candidate and domain_of(candidate) != domain_of(page.url)
                    and domain_of(candidate) not in SOCIAL_HOSTS and urlparse(candidate).hostname not in ATS_HOSTS
                    and (label in {"website", "visit website", "visit site", "company website", domain_of(candidate)} or "website" in label)):
                website = candidate
                break
        if website:
            company["website"], company["domain"] = website, domain_of(website)
        if match:
            for key in ("careers_url", "employee_count", "funding_stage", "description"):
                if match.get(key) not in (None, ""):
                    company[key] = match[key]
        if not company.get("description"):
            meta = next((node.attrs.get("content") for node in document.nodes("meta")
                         if node.attrs.get("name") == "description" or node.attrs.get("property") == "og:description"), None)
            if meta:
                company["description"] = plain_text(meta)
        return company, None
    except FetchError as exc:
        return company, error(source, exc.code, exc, exc.url, exc.retryable)


def _hn(config, cursor, limit, client):
    timeout = setting(config, "request_timeout", 12)
    errors = []
    thread_id = cursor.get("thread_id") if cursor else setting(config, "thread_id")
    try:
        if not thread_id:
            listing = fetch_page(setting(config, "url", SOURCE_URLS["hn"]), client, timeout)
            hits = listing.data.get("hits", []) if isinstance(listing.data, dict) else []
            thread = next((hit for hit in hits if "who is hiring" in hit.get("title", "").casefold()), None)
            if not thread:
                raise FetchError("schema_changed", "No public Who is hiring thread found", listing.url)
            thread_id = thread.get("objectID") or thread.get("id")
        if not str(thread_id).isdigit():
            raise FetchError("invalid_cursor", "HN thread ID must be numeric", None)
        page = fetch_page(f"https://hn.algolia.com/api/v1/items/{thread_id}", client, timeout)
        if not isinstance(page.data, dict) or not isinstance(page.data.get("children"), list):
            raise FetchError("schema_changed", "HN thread has no public comments array", page.url)
        comments = page.data["children"]
        index = int((cursor or {}).get("offset", 0))
        records = []
        while index < len(comments) and len(records) < limit:
            comment = comments[index]
            index += 1
            if comment.get("deleted") or comment.get("dead") or not comment.get("text"):
                continue
            document = Document(comment["text"])
            text = plain_text(comment["text"])
            heading = re.split(r"\s*\|\s*|\s+[-–—]\s+", text, maxsplit=1)[0]
            heading = re.sub(r"\s*\((?:remote[^)]*|series\s+[a-z]|(?:pre[ -])?seed|yc[^)]*)\)", "", heading, flags=re.I).strip()
            if len(heading) > 100 or len(heading) < 2:
                continue
            links = [public_url(node.attrs.get("href"), "https://news.ycombinator.com/") for node in document.nodes("a")]
            links = [link for link in links if link]
            careers = next((link for link in links if urlparse(link).hostname in ATS_HOSTS or re.search(r"/(careers|jobs)(?:/|$)", urlparse(link).path)), None)
            website = next((link for link in links if domain_of(link) not in SOCIAL_HOSTS | {"news.ycombinator.com", "ycombinator.com"}
                            and urlparse(link).hostname not in ATS_HOSTS), None)
            if not links:
                continue
            comment_url = f"https://news.ycombinator.com/item?id={comment['id']}"
            paragraphs = document.nodes("p")
            header = plain_text(paragraphs[0].text()) if paragraphs else text.split("\n", 1)[0]
            stage = re.search(r"\bSeries\s+[A-Z]\b|\bPre[ -]Seed\b|\bSeed\b", header, re.I)
            employees = re.search(r"\b([\d,]+(?:\s*[-–]\s*[\d,]+)?\+?)\s+employees\b", header, re.I)
            company = company_record({"name": heading, "website": website, "careers_url": careers,
                                      "description": text, "id": comment["id"],
                                      "funding_stage": stage.group(0) if stage else None,
                                      "employee_count": employees.group(1) if employees else None}, "hn", comment_url)
            if company:
                records.append(company)
        continuation = {"thread_id": str(thread_id), "offset": index} if index < len(comments) else None
        return {"records": records, "errors": errors, "cursor": continuation, "complete": continuation is None}
    except (FetchError, ValueError) as exc:
        errors.append(error("hn", getattr(exc, "code", "invalid_cursor"), exc, getattr(exc, "url", None), getattr(exc, "retryable", False)))
        return {"records": [], "errors": errors, "cursor": cursor, "complete": False}


def discover_source(source, config, cursor=None, limit=25, client=None, render=None):
    source = source.casefold().replace("hiring.cafe", "hiringcafe") if isinstance(source, str) else source
    if source not in SOURCE_URLS:
        return {"records": [], "errors": [error(str(source), "unsupported_source", "Unsupported public discovery source")], "cursor": cursor, "complete": False}
    if type(limit) is not int or limit < 1:
        raise ValueError("Discovery limit must be a positive integer")
    if cursor is not None and not isinstance(cursor, dict):
        raise ValueError("Discovery cursor must be a mapping")
    timeout = setting(config, "request_timeout", 12)
    client = client or PublicHTTPClient(timeout=timeout)
    if source == "hn":
        return _hn(config, cursor, limit, client)
    url = (cursor or {}).get("url") or setting(config, "url", SOURCE_URLS[source])
    try:
        offset = int((cursor or {}).get("offset", 0))
        if offset < 0:
            raise ValueError("Negative cursor offset")
        sampled = bool((cursor or {}).get("sample_feed"))
        snapshot = (cursor or {}).get("snapshot")
        if sampled and isinstance(snapshot, list) and all(isinstance(item, dict) for item in snapshot):
            records, document, values = deepcopy(snapshot), Document(""), []
            page_url = url
            partial_catalog = False
        else:
            page = fetch_page(url, client, timeout)
            records, document, values = parse_companies(page, source)
            if source == "yc" and not records and url == SOURCE_URLS["yc"] and render is not None:
                page = render_page(page.url, render)
                records, document, values = parse_companies(page, source)
            if (cursor or {}).get("requires_render") and render is not None:
                page = render_page(page.url, render)
                records, document, values = parse_companies(page, source)
            if not records and source == "yc" and url == SOURCE_URLS["yc"]:
                page = fetch_page("https://www.ycombinator.com/jobs", client, timeout)
                records, document, values = parse_companies(page, source)
                sampled = True
            if not records and render is not None:
                page = render_page(page.url, render)
                records, document, values = parse_companies(page, source)
            page_url = page.url
            if source == "yc" and urlparse(page_url).path.startswith("/jobs"):
                sampled = True
            partial_catalog = page.coverage_complete is not True and _partial_catalog(source, document, len(records), values)
        if not records:
            code = "import_required" if source in {"wellfound", "crunchbase"} else "needs_render"
            return {"records": [], "errors": [error(source, code, "Public page contains no usable company records; render the public page or import an authorized export", page_url)], "cursor": cursor or {"url": url, "offset": offset}, "complete": False}
        selected = deepcopy(records[offset:offset + limit])
        errors = []
        if setting(config, "enrich_profiles", True):
            for index, company in enumerate(selected):
                selected[index], issue = _enrich_company(company, source, client, timeout)
                if issue:
                    errors.append(issue)
        following = offset + len(selected)
        next_url = _next_page(document, values, page_url)
        continuation = {"url": page_url, "offset": following} if following < len(records) else ({"url": next_url, "offset": 0} if next_url else None)
        if sampled:
            if continuation:
                continuation.update({"sample_feed": True, "snapshot": records, "captured_at": (cursor or {}).get("captured_at") or now()})
            errors.append(error(source, "partial_public_feed", "Public jobs are a rotating sample, not the complete YC directory; render the directory or refresh for another public sample", page_url))
        elif partial_catalog and not next_url:
            continuation = {"url": page_url, "offset": following, "requires_render": True}
            errors.append(error(source, "partial_public_page", "Public HTML exposes only part of the company catalog; render the normal directory with full coverage or import a permitted export", page_url))
        if next_url == page_url:
            continuation = None
            errors.append(error(source, "pagination_loop", "Public next page points to the current page", page_url))
        return {"records": selected, "errors": errors, "cursor": continuation, "complete": continuation is None and not errors}
    except (FetchError, ValueError) as exc:
        issue = error(source, getattr(exc, "code", "invalid_cursor"), exc, getattr(exc, "url", str(url)), getattr(exc, "retryable", False))
        return {"records": [], "errors": [issue], "cursor": cursor or {"url": url, "offset": 0}, "complete": False}

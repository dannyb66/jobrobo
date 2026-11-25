"""Staffing-agency and job-aggregator detection for the optional --exclude-agencies gate.

Pure functions only: no browser, network or configuration imports. IT consultancies
and outsourcers are intentionally *not* treated as agencies; add them to
``agency_extra_names`` in config/search.py to exclude specific ones.
"""
from __future__ import annotations

import re
import unicodedata

# Observed in this repo's LinkedIn results and application history (Oct-Nov 2026),
# plus large national staffing brands. Matched on the normalized full company name.
DEFAULT_AGENCY_NAMES = frozenset({
    "adecco", "aimhire", "apex systems", "aventis solutions", "blue signal search",
    "brooksource", "colossus search group", "colossus technologies group", "crossing hurdles",
    "cubiq recruitment", "cybercoders", "dewinter group", "dice", "digital waffle",
    "eliassen group", "established search", "goliath partners", "harnham", "harrison clarke",
    "hays", "high country search group", "hireclout", "ikuto", "insight global", "investigo",
    "jobgether", "jobot", "kforce", "lhh", "lunon", "motion recruitment", "oak recruitment",
    "people in ai", "prosearch", "protech talent", "rachel paul recruiting", "radley james",
    "randstad", "recruiting from scratch", "redtech recruitment", "robert half", "saragossa",
    "signify technology", "skyrocket ventures", "smart it frame", "stonegate workforce group",
    "storm2", "strategic employment partners", "strategic employment partners sep",
    "talently", "talentpluto", "teksystems", "xcede",
})

# Name shapes that only staffing/search firms use. Deliberately narrow: a bare
# "search" or "talent" would also hit product companies.
_NAME_PATTERN = re.compile(
    r"\b(?:recruit(?:s|ing|ment|ers?)?|staffing|headhunt(?:ers?|ing)?|executive search|"
    r"search (?:group|partners)|talent (?:partners|solutions|group|acquisition group)|workforce solutions)\b")

# LinkedIn's industry label rendered in "About the company".
_INDUSTRY_PATTERN = re.compile(r"\bstaffing (?:and|&) recruiting\b", re.I)

# Third-party posting language in the job description. Each phrase names a client
# or partner the poster is hiring *for*, which an employer posting its own role does not.
_JD_PATTERNS = (
    re.compile(r"\bon behalf of (?:our|a|an|its|the|one of our) (?:valued |confidential )?(?:client|partner)s?\b", re.I),
    re.compile(r"\bour client,? (?:is|a|an|who)\b", re.I),
    re.compile(r"\b(?:we are|we're|is) (?:exclusively )?partner(?:ing|ed) with (?:a|an)\b(?! (?:range|number|variety))", re.I),
    re.compile(r"\bconfidential client\b", re.I),
)

_SUFFIXES = re.compile(r"\b(?:inc|llc|ltd|limited|corp|corporation|co|plc|gmbh|usa|us)\b")


def normalize_company(name) -> str:
    if not isinstance(name, str):
        return ""
    text = unicodedata.normalize("NFKC", name).casefold().replace("&", " and ")
    text = re.sub(r"[^\w\s]", " ", text)
    text = _SUFFIXES.sub(" ", text)
    return " ".join(text.split())


def _names(values) -> set[str]:
    return {normalize_company(value) for value in values or () if normalize_company(value)}


def agency_by_name(company, *, extra_names=(), allow_names=()) -> str | None:
    """Cheap pre-click check from the card's company name; returns a reason or None."""
    name = normalize_company(company)
    if not name or name in _names(allow_names):
        return None
    if name in DEFAULT_AGENCY_NAMES or name in _names(extra_names):
        return f"company name {company!r} is a listed staffing agency or job aggregator"
    if _NAME_PATTERN.search(name):
        return f"company name {company!r} looks like a staffing or search firm"
    return None


def agency_by_about_company(about_company, *, company=None, allow_names=()) -> str | None:
    """LinkedIn industry 'Staffing and Recruiting' in the employer's About section."""
    if normalize_company(company) in _names(allow_names):
        return None
    if isinstance(about_company, str) and _INDUSTRY_PATTERN.search(about_company):
        return "LinkedIn industry is Staffing and Recruiting"
    return None


def agency_by_description(description, *, company=None, allow_names=()) -> str | None:
    """Third-party posting language ("on behalf of our client") in the job description."""
    if normalize_company(company) in _names(allow_names) or not isinstance(description, str):
        return None
    for pattern in _JD_PATTERNS:
        match = pattern.search(description)
        if match:
            return f"job description posts for a third party ({match.group(0)!r})"
    return None


def classify(company=None, about_company=None, description=None, *, extra_names=(), allow_names=()) -> str | None:
    """First matching reason across all available signals, or None for a direct employer."""
    return (agency_by_name(company, extra_names=extra_names, allow_names=allow_names)
            or agency_by_about_company(about_company, company=company, allow_names=allow_names)
            or agency_by_description(description, company=company, allow_names=allow_names))


class AgencyExcluded(ValueError):
    """Raised by the About-the-company gate so the runner records a distinct skip reason."""

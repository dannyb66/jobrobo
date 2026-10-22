"""Explainable review ordering, independent of optimizer, eligibility and source freshness."""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import zipfile
from xml.etree import ElementTree


POLICY_VERSION = "posting-recency-resume-affinity-v1"
# Deliberately bounded vocabulary: unknown requirements remain outside this heuristic.
SKILLS = {
    "Python": ("python",), "Java": ("java",), "JavaScript": ("javascript",),
    "TypeScript": ("typescript",), "Go": ("golang", "go programming", "go language"), "Rust": ("rust",),
    "C++": ("c++",), "C#": ("c#",), "Scala": ("scala",), "Ruby": ("ruby",),
    "SQL": ("sql",), "React": ("react", "react.js", "reactjs"),
    "Node.js": ("node.js", "nodejs"), "Linux": ("linux",),
    "AWS": ("aws", "amazon web services"), "GCP": ("gcp", "google cloud"),
    "Azure": ("azure",), "Kubernetes": ("kubernetes", "k8s"), "Docker": ("docker",),
    "Terraform": ("terraform",), "PostgreSQL": ("postgresql", "postgres"),
    "MySQL": ("mysql",), "Redis": ("redis",), "Kafka": ("kafka",),
    "Spark": ("apache spark", "spark"), "Airflow": ("airflow",),
    "Elasticsearch": ("elasticsearch",), "MongoDB": ("mongodb",),
    "Distributed systems": ("distributed systems", "distributed system"),
    "Microservices": ("microservices", "microservice"),
    "Machine learning": ("machine learning", "machine-learning"),
    "Deep learning": ("deep learning",), "LLM": ("llm", "llms", "large language model", "large language models"),
    "RAG": ("rag", "retrieval augmented generation", "retrieval-augmented generation"),
    "PyTorch": ("pytorch",), "TensorFlow": ("tensorflow",),
    "vLLM": ("vllm",), "TensorRT": ("tensorrt", "tensorrt-llm"),
    "CUDA": ("cuda",), "GPU": ("gpu", "gpus"), "Inference": ("inference",),
    "Observability": ("observability",), "Prometheus": ("prometheus",),
    "Grafana": ("grafana",), "OpenTelemetry": ("opentelemetry",),
    "CI/CD": ("ci/cd", "continuous integration", "continuous delivery"),
    "Networking": ("networking",), "Security": ("security",),
    "Incident response": ("incident response",), "SRE": ("sre", "site reliability"),
    "Data engineering": ("data engineering", "data engineer"),
    "Data science": ("data science", "data scientist"),
    "System design": ("system design", "systems design"),
}
FAMILIES = {
    "software": r"\b(?:software|backend|back[ -]end|frontend|front[ -]end|full[ -]?stack)\b",
    "ai_ml": r"\b(?:ai|ml|machine[ -]learning|deep[ -]learning|llms?|inference)\b",
    "platform": r"\b(?:platform|infrastructure|cloud|distributed systems?)\b",
    "data": r"\bdata (?:engineer(?:ing)?|scien(?:ce|tist)|platform)\b",
    "reliability": r"\b(?:sre|site reliability|reliability engineer(?:ing)?)\b",
    "security": r"\b(?:security|cybersecurity)\b",
    "research": r"\b(?:research|researcher|research scientist)\b",
    "hardware": r"\b(?:hardware|firmware|embedded|electrical)\b",
    "customer_engineering": r"\b(?:forward[ -]deployed|solutions engineer(?:ing)?|support engineer(?:ing)?)\b",
}
RECENCY_ORDER = {"past_24_hours": 0, "past_7_days": 1, "past_30_days": 2, "older": 3, "unknown": 4}


@dataclass(frozen=True)
class ResumeAffinityProfile:
    sha256: str
    skills: frozenset
    families: frozenset


def _contains(text, alias):
    # Keep punctuation inside terms, and reject Java-in-JavaScript / RAG-in-storage.
    return bool(re.search(r"(?<![\w+#])" + re.escape(alias) + r"(?![\w+#])", text, re.I))


def _skills(text):
    found = {name for name, aliases in SKILLS.items() if any(_contains(text, alias) for alias in aliases)}
    # A capitalized Go in a language list is useful; the everyday verb "go" is not.
    if re.search(r"(?:\bGo(?=\s*[,;/)])|[,;/]\s*Go\b)", text):
        found.add("Go")
    return frozenset(found)


def _families(text):
    return frozenset(name for name, pattern in FAMILIES.items() if re.search(pattern, text, re.I))


def profile_from_text(text, sha256=None):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Resume must contain readable text")
    return ResumeAffinityProfile(sha256 or hashlib.sha256(text.encode("utf-8")).hexdigest(), _skills(text), _families(text))


def load_resume_profile(path):
    """Read locally; retain only file hash and bounded vocabulary, never full resume text."""
    path = Path(path).expanduser()
    content = path.read_bytes()
    try:
        if path.suffix.lower() == ".docx":
            with zipfile.ZipFile(path) as archive:
                root = ElementTree.fromstring(archive.read("word/document.xml"))
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            text = "\n".join("".join(p.itertext()) for p in root.findall(".//w:p", ns))
        elif path.suffix.lower() == ".pdf":
            try:
                import pdfplumber
            except ImportError as error:
                raise ValueError("PDF affinity needs pdfplumber; use the DOCX or a text resume instead") from error
            with pdfplumber.open(path) as document:
                text = "\n".join(page.extract_text() or "" for page in document.pages)
        elif path.suffix.lower() in {".txt", ".md"}:
            text = content.decode("utf-8")
        else:
            raise ValueError("Resume affinity accepts .docx, .pdf, .txt or .md")
    except (zipfile.BadZipFile, ElementTree.ParseError, KeyError, UnicodeError) as error:
        raise ValueError("Resume could not be read as its declared format") from error
    return profile_from_text(text, hashlib.sha256(content).hexdigest())


def as_of_datetime(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("Ranking as-of must be an ISO timestamp with timezone") from error
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("Ranking as-of must be an ISO timestamp with timezone")
    return result.astimezone(timezone.utc)


def posting_recency(published_at, as_of=None):
    now = as_of_datetime(as_of)
    result = {"bucket": "unknown", "age_days": None, "published_at_utc": None, "reason": "missing_posting_date"}
    if published_at in (None, ""):
        return result
    try:
        posted = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
        # Date-only / timezone-free timestamps are not precise enough to claim recency.
        if posted.tzinfo is None or posted.utcoffset() is None:
            return dict(result, reason="posting_date_has_no_timezone")
        posted = posted.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        return dict(result, reason="invalid_posting_date")
    age = (now - posted).total_seconds() / 86400
    if age < 0:
        return dict(result, reason="future_posting_date", published_at_utc=posted.isoformat())
    bucket = "past_24_hours" if age <= 1 else "past_7_days" if age <= 7 else "past_30_days" if age <= 30 else "older"
    return {"bucket": bucket, "age_days": round(age, 6), "published_at_utc": posted.isoformat(), "reason": "published_at"}


def resume_affinity(role, profile=None):
    base = {"band": "unknown", "score": None, "matched_terms": [], "missing_terms": [],
            "matched_title_families": [], "title_families": [], "resume_sha256": None,
            "method": "bounded-lexical-overlap-v1", "is_ats_score": False,
            "qualification_verified": False, "reason": "resume_not_provided"}
    if profile is None:
        return base
    base["resume_sha256"] = profile.sha256
    description = str(role.get("description") or "")
    if not description.strip():
        return dict(base, reason="missing_job_description")
    title = str(role.get("title") or "")
    terms, title_terms = _skills(title + "\n" + description), _skills(title)
    families = _families(title)
    matched = terms & profile.skills
    base.update(matched_terms=sorted(matched), missing_terms=sorted(terms - profile.skills),
                title_families=sorted(families), matched_title_families=sorted(families & profile.families))
    if not terms:
        return dict(base, reason="no_recognized_job_terms")
    # Title terms count twice. Family overlap contributes 20% only when title families exist.
    weight = lambda values: sum(2 if term in title_terms else 1 for term in values)
    coverage = weight(matched) / weight(terms)
    family_overlap = len(families & profile.families) / len(families) if families else 0
    score = round(100 * (0.8 * coverage + 0.2 * family_overlap if families else coverage), 1)
    return dict(base, score=score, band="high" if score >= 65 else "medium" if score >= 35 else "low",
                reason="recognized_job_terms", matched_weight=weight(matched), job_terms_weight=weight(terms))


def _inventory(role):
    return role.get("status") == "open" and role.get("verification_eligible", role.get("eligible")) is True


def _tier(role, recency, affinity):
    if not _inventory(role):
        return 4, "Outside open engineering inventory; retained for audit"
    age, band = RECENCY_ORDER[recency["bucket"]], affinity["band"]
    if age <= 1 and band in {"high", "medium"}:
        return 1, "Posted within seven days; medium or high resume overlap"
    if age <= 1 or (age == 2 and band in {"high", "medium"}) or (age == 3 and band == "high"):
        return 2, "Recent posting or older posting with high resume overlap"
    return 3, "Older, unknown-date or lower-overlap posting; retained for review"


def rank_roles(roles, profile=None, *, as_of=None):
    """Return every input row exactly once, with derived metadata and stable review order."""
    now = as_of_datetime(as_of)
    ranked = []
    for original in roles:
        role = deepcopy(original)
        recency = posting_recency(role.get("published_at"), now)
        affinity = resume_affinity(role, profile)
        tier, reason = _tier(role, recency, affinity)
        role["review_priority"] = {"policy_version": POLICY_VERSION, "as_of": now.isoformat(),
                                   "tier": tier, "reason": reason, "recency": recency, "affinity": affinity}
        ranked.append(role)
    return sorted(ranked, key=review_sort_key)


def review_sort_key(role):
    priority = role["review_priority"]
    recency, affinity = priority["recency"], priority["affinity"]
    posted = recency["published_at_utc"] if recency["bucket"] != "unknown" else None
    timestamp = datetime.fromisoformat(posted).timestamp() if posted else 0
    company = role.get("company") if isinstance(role.get("company"), dict) else {}
    return (priority["tier"], RECENCY_ORDER[recency["bucket"]],
            -(affinity["score"] if affinity["score"] is not None else -1), -timestamp,
            str(company.get("name") or role.get("company_id") or "").casefold(),
            str(role.get("title") or "").casefold(), str(role.get("id") or ""))

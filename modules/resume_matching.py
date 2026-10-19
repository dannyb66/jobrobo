"""Inspectable local JD diagnostics; not a commercial ATS or qualification score."""
from difflib import SequenceMatcher
import math
import re

from modules.resume_scoring import _concepts, _mentions, _tokens, score_keywords

METHOD = "jd-requirement-evidence-v1"
DEFAULT_WEIGHTS = {"required": 2.0, "preferred": 1.0, "context": 1.0}
_REQUIRED = re.compile(r"\b(?:required|requirements|must|minimum|essential|need|qualifications|what you.bring)\b", re.I)
_PREFERRED = re.compile(r"\b(?:preferred|bonus|nice.to.have|a plus|desired|ideally|optional|not required)\b", re.I)
_OPTIONAL = re.compile(r"\b(?:(?:isn['’]?t|aren['’]?t|not)\s+(?:strictly\s+)?required|not necessary)\b", re.I)
_HEADINGS = {
    "requirements": "required", "required qualifications": "required", "basic qualifications": "required",
    "minimum qualifications": "required", "qualifications": "required", "what you bring": "required",
    "nice to have": "preferred", "preferred qualifications": "preferred", "preferred": "preferred", "bonus": "preferred",
    "responsibilities": "context", "the role": "context", "example initiatives": "context",
    "what we are looking for": "context", "what we're looking for": "context",
    "what you'll bring": "required", "what you will bring": "required", "what you will do": "context",
    "what you'll do": "context", "benefits": "ignore", "compensation": "ignore", "about us": "ignore",
}
RELATED_SOURCE_SKILLS = {
    "aws": ("cloud", "infrastructure", "deployment"),
    "docker": ("container", "containers", "deployment", "infrastructure"),
    "terraform": ("infrastructure", "infrastructure as code", "cloud"),
}


def _jd_lines(jd):
    """Recover common structural headings lost by HTML-to-plain-text extraction."""
    headings = "|".join(re.escape(value.upper()) for value in sorted(_HEADINGS, key=len, reverse=True))
    jd = re.sub(r"(?<!\w)(" + headings + r")(?!\w)", lambda m: "\n" + m[0] + ":\n", jd)
    jd = re.sub(r"(?<!\w)(ABOUT [A-Z][A-Z ]{1,35})(?=\s+[A-Z][a-z])", lambda m: "\nABOUT US:\n", jd)
    jd = re.sub(r"\s+[-•]\s+", "\n", jd)
    return re.split(r"[\n]+|(?<=[.!?])\s+|,\s*(?:though|although|but)\s+", jd)


def jd_requirements(jd, keywords, weights=None):
    if weights is not None and not isinstance(weights, dict):
        raise ValueError("match_weights must be an object with required/preferred/context weights")
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    if set(weights) != set(DEFAULT_WEIGHTS) or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in weights.values()):
        raise ValueError("match_weights must contain positive finite required/preferred/context weights")
    concepts = _concepts(keywords)
    requirements, seen = [], set()
    section = "context"
    for line_index, line in enumerate(_jd_lines(jd), 1):
        line = line.strip()
        if not line:
            continue
        heading = line.strip(" :").casefold().replace("’", "'")
        if heading in _HEADINGS:
            section = _HEADINGS[heading]
            continue
        if section == "ignore":
            continue
        optional = bool(_OPTIONAL.search(line))
        required, preferred = bool(_REQUIRED.search(_OPTIONAL.sub("optional", line))), bool(_PREFERRED.search(line)) or optional
        kind = "preferred" if preferred and not required else "required" if required else section
        found = [c for c in concepts if _mentions(line, c["keys"])]
        # Only explicit JD phrases participate; model/bank-only vocabulary cannot inflate the denominator.
        if not found:
            continue
        alternatives = bool(re.search(r"\bor\b", line, re.I)) and not re.search(r"\band\b", line, re.I) and len(found) > 1
        groups = [found] if alternatives else [[c] for c in found]
        for group in groups:
            terms = [c["keyword"] for c in group]
            marker = (tuple(terms), kind, alternatives)
            if marker in seen:
                continue
            seen.add(marker)
            requirements.append({"id": f"jd:{line_index}:{len(requirements)+1}", "terms": terms,
                                 "operator": "any" if alternatives else "all", "kind": kind,
                                 "weight": weights[kind], "jd_span": line,
                                 "extraction": "deterministic_keyword_spans", "requires_review": True})
    unique = {}
    importance = {"required": 3, "preferred": 2, "context": 1}
    for requirement in requirements:
        key = (tuple(requirement["terms"]), requirement["operator"])
        if key not in unique or importance[requirement["kind"]] > importance[unique[key]["kind"]]:
            unique[key] = requirement
    return list(unique.values()), weights


def skill_relevance(skill, jd):
    requirements, _ = jd_requirements(jd, [skill])
    # A source annotation such as Terraform (IaC) retains the tool's low
    # context priority without asserting that the annotation is a JD synonym.
    related_name = re.sub(r"\s*\([^)]*\)\s*$", "", skill).strip().casefold()
    related = RELATED_SOURCE_SKILLS.get(related_name, ())
    related_match = any(score_keywords(jd, [term])["matched"] for term in related)
    if not requirements:
        return (0.5 if related_match else 0, 0)
    concepts = _concepts([skill])
    return (max(item["weight"] for item in requirements), len(_mentions(jd, concepts[0]["keys"])) if concepts else 0)


def match_analysis(source_text, output_text, jd, keywords, source_titles=(), output_titles=(), target_title="", weights=None):
    requirements, weights = jd_requirements(jd, keywords, weights)
    details = []
    for requirement in requirements:
        evidence = {}
        for label, text in (("source", source_text), ("output", output_text)):
            matched = [term for term in requirement["terms"] if score_keywords(text, [term])["matched"]]
            present = bool(matched) if requirement["operator"] == "any" else len(matched) == len(requirement["terms"])
            lines = [line for line in text.splitlines() if any(score_keywords(line, [term])["matched"] for term in matched)]
            negated = bool(lines) and all(re.search(r"\b(?:no|without|never|lack|lacking|not familiar)\b", line, re.I) for line in lines)
            present = present and not negated
            evidence[label] = {"matched": present, "matched_terms": matched, "excerpts": lines[:3],
                               "negated_only": negated,
                               "context_present": any(len(_tokens(line)) > 8 and "," not in line for line in lines)}
        status = "source_supported_mention" if evidence["source"]["matched"] else "draft_only_mention" if evidence["output"]["matched"] else "gap"
        details.append({**requirement, "status": status, "evidence": evidence})
    coverage = {}
    for kind in ("required", "preferred", "context", "all"):
        rows = [r for r in details if kind == "all" or r["kind"] == kind]
        denominator = sum(r["weight"] for r in rows)
        coverage[kind] = {"total": len(rows), **{label: round(100*sum(r["weight"] for r in rows if r["evidence"][label]["matched"])/denominator, 1) if denominator else None for label in ("source", "output")}}
    return {"method": METHOD, "weights": weights, "weight_basis": "local configurable heuristic; not learned or vendor-calibrated",
            "facts_verified": False, "coverage": coverage, "requirements": details,
            "title_alignment": {"source": title_alignment(source_titles, target_title), "output": title_alignment(output_titles, target_title)},
            "limits": "Keyword-span extraction and Boolean OR detection are heuristic. Context flags indicate longer text, not entailment, duration or qualification. Draft-only mentions never improve source evidence. No eligibility or hiring probability is inferred."}


def title_alignment(titles, target):
    def terms(value):
        value = re.sub(r"\bsr\.?\b", "senior", value, flags=re.I)
        value = re.sub(r"\bjr\.?\b", "junior", value, flags=re.I)
        return set(_tokens(value)) - {"of", "the", "and", "a"}
    wanted = terms(target)
    rows = [{"title": title, "exact": terms(title) == wanted and bool(wanted),
             "term_coverage": round(100*len(terms(title) & wanted)/len(wanted), 1) if wanted else None} for title in titles]
    return {"target": target, "best_term_coverage": max((r["term_coverage"] or 0 for r in rows), default=0),
            "titles": rows, "interpretation": "Separate title-term coverage; not proof of role level or an ATS ranking."}


def document_changes(source_lines, output_lines):
    changes = []
    for operation, a, b, c, d in SequenceMatcher(a=source_lines, b=output_lines, autojunk=False).get_opcodes():
        if operation == "equal":
            continue
        changes.append({"id": f"change:{len(changes)+1}", "operation": operation,
                        "source_paragraphs": list(range(a+1, b+1)), "output_paragraphs": list(range(c+1, d+1)),
                        "before": source_lines[a:b], "after": output_lines[c:d],
                        "review_required": True, "facts_verified": False})
    return changes

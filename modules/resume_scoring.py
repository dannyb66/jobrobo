"""Conservative lexical resume diagnostics, independent of commercial ATS scores.

These helpers measure textual mentions. They do not verify qualifications, infer
eligibility, reproduce recruiter calibrations, or predict hiring outcomes.
"""

from collections import defaultdict
import re
import unicodedata


SCORING_METHOD = "bounded-unique-concept-coverage-v1"
_TOKEN = re.compile(r"[^\W_]+(?:[+#]+)?", re.UNICODE)


def _tokens(text):
    return tuple(_TOKEN.findall(unicodedata.normalize("NFKC", text).casefold()))


def _keyword_variants(keyword):
    """Accept parenthetical aliases only when they spell the expansion's initials."""
    parts = re.findall(r"\(([^)]*)\)", keyword)
    base = re.sub(r"\([^)]*\)", " ", keyword).strip()
    base_tokens = _tokens(base)
    initials = "".join(token[0] for token in base_tokens)
    aliases = []
    for part in parts:
        compact = re.sub(r"[^a-z0-9]", "", part.casefold())
        if re.fullmatch(r"[A-Z][A-Za-z0-9]{1,14}", part.strip()) and (
            compact == initials or compact.endswith("s") and compact[:-1] == initials
        ):
            aliases.append(_tokens(part))
            if compact.endswith("s") and compact[:-1] == initials:
                aliases.append((initials,))
        else:
            # Parenthetical context is part of the phrase, not evidence that
            # Infrastructure (AWS) is equivalent to either Infrastructure or AWS.
            return _tokens(keyword), (), False
    return base_tokens, tuple(aliases), bool(aliases)


def _concepts(keywords, bank=None):
    entries = []
    owners = defaultdict(set)
    for keyword in keywords:
        if not isinstance(keyword, str) or not keyword.strip():
            continue
        label = keyword.strip()
        canonical, aliases, expanded = _keyword_variants(label)
        if not canonical:
            continue
        entries.append((label, canonical, aliases, expanded))
        for alias in aliases:
            owners[alias].add(canonical)

    core_keys = set()
    for row in (bank or {}).get("keywords", []):
        if isinstance(row, dict) and "Core" in row.get("tier", ""):
            value = row.get("keyword") or row.get("normalized", "")
            canonical, aliases, _ = _keyword_variants(value)
            core_keys.add(canonical)
            core_keys.update(alias for alias in aliases if len(owners[alias]) <= 1)

    groups = []
    for label, canonical, aliases, expanded in entries:
        keys = {canonical, *(alias for alias in aliases if len(owners[alias]) <= 1)}
        overlapping = [item for item in groups if item["keys"] & keys]
        group = overlapping[0] if overlapping else None
        weight = 2 if keys & core_keys else 1
        if group is None:
            groups.append({"keyword": label, "keys": keys, "members": [label],
                           "expanded": expanded, "weight": weight})
        else:
            for other in overlapping[1:]:
                group["keys"].update(other["keys"])
                group["members"].extend(value for value in other["members"] if value not in group["members"])
                group["weight"] = max(group["weight"], other["weight"])
                groups.remove(other)
            group["keys"].update(keys)
            group["weight"] = max(group["weight"], weight)
            if label not in group["members"]:
                group["members"].append(label)
            if expanded and not group["expanded"]:
                group["keyword"] = label
                group["expanded"] = True
    return groups


def _mentions(text, keys):
    """Return bounded phrase matches with excerpts from normalized source text."""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    token_matches = list(_TOKEN.finditer(normalized))
    words = tuple(match.group() for match in token_matches)
    mentions = []
    for variant in sorted(keys):
        length = len(variant)
        for index in range(len(words) - length + 1):
            if words[index:index + length] == variant:
                start = token_matches[index].start()
                end = token_matches[index + length - 1].end()
                mentions.append({"variant": " ".join(variant),
                                 "excerpt": normalized[max(0, start - 60):end + 60]})
                if len(mentions) >= 3:
                    return mentions
    return mentions


def score_keywords(text, keywords, bank=None):
    """Preserve the legacy result shape while counting each bounded concept once."""
    concepts = _concepts(keywords, bank)
    matched, missing = [], []
    matched_weight = 0
    for concept in concepts:
        if _mentions(text, concept["keys"]):
            matched.append(concept["keyword"])
            matched_weight += concept["weight"]
        else:
            missing.append(concept["keyword"])
    total_weight = sum(concept["weight"] for concept in concepts)
    return {"score": round(100 * matched_weight / total_weight, 1) if total_weight else 0.0,
            "matched": matched, "missing": missing, "total": len(concepts)}


def keyword_provenance(source_text, output_text, keywords, bank=None):
    """Identify introduced/removed mentions without claiming factual verification."""
    details = []
    summary = {"retained_terms": [], "introduced_terms": [], "removed_terms": [], "absent_terms": []}
    for concept in _concepts(keywords, bank):
        source = _mentions(source_text, concept["keys"])
        output = _mentions(output_text, concept["keys"])
        if source and output:
            status, bucket = "source_and_output", "retained_terms"
        elif output:
            status, bucket = "introduced_in_output", "introduced_terms"
        elif source:
            status, bucket = "removed_from_output", "removed_terms"
        else:
            status, bucket = "absent", "absent_terms"
        summary[bucket].append(concept["keyword"])
        details.append({"keyword": concept["keyword"], "weight": concept["weight"],
                        "input_terms": concept["members"], "status": status,
                        "source_mentions": source, "output_mentions": output})
    return {"method": SCORING_METHOD, "facts_verified": False,
            "interpretation": "Textual mentions, including negated claims, do not establish qualifications. "
                              "Introduced terms need source evidence or candidate review; curated-bank evidence "
                              "may exist outside the source resume. This is not an ATS vendor score.",
            **summary, "details": details}

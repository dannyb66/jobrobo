"""Resolve incomplete LinkedIn work-history dates from the source resume."""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path


@dataclass(frozen=True)
class ExperienceRange:
    title: str
    start_month: str
    start_year: str
    end_month: str
    end_year: str


_MONTH_YEAR = re.compile(
    r"^(?P<title>.+?)\s+(?P<start_month>[A-Z][a-z]+)\s+(?P<start_year>\d{4})\s*[-–—]\s*"
    r"(?P<end_month>[A-Z][a-z]+)\s+(?P<end_year>\d{4}|Present)$"
)


def load_experience_ranges(path: str | Path) -> list[ExperienceRange]:
    """Read dated role headings from a DOCX resume, excluding education/projects."""
    from docx import Document

    document = Document(str(path))
    result = []
    for paragraph in document.paragraphs:
        text = " ".join(paragraph.text.split())
        match = _MONTH_YEAR.match(text)
        if not match:
            continue
        title = match.group("title").strip()
        if re.search(r"\b(university|institute|college|school|bachelor|master|mba)\b", title, re.I):
            continue
        end_month, end_year = match.group("end_month"), match.group("end_year")
        if end_year.casefold() == "present":
            continue
        result.append(ExperienceRange(
            title, match.group("start_month"), match.group("start_year"), end_month, end_year
        ))
    return result


def best_experience_range(row_text: str, records: list[ExperienceRange]) -> ExperienceRange | None:
    """Choose the strongest title match, then prefer a role whose wording overlaps the row."""
    if not records:
        return None
    def normalize(value: str) -> set[str]:
        tokens = set(re.findall(r"[a-z0-9]+", value.casefold()))
        # LinkedIn/profile nomenclature commonly uses Product Owner for the
        # corresponding Product Manager entry in a resume.
        if "owner" in tokens and "product" in tokens:
            tokens.remove("owner")
            tokens.add("manager")
        return tokens - {
            "senior", "staff", "principal", "engineer", "engineering", "role", "experience"
        }
    row = normalize(row_text)
    ranked = []
    for record in records:
        title = normalize(record.title)
        overlap = len(row & title) / max(1, len(title))
        ratio = SequenceMatcher(None, " ".join(sorted(row)), " ".join(sorted(title))).ratio()
        ranked.append((overlap * 0.75 + ratio * 0.25, record))
    # On no meaningful semantic match, use the latest completed resume role as the
    # best available resume-backed range instead of leaving required fields empty.
    score, record = max(ranked, key=lambda item: item[0])
    if score < 0.12:
        return max(records, key=lambda item: (int(item.end_year), list_month_index(item.end_month)))
    return record


def list_month_index(month: str) -> int:
    months = "January February March April May June July August September October November December".split()
    return months.index(month) + 1 if month in months else 0

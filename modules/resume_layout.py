"""Measure source-relative resume density from actual PDF word positions."""
import re
import unicodedata

import pdfplumber
from docx import Document


def _compact(text):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).casefold()).replace("\u00ad", "")


def paragraph_density(pdf_path, docx_path, skills_range):
    """Locate each bullet/Skills paragraph in reading order, including page splits.

    Missing matches remain explicit; they must never count as passing density.
    Width excludes the bullet marker and measures the text's occupied line span.
    """
    words, stream, line_number = [], "", 0
    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, 1):
            top = None
            for word in page.extract_words() or []:
                if top is None or abs(float(word["top"]) - top) > 3:
                    line_number += 1
                    top = float(word["top"])
                value = _compact(word["text"])
                words.append({"start": len(stream), "end": len(stream) + len(value),
                              "line": line_number, "page": page_number,
                              "x0": float(word["x0"]), "x1": float(word["x1"])})
                stream += value
    records, cursor = [], 0
    start, end = skills_range
    for index, paragraph in enumerate(Document(docx_path).paragraphs):
        kind = "skills" if start is not None and start <= index < end else (
            "bullet" if (paragraph.style.name.startswith(("List Paragraph", "List Bullet")) or paragraph._p.xpath("./w:pPr/w:numPr") or re.match(r"^\s*[•●▪◦‣\-–]\s+", paragraph.text)) else None)
        if kind is None or not paragraph.text.strip():
            continue
        value = _compact(paragraph.text)
        position = stream.find(value, cursor)
        record = {"paragraph_index": index, "kind": kind, "matched": position >= 0, "lines": []}
        if position >= 0:
            limit = position + len(value)
            grouped = {}
            for word in words:
                if word["start"] < limit and word["end"] > position:
                    grouped.setdefault(word["line"], []).append(word)
            for group in grouped.values():
                record["lines"].append({"page": group[0]["page"],
                                        "x0": min(w["x0"] for w in group), "x1": max(w["x1"] for w in group),
                                        "width": round(max(w["x1"] for w in group) - min(w["x0"] for w in group), 3)})
            cursor = limit
        record["line_count"] = len(record["lines"])
        record["width"] = round(sum(line["width"] for line in record["lines"]), 3)
        records.append(record)
    return records


def compare_density(source, output):
    """Require source line count, page placement and natural occupied width.

    8% allows normal word/font differences without accepting the visibly sparse
    one-line rewrites that a page-count-only verifier previously accepted.
    """
    violations = []
    comparable = len(source) == len(output) and [r["kind"] for r in source] == [r["kind"] for r in output]
    if not comparable:
        violations.append({"reason": "paragraph_count_or_kind_changed"})
    for before, after in zip(source, output) if comparable else []:
        reasons = []
        if not before["matched"] or not after["matched"]:
            reasons.append("paragraph_not_located_in_pdf")
        else:
            if before["line_count"] != after["line_count"]:
                reasons.append("rendered_line_count_changed")
            if [r["page"] for r in before["lines"]] != [r["page"] for r in after["lines"]]:
                reasons.append("page_placement_changed")
            if before["width"] and not 0.92 <= after["width"] / before["width"] <= 1.08:
                reasons.append("occupied_width_outside_92_to_108_percent")
            if before["lines"] and after["lines"]:
                last_width = before["lines"][-1]["width"]
                if last_width and not 0.90 <= after["lines"][-1]["width"] / last_width <= 1.10:
                    reasons.append("last_line_fill_changed")
        if reasons:
            violations.append({"kind": before["kind"], "source_index": before["paragraph_index"],
                               "output_index": after["paragraph_index"], "reasons": reasons,
                               "source": before, "output": after})
    return {"passed": comparable and not violations, "comparable": comparable,
            "source": source, "output": output, "violations": violations}

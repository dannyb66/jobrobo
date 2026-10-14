"""Inspect external resume links and retain them when PDF text is rebuilt."""

from collections import Counter
from html import escape
import math
from pathlib import Path, PurePosixPath
import re
from urllib.parse import urlsplit, urlunsplit
from zipfile import ZipFile
import xml.etree.ElementTree as ET

import pdfplumber
from PyPDF2 import PdfReader


WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def _target_key(target):
    """Allow export-added trailing slashes without changing query/fragment identity."""
    parts = urlsplit(target.strip())
    user_info, separator, host = parts.netloc.rpartition("@")
    authority = (user_info + separator if separator else "") + host.lower()
    return urlunsplit((parts.scheme.lower(), authority, parts.path.rstrip("/"),
                       parts.query, parts.fragment))


def read_docx_links(path):
    links = []
    with ZipFile(path) as document:
        parts = [name for name in document.namelist()
                 if re.fullmatch(r"word/(document|header\d+|footer\d+)\.xml", name)]
        for name in parts:
            part = PurePosixPath(name)
            relationship_path = str(part.parent / "_rels" / (part.name + ".rels"))
            relationships = {}
            if relationship_path in document.namelist():
                relationships = {item.attrib["Id"]: item.attrib for item in
                                 ET.fromstring(document.read(relationship_path))}
            root = ET.fromstring(document.read(name))
            for link in root.iter(WORD_NS + "hyperlink"):
                relationship_id = link.attrib.get(REL_NS + "id")
                if relationship_id is None:  # Internal bookmarks have no external URI.
                    continue
                relationship = relationships.get(relationship_id, {})
                target = relationship.get("Target")
                if not target:
                    raise ValueError(f"DOCX hyperlink has no target: {relationship_id}")
                links.append({"target": target, "label": "".join(
                    item.text or "" for item in link.iter(WORD_NS + "t"))})
            instructions = [item.attrib.get(WORD_NS + "instr", "")
                            for item in root.iter(WORD_NS + "fldSimple")]
            instructions.append("".join(item.text or "" for item in root.iter(WORD_NS + "instrText")))
            for instruction in instructions:
                for match in re.finditer(r'\bHYPERLINK\s+(?:"([^"]+)"|([^\s]+))', instruction, re.I):
                    target = match.group(1) or match.group(2)
                    if not target.startswith("\\"):
                        links.append({"target": target, "label": ""})
    return links


def read_pdf_links(path, include_text=False):
    """Read URI annotations; usable click areas must intersect the visible page."""
    reader = PdfReader(str(path))
    links = []
    for number, page in enumerate(reader.pages):
        annotations = page.get("/Annots", [])
        annotations = annotations.get_object() if hasattr(annotations, "get_object") else annotations
        for reference in annotations:
            annotation = reference.get_object()
            if annotation.get("/Subtype") != "/Link":
                continue
            action = annotation.get("/A", {})
            action = action.get_object() if hasattr(action, "get_object") else action
            if action.get("/S") != "/URI" or not action.get("/URI"):
                continue
            rectangle = [float(value) for value in annotation.get("/Rect", [])]
            box = [float(value) for value in page.cropbox]
            clickable = len(rectangle) == 4 and all(math.isfinite(value) for value in rectangle)
            clickable = clickable and rectangle[2] > rectangle[0] and rectangle[3] > rectangle[1]
            clickable = clickable and min(rectangle[2], box[2]) > max(rectangle[0], box[0])
            clickable = clickable and min(rectangle[3], box[3]) > max(rectangle[1], box[1])
            links.append({"target": str(action["/URI"]), "page": number + 1,
                          "rect": rectangle, "clickable": clickable, "label": ""})
    if include_text and links:
        with pdfplumber.open(path) as pdf:
            source_rows = Counter(" ".join(line.split()) for page in pdf.pages
                                  for line in (page.extract_text() or "").splitlines())
            for link in links:
                if not link["clickable"]:
                    continue
                page = pdf.pages[link["page"] - 1]
                if page.rotation:
                    raise ValueError("Use DOCX input to preserve links from a rotated PDF.")
                x0, y0, x1, y1 = link["rect"]
                bounds = (max(0, x0), max(0, page.height - y1),
                          min(page.width, x1), min(page.height, page.height - y0))
                # Crop includes even tiny pieces of adjacent glyphs. Character
                # centers isolate this label when link rectangles touch rows.
                text = page.filter(lambda item: item.get("object_type") == "char" and
                                   bounds[0] <= (item["x0"] + item["x1"]) / 2 <= bounds[2] and
                                   bounds[1] <= (item["top"] + item["bottom"]) / 2 <= bounds[3]).extract_text() or ""
                link["label"] = " ".join(text.split())
                row = page.filter(lambda item: item.get("object_type") == "char" and
                                  bounds[1] <= (item["top"] + item["bottom"]) / 2 <= bounds[3]).extract_text() or ""
                link["context"] = " ".join(row.split())
                if link["label"] and (source_rows[link["context"]] > 1 or
                                      link["context"].count(link["label"]) > 1):
                    raise ValueError("PDF link row is ambiguous; use DOCX input to preserve its occurrence.")
    return links


def hyperlink_report(source_docx, optimized_docx, source_pdf, optimized_pdf):
    docx = source_docx if source_docx and Path(source_docx).is_file() else optimized_docx
    if docx and Path(docx).is_file():
        expected = read_docx_links(docx)
    elif source_pdf and Path(source_pdf).is_file():
        expected = read_pdf_links(source_pdf)
    else:
        expected = []
    observed = read_pdf_links(optimized_pdf)
    expected_counts = Counter(_target_key(link["target"]) for link in expected)
    if optimized_docx and optimized_docx != docx and Path(optimized_docx).is_file():
        # Counter union takes the maximum count per target, not a double count
        # of source and output. Newly added links must be present too.
        expected_counts |= Counter(_target_key(link["target"]) for link in read_docx_links(optimized_docx))
    observed_counts = Counter(_target_key(link["target"]) for link in observed if link["clickable"])
    missing = expected_counts - observed_counts
    return {"passed": not missing, "expected_count": sum(expected_counts.values()),
            "clickable_count": sum(observed_counts.values()),
            "missing": [{"target": target, "count": count} for target, count in sorted(missing.items())],
            "invalid_click_areas": [link for link in observed if not link["clickable"]]}


def linked_paragraph_text(text, remaining_links):
    """Add ReportLab link markup at source labels, consuming each annotation once."""
    spans = []
    for index, link in sorted(enumerate(remaining_links), key=lambda pair: -len(pair[1]["label"])):
        label = link["label"]
        if not label:
            continue
        if link.get("context") != " ".join(text.split()):
            continue
        if urlsplit(link["target"]).scheme.lower() not in {"http", "https", "mailto"}:
            raise ValueError("Use DOCX input to preserve this PDF link type.")
        start = text.find(label)
        while start >= 0:
            end = start + len(label)
            if all(end <= left or start >= right for left, right, _, _ in spans):
                spans.append((start, end, link["target"], index))
                break
            start = text.find(label, start + 1)
    markup, cursor = [], 0
    for start, end, target, _ in sorted(spans):
        markup.append(escape(text[cursor:start]))
        markup.append(f'<link href="{escape(target, quote=True)}" color="blue">{escape(text[start:end])}</link>')
        cursor = end
    markup.append(escape(text[cursor:]))
    for index in sorted((span[3] for span in spans), reverse=True):
        del remaining_links[index]
    return "".join(markup)

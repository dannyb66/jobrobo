import os
import json
import re
import shutil
import tempfile
from typing import Dict, List, Optional, Tuple
from copy import deepcopy
from collections import Counter
import subprocess
import unicodedata
from openai import OpenAI
from pathlib import Path
import pdfplumber
from PyPDF2 import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from io import BytesIO
import textwrap
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Paragraph, SimpleDocTemplate
from reportlab.lib.styles import getSampleStyleSheet
from docx import Document
from dotenv import load_dotenv
from modules.config_loader import load_runtime_config, resource_path
from modules.ai.openai_key_loader import load_openai_key
from modules.resume_links import hyperlink_report, linked_paragraph_text, read_pdf_links
# from config.settings import replace_job_title, rewrite_bullets


VALID_OPTIMIZATION_MODES = {"skills", "bullets", "full"}
DEFAULT_SKILL_BANK_PATH = resource_path("config/skills/Skills_Keyword_Bank_Staff_Principal_2026-10.md")
DEFAULT_BULLET_BANK_PATH = resource_path("config/bullets/Trek_Health_Bullet_Bank.md")
DEFAULT_EXPECTED_PAGE_COUNT = 2

DEFAULT_PROJECT_BULLET_BANKS = [
    {
        "path": "config/bullets/Trek_Health_Bullet_Bank.md",
        "company": "Trek Health",
        "min_bullets": 7,
        "max_bullets": 7,
        "required_sections": ["A", "N"],
    },
    {
        "path": "config/bullets/Codex_SelfHosted_Bullet_Bank.md",
        "company": "CODEX SELF-HOSTED",
        "min_bullets": 3,
        "max_bullets": 5,
        "required_sections": ["A"],
    },
    {
        "path": "config/bullets/Sohamhamso_Bullet_Bank.md",
        "company": "SOHAMHAMSO",
        "min_bullets": 2,
        "max_bullets": 4,
        "required_sections": ["A"],
    },
    {
        "path": "config/bullets/SponsorSkip_Bullet_Bank.md",
        "company": "SPONSORSKIP",
        "min_bullets": 1,
        "max_bullets": 2,
        "required_sections": ["A"],
    },
]


def _bank_resource_path(path: Optional[str], default: str) -> Path:
    """Resolve bank resources independently of cwd in development and app bundles."""
    requested = Path(path).expanduser() if path else Path(default)
    return requested if requested.is_absolute() else resource_path(str(requested))


def _default_project_bank_settings(bank_path: Path) -> Dict[str, object]:
    """Return safe cardinality defaults for a known bank without requiring config metadata."""
    name = bank_path.name.lower()
    if "codex_selfhosted" in name:
        return {"min_bullets": 3, "max_bullets": 5, "required_sections": ["A"]}
    if "sohamhamso" in name:
        return {"min_bullets": 2, "max_bullets": 4, "required_sections": ["A"]}
    if "sponsorskip" in name:
        return {"min_bullets": 1, "max_bullets": 2, "required_sections": ["A"]}
    return {"min_bullets": 7, "max_bullets": 7, "required_sections": ["A", "N"]}


def normalize_keyword(value: str) -> str:
    """Normalize a keyword for matching while retaining the original display text."""
    value = re.sub(r"\([^)]*\)", " ", value)
    value = value.lower().replace("&", " and ")
    return re.sub(r"[^a-z0-9+#]+", " ", value).strip()


def keyword_variants(value: str) -> List[str]:
    """Return the full phrase plus acronym/parenthetical forms for ATS matching."""
    variants = {normalize_keyword(value)}
    variants.update(normalize_keyword(part) for part in re.findall(r"\(([^)]*)\)", value))
    return [variant for variant in variants if variant]


def _parse_bank_table_row(line: str) -> Optional[Tuple[str, str, str]]:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    if len(cells) < 3 or cells[0].lower() in {"keyword", "tier"} or set(cells[0]) <= {"-", ":"}:
        return None
    return cells[0], cells[1], cells[2]


def load_skill_bank(path: Optional[str] = None) -> Dict[str, object]:
    """Load the Markdown bank as guidance data; the job description remains authoritative."""
    bank_path = _bank_resource_path(path, "config/skills/Skills_Keyword_Bank_Staff_Principal_2026-10.md")
    result: Dict[str, object] = {
        "path": str(bank_path),
        "keywords": [],
        "profiles": {},
        "avoid": [],
        "format_rules": [],
    }
    if not bank_path.exists():
        return result

    current_section = ""
    current_category = ""
    keywords = []
    profiles = {}
    avoid = []
    format_rules = []
    for raw_line in bank_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            current_section = line[3:].strip()
            current_category = ""
            continue
        if line.startswith("### "):
            current_category = line[4:].strip()
            continue

        if current_section.startswith("2.") and line.startswith("|"):
            row = _parse_bank_table_row(line)
            if row:
                keyword, tier, status = row
                keywords.append({
                    "keyword": keyword,
                    "tier": tier,
                    "status": status,
                    "category": current_category,
                    "normalized": normalize_keyword(keyword),
                })
        elif current_section.startswith("4.") and line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 3 and cells[0].lower() not in {"target", "---"} and not set(cells[0]) <= {"-", ":"}:
                profile_name = re.sub(r"\*", "", cells[0]).strip()
                profile_name = re.sub(r"\s*\([^)]*\)$", "", profile_name).strip()
                profiles[profile_name] = {
                    "lead_rows": cells[1],
                    "must_have": [item.strip() for item in cells[2].split(",") if item.strip()],
                }
        elif current_section.startswith("3.") and line.startswith("-"):
            avoid.extend(re.findall(r"\*\*([^*]+)\*\*", line) or [line.lstrip("- ")])
        elif current_section.startswith("5.") and re.match(r"^\d+\.", line):
            format_rules.append(re.sub(r"^\d+\.\s*", "", line))

    result["keywords"] = keywords
    result["profiles"] = profiles
    result["avoid"] = avoid
    result["format_rules"] = format_rules
    return result


def infer_role_profile(job_title: str, job_description: str, profiles: Dict[str, object], override: str = "") -> str:
    """Infer a bank profile from the JD, allowing an explicit profile override."""
    if override and override.lower() not in {"auto", "infer", "none"}:
        return override
    text = f"{job_title} {job_description}".lower()
    candidates = {
        "Staff / Principal AI Platform": ["platform", "infrastructure", "mcp", "eval", "observability", "kubernetes"],
        "Senior / Staff Agents Engineer": ["agent", "agentic", "langgraph", "tool use", "rag", "llm"],
        "Healthcare AI": ["healthcare", "hipaa", "fhir", "medical", "payer", "claims", "edi"],
        "Senior / Staff Backend / Full-Stack": ["backend", "full stack", "full-stack", "api", "react", "java", "microservices"],
    }
    scored = [(sum(text.count(term) for term in terms), name) for name, terms in candidates.items() if name in profiles or not profiles]
    return max(scored, key=lambda item: item[0])[1] if scored else "Staff / Principal AI Platform"


def build_guided_keywords(job_description: str, extracted_keywords: List[str], job_title: str,
                          current_skills: List[str], bank: Dict[str, object], profile_name: str,
                          allow_unverified: bool = True) -> List[str]:
    """Combine existing JD extraction with bank vocabulary found in the JD or selected profile."""
    existing = []
    seen = set()

    def add(value: str):
        value = re.sub(r"\s+", " ", value).strip(" ,.;:")
        key = normalize_keyword(value)
        if value and key and key not in seen:
            seen.add(key)
            existing.append(value)

    for keyword in extracted_keywords:
        add(keyword)

    profile = bank.get("profiles", {}).get(profile_name, {}) if isinstance(bank.get("profiles"), dict) else {}
    preferred = profile.get("must_have", []) if isinstance(profile, dict) else []
    jd_normalized = normalize_keyword(job_description)
    bank_rows = bank.get("keywords", []) if isinstance(bank.get("keywords"), list) else []
    ranked = []
    for row in bank_rows:
        if not isinstance(row, dict):
            continue
        keyword = row.get("keyword", "")
        normalized = row.get("normalized", normalize_keyword(keyword))
        if not normalized or not any(variant in jd_normalized for variant in keyword_variants(keyword)):
            continue
        if not allow_unverified and "†" in row.get("status", ""):
            continue
        rank = 0
        if keyword in preferred:
            rank += 3
        if "Core" in row.get("tier", ""):
            rank += 2
        if any(variant in normalize_keyword(job_title) for variant in keyword_variants(keyword)):
            rank += 2
        ranked.append((rank, keyword))
    for _, keyword in sorted(ranked, key=lambda item: (-item[0], item[1].lower())):
        add(keyword)

    # Keep existing resume terms available when the JD uses a close variant.
    for skill in current_skills:
        if any(variant in jd_normalized for variant in keyword_variants(skill)):
            add(skill)
    return existing


def calculate_keyword_score(text: str, keywords: List[str], bank: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Return a reproducible coverage score; this is a diagnostic, not an ATS vendor score."""
    bank_rows = {row.get("normalized"): row for row in (bank or {}).get("keywords", []) if isinstance(row, dict)}
    matched, missing = [], []
    total_weight = 0
    matched_weight = 0
    normalized_text = normalize_keyword(text)
    for keyword in keywords:
        key = normalize_keyword(keyword)
        if not key:
            continue
        row = bank_rows.get(key, {})
        weight = 2 if "Core" in row.get("tier", "") else 1
        total_weight += weight
        if any(variant in normalized_text for variant in keyword_variants(keyword)):
            matched.append(keyword)
            matched_weight += weight
        else:
            missing.append(keyword)
    score = round((matched_weight / total_weight) * 100, 1) if total_weight else 0.0
    return {"score": score, "matched": matched, "missing": missing, "total": len(matched) + len(missing)}


def _expand_bullet_refs(value: str) -> List[str]:
    """Expand references such as A1–A4 into individual bank IDs."""
    refs = []
    for token in re.split(r"[,·\s]+", value.replace("–", "-").replace("—", "-")):
        match = re.fullmatch(r"([A-Z])(\d+)(?:-\1(\d+))?", token.strip())
        if not match:
            continue
        start = int(match.group(2))
        end = int(match.group(3) or start)
        refs.extend(f"{match.group(1)}{number}" for number in range(start, end + 1))
    return refs


def load_bullet_bank(path: Optional[str] = None) -> Dict[str, object]:
    """Parse a Markdown bullet bank into selectable, metric-aware resume bullets."""
    bank_path = _bank_resource_path(path, "config/bullets/Trek_Health_Bullet_Bank.md")
    defaults = _default_project_bank_settings(bank_path)
    result: Dict[str, object] = {
        "path": str(bank_path),
        "company": "Trek Health",
        "bullets": [],
        "metrics": {},
        "presets": {},
        "lookup": {},
        "fluency_terms": [],
        **defaults,
    }
    if not bank_path.exists():
        return result

    section = ""
    subsection = ""
    bullets = []
    metrics = {}
    presets = {}
    lookup = {}
    fluency_terms = []

    for raw_line in bank_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("## "):
            section = line[3:].strip()
            subsection = ""
            continue
        if line.startswith("### "):
            subsection = line[4:].strip()
            continue

        if section.startswith("0.") and line.startswith("**Role:**"):
            role_match = re.search(r"Role:\*\s*[^,]+,\s*([^,]+)", line)
            if role_match:
                result["company"] = role_match.group(1).strip()
        elif line.startswith("**Project:**"):
            project_match = re.search(r"Project:\*+\s*([^,]+)", line)
            if project_match:
                result["company"] = project_match.group(1).strip()
        elif section.startswith("2.") and line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 3 and re.fullmatch(r"[A-Z]\d+", cells[0]):
                metrics[cells[0]] = {"metric": cells[1], "source": cells[2], "status": cells[3] if len(cells) >= 4 else ""}
        elif section.startswith("3.") and line.startswith("|"):
            continue
        elif section.startswith("3.") and re.match(r"^(?:[A-Z]\d+|\d+)\.\s+", line) and " · " in line:
            match = re.match(r"^(?:(?P<section>[A-Z])(?P<section_number>\d+)|(?P<number>\d+))\.\s+(.*?)\s+·\s+`([^`]*)`\s+·\s+(.+)$", line)
            if match and subsection:
                section_id = match.group("section") or subsection.split(".", 1)[0].strip()
                number = match.group("section_number") or match.group("number")
                raw_text = match.group(4)
                text_value = raw_text.replace("†", "").replace("‡", "").strip()
                metric_ids = re.findall(r"\b[A-Z]\d+\b", match.group(6))
                bullets.append({
                    "id": f"{section_id}{number}",
                    "section": section_id,
                    "text": text_value,
                    "tags": [tag for tag in match.group(5).split() if tag],
                    "metrics": metric_ids,
                    "unverified": any(marker in raw_text for marker in ("†", "‡")) or any(
                        any(marker in metrics.get(metric_id, {}).get("status", "") for marker in ("†", "‡"))
                        for metric_id in metric_ids
                    ),
                    "lead_verb": text_value.split()[0].strip(" ,:;.-") if text_value else "",
                    "length": len(text_value),
                })
        elif section.startswith("4.") and line.startswith("-"):
            fluency_terms.extend(re.findall(r"\*\*([^*]+)\*\*", line))
        elif section.startswith("5.") and line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0].lower() not in {"target role", "---"} and not set(cells[0]) <= {"-", ":"}:
                target = re.sub(r"\*", "", cells[0]).strip()
                presets[target] = _expand_bullet_refs(cells[1])
        elif section.startswith("6.") and line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0].lower() not in {"jd says…", "jd says...", "---"} and not set(cells[0]) <= {"-", ":"}:
                lookup[cells[0].lower()] = _expand_bullet_refs(cells[1])

    result["bullets"] = bullets
    result["metrics"] = metrics
    result["presets"] = presets
    result["lookup"] = lookup
    result["fluency_terms"] = fluency_terms
    return result


def _select_bullet_preset(job_title: str, job_description: str, presets: Dict[str, List[str]]) -> str:
    """Choose the closest bank preset for the target JD."""
    text = normalize_keyword(f"{job_title} {job_description}")
    rules = [
        (["Healthcare AI / Health-tech"], ["healthcare", "health tech", "payer", "contract", "price transparency", "edi", "claims"]),
        (["Healthcare data / RCM / payer"], ["rcm", "revenue cycle", "remittance", "medical claims", "edi 835"]),
        (["AI Security / Safety / Governance"], ["security", "safety", "governance", "prompt injection", "guardrail"]),
        (["Evals / Quality Engineer"], ["eval", "evaluation", "regression", "quality"]),
        (["SRE / Reliability for AI"], ["sre", "reliability", "incident", "on call", "rollback"]),
        (["Data Platform / Snowflake"], ["snowflake", "snowpark", "data platform", "etl"]),
        (["Senior/Staff Backend or Full-Stack"], ["backend", "full stack", "api", "typescript", "next js"]),
        (["Founding / early-stage startup", "Founding / generalist (2 lines)"], ["founding", "startup", "zero to one", "0 1"]),
        (["Staff Agents Engineer (applied)", "Agents / Applied AI", "AI Security / Safety / Governance"], ["agent", "agentic", "react", "subagent", "tool calling"]),
        (["Staff/Principal AI Platform", "Staff/Principal AI platform roles", "Staff/Principal AI (general)", "AI Platform / Infra"], ["platform", "infrastructure", "architecture", "principal", "staff"]),
        (["ML Inference / Model Serving"], ["inference", "model serving", "vllm", "throughput", "latency", "gpu"]),
        (["Search / Retrieval"], ["search", "retrieval", "embedding", "vector", "rrf"]),
        (["LLM Applications / Applied AI"], ["llm", "generative ai", "prompt", "structured output"]),
        (["Media / Multimodal AI"], ["tts", "speech", "video", "multimodal", "media"]),
    ]
    for preset_names, terms in rules:
        for preset in preset_names:
            if preset in presets and any(normalize_keyword(term) in text for term in terms):
                return preset

    # Banks may add a new preset without code changes. Prefer the preset with
    # the most meaningful target-role token overlap, then fall back to the
    # bank's first preset (which is its documented default).
    stop_words = {"and", "or", "the", "for", "with", "role", "roles", "general", "lines", "type"}
    text_tokens = set(text.split())
    ranked = []
    for preset in presets:
        preset_tokens = {token for token in normalize_keyword(preset).split() if token not in stop_words}
        ranked.append((len(text_tokens.intersection(preset_tokens)), preset))
    return max(ranked, key=lambda item: (item[0], -list(presets).index(item[1])))[1] if ranked else ""


def select_bullet_bank_bullets(job_title: str, job_description: str, bank: Dict[str, object],
                               max_bullets: Optional[int] = None, allow_unverified: bool = False,
                               required_sections: Optional[List[str]] = None,
                               min_bullets: Optional[int] = None,
                               excluded_metrics: Optional[List[str]] = None,
                               excluded_lead_verbs: Optional[List[str]] = None) -> List[Dict[str, object]]:
    """Select fact-preserving bank bullets with JD relevance and metric/verb deduplication."""
    candidates = [item for item in bank.get("bullets", []) if isinstance(item, dict)]
    if not candidates:
        return []
    defaults = _default_project_bank_settings(Path(str(bank.get("path", ""))))
    max_bullets = int(max_bullets or bank.get("max_bullets") or defaults["max_bullets"])
    min_bullets = int(min_bullets or bank.get("min_bullets") or defaults["min_bullets"])
    required_sections = required_sections or bank.get("required_sections") or defaults["required_sections"]
    text = normalize_keyword(f"{job_title} {job_description}")
    preset_name = _select_bullet_preset(job_title, job_description, bank.get("presets", {}))
    preset_refs = set(bank.get("presets", {}).get(preset_name, []))
    lookup_refs = set()
    for phrase, refs in bank.get("lookup", {}).items():
        if normalize_keyword(phrase) in text:
            lookup_refs.update(refs)

    def score(candidate: Dict[str, object]) -> int:
        candidate_text = normalize_keyword(candidate["text"])
        overlap = sum(1 for token in set(candidate_text.split()) if len(token) > 2 and token in text)
        value = overlap
        if candidate["id"] in preset_refs:
            value += 8
        if candidate["id"] in lookup_refs:
            value += 10
        if candidate["section"] in set(required_sections):
            value += 2
        if 110 <= candidate["length"] <= 126:
            value += 2
        return value

    eligible = [candidate for candidate in candidates if allow_unverified or not candidate.get("unverified")]
    ranked = sorted(eligible, key=lambda candidate: (-score(candidate), candidate["id"]))
    selected = []
    used_metrics = set(excluded_metrics or [])
    used_verbs = {verb.lower() for verb in (excluded_lead_verbs or [])}
    present_tense = 0

    def try_add(candidate: Dict[str, object], required: bool = False) -> bool:
        nonlocal present_tense
        if len(selected) >= max_bullets or candidate in selected:
            return False
        if used_metrics.intersection(candidate.get("metrics", [])):
            return False
        verb = candidate.get("lead_verb", "").lower()
        if verb in used_verbs:
            return False
        if verb in {"own", "mentor", "lead", "set", "align", "define"}:
            if present_tense >= 2:
                return False
            present_tense += 1
        selected.append(candidate)
        used_metrics.update(candidate.get("metrics", []))
        used_verbs.add(verb)
        return True

    for required_section in required_sections:
        for candidate in ranked:
            if candidate["section"] == required_section and try_add(candidate, required=True):
                break
    for candidate in ranked:
        if len(selected) >= max_bullets:
            break
        try_add(candidate)
    # If a bank has enough safe candidates, never reintroduce an unverified
    # claim just to hit its target count. This is especially important for the
    # SponsorSkip result bullets and candidate-supplied Codex benchmarks.
    return selected[:max_bullets] if len(selected) >= min_bullets else selected


def load_project_bullet_banks(configured_banks: Optional[List[Dict[str, object]]] = None) -> List[Dict[str, object]]:
    """Load configured project banks, resolving repo-relative paths for GUI/runtime use."""
    entries = DEFAULT_PROJECT_BULLET_BANKS if configured_banks is None else configured_banks
    loaded = []
    for entry in entries:
        if isinstance(entry, str):
            entry = {"path": entry}
        if not isinstance(entry, dict):
            continue
        raw_path = entry.get("path")
        if not raw_path:
            continue
        path = _bank_resource_path(str(raw_path), str(raw_path))
        bank = load_bullet_bank(str(path))
        if not bank.get("bullets"):
            continue
        spec = dict(entry)
        spec["path"] = str(path)
        spec["company"] = entry.get("company") or bank.get("company")
        spec["min_bullets"] = int(entry.get("min_bullets", bank.get("min_bullets", 1)) or 1)
        spec["max_bullets"] = int(entry.get("max_bullets", bank.get("max_bullets", spec["min_bullets"])) or spec["min_bullets"])
        spec["required_sections"] = entry.get("required_sections", bank.get("required_sections", ["A"]))
        spec["allow_unverified"] = bool(entry.get("allow_unverified", entry.get("allow_unverified_bullet_terms", False)))
        spec["bank"] = bank
        loaded.append(spec)
    return loaded

class ResumeOptimizer:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    def extract_keywords(self, job_description: str) -> List[str]:
        """Extract top 15 keywords from job description using OpenAI API."""
        self.last_keyword_error = None
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are an ATS expert that analyzes job descriptions and "
                            "identifies the most important keywords for ATS systems like Greenhouse and Workday. "
                            "Return exactly 15 most important keywords as a JSON object in this format:\n"
                            '{"keywords": ["keyword1", "keyword2", ..., "keyword15"]}'
                        )
                    },
                    {
                        "role": "user",
                        "content": (
                            "Analyze this job description and identify the top 15 most important keywords "
                            "that should be included in a resume to pass ATS systems:\n\n" + job_description
                        )
                    }
                ]
            )

            content = response.choices[0].message.content.strip()
            # print(f"\n🔍 Raw GPT response:\n{content}\n")

            # Try parsing directly
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                # Try extracting JSON substring
                match = re.search(r'\{.*\}', content, re.DOTALL)
                if match:
                    result = json.loads(match.group())
                else:
                    raise ValueError("No valid JSON found in response.")

            # print(f"✅ Extracted keywords: {result}")
            keywords = result.get("keywords") if isinstance(result, dict) else None
            if not isinstance(keywords, list) or not all(isinstance(keyword, str) and keyword.strip() for keyword in keywords):
                raise ValueError("Keyword response must contain a list of nonempty strings.")
            return list(dict.fromkeys(keyword.strip() for keyword in keywords))[:50]

        except Exception as e:
            self.last_keyword_error = str(e)
            print(f"❌ Error extracting keywords: {e}")
            return []
        
    def read_pdf_resume(self, resume_path: str) -> Tuple[str, List[str], dict]:
        """Read PDF resume and extract the entire skills section with formatting information."""
        try:
            with pdfplumber.open(resume_path) as pdf:
                content = ""
                skills_page = 0
                skills_bbox = None
                current_skills = []

                for page_num, page in enumerate(pdf.pages):
                    page_text = page.extract_text()
                    content += page_text + "\n"

                    lines = page_text.splitlines()
                    skills_started = False
                    skills_heading_only = False
                    skills_lines = []

                    for i, line in enumerate(lines):
                        if not skills_started and re.match(r"(?i)^skills\s*:", line.strip()):
                            skills_started = True
                            skills_lines.append(line)
                            continue
                        if not skills_started and line.strip().upper() == "SKILLS":
                            skills_started = True
                            skills_heading_only = True
                            continue
                        if skills_started:
                            # Stop if we hit the next section (all caps heading or known section)
                            if re.match(r"^[A-Z\s]{5,}$", line.strip()):
                                break
                            skills_lines.append(line)

                    if skills_lines:
                        skills_page = page_num
                        skills_text = " ".join(skills_lines)
                        # Extract the part after "Skills:"
                        skills_raw = re.sub(r"(?i)^skills\s*:\s*", "", skills_text)
                        current_skills = [skill.strip() for skill in skills_raw.split(',') if skill.strip()]

                        # Extract skills bbox
                        words = page.extract_words()
                        for word in words:
                            if "skills" in word['text'].lower():
                                skills_bbox = {
                                    'x0': word['x0'],
                                    'x1': word['x1'],
                                    'top': word['top'],
                                    'bottom': word['bottom']
                                }
                                break

                        break  # We found the section, no need to check other pages

                if not current_skills:
                    raise ValueError("Skills section not found in resume")

                format_info = {
                    'skills_page': skills_page,
                    'skills_bbox': skills_bbox
                }

                # print(f"Skills section found on page {skills_page + 1} with bbox: {skills_bbox}")
                # print(f"Extracted skills: {current_skills}")
                return content, current_skills, format_info

        except Exception as e:
            print(f"Error reading PDF resume: {e}")
            return "", [], {}
        
    def optimize_skills(self, current_skills: List[str], new_keywords: List[str], job_description: str,
                        max_count: Optional[int] = 50) -> List[str]:
        """Prefer JD vocabulary and deduplicate proven acronym aliases within source capacity."""
        def aliases(value):
            parts = re.findall(r"\(([^)]*)\)", value)
            base = re.sub(r"\([^)]*\)", " ", value).strip()
            words = re.findall(r"[A-Za-z0-9]+", base)
            initials = "".join(word[0] for word in words).lower()
            acronyms = []
            for part in parts:
                compact = re.sub(r"[^A-Za-z0-9]", "", part).lower()
                if re.fullmatch(r"[A-Z][A-Za-z0-9+#/.-]{1,14}", part.strip()) and (
                    compact == initials or compact.endswith("s") and compact[:-1] == initials
                ):
                    acronyms.append(compact)
            # Parenthetical context such as Infrastructure (AWS) is not an expansion of AWS.
            if parts and len(acronyms) != len(parts):
                return {re.sub(r"[^a-z0-9+#]+", " ", value.lower()).strip()}, False
            return {normalize_keyword(base), *acronyms, *([initials] if acronyms else [])}, bool(acronyms)

        selected, concepts = [], []
        # JD terms come first; full expansion with its verified acronym wins over an alias.
        for value in list(new_keywords) + list(current_skills):
            value = value.strip()
            keys, expanded = aliases(value)
            keys.discard("")
            if not value or not keys:
                continue
            existing = next((index for index, (known, _) in enumerate(concepts) if known & keys), None)
            if existing is None:
                selected.append(value)
                concepts.append((keys, expanded))
            else:
                known, already_expanded = concepts[existing]
                if expanded and not already_expanded:
                    selected[existing] = value
                concepts[existing] = (known | keys, expanded or already_expanded)
        capacity = len(current_skills)
        if max_count and max_count > 0:
            capacity = min(capacity, max_count)
        return selected[:capacity]

    def save_optimized_pdf(self, resume_path: str, optimized_skills: List[str], format_info: dict, output_path: str):
        try:
            source_links = read_pdf_links(resume_path, include_text=True)
            # Step 1: Use pdfplumber to extract structured text
            with pdfplumber.open(resume_path) as pdf:
                full_text_lines = []
                skills_section_found = False
                skills_started = False
                skills_heading_only = False

                for page in pdf.pages:
                    page_lines = page.extract_text().splitlines()
                    i = 0
                    while i < len(page_lines):
                        line = page_lines[i]
                        if not skills_started and re.match(r"(?i)^skills\s*:", line.strip()):
                            skills_started = True
                            skills_section_found = True
                            skills_heading_only = False

                            # Format the new skills section
                            wrapped_skills = textwrap.wrap(", ".join(optimized_skills), width=110)
                            wrapped_skills[0] = "Skills: " + wrapped_skills[0]  # Add label to first line
                            full_text_lines.extend(wrapped_skills)

                            # Skip original skills block
                            i += 1
                            while i < len(page_lines):
                                next_line = page_lines[i]
                                if re.match(r"^[A-Z\s]{5,}$", next_line.strip()):
                                    break
                                i += 1
                            continue
                        if not skills_started and line.strip().upper() == "SKILLS":
                            skills_started = True
                            skills_section_found = True
                            skills_heading_only = True
                            full_text_lines.append(line)
                            wrapped_skills = textwrap.wrap(", ".join(optimized_skills), width=110)
                            full_text_lines.extend(wrapped_skills)
                            i += 1
                            while i < len(page_lines):
                                next_line = page_lines[i]
                                if re.match(r"^[A-Z\s]{5,}$", next_line.strip()):
                                    break
                                i += 1
                            continue
                        if skills_started and re.match(r"^[A-Z\s]{5,}$", line.strip()):
                            skills_started = False
                        full_text_lines.append(line)
                        i += 1

                if not skills_section_found:
                    raise ValueError("Skills section not found in the resume.")

            # Step 2: Rebuild PDF using ReportLab
            buffer = BytesIO()
            doc = SimpleDocTemplate(buffer, pagesize=letter,
                                    rightMargin=40, leftMargin=40,
                                    topMargin=60, bottomMargin=40)
            styles = getSampleStyleSheet()
            story = []

            for para in "\n".join(full_text_lines).split('\n\n'):
                for line in para.strip().splitlines():
                    story.append(Paragraph(linked_paragraph_text(line.strip(), source_links), styles["Normal"]))

            if source_links:
                raise ValueError("PDF links could not be mapped to the rewritten text; use DOCX input.")

            doc.build(story)

            # Step 3: Save to disk
            with open(output_path, 'wb') as f:
                f.write(buffer.getvalue())

            print(f"✅ Successfully saved updated PDF to: {output_path}")

        except Exception as e:
            print(f"❌ Error saving optimized PDF resume: {e}")
            raise

    def read_docx_resume(self, resume_path: str) -> Tuple[Document, List[str]]:
        """Read a DOCX resume and extract the skills section."""
        try:
            doc = Document(resume_path)
            skills_text = ""
            skills_started = False
            skills_heading_only = False
            skills_lines = []

            for para in doc.paragraphs:
                text = para.text.strip()
                if not skills_started and re.match(r"(?i)^skills\s*:", text):
                    skills_started = True
                    skills_lines.append(text)
                    continue
                if not skills_started and text.upper() == "SKILLS":
                    skills_started = True
                    skills_heading_only = True
                    continue
                if skills_started:
                    if self._is_resume_section(para):
                        break
                    skills_lines.append(text)

            if not skills_lines:
                raise ValueError("Skills section not found in DOCX resume")

            skills_text = " ".join(skills_lines)
            skills_raw = re.sub(r"(?i)^skills\s*:\s*", "", skills_text)
            current_skills = [s.strip() for s in skills_raw.split(',') if s.strip()]

            return doc, current_skills

        except Exception as e:
            print(f"Error reading DOCX resume: {e}")
            return None, []
        
    # Replace job titles in the Professional Experience section
    def replace_job_titles(self, doc: Document, new_title: str, max_line_length: int = 150) -> None:
        """
        Replace all job titles in the 'Professional Experience' section with the given new_title,
        padding it with spaces so the final line reaches up to max_line_length without overflowing.
        """
        try:
            is_in_experience_section = False
            job_title_with_dates_pattern = re.compile(r'^(.*?)(\s{2,}|\t+)?\(?[A-Za-z]+\s+\d{4}.*\)?$')

            for para in doc.paragraphs:
                text = para.text.strip()
                if not text:
                    continue

                # Toggle section flags
                if text.upper() in {"PROFESSIONAL EXPERIENCE", "WORK EXPERIENCE", "EXPERIENCE"}:
                    is_in_experience_section = True
                    continue
                elif self._is_resume_section(para):
                    is_in_experience_section = False
                    continue

                if is_in_experience_section:
                    match = job_title_with_dates_pattern.match(text)
                    if match:
                        old_title = match.group(1).strip()
                        rest_of_line = text[len(old_title):].strip()

                        # Limit new title to fit within line length
                        allowed_title_length = max_line_length - len(rest_of_line)
                        safe_new_title = new_title[:allowed_title_length].rstrip()

                        # Clean up the title, no extra spaces, no special characters or numbers
                        safe_new_title = re.sub(r'[^A-Za-z\s]', '', safe_new_title).strip()

                        # Calculate how many spaces to add after title
                        padding_space = max(1, max_line_length - len(safe_new_title + ' ' + rest_of_line))
                        padded_title = safe_new_title + ' ' * padding_space                        

                        # Update paragraph text with a tab between the title and rest of the line, and apply italic style
                        # para.text = padded_title + rest_of_line
                        self._replace_paragraph_text(para, safe_new_title + "\t" + rest_of_line.lstrip())

        except Exception as e:
            print(f"❌ Error replacing job titles: {e}")

    # Rewrite experience bullets to match job description
    def rewrite_experience_bullets(self, doc: Document, job_title: str, job_description: str,
                                   optimized_skills: List[str], bullet_bank: Optional[Dict[str, object]] = None,
                                   bullet_bank_company: str = "Trek Health", max_bank_bullets: int = 7,
                                   allow_unverified_bullet_terms: bool = False,
                                   guided_keywords: Optional[List[str]] = None,
                                   project_bullet_banks: Optional[List[Dict[str, object]]] = None) -> None:
        """Rewrite experience bullets and apply exact JD-selected bullets to configured projects."""
        try:
            experience_bullets = self._extract_experience_bullets(doc)
            print(f"🔍 Extracted experience bullets: {experience_bullets}")
            self.last_bullet_bank_selection = []
            self.last_bullet_bank_selections = {}
            bank_specs = list(project_bullet_banks or [])
            if project_bullet_banks is None and bullet_bank:
                bank_specs = [{
                    "bank": bullet_bank,
                    "company": bullet_bank_company,
                    "min_bullets": max_bank_bullets,
                    "max_bullets": max_bank_bullets,
                    "required_sections": bullet_bank.get("required_sections", ["A", "N"]),
                    "allow_unverified": allow_unverified_bullet_terms,
                }]

            target_entries = []
            selected_targets = []
            used_metrics = []
            used_verbs = []
            for spec in bank_specs:
                bank = spec.get("bank") if isinstance(spec, dict) else None
                company = spec.get("company") if isinstance(spec, dict) else ""
                if not bank or not company:
                    continue
                target_entry = next(
                    (entry for entry in experience_bullets
                     if normalize_keyword(entry.get("company", "")) == normalize_keyword(company)),
                    None,
                )
                is_present = target_entry is not None or any(
                    normalize_keyword(paragraph.text.split("\t", 1)[0]) == normalize_keyword(company)
                    for paragraph in doc.paragraphs
                )
                if not is_present:
                    continue
                selected = select_bullet_bank_bullets(
                    job_title,
                    job_description,
                    bank,
                    int(spec.get("max_bullets", bank.get("max_bullets", max_bank_bullets)) or max_bank_bullets),
                    bool(spec.get("allow_unverified", allow_unverified_bullet_terms)),
                    spec.get("required_sections"),
                    int(spec.get("min_bullets", bank.get("min_bullets", 1)) or 1),
                    used_metrics,
                    used_verbs,
                )
                if not selected:
                    continue
                selected_targets.append((company, selected, target_entry))
                used_metrics.extend(metric for item in selected for metric in item.get("metrics", []))
                used_verbs.extend(item.get("lead_verb", "") for item in selected)
                if target_entry:
                    target_entries.append(target_entry)

            # Let the existing LLM flow handle every other professional entry.
            # Bank-targeted Trek Health experience is excluded so exact bullets
            # remain exact; project entries are outside this LLM extraction path.
            llm_entries = experience_bullets
            if target_entries:
                llm_entries = [entry for entry in experience_bullets if entry not in target_entries]
            rewritten_experience = self._call_openai_to_rewrite_bullets(
                llm_entries, job_title, job_description, optimized_skills, guided_keywords or []
            ) if llm_entries else []
            print(f"🔍 Rewritten experience bullets: {rewritten_experience}")

            if rewritten_experience:
                self._update_document_with_rewritten_bullets(doc, llm_entries, rewritten_experience)
            for company, selected_bank_bullets, _ in selected_targets:
                selected_text = [bullet["text"] for bullet in selected_bank_bullets]
                if self._replace_first_company_bullets(doc, company, selected_text):
                    self.last_bullet_bank_selections[company] = selected_bank_bullets
                    self.last_bullet_bank_selection.extend(selected_bank_bullets)
                    print(f"✅ Applied {len(selected_text)} exact bank bullets to first {company} entry.")

        except Exception as e:
            print(f"❌ Error rewriting experience bullets: {e}")

    def _replace_first_company_bullets(self, doc: Document, company_name: str, bullets: List[str]) -> bool:
        """Replace only the first matching company's bullet paragraphs and preserve list styling."""
        target_company = normalize_keyword(company_name)
        paragraphs = doc.paragraphs
        for company_index, paragraph in enumerate(paragraphs):
            company_text = normalize_keyword(paragraph.text.split("\t", 1)[0])
            if company_text != target_company:
                continue

            title_index = company_index + 1
            while title_index < len(paragraphs) and not paragraphs[title_index].text.strip():
                title_index += 1
            bullet_paragraphs = []
            cursor = title_index + 1
            while cursor < len(paragraphs):
                current = paragraphs[cursor]
                if current.style.name == "List Paragraph":
                    bullet_paragraphs.append(current)
                    cursor += 1
                    continue
                break
            if not bullet_paragraphs:
                return False

            for paragraph, bullet in zip(bullet_paragraphs, bullets):
                self._replace_paragraph_text(paragraph, bullet)
            for paragraph in reversed(bullet_paragraphs[len(bullets):]):
                paragraph._element.getparent().remove(paragraph._element)

            if len(bullets) > len(bullet_paragraphs):
                insert_after = bullet_paragraphs[-1]._element
                from docx.text.paragraph import Paragraph as DocxParagraph
                for bullet in bullets[len(bullet_paragraphs):]:
                    new_element = deepcopy(bullet_paragraphs[-1]._element)
                    insert_after.addnext(new_element)
                    self._replace_paragraph_text(DocxParagraph(new_element, paragraph._parent), bullet)
                    insert_after = new_element
            return True
        return False

    def _is_resume_section(self, paragraph) -> bool:
        """Recognize source section boundaries without treating company lines as headings."""
        text = paragraph.text.strip()
        if not text or "\t" in text:
            return False
        return paragraph.style.name.startswith("Heading") or text.upper() in {
            "PROFESSIONAL EXPERIENCE", "WORK EXPERIENCE", "EXPERIENCE", "EDUCATION",
            "ENTREPRENEURIAL VENTURES", "ENTREPRENEURIAL VENTURES & PROJECTS",
            "ACADEMIC PROJECTS", "PROJECTS", "CERTIFICATIONS", "SKILLS",
            "ACADEMIC DISTINCTIONS", "AWARDS", "AWARDS & HONORS",
        }

    def _experience_blocks(self, doc: Document):
        """Yield professional entries and their actual bullet paragraphs only."""
        active = False
        company, title, paragraphs = None, None, []
        for paragraph in doc.paragraphs:
            text = paragraph.text.strip()
            if not text:
                continue
            if self._is_resume_section(paragraph):
                if company and title and paragraphs:
                    yield {"company": company, "job_title": title,
                           "bullets": [item.text.strip() for item in paragraphs]}, paragraphs
                company, title, paragraphs = None, None, []
                active = text.upper() in {"PROFESSIONAL EXPERIENCE", "WORK EXPERIENCE", "EXPERIENCE"}
                continue
            if not active:
                continue
            if paragraph.style.name == "List Paragraph":
                if company and title:
                    paragraphs.append(paragraph)
            elif self._is_header_line(text):
                if company and title:
                    if paragraphs:
                        yield {"company": company, "job_title": title,
                               "bullets": [item.text.strip() for item in paragraphs]}, paragraphs
                    company, title, paragraphs = None, None, []
                if company is None:
                    company = text.split("\t", 1)[0].strip()
                else:
                    title = text.split("\t", 1)[0].strip()
        if company and title and paragraphs:
            yield {"company": company, "job_title": title,
                   "bullets": [item.text.strip() for item in paragraphs]}, paragraphs

    def _extract_experience_bullets(self, doc: Document) -> List[dict]:
        return [entry for entry, _ in self._experience_blocks(doc)]

    def _replace_paragraph_text(self, paragraph, text: str) -> None:
        """Keep every source run's font/character spacing, including mixed compression."""
        if paragraph.text == text:
            return
        from docx.text.run import Run
        # paragraph.runs omits runs inside hyperlinks; include them to avoid stale visible text.
        runs = [Run(element, paragraph) for element in paragraph._p.xpath(".//w:r")]
        original_lengths = [len(run.text) for run in runs]
        total = sum(original_lengths)
        if not total:
            paragraph.add_run(text)
            return
        # Redistribute replacement characters in the same proportions as source runs.
        # Assigning run.text preserves rPr; paragraph.text would erase it.
        consumed, previous = 0, 0
        for run, length in zip(runs, original_lengths):
            consumed += length
            end = round(len(text) * consumed / total)
            run.text = text[previous:end]
            previous = end

    def _initialize_experience_entry(self) -> dict:
        """Initialize a new experience entry."""
        return {"company": None, "job_title": None, "bullets": []}

    def _finalize_experience_entry(self, entry: dict, experience_bullets: List[dict]) -> None:
        """Finalize the current experience entry and add it to the list."""
        if entry["company"] and entry["job_title"] and entry["bullets"]:
            experience_bullets.append(entry)

    def _is_section_header(self, text: str, headers: List[str] or str) -> bool:
        """Check if the text matches a section header."""
        if isinstance(headers, list):
            return text.upper() in headers
        return text.upper() == headers

    def _is_header_line(self, text: str) -> bool:
        """Determine if the line is a header (company or job title)."""
        return "\t" in text or re.search(r"\s{2,}", text)

    def _process_header_line(self, text: str, current_entry: dict) -> dict:
        """Process a header line and update the current entry."""
        if current_entry["company"] is None:
            current_entry["company"] = text.split("\t")[0].strip()
            current_entry["job_title"] = None
            current_entry["bullets"] = []
        else:
            current_entry["job_title"] = text.split("\t")[0].strip()
            current_entry["bullets"] = []
        return current_entry

    def _add_bullet_to_entry(self, text: str, current_entry: dict) -> None:
        """Add a bullet point to the current entry."""
        current_entry["bullets"].append(text)

    def _call_openai_to_rewrite_bullets(self, experience_bullets: List[dict], job_title: str,
                                        job_description: str, optimized_skills: Optional[List[str]] = None,
                                        guided_keywords: Optional[List[str]] = None) -> List[dict]:
        """Call OpenAI API to rewrite experience bullets."""
        self.last_bullet_rewrite_error = None
        try:
            system_message = self._generate_system_message()
            user_message = self._generate_user_message(
                experience_bullets, job_title, job_description,
                optimized_skills or [], guided_keywords or [],
            )

            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ]
            )

            return self._parse_openai_response(response, experience_bullets)

        except Exception as e:
            self.last_bullet_rewrite_error = str(e)
            print(f"❌ Error calling OpenAI API to rewrite bullets: {e}")
            return experience_bullets

    def _generate_system_message(self) -> str:
        """Generate the system message for the OpenAI API request."""
        return (
            "You are an ATS resume optimization expert and professional career writer. "
            "You are given a list of professional experience entries, where each entry contains:\n"
            "- the job title\n"
            "- the company name\n"
            "- a list of bullet points describing the work.\n\n"
            "Your task is to rewrite each bullet point **specifically for a target job title and description**, "
            "while making sure the rewritten content still logically fits the role and domain of the original company and job title.\n\n"
            "Use keywords, technologies, and phrasing relevant to the target job description wherever appropriate, "
            "without introducing false or irrelevant information. If a bullet is about a different domain, find the closest possible conceptual match "
            "to bridge relevance. Optimize each bullet to align better with the responsibilities and qualifications expected in the target job.\n\n"
            "The selected ATS skills and JD-guided phrases are provided as context. Use them only when supported by the source bullet and candidate experience. "
            "The target Trek Health entry may be excluded because it is replaced separately by verified bullets from a curated bank.\n\n"
            "Bullet Rewriting Guidelines:\n"
            "1. **Use either of these styles:**\n"
            "   - [A] Action + Project + Result\n"
            "     → Example: 'Optimized backend APIs for a fintech product, reducing latency by 30% and improving customer satisfaction scores.'\n"
            "   - [B] Accomplished [X] as measured by [Y] by doing [Z]\n"
            "     → Example: 'Increased automation coverage by 40% by designing and deploying scalable AI workflows.'\n\n"
            "2. **Do NOT exceed the original bullet's character count**.\n"
            "3. Preserve the source bullet length and density; shorter source bullets stay shorter.\n"
            "4. Ensure each bullet reflects **individual contributions**, not team achievements.\n"
            "5. Use **concise, powerful, and ATS-friendly phrasing**.\n"
            "6. Keep the job title as the one in the orignal bullets and do not update it to the new job title.\n"
            "7. Strongly align with the **job title and job description**.\n\n"
            "Return only a valid JSON object in this format:\n"
            "{ \"rewritten_experience\": [ { \"job_title\": \"...\", \"company\": \"...\", \"bullets\": [\"...\", \"...\"] }, ... ] }"
        )

    def _generate_user_message(self, experience_bullets: List[dict], job_title: str,
                               job_description: str, optimized_skills: Optional[List[str]] = None,
                               guided_keywords: Optional[List[str]] = None) -> str:
        """Generate the user message for the OpenAI API request."""
        return (
            f"Here is the job title: {job_title}\n\n"
            f"Here is the job description:\n{job_description}\n\n"
            f"Here are the selected ATS skills for this application:\n{json.dumps(optimized_skills or [])}\n\n"
            f"Here are the JD keywords and bank-guided phrases to use when factually supported:\n{json.dumps(guided_keywords or [])}\n\n"
            f"Here are the experience entries to rewrite:\n{json.dumps(experience_bullets, indent=2)}"
        )

    def _parse_openai_response(self, response, fallback: List[dict]) -> List[dict]:
        """Accept matching entry identities and one valid replacement per source bullet."""
        try:
            content = response.choices[0].message.content.strip()
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content).strip()
            result = json.loads(content)
            entries = result.get("rewritten_experience") if isinstance(result, dict) else None
            if not isinstance(entries, list) or len(entries) != len(fallback):
                raise ValueError("Rewrite response must contain exactly the source entries.")
            lookup = {}
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("company"), str) or not isinstance(entry.get("job_title"), str):
                    raise ValueError("Rewrite entries require source company and title strings.")
                key = (entry["company"], entry["job_title"])
                if key in lookup:
                    raise ValueError("Duplicate entries in rewrite response.")
                lookup[key] = entry.get("bullets")
            rewritten = []
            for source in fallback:
                bullets = lookup.get((source["company"], source["job_title"]))
                if not isinstance(bullets, list) or len(bullets) != len(source["bullets"]):
                    raise ValueError("Rewrite response changed an entry identity or bullet count.")
                if not all(isinstance(bullet, str) and bullet.strip() and len(bullet.strip()) <= len(original)
                           for bullet, original in zip(bullets, source["bullets"])):
                    raise ValueError("Rewritten bullets must be nonempty strings within their source length.")
                rewritten.append(dict(source, bullets=[bullet.strip() for bullet in bullets]))
            return rewritten
        except (ValueError, AttributeError, IndexError, TypeError) as exc:
            self.last_bullet_rewrite_error = str(exc)
            print(f"❌ Invalid OpenAI rewrite response; retaining source bullets: {exc}")
            return fallback

    def _update_document_with_rewritten_bullets(self, doc: Document, original_bullets: List[dict], rewritten_bullets: List[dict]) -> None:
        """Rewrite only parsed professional bullet paragraphs, preserving source formatting."""
        original_lookup = self._create_bullet_lookup(original_bullets)
        rewritten_lookup = self._create_bullet_lookup(rewritten_bullets)
        for entry, paragraphs in self._experience_blocks(doc):
            key = (entry["company"], entry["job_title"])
            if key not in original_lookup or key not in rewritten_lookup:
                continue
            for paragraph, text in zip(paragraphs, rewritten_lookup[key]):
                if isinstance(text, str) and text.strip():
                    self._replace_paragraph_text(paragraph, text)

    def _create_bullet_lookup(self, bullets: List[dict]) -> dict:
        """Create a lookup dictionary for bullets."""
        return {
            (entry['company'], entry['job_title']): entry['bullets']
            for entry in bullets
        }

    def _is_company_line(self, text: str) -> bool:
        """Check if the line represents a company."""
        return re.fullmatch(r"[A-Z0-9\s&/'’*()\-]+", text.split("\t")[0]) and (
            "\t" in text or re.search(r"\s{2,}", text)
        )

    def _extract_company_name(self, text: str) -> str:
        """Extract the company name from the text."""
        return text.split("\t")[0].strip()

    def _is_job_title_line(self, text: str) -> bool:
        """Check if the line represents a job title."""
        return "\t" in text or re.search(r"\s{2,}", text)

    def _extract_job_title(self, text: str) -> str:
        """Extract the job title from the text."""
        return text.split("\t")[0].strip()

    def _update_bullet_point(
        self, para, bullet_lookup, rewritten_lookup, current_company, current_job_title, bullet_index
    ) -> None:
        """Update a single bullet point in the document."""
        old_bullets = bullet_lookup[(current_company, current_job_title)]
        new_bullets = rewritten_lookup[(current_company, current_job_title)]

        if bullet_index < len(old_bullets) and bullet_index < len(new_bullets):
            self._replace_paragraph_text(para, new_bullets[bullet_index])

    def _has_updated_all_bullets(self, bullet_index: int, rewritten_lookup: dict, current_company: str, current_job_title: str) -> bool:
        """Check if all bullets for the current entry have been updated."""
        return bullet_index >= len(rewritten_lookup[(current_company, current_job_title)])

    def _reset_state(self) -> Tuple[None, None, bool, int]:
        """Reset the state variables."""
        return None, None, False, 0

    def _document_format_signature(self, path: str) -> Dict[str, object]:
        """Capture source section headings, margins and effective body font sizes."""
        doc = Document(path)
        sections = [{
            key: round(getattr(section, key + "_margin").inches, 3)
            for key in ("top", "bottom", "left", "right")
        } for section in doc.sections]
        headings = [paragraph.text.strip().upper() for paragraph in doc.paragraphs
                    if self._is_resume_section(paragraph)]
        sizes = []
        for paragraph in doc.paragraphs:
            if self._is_resume_section(paragraph) or paragraph.style.name == "Title":
                continue
            for run in paragraph.runs:
                if not run.text.strip():
                    continue
                size = run.font.size
                for style in (run.style, paragraph.style, doc.styles["Normal"]):
                    seen = set()
                    while size is None and style is not None and style.style_id not in seen:
                        seen.add(style.style_id)
                        size = style.font.size
                        style = style.base_style
                if size is not None and size.pt > 0:
                    sizes.append(size.pt)
        return {
            "sections": sections, "headings": headings,
            "body_font_min": min(sizes) if sizes else None,
            "body_font_max": max(sizes) if sizes else None,
            "body_font_typical": Counter(sizes).most_common(1)[0][0] if sizes else None,
            "paragraph_count": len(doc.paragraphs),
            "bullet_count": sum(paragraph.style.name == "List Paragraph" for paragraph in doc.paragraphs),
        }

    def _rendered_layout(self, path: str, headings: List[str], docx_path: str = "") -> Dict[str, object]:
        """Inspect text bounds, rendered headings and bullet wrapping without image heuristics."""
        pages, heading_pages, orphans, wrapping = [], {}, [], []
        normalize = lambda text: re.sub(r"\s+", " ", text).strip().upper()
        with pdfplumber.open(path) as pdf:
            horizontal, vertical = True, True
            for page_number, page in enumerate(pdf.pages):
                words = page.extract_words() or []
                lines = []
                for word in words:
                    horizontal &= float(word["x0"]) >= -0.5 and float(word["x1"]) <= float(page.width) + 0.5
                    vertical &= float(word["top"]) >= -0.5 and float(word["bottom"]) <= float(page.height) + 0.5
                    if not lines or abs(float(word["top"]) - lines[-1]["top"]) > 3:
                        lines.append({"top": float(word["top"]), "bottom": float(word["bottom"]), "text": word["text"]})
                    else:
                        lines[-1]["text"] += " " + word["text"]
                        lines[-1]["bottom"] = max(lines[-1]["bottom"], float(word["bottom"]))
                # Character bounds catch text fragments that the word extractor omits.
                for character in page.chars:
                    if not character.get("text", "").strip():
                        continue
                    horizontal &= float(character["x0"]) >= -0.5 and float(character["x1"]) <= float(page.width) + 0.5
                    vertical &= float(character["top"]) >= -0.5 and float(character["bottom"]) <= float(page.height) + 0.5
                text = normalize(page.extract_text() or "")
                pages.append({"text": text, "lines": lines})
                for heading in headings:
                    heading_text = normalize(heading)
                    for line_index, line in enumerate(lines):
                        if normalize(line["text"]) == heading_text:
                            heading_pages.setdefault(heading, []).append(page_number + 1)
                            if line_index == len(lines) - 1:
                                orphans.append(heading)
        if docx_path and Path(docx_path).exists():
            for paragraph in Document(docx_path).paragraphs:
                if paragraph.style.name != "List Paragraph" or not paragraph.text.strip():
                    continue
                bullet = normalize(paragraph.text)
                matches = []
                for page_number, page in enumerate(pages):
                    if bullet not in page["text"]:
                        continue
                    # Count lines intersecting this bullet in the normalized page text.
                    joined = normalize(" ".join(line["text"] for line in page["lines"]))
                    position = joined.find(bullet)
                    if position < 0:
                        continue
                    offset, line_count = 0, 0
                    for line in page["lines"]:
                        line_text = normalize(line["text"])
                        if offset < position + len(bullet) and offset + len(line_text) > position:
                            line_count += 1
                        offset += len(line_text) + 1
                    matches.append({"page": page_number + 1, "lines": line_count})
                wrapping.append({"text": paragraph.text, "matches": matches})
        return {"page_count": len(pages), "all_pages_have_text": bool(pages) and all(page["text"] for page in pages),
                "no_horizontal_clipping": bool(pages) and horizontal,
                "no_vertical_clipping": bool(pages) and vertical,
                "heading_pages": heading_pages, "orphaned_headings": orphans,
                "bullet_wrapping": wrapping, "text": " ".join(page["text"] for page in pages),
                "max_bullet_lines": max((match["lines"] for bullet in wrapping for match in bullet["matches"]), default=0)}

    def verify_format(self, source_docx: str, optimized_docx: str, source_pdf: str,
                      optimized_pdf: str, expected_pages: int = DEFAULT_EXPECTED_PAGE_COUNT) -> Dict[str, object]:
        """Reject measurable layout regressions; wrapping diagnostics still need visual review."""
        checks, warnings, details = {}, [], {}
        try:
            source = self._document_format_signature(source_docx) if source_docx and Path(source_docx).exists() else {}
            optimized = self._document_format_signature(optimized_docx) if optimized_docx and Path(optimized_docx).exists() else {}
            headings = source.get("headings", [])
            layout = self._rendered_layout(optimized_pdf, headings, optimized_docx)
            source_layout = self._rendered_layout(source_pdf, headings, source_docx) if source_pdf and Path(source_pdf).exists() else {}
            checks.update({name: layout[name] for name in ("all_pages_have_text", "no_horizontal_clipping", "no_vertical_clipping")})
            checks.update({
                "page_count": layout["page_count"] == expected_pages,
                "page_count_value": layout["page_count"], "expected_page_count": expected_pages,
                "source_page_count": source_layout.get("page_count"),
                "no_empty_rendered_pages": layout["all_pages_have_text"],
                "bullets_fit_page": layout["no_horizontal_clipping"] and layout["no_vertical_clipping"],
                "section_order_preserved": not source or headings == optimized.get("headings", []),
                "section_count_stable": not source or len(headings) == len(optimized.get("headings", [])),
                "bullet_count_stable": not source or abs(source["bullet_count"] - optimized.get("bullet_count", 0)) <= 2,
            })
            source_sections, optimized_sections = source.get("sections", []), optimized.get("sections", [])
            checks["margins_similar"] = not source or (
                len(source_sections) == len(optimized_sections) and all(
                    abs(left[key] - right[key]) <= 0.1
                    for left, right in zip(source_sections, optimized_sections) for key in left
                )
            )
            checks["font_sizes_similar"] = not source or all(
                source.get(key) is None and optimized.get(key) is None or
                source.get(key) is not None and optimized.get(key) is not None and abs(source[key] - optimized[key]) <= 1.5
                for key in ("body_font_min", "body_font_max", "body_font_typical")
            )
            # Compare source-rendered headings only, avoiding false failures on unusual source typography.
            rendered_source_headings = source_layout.get("heading_pages", {})
            tokens = lambda text: re.findall(r"[^\W_]+", unicodedata.normalize("NFKC", text).casefold())
            rendered_tokens = tokens(layout["text"])
            rendered_phrase = " ".join(rendered_tokens)
            required_headings = optimized.get("headings", []) if optimized else rendered_source_headings
            checks["rendered_headings_present"] = all(
                " ".join(tokens(heading)) in rendered_phrase for heading in required_headings
            )
            cursor, rendered_order_ok = 0, True
            for heading in required_headings:
                phrase = " ".join(tokens(heading))
                position = rendered_phrase.find(phrase, cursor)
                if position < 0:
                    rendered_order_ok = False
                    break
                cursor = position + len(phrase)
            checks["rendered_section_order_preserved"] = rendered_order_ok
            checks["docx_pdf_content_consistent"] = True
            if optimized_docx and Path(optimized_docx).exists():
                document_text = " ".join(paragraph.text for paragraph in Document(optimized_docx).paragraphs)
                document_counts, rendered_counts = Counter(tokens(document_text)), Counter(rendered_tokens)
                matched = sum((document_counts & rendered_counts).values())
                expected = sum(document_counts.values())
                coverage = matched / expected if expected else 0
                checks["docx_pdf_content_consistent"] = coverage >= 0.95
                details["docx_pdf_token_coverage"] = round(coverage, 4)
            checks["no_new_orphaned_headings"] = not (set(layout["orphaned_headings"]) - set(source_layout.get("orphaned_headings", [])))
            details.update({"source_layout": source_layout, "optimized_layout": layout})
            links = hyperlink_report(source_docx, optimized_docx, source_pdf, optimized_pdf)
            checks["hyperlinks_preserved"] = links["passed"]
            details["hyperlinks"] = links
            if layout["max_bullet_lines"] > source_layout.get("max_bullet_lines", 0) and source_layout:
                warnings.append("Some bullets wrap to more lines than the source; inspect the rendered PDF.")
            if source_layout and source_layout["page_count"] != expected_pages:
                warnings.append(f"Source resume has {source_layout['page_count']} pages; expected {expected_pages}.")
        except Exception as exc:
            checks["verifier_error"] = str(exc)
        required = ("page_count", "all_pages_have_text", "no_horizontal_clipping", "no_vertical_clipping",
                    "bullets_fit_page", "section_order_preserved", "section_count_stable", "bullet_count_stable",
                    "margins_similar", "font_sizes_similar", "no_empty_rendered_pages", "rendered_headings_present",
                    "no_new_orphaned_headings", "docx_pdf_content_consistent", "rendered_section_order_preserved",
                    "hyperlinks_preserved")
        passed = all(checks.get(name, False) for name in required)
        checks["passed"] = passed
        return {"passed": passed, "checks": checks, "warnings": warnings, "details": details}

    def save_optimized_docx(self, doc: Document, optimized_skills: List[str], output_path: str,
                            job_title: str = "job", job_description: str = "",
                            optimization_mode: str = "full", bullet_bank: Optional[Dict[str, object]] = None,
                            bullet_bank_company: str = "Trek Health", max_bank_bullets: int = 7,
                            allow_unverified_bullet_terms: bool = False,
                            guided_keywords: Optional[List[str]] = None,
                            project_bullet_banks: Optional[List[Dict[str, object]]] = None) -> None:
        """Update the skills section in the DOCX and save it."""
        try:
            optimization_mode = optimization_mode if optimization_mode in VALID_OPTIMIZATION_MODES else "full"
            skills_index, end_index = self._find_skills_section(doc)
            if skills_index is None:
                raise ValueError("Skills section not found in DOCX resume")

            self._update_skills_section(doc, skills_index, end_index, optimized_skills)            

            if optimization_mode in {"bullets", "full"}:
                self.rewrite_experience_bullets(
                    doc, job_title, job_description, optimized_skills, bullet_bank,
                    bullet_bank_company, max_bank_bullets, allow_unverified_bullet_terms, guided_keywords,
                    project_bullet_banks,
                )

            if optimization_mode == "full":
                self.replace_job_titles(doc, job_title)

            doc.save(output_path)
            print(f"✅ Successfully saved updated DOCX resume to: {output_path}")

        except Exception as e:
            print(f"❌ Error saving optimized DOCX resume: {e}")
            raise

    def _find_skills_section(self, doc: Document) -> Tuple[int, int]:
        """Find the start and end indices of the skills section."""
        skills_started = False
        skills_heading_only = False
        skills_index = None
        end_index = None

        for i, para in enumerate(doc.paragraphs):
            text = para.text.strip()
            if not skills_started and re.match(r"(?i)^skills\s*:", text):
                skills_started = True
                skills_index = i
                continue
            if not skills_started and text.upper() == "SKILLS":
                skills_started = True
                skills_heading_only = True
                continue
            if skills_started and self._is_resume_section(para):
                end_index = i
                break
            if skills_started and skills_heading_only and skills_index is None and text:
                skills_index = i

        if end_index is None:
            end_index = len(doc.paragraphs)

        return skills_index, end_index

    def _update_skills_section(self, doc: Document, skills_index: int, end_index: int, optimized_skills: List[str]) -> None:
        """Replace text in source paragraphs while retaining their spacing and run properties."""
        paragraphs = doc.paragraphs[skills_index:end_index]
        content_paragraphs = [paragraph for paragraph in paragraphs if paragraph.text.strip()]
        if not content_paragraphs or not optimized_skills:
            raise ValueError("Skills section has no editable content")
        prefix = "Skills: " if re.match(r"(?i)^skills\s*:", content_paragraphs[0].text.strip()) else ""
        # Reuse source line capacities rather than creating unformatted paragraphs.
        pending = list(optimized_skills)
        for index, paragraph in enumerate(content_paragraphs):
            if index == len(content_paragraphs) - 1:
                chosen, pending = pending, []
            else:
                capacity = len(paragraph.text)
                chosen = []
                while pending and (not chosen or len(", ".join(chosen + [pending[0]])) <= capacity):
                    chosen.append(pending.pop(0))
            self._replace_paragraph_text(paragraph, (prefix if index == 0 else "") + ", ".join(chosen))

    # Convert docx to pdf
    def convert_docx_to_pdf(self, docx_path: str, pdf_path: str) -> bool:
        """Convert in an isolated directory and accept only a fresh, readable PDF."""
        self.last_conversion_error = None
        configured = os.getenv("LIBREOFFICE_PATH", "").strip()
        executable = configured or shutil.which("soffice") or shutil.which("libreoffice")
        if not executable and Path("/Applications/LibreOffice.app/Contents/MacOS/soffice").exists():
            executable = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
        if not executable:
            self.last_conversion_error = "LibreOffice was not found; set LIBREOFFICE_PATH or install soffice on PATH."
            print(f"❌ {self.last_conversion_error}")
            return False
        try:
            destination = Path(pdf_path).expanduser().resolve()
            source = Path(docx_path).expanduser().resolve(strict=True)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix="jobrobo-libreoffice-") as temporary:
                work = Path(temporary)
                output = work / "output"
                output.mkdir()
                result = subprocess.run([
                    executable, "--headless", "--nologo", "--nodefault", "--nofirststartwizard",
                    f"-env:UserInstallation={(work / 'profile').as_uri()}",
                    "--convert-to", "pdf:writer_pdf_Export", str(source), "--outdir", str(output),
                ], check=True, capture_output=True, text=True, timeout=60)
                generated = output / (source.stem + ".pdf")
                if not generated.is_file() or generated.stat().st_size == 0:
                    raise ValueError("LibreOffice did not create a PDF. " + (result.stderr or result.stdout).strip())
                if not PdfReader(str(generated)).pages:
                    raise ValueError("LibreOffice created a PDF with no pages.")
                shutil.move(str(generated), str(destination))
            print(f"✅ Successfully converted DOCX to PDF: {destination}")
            return True
        except Exception as exc:
            self.last_conversion_error = str(exc)
            print(f"❌ Error converting DOCX to PDF: {exc}")
            return False


# Function to run the resume optimization process given job description and resume path similar to main()
def run_resume_optimization(job_description: str, resume_path: str, job_id: str,
                            job_title: str = "job", first_name: str = "first", last_name: str = "last",
                            optimization_mode: Optional[str] = None) -> Optional[str]:
    """Generate, verify and report one resume; return a PDF only after acceptance."""
    source_path = Path(resume_path).expanduser()
    runtime_config = load_runtime_config()
    configured_mode = runtime_config.get("optimization_mode") or (
        "full" if runtime_config.get("replace_job_title") and runtime_config.get("rewrite_bullets")
        else "bullets" if runtime_config.get("rewrite_bullets") else "skills"
    )
    requested_mode = optimization_mode if optimization_mode is not None else configured_mode
    mode = requested_mode if requested_mode in VALID_OPTIMIZATION_MODES else "full"
    if mode != requested_mode:
        print(f"⚠️ Unknown optimization mode '{requested_mode}'. Using full mode.")
    sanitize = lambda value: re.sub(r'[^a-zA-Z0-9_.-]+', '_', str(value).lower()).strip("._") or "resume"
    filename = "_".join(sanitize(value) for value in (first_name, last_name, job_title, job_id))
    output_pdf = source_path.parent.parent / "temp" / (filename + ".pdf")
    output_docx = output_pdf.with_suffix(".docx") if source_path.suffix.lower() == ".docx" else None
    source_docx = str(source_path) if output_docx else ""
    source_pdf = str(source_path.with_suffix(".pdf")) if output_docx else str(source_path)
    report_path = output_pdf.with_suffix(".match_report.json")
    report = {
        "job_id": str(job_id), "job_title": job_title, "requested_mode": requested_mode,
        "normalized_mode": mode, "effective_mode": mode, "status": "failed", "error": None,
        "attempts": [], "keywords": [], "selected_bullet_bank_ids": [],
        "project_bullet_bank_selections": {}, "format_verification": {"passed": False, "checks": {}, "warnings": []},
        "output_path": str(output_pdf),
    }
    optimizer = None
    keywords, source_text, optimized_text = [], "", ""
    bank = {}

    def selected_ids():
        return {
            "selected_bullet_bank_ids": [item.get("id") for item in getattr(optimizer, "last_bullet_bank_selection", [])],
            "project_bullet_bank_selections": {
                company: [item.get("id") for item in items]
                for company, items in getattr(optimizer, "last_bullet_bank_selections", {}).items()
            },
        }

    def read_pdf_text(path):
        with pdfplumber.open(str(path)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)

    def attempt_docx(attempt_mode, docx_path, pdf_path, skills, project_banks=None, legacy_bank=None):
        attempt = {"mode": attempt_mode, "docx_path": str(docx_path), "output_path": str(pdf_path),
                   "conversion_succeeded": False, "format_verification": None,
                   "selected_bullet_bank_ids": [], "project_bullet_bank_selections": {}, "error": None}
        report["attempts"].append(attempt)
        # Remove previous artifacts before generation so swallowed saves cannot accept stale output.
        for artifact in (docx_path, pdf_path, pdf_path.with_suffix(".match_report.json")):
            artifact.unlink(missing_ok=True)
        try:
            optimizer.last_bullet_bank_selection = []
            optimizer.last_bullet_bank_selections = {}
            doc, _ = optimizer.read_docx_resume(str(source_path))
            if doc is None:
                raise ValueError("Source DOCX could not be read.")
            optimizer.save_optimized_docx(
                doc, skills, str(docx_path), job_title, job_description, attempt_mode,
                legacy_bank, report.get("bullet_bank_company", "Trek Health"),
                int(runtime_config.get("max_bank_bullets", 7) or 7),
                bool(runtime_config.get("allow_unverified_bullet_terms", False)), keywords, project_banks,
            )
            attempt.update(selected_ids())
            if not docx_path.is_file():
                raise ValueError("Optimized DOCX was not created.")
            if not optimizer.convert_docx_to_pdf(str(docx_path), str(pdf_path)):
                raise ValueError(getattr(optimizer, "last_conversion_error", None) or "Optimized resume could not be converted to PDF.")
            if not pdf_path.is_file():
                raise ValueError("Converter did not create the requested PDF.")
            attempt["conversion_succeeded"] = True
            text = read_pdf_text(pdf_path)
            attempt["format_verification"] = optimizer.verify_format(
                source_docx, str(docx_path), source_pdf, str(pdf_path),
                int(runtime_config.get("expected_page_count", DEFAULT_EXPECTED_PAGE_COUNT)),
            )
            return attempt, text
        except Exception as exc:
            attempt["error"] = str(exc)
            return attempt, ""

    try:
        output_pdf.parent.mkdir(parents=True, exist_ok=True)
        report_path.unlink(missing_ok=True)
        if not source_path.is_file():
            raise ValueError("Resume file not found.")
        if source_path.suffix.lower() not in {".docx", ".pdf"}:
            raise ValueError("Unsupported file format. Please use PDF or DOCX.")
        # Load .env locally only; importing this module never triggers a cloud request.
        load_dotenv()
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("Please set the OPENAI_API_KEY environment variable.")
        bank = load_skill_bank(runtime_config.get("skill_bank_path") or None)
        project_banks = load_project_bullet_banks(runtime_config.get("project_bullet_banks"))
        legacy_bank = load_bullet_bank(runtime_config.get("bullet_bank_path") or None)
        profile = infer_role_profile(job_title, job_description, bank.get("profiles", {}), runtime_config.get("role_profile", "auto"))
        report.update({
            "role_profile": profile, "skill_bank": bank.get("path"), "bullet_bank": legacy_bank.get("path"),
            "bullet_bank_company": runtime_config.get("bullet_bank_company", legacy_bank.get("company", "Trek Health")),
            "project_bullet_banks": [{key: spec.get(key) for key in ("company", "path", "min_bullets", "max_bullets")} for spec in project_banks],
        })
        optimizer = ResumeOptimizer(api_key)
        extracted_keywords = optimizer.extract_keywords(job_description)
        if output_docx:
            doc, current_skills = optimizer.read_docx_resume(str(source_path))
            if doc is None or not current_skills:
                raise ValueError("Source DOCX has no readable Skills section.")
            source_text = "\n".join(paragraph.text for paragraph in doc.paragraphs)
        else:
            source_text, current_skills, format_info = optimizer.read_pdf_resume(str(source_path))
            if not source_text or not current_skills:
                raise ValueError("Source PDF has no readable Skills section.")
            source_text = read_pdf_text(source_path)
        keywords = build_guided_keywords(job_description, extracted_keywords, job_title, current_skills, bank, profile,
                                         bool(runtime_config.get("allow_unverified_bank_terms", True)))
        report["keywords"] = keywords
        report["unverified_terms"] = [keyword for keyword in keywords if any(
            row.get("normalized") == normalize_keyword(keyword) and "†" in row.get("status", "")
            for row in bank.get("keywords", []) if isinstance(row, dict)
        )]
        skills = optimizer.optimize_skills(current_skills, keywords, job_description, int(runtime_config.get("max_skills", 50) or 50))
        if output_docx:
            attempt, optimized_text = attempt_docx(mode, output_docx, output_pdf, skills, project_banks, legacy_bank)
            report.update({key: attempt[key] for key in ("selected_bullet_bank_ids", "project_bullet_bank_selections")})
            verification = attempt["format_verification"]
            if attempt["error"]:
                raise ValueError(attempt["error"])
            report["format_verification"] = verification
            if not verification["passed"] and mode != "skills":
                print("⚠️ Format verification failed; retrying with Skills-only output.")
                fallback_docx = output_docx.with_name(output_docx.stem + "_layout_safe.docx")
                fallback_pdf = output_pdf.with_name(output_pdf.stem + "_layout_safe.pdf")
                fallback, fallback_text = attempt_docx("skills", fallback_docx, fallback_pdf, skills, [])
                if fallback["format_verification"] and fallback["format_verification"]["passed"]:
                    output_pdf, output_docx, optimized_text = fallback_pdf, fallback_docx, fallback_text
                    verification = fallback["format_verification"]
                    report.update({"effective_mode": "skills-fallback", "format_verification": verification,
                                   "selected_bullet_bank_ids": [], "project_bullet_bank_selections": {}})
                    report_path = output_pdf.with_suffix(".match_report.json")
                elif fallback["error"]:
                    report["error"] = "Skills-only retry failed: " + fallback["error"]
        else:
            report["effective_mode"] = "skills-pdf"
            output_pdf.unlink(missing_ok=True)
            optimizer.save_optimized_pdf(str(source_path), skills, format_info, str(output_pdf))
            if not output_pdf.is_file():
                raise ValueError("Optimized PDF was not created.")
            optimized_text = read_pdf_text(output_pdf)
            verification = optimizer.verify_format("", "", source_pdf, str(output_pdf),
                                                   int(runtime_config.get("expected_page_count", DEFAULT_EXPECTED_PAGE_COUNT)))
            report["format_verification"] = verification
            report["attempts"].append({"mode": "skills-pdf", "output_path": str(output_pdf), "format_verification": verification})
        report["output_path"] = str(output_pdf)
        report["status"] = "accepted" if verification["passed"] else "rejected"
    except Exception as exc:
        report["error"] = str(exc)
        print(f"❌ Resume optimization failed: {exc}")
    finally:
        report["api_warnings"] = [error for error in (
            getattr(optimizer, "last_keyword_error", None), getattr(optimizer, "last_bullet_rewrite_error", None)
        ) if error]
        report["pre_optimization"] = calculate_keyword_score(source_text, keywords, bank)
        report["post_optimization"] = calculate_keyword_score(optimized_text, keywords, bank)
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        except OSError as exc:
            print(f"❌ Could not save optimization report: {exc}")
            return None
    if report["status"] != "accepted":
        print(f"❌ Resume rejected or failed. See: {report_path}")
        return None
    print(f"🎯 Format-verified resume: {output_pdf}; report: {report_path}")
    return str(output_pdf)


# Function to load configuration variables
def load_config() -> dict:
    """Load configuration variables from a JSON file."""
    config_path = Path(__file__).parent.parent.parent / "config" / "resume_optimizer_defaults.json"
    try:
        with open(config_path, "r") as config_file:
            config = json.load(config_file)
            return {
                "replace_job_title": config.get("replace_job_title", False),
                "rewrite_bullets": config.get("rewrite_bullets", False),
                "optimization_mode": config.get("optimization_mode", "full"),
                "skill_bank_path": config.get("skill_bank_path", str(DEFAULT_SKILL_BANK_PATH)),
                "bullet_bank_path": config.get("bullet_bank_path", str(DEFAULT_BULLET_BANK_PATH)),
                "bullet_bank_company": config.get("bullet_bank_company", "Trek Health"),
                "max_bank_bullets": config.get("max_bank_bullets", 7),
                "allow_unverified_bullet_terms": config.get("allow_unverified_bullet_terms", False),
                "project_bullet_banks": config.get("project_bullet_banks", DEFAULT_PROJECT_BULLET_BANKS),
                "role_profile": config.get("role_profile", "auto"),
                "allow_unverified_bank_terms": config.get("allow_unverified_bank_terms", True),
                "max_skills": config.get("max_skills", 50),
                "expected_page_count": config.get("expected_page_count", DEFAULT_EXPECTED_PAGE_COUNT),
                "resume_path": config.get("resume_path", ""),
                "job_id": config.get("job_id", ""),
                "first_name": config.get("first_name", "first"),
                "last_name": config.get("last_name", "last"),
                "job_title": config.get("job_title", "job"),
                "job_description": config.get("job_description", ""),
            }
    except FileNotFoundError:
        print(f"❌ Config file not found at {config_path}. Using default values.")
        return {
            "replace_job_title": False,
            "rewrite_bullets": False,
            "optimization_mode": "full",
            "skill_bank_path": str(DEFAULT_SKILL_BANK_PATH),
            "bullet_bank_path": str(DEFAULT_BULLET_BANK_PATH),
            "bullet_bank_company": "Trek Health",
            "max_bank_bullets": 7,
            "allow_unverified_bullet_terms": False,
            "project_bullet_banks": DEFAULT_PROJECT_BULLET_BANKS,
            "role_profile": "auto",
            "allow_unverified_bank_terms": True,
            "max_skills": 50,
            "expected_page_count": DEFAULT_EXPECTED_PAGE_COUNT,
            "resume_path": "",
            "job_id": "",
            "first_name": "first",
            "last_name": "last",
            "job_title": "job",
            "job_description": "",
        }
    except json.JSONDecodeError:
        print(f"❌ Error decoding JSON config file at {config_path}. Using default values.")
        return {
            "replace_job_title": False,
            "rewrite_bullets": False,
            "optimization_mode": "full",
            "skill_bank_path": str(DEFAULT_SKILL_BANK_PATH),
            "bullet_bank_path": str(DEFAULT_BULLET_BANK_PATH),
            "bullet_bank_company": "Trek Health",
            "max_bank_bullets": 7,
            "allow_unverified_bullet_terms": False,
            "project_bullet_banks": DEFAULT_PROJECT_BULLET_BANKS,
            "role_profile": "auto",
            "allow_unverified_bank_terms": True,
            "max_skills": 50,
            "expected_page_count": DEFAULT_EXPECTED_PAGE_COUNT,
            "resume_path": "",
            "job_id": "",
            "first_name": "first",
            "last_name": "last",
            "job_title": "job",
            "job_description": "",
        }

if __name__ == "__main__":
    load_dotenv()
    if not os.getenv("OPENAI_API_KEY"):
        load_openai_key()
    config = load_runtime_config()
    run_resume_optimization(
        config.get("job_description", ""), config.get("resume_path", ""), config.get("job_id", ""),
        config.get("job_title", "job"), config.get("first_name", "first"), config.get("last_name", "last"),
    )

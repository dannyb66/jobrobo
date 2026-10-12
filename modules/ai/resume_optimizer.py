import os
import json
import re
import shutil
import tempfile
from typing import Dict, List, Optional, Tuple
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
from docx.shared import Pt
from dotenv import load_dotenv
from modules.config_loader import load_runtime_config, save_runtime_config
from modules.ai.openai_key_loader import load_openai_key
# from config.settings import replace_job_title, rewrite_bullets


VALID_OPTIMIZATION_MODES = {"skills", "bullets", "full"}
DEFAULT_SKILL_BANK_PATH = Path(__file__).resolve().parents[2] / "config" / "skills" / "Skills_Keyword_Bank_Staff_Principal_2026-10.md"
DEFAULT_EXPECTED_PAGE_COUNT = 2


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
    bank_path = Path(path).expanduser() if path else DEFAULT_SKILL_BANK_PATH
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

class ResumeOptimizer:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)

    def extract_keywords(self, job_description: str) -> List[str]:
        """Extract top 15 keywords from job description using OpenAI API."""
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
            return result.get('keywords', [])

        except Exception as e:
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
                    skills_lines = []

                    for i, line in enumerate(lines):
                        if not skills_started and re.match(r"(?i)^skills\s*:", line.strip()):
                            skills_started = True
                            skills_lines.append(line)
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
        """Replace the least relevant skills while preserving order and document density."""
        target = {normalize_keyword(keyword) for keyword in new_keywords}
        current_by_key = {normalize_keyword(skill): skill for skill in current_skills}
        keep = []
        additions = []

        for skill in current_skills:
            key = normalize_keyword(skill)
            if key in target:
                keep.append(skill)

        for keyword in new_keywords:
            key = normalize_keyword(keyword)
            if key and key not in current_by_key and key not in {normalize_keyword(item) for item in additions}:
                additions.append(keyword)

        # Preserve the original number of entries so keyword improvements do not expand the layout.
        slots = max(0, len(current_skills) - len(keep))
        optimized_skills = keep + additions[:slots]
        if len(optimized_skills) < len(current_skills):
            optimized_skills.extend(skill for skill in current_skills if skill not in optimized_skills)
        if max_count and max_count > 0:
            optimized_skills = optimized_skills[:max_count]

        # Order the optimized skills with the best order for ATS systems optimized for the job description using OpenAI API
        # try:
        #     response = self.client.chat.completions.create(
        #     model="gpt-4o",
        #     messages=[
        #         {
        #         "role": "system",
        #         "content": (
        #             "You are an ATS optimization expert. Given a list of skills and a job description, "
        #             "reorder the skills to maximize relevance and impact for ATS systems. Make sure to always include all the skills from the original list. "
        #             "Return the reordered skills as a JSON object in this format without the json code block:\n"
        #             '{"ordered_skills": ["skill1", "skill2", ..., "skillN"]}'
        #         )
        #         },
        #         {
        #         "role": "user",
        #         "content": (
        #             f"Here is the job description:\n{job_description}\n\n"
        #             f"Here is the list of skills to reorder:\n{optimized_skills}"
        #         )
        #         }
        #     ]
        #     )

        #     content = response.choices[0].message.content.strip()
        #     print(f"\n🔍 Raw GPT response:\n{content}\n")
        #     # Try parsing the response
        #     try:
        #         result = json.loads(content)
        #         ordered_skills = result.get('ordered_skills', optimized_skills)
        #         if ordered_skills and isinstance(ordered_skills, list):
        #             optimized_skills = ordered_skills
        #     except json.JSONDecodeError:
        #         print("❌ Error parsing OpenAI response for skill ordering. Using original order.")

        # except Exception as e:
        #     print(f"❌ Error reordering skills using OpenAI API: {e}")
        
        return optimized_skills[:len(current_skills)]
    
    def save_optimized_pdf(self, resume_path: str, optimized_skills: List[str], format_info: dict, output_path: str):
        try:
            # Step 1: Use pdfplumber to extract structured text
            with pdfplumber.open(resume_path) as pdf:
                full_text_lines = []
                skills_section_found = False
                skills_started = False

                for page in pdf.pages:
                    page_lines = page.extract_text().splitlines()
                    i = 0
                    while i < len(page_lines):
                        line = page_lines[i]
                        if not skills_started and re.match(r"(?i)^skills\s*:", line.strip()):
                            skills_started = True
                            skills_section_found = True

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
                    story.append(Paragraph(line.strip(), styles["Normal"]))

            doc.build(story)

            # Step 3: Save to disk
            with open(output_path, 'wb') as f:
                f.write(buffer.getvalue())

            print(f"✅ Successfully saved updated PDF to: {output_path}")

        except Exception as e:
            print(f"❌ Error saving optimized PDF resume: {e}")

    def read_docx_resume(self, resume_path: str) -> Tuple[Document, List[str]]:
        """Read a DOCX resume and extract the skills section."""
        try:
            doc = Document(resume_path)
            skills_text = ""
            skills_started = False
            skills_lines = []

            for para in doc.paragraphs:
                text = para.text.strip()
                if not skills_started and re.match(r"(?i)^skills\s*:", text):
                    skills_started = True
                    skills_lines.append(text)
                    continue
                if skills_started:
                    if re.match(r"^[A-Z\s]{5,}$", text):
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
                if text.upper() == "PROFESSIONAL EXPERIENCE":
                    is_in_experience_section = True
                    continue
                elif text.upper() in ["EDUCATION", "ENTREPRENEURIAL VENTURES", "ACADEMIC PROJECTS", "CERTIFICATIONS", "SKILLS"]:
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
                        para.text = safe_new_title + "\t" + rest_of_line.lstrip()
                        run = para.runs[0]
                        run.italic = True
                        run.font.size = Pt(9)

        except Exception as e:
            print(f"❌ Error replacing job titles: {e}")

    # Rewrite experience bullets to match job description
    def rewrite_experience_bullets(self, doc: Document, job_title: str, job_description: str, optimized_skills: List[str]) -> None:
        """Rewrite experience bullets to match job description using OpenAI API."""
        try:
            experience_bullets = self._extract_experience_bullets(doc)
            print(f"🔍 Extracted experience bullets: {experience_bullets}")
            if not experience_bullets:
                raise ValueError("No experience bullets found in the resume.")

            rewritten_experience = self._call_openai_to_rewrite_bullets(
                experience_bullets, job_title, job_description
            )
            print(f"🔍 Rewritten experience bullets: {rewritten_experience}")

            if rewritten_experience:
                self._update_document_with_rewritten_bullets(doc, experience_bullets, rewritten_experience)

        except Exception as e:
            print(f"❌ Error rewriting experience bullets: {e}")

    def _extract_experience_bullets(self, doc: Document) -> List[dict]:
        """Extract experience bullets from the document."""
        experience_bullets = []
        current_entry = self._initialize_experience_entry()
        is_in_experience_section = False
        header_line_stage = 0  # 0 = expecting company, 1 = expecting title, 2 = collecting bullets

        # print("\n📄 Starting experience bullet extraction...")

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            # print(f"\n🔎 Analyzing line: '{text}'")

            if self._is_section_header(text, "PROFESSIONAL EXPERIENCE"):
                # print("📌 Entered PROFESSIONAL EXPERIENCE section.")
                is_in_experience_section = True
                header_line_stage = 0
                continue
            elif self._is_section_header(text, ["EDUCATION", "ENTREPRENEURIAL VENTURES", "ACADEMIC PROJECTS", "CERTIFICATIONS", "SKILLS"]):
                # if is_in_experience_section:
                #     print("📤 Exiting PROFESSIONAL EXPERIENCE section.")
                is_in_experience_section = False
                self._finalize_experience_entry(current_entry, experience_bullets)
                current_entry = self._initialize_experience_entry()
                continue

            if is_in_experience_section:
                if self._is_header_line(text):
                    # print(f"🧾 Detected header line: '{text}'")
                    if header_line_stage == 0:
                        self._finalize_experience_entry(current_entry, experience_bullets)
                        current_entry = self._initialize_experience_entry()
                        current_entry["company"] = text.split("\t")[0].strip()
                        header_line_stage = 1
                    elif header_line_stage == 1:
                        current_entry["job_title"] = text.split("\t")[0].strip()
                        header_line_stage = 2
                    elif header_line_stage == 2:
                        # New workex block started – reset everything
                        # print("🔁 Starting new work experience entry.")
                        self._finalize_experience_entry(current_entry, experience_bullets)
                        current_entry = self._initialize_experience_entry()
                        current_entry["company"] = text.split("\t")[0].strip()
                        header_line_stage = 1  # Expect job title next
                else:
                    if header_line_stage == 2:
                        # print(f"➕ Adding bullet: '{text}'")
                        self._add_bullet_to_entry(text, current_entry)
                    else:
                        print(f"⚠️ Skipping unexpected line: '{text}'")

        # print("\n🧹 Finalizing last experience entry if any.")
        self._finalize_experience_entry(current_entry, experience_bullets)

        # print(f"\n✅ Extracted {len(experience_bullets)} experience entries.")
        for idx, entry in enumerate(experience_bullets):
            print(f"  {idx+1}. Company: {entry['company']}, Title: {entry['job_title']}, Bullets: {len(entry['bullets'])}")

        return experience_bullets

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

    def _call_openai_to_rewrite_bullets(self, experience_bullets: List[dict], job_title: str, job_description: str) -> List[dict]:
        """Call OpenAI API to rewrite experience bullets."""
        try:
            system_message = self._generate_system_message()
            user_message = self._generate_user_message(experience_bullets, job_title, job_description)

            response = self.client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": user_message}
                ]
            )

            return self._parse_openai_response(response, experience_bullets)

        except Exception as e:
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
            "Bullet Rewriting Guidelines:\n"
            "1. **Use either of these styles:**\n"
            "   - [A] Action + Project + Result\n"
            "     → Example: 'Optimized backend APIs for a fintech product, reducing latency by 30% and improving customer satisfaction scores.'\n"
            "   - [B] Accomplished [X] as measured by [Y] by doing [Z]\n"
            "     → Example: 'Increased automation coverage by 40% by designing and deploying scalable AI workflows.'\n\n"
            "2. **Do NOT exceed the original bullet's character count**.\n"
            "3. **Use a minimum of 120 characters per bullet.**\n"
            "4. Ensure each bullet reflects **individual contributions**, not team achievements.\n"
            "5. Use **concise, powerful, and ATS-friendly phrasing**.\n"
            "6. Keep the job title as the one in the orignal bullets and do not update it to the new job title.\n"
            "7. Strongly align with the **job title and job description**.\n\n"
            "Return only a valid JSON object in this format:\n"
            "{ \"rewritten_experience\": [ { \"job_title\": \"...\", \"company\": \"...\", \"bullets\": [\"...\", \"...\"] }, ... ] }"
        )

    def _generate_user_message(self, experience_bullets: List[dict], job_title: str, job_description: str) -> str:
        """Generate the user message for the OpenAI API request."""
        return (
            f"Here is the job title: {job_title}\n\n"
            f"Here is the job description:\n{job_description}\n\n"
            f"Here are the experience entries to rewrite:\n{json.dumps(experience_bullets, indent=2)}"
        )

    def _parse_openai_response(self, response, fallback: List[dict]) -> List[dict]:
        """Parse the OpenAI API response and extract rewritten experience bullets."""
        try:
            content = response.choices[0].message.content.strip()

            # Remove JSON code block markers if present
            if content.startswith("```json") and content.endswith("```"):
                content = content[7:-3].strip()

            # Parse the response
            result = json.loads(content)
            return result.get('rewritten_experience', fallback)

        except (json.JSONDecodeError, AttributeError) as e:
            print(f"❌ Error parsing OpenAI API response: {e}")
            return fallback
        
    def _update_document_with_rewritten_bullets(self, doc: Document, original_bullets: List[dict], rewritten_bullets: List[dict]) -> None:
        """Update the document with rewritten bullets."""
        bullet_lookup = self._create_bullet_lookup(original_bullets)
        rewritten_lookup = self._create_bullet_lookup(rewritten_bullets)

        current_company = None
        current_job_title = None
        is_in_target_entry = False
        bullet_index = 0

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue

            if self._is_company_line(text):
                current_company = self._extract_company_name(text)
                current_job_title = None
                is_in_target_entry = False
                bullet_index = 0

            elif current_company and self._is_job_title_line(text):
                current_job_title = self._extract_job_title(text)
                bullet_key = (current_company, current_job_title)
                is_in_target_entry = bullet_key in bullet_lookup and bullet_key in rewritten_lookup
                bullet_index = 0

            elif is_in_target_entry:
                self._update_bullet_point(
                    para, bullet_lookup, rewritten_lookup, current_company, current_job_title, bullet_index
                )
                bullet_index += 1

                if self._has_updated_all_bullets(bullet_index, rewritten_lookup, current_company, current_job_title):
                    current_company, current_job_title, is_in_target_entry, bullet_index = self._reset_state()

            elif current_company and current_job_title and not is_in_target_entry:
                current_company, current_job_title, is_in_target_entry, bullet_index = self._reset_state()

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
            para.text = new_bullets[bullet_index]
            for run in para.runs:
                run.font.size = Pt(9.5)

    def _has_updated_all_bullets(self, bullet_index: int, rewritten_lookup: dict, current_company: str, current_job_title: str) -> bool:
        """Check if all bullets for the current entry have been updated."""
        return bullet_index >= len(rewritten_lookup[(current_company, current_job_title)])

    def _reset_state(self) -> Tuple[None, None, bool, int]:
        """Reset the state variables."""
        return None, None, False, 0

    def _document_format_signature(self, path: str) -> Dict[str, object]:
        """Capture stable layout characteristics from a DOCX for source comparison."""
        doc = Document(path)
        sections = []
        for section in doc.sections:
            sections.append({
                "top": round(section.top_margin.inches, 2),
                "bottom": round(section.bottom_margin.inches, 2),
                "left": round(section.left_margin.inches, 2),
                "right": round(section.right_margin.inches, 2),
            })
        headings = [
            para.text.strip().upper()
            for para in doc.paragraphs
            if para.text.strip() and (para.style.name.startswith("Heading") or re.fullmatch(r"[A-Z][A-Z\s&/&-]{4,}", para.text.strip()))
        ]
        sizes = [
            run.font.size.pt for para in doc.paragraphs for run in para.runs
            if run.font.size and run.font.size.pt
        ]
        body_sizes = [size for size in sizes if 8 <= size <= 14]
        return {
            "sections": sections,
            "headings": headings,
            "body_font_min": min(body_sizes) if body_sizes else None,
            "body_font_max": max(body_sizes) if body_sizes else None,
            "paragraph_count": len(doc.paragraphs),
            "bullet_count": sum(1 for para in doc.paragraphs if para.style.name == "List Paragraph"),
        }

    def verify_format(self, source_docx: str, optimized_docx: str, source_pdf: str,
                      optimized_pdf: str, expected_pages: int = DEFAULT_EXPECTED_PAGE_COUNT) -> Dict[str, object]:
        """Verify rendered output before it is eligible for LinkedIn upload."""
        checks: Dict[str, object] = {}
        warnings = []
        try:
            optimized_reader = PdfReader(optimized_pdf)
            source_reader = PdfReader(source_pdf) if source_pdf and Path(source_pdf).exists() else None
            page_count = len(optimized_reader.pages)
            checks["page_count"] = page_count == expected_pages
            checks["page_count_value"] = page_count
            checks["expected_page_count"] = expected_pages

            extracted_pages = []
            max_word_right = 0.0
            page_width = 0.0
            with pdfplumber.open(optimized_pdf) as pdf:
                for page in pdf.pages:
                    page_width = max(page_width, float(page.width))
                    page_text = (page.extract_text() or "").strip()
                    extracted_pages.append(bool(page_text))
                    for word in page.extract_words() or []:
                        max_word_right = max(max_word_right, float(word.get("x1", 0)))
            checks["all_pages_have_text"] = bool(extracted_pages) and all(extracted_pages)
            if max_word_right:
                checks["no_horizontal_clipping"] = max_word_right <= page_width - 3
            else:
                checks["no_horizontal_clipping"] = False
            checks["bullets_fit_page"] = checks["no_horizontal_clipping"]

            source_signature = self._document_format_signature(source_docx) if source_docx and Path(source_docx).exists() else {}
            optimized_signature = self._document_format_signature(optimized_docx) if optimized_docx and Path(optimized_docx).exists() else {}
            source_headings = source_signature.get("headings", [])
            optimized_headings = optimized_signature.get("headings", [])
            expected_sections = ["EDUCATION", "CERTIFICATIONS", "SKILLS", "PROFESSIONAL EXPERIENCE"]
            source_sections_order = [heading for heading in source_headings if heading in expected_sections]
            optimized_sections_order = [heading for heading in optimized_headings if heading in expected_sections]
            checks["section_order_preserved"] = (
                all(section in optimized_sections_order for section in source_sections_order)
                and optimized_sections_order == sorted(optimized_sections_order, key=expected_sections.index)
            ) if source_signature else True
            checks["section_count_stable"] = abs(
                len(source_headings) - len(optimized_headings)
            ) <= 2 if source_headings else True
            checks["bullet_count_stable"] = abs(
                source_signature.get("bullet_count", 0) - optimized_signature.get("bullet_count", 0)
            ) <= 2 if source_signature else True

            source_sections = source_signature.get("sections", [])
            optimized_sections = optimized_signature.get("sections", [])
            margin_ok = True
            if source_sections and optimized_sections:
                for source_section, optimized_section in zip(source_sections, optimized_sections):
                    margin_ok = margin_ok and all(
                        abs(source_section[key] - optimized_section[key]) <= 0.1
                        for key in ("top", "bottom", "left", "right")
                    )
            checks["margins_similar"] = margin_ok

            source_min = source_signature.get("body_font_min")
            optimized_min = optimized_signature.get("body_font_min")
            checks["font_sizes_similar"] = (
                not source_signature or source_min is None or optimized_min is None or abs(source_min - optimized_min) <= 1.5
            )
            checks["no_empty_rendered_pages"] = not any(not page for page in extracted_pages)
            checks["source_page_count"] = len(source_reader.pages) if source_reader else None
            if source_reader and len(source_reader.pages) != expected_pages:
                warnings.append(f"Source resume has {len(source_reader.pages)} pages; expected {expected_pages}.")
        except Exception as exc:
            checks["verifier_error"] = str(exc)
            warnings.append(str(exc))

        required_checks = [
            "page_count", "all_pages_have_text", "no_horizontal_clipping",
            "bullets_fit_page", "section_order_preserved", "section_count_stable", "bullet_count_stable",
            "margins_similar", "font_sizes_similar",
            "no_empty_rendered_pages",
        ]
        checks["passed"] = not warnings and all(checks.get(name, False) for name in required_checks)
        return {"passed": checks["passed"], "checks": checks, "warnings": warnings}

    def save_optimized_docx(self, doc: Document, optimized_skills: List[str], output_path: str,
                            job_title: str = "job", job_description: str = "",
                            optimization_mode: str = "full") -> None:
        """Update the skills section in the DOCX and save it."""
        try:
            optimization_mode = optimization_mode if optimization_mode in VALID_OPTIMIZATION_MODES else "full"
            skills_index, end_index = self._find_skills_section(doc)
            if skills_index is None:
                raise ValueError("Skills section not found in DOCX resume")

            self._update_skills_section(doc, skills_index, end_index, optimized_skills)            

            if optimization_mode in {"bullets", "full"}:
                self.rewrite_experience_bullets(doc, job_title, job_description, optimized_skills)

            if optimization_mode == "full":
                self.replace_job_titles(doc, job_title)

            doc.save(output_path)
            print(f"✅ Successfully saved updated DOCX resume to: {output_path}")

        except Exception as e:
            print(f"❌ Error saving optimized DOCX resume: {e}")

    def _find_skills_section(self, doc: Document) -> Tuple[int, int]:
        """Find the start and end indices of the skills section."""
        skills_started = False
        skills_index = None
        end_index = None

        for i, para in enumerate(doc.paragraphs):
            text = para.text.strip()
            if not skills_started and re.match(r"(?i)^skills\s*:", text):
                skills_started = True
                skills_index = i
                continue
            if skills_started and re.match(r"^[A-Z\s]{5,}$", text):
                end_index = i
                break

        if end_index is None:
            end_index = len(doc.paragraphs)

        return skills_index, end_index

    def _update_skills_section(self, doc: Document, skills_index: int, end_index: int, optimized_skills: List[str]) -> None:
        """Update the skills section in the document."""
        # Remove existing skills content
        for i in range(end_index - 1, skills_index, -1):
            p = doc.paragraphs[i]
            p._element.getparent().remove(p._element)

        # Add optimized skills
        skills_text_wrapped = textwrap.wrap(", ".join(optimized_skills), width=120)
        doc.paragraphs[skills_index].text = skills_text_wrapped[0]

        # Add additional lines for wrapped skills
        insert_after = doc.paragraphs[skills_index]._element
        for line in skills_text_wrapped[1:]:
            new_para = doc.add_paragraph(line)
            new_para.style = doc.paragraphs[skills_index].style
            insert_after.addnext(new_para._element)
            insert_after = new_para._element

    # Convert docx to pdf
    def convert_docx_to_pdf(self, docx_path: str, pdf_path: str) -> bool:
        profile_path = Path(tempfile.mkdtemp(prefix="jobrobo-libreoffice-"))
        try:
            # pypandoc.convert_file(docx_path, 'pdf', outputfile=pdf_path)
            # docx2pdf.convert(docx_path, pdf_path)
            # Use LibreOffice to convert DOCX to PDF
            import subprocess
            libreoffice_path = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
            subprocess.run([
                libreoffice_path,
                '--headless',
                f'-env:UserInstallation={profile_path.as_uri()}',
                '--convert-to', 'pdf',
                docx_path,
                '--outdir', str(Path(pdf_path).parent),
            ], check=True)
            print(f"✅ Successfully converted DOCX to PDF: {pdf_path}")
            return Path(pdf_path).exists()
        except ImportError:
            print("❌ pypandoc module not found. Please install it using 'pip install pypandoc'.")
            return False
        except Exception as e:
            print(f"❌ Error converting DOCX to PDF: {e}")
            return False
        finally:
            shutil.rmtree(profile_path, ignore_errors=True)

# Function to run the resume optimization process given job description and resume path similar to main()
def run_resume_optimization(job_description: str, resume_path: str, job_id: str,
                            job_title: str = "job", first_name: str = "first", last_name: str = "last",
                            optimization_mode: Optional[str] = None) -> Optional[str]:
    # Get OpenAI API key
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("Please set the OPENAI_API_KEY environment variable")
        return

    # Check if resume file exists
    if not Path(resume_path).exists():
        print("Resume file not found!")
        return

    runtime_config = load_runtime_config()
    configured_mode = runtime_config.get("optimization_mode")
    if not configured_mode:
        configured_mode = (
            "full" if runtime_config.get("replace_job_title") and runtime_config.get("rewrite_bullets")
            else "bullets" if runtime_config.get("rewrite_bullets")
            else "skills"
        )
    mode = optimization_mode or configured_mode
    if mode not in VALID_OPTIMIZATION_MODES:
        print(f"⚠️ Unknown optimization mode '{mode}'. Using full mode.")
        mode = "full"
    bank = load_skill_bank(runtime_config.get("skill_bank_path") or None)
    max_skills = int(runtime_config.get("max_skills", 50) or 50)
    profile_name = infer_role_profile(
        job_title,
        job_description,
        bank.get("profiles", {}) if isinstance(bank.get("profiles"), dict) else {},
        runtime_config.get("role_profile", "auto"),
    )
    allow_unverified = bool(runtime_config.get("allow_unverified_bank_terms", True))
    optimizer = ResumeOptimizer(api_key)

    # Existing JD extraction remains primary; the bank adds relevant ATS vocabulary.
    print("\nExtracting keywords from job description...")
    extracted_keywords = optimizer.extract_keywords(job_description)
    print(f"Top keywords identified: {', '.join(extracted_keywords)}")

    ext = Path(resume_path).suffix.lower()
    output_path = None
    output_path_docx = None
    effective_mode = mode
    source_docx = str(Path(resume_path)) if ext == ".docx" else ""
    source_pdf = str(Path(resume_path).with_suffix(".pdf")) if ext == ".docx" else str(Path(resume_path))

    # Process resume based on file type
    print("\nProcessing resume...")
    # Sanitize variables to ensure they don't contain invalid path characters
    sanitized_job_title = re.sub(r'[\/:*?"<>|]', '_', job_title.lower().replace(' ', '_'))
    sanitized_first_name = re.sub(r'[\/:*?"<>|]', '_', first_name.lower())
    sanitized_last_name = re.sub(r'[\/:*?"<>|]', '_', last_name.lower())

    if ext == ".pdf":
        if mode != "skills":
            print("⚠️ PDF input supports Skills-only rewriting; recording the effective mode.")
            effective_mode = "skills-pdf"
        content, current_skills, format_info = optimizer.read_pdf_resume(resume_path)
        if not content or not current_skills:
            return
        keywords = build_guided_keywords(job_description, extracted_keywords, job_title, current_skills, bank, profile_name, allow_unverified)
        optimized_skills = optimizer.optimize_skills(current_skills, keywords, job_description, max_skills)
        output_path = Path(resume_path).parent.parent / "temp" / f"{sanitized_first_name}_{sanitized_last_name}_{sanitized_job_title}_{job_id}.pdf"
        optimizer.save_optimized_pdf(resume_path, optimized_skills, format_info, str(output_path))

    elif ext == ".docx":
        doc, current_skills = optimizer.read_docx_resume(resume_path)
        if not doc or not current_skills:
            return
        keywords = build_guided_keywords(job_description, extracted_keywords, job_title, current_skills, bank, profile_name, allow_unverified)
        optimized_skills = optimizer.optimize_skills(current_skills, keywords, job_description, max_skills)
        output_path_docx = Path(resume_path).parent.parent / "temp" / f"{sanitized_first_name}_{sanitized_last_name}_{sanitized_job_title}_{job_id}.docx"
        output_path_pdf = Path(resume_path).parent.parent / "temp" / f"{sanitized_first_name}_{sanitized_last_name}_{sanitized_job_title}_{job_id}.pdf"
        output_path_docx.parent.mkdir(parents=True, exist_ok=True)
        optimizer.save_optimized_docx(doc, optimized_skills, str(output_path_docx), job_title, job_description, mode)
        if not output_path_docx.exists() or not optimizer.convert_docx_to_pdf(str(output_path_docx), str(output_path_pdf)):
            print("❌ Optimized resume could not be converted to PDF.")
            return
        output_path = output_path_pdf

    else:
        print("❌ Unsupported file format. Please use PDF or DOCX.")
        return

    if not output_path or not Path(output_path).exists():
        print("❌ Optimized resume was not created.")
        return

    if Path(source_pdf).exists():
        with pdfplumber.open(str(source_pdf)) as source_reader:
            source_text = "\n".join(page.extract_text() or "" for page in source_reader.pages)
    elif ext == ".docx":
        source_text = "\n".join(paragraph.text for paragraph in Document(resume_path).paragraphs)
    else:
        source_text = ""

    def read_output_text(path: Path) -> str:
        with pdfplumber.open(str(path)) as output_reader:
            return "\n".join(page.extract_text() or "" for page in output_reader.pages)

    optimized_text = read_output_text(Path(output_path))
    report_path = Path(output_path).with_suffix(".match_report.json")
    verification = optimizer.verify_format(
        source_docx,
        str(output_path_docx) if output_path_docx else "",
        source_pdf,
        str(output_path),
        int(runtime_config.get("expected_page_count", DEFAULT_EXPECTED_PAGE_COUNT)),
    )

    # One constrained fallback keeps the existing JD-selected Skills section but removes
    # layout-risky rewrites when a generated DOCX does not fit the source format.
    if not verification["passed"] and ext == ".docx" and mode != "skills":
        print("⚠️ Format verification failed; retrying with Skills-only layout-safe output.")
        fallback_doc, _ = optimizer.read_docx_resume(resume_path)
        fallback_docx = output_path_docx.with_name(output_path_docx.stem + "_layout_safe.docx")
        fallback_pdf = output_path.with_name(output_path.stem + "_layout_safe.pdf")
        optimizer.save_optimized_docx(fallback_doc, optimized_skills, str(fallback_docx), job_title, job_description, "skills")
        if fallback_docx.exists() and optimizer.convert_docx_to_pdf(str(fallback_docx), str(fallback_pdf)):
            fallback_verification = optimizer.verify_format(source_docx, str(fallback_docx), source_pdf, str(fallback_pdf), int(runtime_config.get("expected_page_count", DEFAULT_EXPECTED_PAGE_COUNT)))
            if fallback_verification["passed"]:
                output_path_docx, output_path, verification, effective_mode = fallback_docx, fallback_pdf, fallback_verification, "skills-fallback"
                optimized_text = read_output_text(Path(output_path))
                report_path = Path(output_path).with_suffix(".match_report.json")

    report = {
        "job_id": str(job_id),
        "job_title": job_title,
        "requested_mode": mode,
        "effective_mode": effective_mode,
        "role_profile": profile_name,
        "skill_bank": bank.get("path"),
        "keywords": keywords,
        "unverified_terms": [
            keyword for keyword in keywords
            if any(
                row.get("normalized") == normalize_keyword(keyword) and "†" in row.get("status", "")
                for row in bank.get("keywords", []) if isinstance(row, dict)
            )
        ],
        "pre_optimization": calculate_keyword_score(source_text, keywords, bank),
        "post_optimization": calculate_keyword_score(optimized_text, keywords, bank),
        "format_verification": verification,
        "output_path": str(output_path),
    }
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if not verification["passed"]:
        print(f"❌ Resume rejected by format verifier. See: {report_path}")
        return

    print(f"\n🎯 Optimized resume saved to: {output_path}")
    print(f"📊 ATS coverage: {report['pre_optimization']['score']} -> {report['post_optimization']['score']}")
    print(f"✅ Format verified; report saved to: {report_path}")
    return str(output_path)

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

# Load configuration variables
# load_dotenv()  # Load environment variables from .env file
load_openai_key()  # Load OpenAI API key from cloud or .env file
# config = load_config()
config = load_runtime_config()
replace_job_title = config["replace_job_title"]
rewrite_bullets = config["rewrite_bullets"]
job_description = config["job_description"]
resume_path = config["resume_path"]
job_id = config["job_id"]
job_title = config["job_title"]
first_name = config["first_name"]
last_name = config["last_name"]

# Main function to run the resume optimization process
if __name__ == "__main__":
    # Run the resume optimization process
    run_resume_optimization(job_description, resume_path, job_id, job_title, first_name, last_name)

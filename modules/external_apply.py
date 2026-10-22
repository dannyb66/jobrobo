"""Reviewed hosted ATS applications. Importing starts no browser or credential services."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
import tempfile
from pathlib import Path
import re
import time
import uuid
from urllib.parse import urlparse


@dataclass(frozen=True)
class ATSIdentity:
    provider: str
    host: str
    board: str
    job_id: str

    @property
    def key(self):
        return (self.provider, self.host, self.board.casefold(), self.job_id)


def identify_ats(url):
    if not isinstance(url, str) or re.search(r"[\x00-\x20]", url):
        return None
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return None
    try:
        if parsed.port not in (None, 443):
            return None
    except ValueError:
        return None
    host = (parsed.hostname or "").casefold()
    parts = [part for part in parsed.path.split("/") if part]
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io", "job-boards.eu.greenhouse.io"}:
        if len(parts) == 3 and parts[1] == "jobs" and parts[2].isdigit() and re.fullmatch(r"[A-Za-z0-9_-]+", parts[0]):
            # Old/new US hosted domains address the same Greenhouse posting.
            return ATSIdentity("greenhouse", "greenhouse_us" if host != "job-boards.eu.greenhouse.io" else host, parts[0], parts[2])
    if host in {"jobs.lever.co", "jobs.eu.lever.co", "jobs.ashbyhq.com"}:
        if len(parts) in (2, 3) and (len(parts) == 2 or parts[2] in {"apply", "application"}) and re.fullmatch(r"[A-Za-z0-9_-]+", parts[0]) and re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", parts[1]):
            return ATSIdentity("ashby" if host == "jobs.ashbyhq.com" else "lever", host, parts[0], parts[1].lower())
    return None


@dataclass
class ExternalApplicationResult:
    status: str
    application_link: str
    provider: str | None = None
    ats_job_id: str | None = None
    reason: str = ""
    resume_name: str | None = None
    resume_sha256: str | None = None
    filled_fields: list = field(default_factory=list)
    manual_questions: list = field(default_factory=list)
    question_metadata: list = field(default_factory=list)
    submitted_at: str | None = None
    submission_disabled: bool = False
    submit_enabled: bool | None = None
    preparation_report: str | None = None
    attempt_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self):
        return asdict(self)


# Known identity fields remain available without question configuration.
FIELD_KEYS = {
    "first_name": "first_name", "last_name": "last_name", "email": "email", "phone": "phone",
    "name": "full_name", "_systemfield_name": "full_name", "_systemfield_email": "email", "urls[LinkedIn]": "linkedin", "urls[Portfolio]": "website", "urls[Website]": "website",
}
LABEL_KEYS = {"first name": "first_name", "last name": "last_name", "full name": "full_name", "email": "email",
              "phone": "phone", "phone number": "phone", "linkedin profile": "linkedin", "linkedin url": "linkedin", "website": "website", "portfolio": "website"}

# Shared by automatic snapshots and retained-tab monitoring. The historical
# `headings` snapshot field carries these targeted confirmation messages too;
# this keeps freshness/baseline checks identical across both submission paths.
CONFIRMATION_SELECTOR = ('h1,h2,[role=status],[role=alert],[aria-live=polite],[aria-live=assertive],'
                         '.ashby-application-form-success-container,.application-confirmation,'
                         '.confirmation,[data-testid=application-success]')

SNAPSHOT_JS = r"""
const visible=e=>Boolean(e.getClientRects().length)&&getComputedStyle(e).visibility!=='hidden';
const labelText=e=>{if(!e)return '';const clone=e.cloneNode(true);clone.querySelectorAll('input,textarea,select,button,script,style').forEach(control=>control.remove());return clone.textContent||'';};
const labelled=e=>(e.getAttribute('aria-labelledby')||'').split(/\s+/).map(id=>labelText(document.getElementById(id))).join(' ').trim();
const label=e=>(e.getAttribute('aria-label')||labelled(e)||[...(e.labels||[])].map(labelText).join(' ')||labelText(e.closest('.application-question,.field')?.querySelector('label,.application-label'))||'').trim();
const groups=new Map(),forms=new Map();
const fields=[...document.querySelectorAll('input,textarea,select')].map(e=>{
 const container=e.closest('fieldset,[role=radiogroup],[role=group],.application-question,.field');
 const choice=['radio','checkbox'].includes(e.type);
 const header=container?[...container.querySelectorAll('legend,.application-label,[data-question-label],label,h3,h4')].find(l=>l.matches('legend,.application-label,[data-question-label],h3,h4')||!l.querySelector('input,select,textarea')&&![...container.querySelectorAll('input')].some(c=>[...(c.labels||[])].includes(l))):null;
 const ownLabel=[...(e.labels||[])].map(l=>labelText(l).trim()).join(' ').trim();
 let reference=labelled(e);if(ownLabel&&reference.endsWith(ownLabel))reference=reference.slice(0,-ownLabel.length).trim();
 let question=choice?(reference||header?.textContent||labelled(container||e)||label(e)).trim():label(e);
 if(container&&!groups.has(container))groups.set(container,'group-'+groups.size);
 if(e.form&&!forms.has(e.form))forms.set(e.form,'form-'+forms.size);
 const controlRequired=e.required||e.getAttribute('aria-required')==='true'||/[*✱]\s*$/.test(label(e));
 const groupRequired=choice&&(container?.getAttribute('aria-required')==='true'||Boolean(header)&&/[*✱]\s*$/.test(question));
 const checkboxGroup=e.type==='checkbox'&&!controlRequired&&Boolean(container)&&Boolean(header)&&(groupRequired||[...container.querySelectorAll('input[type=checkbox]')].filter(c=>c.name===e.name).length>1);
 if(e.type==='checkbox'&&!checkboxGroup)question=ownLabel||label(e);
 return {element:e,tag:e.tagName.toLowerCase(),type:e.type||'',name:e.name||'',id:e.id||'',form_id:e.form?forms.get(e.form):'',label:label(e),question,option_label:ownLabel||e.getAttribute('aria-label')||e.value||label(e),group:(e.type==='radio'||checkboxGroup)&&container?groups.get(container):'',value:e.value||'',native_required:e.required,control_required:controlRequired,group_required:groupRequired,required:controlRequired||groupRequired,visible:visible(e),disabled:e.disabled,readonly:e.readOnly,combobox:e.getAttribute('role')==='combobox',checked:e.checked,multiple:e.multiple||false,valid:e.checkValidity(),max_length:e.maxLength>0?e.maxLength:null,min:e.min||'',max:e.max||'',options:e.options?[...e.options].map(o=>({label:o.text.trim(),value:o.value,selected:o.selected,disabled:o.disabled})):[],files:[...(e.files||[])].map(f=>({name:f.name,size:f.size}))};
});
const buttons=[...document.querySelectorAll('button,input[type=submit]')].filter(e=>visible(e)&&!e.disabled).map(e=>({element:e,text:(e.textContent||e.value||'').trim(),type:e.type||'',id:e.id||''}));
const headings=[...document.querySelectorAll('__JOBROBO_CONFIRMATION_SELECTOR__')].filter(visible).map(e=>e.textContent.trim());
const challenge=[...document.querySelectorAll('iframe[title*=challenge],iframe[title*=Challenge],iframe[src*=hcaptcha],iframe[src*=recaptcha]')].some(e=>visible(e)&&e.getBoundingClientRect().height>100);
return {url:location.href,title:document.title,fields,buttons,headings,challenge};
""".replace('__JOBROBO_CONFIRMATION_SELECTOR__', CONFIRMATION_SELECTOR)


def snapshot(driver):
    return driver.execute_script(SNAPSHOT_JS)


def _label_key(text):
    return re.sub(r"\s+", " ", re.sub(r"[*✱]+", "", text or "")).strip().casefold()


def field_key(item, provider):
    if item.get("type") not in {"text", "email", "tel", "url"} or item.get("readonly"):
        return None
    # Comboboxes include country/location and custom questions; completing them is manual.
    if item.get("combobox"):
        return None
    name = item.get("name") or item.get("id")
    key = FIELD_KEYS.get(name) or LABEL_KEYS.get(_label_key(item.get("label")))
    if key == "full_name" and provider == "greenhouse" and name == "name":
        return None
    return key


def missing_required(fields):
    missing = []
    for item in fields:
        if not item.get("visible") or item.get("disabled") or (not item.get("required") and item.get("valid") is not False) or item.get("type") in {"hidden", "file", "submit", "button"}:
            continue
        if item.get("type") == "radio":
            ready = any(other.get("type") == "radio" and other.get("checked") for other in fields if (other.get("name") == item["name"] and other.get("form_id", "") == item.get("form_id", "") if item.get("name") else other is item))
        elif item.get("type") == "checkbox":
            siblings = [other for other in fields if other.get("group") and other.get("group") == item.get("group") and other.get("type") == "checkbox"]
            ready = any(other.get("checked") for other in siblings) if len(siblings) > 1 and item.get("group_required") is True and item.get("control_required") is False else item.get("checked") is True
        elif item.get("multiple"):
            ready = any(option.get("selected") and option.get("value") for option in item.get("options", []))
        else:
            ready = bool(str(item.get("value", "")).strip())
        if item.get("valid") is False:
            ready = False
        if not ready:
            missing.append(item.get("question") or item.get("label") or item.get("name") or item.get("id") or "Unlabelled required field")
    return list(dict.fromkeys(missing))


SELECT_ANSWER_JS = r"""
const element=arguments[0], labels=arguments[1];
for(const option of element.options)option.selected=labels.includes(option.text.trim())&&!option.disabled;
element.dispatchEvent(new Event('input',{bubbles:true}));
element.dispatchEvent(new Event('change',{bubbles:true}));
return [...element.selectedOptions].map(o=>o.text.trim());
"""


def _current_answer(question):
    controls, kind = question["fields"], question["kind"]
    if kind == "checkbox":
        return bool(controls[0].get("checked"))
    if kind in {"radio", "multiselect"} and controls[0].get("type") in {"radio", "checkbox"}:
        selected = [item.get("option_label") or item.get("label") or str(item.get("value", "")) for item in controls if item.get("checked")]
        return selected if kind == "multiselect" else selected[0] if len(selected) == 1 else ""
    if kind in {"select", "multiselect"}:
        selected = [option["label"] for option in controls[0].get("options", []) if option.get("selected") and option.get("value")]
        return selected if kind == "multiselect" else selected[0] if len(selected) == 1 else ""
    return controls[0].get("value", "")


def _fill_question(driver, question, value):
    controls, kind = question["fields"], question["kind"]
    if kind in {"text", "textarea", "number", "date"}:
        controls[0]["element"].clear()
        controls[0]["element"].send_keys(value)
    elif kind == "checkbox":
        if bool(controls[0].get("checked")) != value:
            controls[0]["element"].click()
    elif kind == "radio" or kind == "multiselect" and controls[0].get("type") == "checkbox":
        desired = value if isinstance(value, list) else [value]
        for item in controls:
            label = item.get("option_label") or item.get("label") or str(item.get("value", ""))
            selected = label in desired
            if bool(item.get("checked")) != selected and (kind != "radio" or selected):
                item["element"].click()
    else:
        observed = driver.execute_script(SELECT_ANSWER_JS, controls[0]["element"], value if isinstance(value, list) else [value])
        if set(observed) != set(value if isinstance(value, list) else [value]):
            raise ValueError("Native selection was not accepted.")


def prepare_questions(driver, fields, provider, resolver):
    """Return ephemeral review values separately from persistable, value-free metadata."""
    from .external_questions import collect_questions
    previews, metadata, manual = [], [], []
    for question in collect_questions(fields):
        if len(question["fields"]) == 1 and not question.get("repeated_label") and not question.get("ambiguous"):
            question["candidate_key"] = field_key(question["fields"][0], provider)
        current = _current_answer(question)
        answer = resolver.resolve(question, provider, allow_ai=current in (None, "", [], False))
        source, value, reason = answer.source, answer.value, answer.reason
        # Preserve operator/browser entries unless an explicit per-question answer overrides them.
        if current not in (None, "", [], False) and answer.source != "question_config":
            source, value, reason = "existing_browser", current, "Review the existing browser answer."
            key = field_key(question["fields"][0], provider) if len(question["fields"]) == 1 else None
            if key and current == resolver.candidate.get(key):
                source, reason = "candidate_config:" + key, ""
        elif answer.resolved:
            try:
                _fill_question(driver, question, value)
            except Exception:
                source, value, reason = "manual", None, "The browser control did not accept the answer; complete it manually."
        status = "prepared" if source != "manual" else "manual_review"
        label = question["label"] or question["name"] or "Unlabelled field"
        previews.append({"question": label, "name": question["name"], "type": question["kind"], "answer": value, "source": source, "status": status, "reason": reason})
        metadata.append({"question": label, "name": question["name"], "type": question["kind"], "source": source, "status": status})
        if source == "manual":
            manual.append(label)
    return previews, metadata, list(dict.fromkeys(manual))


def identity_matches(state, identity, *, official_role_urls=(), company="", title=""):
    current = identify_ats(state.get("url"))
    if current is None or current.key != identity.key:
        return False
    if official_role_urls:
        return any((parent := identify_ats(url)) is not None and parent.key == current.key for url in official_role_urls)
    # Legacy runs require exact company/title evidence, never a loose partial company name.
    normalize = lambda value: re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
    document_title = state.get("title", "")
    if identity.provider == "greenhouse":
        match = re.fullmatch(r"Job Application for (.+) at (.+)", document_title, re.I)
        observed_title, observed_company = match.groups() if match else ("", "")
    elif identity.provider == "ashby":
        observed_title, separator, observed_company = document_title.rpartition(" @ ")
        if not separator:
            return False
    else:
        observed_company, separator, observed_title = document_title.partition(" - ")
        if not separator:
            return False
    return bool(company and title and normalize(company) == normalize(observed_company) and normalize(title) == normalize(observed_title))


def confirmation_identity(url):
    """A shared ATS host alone cannot identify which employer received the application."""
    identity = identify_ats(url)
    if identity is not None:
        return identity
    parsed = urlparse(url or "")
    parts = [part for part in parsed.path.split("/") if part]
    if parts and parts[-1] in {"thanks", "thank-you", "thank_you", "confirmation"}:
        return identify_ats(parsed._replace(path="/" + "/".join(parts[:-1])).geturl())
    return None


def _confirmed(state):
    phrases = r"thank you for applying|successfully applied|application (?:has been |was )?(?:successfully )?(?:submitted|received)|received your application"
    return any(re.search(phrases, text, re.I) for text in state.get("headings", []))


def apply_hosted_application(driver, application_url, applicant, resume_pdf, *, verify_pdf,
                             company="", title="", official_role_urls=(), review=None,
                             on_status=None, timeout=10, sleep=time.sleep, question_config=None,
                             question_context=None, ai_answerer=None, question_config_error="", prepare_only=False):
    """Prepare known fields, review, then submit only with a durable pre-submit checkpoint.

    Unknown fields remain manual. An unconfirmed click is always an uncertain
    submission and never consumes a confirmed-submission budget.
    """
    identity = identify_ats(application_url)
    result = ExternalApplicationResult("handoff", application_url, submission_disabled=prepare_only)
    if identity is None:
        result.reason = "Unsupported employer site; complete the application manually."
        return result
    result.provider, result.ats_job_id = identity.provider, identity.job_id
    clicked = False
    try:
        applicant = {**applicant, **(question_config or {}).get("candidate", {})}
        state = snapshot(driver)
        if not identity_matches(state, identity, official_role_urls=official_role_urls, company=company, title=title):
            result.reason = "Hosted job identity does not match the reviewed role/company."
            return result
        if identity.provider == "lever" and not any(item.get("type") == "file" for item in state["fields"]):
            driver.get(application_url.rstrip("/") + "/apply")
            state = snapshot(driver)
        if not identity_matches(state, identity, official_role_urls=official_role_urls, company=company, title=title):
            result.reason = "Application navigation changed the reviewed job identity."
            return result
        if state.get("challenge"):
            result.reason = "Access challenge requires manual completion; no answers were filled."
            return result
        pdf = Path(resume_pdf).expanduser().resolve()
        if pdf.suffix.lower() != ".pdf" or not pdf.is_file() or not verify_pdf(pdf):
            result.status, result.reason = "failed", "No independently verified PDF resume is available."
            return result
        digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
        resume_fields = [item for item in state["fields"] if item.get("type") == "file" and (item.get("name") == "resume" or item.get("id") in {"resume", "resume-upload-input", "_systemfield_resume"})]
        if len(resume_fields) != 1:
            result.reason = "The hosted resume-upload contract is unsupported or ambiguous."
            return result
        result.resume_name, result.resume_sha256 = pdf.name, digest
        resume_fields[0]["element"].send_keys(str(pdf))
        state = snapshot(driver)
        attached = any(file.get("name") == pdf.name and file.get("size") == pdf.stat().st_size
                       for item in state["fields"] if item.get("type") == "file" and (item.get("name") == "resume" or item.get("id") in {"resume", "resume-upload-input", "_systemfield_resume"}) for file in item.get("files", []))
        if not attached:
            result.status, result.reason = "failed", "The new verified resume attachment could not be confirmed."
            return result
        from .external_questions import QuestionResolver
        resolver = QuestionResolver(question_config, applicant, question_context, ai_answerer)
        previews, result.question_metadata, result.manual_questions = prepare_questions(driver, state["fields"], identity.provider, resolver)
        result.filled_fields = list(dict.fromkeys(item["source"].split(":", 1)[1] if item["source"].startswith("candidate_config:") else item["name"] for item in result.question_metadata if item["status"] == "prepared"))
        if question_config_error:
            result.manual_questions.insert(0, question_config_error)
        result.status, result.reason = "awaiting_review", "Configured answers prepared; review answers/sources and complete unresolved questions."
        if prepare_only:
            prepared_state = snapshot(driver)
            required = missing_required(prepared_state["fields"])
            result.submit_enabled = len([b for b in prepared_state.get('buttons', []) if re.fullmatch(r'submit(?: application)?', b.get('text', ''), re.I)]) == 1
            result.status = "handoff" if required else "prepared"
            result.reason = "Preparation only; submission disabled." + (" Required: " + ", ".join(required) if required else "")
            return result
        if review is None:
            return result
        decision = review({**result.to_dict(), "answer_preview": previews})
        if decision == "Discard application":
            result.status, result.reason = "discarded", "Application discarded during explicit review."
            return result
        if decision != "Submit application":
            return result
        state = snapshot(driver)
        if not identity_matches(state, identity, official_role_urls=official_role_urls, company=company, title=title):
            result.status, result.reason = "failed", "The reviewed job changed before submission."
            return result
        required = missing_required(state["fields"])
        if required or state.get("challenge"):
            result.status, result.reason = "handoff", "Complete required questions or the access challenge manually: " + ", ".join(required)
            return result
        still_attached = any(file.get("name") == pdf.name and file.get("size") == pdf.stat().st_size
                             for item in state["fields"] if item.get("type") == "file" and (item.get("name") == "resume" or item.get("id") in {"resume", "resume-upload-input", "_systemfield_resume"})
                             for file in item.get("files", []))
        if not still_attached or hashlib.sha256(pdf.read_bytes()).hexdigest() != digest or not verify_pdf(pdf):
            result.status, result.reason = "failed", "The verified resume changed before submission."
            return result
        buttons = [item for item in state.get("buttons", []) if re.fullmatch(r"submit(?: application)?", item.get("text", ""), re.I)]
        if len(buttons) != 1 or on_status is None:
            result.reason = "A unique Submit button and durable submission checkpoint are required."
            return result
        result.status, result.reason = "submitting", "Submission requested; verify the employer site if confirmation is interrupted."
        on_status(result)
        clicked = True
        buttons[0]["element"].click()
        prior_confirmations = set(state.get("headings", []))
        deadline = time.monotonic() + timeout
        while True:
            current = snapshot(driver)
            # A confirmation on a different ATS/company host cannot establish this submission.
            current_identity = confirmation_identity(current.get("url"))
            new_confirmation = dict(current, headings=[heading for heading in current.get("headings", []) if heading not in prior_confirmations])
            if current_identity is not None and current_identity.key == identity.key and not current.get("challenge") and _confirmed(new_confirmation):
                result.status, result.reason = "applied", "Employer application submission confirmed."
                result.submitted_at = datetime.now(timezone.utc).isoformat()
                on_status(result)
                return result
            if time.monotonic() >= deadline:
                return result
            sleep(0.1)
    except Exception as exc:
        if result.status != "applied":
            result.status = "submitting" if clicked else "failed"
        result.reason = ("Employer confirmation succeeded but tracking failed. " if result.status == "applied" else "Submission may have occurred; employer confirmation requires inspection. " if clicked else "Hosted application preparation failed. ") + type(exc).__name__
        return result


class ExternalApplicationLedger:
    """Protect a hosted posting globally, even when LinkedIn exposes another ID."""
    def __init__(self, path):
        self.path = Path(path)

    def _read(self):
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text())
        if not isinstance(data, dict):
            raise ValueError("External application ledger must be an object")
        return data

    @staticmethod
    def target_key(url):
        identity = identify_ats(url)
        if identity:
            return "|".join(identity.key)
        from .generic_prepare import canonical_url, fingerprint
        try:
            return 'generic|' + fingerprint(canonical_url(url, allow_local=True))
        except (ValueError, TypeError, AttributeError):
            return None

    def release_unactivated(self, url, attempt_id, *, proof):
        return self.release_aliases([url], attempt_id, proof=proof)

    def reconcile(self, url, attempt_id, *, applied, reason):
        """Record an operator-verified outcome; never contact an employer."""
        from .search_history import file_lock
        from .direct_careers_apply import write_json
        with file_lock(self.path.with_suffix('.lock')):
            data = self._read()
            entry = data.get(self.target_key(url), {})
            aliases = entry.get('posting_aliases') or [url]
            keys = list(dict.fromkeys(self.target_key(u) for u in aliases))
            for key in keys:
                prior = data.get(key, {})
                if prior.get('attempt_id') != attempt_id or prior.get('status') not in {'submitting','applied','not_submitted'}:
                    raise ValueError('Reconciliation requires the original protected attempt')
                if prior.get('status') == 'applied' and not applied:
                    raise ValueError('A confirmed application cannot be released as not submitted')
            at = datetime.now(timezone.utc).isoformat()
            for key in keys:
                data[key].update(status='applied' if applied else 'not_submitted',
                    reconciliation={'source':'operator_verified','reason':reason,'at':at}, updated_at=at)
                if applied:
                    data[key]['submitted_at'] = data[key].get('submitted_at') or at
            write_json(self.path, data)
            return data[self.target_key(url)]

    def record_aliases(self, outcome, urls, source_id):
        """Claim redirect/embedded posting identities together, before any click."""
        from .search_history import file_lock
        from .direct_careers_apply import write_json
        keys = list(dict.fromkeys(self.target_key(url) for url in urls))
        if not keys or None in keys:
            raise ValueError('Invalid posting alias')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self.path.with_suffix('.lock')):
            data = self._read()
            for key in keys:
                prior = data.get(key, {})
                if prior.get('status') in {'applied','submitting','duplicate'} and (
                    prior.get('attempt_id') != outcome.attempt_id or prior.get('status')=='applied' and outcome.status!='applied'):
                    raise RuntimeError('Posting or redirect alias is already protected')
            for key in keys:
                data[key] = dict(outcome.to_dict(), linkedin_id=str(source_id), posting_aliases=list(urls), updated_at=datetime.now(timezone.utc).isoformat())
            write_json(self.path, data)

    def release_aliases(self, urls, attempt_id, *, proof):
        """Only the live owner may release a disarmed, provably unused claim."""
        from .search_history import file_lock
        if proof != {'disarmed': True, 'activated': False}:
            raise ValueError('A live disarmed guard with no activation is required')
        keys = list(dict.fromkeys(self.target_key(url) for url in urls))
        with file_lock(self.path.with_suffix('.lock')):
            data = self._read()
            for key in keys:
                prior = data.get(key, {})
                if prior.get('status') != 'submitting' or prior.get('attempt_id') != attempt_id:
                    raise ValueError('Cannot release another or confirmed submission claim')
            for key in keys:
                del data[key]
            from .direct_careers_apply import write_json
            write_json(self.path, data)

    def protected(self, url):
        key = self.target_key(url)
        return key is not None and self._read().get(key, {}).get("status") in {"applied", "submitting", "duplicate"}

    def record(self, outcome, linkedin_id):
        from modules.search_history import file_lock
        key = self.target_key(outcome.application_link)
        if key is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(self.path.with_suffix(".lock")):
            data = self._read()
            previous = data.get(key, {})
            if outcome.status in {"submitting", "applied"} and previous.get("status") in {"submitting", "applied"}:
                if previous.get("attempt_id") != outcome.attempt_id or previous.get("status") == "applied" and outcome.status == "submitting":
                    raise RuntimeError("Employer posting is already claimed by a protected submission attempt.")
            if previous.get("status") == "applied" and outcome.status != "applied":
                return
            if previous.get("status") == "submitting" and outcome.status not in {"submitting", "applied"}:
                return
            data[key] = dict(outcome.to_dict(), linkedin_id=str(linkedin_id), updated_at=datetime.now(timezone.utc).isoformat())
            descriptor, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".external-applications-")
            try:
                with os.fdopen(descriptor, "w") as handle:
                    json.dump(data, handle, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, self.path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)

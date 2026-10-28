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
    challenge_solved: bool = False
    challenge: dict | None = None
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
APPLICATION_SUCCESS_SELECTOR = '.ashby-application-form-success-container,[data-testid=application-success]'

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
 // A react-select style combobox is an <input role=combobox> with no <option>s:
 // its question is the aria-labelledby target and its choices are role=option
 // nodes, which only exist while the list is open.
 const combo=e.getAttribute('role')==='combobox';
 const comboLabel=combo?(document.getElementById(e.getAttribute('aria-labelledby')||'')?.textContent||'').trim():'';
 // A chosen combobox keeps its text in a value span, not in input.value; read it
 // here so every later snapshot can tell a filled control from an empty one.
 let comboValue='';
 if(combo){let b=e;for(let i=0;i<6&&b&&!comboValue;i++){const t=[...b.querySelectorAll('[class*=single-value],[class*=multi-value__label]')].map(x=>(x.textContent||'').trim()).filter(Boolean);if(t.length)comboValue=t.join(' ');b=b.parentElement;}}
 return {element:e,tag:e.tagName.toLowerCase(),type:e.type||'',name:e.name||'',id:e.id||'',form_id:e.form?forms.get(e.form):'',label:label(e),question:comboLabel||question,option_label:ownLabel||e.getAttribute('aria-label')||e.value||label(e),group:(e.type==='radio'||checkboxGroup)&&container?groups.get(container):'',value:combo?(comboValue||''):(e.value||''),native_required:e.required,control_required:controlRequired,group_required:groupRequired,required:controlRequired||groupRequired||(combo&&e.getAttribute('aria-required')==='true'),visible:visible(e)&&e.getAttribute('aria-hidden')!=='true',disabled:e.disabled,readonly:e.readOnly,combobox:combo,checked:e.checked,multiple:e.multiple||false,valid:e.checkValidity(),max_length:e.maxLength>0?e.maxLength:null,min:e.min||'',max:e.max||'',options:e.options?[...e.options].map(o=>({label:o.text.trim(),value:o.value,selected:o.selected,disabled:o.disabled})):[...(!e.options&&combo&&e.getAttribute('aria-expanded')==='true'?[...document.querySelectorAll('[role=option]')].filter(visible).map(o=>({label:o.textContent.trim(),value:o.textContent.trim(),selected:o.getAttribute('aria-selected')==='true',disabled:o.getAttribute('aria-disabled')==='true'})):[])],files:[...(e.files||[])].map(f=>({name:f.name,size:f.size}))};
});
const buttons=[...document.querySelectorAll('button,input[type=submit]')].filter(e=>visible(e)&&!e.disabled).map(e=>({element:e,text:(e.textContent||e.value||'').trim(),type:e.type||'',id:e.id||''}));
const headings=[...document.querySelectorAll('__JOBROBO_CONFIRMATION_SELECTOR__')].filter(visible).map(e=>e.textContent.trim());
const challenge=[...document.querySelectorAll('iframe[title*=challenge],iframe[title*=Challenge],iframe[src*=hcaptcha],iframe[src*=recaptcha]')].some(e=>visible(e)&&e.getBoundingClientRect().height>100);
const application_success=[...document.querySelectorAll('__JOBROBO_APPLICATION_SUCCESS_SELECTOR__')].filter(visible).map(e=>e.textContent.trim()).filter(Boolean);
const REJECT=/couldn.t submit your application|flagged as possible spam|application was not submitted|try these steps/i;
const rejection=[...document.querySelectorAll('__JOBROBO_CONFIRMATION_SELECTOR__')].filter(visible).map(e=>e.textContent.trim()).filter(t=>REJECT.test(t));
// Sites that replace the file input on upload (Greenhouse) show the name in a card instead.
const attached_files=[...document.querySelectorAll('.file-upload__filename,[class*=uploaded][class*=file]')].filter(visible).map(e=>e.textContent.trim()).filter(Boolean);
return {url:location.href,title:document.title,fields,buttons,headings,challenge,application_success,rejection,attached_files};
""".replace('__JOBROBO_CONFIRMATION_SELECTOR__', CONFIRMATION_SELECTOR).replace('__JOBROBO_APPLICATION_SUCCESS_SELECTOR__', APPLICATION_SUCCESS_SELECTOR)


def snapshot(driver):
    return driver.execute_script(SNAPSHOT_JS)


def _label_key(text):
    return re.sub(r"\s+", " ", re.sub(r"[*✱]+", "", text or "")).strip().casefold()


def field_key(item, provider):
    if item.get("type") not in {"text", "email", "tel", "url"} or item.get("readonly"):
        return None
    # Comboboxes are mapped like selects; their options are read on demand.
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


COMBOBOX_OPEN_JS = r"""
const el=arguments[0];
el.scrollIntoView({block:'center'});
return true;
"""

# The menu is a sibling listbox, not a child of the 1px input, and the chosen
# text lives in a container that is not the input's parent.

COMBOBOX_READ_JS = r"""
return [...document.querySelectorAll('[role=option]')]
  .filter(o=>o.getClientRects().length)
  .map(o=>({label:(o.textContent||'').trim(), selected:o.getAttribute('aria-selected')==='true',
            disabled:o.getAttribute('aria-disabled')==='true'}));
"""

COMBOBOX_PICK_JS = r"""
const want=arguments[1];
const options=[...document.querySelectorAll('[role=option]')].filter(o=>o.getClientRects().length);
const hit=options.find(o=>(o.textContent||'').trim()===want);
if(!hit)return null;
hit.click();
return (hit.textContent||'').trim();
"""

COMBOBOX_VALUE_JS = r"""
const el=arguments[0];
let box=el;
for(let i=0;i<6&&box;i++){
  const found=[...box.querySelectorAll('[class*=single-value],[class*=multi-value__label]')].map(e=>(e.textContent||'').trim());
  if(found.length)return found;
  box=box.parentElement;
}
return null;
"""

COMBOBOX_EXPANDED_JS = r"""
return arguments[0].getAttribute('aria-expanded')==='true';
"""


def _combo_options(driver):
    return driver.execute_script(COMBOBOX_READ_JS) or []


def _open_combobox(driver, element, wait=time.sleep):
    """Open the menu and return its options.

    A JavaScript ``element.click()`` does not open these react-select menus; only
    a WebDriver click does, because the input listens on a real pointer sequence.
    So click for real, confirm ``aria-expanded``, and retry once if the hit test
    was intercepted at the current scroll position.
    """
    for attempt in (1, 2):
        # Put it in the viewport first; an offscreen control's click is
        # intercepted by whatever is actually painted at that point.
        try:
            driver.execute_script(COMBOBOX_OPEN_JS, element)
            wait(0.15)
        except Exception:
            pass
        try:
            element.click()
        except Exception:
            if attempt == 2:
                raise
            driver.execute_script(COMBOBOX_OPEN_JS, element)
            continue
        wait(0.4)
        if driver.execute_script(COMBOBOX_EXPANDED_JS, element):
            return _combo_options(driver)
        if attempt == 2:
            break
        driver.execute_script(COMBOBOX_OPEN_JS, element)
    return _combo_options(driver)


def _read_combobox_options(driver, fields, wait=time.sleep):
    """Open each combobox once to learn its choices, then close it.

    A react-select list only exists in the DOM while open, so the options have
    to be read before the resolver can validate an answer against them.
    """
    for item in fields:
        if not item.get("combobox") or not item.get("visible") or item.get("disabled"):
            continue
        try:
            options = _open_combobox(driver, item["element"], wait)
            item["_combo_open"] = True
            current = driver.execute_script(COMBOBOX_VALUE_JS, item["element"]) or []
            if current:
                item["value"] = current[0] if len(current) == 1 else current
        except Exception:
            continue
        finally:
            # Close again so a later select is not competing with an open menu.
            if item.get("_combo_open"):
                try:
                    driver.execute_script("arguments[0].blur()", item["element"])
                except Exception:
                    pass
        if options:
            item["options"] = [{"label": o["label"], "value": o["label"],
                                "selected": o.get("selected", False), "disabled": o.get("disabled", False)}
                               for o in options if o.get("label")]


def _typing_char_delay():
    """Seconds per character; 0 disables pacing (tests)."""
    try:
        return max(0.0, float(os.getenv("JOBROBO_TYPING_DELAY", "0.03")))
    except ValueError:
        return 0.03


def _dwell_ms():
    """Pause before Submit so the form is not filled and sent in one burst."""
    try:
        return max(0, int(os.getenv("JOBROBO_SUBMIT_DWELL_MS", "1500")))
    except ValueError:
        return 1500


def _type(driver, element, value, wait=time.sleep):
    """Fill a field with per-character timing, like a person typing.

    ``send_keys`` in one call lands the whole string instantly, which is one of
    the cheapest signals that a form was machine-filled.
    """
    import random

    delay = _typing_char_delay()
    text = "" if value is None else str(value)
    if not delay or not text:
        element.send_keys(text)
        return
    # One element handle is reused, so no re-resolution per character.
    for char in text:
        element.send_keys(char)
        wait(delay * (0.6 + 0.8 * random.random()))


def _pick_combobox(driver, element, value, wait=time.sleep):
    """Choose one option by exact label; fall back to a prefix match."""
    from .external_questions import normalize_label

    chosen = value if isinstance(value, str) else str(value)
    options = _open_combobox(driver, element, wait)
    picked = driver.execute_script(COMBOBOX_PICK_JS, element, chosen)
    if picked is None:
        lowered = chosen.casefold()
        prefix = next((o["label"] for o in options if o["label"].casefold().startswith(lowered)), None)
        if prefix:
            picked = driver.execute_script(COMBOBOX_PICK_JS, element, prefix)
    if picked is None:
        raise ValueError("The combobox did not offer that option.")
    wait(0.25)
    observed = driver.execute_script(COMBOBOX_VALUE_JS, element) or []
    # A readback can be split across spans (a country renders flag and dial code
    # separately), so compare as one joined string and also allow a fragment.
    seen = " ".join(observed)
    wanted = normalize_label(picked)
    if wanted and not (wanted in normalize_label(seen)
                       or any(text and normalize_label(text) in wanted for text in observed)):
        raise ValueError("The combobox did not accept the option.")
    return picked


def _fill_question(driver, question, value, wait=time.sleep):
    controls, kind = question["fields"], question["kind"]
    if controls[0].get("combobox"):
        _pick_combobox(driver, controls[0]["element"], value, wait)
        return
    if kind in {"text", "textarea", "number", "date"}:
        controls[0]["element"].clear()
        _type(driver, controls[0]["element"], value, wait)
    elif kind == "checkbox":
        if bool(controls[0].get("checked")) != value:
            _pick(driver, controls[0]["element"])
    elif kind == "radio" or kind == "multiselect" and controls[0].get("type") == "checkbox":
        desired = value if isinstance(value, list) else [value]
        for item in controls:
            label = item.get("option_label") or item.get("label") or str(item.get("value", ""))
            selected = label in desired
            if bool(item.get("checked")) != selected and (kind != "radio" or selected):
                _pick(driver, item["element"])
    else:
        observed = driver.execute_script(SELECT_ANSWER_JS, controls[0]["element"], value if isinstance(value, list) else [value])
        if set(observed) != set(value if isinstance(value, list) else [value]):
            raise ValueError("Native selection was not accepted.")


def prepare_questions(driver, fields, provider, resolver):
    """Return ephemeral review values separately from persistable, value-free metadata."""
    from .external_questions import collect_questions
    _read_combobox_options(driver, fields)
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
    headings = state.get('headings', [])
    # Callers filter pre-existing messages out of headings before checking.
    # Intersect with that fresh list so a stale success container cannot count.
    declared = any(text.strip() and text in headings for text in state.get('application_success', []))
    return declared or any(re.search(phrases, text, re.I) for text in headings)


def _solve_challenge(driver, *, expect_provider=None, result=None, wait_painted_ms=0):
    """Try the solver; record evidence on the result. Never raises."""
    from . import captcha_solver

    def manual(reason="Access challenge requires manual completion; no answers were filled."):
        if result is not None:
            result.reason = reason
        return False

    try:
        if not captcha_solver.enabled():
            return manual()
        ready, why = captcha_solver.available()
        if not ready:
            return manual("Access challenge requires manual completion; solver unavailable: " + why)
        record = captcha_solver.solve(driver, expect_provider=expect_provider,
                                      wait_painted_ms=wait_painted_ms)
    except Exception as exc:
        record = {"status": "error", "detail": type(exc).__name__}
    if result is not None:
        result.challenge = record
    try:
        solved = captcha_solver.cleared(record)
    except Exception:
        solved = False
    if result is not None:
        result.challenge_solved = solved
    return solved


def _provider_hint(provider):
    """ATS names are not solver names; pass only an unambiguous provider."""
    return provider if provider in {"recaptcha", "hcaptcha", "turnstile"} else None


def _click_submit(driver, element):
    """Click Submit, falling back to a DOM click.

    A fully filled Ashby form covers the button with a translucent overlay while
    it settles, so WebDriver reports "element click intercepted" and no widget is
    ever triggered. The fallback dispatches the same click the button's own
    handler listens for. Returns which path was used, or "" if both failed.
    """
    try:
        element.click()
        return "native"
    except Exception:
        try:
            driver.execute_script("arguments[0].click()", element)
            return "script"
        except Exception:
            return ""


def _pick(driver, element):
    """Select a radio/checkbox, falling back to a DOM click.

    Custom-styled ATS choices (Lever draws its own label over a hidden input)
    ignore a native click on the label but accept one on the input itself.
    The native click reports success either way, so the state is read back.
    """
    def state():
        try:
            return bool(driver.execute_script("return arguments[0].checked", element))
        except Exception:
            return None

    before = state()
    try:
        element.click()
    except Exception:
        before = None
    if before is not None:
        after = state()
        if after is not None and after != before:
            return
    try:
        driver.execute_script("arguments[0].click()", element)
    except Exception:
        pass


def _attach_resume(driver, field, pdf):
    """Attach the verified PDF, tolerating a control the site replaces.

    Greenhouse hides the input under a styled "Attach" button and swaps the
    element out while it processes the upload, which makes the handle stale
    before the caller can read the result. Re-resolve by name/id and un-hide it
    so WebDriver will fill a control it otherwise considers invisible.
    """
    def resolve():
        if not hasattr(driver, "find_element"):
            return None
        ident = field.get("id") or field.get("name")
        if ident:
            for by in ("css selector", "xpath"):
                selector = f"#{ident}" if by == "css selector" else f"//*[@id='{ident}']"
                try:
                    return driver.find_element(by, selector)
                except Exception:
                    continue
        return None

    def unhide(element):
        try:
            driver.execute_script(
                "arguments[0].style.cssText="
                "'display:block;visibility:visible;opacity:1;position:static'", element)
        except Exception:
            pass

    element = field["element"]
    try:
        if hasattr(element, "is_displayed") and not element.is_displayed():
            unhide(element)
        element.send_keys(str(pdf))
        return
    except Exception:
        pass
    fresh = resolve()
    if fresh is None:
        raise
    unhide(fresh)
    fresh.send_keys(str(pdf))


def _solver_note(result):
    from . import captcha_solver
    return " Solver: " + captcha_solver.describe(result.challenge) if result.challenge else ""


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
            if not _solve_challenge(driver, expect_provider=_provider_hint(identity.provider), result=result):
                result.reason = "Access challenge requires manual completion; no answers were filled." + _solver_note(result)
                return result
            state = snapshot(driver)
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
        # Greenhouse keeps the real input under a styled "Attach" button as
        # `visually-hidden`; WebDriver will not fill a control it cannot see.
        _attach_resume(driver, resume_fields[0], pdf)
        # The upload is asynchronous on every ATS, and the styled buttons sit
        # over a hidden input, so the file only appears after the site has
        # processed it. Poll rather than sampling once.
        deadline = time.monotonic() + 15
        while True:
            state = snapshot(driver)
            attached = any(file.get("name") == pdf.name and file.get("size") == pdf.stat().st_size
                           for item in state["fields"] if item.get("type") == "file" and (item.get("name") == "resume" or item.get("id") in {"resume", "resume-upload-input", "_systemfield_resume"}) for file in item.get("files", []))
            attached = attached or any(pdf.name in text for text in state.get("attached_files", []))
            if attached or time.monotonic() >= deadline:
                break
            sleep(0.25)
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
        if state.get("challenge"):
            if not _solve_challenge(driver, expect_provider=_provider_hint(identity.provider), result=result):
                result.status = "handoff"
                result.reason = "Complete the access challenge manually." + _solver_note(result)
                required = missing_required(state["fields"])
                if required:
                    result.reason += ". Required: " + ", ".join(required)
                return result
            state = snapshot(driver)
        required = missing_required(state["fields"])
        if required:
            result.status, result.reason = "handoff", "Complete required questions manually: " + ", ".join(required)
            return result
        still_attached = any(file.get("name") == pdf.name and file.get("size") == pdf.stat().st_size
                             for item in state["fields"] if item.get("type") == "file" and (item.get("name") == "resume" or item.get("id") in {"resume", "resume-upload-input", "_systemfield_resume"})
                             for file in item.get("files", []))
        still_attached = still_attached or any(pdf.name in text for text in state.get("attached_files", []))
        if not still_attached or hashlib.sha256(pdf.read_bytes()).hexdigest() != digest or not verify_pdf(pdf):
            result.status, result.reason = "failed", "The verified resume changed before submission."
            return result
        buttons = [item for item in state.get("buttons", []) if re.fullmatch(r"submit(?: application)?", item.get("text", ""), re.I)]
        if len(buttons) != 1 or on_status is None:
            result.reason = "A unique Submit button and durable submission checkpoint are required."
            return result
        result.status, result.reason = "submitting", "Submission requested; verify the employer site if confirmation is interrupted."
        # A form filled and fired in one burst reads as machine-submitted.
        dwell = _dwell_ms()
        if dwell:
            sleep(dwell / 1000.0)
        on_status(result)
        clicked = True
        _click_submit(driver, buttons[0]["element"])
        prior_confirmations = set(state.get("headings", []))
        deadline = time.monotonic() + timeout
        # An invisible reCAPTCHA is idle until Submit runs it: the click, not the
        # form load, is what raises the board. One round covers the normal case;
        # the second absorbs a vendor re-issue after a rejected answer.
        challenge_rounds = 2
        # One re-click when the first submit neither confirmed nor raised a
        # challenge; an intercepted click is common and costs one attempt.
        reclicked = False
        settle_deadline = min(deadline, time.monotonic() + 8)
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
            if current.get("rejection") and not current.get("challenge"):
                # The vendor took the submission and then refused it. That is an
                # employer-side block, not a solver failure, and not a success.
                result.status = "handoff"
                result.reason = ("Submission reached the employer but was rejected: "
                                 + current["rejection"][0][:160].replace("\n", " ")
                                 + _solver_note(result))
                return result
            if current.get("challenge"):
                if challenge_rounds <= 0:
                    result.status, result.reason = "handoff", "Submission raised a further access challenge." + _solver_note(result)
                    return result
                challenge_rounds -= 1
                result.status, result.reason = "submitting", "Submission raised an access challenge; solving it, then submitting again."
                if not _solve_challenge(driver, expect_provider=_provider_hint(identity.provider),
                                        result=result, wait_painted_ms=15000):
                    result.status = "handoff"
                    result.reason = "Submission raised an access challenge that could not be solved." + _solver_note(result)
                    return result
                # The solver hides the widget once clear; give the frame time to go
                # before clicking, or the click lands in the challenge frame.
                gate = time.monotonic() + 5
                while time.monotonic() < gate and snapshot(driver).get("challenge"):
                    sleep(0.1)
                # The form also repaints while the widget collapses, so the
                # button can be briefly absent. Look again before giving up.
                after_solve = snapshot(driver)
                settle = time.monotonic() + 5
                while time.monotonic() < settle and not any(
                        re.fullmatch(r"submit(?: application)?", item.get("text", ""), re.I)
                        for item in after_solve.get("buttons", [])):
                    sleep(0.1)
                    after_solve = snapshot(driver)
                if after_solve.get("rejection") and not after_solve.get("challenge"):
                    result.status = "handoff"
                    result.reason = ("Submission reached the employer but was rejected: "
                                     + after_solve["rejection"][0][:160].replace("\n", " ")
                                     + _solver_note(result))
                    return result
                buttons = [item for item in after_solve.get("buttons", []) if re.fullmatch(r"submit(?: application)?", item.get("text", ""), re.I)]
                if len(buttons) != 1:
                    result.status, result.reason = "handoff", "No unique Submit button after the challenge cleared." + _solver_note(result)
                    return result
                result.status, result.reason = "submitting", "Challenge cleared; submitting again."
                _click_submit(driver, buttons[0]["element"])
            elif not reclicked and time.monotonic() >= settle_deadline:
                reclicked = True
                frame = [item for item in current.get("buttons", []) if re.fullmatch(r"submit(?: application)?", item.get("text", ""), re.I)]
                if len(frame) == 1:
                    _click_submit(driver, frame[0]["element"])
                    settle_deadline = min(deadline, time.monotonic() + 8)
                    # Judge the re-click before the deadline can end the wait,
                    # or a zero-timeout caller never sees its effect.
                    continue
            if time.monotonic() >= deadline:
                return result
            sleep(0.1)
    except Exception as exc:
        import traceback as _tb, os as _os
        if _os.getenv("JOBROBO_DEBUG_EXC"): _tb.print_exc()
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

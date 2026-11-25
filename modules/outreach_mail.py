"""Send the Task 7 faculty drafts through Gmail's web UI.

The mailbox is reached through the dedicated JobRobo Chrome profile, which is
already signed in to Gmail, so nothing secret has to be stored: no OAuth client,
no app password, no vendor account. Gmail's own daily cap still applies.

The private JSON draft ledger is the source of truth. Every run is resumable and
records one append-only JSONL line per draft actually sent; a draft already in a
previous ledger is skipped unless it is named with ``only``.

    --source      draft JSON (default: the Task 7 ledger)
    --from-html   optional import from the exported review HTML
    --dry-run     compose and verify, then discard the draft
    --attach      PDF attached to every message in the run
"""
from __future__ import annotations

import hashlib
import html
import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

DEFAULT_SOURCE = ("/Users/deepakbasavaraju/Library/Application Support/jobrobo/"
                  "work-programme-20261014/phd/faculty90/outreach-drafts-90.json")
COMPOSE_URL = "https://mail.google.com/mail/u/0/"

COMPOSE_BUTTON = 'div[role="button"][gh="cm"], div[role="button"][aria-label="Compose"]'
# Docked compose windows are role=region in current Gmail; pop-outs are role=dialog.
DIALOG = 'div[role="dialog"], div[role="region"]'
TO_FIELD = 'input[aria-label^="To recipients"], textarea[name="to"], input[name="to"]'
SUBJECT_FIELD = 'input[name="subjectbox"]'
BODY_FIELD = 'div[aria-label="Message Body"]'
FILE_INPUT = 'input[type="file"][name="Filedata"], input[type="file"]'
DISCARD_BUTTON = 'div[role="button"][aria-label^="Discard draft"]'
SNACKBAR = '.bAq, div[role="alert"]'
RECIPIENT_CHIP = '[data-hovercard-id], span[email], div[data-name]'
ACCOUNT_BUTTON = 'a[aria-label^="Google Account"]'
ADDRESS_IN_TEXT = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
RESTORE_BUTTON = '[aria-label="Maximise"], [aria-label="Maximize"]'
MAX_LEFTOVER_COMPOSE = 5
UPLOAD_TIMEOUT = 60
UPLOAD_PROGRESS = '[role="progressbar"]'
DEBUG_PORT = 9222
PROFILE_OPEN_WITHOUT_PORT = (
    "The JobRobo Chrome profile is open without a debug port, so the sender cannot attach. "
    "Quit that Chrome window, then run: python3 outreach.py --open-chrome")

EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+\.[^@\s]+$")
CLAIMS_ATTACHMENT = re.compile(r"\battached (?:is )?my (?:research )?(?:resume|cv)\b", re.I)
ATTACHMENT_SENTENCE = re.compile(
    r"I(?: have|'ve)? attached my (?:research )?(?:resume|cv)\.[ \t]*", re.I)
SENT_TIMEOUT = 20
NOTICE_CLEAR_TIMEOUT = 12
RECIPIENT_ATTEMPTS = 3
COMPOSE_ATTEMPTS = 2
RECIPIENT_TIMEOUT = 4
DEFAULT_DELAY = (0.0, 30.0)  # seconds between messages; override with --delay
FILL_TIMEOUT = 15


class PreflightError(RuntimeError):
    """A run cannot start; nothing has been sent or clicked."""


class SendUnconfirmed(RuntimeError):
    """Send was clicked but Gmail never confirmed it; the message may have gone out."""


def _now():
    return datetime.now(timezone.utc)


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-") or "run"


# >>>>>>>>>>>>>>>>>>>>> Draft sources <<<<<<<<<<<<<<<<<<<<

def load_drafts(source):
    """Read the JSON ledger and return its draft records."""
    path = Path(source).expanduser()
    if not path.exists():
        raise PreflightError(f"Draft source not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise PreflightError(f"Draft source is not readable JSON: {path}: {error}") from None
    drafts = payload.get("drafts") if isinstance(payload, dict) else payload
    if not isinstance(drafts, list) or not drafts:
        raise PreflightError(f"Draft source has no drafts list: {path}")
    records = []
    for index, draft in enumerate(drafts, 1):
        if not isinstance(draft, dict):
            raise PreflightError(f"Draft {index} is not an object")
        draft_id = str(draft.get("draft_id") or draft.get("id") or f"draft-{index}")
        if draft.get("cc") or draft.get("bcc"):
            raise PreflightError(f"{draft_id}: cc/bcc are not supported by the Gmail web sender")
        recipient = draft.get("email") or draft.get("to") or ""
        if isinstance(recipient, list):
            if len(recipient) != 1:
                raise PreflightError(f"{draft_id}: exactly one recipient is supported")
            recipient = recipient[0]
        readiness = str(draft.get("readiness") or "")
        records.append({
            "draft_id": draft_id,
            "email": str(recipient).strip(),
            "subject": str(draft.get("subject") or "").strip(),
            "body": str(draft.get("body_plain") or draft.get("body") or ""),
            "faculty": str(draft.get("faculty") or ""),
            "readiness": readiness,
            "hold": bool(draft.get("hold")) or readiness.lower().startswith("hold"),
        })
    return records


def _flatten(fragment):
    text = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    text = re.sub(r"</(?:p|div|li)>\s*", "\n\n", text, flags=re.I)
    text = re.sub(r'<a\b[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
                  lambda m: f"{re.sub(r'<[^>]+>', '', m.group(2))} ({m.group(1)})",
                  text, flags=re.I | re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def drafts_from_copies_html(path):
    """Draft dicts from a review page that embeds ``COPIES`` and ``CSVROWS`` (batch 2 layout).

    ``COPIES`` is exactly what the page's copy button sends ({to, subject, body});
    ``CSVROWS`` adds status, school and name. Any status other than "Ready..." is a hold.
    """
    source = Path(path).expanduser()
    if not source.exists():
        raise PreflightError(f"HTML source not found: {source}")
    document = source.read_text(encoding="utf-8", errors="replace")
    copies = re.search(r"const COPIES=(\{.*?\});", document, re.S)
    table = re.search(r"const CSVROWS=(\[.*?\]\]);", document, re.S)
    if not (copies and table):
        raise PreflightError(f"{source} has no embedded COPIES/CSVROWS data")
    copies = json.loads(copies.group(1))
    rows = json.loads(table.group(1))
    header, rows = rows[0], [dict(zip(rows[0], row)) for row in rows[1:]]
    drafts = []
    for row in rows:
        copy = copies.get(row["id"])
        if copy is None:
            raise PreflightError(f"{row['id']}: in CSVROWS but not in COPIES")
        if copy["to"] != row["email"] or copy["subject"] != row["subject"]:
            raise PreflightError(f"{row['id']}: COPIES and CSVROWS disagree on recipient or subject")
        status = row.get("status") or ""
        ready = status.lower().startswith("ready")
        drafts.append({
            "draft_id": row["id"], "email": copy["to"], "subject": copy["subject"],
            "body_plain": copy["body"], "faculty": row.get("name", ""),
            "school": row.get("school", ""), "dept": row.get("dept", ""),
            "paper": row.get("paper", ""), "paper_url": row.get("paper_url", ""),
            "profile_url": row.get("profile_url", ""),
            "readiness": status if ready else f"Hold — {status}",
            "status": "DRAFT — not sent",
        })
    return drafts


def write_drafts_file(drafts, destination, source):
    """Write drafts in the same JSON shape as the Task 7 ledger; never overwrites."""
    target = Path(destination).expanduser()
    if target.exists():
        raise PreflightError(f"{target} already exists; choose a new path")
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {"metadata": {
        "imported_from": str(Path(source).expanduser().resolve()),
        "imported_utc": _now().isoformat(),
        "draft_count": len(drafts),
        "held": [draft["draft_id"] for draft in drafts if draft["readiness"].startswith("Hold")],
        "status": f"{len(drafts)} drafts imported for review — not sent",
    }, "drafts": drafts}
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def records_from_html(path):
    """Import recipients, subjects and bodies from the review HTML export."""
    source = Path(path).expanduser()
    if not source.exists():
        raise PreflightError(f"HTML source not found: {source}")
    document = source.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r'(?=<details[^>]*data-draft-id=")', document)
    records = []
    for block in blocks[1:]:
        draft_id = re.search(r'data-draft-id="([^"]+)"', block)
        email = re.search(r"<strong>To:</strong>\s*([^\s<·]+)", block)
        subject = re.search(r'class="faculty90-subject">Subject:\s*(.*?)</p>', block, re.S)
        body = re.search(r'class="faculty90-body">(.*?)</div>', block, re.S)
        if not (draft_id and email and subject and body):
            continue
        records.append({
            "draft_id": draft_id.group(1),
            "email": email.group(1).strip(),
            "subject": _flatten(subject.group(1)),
            "body": _flatten(body.group(1)),
            "faculty": "", "readiness": "", "hold": False,
        })
    if not records:
        raise PreflightError(f"No data-draft-id blocks found in {source}")
    return records


def compare_sources(json_records, html_records):
    """Report drafts whose subject or body differs between the two sources."""
    by_id = {record["draft_id"]: record for record in json_records}
    drift = []
    for record in html_records:
        twin = by_id.get(record["draft_id"])
        if twin is None:
            drift.append(f"{record['draft_id']}: absent from JSON")
        elif (twin["subject"] != record["subject"]
              or twin["body"].split() != record["body"].split()):
            drift.append(f"{record['draft_id']}: subject or body differs")
    return drift


# >>>>>>>>>>>>>>>>>>>>> Ledger <<<<<<<<<<<<<<<<<<<<

def read_ledger(logs_root):
    """Every recorded send across all runs, keyed by draft id and recipient."""
    sent = {}
    for ledger in sorted(Path(logs_root).glob("*/sent.jsonl")):
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            key = (record.get("draft_id"), record.get("email"))
            if record.get("void"):
                sent.pop(key, None)  # a later requeue cancels an earlier unverified send
            else:
                sent[key] = record
    return sent


def exclusions_path(logs_root):
    return Path(logs_root) / "excluded.jsonl"


def read_exclusions(logs_root):
    """Draft ids and addresses the user has permanently dropped (lower-cased addresses)."""
    ids, emails = set(), set()
    path = exclusions_path(logs_root)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("draft_id"):
                ids.add(row["draft_id"])
            if row.get("email"):
                emails.add(row["email"].lower())
    return ids, emails


def is_excluded(record, exclusions):
    ids, emails = exclusions
    return record["draft_id"] in ids or record["email"].lower() in emails


def exclude(targets, source, logs_root, reason="dropped by user"):
    """Permanently drop drafts by draft id or recipient address; returns matched draft ids."""
    records = load_drafts(source)
    wanted = {str(target).strip().lower() for target in targets}
    matched = [record for record in records
               if record["draft_id"].lower() in wanted or record["email"].lower() in wanted]
    unknown = wanted - {r["draft_id"].lower() for r in matched} - {r["email"].lower() for r in matched}
    if unknown:
        raise PreflightError(f"No draft matches: {', '.join(sorted(unknown))}")
    for record in matched:
        append_ledger(exclusions_path(logs_root), {
            "draft_id": record["draft_id"], "email": record["email"], "reason": reason,
            "excluded_utc": _now().isoformat()})
    return [record["draft_id"] for record in matched]


def append_ledger(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        handle.flush()


def write_remaining(source, logs_root, destination):
    """Write a copy of the draft file without drafts the ledger records as sent.

    Every other draft is kept unchanged (holds included), metadata is preserved,
    and the source file is never modified. Returns (kept, dropped draft ids).
    """
    source_path = Path(source).expanduser().resolve()
    target = Path(destination).expanduser().resolve()
    if target == source_path:
        raise PreflightError("--write-remaining must not overwrite the source draft file")
    records = load_drafts(source_path)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    raw = payload.get("drafts") if isinstance(payload, dict) else payload
    sent = read_ledger(logs_root)
    exclusions = read_exclusions(logs_root)
    kept, dropped, excluded = [], [], []
    for record, draft in zip(records, raw):
        if is_excluded(record, exclusions):
            excluded.append(record["draft_id"])
        elif (record["draft_id"], record["email"]) in sent:
            dropped.append(record["draft_id"])
        else:
            kept.append(draft)
    if isinstance(payload, dict):
        out = dict(payload, drafts=kept)
        out["metadata"] = dict(payload.get("metadata") or {}, remaining={
            "derived_from": str(source_path),
            "generated_utc": _now().isoformat(),
            "excluded_as_sent": dropped,
            "excluded_by_user": excluded,
            "ledger_root": str(Path(logs_root).resolve()),
        })
    else:
        out = kept
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(target)
    gone = set(dropped) | set(excluded)
    return [record["draft_id"] for record in records if record["draft_id"] not in gone], dropped + excluded


def select(records, *, already_sent=(), limit=25, start=1, only=(), include_held=False,
           exclusions=(set(), set())):
    """Choose this run's drafts and explain every draft left out.

    Held drafts are only sent when named with ``only`` and ``include_held``.
    """
    only = [str(value) for value in only]
    chosen, skipped = [], []
    for index, record in enumerate(records, 1):
        draft_id = record["draft_id"]
        held = record.get("hold")
        if is_excluded(record, exclusions):
            skipped.append((draft_id, "excluded by user"))
            continue
        if only:
            if draft_id in only:
                if held and not include_held:
                    skipped.append((draft_id, "on hold (add --include-held)"))
                else:
                    chosen.append(record)
            continue
        if held:
            skipped.append((draft_id, "on hold"))
        elif index < start:
            skipped.append((draft_id, f"before --start {start}"))
        elif (draft_id, record["email"]) in already_sent:
            skipped.append((draft_id, "already sent"))
        elif len(chosen) >= limit:
            skipped.append((draft_id, f"beyond --limit {limit}"))
        else:
            chosen.append(record)
    if only:
        known = {record["draft_id"] for record in records}
        missing = [draft_id for draft_id in only if draft_id not in known]
        if missing:
            skipped.append((", ".join(missing), "unknown draft id"))
    return chosen, skipped


def validate(records, attach=None, *, sending=False):
    """Pre-send checks that must pass before any browser action.

    When ``sending``, a body that claims an attachment without ``attach`` is an
    error rather than a warning.
    """
    problems, seen, warned = [], set(), []
    for record in records:
        draft_id = record["draft_id"]
        if draft_id in seen:
            problems.append(f"{draft_id}: duplicate draft id")
        seen.add(draft_id)
        if not EMAIL.match(record["email"]):
            problems.append(f"{draft_id}: invalid recipient {record['email']!r}")
        if not record["subject"]:
            problems.append(f"{draft_id}: empty subject")
        if not record["body"].strip():
            problems.append(f"{draft_id}: empty body")
        if not attach and CLAIMS_ATTACHMENT.search(record["body"]):
            message = f"{draft_id}: body claims an attachment; no --attach given"
            (problems if sending else warned).append(message)
    if attach:
        path = Path(attach).expanduser()
        if not path.is_file():
            problems.append(f"--attach file not found: {path}")
        elif path.suffix.lower() != ".pdf":
            problems.append(f"--attach is not a PDF: {path}")
        else:
            attach = str(path.resolve())
    if problems:
        shown = problems[:5]
        if len(problems) > 5:
            shown.append(f"...and {len(problems) - 5} more")
        hint = ""
        if any("claims an attachment" in problem for problem in problems):
            hint = ("\nAdd --attach PDF to send the CV, or --no-attach to send without it "
                    "(removes the 'I have attached my research resume.' sentence).")
        raise PreflightError("Draft validation failed:\n  " + "\n  ".join(shown) + hint)
    return attach, warned


def without_attachment_claim(records):
    """Copies of the drafts with the 'I have attached my research resume.' sentence removed."""
    return [dict(record, body=ATTACHMENT_SENTENCE.sub("", record["body"])) for record in records]


# >>>>>>>>>>>>>>>>>>>>> Browser <<<<<<<<<<<<<<<<<<<<

def profile_path():
    from config import settings
    return Path(settings.chrome_profile_path).expanduser()


def _port_open(port):
    import socket
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", int(port))) == 0


def chrome_processes(profile, listing=None):
    """Debug ports of running Chrome main processes using ``profile`` (None = no port flag)."""
    if listing is None:
        import subprocess
        try:
            listing = subprocess.run(["ps", "-axww", "-o", "command="], capture_output=True,
                                     text=True, timeout=5).stdout
        except (OSError, subprocess.SubprocessError):
            return []
    flag = f"--user-data-dir={Path(profile).expanduser()}"
    ports = []
    for line in listing.splitlines():
        if flag not in line or "--type=" in line or "Google Chrome" not in line:
            continue
        match = re.search(r"--remote-debugging-port=(\d+)", line)
        ports.append(int(match.group(1)) if match and match.group(1) != "0" else None)
    return ports


def live_debugger_address(profile, listing=None):
    """Address of a Chrome already running on this profile with a debug port, else None."""
    candidates = [port for port in chrome_processes(profile, listing) if port]
    try:
        marker = (Path(profile) / "DevToolsActivePort").read_text(encoding="utf-8").split()[0]
        candidates.append(int(marker))
    except (OSError, IndexError, ValueError):
        pass
    for port in candidates:
        if _port_open(port):
            return f"127.0.0.1:{port}"
    return None


def open_chrome_window(profile, port=DEBUG_PORT, url=COMPOSE_URL, runner=None):
    """Start normal Chrome (real keychain) on the profile with a local debug port.

    Returns (address, started). Logins made in this window are stored the same way
    the sender's fallback launch reads them.
    """
    import subprocess
    address = live_debugger_address(profile)
    if address:
        return address, False
    if chrome_processes(profile):
        raise PreflightError(PROFILE_OPEN_WITHOUT_PORT)
    if _port_open(port):
        from modules.open_chrome import _free_port
        port = _free_port()
    (runner or subprocess.run)(
        ["open", "-na", "Google Chrome", "--args", f"--user-data-dir={profile}",
         f"--remote-debugging-port={port}", "--remote-debugging-address=127.0.0.1", url],
        check=True)
    deadline = time.time() + 20
    while time.time() < deadline:
        if _port_open(port):
            return f"127.0.0.1:{port}", True
        time.sleep(0.5)
    raise PreflightError(f"Chrome did not open debug port {port} within 20s")


def launch_options(profile, port):
    """ChromeDriver options that keep the real macOS keychain.

    ChromeDriver adds --use-mock-keychain by default; Chrome then cannot decrypt
    cookies saved by normal Chrome and discards the Gmail/LinkedIn login.
    """
    from selenium import webdriver
    options = webdriver.ChromeOptions()
    options.add_argument(f"--user-data-dir={profile}")
    options.add_argument(f"--remote-debugging-port={port}")
    options.add_argument("--remote-debugging-address=127.0.0.1")
    options.add_experimental_option("excludeSwitches", ["use-mock-keychain", "enable-automation"])
    options.add_experimental_option("detach", True)
    return options


def open_browser(profile, *, attach_existing=True):
    """Attach to the running profile; launch only when no Chrome owns it."""
    from selenium import webdriver
    from selenium.webdriver.support.ui import WebDriverWait
    from modules.open_chrome import _free_port

    address = live_debugger_address(profile) if attach_existing else None
    if address:
        options = webdriver.ChromeOptions()
        options.debugger_address = address
        driver = webdriver.Chrome(options=options)
        return driver, WebDriverWait(driver, FILL_TIMEOUT), address, False
    if chrome_processes(profile):
        raise PreflightError(PROFILE_OPEN_WITHOUT_PORT)
    Path(profile).mkdir(parents=True, exist_ok=True)
    driver = webdriver.Chrome(options=launch_options(profile, _free_port()))
    return driver, WebDriverWait(driver, FILL_TIMEOUT), None, True


def frame_for(driver):
    """The Gmail page: the current tab, else the first non-extension tab."""
    driver.switch_to.default_content()
    handles = driver.window_handles
    for handle in [driver.current_window_handle, *handles]:
        try:
            driver.switch_to.window(handle)
            if "mail.google.com" in driver.current_url:
                return
        except Exception:
            continue
    driver.switch_to.window(handles[0])


def compose_dialog(driver):
    """The newest open compose window, or None."""
    windows = compose_windows(driver)
    return windows[-1] if windows else None


def dismiss_alert(driver):
    """Close a stray browser alert (e.g. Gmail's leave-page warning); stay on the page."""
    try:
        alert = driver.switch_to.alert
        text = alert.text
        alert.dismiss()
        return text
    except Exception:
        return None


def _shown(element, selector):
    try:
        return any(item.is_displayed() for item in element.find_elements("css selector", selector))
    except Exception:
        return False


OUTERMOST_WINDOWS_JS = """
const [container, subject] = arguments;
return [...document.querySelectorAll(container)].filter(element => {
  if (!element.querySelector(subject)) return false;
  const outer = element.parentElement && element.parentElement.closest(container);
  return !(outer && outer.querySelector(subject));
});
"""


def compose_windows(driver):
    """Every open compose window, minimised or not, as its outermost container.

    A window is a role=dialog wrapper holding a role=region; the Maximise and
    Discard controls can sit on the wrapper, so the inner region is not enough.
    """
    try:
        found = driver.execute_script(OUTERMOST_WINDOWS_JS, DIALOG, SUBJECT_FIELD)
        if isinstance(found, list):
            return found
    except Exception:
        pass
    found = []
    for element in driver.find_elements("css selector", DIALOG):
        try:
            if element.find_elements("css selector", SUBJECT_FIELD):
                found.append(element)
        except Exception:
            continue
    return found


def restore(dialog):
    """Expand a minimised compose window; no-op when it is already open."""
    if _shown(dialog, SUBJECT_FIELD):
        return
    for button in dialog.find_elements("css selector", RESTORE_BUTTON):
        try:
            if button.is_displayed():
                button.click()
                break
        except Exception:
            continue
    WebDriverWaitLike(dialog, FILL_TIMEOUT).until(lambda _: _shown(dialog, SUBJECT_FIELD))


def close_compose_windows(driver):
    """Discard every open compose window so a run starts from a clean page."""
    for _ in range(MAX_LEFTOVER_COMPOSE):
        windows = compose_windows(driver)
        if not windows:
            return
        dialog = windows[-1]
        restore(dialog)
        subject = ""
        try:
            subject = visible_field(dialog, WebDriverWaitLike(dialog, 2), SUBJECT_FIELD).get_attribute("value") or ""
        except Exception:
            pass
        filled_to = recipients(dialog)
        if subject.strip() or filled_to:
            raise RuntimeError(
                f"an unsent compose window is still open (to {', '.join(filled_to) or 'nobody'}, "
                f"subject {subject!r}); send or discard it in Gmail, then rerun")
        discard(driver, dialog)
        WebDriverWaitLike(driver, FILL_TIMEOUT).until(
            lambda _: len(compose_windows(driver)) < len(windows))
        dismiss_alert(driver)
    if compose_windows(driver):
        raise RuntimeError("could not close leftover compose windows")


def open_compose(driver, wait, record=None):
    """Open one fresh compose window with the Compose button; no page navigation.

    Loading a URL while a compose window has content raises Gmail's leave-page
    alert, so the sender stays on the loaded inbox for the whole run.
    """
    dismiss_alert(driver)
    close_compose_windows(driver)
    for _attempt in range(COMPOSE_ATTEMPTS):
        WebDriverWaitLike(driver, FILL_TIMEOUT).until(lambda _: _shown(driver, COMPOSE_BUTTON))
        for button in driver.find_elements("css selector", COMPOSE_BUTTON):
            if button.is_displayed():
                button.click()
                break
        try:
            dialog = WebDriverWaitLike(driver, FILL_TIMEOUT).until(lambda _: next(
                (window for window in compose_windows(driver) if _shown(window, SUBJECT_FIELD)), None))
            return dialog, False
        except TimeoutError:
            dismiss_alert(driver)  # the click can land while Gmail is still loading; try again
    raise RuntimeError(f"compose window did not open after {COMPOSE_ATTEMPTS} Compose clicks")


def insert(element, text):
    """Type text as-is; CDP insertText keeps blank lines and skips autocorrect."""
    element.click()
    element._parent.execute_cdp_cmd("Input.insertText", {"text": text})


def set_body(driver, body, text):
    """Replace the whole body, signature included, with plain draft text.

    Clicking into the body lands the caret inside Gmail's signature, so typed text
    inherits its fonts (e.g. bold italic monospace). Emptying the body first gives
    an unformatted message containing exactly the draft, which has its own sign-off.
    """
    driver.execute_script("""
        const body = arguments[0];
        body.focus();
        body.replaceChildren();  // Gmail enforces Trusted Types; innerHTML is blocked.
        const range = document.createRange();
        range.setStart(body, 0);
        range.collapse(true);
        const selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
    """, body)
    driver.execute_cdp_cmd("Input.insertText", {"text": text})


def attach_file(driver, path):
    """Set the compose's file input through CDP."""
    document = driver.execute_cdp_cmd("DOM.getDocument", {"depth": 1, "pierce": True})
    node = driver.execute_cdp_cmd("DOM.querySelector", {
        "nodeId": document["root"]["nodeId"],
        "selector": ", ".join(f"{container} {field}" for container in DIALOG.split(", ")
                              for field in FILE_INPUT.split(", "))})
    if not node.get("nodeId"):
        raise RuntimeError("compose file input not found")
    driver.execute_cdp_cmd("DOM.setFileInputFiles",
                           {"files": [path], "nodeId": node["nodeId"]})


def wait_for_attachment(dialog, wait, name):
    """Confirm the attachment chip shows the expected filename."""
    def chip(_):
        try:
            return name in (dialog.text or "")
        except Exception:
            return False
    wait.until(chip)
    # The chip appears before the upload finishes; wait for its progress bar to go.
    deadline = time.time() + UPLOAD_TIMEOUT
    while time.time() < deadline:
        try:
            if not dialog.find_elements("css selector", UPLOAD_PROGRESS):
                return
        except Exception:
            return
        time.sleep(0.5)
    raise RuntimeError("attachment upload did not finish")


def recipients(dialog):
    """Addresses shown in the To field: Gmail chips first, then the raw input."""
    found = []
    for element in dialog.find_elements("css selector", RECIPIENT_CHIP):
        for attribute in ("data-hovercard-id", "email", "data-name"):
            try:
                value = element.get_attribute(attribute)
            except Exception:
                value = None
            if value and "@" in value:
                address = _normalise(value)
                if address not in found:
                    found.append(address)
                break
    for element in dialog.find_elements("css selector", TO_FIELD):
        try:
            value = _normalise(element.get_attribute("value"))
        except Exception:
            value = ""
        for part in re.split(r"[,;]", value):
            if part.strip() and part.strip() not in found:
                found.append(part.strip())
    return found


def visible_field(dialog, wait, selector):
    """The first displayed, enabled match; Gmail keeps hidden twins of some inputs."""
    def ready(_):
        for element in dialog.find_elements("css selector", selector):
            try:
                if element.is_displayed() and element.is_enabled():
                    return element
            except Exception:
                continue
        return None
    return wait.until(ready)


SIGN_OFF = re.compile(r"^(cheers|best|best regards|regards|kind regards|thanks|thank you|sincerely)[,!.]?$",
                      re.I)
SIGNATURE_JS = """
const sig = arguments[0].querySelector('.gmail_signature');
if (!sig) return null;
const links = [...sig.querySelectorAll('a[href]')].map(a => [a.innerText.trim(), a.href]);
return {text: sig.innerText, links: links};
"""


def contact_lines(signature, body):
    """Plain-text contact lines from Gmail's signature, minus its sign-off and name.

    ``signature`` is {"text": innerText, "links": [[label, href], ...]}. Lines
    already in the draft body (e.g. the name) and closing words are dropped; a
    link label becomes "Label: URL" so the address survives as plain text.
    """
    if not signature:
        return []
    links = {label: href for label, href in signature.get("links") or [] if label}
    existing = {line.strip().lower() for line in body.splitlines() if line.strip()}
    lines = []
    for line in (signature.get("text") or "").splitlines():
        line = line.strip()
        if not line or SIGN_OFF.match(line) or line.lower() in existing:
            continue
        lines.append(f"{line}: {links[line]}" if line in links and links[line] != line else line)
    return lines


def with_contact(record, lines):
    """The draft with contact lines placed directly under its last line (the name)."""
    if not lines:
        return record
    return dict(record, body=record["body"].rstrip() + "\n" + "\n".join(lines))


def enter_recipient(dialog, wait, email, attempts=RECIPIENT_ATTEMPTS):
    """Type the address and wait until Gmail shows it as a recipient; retry if it drops.

    Gmail occasionally swallows the address (the chip never forms), which left the
    compose with no recipient and failed verification.
    """
    target = email.lower()
    for _attempt in range(attempts):
        to = visible_field(dialog, wait, TO_FIELD)
        try:
            to.clear()
        except Exception:
            pass
        insert(to, email)
        to.send_keys("\n")
        deadline = time.time() + RECIPIENT_TIMEOUT
        while time.time() < deadline:
            if target in [address.lower() for address in recipients(dialog)]:
                return
            time.sleep(0.25)
    raise RuntimeError(f"recipient {email} did not register after {attempts} attempts")


def fill(driver, dialog, wait, record, attach=None, *, prefilled=False, contact=False):
    """Fill one compose window, read the values back, and return the record actually used."""
    if not prefilled:
        enter_recipient(dialog, wait, record["email"])
        insert(visible_field(dialog, wait, SUBJECT_FIELD), record["subject"])
    body = visible_field(dialog, wait, BODY_FIELD)
    if contact:
        signature = wait.until(lambda _: driver.execute_script(SIGNATURE_JS, body))
        lines = contact_lines(signature, record["body"])
        if not lines:
            raise RuntimeError("Gmail signature has no contact lines to copy")
        record = with_contact(record, lines)
    set_body(driver, body, record["body"])
    if attach:
        attach_file(driver, attach)
        wait_for_attachment(dialog, wait, Path(attach).name)
    verify(dialog, record, attach)
    return record


class WebDriverWaitLike:
    """Small polling wait usable with fakes as well as a real driver."""
    def __init__(self, driver, timeout=FILL_TIMEOUT):
        self.driver, self.timeout = driver, timeout

    def until(self, predicate):
        end = time.time() + self.timeout
        while True:
            value = predicate(self.driver)
            if value:
                return value
            if time.time() > end:
                raise TimeoutError("condition not met before timeout")
            time.sleep(0.25)


def _normalise(text):
    return re.sub(r"\s+", " ", (text or "").replace("​", "")).strip()


def verify(dialog, record, attach=None):
    """Compare the compose contents with the draft; raise on any mismatch."""
    problems = []
    found = [address.lower() for address in recipients(dialog)]
    if found != [record["email"].lower()]:
        problems.append(f"recipients are {found!r}")
    subject = dialog.find_element("css selector", SUBJECT_FIELD).get_attribute("value") or ""
    if subject != record["subject"]:
        problems.append("subject differs")
    field = dialog.find_element("css selector", BODY_FIELD)
    # innerText keeps line breaks between Gmail's per-line <div>s; textContent glues them.
    body = field.get_attribute("innerText") or field.get_attribute("textContent") or ""
    if _normalise(body) != _normalise(record["body"]):
        problems.append("body differs (signature or formatting left in the body?)")
    if field.find_elements("css selector", "b, i, strong, em, font, .gmail_signature"):
        problems.append("body contains formatting or a signature")
    if attach and Path(attach).name not in (dialog.text or ""):
        problems.append("attachment chip missing")
    if problems:
        raise RuntimeError("compose verification failed: " + "; ".join(problems))
    return True


def _snackbar_texts(driver):
    texts = []
    for element in driver.find_elements("css selector", SNACKBAR):
        try:
            texts.append((element.text or "").strip())
        except Exception:
            continue
    return texts


def _open_subjects(driver):
    """Subjects of every compose window still open (re-found each time; never stale)."""
    subjects = []
    for window in compose_windows(driver):
        try:
            subjects += [field.get_attribute("value") or "" for field in
                         window.find_elements("css selector", SUBJECT_FIELD)]
        except Exception:
            continue
    return subjects


def send(driver, dialog, wait, subject=None):
    """Click Send; confirmed only when Gmail says "Message sent" and the window is gone.

    A closed-looking window is not proof: Gmail re-renders compose windows, which
    makes the old element stale. Anything short of the notice is SendUnconfirmed.
    """
    sent_notice = re.compile(r"message sent", re.I)
    deadline = time.time() + NOTICE_CLEAR_TIMEOUT
    while time.time() < deadline and any(sent_notice.search(t) for t in _snackbar_texts(driver)):
        time.sleep(0.25)  # let the previous message's notice clear first
    button = None
    for element in dialog.find_elements("css selector", 'div[role="button"]'):
        try:
            if (element.get_attribute("aria-label") or "").startswith("Send"):
                button = element
                break
        except Exception:
            continue
    if button is None:
        raise RuntimeError("Send button not found")
    button.click()
    end = time.time() + SENT_TIMEOUT
    noticed = closed = False
    while time.time() < end:
        for text in _snackbar_texts(driver):
            if re.search(r"error|failed|couldn.t|limit", text, re.I):
                raise RuntimeError(f"Gmail reported: {text}")
            if sent_notice.search(text):
                noticed = True
        closed = subject is None or subject not in _open_subjects(driver)
        if noticed and closed:
            return "snackbar"
        time.sleep(0.25)
    if not closed:
        raise SendUnconfirmed("compose window still open after Send; send unconfirmed")
    raise SendUnconfirmed("compose closed but Gmail never showed 'Message sent'; send unconfirmed")


def discard(driver, dialog):
    for element in dialog.find_elements("css selector", DISCARD_BUTTON):
        try:
            element.click()
            return
        except Exception:
            continue


# >>>>>>>>>>>>>>>>>>>>> Run <<<<<<<<<<<<<<<<<<<<

def signed_in_account(driver):
    """The Gmail address of the open mailbox, read from the title or account button."""
    texts = [driver.title or ""]
    for element in driver.find_elements("css selector", ACCOUNT_BUTTON):
        try:
            texts.append(element.get_attribute("aria-label") or "")
        except Exception:
            continue
    for text in texts:
        match = ADDRESS_IN_TEXT.search(text)
        if match:
            return match.group(0).lower()
    return None


def preflight_message(driver, expected_from=None):
    """Raise unless Gmail is reachable for this profile; return the signed-in address."""
    signin = "Chrome profile is not signed in to Gmail (redirected to Google sign-in)"
    if "accounts.google.com" in (driver.current_url or ""):
        raise PreflightError(signin)
    if "mail.google.com" not in (driver.current_url or ""):
        driver.get(COMPOSE_URL)
        WebDriverWaitLike(driver).until(
            lambda d: any(host in (d.current_url or "")
                          for host in ("mail.google.com", "accounts.google.com")))
        if "accounts.google.com" in (driver.current_url or ""):
            raise PreflightError(signin)
    dismiss_alert(driver)
    deadline = time.time() + 30
    while time.time() < deadline:
        if driver.find_elements("css selector", COMPOSE_BUTTON) or compose_dialog(driver):
            break
        time.sleep(0.5)
    else:
        raise PreflightError("Gmail compose button never appeared; is the profile signed in and loaded?")
    account = signed_in_account(driver)
    if expected_from and (account or "") != expected_from.strip().lower():
        raise PreflightError(f"Signed-in Gmail account is {account or 'unknown'}, "
                             f"not --from {expected_from}")
    return account


def run(*, source=DEFAULT_SOURCE, from_html=None, logs_root="logs/outreach", limit=25,
        start=1, only=(), attach=None, dry_run=False, delay=DEFAULT_DELAY, seed=None,
        include_held=False, expected_from=None, no_attach=False, contact=True,
        verify_sent=True, browsers=None, printer=print):
    """Send one batch. Returns the run summary; never raises for a single failure."""
    if limit < 1:
        raise PreflightError("--limit must be positive")
    records = load_drafts(source)
    if from_html:
        drift = compare_sources(records, records_from_html(from_html))
        if drift:
            printer(f"warning: review HTML disagrees with the JSON ledger ({len(drift)} draft(s)); "
                    "JSON wins")
            for line in drift[:10]:
                printer(f"  {line}")
    if no_attach:
        if attach:
            raise PreflightError("--attach and --no-attach cannot be combined")
        records = without_attachment_claim(records)
    attach, warned = validate(records, attach, sending=not dry_run)
    for line in warned[:3]:
        printer(f"warning: {line}")
    if len(warned) > 3:
        printer(f"warning: ...and {len(warned) - 3} more drafts claim an attachment; "
                "a real send needs --attach")
    already = read_ledger(logs_root)
    chosen, skipped = select(records, already_sent=already, limit=limit, start=start, only=only,
                             include_held=include_held, exclusions=read_exclusions(logs_root))
    if not chosen:
        raise PreflightError("No drafts selected for this run")

    lock = acquire_run_lock(logs_root)
    stamp = _now()
    run_id = f"{stamp:%Y%m%dT%H%M%SZ}-{_slug('dry' if dry_run else 'send')}"
    run_dir = Path(logs_root) / run_id
    (run_dir / "screenshots").mkdir(parents=True, exist_ok=True)
    ledger = run_dir / "sent.jsonl"
    rng = random.Random(seed)

    driver, wait, address, launched = (browsers or open_browser_with(None))()
    printer(f"run {run_id}: {len(chosen)} draft(s), {'dry run' if dry_run else 'sending'}, "
            f"{'attached ' + attach if attach else 'no attachment'}")
    sent, failed, verification, unconfirmed = [], [], None, []
    try:
        frame_for(driver)
        account = preflight_message(driver, expected_from)
        printer(f"signed in as {account or 'unknown account (use --from to enforce one)'}")
        for position, record in enumerate(chosen, 1):
            draft_id = record["draft_id"]
            dialog = None
            try:
                dialog, prefilled = open_compose(driver, wait, record)
                record = fill(driver, dialog, wait, record, attach, prefilled=prefilled,
                              contact=contact)
                shot = run_dir / "screenshots" / f"{position:03d}-{_slug(draft_id)}-filled.png"
                driver.save_screenshot(str(shot))
                if dry_run:
                    discard(driver, dialog)
                    wait.until(lambda _: compose_dialog(driver) is None)
                else:
                    try:
                        confirm = send(driver, dialog, wait, subject=record["subject"])
                    except SendUnconfirmed:
                        # Possibly delivered: record it so a rerun skips it unless --only.
                        unconfirmed_row = _sent_row(record, run_id, "unconfirmed",
                                                    shot, attach, account)
                        append_ledger(ledger, unconfirmed_row)
                        unconfirmed.append(unconfirmed_row)
                        raise
                    record_row = _sent_row(record, run_id, confirm, shot, attach, account)
                    append_ledger(ledger, record_row)
                    sent.append(record_row)
                printer(f"[{position}/{len(chosen)}] OK {draft_id} -> {record['email']}")
                if position < len(chosen):
                    pause = rng.uniform(*delay)
                    printer(f"    waiting {pause:.0f}s")
                    time.sleep(pause)
            except Exception as error:
                shot = run_dir / "screenshots" / f"{position:03d}-{_slug(draft_id)}-failed.png"
                try:
                    driver.save_screenshot(str(shot))
                except Exception:
                    shot = None
                reason = _reason(error)
                failed.append({"draft_id": draft_id, "email": record["email"],
                               "reason": reason, "screenshot": str(shot) if shot else None})
                printer(f"[{position}/{len(chosen)}] FAIL {draft_id}: {reason}")
                if dialog is not None and not isinstance(error, SendUnconfirmed):
                    try:
                        discard(driver, dialog)
                    except Exception:
                        pass
        if (sent or unconfirmed) and verify_sent:
            printer("verifying sent messages in Gmail Sent...")
            verification = verify_rows(driver, sent + unconfirmed, printer)
            if verification["verdict"] != "BATCH VERIFIED":
                printer(f"not found in Sent? requeue them: python3 outreach.py --requeue {run_id}")
    finally:
        lock.close()
        write_report(run_dir, run_id, sent, failed, skipped, dry_run, attach, launched, address)
        if verification:
            write_verification(run_dir, verification)
        if launched:
            try:
                driver.quit()
            except Exception:
                pass
    return {"run_id": run_id, "directory": str(run_dir), "sent": sent,
            "failed": failed, "skipped": skipped, "verification": verification}


# >>>>>>>>>>>>>>>>>>>>> Post-send verification <<<<<<<<<<<<<<<<<<<<

SEARCH_ROW = 'div[role="main"] tr.zA'
ROW_SUBJECT = 'span.bog'
THREAD_SUBJECT = 'h2.hP'
MESSAGE_BODY = 'div.a3s'
VERIFY_TIMEOUT = 45


def body_fingerprint(text):
    """Hash of the whitespace-normalised body, comparable with Gmail's rendered text."""
    return hashlib.sha256(_normalise(text).encode()).hexdigest()


def sent_search_url(row):
    query = f'in:sent to:{row["email"]} subject:"{row["subject"]}"'
    return f"{COMPOSE_URL}#search/{quote(query, safe='')}"


def _visible_rows(driver, subject):
    rows = []
    for row in driver.find_elements("css selector", SEARCH_ROW):
        try:
            if not row.is_displayed():
                continue
            titles = [item.text.strip() for item in row.find_elements("css selector", ROW_SUBJECT)]
            if subject in titles:
                rows.append(row)
        except Exception:
            continue
    return rows


def verify_one(driver, row, timeout=VERIFY_TIMEOUT):
    """Find one ledger row in Gmail Sent and check recipient and body; never raises."""
    result = {"draft_id": row.get("draft_id"), "email": row.get("email"),
              "subject": row.get("subject"), "status": "missing", "detail": ""}
    try:
        driver.get(sent_search_url(row))
        deadline = time.time() + timeout
        matches = []
        while time.time() < deadline:
            matches = _visible_rows(driver, row["subject"])
            if matches:
                break
            time.sleep(1)
        if not matches:
            result["detail"] = "no message with this subject to this recipient in Sent"
            return result
        result["sent_matches"] = len(matches)
        matches[0].click()
        WebDriverWaitLike(driver, FILL_TIMEOUT).until(lambda d: any(
            item.text.strip() == row["subject"] for item in d.find_elements("css selector", THREAD_SUBJECT)))
        bodies = [item for item in driver.find_elements("css selector", MESSAGE_BODY) if item.is_displayed()]
        recipients = {(item.get_attribute("email") or "").lower()
                      for item in driver.find_elements("css selector", "span[email]")}
        if row["email"].lower() not in recipients:
            result.update(status="wrong-recipient", detail=f"recipient {row['email']} not shown on message")
            return result
        if not bodies:
            result.update(status="no-body", detail="message body not found")
            return result
        rendered = driver.execute_script("return arguments[0].innerText", bodies[-1]) or ""
        expected = row.get("body_fingerprint")
        if expected is None:
            result.update(status="confirmed", detail="found in Sent; body not compared (older log row)")
        elif body_fingerprint(rendered) == expected:
            result.update(status="confirmed", detail="found in Sent; recipient and body match")
        else:
            result.update(status="body-mismatch", detail="found in Sent but body differs from what was typed")
        if len(matches) > 1:
            result["detail"] += f"; {len(matches)} matching messages in Sent"
        return result
    except Exception as error:
        result.update(status="error", detail=_reason(error))
        return result


def verify_rows(driver, rows, printer=print):
    """Verify every sent row and print one explicit batch verdict."""
    dismiss_alert(driver)
    close_compose_windows(driver)
    results = []
    for position, row in enumerate(rows, 1):
        result = verify_one(driver, row)
        results.append(result)
        mark = "OK  " if result["status"] == "confirmed" else "FAIL"
        printer(f"  verify [{position}/{len(rows)}] {mark} {row.get('draft_id')} -> {row.get('email')}: "
                f"{result['detail']}")
    try:
        driver.get(COMPOSE_URL)
    except Exception:
        pass
    good = sum(result["status"] == "confirmed" for result in results)
    verdict = "BATCH VERIFIED" if good == len(results) else "BATCH NOT VERIFIED"
    printer(f"{verdict}: {good}/{len(results)} sent message(s) confirmed in Gmail Sent")
    return {"verdict": verdict, "confirmed": good, "total": len(results),
            "checked_utc": _now().isoformat(), "results": results}


def write_verification(run_dir, summary):
    run_dir = Path(run_dir)
    (run_dir / "verify.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                         encoding="utf-8")
    report = run_dir / "report.md"
    lines = ["", f"## Verification — {summary['verdict']} ({summary['confirmed']}/{summary['total']})",
             f"- Checked {summary['checked_utc']} against Gmail Sent"]
    lines += [f"- {item['status'].upper()} {item['draft_id']} -> {item['email']}: {item['detail']}"
              for item in summary["results"]] or ["- nothing to verify"]
    with report.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def find_run_dir(logs_root, run):
    """A run directory from a full path, a run id, or 'latest' (newest send run)."""
    candidate = Path(run).expanduser()
    if candidate.is_dir():
        return candidate
    root = Path(logs_root)
    if run == "latest":
        sends = sorted(path for path in root.glob("*-send") if (path / "sent.jsonl").exists())
        if not sends:
            raise PreflightError(f"No send runs with sent.jsonl under {root}")
        return sends[-1]
    if (root / run).is_dir():
        return root / run
    raise PreflightError(f"Run not found: {run}")


def requeue_missing(run, *, logs_root="logs/outreach"):
    """Void ledger rows that verification found missing from Gmail, so they are resent.

    Only rows whose verify.json status is "missing" are voided; the void is an
    appended line in the same run's sent.jsonl, so history stays append-only.
    """
    run_dir = find_run_dir(logs_root, run)
    report = run_dir / "verify.json"
    if not report.exists():
        raise PreflightError(f"{run_dir.name} has not been verified; run --verify {run_dir.name} first")
    missing = [item for item in json.loads(report.read_text(encoding="utf-8"))["results"]
               if item.get("status") == "missing"]
    for item in missing:
        append_ledger(run_dir / "sent.jsonl", {
            "draft_id": item["draft_id"], "email": item["email"], "void": True,
            "reason": "not found in Gmail Sent at verification", "voided_utc": _now().isoformat()})
    return [item["draft_id"] for item in missing]


def verify_run(run, *, logs_root="logs/outreach", browsers=None, printer=print):
    """Re-check an earlier run's sends against Gmail Sent (read-only)."""
    run_dir = find_run_dir(logs_root, run)
    ledger = run_dir / "sent.jsonl"
    rows = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()] \
        if ledger.exists() else []
    voided = {(row["draft_id"], row["email"]) for row in rows if row.get("void")}
    rows = [row for row in rows if not row.get("void") and (row["draft_id"], row["email"]) not in voided]
    if not rows:
        raise PreflightError(f"{run_dir.name} has no sent messages to verify")
    lock = acquire_run_lock(logs_root)
    driver, _wait, _address, launched = (browsers or open_browser_with(None))()
    try:
        frame_for(driver)
        preflight_message(driver)
        printer(f"verifying {len(rows)} message(s) from {run_dir.name}")
        summary = verify_rows(driver, rows, printer)
        write_verification(run_dir, summary)
        return summary
    finally:
        lock.close()
        if launched:
            try:
                driver.quit()
            except Exception:
                pass


def acquire_run_lock(logs_root):
    """Hold an exclusive lock so two runs never drive the same Gmail window at once."""
    import fcntl
    path = Path(logs_root) / ".run.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        raise PreflightError("Another outreach run is in progress; wait for it to finish") from None
    return handle


def _reason(error):
    """One readable line: Selenium messages carry a chromedriver stack trace."""
    text = getattr(error, "msg", None) or str(error) or type(error).__name__
    return text.strip().splitlines()[0] if text.strip() else type(error).__name__


def _sent_row(record, run_id, confirm, shot, attach, account):
    return {
        "draft_id": record["draft_id"], "email": record["email"],
        "subject": record["subject"], "sent_utc": _now().isoformat(),
        "run_id": run_id, "confirm": confirm, "from": account,
        "screenshot": str(shot), "attachment": attach,
        "body_sha256": hashlib.sha256(record["body"].encode()).hexdigest(),
        "body_fingerprint": body_fingerprint(record["body"]),
    }


def open_browser_with(profile):
    def factory():
        return open_browser(profile or profile_path())
    return factory


def write_report(run_dir, run_id, sent, failed, skipped, dry_run, attach, launched, address):
    lines = [f"# Outreach run {run_id}", "",
             f"- Mode: {'dry run (nothing sent)' if dry_run else 'send'}",
             f"- Attachment: {attach or 'none'}",
             f"- Browser: {'launched' if launched else f'attached {address}'}", "",
             f"## Sent ({len(sent)})"]
    lines += [f"- {row['draft_id']} -> {row['email']} at {row['sent_utc']}" for row in sent] or ["- none"]
    lines += ["", f"## Failed ({len(failed)})"]
    lines += [f"- {row['draft_id']} -> {row['email']}: {row['reason']}" for row in failed] or ["- none"]
    lines += ["", f"## Not attempted ({len(skipped)})"]
    lines += [f"- {draft_id}: {reason}" for draft_id, reason in skipped] or ["- none"]
    (Path(run_dir) / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

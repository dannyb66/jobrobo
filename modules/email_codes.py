"""Fetch a one-time verification code from a mailbox over IMAP.

Some ATSs answer a low-trust submission with an emailed code instead of a
receipt (Greenhouse does this when invisible reCAPTCHA scores us low). The
retained tab then sits on a code prompt and the run ends as
``awaiting_email_verification``. Completing it needs the mailbox, which the
browser cannot reach.

Configured entirely by environment so nothing secret is committed:

    JOBROBO_EMAIL_ADDRESS    mailbox to read (also the expected recipient)
    JOBROBO_EMAIL_PASSWORD   IMAP password or app-password
    JOBROBO_EMAIL_IMAP_HOST  default imap.gmail.com
    JOBROBO_EMAIL_IMAP_PORT  default 993
    JOBROBO_EMAIL_AFTER      unix seconds; only mail newer than this is used
    JOBROBO_EMAIL_FOLDER     default INBOX
"""
from __future__ import annotations

import email
import imaplib
import os
import re
import time

CODE = re.compile(r"\b(\d{6})\b")
SENDER = re.compile(r"greenhouse|ashby|lever|no-?reply|verif", re.I)
SUBJECT = re.compile(r"code|verif|confirm|security", re.I)


def _setting(name, default=""):
    return (os.getenv(name) or default).strip()


def configured() -> bool:
    return bool(_setting("JOBROBO_EMAIL_ADDRESS") and _setting("JOBROBO_EMAIL_PASSWORD"))


def _latest_code(folder="INBOX"):
    """Newest code in a matching recent message, or None."""
    host = _setting("JOBROBO_EMAIL_IMAP_HOST", "imap.gmail.com")
    port = int(_setting("JOBROBO_EMAIL_IMAP_PORT", "993"))
    after = float(_setting("JOBROBO_EMAIL_AFTER", "0") or 0)
    user = _setting("JOBROBO_EMAIL_ADDRESS")
    box = imaplib.IMAP4_SSL(host, port)
    try:
        box.login(user, _setting("JOBROBO_EMAIL_PASSWORD"))
        box.select(folder)
        typ, data = box.search(None, "ALL")
        if typ != "OK":
            return None
        for num in reversed((data[0] or b"").split()[-25:]):
            typ, parts = box.fetch(num, "(RFC822)")
            if typ != "OK" or not parts:
                continue
            message = email.message_from_bytes(parts[0][1])
            # Only mail arriving around this run counts; an older code would
            # be from a previous application.
            try:
                stamp = email.utils.mktime_tz(email.utils.parsedate_tz(message["Date"]))
            except Exception:
                continue
            if after and stamp < after:
                continue
            sender = message.get("From", "")
            subject = message.get("Subject", "")
            if not (SENDER.search(sender) or SUBJECT.search(subject)):
                continue
            body = ""
            for part in message.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                    break
            found = CODE.search(body) or CODE.search(subject)
            if found:
                return found.group(1)
        return None
    finally:
        try:
            box.logout()
        except Exception:
            pass


def await_code(timeout=120, after=None, interval=5):
    """Poll the mailbox for a code, returning it or None on timeout.

    ``after`` defaults to process start, so a rerun cannot pick up the code the
    previous attempt already used.
    """
    if not configured():
        return None
    after = float(after if after is not None else (time.monotonic() and time.time()))
    end = time.time() + timeout
    while time.time() < end:
        try:
            code = _latest_code(_setting("JOBROBO_EMAIL_FOLDER", "INBOX"))
        except Exception:
            code = None
        if code:
            return code
        time.sleep(interval)
    return None

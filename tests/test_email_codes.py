"""Mailbox code extraction; no network."""
import email
import email.utils
import os
import unittest
from unittest import mock

from modules import email_codes


class Message:
    def __init__(self, sender, subject, body, date="Wed, 29 Oct 2026 00:30:00 +0000"):
        self.body, self.date = body, date
        self.headers = {"From": sender, "Subject": subject, "Date": date}
    def get(self, name, default=""): return self.headers.get(name, default)
    def __getitem__(self, name): return self.headers.get(name, "")
    def walk(self): return [self]
    def get_content_type(self): return "text/plain"
    def get_payload(self, decode=False): return self.body.encode() if decode else self.body
    def get_content_charset(self): return "utf-8"
    def as_bytes(self): return b""


def message(sender, subject, body, date="Wed, 29 Oct 2026 00:30:00 +0000"):
    return Message(sender, subject, body, date)


def _raw(m):
    from email.message import EmailMessage
    msg = EmailMessage()
    msg["From"], msg["Subject"], msg["Date"] = m["From"], m["Subject"], m["Date"]
    msg.set_content(m.body)
    return msg.as_bytes()


class FakeBox:
    def __init__(self, messages): self.messages = messages
    def login(self, *a): return "OK", b""
    def select(self, folder): return "OK", b""
    def search(self, *a): return "OK", [b" ".join(str(i).encode() for i in range(len(self.messages)))]
    def fetch(self, num, spec):
        return "OK", [(spec, _raw(self.messages[int(num)]))]
    def logout(self): return "BYE", b""


class CodeTests(unittest.TestCase):
    def setUp(self):
        os.environ.update(JOBROBO_EMAIL_ADDRESS="a@example.test", JOBROBO_EMAIL_PASSWORD="x",
                          JOBROBO_EMAIL_AFTER="0")
        self.addCleanup(lambda: [os.environ.pop(k, None) for k in
                                 ("JOBROBO_EMAIL_ADDRESS", "JOBROBO_EMAIL_PASSWORD", "JOBROBO_EMAIL_AFTER",
                                  "JOBROBO_EMAIL_IMAP_HOST")])

    def run_with(self, messages):
        box = FakeBox(messages)
        with mock.patch.object(email_codes.imaplib, "IMAP4_SSL", return_value=box):
            return email_codes._latest_code()

    def test_takes_the_code_from_an_ats_message(self):
        self.assertEqual(self.run_with([message("no-reply@greenhouse.io", "Verification code",
                                                "Your code is 123456")]), "123456")

    def test_ignores_unrelated_mail(self):
        self.assertIsNone(self.run_with([message("friend@example.test", "lunch", "123456 at noon")]))

    def test_prefers_the_newest_matching_message(self):
        self.assertEqual(self.run_with([message("no-reply@ashbyhq.com", "code", "111111"),
                                        message("no-reply@ashbyhq.com", "code", "222222")]), "222222")

    def test_unconfigured_is_false(self):
        os.environ.pop("JOBROBO_EMAIL_PASSWORD")
        self.assertFalse(email_codes.configured())
        self.assertIsNone(email_codes.await_code(timeout=0))

"""The mailer picks Brevo, SMTP or the log, and talks to Brevo correctly. Nothing is really sent."""
import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import mailer

BREVO = {"BREVO_API_KEY": "test-key", "MAIL_FROM": "Raahi <raahi@example.com>"}


class MailerTests(unittest.TestCase):
    def env(self, values):
        patcher = mock.patch.dict("os.environ", values, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def urlopen(self, **behaviour):
        patcher = mock.patch.object(mailer.urllib.request, "urlopen", **behaviour)
        opened = patcher.start()
        self.addCleanup(patcher.stop)
        return opened

    def test_brevo_request(self):
        self.env(BREVO)
        opened = self.urlopen()
        mailer.send("asha@example.com", "Welcome", "Hello")
        request = opened.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.brevo.com/v3/smtp/email")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Api-key"), "test-key")
        self.assertEqual(json.loads(request.data), {
            "sender": {"name": "Raahi", "email": "raahi@example.com"},
            "to": [{"email": "asha@example.com"}], "subject": "Welcome", "textContent": "Hello"})

    def test_brevo_wins_over_smtp(self):
        self.env({**BREVO, "SMTP_HOST": "smtp.example.com"})
        opened = self.urlopen()
        with mock.patch.object(mailer.smtplib, "SMTP") as smtp:
            mailer.send("a@example.com", "s", "b")
        opened.assert_called_once()
        smtp.assert_not_called()

    def test_brevo_refusal_and_network_errors_raise_mail_error(self):
        self.env(BREVO)
        refused = urllib.error.HTTPError(mailer.BREVO_URL, 401, "Unauthorized", {},
                                         io.BytesIO(b'{"code":"unauthorized"}'))
        self.urlopen(side_effect=refused)
        with self.assertRaises(mailer.MailError):
            mailer.send("a@example.com", "s", "b")
        self.urlopen(side_effect=OSError("down"))
        with self.assertRaises(mailer.MailError):
            mailer.send("a@example.com", "s", "b")

    def test_send_quietly_swallows_failures_and_skips_missing_addresses(self):
        self.env(BREVO)
        opened = self.urlopen(side_effect=OSError("down"))
        mailer.send_quietly("a@example.com", "s", "b")
        mailer.send_quietly(None, "s", "b")
        opened.assert_called_once()

    def test_sender_formats(self):
        for raw, expected in (("Raahi <raahi.pvt.limited@gmail.com>", ("Raahi", "raahi.pvt.limited@gmail.com")),
                              ("Raahi raahi.pvt.limited@gmail.com", ("Raahi", "raahi.pvt.limited@gmail.com")),
                              ('"Team Raahi" <a@b.com>', ("Team Raahi", "a@b.com")),
                              ("a@b.com", ("Raahi", "a@b.com"))):
            self.env({"MAIL_FROM": raw})
            self.assertEqual(mailer.sender(), expected, raw)

    def test_without_settings_the_email_is_only_logged(self):
        self.env({})
        self.assertFalse(mailer.configured())
        opened = self.urlopen()
        mailer.send("a@example.com", "s", "b")
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()

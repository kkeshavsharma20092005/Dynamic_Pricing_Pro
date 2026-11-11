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
        sent = json.loads(request.data)
        html = sent.pop("htmlContent")
        self.assertEqual(sent, {
            "sender": {"name": "Raahi", "email": "raahi@example.com"},
            "to": [{"email": "asha@example.com"}], "subject": "Welcome", "textContent": "Hello"})
        self.assertIn("Hello", html)

    def test_html_version_has_the_logo_and_escapes_the_text(self):
        self.env({"RENDER_EXTERNAL_URL": "https://raahi-jk.onrender.com"})
        page = mailer.html_body("Hi", "Hello <b>Asha</b>,\nline two\n\nTeam Raahi")
        self.assertIn('src="https://raahi-jk.onrender.com/static/icons/icon-192.png"', page)
        self.assertIn("Hello &lt;b&gt;Asha&lt;/b&gt;,<br>line two</p>", page)
        self.assertIn("<p style=\"margin:0 0 16px;\">Team Raahi</p>", page)
        self.env({"PUBLIC_URL": "https://raahi.example/"})
        self.assertIn('src="https://raahi.example/static/icons/icon-192.png"', mailer.html_body("s", "b"))

    def test_without_a_public_address_the_header_has_no_image(self):
        self.env({})
        self.assertNotIn("<img", mailer.html_body("s", "b"))
        self.env({"PUBLIC_URL": "http://localhost:8000"})     # a phone or inbox cannot load this
        self.assertNotIn("<img", mailer.html_body("s", "b"))

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

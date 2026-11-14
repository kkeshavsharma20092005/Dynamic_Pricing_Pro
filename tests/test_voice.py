"""Voice through Sarvam: what the app sends, what it gets back, and how it fails. Sarvam is mocked."""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "data_pipeline"))

import testenv  # noqa: F401  (must precede the backend imports)
import httpx
from fastapi.testclient import TestClient

import voice
from main import app

AUDIO = b"\x1aE\xdf\xa3fake-webm-recording"
_next_phone = [9400000000]


def sarvam_answer(status, body):
    return httpx.Response(status, json=body, request=httpx.Request("POST", "https://api.sarvam.ai"))


class VoiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def setUp(self):
        voice._usage.clear()
        patcher = mock.patch.dict("os.environ", {"SARVAM_API_KEY": "test-key"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.rider = self.account("rider")

    def account(self, role, vehicle=None):
        _next_phone[0] += 1
        phone = str(_next_phone[0])
        with mock.patch("mailer.send_quietly"):
            self.client.post("/api/register", json={"phone": phone, "name": f"Voice {role}", "password": "password123",
                                                    "role": role, "vehicle": vehicle, "email": "v@example.com"})
        token = self.client.post("/api/login", json={"phone": phone, "password": "password123", "role": role}).json()["token"]
        return {"Authorization": "Bearer " + token}

    def listen(self, headers=None, body=AUDIO, content_type="audio/webm", lang="unknown"):
        return self.client.post(f"/api/voice/listen?lang={lang}", content=body,
                                headers={**(headers or self.rider), "Content-Type": content_type})

    def test_status_says_whether_sarvam_is_on(self):
        on = self.client.get("/api/voice/status").json()
        self.assertTrue(on["sarvam"])
        self.assertEqual(on["listen"], ["hi", "ur", "en", "doi", "ks"])
        self.assertEqual(on["speak"], ["hi", "en", "hinglish"])
        with mock.patch.dict("os.environ", {"SARVAM_API_KEY": ""}):
            self.assertEqual(self.client.get("/api/voice/status").json(), {"sarvam": False, "listen": [], "speak": []})

    def test_recording_goes_to_sarvam_and_dogri_comes_back(self):
        answer = sarvam_answer(200, {"request_id": "r1", "transcript": " मैं कटरा जाना ऐ ", "language_code": "doi-IN"})
        with mock.patch.object(voice.httpx, "post", return_value=answer) as post:
            reply = self.listen(lang="doi")
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(reply.json(), {"text": "मैं कटरा जाना ऐ", "lang": "doi"})
        url, kwargs = post.call_args.args[0], post.call_args.kwargs
        self.assertEqual(url, "https://api.sarvam.ai/speech-to-text")
        self.assertEqual(kwargs["headers"], {"api-subscription-key": "test-key"})
        self.assertEqual(kwargs["files"]["file"], ("speech.webm", AUDIO, "audio/webm"))
        self.assertEqual(kwargs["data"], {"model": "saaras:v4", "language_code": "doi-IN"})

    def test_unknown_language_lets_sarvam_detect_it(self):
        answer = sarvam_answer(200, {"request_id": None, "transcript": "hello", "language_code": None})
        with mock.patch.object(voice.httpx, "post", return_value=answer) as post:
            reply = self.listen(lang="klingon")
        self.assertEqual(reply.json(), {"text": "hello", "lang": None})
        self.assertEqual(post.call_args.kwargs["data"]["language_code"], "unknown")

    def test_bad_recordings_are_refused_before_calling_sarvam(self):
        with mock.patch.object(voice.httpx, "post") as post:
            self.assertEqual(self.listen(content_type="text/plain").status_code, 415)
            self.assertEqual(self.listen(body=b"").status_code, 422)
            self.assertEqual(self.listen(body=b"x" * (voice.MAX_AUDIO_BYTES + 1)).status_code, 413)
        post.assert_not_called()

    def test_only_logged_in_riders_can_use_it(self):
        self.assertEqual(self.client.post("/api/voice/listen", content=AUDIO,
                                          headers={"Content-Type": "audio/webm"}).status_code, 401)
        driver = self.account("driver", "cab")
        self.assertEqual(self.listen(headers=driver).status_code, 403)

    def test_sarvam_failures_become_a_clear_503(self):
        refused = sarvam_answer(403, {"error": {"request_id": None, "message": "Invalid key", "code": "invalid_api_key_error"}})
        with mock.patch.object(voice.httpx, "post", return_value=refused):
            self.assertEqual(self.listen().status_code, 503)
        with mock.patch.object(voice.httpx, "post", side_effect=httpx.ConnectError("down")):
            self.assertEqual(self.listen().status_code, 503)
        with mock.patch.dict("os.environ", {"SARVAM_API_KEY": ""}):
            self.assertEqual(self.listen().status_code, 503)

    def test_daily_limit(self):
        answer = sarvam_answer(200, {"transcript": "hi", "language_code": "en-IN"})
        with mock.patch.dict("os.environ", {"VOICE_DAILY_LIMIT": "2"}), \
                mock.patch.object(voice.httpx, "post", return_value=answer) as post:
            self.assertEqual(self.listen().status_code, 200)
            self.assertEqual(self.listen().status_code, 200)
            self.assertEqual(self.listen().status_code, 429)
        self.assertEqual(post.call_count, 2)

    def test_hindi_reply_is_spoken_by_bulbul(self):
        answer = sarvam_answer(200, {"request_id": "r2", "audios": ["UklGRiQAAABXQVZF", "Zm10IBAAAAAB"]})
        with mock.patch.object(voice.httpx, "post", return_value=answer) as post:
            reply = self.client.post("/api/voice/speak", headers=self.rider, json={"text": "आपकी राइड बुक हो गई", "lang": "hi"})
        self.assertEqual(reply.json(), {"audio": "UklGRiQAAABXQVZFZm10IBAAAAAB", "type": "audio/wav"})
        self.assertEqual(post.call_args.args[0], "https://api.sarvam.ai/text-to-speech")
        self.assertEqual(post.call_args.kwargs["json"], {"text": "आपकी राइड बुक हो गई", "language_code": "hi-IN",
                                                         "model": "bulbul:v3", "speaker": "shubh",
                                                         "output_audio_codec": "wav"})

    def test_languages_sarvam_cannot_speak_fall_back_to_the_browser(self):
        with mock.patch.object(voice.httpx, "post") as post:
            reply = self.client.post("/api/voice/speak", headers=self.rider, json={"text": "آپ کی سواری", "lang": "ur"})
        self.assertEqual(reply.json(), {"audio": None})
        post.assert_not_called()
        self.assertEqual(self.client.post("/api/voice/speak", headers=self.rider,
                                          json={"text": "x" * 1501, "lang": "hi"}).status_code, 422)


if __name__ == "__main__":
    unittest.main()

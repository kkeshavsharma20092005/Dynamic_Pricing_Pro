"""
Voice for the booking assistant through Sarvam AI, which knows Indian languages far better
than the browsers do: it hears Hindi, Urdu, Dogri, Kashmiri and English, and speaks Hindi
and English.

Set SARVAM_API_KEY (dashboard.sarvam.ai > API Keys) to turn it on. The key stays on the
server: the app sends its recording here and gets text or audio back. Without the key, or
when Sarvam fails or a rider reaches the daily limit, these endpoints say so and the app
falls back to the browser's own speech features, so voice never breaks the assistant.

Optional settings:
    SARVAM_TTS_MODEL    default bulbul:v3
    SARVAM_TTS_SPEAKER  default shubh (a bulbul:v3 voice)
    VOICE_DAILY_LIMIT   Sarvam calls per rider per day, default 80
"""
import os
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from rides import current_user

router = APIRouter(prefix="/api/voice", tags=["voice"])

STT_URL = "https://api.sarvam.ai/speech-to-text"
TTS_URL = "https://api.sarvam.ai/text-to-speech"
MAX_AUDIO_BYTES = 2_000_000          # about 30 seconds of compressed speech, Sarvam's REST limit
MAX_SPEECH_CHARS = 1500
AUDIO_TYPES = ("audio/webm", "audio/ogg", "audio/mp4", "audio/mpeg", "audio/wav", "audio/x-wav", "audio/aac")

# The app's language names and Sarvam's. Sarvam hears all of these; it speaks only Hindi and
# English, so Urdu, Dogri and Kashmiri replies are read by the browser or shown as text.
HEARD = {"hi-IN": "hi", "ur-IN": "ur", "en-IN": "en", "doi-IN": "doi", "ks-IN": "ks"}
LISTEN_CODES = {"hi": "hi-IN", "ur": "ur-IN", "en": "en-IN", "doi": "doi-IN", "ks": "ks-IN"}
SPOKEN = {"hi": "hi-IN", "en": "en-IN", "hinglish": "en-IN"}

_usage: dict[tuple[int, str], int] = {}     # (user id, day) -> Sarvam calls, kept in memory


class VoiceError(Exception):
    pass


def configured() -> bool:
    return bool(os.environ.get("SARVAM_API_KEY", "").strip())


def headers() -> dict:
    return {"api-subscription-key": os.environ["SARVAM_API_KEY"].strip()}


def daily_limit() -> int:
    try:
        return int(os.environ.get("VOICE_DAILY_LIMIT", "80"))
    except ValueError:
        return 80


def take_turn(user_id: int) -> None:
    """Count one Sarvam call, or refuse once the rider has used today's allowance."""
    day = time.strftime("%Y-%m-%d")
    for key in [k for k in _usage if k[1] != day]:
        del _usage[key]
    used = _usage.get((user_id, day), 0)
    if used >= daily_limit():
        raise HTTPException(429, "You have used today's voice limit. Typing still works.")
    _usage[(user_id, day)] = used + 1


def sarvam_failure(response: httpx.Response, what: str) -> VoiceError:
    try:
        message = response.json()["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = response.text[:200]
    print(f"[voice] Sarvam {what} failed: HTTP {response.status_code} {message}")
    return VoiceError(f"HTTP {response.status_code}")


def transcribe(audio: bytes, content_type: str, language: str = "unknown") -> dict:
    """Speech to text with Saaras. Returns {"text", "lang"}; lang is None if Sarvam could not tell."""
    extension = content_type.split("/")[-1].split(";")[0].replace("x-", "") or "webm"
    try:
        response = httpx.post(STT_URL, headers=headers(), timeout=30,
                              files={"file": (f"speech.{extension}", audio, content_type)},
                              data={"model": "saaras:v4", "language_code": language})
    except httpx.HTTPError as e:
        print(f"[voice] Sarvam speech-to-text failed: {e}")
        raise VoiceError(str(e)) from e
    if response.status_code != 200:
        raise sarvam_failure(response, "speech-to-text")
    data = response.json()
    return {"text": (data.get("transcript") or "").strip(), "lang": HEARD.get(data.get("language_code"))}


def synthesize(text: str, lang: str) -> str:
    """Text to speech with Bulbul. Returns base64 WAV audio."""
    body = {"text": text, "language_code": SPOKEN[lang],
            "model": os.environ.get("SARVAM_TTS_MODEL", "bulbul:v3"),
            "speaker": os.environ.get("SARVAM_TTS_SPEAKER", "shubh"),
            "output_audio_codec": "wav"}
    try:
        response = httpx.post(TTS_URL, headers=headers(), json=body, timeout=30)
    except httpx.HTTPError as e:
        print(f"[voice] Sarvam text-to-speech failed: {e}")
        raise VoiceError(str(e)) from e
    if response.status_code != 200:
        raise sarvam_failure(response, "text-to-speech")
    audios = response.json().get("audios") or []
    if not audios:
        raise VoiceError("no audio returned")
    # Long text comes back in pieces; joined, they are one base64 WAV, as Sarvam's own samples do.
    return "".join(audios)


def require_rider(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "rider":
        raise HTTPException(403, "The assistant is for rider accounts.")
    return user


@router.get("/status")
def status():
    """Which languages the app can hear and speak through Sarvam right now. Public: it says
    only whether the feature is on, and the app asks before the rider has logged in."""
    return {"sarvam": configured(), "listen": list(LISTEN_CODES) if configured() else [],
            "speak": list(SPOKEN) if configured() else []}


@router.post("/listen")
async def listen(request: Request, lang: str = "unknown", user: dict = Depends(require_rider)):
    """The app posts its recording as the raw request body, with the recording's audio type."""
    if not configured():
        raise HTTPException(503, "Voice through Sarvam is not set up.")
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in AUDIO_TYPES:
        raise HTTPException(415, "Send the recording as audio.")
    audio = await request.body()
    if not audio:
        raise HTTPException(422, "The recording was empty.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Please keep it under 30 seconds.")
    take_turn(user["id"])
    try:
        return transcribe(audio, content_type, LISTEN_CODES.get(lang, "unknown"))
    except VoiceError:
        raise HTTPException(503, "Voice isn't working right now. Please type, or try again.")


class SpeakBody(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_SPEECH_CHARS)
    lang: str


@router.post("/speak")
def speak(body: SpeakBody, user: dict = Depends(require_rider)):
    """Audio for a reply, or {"audio": null} when Sarvam has no voice for that language."""
    if not configured():
        raise HTTPException(503, "Voice through Sarvam is not set up.")
    if body.lang not in SPOKEN:
        return {"audio": None}
    take_turn(user["id"])
    try:
        return {"audio": synthesize(body.text, body.lang), "type": "audio/wav"}
    except VoiceError:
        raise HTTPException(503, "Voice isn't working right now.")

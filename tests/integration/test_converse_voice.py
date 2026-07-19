import base64
import uuid

import httpx
import respx

from tests.conftest import openai_chat_json

OPENAI_CHAT = "https://api.openai.com/v1/chat/completions"
OPENAI_STT = "https://api.openai.com/v1/audio/transcriptions"
OPENAI_TTS = "https://api.openai.com/v1/audio/speech"

FAKE_MP3 = b"ID3fake-mp3-bytes"


def _post_audio(client, data: bytes = b"fake-webm-audio", filename: str = "speech.webm"):
    return client.post(
        "/api/converse",
        data={"session_id": str(uuid.uuid4())},
        files={"audio": (filename, data, "audio/webm")},
        headers={"X-User-Id": str(uuid.uuid4())},
    )


@respx.mock
def test_voice_turn_roundtrip(client):
    respx.post(OPENAI_STT).mock(
        return_value=httpx.Response(200, json={"text": "what is the capital of Japan"})
    )
    respx.post(OPENAI_CHAT).mock(
        return_value=httpx.Response(200, json=openai_chat_json("Tokyo is the capital of Japan."))
    )
    respx.post(OPENAI_TTS).mock(return_value=httpx.Response(200, content=FAKE_MP3))

    r = _post_audio(client)
    assert r.status_code == 200
    body = r.json()
    assert body["transcript"] == "what is the capital of Japan"
    assert body["reply_text"] == "Tokyo is the capital of Japan."
    assert base64.b64decode(body["audio_b64"]) == FAKE_MP3
    t = body["timings"]
    assert t["stt_ms"] >= 0 and t["tts_ms"] >= 0 and t["total_ms"] >= t["llm_ms"]


@respx.mock
def test_tts_failure_degrades_to_text_only(client):
    respx.post(OPENAI_STT).mock(return_value=httpx.Response(200, json={"text": "hello"}))
    respx.post(OPENAI_CHAT).mock(return_value=httpx.Response(200, json=openai_chat_json("Hi!")))
    respx.post(OPENAI_TTS).mock(return_value=httpx.Response(500, json={"error": "boom"}))

    r = _post_audio(client)
    assert r.status_code == 200  # the turn still succeeds
    body = r.json()
    assert body["reply_text"] == "Hi!"
    assert body["audio_b64"] is None  # client falls back to speechSynthesis


@respx.mock
def test_stt_failure_is_honest(client):
    respx.post(OPENAI_STT).mock(return_value=httpx.Response(500, json={"error": "boom"}))
    r = _post_audio(client)
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "stt_failed"


@respx.mock
def test_empty_transcript_rejected(client):
    respx.post(OPENAI_STT).mock(return_value=httpx.Response(200, json={"text": "   "}))
    r = _post_audio(client)
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "stt_failed"


def test_oversized_audio_rejected(client):
    r = _post_audio(client, data=b"0" * (10 * 1024 * 1024 + 1))
    assert r.status_code == 400
    assert "10 MB" in r.json()["error"]["message"]


def test_empty_audio_rejected(client):
    r = _post_audio(client, data=b"")
    assert r.status_code == 400


@respx.mock
def test_text_path_also_returns_tts_audio(client):
    respx.post(OPENAI_CHAT).mock(return_value=httpx.Response(200, json=openai_chat_json("Sure!")))
    respx.post(OPENAI_TTS).mock(return_value=httpx.Response(200, content=FAKE_MP3))
    r = client.post(
        "/api/converse",
        data={"text": "hi", "session_id": str(uuid.uuid4())},
        headers={"X-User-Id": str(uuid.uuid4())},
    )
    assert r.status_code == 200
    assert base64.b64decode(r.json()["audio_b64"]) == FAKE_MP3

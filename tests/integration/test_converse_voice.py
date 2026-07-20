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
def test_voice_turn_roundtrip_with_streamed_speech(client):
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
    # reply returns immediately; audio comes from the streaming endpoint
    assert body["audio_url"] == f"/api/speech/{body['request_id']}"
    t = body["timings"]
    assert t["stt_ms"] >= 0 and t["total_ms"] >= t["llm_ms"]

    speech = client.get(body["audio_url"])
    assert speech.status_code == 200
    assert speech.headers["content-type"].startswith("audio/mpeg")
    assert speech.content == FAKE_MP3


@respx.mock
def test_tts_failure_surfaces_only_on_speech_endpoint(client):
    """The turn itself can no longer be hurt by TTS: reply text always returns;
    a failing speech stream 502s and the client falls back to speechSynthesis."""
    respx.post(OPENAI_STT).mock(return_value=httpx.Response(200, json={"text": "hello"}))
    respx.post(OPENAI_CHAT).mock(return_value=httpx.Response(200, json=openai_chat_json("Hi!")))
    respx.post(OPENAI_TTS).mock(return_value=httpx.Response(500, json={"error": "boom"}))

    r = _post_audio(client)
    assert r.status_code == 200
    assert r.json()["reply_text"] == "Hi!"

    speech = client.get(r.json()["audio_url"])
    assert speech.status_code == 502
    assert speech.json()["error"]["code"] == "tts_failed"


def test_unknown_speech_id_is_404(client):
    r = client.get("/api/speech/doesnotexist")
    assert r.status_code == 404


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
def test_text_path_also_gets_speech_url(client):
    respx.post(OPENAI_CHAT).mock(return_value=httpx.Response(200, json=openai_chat_json("Sure!")))
    respx.post(OPENAI_TTS).mock(return_value=httpx.Response(200, content=FAKE_MP3))
    r = client.post(
        "/api/converse",
        data={"text": "hi", "session_id": str(uuid.uuid4())},
        headers={"X-User-Id": str(uuid.uuid4())},
    )
    assert r.status_code == 200
    assert client.get(r.json()["audio_url"]).content == FAKE_MP3

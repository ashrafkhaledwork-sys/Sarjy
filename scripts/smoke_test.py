"""Deployment smoke test - run against a live Sarjy (local or public).

    python scripts/smoke_test.py http://localhost:8000
    python scripts/smoke_test.py https://sarjy.up.railway.app

Exercises the real stack (spends ~$0.01 of OpenAI credit): health, a text turn,
speech streaming, a voice turn with real recorded audio, and memory round-trip.
Exits non-zero on any failure.
"""

import sys
import time
import uuid
from pathlib import Path

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
USER = str(uuid.uuid4())
SESSION = str(uuid.uuid4())
AUDIO = Path(__file__).resolve().parents[1] / "tests" / "assets" / "hello_sarjy.mp3"

failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"[{'OK ' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    failures += 0 if ok else 1


client = httpx.Client(timeout=120, headers={"X-User-Id": USER})

# 1. health
r = client.get(f"{BASE}/healthz")
check("healthz", r.status_code == 200, str(r.status_code))
r = client.get(f"{BASE}/readyz")
check("readyz (db)", r.status_code == 200 and r.json().get("status") == "ready", r.text[:60])

# 2. text turn
r = client.post(
    f"{BASE}/api/converse",
    data={"text": "In one short sentence, what is the capital of France?", "session_id": SESSION},
)
ok = r.status_code == 200 and r.json().get("reply_text")
check("text converse", bool(ok), r.json().get("reply_text", r.text[:80]))

# 3. speech streaming for that reply
if ok:
    s = client.get(f"{BASE}{r.json()['audio_url']}")
    check(
        "speech stream",
        s.status_code == 200 and len(s.content) > 1000,
        f"{s.status_code}, {len(s.content)} bytes",
    )

# 4. voice turn with real audio
if AUDIO.exists():
    r = client.post(
        f"{BASE}/api/converse",
        data={"session_id": SESSION},
        files={"audio": ("hello.mp3", AUDIO.read_bytes(), "audio/mpeg")},
    )
    ok = r.status_code == 200 and r.json().get("transcript")
    check("voice converse", bool(ok), r.json().get("transcript", r.text[:80])[:60])
else:
    check("voice converse", False, f"missing asset {AUDIO}")

# 5. memory round-trip
r = client.post(
    f"{BASE}/api/converse",
    data={"text": "My favorite color is teal.", "session_id": SESSION},
)
check("memory turn", r.status_code == 200)
time.sleep(4)  # allow the background extraction sweep to finish
mems = client.get(f"{BASE}/api/memories").json().get("memories", [])
check("memory persisted", any("teal" in m["value"].lower() for m in mems), str(mems)[:80])
client.delete(f"{BASE}/api/memories")

print()
print("SMOKE PASSED" if failures == 0 else f"SMOKE FAILED ({failures})")
sys.exit(1 if failures else 0)

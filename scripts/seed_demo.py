"""Seed the demo's returning user: memories + an unfinished booking.

    python scripts/seed_demo.py [base-url]

Prints the user id to plant in the second browser before the demo:
    localStorage.setItem("sarjy_user_id", "<id>")
Safe to re-run - creates a fresh user each time (~$0.01 of API spend).
"""

import sys
import time
import uuid

import httpx

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000").rstrip("/")
USER = str(uuid.uuid4())

client = httpx.Client(timeout=180, headers={"X-User-Id": USER})


def turn(text: str) -> dict:
    r = client.post(
        f"{BASE}/api/converse",
        data={"text": text, "session_id": str(uuid.uuid4())},
    )
    r.raise_for_status()
    return r.json()


print(f"seeding against {BASE} ...")
turn("Hi! My name is Ashraf, my favorite color is blue, and I love Italian food.")
turn("I want to book a table for 2 somewhere in Maadi")  # left unfinished on purpose

time.sleep(5)  # let the background extraction sweep land
memories = client.get(f"{BASE}/api/memories").json()["memories"]
bookings = client.get(f"{BASE}/api/bookings").json()["bookings"]

print(f"memories: {[m['key'] + '=' + m['value'] for m in memories]}")
print(f"bookings: {[(b['status'], b['slots']) for b in bookings]}")
print()
print("Plant this in the second browser's console, then reload:")
print(f'  localStorage.setItem("sarjy_user_id", "{USER}")')

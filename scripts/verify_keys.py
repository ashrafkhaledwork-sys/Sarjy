"""Phase 1 key verification: run after filling .env.

    python scripts/verify_keys.py [demo city]

Checks OpenAI auth, then Foursquare (both current and legacy auth styles)
and/or Geoapify restaurant search for the demo city. Exits non-zero if the
required keys fail, and tells you which PLACES_PROVIDER to set.
"""

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import settings  # noqa: E402

CITY = sys.argv[1] if len(sys.argv) > 1 else "Cairo"
ok = True


def report(name: str, success: bool, detail: str) -> None:
    global ok
    print(f"[{'OK ' if success else 'FAIL'}] {name}: {detail}")
    if not success:
        ok = False


# --- OpenAI ---
if not settings.openai_api_key:
    report("OpenAI", False, "OPENAI_API_KEY is empty in .env")
else:
    r = httpx.get(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {settings.openai_api_key}"},
        timeout=15,
    )
    report("OpenAI", r.status_code == 200, f"HTTP {r.status_code}")

# --- Foursquare: try current (Bearer + version header) then legacy v3 auth ---
if settings.foursquare_api_key:
    fsq_ok, fsq_detail = False, "no auth style worked"
    for label, url, headers in [
        (
            "places-api (Bearer)",
            "https://places-api.foursquare.com/places/search",
            {
                "Authorization": f"Bearer {settings.foursquare_api_key}",
                "X-Places-Api-Version": "2025-06-17",
            },
        ),
        (
            "legacy v3",
            "https://api.foursquare.com/v3/places/search",
            {"Authorization": settings.foursquare_api_key},
        ),
    ]:
        r = httpx.get(
            url,
            headers={**headers, "Accept": "application/json"},
            params={"query": "restaurant", "near": CITY, "limit": 3},
            timeout=15,
        )
        if r.status_code == 200:
            names = [p.get("name") for p in r.json().get("results", [])]
            fsq_ok, fsq_detail = bool(names), f"{label} -> {names or 'zero results in ' + CITY}"
            if fsq_ok:
                break
        else:
            fsq_detail = f"{label} -> HTTP {r.status_code}"
    report("Foursquare", fsq_ok, fsq_detail)
else:
    print("[SKIP] Foursquare: FOURSQUARE_API_KEY empty")

# --- Geoapify ---
if settings.geoapify_api_key:
    r = httpx.get(
        "https://api.geoapify.com/v1/geocode/search",
        params={"text": CITY, "limit": 1, "apiKey": settings.geoapify_api_key},
        timeout=15,
    )
    geo_ok = r.status_code == 200 and bool(r.json().get("features"))
    report("Geoapify", geo_ok, f"HTTP {r.status_code}, geocoded {CITY}: {geo_ok}")
else:
    print("[SKIP] Geoapify: GEOAPIFY_API_KEY empty")

if not settings.foursquare_api_key and not settings.geoapify_api_key:
    report("Places", False, "need at least one of FOURSQUARE_API_KEY / GEOAPIFY_API_KEY")

print()
print("All required checks passed." if ok else "Fix the failures above before Phase 3.")
sys.exit(0 if ok else 1)

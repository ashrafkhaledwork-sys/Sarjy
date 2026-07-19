"""Restaurant search behind a provider interface.

Foursquare (primary, new places-api Bearer auth - verified during key setup)
and Geoapify (fallback) normalize to the same Restaurant shape, so swapping
providers is an env-var change: PLACES_PROVIDER=foursquare|geoapify.

External facts must come from validated tool results: on any failure these
return an error marker - the model is instructed to relay it honestly and
can never fabricate restaurants because none enter the prompt any other way.
"""

import logging
import time
from typing import Protocol

import httpx
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

TIMEOUT = httpx.Timeout(10.0)
SEARCH_UNAVAILABLE = {"error": "search_unavailable"}


class Restaurant(BaseModel):
    name: str
    address: str = ""
    categories: list[str] = []
    rating: float | None = None
    price_tier: int | None = None


class PlacesProvider(Protocol):
    def search(self, query: str, near: str, limit: int) -> list[Restaurant]: ...


class FoursquareProvider:
    BASE = "https://places-api.foursquare.com/places/search"

    def search(self, query: str, near: str, limit: int) -> list[Restaurant]:
        resp = httpx.get(
            self.BASE,
            headers={
                "Authorization": f"Bearer {settings.foursquare_api_key}",
                "X-Places-Api-Version": "2025-06-17",
                "Accept": "application/json",
            },
            # Default fields only: rating/price are premium-tier on the free plan
            # and requesting them draws from a separate, tiny quota bucket (429s).
            params={"query": query, "near": near, "limit": limit},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        results = []
        for place in resp.json().get("results", []):
            results.append(
                Restaurant(
                    name=place.get("name", "Unknown"),
                    address=(place.get("location") or {}).get("formatted_address", ""),
                    categories=[c.get("name", "") for c in place.get("categories", [])][:3],
                    rating=place.get("rating"),
                    price_tier=place.get("price"),
                )
            )
        return results


class GeoapifyProvider:
    GEOCODE = "https://api.geoapify.com/v1/geocode/search"
    PLACES = "https://api.geoapify.com/v2/places"

    def search(self, query: str, near: str, limit: int) -> list[Restaurant]:
        geo = httpx.get(
            self.GEOCODE,
            params={"text": near, "limit": 1, "apiKey": settings.geoapify_api_key},
            timeout=TIMEOUT,
        )
        geo.raise_for_status()
        features = geo.json().get("features", [])
        if not features:
            return []
        lon, lat = features[0]["geometry"]["coordinates"]

        resp = httpx.get(
            self.PLACES,
            params={
                "categories": "catering.restaurant",
                "filter": f"circle:{lon},{lat},6000",
                "name": query if query != "restaurant" else None,
                "limit": limit,
                "apiKey": settings.geoapify_api_key,
            },
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
        results = []
        for feature in resp.json().get("features", []):
            props = feature.get("properties", {})
            if not props.get("name"):
                continue
            results.append(
                Restaurant(
                    name=props["name"],
                    address=props.get("formatted", ""),
                    categories=[c for c in props.get("categories", []) if "." in c][:3],
                )
            )
        return results


def get_provider() -> PlacesProvider:
    if settings.places_provider.lower() == "geoapify":
        return GeoapifyProvider()
    return FoursquareProvider()


def search_restaurants(query: str, near: str, limit: int = 3) -> dict:
    """Execute a search with one retry; degrade to an honest error marker."""
    provider = get_provider()
    for attempt in (1, 2):
        try:
            restaurants = provider.search(query, near, limit)
            return {"restaurants": [r.model_dump(exclude_none=True) for r in restaurants]}
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.error(
                "places search attempt %d failed: %s: %s", attempt, type(exc).__name__, exc
            )
            if attempt == 1:
                time.sleep(0.8)  # QPS throttles clear quickly
    return dict(SEARCH_UNAVAILABLE)

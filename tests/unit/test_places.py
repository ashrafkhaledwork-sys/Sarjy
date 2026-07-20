import httpx
import respx

from app.tools.places import FoursquareProvider, search_restaurants

FSQ = "https://places-api.foursquare.com/places/search"

FSQ_PAYLOAD = {
    "results": [
        {
            "name": "Kababgy El Nasr",
            "location": {"formatted_address": "12 El Nasr St, Cairo"},
            "categories": [{"name": "Kebab Restaurant"}, {"name": "Grill"}],
            "rating": 8.9,
            "price": 2,
        },
        {"name": "Latif Wassily", "location": {}},
    ]
}


@respx.mock
def test_foursquare_parses_results():
    respx.get(FSQ).mock(return_value=httpx.Response(200, json=FSQ_PAYLOAD))
    results = FoursquareProvider().search("kebab", "Cairo", 3)
    assert [r.name for r in results] == ["Kababgy El Nasr", "Latif Wassily"]
    assert results[0].address == "12 El Nasr St, Cairo"
    assert results[0].rating == 8.9
    assert results[0].price_tier == 2
    assert results[1].address == ""


@respx.mock
def test_search_returns_normalized_dicts():
    respx.get(FSQ).mock(return_value=httpx.Response(200, json=FSQ_PAYLOAD))
    result = search_restaurants("kebab", "Cairo")
    assert "restaurants" in result
    assert result["restaurants"][0]["name"] == "Kababgy El Nasr"
    # None fields are excluded so the model never sees nulls
    assert "rating" not in result["restaurants"][1]


@respx.mock
def test_search_retries_then_degrades_honestly():
    route = respx.get(FSQ).mock(return_value=httpx.Response(500))
    result = search_restaurants("kebab", "Cairo")
    assert result == {"error": "search_unavailable"}
    assert route.call_count == 2  # exactly one retry


@respx.mock
def test_search_survives_timeout():
    respx.get(FSQ).mock(side_effect=httpx.ConnectTimeout("slow"))
    assert search_restaurants("kebab", "Cairo") == {"error": "search_unavailable"}


@respx.mock
def test_zero_results_is_not_an_error():
    respx.get(FSQ).mock(return_value=httpx.Response(200, json={"results": []}))
    assert search_restaurants("sushi", "Nowhere") == {"restaurants": []}


@respx.mock
def test_geocoded_areas_use_precise_coordinates(monkeypatch):
    """Foursquare's `near` geocoder fails on districts like 'New Cairo';
    with a Geoapify key we geocode first and send ll+radius instead."""
    monkeypatch.setattr(
        "app.tools.places.settings.geoapify_api_key", "test-geo-key", raising=False
    )
    respx.get("https://api.geoapify.com/v1/geocode/search").mock(
        return_value=httpx.Response(
            200,
            json={"features": [{"geometry": {"coordinates": [31.476, 30.028]}}]},
        )
    )
    fsq = respx.get(FSQ).mock(return_value=httpx.Response(200, json=FSQ_PAYLOAD))
    result = search_restaurants("sushi", "New Cairo")
    assert result["restaurants"]
    sent = fsq.calls[0].request.url
    assert sent.params["ll"] == "30.028,31.476"
    assert "near" not in sent.params
    assert sent.params["radius"] == "8000"

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz_returns_ok():
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_index_served():
    r = client.get("/")
    assert r.status_code == 200
    assert "Sarjy" in r.text

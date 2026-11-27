"""Tests for the FastAPI application wiring."""

from fastapi.testclient import TestClient

from sec_filings.api.main import app

client = TestClient(app)


def test_health_check():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_app_metadata():
    assert app.title == "SEC Filings Analytics Platform"
    assert app.version == "0.1.0"
    schema = client.get("/openapi.json").json()
    assert schema["info"]["title"] == "SEC Filings Analytics Platform"
    assert schema["info"]["version"] == "0.1.0"


def test_all_routers_mounted_with_prefixes():
    paths = set(client.get("/openapi.json").json()["paths"])
    assert {
        "/health",
        "/insiders/{ticker}",
        "/holdings/{manager_cik}",
        "/holdings/changes/{manager_cik}",
        "/screen/cluster-buying",
        "/screen/concentration",
        "/search/risk-similar/{ticker}",
        "/search/diffs/{ticker}/{year}",
    } <= paths


def test_router_tags():
    schema = client.get("/openapi.json").json()
    tags = {
        path: next(iter(ops.values()))["tags"]
        for path, ops in schema["paths"].items()
        if path != "/health"
    }
    assert tags["/insiders/{ticker}"] == ["Insiders"]
    assert tags["/holdings/{manager_cik}"] == ["Holdings"]
    assert tags["/screen/concentration"] == ["Screens"]
    assert tags["/search/diffs/{ticker}/{year}"] == ["Search"]


def test_cors_preflight_allows_any_origin():
    resp = client.options(
        "/health",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    # allow_credentials=True makes Starlette echo the request origin instead of "*".
    assert resp.headers["access-control-allow-origin"] == "https://example.com"
    assert resp.headers["access-control-allow-credentials"] == "true"


def test_cors_header_on_simple_request():
    resp = client.get("/health", headers={"Origin": "https://example.com"})
    assert resp.status_code == 200
    assert "access-control-allow-origin" in resp.headers


def test_unknown_route_is_404():
    assert client.get("/does-not-exist").status_code == 404

"""Tests for the servicedesk static_router — assetlinks.json endpoint (SD-4)."""

import os
import sys
from pathlib import Path

import pytest

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

os.environ.setdefault("SQLITE_PATH", ":memory:")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from servicedesk.static_router import router as sd_static_router, _PLACEHOLDER_SHA256


@pytest.fixture
def client():
    """Minimal FastAPI app that only registers the sd_static_router."""
    app = FastAPI()
    app.include_router(sd_static_router)
    return TestClient(app, raise_server_exceptions=True)


class TestAssetLinksEndpoint:
    """Tests for GET /.well-known/assetlinks.json (TWA domain verification)."""

    def test_returns_200(self, client):
        resp = client.get("/.well-known/assetlinks.json")
        assert resp.status_code == 200

    def test_content_type_is_json(self, client):
        resp = client.get("/.well-known/assetlinks.json")
        assert "application/json" in resp.headers["content-type"]

    def test_response_is_list(self, client):
        data = client.get("/.well-known/assetlinks.json").json()
        assert isinstance(data, list)
        assert len(data) == 1

    def test_relation_field(self, client):
        entry = client.get("/.well-known/assetlinks.json").json()[0]
        assert "relation" in entry
        assert "delegate_permission/common.handle_all_urls" in entry["relation"]

    def test_target_namespace(self, client):
        target = client.get("/.well-known/assetlinks.json").json()[0]["target"]
        assert target["namespace"] == "android_app"

    def test_target_package_name(self, client):
        target = client.get("/.well-known/assetlinks.json").json()[0]["target"]
        assert target["package_name"] == "ua.imero.servicedesk"

    def test_target_has_sha256_fingerprints(self, client):
        target = client.get("/.well-known/assetlinks.json").json()[0]["target"]
        assert "sha256_cert_fingerprints" in target
        assert isinstance(target["sha256_cert_fingerprints"], list)
        assert len(target["sha256_cert_fingerprints"]) == 1

    def test_placeholder_sha256_present(self, client):
        """Fingerprint list must contain the placeholder (or a real value)."""
        target = client.get("/.well-known/assetlinks.json").json()[0]["target"]
        assert target["sha256_cert_fingerprints"][0] == _PLACEHOLDER_SHA256

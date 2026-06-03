"""
Unit tests for the Knowledge Indexing Platform.

Run:
    pytest service/tests/ -v --cov=app --cov-report=term-missing
"""

import json
import os
import tempfile
import pytest

# Use a temp-file DB so it's shared across all threads (in-memory can't cross threads)
_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_PATH"] = _tmp.name

from fastapi.testclient import TestClient
from app import app
from app.database import init_db
import app.database as db_module


@pytest.fixture(autouse=True)
def reset_db():
    """Wipe and re-create the DB before each test for isolation."""
    # Close any open connections so we can recreate the file cleanly
    if hasattr(db_module._local, "conn") and db_module._local.conn:
        try:
            db_module._local.conn.close()
        except Exception:
            pass
        db_module._local.conn = None
    # Delete and recreate
    import sqlite3
    conn = sqlite3.connect(os.environ["DB_PATH"])
    conn.executescript("PRAGMA writable_schema=ON; DELETE FROM sqlite_master WHERE type IN ('table','index','trigger','view'); PRAGMA writable_schema=OFF; VACUUM;")
    conn.close()
    init_db()
    yield


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


ALPHA_KEY = "key-alpha-secret"
BETA_KEY = "key-beta-secret"
ALPHA_TENANT = "tenant-alpha"
BETA_TENANT = "tenant-beta"


# ─── Health ──────────────────────────────────────────────────────────────────

class TestHealth:
    def test_health_ok(self, client):
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["database"] == "ok"
        assert "timestamp" in body

    def test_health_no_auth_required(self, client):
        """Health endpoint must be public (load balancer doesn't send auth)."""
        r = client.get("/api/v1/health")
        assert r.status_code == 200


# ─── Authentication ───────────────────────────────────────────────────────────

class TestAuth:
    def test_missing_api_key_returns_401(self, client):
        r = client.post(f"/api/v1/tenants/{ALPHA_TENANT}/documents", json={
            "title": "T", "content": "C"
        })
        assert r.status_code == 401

    def test_invalid_api_key_returns_401(self, client):
        r = client.post(
            f"/api/v1/tenants/{ALPHA_TENANT}/documents",
            json={"title": "T", "content": "C"},
            headers={"X-API-Key": "bad-key"},
        )
        assert r.status_code == 401

    def test_cross_tenant_access_denied(self, client):
        """Alpha key cannot access Beta tenant's endpoints."""
        r = client.post(
            f"/api/v1/tenants/{BETA_TENANT}/documents",
            json={"title": "T", "content": "C"},
            headers={"X-API-Key": ALPHA_KEY},
        )
        assert r.status_code == 403


# ─── Document Ingestion ───────────────────────────────────────────────────────

class TestDocumentIngestion:
    def test_create_document_returns_201(self, client):
        r = client.post(
            f"/api/v1/tenants/{ALPHA_TENANT}/documents",
            json={"title": "Hello World", "content": "Some content here", "tags": ["test"]},
            headers={"X-API-Key": ALPHA_KEY},
        )
        assert r.status_code == 201
        body = r.json()
        assert "id" in body
        assert body["tenant_id"] == ALPHA_TENANT

    def test_create_document_missing_title_returns_422(self, client):
        r = client.post(
            f"/api/v1/tenants/{ALPHA_TENANT}/documents",
            json={"content": "No title here"},
            headers={"X-API-Key": ALPHA_KEY},
        )
        assert r.status_code == 422

    def test_create_document_missing_content_returns_422(self, client):
        r = client.post(
            f"/api/v1/tenants/{ALPHA_TENANT}/documents",
            json={"title": "Title only"},
            headers={"X-API-Key": ALPHA_KEY},
        )
        assert r.status_code == 422

    def test_create_document_empty_title_returns_422(self, client):
        r = client.post(
            f"/api/v1/tenants/{ALPHA_TENANT}/documents",
            json={"title": "", "content": "Content"},
            headers={"X-API-Key": ALPHA_KEY},
        )
        assert r.status_code == 422

    def test_create_document_too_many_tags_returns_422(self, client):
        r = client.post(
            f"/api/v1/tenants/{ALPHA_TENANT}/documents",
            json={"title": "T", "content": "C", "tags": [str(i) for i in range(25)]},
            headers={"X-API-Key": ALPHA_KEY},
        )
        assert r.status_code == 422

    def test_create_document_normalises_tags(self, client):
        r = client.post(
            f"/api/v1/tenants/{ALPHA_TENANT}/documents",
            json={"title": "T", "content": "C", "tags": ["  UPPER  ", "lower"]},
            headers={"X-API-Key": ALPHA_KEY},
        )
        assert r.status_code == 201

    def test_document_ids_are_unique(self, client):
        ids = set()
        for i in range(5):
            r = client.post(
                f"/api/v1/tenants/{ALPHA_TENANT}/documents",
                json={"title": f"Doc {i}", "content": "Content"},
                headers={"X-API-Key": ALPHA_KEY},
            )
            assert r.status_code == 201
            ids.add(r.json()["id"])
        assert len(ids) == 5


# ─── Search ───────────────────────────────────────────────────────────────────

class TestSearch:
    def _ingest(self, client, tenant_id, api_key, title, content, tags=None):
        r = client.post(
            f"/api/v1/tenants/{tenant_id}/documents",
            json={"title": title, "content": content, "tags": tags or []},
            headers={"X-API-Key": api_key},
        )
        assert r.status_code == 201, r.text
        return r.json()["id"]

    def test_search_returns_matching_documents(self, client):
        self._ingest(client, ALPHA_TENANT, ALPHA_KEY, "Python Tutorial", "Learn python programming basics")
        self._ingest(client, ALPHA_TENANT, ALPHA_KEY, "Java Guide", "Enterprise java development")

        r = client.get(
            f"/api/v1/tenants/{ALPHA_TENANT}/documents/search?q=python",
            headers={"X-API-Key": ALPHA_KEY},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 1
        titles = [res["title"] for res in body["results"]]
        assert "Python Tutorial" in titles

    def test_search_tenant_isolation(self, client):
        """Documents ingested by Alpha must NOT appear in Beta's search."""
        self._ingest(client, ALPHA_TENANT, ALPHA_KEY, "Secret Alpha Doc", "confidential alpha data")

        r = client.get(
            f"/api/v1/tenants/{BETA_TENANT}/documents/search?q=alpha",
            headers={"X-API-Key": BETA_KEY},
        )
        assert r.status_code == 200
        assert r.json()["total"] == 0

    def test_search_returns_relevance_scores(self, client):
        self._ingest(client, ALPHA_TENANT, ALPHA_KEY, "Cats", "cats cats cats everywhere")
        r = client.get(
            f"/api/v1/tenants/{ALPHA_TENANT}/documents/search?q=cats",
            headers={"X-API-Key": ALPHA_KEY},
        )
        results = r.json()["results"]
        assert len(results) > 0
        assert results[0]["relevance_score"] >= 0

    def test_search_pagination(self, client):
        for i in range(5):
            self._ingest(client, ALPHA_TENANT, ALPHA_KEY, f"Doc {i}", f"keyword content item {i}")

        r1 = client.get(
            f"/api/v1/tenants/{ALPHA_TENANT}/documents/search?q=keyword&limit=2&offset=0",
            headers={"X-API-Key": ALPHA_KEY},
        )
        r2 = client.get(
            f"/api/v1/tenants/{ALPHA_TENANT}/documents/search?q=keyword&limit=2&offset=2",
            headers={"X-API-Key": ALPHA_KEY},
        )
        assert r1.status_code == 200
        assert r2.status_code == 200
        ids1 = {d["id"] for d in r1.json()["results"]}
        ids2 = {d["id"] for d in r2.json()["results"]}
        assert ids1.isdisjoint(ids2), "Paginated pages must not overlap"

    def test_search_no_results(self, client):
        r = client.get(
            f"/api/v1/tenants/{ALPHA_TENANT}/documents/search?q=xyznotfound",
            headers={"X-API-Key": ALPHA_KEY},
        )
        assert r.status_code == 200
        assert r.json()["total"] == 0
        assert r.json()["results"] == []

    def test_search_missing_query_returns_422(self, client):
        r = client.get(
            f"/api/v1/tenants/{ALPHA_TENANT}/documents/search",
            headers={"X-API-Key": ALPHA_KEY},
        )
        assert r.status_code == 422

    def test_search_content_snippet_max_200_chars(self, client):
        long_content = "word " * 200  # 1000 chars
        self._ingest(client, ALPHA_TENANT, ALPHA_KEY, "Long Doc", long_content)
        r = client.get(
            f"/api/v1/tenants/{ALPHA_TENANT}/documents/search?q=word",
            headers={"X-API-Key": ALPHA_KEY},
        )
        for result in r.json()["results"]:
            assert len(result["content_snippet"]) <= 200


# ─── Metrics ─────────────────────────────────────────────────────────────────

class TestMetrics:
    def test_metrics_endpoint_returns_200(self, client):
        r = client.get("/api/v1/metrics")
        assert r.status_code == 200

    def test_metrics_includes_uptime(self, client):
        body = client.get("/api/v1/metrics").json()
        assert "uptime_seconds" in body
        assert body["uptime_seconds"] >= 0

    def test_metrics_includes_document_count(self, client):
        # Ingest a doc
        client.post(
            f"/api/v1/tenants/{ALPHA_TENANT}/documents",
            json={"title": "T", "content": "C"},
            headers={"X-API-Key": ALPHA_KEY},
        )
        body = client.get("/api/v1/metrics").json()
        tenant_data = {t["tenant_id"]: t for t in body["tenants"]}
        if ALPHA_TENANT in tenant_data:
            assert tenant_data[ALPHA_TENANT]["document_count"] >= 1

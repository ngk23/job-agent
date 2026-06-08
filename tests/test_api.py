"""
Unit tests for the /api/mark-applied Flask endpoint.
Tests that the route handles auth, validation, marking, and duplicates correctly.
"""

import json
import os
import pytest
import tempfile
from pathlib import Path

# Set DATA_DIR before any agent module imports so DB_PATH picks it up
_tmp_data_dir = tempfile.mkdtemp()
os.environ["DATA_DIR"] = _tmp_data_dir

from agent.config import AppConfig
from agent.dashboard import create_dashboard_app


# Clean up temp directory on exit
import atexit
import shutil
atexit.register(shutil.rmtree, _tmp_data_dir, ignore_errors=True)


@pytest.fixture
def app():
    """Create a Flask test app with a temporary data directory."""
    config = AppConfig(data_dir=_tmp_data_dir)
    app = create_dashboard_app(config)
    app.config["TESTING"] = True
    app.config["SERVER_NAME"] = "localhost"
    yield app


@pytest.fixture
def client(app):
    """Create a Flask test client."""
    with app.test_client() as client:
        yield client


def _login(client, app):
    """Helper: inject a user session and ensure the admin user exists."""
    from agent.auth import ensure_admin_exists
    from agent.database import get_user_by_email

    with app.app_context():
        ensure_admin_exists()
        user = get_user_by_email("admin@admin.com")
        if not user:
            from agent.database import get_db
            from werkzeug.security import generate_password_hash
            db = get_db()
            db.execute(
                "INSERT OR IGNORE INTO users (email, password_hash, name, role, status) "
                "VALUES (?, ?, ?, ?, ?)",
                ("admin@admin.com", generate_password_hash("testpass123"), "Admin", "admin", "active"),
            )
            db.commit()
            user = get_user_by_email("admin@admin.com")

    with client.session_transaction() as sess:
        sess["user_id"] = user["id"]
        sess["user_name"] = user["name"]
        sess["user_role"] = user["role"]
        sess["user_email"] = user["email"]

    return user


class TestMarkAppliedEndpoint:
    """Tests for the POST /api/mark-applied endpoint."""

    def test_unauthenticated_returns_401(self, client):
        """Request without a session should return 401."""
        resp = client.post(
            "/api/mark-applied",
            data=json.dumps({"url": "https://example.com/job/1"}),
            content_type="application/json",
        )
        assert resp.status_code == 401
        data = resp.get_json()
        assert data is not None
        assert "error" in data
        assert "Authentication required" in data["error"]

    def test_missing_url_returns_400(self, client, app):
        """Request without a url field should return 400."""
        _login(client, app)
        resp = client.post(
            "/api/mark-applied",
            data=json.dumps({}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["status"] == "error"
        assert "No URL provided" in data["error"]

    def test_empty_url_returns_400(self, client, app):
        """Request with an empty/whitespace URL should return 400."""
        _login(client, app)
        resp = client.post(
            "/api/mark-applied",
            data=json.dumps({"url": "   "}),
            content_type="application/json",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["status"] == "error"
        assert "Empty URL" in data["error"]

    def test_non_json_body_returns_400(self, client, app):
        """Request with non-JSON content should return 400."""
        _login(client, app)
        resp = client.post(
            "/api/mark-applied",
            data="not json",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_valid_url_marks_as_applied(self, client, app):
        """Valid request with a new URL should return ok and newly_marked=True."""
        _login(client, app)
        resp = client.post(
            "/api/mark-applied",
            data=json.dumps({"url": "https://example.com/job/new"}),
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "ok"
        assert data["newly_marked"] is True

    def test_duplicate_url_returns_false(self, client, app):
        """Marking the same URL twice should return newly_marked=False."""
        user = _login(client, app)
        url = "https://example.com/job/duplicate"

        # First request
        resp1 = client.post(
            "/api/mark-applied",
            data=json.dumps({"url": url}),
            content_type="application/json",
        )
        assert resp1.status_code == 200
        assert resp1.get_json()["newly_marked"] is True

        # Second request (same URL)
        resp2 = client.post(
            "/api/mark-applied",
            data=json.dumps({"url": url}),
            content_type="application/json",
        )
        assert resp2.status_code == 200
        data2 = resp2.get_json()
        assert data2["status"] == "ok"
        assert data2["newly_marked"] is False

    def test_url_persists_in_database(self, client, app):
        """After marking, the URL should be stored in the database."""
        user = _login(client, app)
        url = "https://example.com/job/persist-test"

        resp = client.post(
            "/api/mark-applied",
            data=json.dumps({"url": url}),
            content_type="application/json",
        )
        assert resp.status_code == 200

        # Verify the URL is in the database
        from agent.database import get_db
        db = get_db()
        cursor = db.execute(
            "SELECT url FROM applied_jobs WHERE user_id = ? AND url = ?",
            (user["id"], url),
        )
        row = cursor.fetchone()
        assert row is not None
        assert row[0] == url

    def test_multiple_urls_all_independently_marked(self, client, app):
        """Multiple different URLs should all be markable independently."""
        user = _login(client, app)
        urls = [
            "https://example.com/job/a",
            "https://example.com/job/b",
            "https://example.com/job/c",
        ]

        for url in urls:
            resp = client.post(
                "/api/mark-applied",
                data=json.dumps({"url": url}),
                content_type="application/json",
            )
            assert resp.status_code == 200
            assert resp.get_json()["newly_marked"] is True, f"Failed for url: {url}"

        # Verify each URL is in the database for this user
        from agent.database import get_db
        db = get_db()
        for url in urls:
            cursor = db.execute(
                "SELECT COUNT(*) FROM applied_jobs WHERE user_id = ? AND url = ?",
                (user["id"], url),
            )
            assert cursor.fetchone()[0] == 1, f"URL not persisted: {url}"

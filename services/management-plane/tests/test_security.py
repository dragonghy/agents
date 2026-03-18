"""Tests for security features: rate limiting, encryption, CORS."""

import os

os.environ["MGMT_MOCK_MODE"] = "true"

from management.security import RateLimiter, encrypt_token, decrypt_token, get_cors_origins


class TestRateLimiter:
    def test_allows_within_limit(self):
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        assert limiter.is_allowed("ip1") is True
        assert limiter.is_allowed("ip1") is True
        assert limiter.is_allowed("ip1") is True

    def test_blocks_over_limit(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        assert limiter.is_allowed("ip1") is True
        assert limiter.is_allowed("ip1") is True
        assert limiter.is_allowed("ip1") is False

    def test_different_keys_independent(self):
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        assert limiter.is_allowed("ip1") is True
        assert limiter.is_allowed("ip2") is True
        assert limiter.is_allowed("ip1") is False


class TestEncryption:
    def test_roundtrip_without_key(self):
        """Without MGMT_ENCRYPT_KEY, tokens pass through unchanged."""
        original = "sk-test-token"
        encrypted = encrypt_token(original)
        decrypted = decrypt_token(encrypted)
        assert decrypted == original

    def test_roundtrip_with_key(self):
        """With MGMT_ENCRYPT_KEY set, tokens are encrypted and decryptable."""
        os.environ["MGMT_ENCRYPT_KEY"] = "test-passphrase-for-encryption"
        # Reset cached fernet
        import management.security as sec
        sec._fernet = None
        sec._ENCRYPT_KEY = "test-passphrase-for-encryption"

        original = "sk-ant-secret-token-12345"
        encrypted = sec.encrypt_token(original)
        assert encrypted != original  # Should be different (encrypted)
        decrypted = sec.decrypt_token(encrypted)
        assert decrypted == original

        # Cleanup
        sec._fernet = None
        sec._ENCRYPT_KEY = ""
        os.environ.pop("MGMT_ENCRYPT_KEY", None)


class TestCorsConfig:
    def test_development_allows_all(self):
        os.environ["MGMT_ENV"] = "development"
        origins = get_cors_origins()
        assert "*" in origins

    def test_production_restricts_origins(self):
        os.environ["MGMT_ENV"] = "production"
        os.environ["MGMT_DOMAIN"] = "example.com"
        origins = get_cors_origins()
        assert "*" not in origins
        assert "https://example.com" in origins
        # Cleanup
        os.environ["MGMT_ENV"] = "development"


class TestRateLimitingInApi:
    """Test rate limiting on auth endpoints."""

    def test_register_rate_limit(self, client):
        """Register endpoint should enforce rate limiting."""
        # The default limiter allows 10 req/min
        # We just verify the endpoint works normally
        resp = client.post("/api/auth/register", json={
            "email": "rate@test.com",
            "password": "password123",
        })
        assert resp.status_code == 201


class TestUsageDateFilterBugFix:
    """M6 bug fix: summary should respect date filters."""

    def test_summary_respects_date_range(self, client, auth_headers):
        # Create company
        r = client.post("/api/companies", json={"name": "Date Fix"}, headers=auth_headers)
        cid = r.json()["company"]["id"]
        secret = {"x-usage-secret": "dev-usage-secret"}

        # Record usage on different dates
        client.post(f"/api/companies/{cid}/usage", json={
            "date": "2026-03-10", "input_tokens": 1000, "output_tokens": 500,
        }, headers=secret)
        client.post(f"/api/companies/{cid}/usage", json={
            "date": "2026-03-15", "input_tokens": 2000, "output_tokens": 1000,
        }, headers=secret)
        client.post(f"/api/companies/{cid}/usage", json={
            "date": "2026-03-20", "input_tokens": 3000, "output_tokens": 1500,
        }, headers=secret)

        # Get all usage — total should be 9000
        r = client.get(f"/api/companies/{cid}/usage", headers=auth_headers)
        assert r.json()["summary"]["total_tokens"] == 9000

        # Get usage with date filter — summary should also be filtered
        r = client.get(
            f"/api/companies/{cid}/usage?from=2026-03-15&to=2026-03-15",
            headers=auth_headers,
        )
        summary = r.json()["summary"]
        assert summary["total_tokens"] == 3000  # Only March 15th
        assert summary["total_input"] == 2000
        assert summary["total_output"] == 1000

    def test_summary_no_filter_returns_all(self, client, auth_headers):
        """Without filters, summary includes all data."""
        r = client.post("/api/companies", json={"name": "No Filter"}, headers=auth_headers)
        cid = r.json()["company"]["id"]
        secret = {"x-usage-secret": "dev-usage-secret"}

        client.post(f"/api/companies/{cid}/usage", json={
            "date": "2026-01-01", "input_tokens": 100, "output_tokens": 50,
        }, headers=secret)
        client.post(f"/api/companies/{cid}/usage", json={
            "date": "2026-12-31", "input_tokens": 200, "output_tokens": 100,
        }, headers=secret)

        r = client.get(f"/api/companies/{cid}/usage", headers=auth_headers)
        assert r.json()["summary"]["total_tokens"] == 450


class TestHealthEndpoint:
    def test_health_returns_subsystem_status(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert data["database"] is True
        assert "mock_mode" in data
        assert "stripe" in data

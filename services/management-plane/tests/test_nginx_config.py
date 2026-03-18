"""Tests for nginx_config module."""

import os
from pathlib import Path

os.environ["MGMT_MOCK_MODE"] = "true"

from management.nginx_config import (
    generate_instance_config,
    get_instance_url,
    MGMT_DOMAIN,
)


class TestGenerateInstanceConfig:
    def test_contains_server_name(self):
        config = generate_instance_config("alice", 10001)
        assert f"alice.{MGMT_DOMAIN}" in config

    def test_contains_proxy_pass_port(self):
        config = generate_instance_config("bob", 10042)
        assert "proxy_pass http://host.docker.internal:10042" in config

    def test_contains_ssl_directives(self):
        config = generate_instance_config("test", 10000)
        assert "ssl_certificate" in config
        assert "ssl_certificate_key" in config

    def test_contains_websocket_headers(self):
        config = generate_instance_config("test", 10000)
        assert "Upgrade" in config
        assert "Connection" in config

    def test_valid_nginx_server_block(self):
        config = generate_instance_config("my-co", 10005)
        assert config.strip().startswith("#")
        assert "server {" in config
        assert "location / {" in config


class TestGetInstanceUrl:
    def test_returns_https_url(self):
        url = get_instance_url("alice")
        assert url == f"https://alice.{MGMT_DOMAIN}"

    def test_slug_in_url(self):
        url = get_instance_url("my-startup")
        assert "my-startup" in url


class TestUpdateNginxConfig:
    """Test update/remove in mock mode (no filesystem or nginx changes)."""

    def test_update_mock_mode(self):
        import asyncio
        from management.nginx_config import update_nginx_config
        # Should not raise in mock mode
        asyncio.get_event_loop().run_until_complete(
            update_nginx_config("test-slug", 10001)
        )

    def test_remove_mock_mode(self):
        import asyncio
        from management.nginx_config import remove_nginx_config
        # Should not raise in mock mode
        asyncio.get_event_loop().run_until_complete(
            remove_nginx_config("test-slug")
        )


class TestUpdateNginxConfigRealMode:
    """Test update/remove with real filesystem writes (but no nginx binary)."""

    def test_writes_config_file(self, tmp_path):
        import asyncio
        from unittest.mock import patch, AsyncMock
        from management.nginx_config import update_nginx_config

        with patch("management.nginx_config.MOCK_MODE", False), \
             patch("management.nginx_config.NGINX_CONF_DIR", tmp_path), \
             patch("management.nginx_config._reload_nginx", new_callable=AsyncMock):
            asyncio.get_event_loop().run_until_complete(
                update_nginx_config("test-co", 10010)
            )

        conf_file = tmp_path / "test-co.conf"
        assert conf_file.exists()
        content = conf_file.read_text()
        assert "test-co" in content
        assert "10010" in content

    def test_removes_config_file(self, tmp_path):
        import asyncio
        from unittest.mock import patch, AsyncMock
        from management.nginx_config import remove_nginx_config

        # Create a config file first
        conf_file = tmp_path / "test-co.conf"
        conf_file.write_text("dummy config")

        with patch("management.nginx_config.MOCK_MODE", False), \
             patch("management.nginx_config.NGINX_CONF_DIR", tmp_path), \
             patch("management.nginx_config._reload_nginx", new_callable=AsyncMock):
            asyncio.get_event_loop().run_until_complete(
                remove_nginx_config("test-co")
            )

        assert not conf_file.exists()


class TestCompanyUrlInApi:
    """Verify the url field appears in API responses."""

    def test_create_company_has_url(self, client, auth_headers):
        resp = client.post("/api/companies", json={
            "name": "URL Test Co",
            "template": "solo",
        }, headers=auth_headers)
        assert resp.status_code == 201
        company = resp.json()["company"]
        assert "url" in company
        assert company["slug"] in company["url"]
        assert company["url"].startswith("https://")

    def test_list_companies_has_url(self, client, auth_headers):
        client.post("/api/companies", json={"name": "List URL Co"}, headers=auth_headers)
        resp = client.get("/api/companies", headers=auth_headers)
        assert resp.status_code == 200
        for c in resp.json()["companies"]:
            assert "url" in c

    def test_get_company_has_url(self, client, auth_headers):
        create_resp = client.post("/api/companies", json={"name": "Get URL Co"}, headers=auth_headers)
        company_id = create_resp.json()["company"]["id"]
        resp = client.get(f"/api/companies/{company_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert "url" in resp.json()["company"]

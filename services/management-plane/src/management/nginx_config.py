"""Nginx reverse-proxy configuration management.

Generates per-instance Nginx server-block configs and triggers
hot-reload so that each company slug gets its own subdomain
(e.g. alice.agenthub.local -> proxy to the instance port).

Skipped entirely when MOCK_MODE is enabled.
"""

import asyncio
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

NGINX_CONF_DIR = Path(os.environ.get("MGMT_NGINX_CONF_DIR", "/etc/nginx/conf.d"))
MGMT_DOMAIN = os.environ.get("MGMT_DOMAIN", "agenthub.local")
MOCK_MODE = os.environ.get("MGMT_MOCK_MODE", "true").lower() in ("true", "1", "yes")


def generate_instance_config(slug: str, port: int) -> str:
    """Generate an Nginx server block for a single instance.

    The block listens on 80/443 for ``<slug>.<MGMT_DOMAIN>`` and
    reverse-proxies to the instance daemon on *host.docker.internal:<port>*.
    """
    return f"""# Auto-generated for instance: {slug}
server {{
    listen 80;
    listen 443 ssl;
    server_name {slug}.{MGMT_DOMAIN};

    ssl_certificate /etc/nginx/certs/wildcard.crt;
    ssl_certificate_key /etc/nginx/certs/wildcard.key;

    location / {{
        proxy_pass http://host.docker.internal:{port};
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }}
}}
"""


async def update_nginx_config(slug: str, port: int) -> None:
    """Write (or overwrite) the per-instance config and reload Nginx."""
    if MOCK_MODE:
        logger.info("[MOCK] Would update Nginx config for %s -> port %d", slug, port)
        return

    conf_path = NGINX_CONF_DIR / f"{slug}.conf"
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    conf_path.write_text(generate_instance_config(slug, port))
    logger.info("Wrote Nginx config: %s", conf_path)
    await _reload_nginx()


async def remove_nginx_config(slug: str) -> None:
    """Remove the per-instance config and reload Nginx."""
    if MOCK_MODE:
        logger.info("[MOCK] Would remove Nginx config for %s", slug)
        return

    conf_path = NGINX_CONF_DIR / f"{slug}.conf"
    if conf_path.exists():
        conf_path.unlink()
        logger.info("Removed Nginx config: %s", conf_path)
    await _reload_nginx()


async def _reload_nginx() -> None:
    """Send a reload signal to the Nginx process."""
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            ["nginx", "-s", "reload"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if proc.returncode != 0:
            logger.warning("Nginx reload failed: %s", proc.stderr)
        else:
            logger.info("Nginx reloaded successfully")
    except FileNotFoundError:
        logger.warning("nginx binary not found — skipping reload")
    except Exception as e:
        logger.warning("Nginx reload error: %s", e)


def get_instance_url(slug: str) -> str:
    """Return the public URL for an instance."""
    return f"https://{slug}.{MGMT_DOMAIN}"

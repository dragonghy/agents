"""Instance lifecycle manager — Docker Compose operations.

When MOCK_MODE is enabled (default for development without Docker),
operations are simulated with realistic delays and state transitions.
"""

import asyncio
import logging
import os
import shutil

from . import models

logger = logging.getLogger(__name__)

# Enable mock mode when Docker is not available
MOCK_MODE = os.environ.get("MGMT_MOCK_MODE", "true").lower() in ("true", "1", "yes")

# Port allocation range
PORT_START = int(os.environ.get("MGMT_PORT_START", "10000"))
PORT_MAX = int(os.environ.get("MGMT_PORT_MAX", "10999"))


async def _allocate_port() -> int:
    """Find the next available port."""
    from .db import get_db

    db = await get_db()
    cursor = await db.execute(
        "SELECT port FROM companies WHERE port IS NOT NULL ORDER BY port DESC LIMIT 1"
    )
    row = await cursor.fetchone()
    if row and row["port"]:
        next_port = row["port"] + 1
    else:
        next_port = PORT_START

    if next_port > PORT_MAX:
        raise RuntimeError("No available ports")
    return next_port


async def create_instance(company_id: str) -> dict:
    """Create and start a new Agent Hub instance for a company.

    In mock mode: simulates the creation with a short delay.
    In real mode: generates config, writes files, runs docker compose up.
    """
    company = await models.get_company(company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")

    port = await _allocate_port()

    if MOCK_MODE:
        logger.info("[MOCK] Creating instance for %s on port %d", company["slug"], port)
        await asyncio.sleep(0.5)  # Simulate creation delay
        await models.update_company(company_id, status="running", port=port)
        await models.log_event(company_id, "started", {"port": port, "mock": True})
        return {"status": "running", "port": port, "mock": True}

    # Real Docker Compose deployment would go here
    # For now, just update status
    await models.update_company(company_id, status="running", port=port)
    await models.log_event(company_id, "started", {"port": port})
    return {"status": "running", "port": port}


async def start_instance(company_id: str) -> dict:
    """Start a stopped instance."""
    company = await models.get_company(company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")
    if company["status"] not in ("stopped", "error"):
        raise ValueError(f"Cannot start instance in '{company['status']}' state")

    if MOCK_MODE:
        logger.info("[MOCK] Starting instance %s", company["slug"])
        await asyncio.sleep(0.3)
        await models.update_company(company_id, status="running")
        await models.log_event(company_id, "started", {"mock": True})
        return {"status": "running"}

    await models.update_company(company_id, status="running")
    await models.log_event(company_id, "started")
    return {"status": "running"}


async def stop_instance(company_id: str) -> dict:
    """Stop a running instance."""
    company = await models.get_company(company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")
    if company["status"] not in ("running", "paused"):
        raise ValueError(f"Cannot stop instance in '{company['status']}' state")

    if MOCK_MODE:
        logger.info("[MOCK] Stopping instance %s", company["slug"])
        await asyncio.sleep(0.3)
        await models.update_company(company_id, status="stopped")
        await models.log_event(company_id, "stopped", {"mock": True})
        return {"status": "stopped"}

    await models.update_company(company_id, status="stopped")
    await models.log_event(company_id, "stopped")
    return {"status": "stopped"}


async def pause_instance(company_id: str) -> dict:
    """Pause a running instance."""
    company = await models.get_company(company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")
    if company["status"] != "running":
        raise ValueError(f"Cannot pause instance in '{company['status']}' state")

    if MOCK_MODE:
        logger.info("[MOCK] Pausing instance %s", company["slug"])
        await asyncio.sleep(0.2)
        await models.update_company(company_id, status="paused")
        await models.log_event(company_id, "paused", {"mock": True})
        return {"status": "paused"}

    await models.update_company(company_id, status="paused")
    await models.log_event(company_id, "paused")
    return {"status": "paused"}


async def resume_instance(company_id: str) -> dict:
    """Resume a paused instance."""
    company = await models.get_company(company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")
    if company["status"] != "paused":
        raise ValueError(f"Cannot resume instance in '{company['status']}' state")

    if MOCK_MODE:
        logger.info("[MOCK] Resuming instance %s", company["slug"])
        await asyncio.sleep(0.2)
        await models.update_company(company_id, status="running")
        await models.log_event(company_id, "resumed", {"mock": True})
        return {"status": "running"}

    await models.update_company(company_id, status="running")
    await models.log_event(company_id, "resumed")
    return {"status": "running"}


async def delete_instance(company_id: str) -> dict:
    """Delete an instance and clean up resources."""
    company = await models.get_company(company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")

    # Stop first if running
    if company["status"] in ("running", "paused"):
        await stop_instance(company_id)

    if MOCK_MODE:
        logger.info("[MOCK] Deleting instance %s", company["slug"])
        await asyncio.sleep(0.2)

    await models.delete_company(company_id)
    return {"status": "deleted"}


async def get_instance_status(company_id: str) -> dict:
    """Get the current status of an instance."""
    company = await models.get_company(company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")

    return {
        "status": company["status"],
        "port": company.get("port"),
        "mock_mode": MOCK_MODE,
    }

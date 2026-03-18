"""Instance lifecycle manager — Docker Compose operations.

When MOCK_MODE is enabled (default for development without Docker),
operations are simulated with realistic delays and state transitions.

When MOCK_MODE is disabled, real Docker Compose commands are executed
to manage Agent Hub instances.
"""

import asyncio
import json
import logging
import os
import shutil
import subprocess
from pathlib import Path
from textwrap import dedent

import yaml

from . import models

logger = logging.getLogger(__name__)

# Enable mock mode when Docker is not available
MOCK_MODE = os.environ.get("MGMT_MOCK_MODE", "true").lower() in ("true", "1", "yes")

# Port allocation range
PORT_START = int(os.environ.get("MGMT_PORT_START", "10000"))
PORT_MAX = int(os.environ.get("MGMT_PORT_MAX", "10999"))

# Instance root directory
INSTANCES_DIR = Path(os.environ.get("MGMT_INSTANCES_DIR", "/tmp/aghub-instances"))

# Path to the repo root (for docker build context)
REPO_ROOT = Path(os.environ.get("MGMT_REPO_ROOT", str(Path(__file__).resolve().parents[4])))

# ── Agent team templates ──

TEAM_TEMPLATES: dict[str, dict] = {
    "solo": {
        "agents": {
            "product": {
                "template": "product",
                "role": "Product Manager",
                "description": "Requirements analysis, task distribution, and acceptance",
                "dispatchable": True,
            },
            "dev": {
                "template": "dev",
                "role": "Developer",
                "description": "Technical design, implementation, and testing",
                "dispatchable": True,
            },
            "qa": {
                "template": "qa",
                "role": "QA Engineer",
                "description": "E2E testing and requirements verification",
                "dispatchable": True,
            },
        },
    },
    "standard": {
        "agents": {
            "product": {
                "template": "product",
                "role": "Product Manager",
                "description": "Requirements analysis, task distribution, and acceptance",
                "dispatchable": True,
            },
            "dev-1": {
                "template": "dev",
                "role": "Developer",
                "description": "Technical design, implementation, and testing",
                "dispatchable": True,
            },
            "dev-2": {
                "template": "dev",
                "role": "Developer",
                "description": "Technical design, implementation, and testing",
                "dispatchable": True,
            },
            "qa": {
                "template": "qa",
                "role": "QA Engineer",
                "description": "E2E testing and requirements verification",
                "dispatchable": True,
            },
            "user": {
                "template": "user",
                "role": "User Tester",
                "description": "User experience testing from end-user perspective",
                "dispatchable": True,
            },
        },
    },
    "full": {
        "agents": {
            "admin": {
                "template": "admin",
                "role": "Admin",
                "description": "Global configuration, skill management, agent restarts",
                "dispatchable": True,
            },
            "product": {
                "template": "product",
                "role": "Product Manager",
                "description": "Requirements analysis, task distribution, and acceptance",
                "dispatchable": True,
            },
            "dev-1": {
                "template": "dev",
                "role": "Developer",
                "description": "Technical design, implementation, and testing",
                "dispatchable": True,
            },
            "dev-2": {
                "template": "dev",
                "role": "Developer",
                "description": "Technical design, implementation, and testing",
                "dispatchable": True,
            },
            "dev-3": {
                "template": "dev",
                "role": "Developer",
                "description": "Technical design, implementation, and testing",
                "dispatchable": True,
            },
            "qa-1": {
                "template": "qa",
                "role": "QA Engineer",
                "description": "E2E testing and requirements verification",
                "dispatchable": True,
            },
            "qa-2": {
                "template": "qa",
                "role": "QA Engineer",
                "description": "E2E testing and requirements verification",
                "dispatchable": True,
            },
            "user": {
                "template": "user",
                "role": "User Tester",
                "description": "User experience testing from end-user perspective",
                "dispatchable": True,
            },
        },
    },
}


def _generate_agents_yaml(template: str, daemon_port: int = 8765) -> dict:
    """Generate agents.yaml config for a given team template."""
    team = TEAM_TEMPLATES.get(template, TEAM_TEMPLATES["standard"])

    config = {
        "tmux_session": "agents",
        "project_id": 1,
        "daemon": {
            "host": "daemon",
            "port": daemon_port,
        },
        "mcp_servers": {
            "agents": {
                "command": "uv",
                "args": [
                    "run",
                    "--directory",
                    "/app/services/agents-mcp",
                    "agents-mcp-proxy",
                ],
            },
        },
        "agents": team["agents"],
    }
    return config


def _generate_compose_yaml(slug: str, web_port: int) -> str:
    """Generate docker-compose.yml for an instance."""
    return dedent(f"""\
        # Auto-generated by Management Plane for instance: {slug}
        # Project: aghub-{slug}

        services:
          daemon:
            build:
              context: {REPO_ROOT}/services/agents-mcp
            ports:
              - "${{WEB_PORT:-{web_port}}}:8765"
            volumes:
              - agents-data:/config
              - ./agents.yaml:/config/agents.yaml:ro
            env_file:
              - path: .env
                required: false
            restart: unless-stopped

          agents:
            build:
              context: {REPO_ROOT}
              dockerfile: docker/agent/Dockerfile
            environment:
              - CLAUDE_CODE_OAUTH_TOKEN=${{CLAUDE_CODE_OAUTH_TOKEN:-}}
              - ANTHROPIC_API_KEY=${{ANTHROPIC_API_KEY:-}}
              - DAEMON_HOST=daemon
              - SKIP_DAEMON=1
            volumes:
              - .:/app
            depends_on:
              daemon:
                condition: service_started
            profiles:
              - agents
            restart: unless-stopped

        volumes:
          agents-data:
    """)


def _generate_env(auth_type: str | None, auth_token: str | None, web_port: int) -> str:
    """Generate .env file content for an instance."""
    lines = [f"WEB_PORT={web_port}"]
    if auth_token:
        if auth_type == "oauth_token":
            lines.append(f"CLAUDE_CODE_OAUTH_TOKEN={auth_token}")
        elif auth_type == "api_key":
            lines.append(f"ANTHROPIC_API_KEY={auth_token}")
    return "\n".join(lines) + "\n"


def _get_instance_dir(slug: str) -> Path:
    """Get the instance directory path."""
    return INSTANCES_DIR / slug


def _get_project_name(slug: str) -> str:
    """Get the Docker Compose project name for an instance."""
    return f"aghub-{slug}"


async def _run_compose(slug: str, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a docker compose command for an instance."""
    instance_dir = _get_instance_dir(slug)
    project_name = _get_project_name(slug)

    cmd = [
        "docker", "compose",
        "--project-name", project_name,
        "--project-directory", str(instance_dir),
        *args,
    ]

    logger.info("Running: %s", " ".join(cmd))

    proc = await asyncio.to_thread(
        subprocess.run,
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if proc.returncode != 0:
        logger.error("Docker compose failed: %s", proc.stderr)
    else:
        logger.info("Docker compose succeeded: %s", proc.stdout[:200] if proc.stdout else "(no output)")

    return proc


async def _get_raw_company(company_id: str) -> dict:
    """Get company with auth_token (not stripped). For internal use only."""
    from .db import get_db
    db = await get_db()
    cursor = await db.execute("SELECT * FROM companies WHERE id = ?", (company_id,))
    row = await cursor.fetchone()
    if row is None:
        raise ValueError(f"Company {company_id} not found")
    return dict(row)


# ── Port allocation ──


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


# ── Lifecycle operations ──


async def create_instance(company_id: str) -> dict:
    """Create and start a new Agent Hub instance for a company.

    In mock mode: simulates the creation with a short delay.
    In real mode: generates config files, creates instance directory,
    and runs docker compose up.
    """
    company = await models.get_company(company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")

    port = await _allocate_port()

    if MOCK_MODE:
        logger.info("[MOCK] Creating instance for %s on port %d", company["slug"], port)
        await asyncio.sleep(0.5)
        await models.update_company(company_id, status="running", port=port)
        await models.log_event(company_id, "started", {"port": port, "mock": True})
        return {"status": "running", "port": port, "mock": True}

    slug = company["slug"]
    template = company.get("template", "standard")
    instance_dir = _get_instance_dir(slug)

    # Get auth_token from raw company (not stripped)
    raw_company = await _get_raw_company(company_id)
    auth_type = raw_company.get("auth_type")
    auth_token = raw_company.get("auth_token")

    # 1. Create instance directory
    instance_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Created instance directory: %s", instance_dir)

    # 2. Generate and write agents.yaml
    agents_config = _generate_agents_yaml(template)
    with open(instance_dir / "agents.yaml", "w") as f:
        yaml.dump(agents_config, f, default_flow_style=False, allow_unicode=True)
    logger.info("Wrote agents.yaml for template '%s'", template)

    # 3. Generate and write docker-compose.yml
    compose_content = _generate_compose_yaml(slug, port)
    with open(instance_dir / "docker-compose.yml", "w") as f:
        f.write(compose_content)
    logger.info("Wrote docker-compose.yml with port %d", port)

    # 4. Generate and write .env
    env_content = _generate_env(auth_type, auth_token, port)
    with open(instance_dir / ".env", "w") as f:
        f.write(env_content)
    logger.info("Wrote .env file")

    # 5. Run docker compose up (daemon only first, agents need auth token)
    await models.update_company(company_id, status="creating", port=port)
    try:
        proc = await _run_compose(slug, "up", "--build", "-d")
        if proc.returncode != 0:
            await models.update_company(company_id, status="error")
            await models.log_event(company_id, "error", {
                "stage": "docker_compose_up",
                "stderr": proc.stderr[:500],
            })
            return {"status": "error", "port": port, "error": proc.stderr[:500]}
    except subprocess.TimeoutExpired:
        await models.update_company(company_id, status="error")
        await models.log_event(company_id, "error", {"stage": "docker_compose_up", "reason": "timeout"})
        return {"status": "error", "port": port, "error": "Docker compose timed out"}

    # 6. Update status
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

    proc = await _run_compose(company["slug"], "up", "-d")
    if proc.returncode != 0:
        await models.log_event(company_id, "error", {"stage": "start", "stderr": proc.stderr[:500]})
        return {"status": "error", "error": proc.stderr[:500]}

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

    proc = await _run_compose(company["slug"], "down")
    if proc.returncode != 0:
        logger.warning("docker compose down failed: %s", proc.stderr)
        # Still mark as stopped — containers may already be gone

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

    proc = await _run_compose(company["slug"], "pause")
    if proc.returncode != 0:
        await models.log_event(company_id, "error", {"stage": "pause", "stderr": proc.stderr[:500]})
        return {"status": "error", "error": proc.stderr[:500]}

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

    proc = await _run_compose(company["slug"], "unpause")
    if proc.returncode != 0:
        await models.log_event(company_id, "error", {"stage": "resume", "stderr": proc.stderr[:500]})
        return {"status": "error", "error": proc.stderr[:500]}

    await models.update_company(company_id, status="running")
    await models.log_event(company_id, "resumed")
    return {"status": "running"}


async def delete_instance(company_id: str) -> dict:
    """Delete an instance and clean up resources."""
    company = await models.get_company(company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")

    slug = company["slug"]

    # Stop first if running
    if company["status"] in ("running", "paused"):
        await stop_instance(company_id)

    if MOCK_MODE:
        logger.info("[MOCK] Deleting instance %s", slug)
        await asyncio.sleep(0.2)
    else:
        # Remove containers and volumes
        await _run_compose(slug, "down", "-v")

        # Clean up instance directory
        instance_dir = _get_instance_dir(slug)
        if instance_dir.exists():
            shutil.rmtree(instance_dir)
            logger.info("Removed instance directory: %s", instance_dir)

    await models.delete_company(company_id)
    return {"status": "deleted"}


async def get_instance_status(company_id: str) -> dict:
    """Get the current status of an instance."""
    company = await models.get_company(company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")

    result = {
        "status": company["status"],
        "port": company.get("port"),
        "mock_mode": MOCK_MODE,
    }

    # In real mode, also check Docker container status
    if not MOCK_MODE and company["status"] == "running":
        try:
            proc = await _run_compose(
                company["slug"], "ps", "--format", "json", timeout=10
            )
            if proc.returncode == 0 and proc.stdout.strip():
                result["containers"] = proc.stdout.strip()
        except Exception:
            pass

    return result


async def get_instance_logs(company_id: str, tail: int = 100) -> str:
    """Get Docker Compose logs for an instance."""
    company = await models.get_company(company_id)
    if not company:
        raise ValueError(f"Company {company_id} not found")

    if MOCK_MODE:
        return "[MOCK MODE] No real container logs available."

    try:
        proc = await _run_compose(
            company["slug"], "logs", f"--tail={tail}", "--no-color", timeout=15
        )
        return proc.stdout or proc.stderr or "(no output)"
    except subprocess.TimeoutExpired:
        return "(log retrieval timed out)"
    except Exception as e:
        return f"(error retrieving logs: {e})"


# ── Health check ──


async def check_instance_health(company_id: str) -> dict:
    """Check health of a running instance by hitting its /api/v1/health endpoint."""
    company = await models.get_company(company_id)
    if not company or company["status"] != "running":
        return {"healthy": False, "reason": "not running"}

    port = company.get("port")
    if not port:
        return {"healthy": False, "reason": "no port assigned"}

    if MOCK_MODE:
        return {"healthy": True, "mock": True}

    import httpx

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"http://localhost:{port}/api/v1/health")
            if resp.status_code == 200:
                return {"healthy": True, "data": resp.json()}
            return {"healthy": False, "status_code": resp.status_code}
    except Exception as e:
        return {"healthy": False, "error": str(e)}


async def health_check_loop():
    """Background task that periodically checks all running instances.

    Runs every 60 seconds. After 3 consecutive failures, marks instance as error.
    """
    fail_counts: dict[str, int] = {}

    while True:
        await asyncio.sleep(60)

        try:
            from .db import get_db
            db = await get_db()
            cursor = await db.execute(
                "SELECT id, slug FROM companies WHERE status = 'running'"
            )
            rows = await cursor.fetchall()

            for row in rows:
                company_id = row["id"]
                result = await check_instance_health(company_id)

                if result.get("healthy"):
                    fail_counts.pop(company_id, None)
                else:
                    count = fail_counts.get(company_id, 0) + 1
                    fail_counts[company_id] = count
                    logger.warning(
                        "Health check failed for %s (%d/3): %s",
                        row["slug"], count, result,
                    )

                    if count >= 3:
                        logger.error("Instance %s failed 3 health checks, marking as error", row["slug"])
                        await models.update_company(company_id, status="error")
                        await models.log_event(company_id, "error", {
                            "reason": "health_check_failed",
                            "consecutive_failures": count,
                        })
                        fail_counts.pop(company_id, None)
        except Exception as e:
            logger.error("Health check loop error: %s", e)


# ── Utility ──


def get_template_info(template: str) -> dict:
    """Get info about a team template (for UI display)."""
    team = TEAM_TEMPLATES.get(template)
    if not team:
        return {"error": f"Unknown template: {template}"}
    return {
        "template": template,
        "agent_count": len(team["agents"]),
        "agents": [
            {"name": name, "role": agent.get("role", "")}
            for name, agent in team["agents"].items()
        ],
    }

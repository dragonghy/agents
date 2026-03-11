#!/usr/bin/env python3
"""E2E isolated test environment manager.

Creates and destroys isolated test environments for QA agents.
Each environment gets its own daemon port, Leantime project, and work directory.

Usage:
  python3 tests/e2e_env.py up      [--name NAME] [--port PORT] [--preset minimal|full]
  python3 tests/e2e_env.py down    --name NAME
  python3 tests/e2e_env.py list
  python3 tests/e2e_env.py archive <env-name> --name <showcase-name> [--force]
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRESETS_DIR = os.path.join(ROOT_DIR, "tests", "presets")
PROD_CONFIG = os.path.join(ROOT_DIR, "agents.yaml")

sys.path.insert(0, ROOT_DIR)
from config_utils import load_dotenv, resolve_env_vars
ENV_PREFIX = "/tmp/agents-e2e-"
PORT_RANGE = range(8770, 8800)
SHOWCASE_DIR = os.path.join(ROOT_DIR, "projects", "showcase")


# ── Helpers ──


def load_yaml(path):
    import yaml
    load_dotenv(os.path.join(os.path.dirname(path), ".env"))
    with open(path) as f:
        cfg = yaml.safe_load(f)
    return resolve_env_vars(cfg)


def leantime_rpc(method, params=None, config=None):
    """Call Leantime JSON-RPC API."""
    if config is None:
        config = load_yaml(PROD_CONFIG).get("leantime", {})
    url = config["url"].rstrip("/") + "/api/jsonrpc"
    api_key = config["api_key"]

    payload = json.dumps({
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": 1,
    }).encode()
    req = urllib.request.Request(
        url, data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.loads(resp.read())
    if "error" in data:
        err = data["error"]
        raise RuntimeError(f"Leantime API error {err.get('code')}: {err.get('message')} - {err.get('data', '')}")
    return data.get("result")


def port_is_free(port):
    return subprocess.run(
        ["lsof", "-i", f":{port}", "-sTCP:LISTEN"],
        capture_output=True,
    ).returncode != 0


def find_free_port():
    for port in PORT_RANGE:
        if port_is_free(port):
            return port
    raise RuntimeError(f"No free port in {PORT_RANGE.start}-{PORT_RANGE.stop - 1}")


def wait_for_port(port, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not port_is_free(port):
            return True
        time.sleep(0.5)
    return False


def kill_port(port):
    result = subprocess.run(
        ["lsof", "-t", "-i", f":{port}", "-sTCP:LISTEN"],
        capture_output=True, text=True,
    )
    pids = result.stdout.strip()
    if pids:
        for pid in pids.split("\n"):
            subprocess.run(["kill", pid.strip()], capture_output=True)
        return True
    return False


def env_dir(name):
    return f"{ENV_PREFIX}{name}"


# ── Commands ──


def cmd_up(args):
    # 1. Determine name
    name = args.name
    if not name:
        import secrets
        name = secrets.token_hex(4)

    work_dir = env_dir(name)
    if os.path.exists(work_dir):
        print(f"Error: environment '{name}' already exists at {work_dir}", file=sys.stderr)
        print("Run 'down' first or choose a different name.", file=sys.stderr)
        sys.exit(1)

    # 2. Allocate port
    port = args.port
    if port:
        if not port_is_free(port):
            print(f"Error: port {port} is already in use", file=sys.stderr)
            sys.exit(1)
    else:
        port = find_free_port()

    # 3. Load preset
    preset = args.preset
    preset_path = os.path.join(PRESETS_DIR, f"{preset}.yaml")
    if not os.path.isfile(preset_path):
        available = [f.replace(".yaml", "") for f in os.listdir(PRESETS_DIR) if f.endswith(".yaml")]
        print(f"Error: preset '{preset}' not found. Available: {available}", file=sys.stderr)
        sys.exit(1)
    preset_cfg = load_yaml(preset_path)

    # 4. Verify agent templates exist
    for agent_name, agent_info in preset_cfg.get("agents", {}).items():
        template = agent_info.get("template", agent_name) if isinstance(agent_info, dict) else agent_name
        agent_def = os.path.join(ROOT_DIR, ".claude", "agents", f"{template}.md")
        if not os.path.isfile(agent_def):
            print(f"Error: agent definition not found: {agent_def}", file=sys.stderr)
            sys.exit(1)
        template_claude = os.path.join(ROOT_DIR, "templates", template, "CLAUDE.md")
        if not os.path.isfile(template_claude):
            print(f"Error: template CLAUDE.md not found: {template_claude}", file=sys.stderr)
            sys.exit(1)

    # 5. Create Leantime project
    prod_cfg = load_yaml(PROD_CONFIG)
    lt_cfg = prod_cfg["leantime"]
    project_name = f"e2e-{name}"

    print(f"Creating Leantime project '{project_name}'...")
    result = leantime_rpc(
        "leantime.rpc.Projects.addProject",
        {"values": {"name": project_name, "clientId": 1}},
        lt_cfg,
    )
    project_id = result[0] if isinstance(result, list) else result
    print(f"  Project ID: {project_id}")

    # 6. Generate test agents.yaml
    os.makedirs(work_dir, exist_ok=True)
    test_config = {
        "tmux_session": f"e2e-{name}",
        "leantime": {
            "url": lt_cfg["url"],
            "api_key": lt_cfg["api_key"],
            "project_id": project_id,
            "user_id": lt_cfg.get("user_id", 1),
        },
        "daemon": {
            "host": "127.0.0.1",
            "port": port,
        },
        "mcp_servers": prod_cfg.get("mcp_servers", {}),
        "agents": preset_cfg["agents"],
    }

    config_path = os.path.join(work_dir, "agents.yaml")
    import yaml
    with open(config_path, "w") as f:
        yaml.dump(test_config, f, default_flow_style=False, allow_unicode=True)

    # 7. Scaffold workspaces
    print("Scaffolding agent workspaces...")
    subprocess.run(
        [
            sys.executable, os.path.join(ROOT_DIR, "setup-agents.py"),
            "--config", config_path,
            "--source-dir", ROOT_DIR,
            "--output-dir", work_dir,
        ],
        check=True,
    )

    # 7b. Initialize git repo so Claude Code resolves the project root to work_dir.
    # Without .git, `claude --agent <name>` walks up the filesystem and may find
    # the source repo's .git, causing agents to work outside the isolated env.
    subprocess.run(
        ["git", "init", work_dir],
        capture_output=True, check=True,
    )
    print("  git init: OK")

    # 8. Start daemon
    daemon_log = os.path.join(work_dir, "daemon.log")
    print(f"Starting daemon on port {port}...")
    env = os.environ.copy()
    env["AGENTS_CONFIG_PATH"] = config_path
    proc = subprocess.Popen(
        [
            "uv", "run",
            "--directory", os.path.join(ROOT_DIR, "services", "agents-mcp"),
            "agents-mcp", "--daemon",
            "--host", "127.0.0.1",
            "--port", str(port),
            "--no-dispatch",
        ],
        env=env,
        stdout=open(daemon_log, "w"),
        stderr=subprocess.STDOUT,
    )

    # 9. Wait for daemon
    if not wait_for_port(port, timeout=15):
        print(f"Error: daemon failed to start. Check {daemon_log}", file=sys.stderr)
        proc.kill()
        sys.exit(1)
    print(f"  Daemon ready (pid: {proc.pid})")

    # 10. Save metadata
    daemon_url = f"http://127.0.0.1:{port}/sse"
    metadata = {
        "name": name,
        "preset": preset,
        "port": port,
        "daemon_pid": proc.pid,
        "project_id": project_id,
        "project_name": project_name,
        "daemon_url": daemon_url,
        "work_dir": work_dir,
        "config_path": config_path,
        "created_at": datetime.now().isoformat(),
        "leantime_url": lt_cfg["url"],
        "leantime_api_key": lt_cfg["api_key"],
    }
    with open(os.path.join(work_dir, "env.json"), "w") as f:
        json.dump(metadata, f, indent=2)
        f.write("\n")

    # 11. Summary
    print()
    print(f"  Environment:  {name}")
    print(f"  Preset:       {preset}")
    print(f"  Daemon URL:   {daemon_url}")
    print(f"  Project ID:   {project_id}")
    print(f"  Work dir:     {work_dir}")
    print(f"  Config:       {config_path}")
    print(f"  Daemon log:   {daemon_log}")
    print()


def cmd_down(args):
    name = args.name
    if not name:
        print("Error: --name is required for 'down'", file=sys.stderr)
        sys.exit(1)

    work_dir = env_dir(name)
    env_file = os.path.join(work_dir, "env.json")

    if not os.path.isfile(env_file):
        print(f"Error: environment '{name}' not found at {work_dir}", file=sys.stderr)
        sys.exit(1)

    with open(env_file) as f:
        meta = json.load(f)

    port = meta["port"]
    project_id = meta["project_id"]
    lt_cfg = {
        "url": meta.get("leantime_url", "http://localhost:9090"),
        "api_key": meta["leantime_api_key"],
    }

    # 1. Stop daemon
    print(f"Stopping daemon on port {port}...")
    if kill_port(port):
        print("  Daemon stopped")
    else:
        print("  Daemon not running")

    # 2. Delete Leantime project
    print(f"Deleting Leantime project {meta['project_name']} (id={project_id})...")
    try:
        leantime_rpc(
            "leantime.rpc.AgentsApi.deleteProject",
            {"id": project_id},
            lt_cfg,
        )
        print("  Project deleted")
    except Exception as e:
        print(f"  Warning: failed to delete project: {e}", file=sys.stderr)

    # 3. Remove work directory
    print(f"Removing {work_dir}...")
    shutil.rmtree(work_dir, ignore_errors=True)
    print("  Done")
    print()


def cmd_list(args):
    envs = sorted(glob.glob(f"{ENV_PREFIX}*/env.json"))
    if not envs:
        print("No active test environments.")
        return

    print(f"{'NAME':<16} {'PRESET':<10} {'PORT':<6} {'PROJECT':<10} {'DAEMON':<8} {'CREATED'}")
    print("-" * 80)
    for env_file in envs:
        with open(env_file) as f:
            meta = json.load(f)
        daemon_status = "running" if not port_is_free(meta["port"]) else "stopped"
        created = meta.get("created_at", "?")[:19]
        print(f"{meta['name']:<16} {meta.get('preset','?'):<10} {meta['port']:<6} {meta['project_id']:<10} {daemon_status:<8} {created}")


# ── Archive helpers ──


# Agent infrastructure files/dirs to exclude when copying project code
_INFRA_FILES = {".mcp.json", "system_prompt.md", "CLAUDE.md"}
_INFRA_DIRS = {".claude", ".git", "__pycache__", "node_modules", "screenshots", "test-results"}
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

_EXT_TO_TECH = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".html": "HTML",
    ".css": "CSS",
    ".jsx": "React (JSX)",
    ".tsx": "React (TSX)",
    ".vue": "Vue",
    ".rb": "Ruby",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".php": "PHP",
}


def _infer_tech_stack(directory):
    """Infer tech stack from file extensions in the directory."""
    found = set()
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d != "screenshots"]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in _EXT_TO_TECH:
                found.add(_EXT_TO_TECH[ext])
    return sorted(found)


def _generate_archive_readme(showcase_dir, name, meta):
    """Generate README.md for the archived showcase project."""
    lines = [f"# {name}", "", "> 此项目由 Agent-Hub 自动生成。", ""]

    if meta:
        lines.append("## 项目信息")
        lines.append("")
        if meta.get("created_at"):
            lines.append(f"- **创建时间**: {meta['created_at'][:19]}")
        if meta.get("project_id"):
            lines.append(f"- **Leantime Project ID**: {meta['project_id']}")
        if meta.get("port"):
            lines.append(f"- **Daemon Port**: {meta['port']}")
        if meta.get("preset"):
            lines.append(f"- **Preset**: {meta['preset']}")
        lines.append("")

    tech = _infer_tech_stack(showcase_dir)
    if tech:
        lines.append("## 技术栈")
        lines.append("")
        for t in tech:
            lines.append(f"- {t}")
        lines.append("")

    ss_dir = os.path.join(showcase_dir, "screenshots")
    if os.path.isdir(ss_dir):
        screenshots = []
        for root, dirs, files in os.walk(ss_dir):
            for f in sorted(files):
                if os.path.splitext(f)[1].lower() in _IMAGE_EXTS:
                    rel = os.path.relpath(os.path.join(root, f), showcase_dir)
                    screenshots.append(rel)
        if screenshots:
            lines.append("## 截图")
            lines.append("")
            for ss in screenshots:
                lines.append(f"![{os.path.basename(ss)}]({ss})")
            lines.append("")

    with open(os.path.join(showcase_dir, "README.md"), "w") as f:
        f.write("\n".join(lines) + "\n")


def cmd_archive(args):
    env_name = args.env_name
    showcase_name = args.name
    force = args.force

    work_dir = env_dir(env_name)

    # Validate environment exists
    if not os.path.exists(work_dir):
        print(f"Error: environment '{env_name}' not found at {work_dir}", file=sys.stderr)
        sys.exit(1)

    # Load metadata (may be absent if env was partially cleaned up)
    env_file = os.path.join(work_dir, "env.json")
    meta = {}
    if os.path.isfile(env_file):
        with open(env_file) as f:
            meta = json.load(f)

    # Target directory
    showcase_path = os.path.join(SHOWCASE_DIR, showcase_name)

    if os.path.exists(showcase_path):
        if not force:
            print(
                f"Error: '{showcase_path}' already exists. Use --force to overwrite.",
                file=sys.stderr,
            )
            sys.exit(1)
        shutil.rmtree(showcase_path)

    os.makedirs(showcase_path, exist_ok=True)

    print(f"Archiving environment '{env_name}' as '{showcase_name}'...")

    # 1. Copy project code from projects/ directory (where Dev agents create code)
    projects_dir = os.path.join(work_dir, "projects")
    agents_dir = os.path.join(work_dir, "agents")
    copied_files = 0

    if os.path.isdir(projects_dir):
        for dirpath, dirnames, filenames in os.walk(projects_dir):
            dirnames[:] = [d for d in dirnames if d not in _INFRA_DIRS]
            for fname in filenames:
                if fname in _INFRA_FILES:
                    continue
                src = os.path.join(dirpath, fname)
                rel = os.path.relpath(src, projects_dir)
                dst = os.path.join(showcase_path, rel)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src, dst)
                copied_files += 1

    # Also scan agent workspaces for any project files created there
    if os.path.isdir(agents_dir):
        for agent_name in sorted(os.listdir(agents_dir)):
            agent_path = os.path.join(agents_dir, agent_name)
            if not os.path.isdir(agent_path) or agent_name == "shared":
                continue

            for dirpath, dirnames, filenames in os.walk(agent_path):
                dirnames[:] = [d for d in dirnames if d not in _INFRA_DIRS]
                for fname in filenames:
                    if fname in _INFRA_FILES:
                        continue
                    src = os.path.join(dirpath, fname)
                    rel = os.path.relpath(src, agent_path)
                    dst = os.path.join(showcase_path, rel)
                    if not os.path.exists(dst):
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy2(src, dst)
                        copied_files += 1

    print(f"  Copied {copied_files} project files")

    # 2. Copy QA screenshots from multiple locations
    screenshots_copied = 0
    screenshot_dst = os.path.join(showcase_path, "screenshots")

    # Scan tests/screenshots/ at the environment root
    for sdir in (
        os.path.join(work_dir, "tests", "screenshots"),
        os.path.join(work_dir, "tests", "test-results"),
    ):
        if os.path.isdir(sdir):
            for root, _dirs, files in os.walk(sdir):
                for f in files:
                    if os.path.splitext(f)[1].lower() in _IMAGE_EXTS:
                        src = os.path.join(root, f)
                        rel = os.path.relpath(src, sdir)
                        dst = os.path.join(screenshot_dst, rel)
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        shutil.copy2(src, dst)
                        screenshots_copied += 1

    # Scan projects/*/tests/screenshots/ and projects/*/tests/test-results/
    if os.path.isdir(projects_dir):
        for project_name in sorted(os.listdir(projects_dir)):
            project_path = os.path.join(projects_dir, project_name)
            if not os.path.isdir(project_path):
                continue
            for sdir_name in ("tests/screenshots", "tests/test-results"):
                src_dir = os.path.join(project_path, sdir_name)
                if not os.path.isdir(src_dir):
                    continue
                for root, _dirs, files in os.walk(src_dir):
                    for f in files:
                        if os.path.splitext(f)[1].lower() in _IMAGE_EXTS:
                            src = os.path.join(root, f)
                            rel = os.path.relpath(src, src_dir)
                            dst = os.path.join(screenshot_dst, rel)
                            if not os.path.exists(dst):
                                os.makedirs(os.path.dirname(dst), exist_ok=True)
                                shutil.copy2(src, dst)
                                screenshots_copied += 1

    # Also scan agent workspace screenshot directories
    if os.path.isdir(agents_dir):
        for agent_name in sorted(os.listdir(agents_dir)):
            agent_path = os.path.join(agents_dir, agent_name)
            if not os.path.isdir(agent_path) or agent_name == "shared":
                continue

            for sdir_name in ("screenshots", "test-results"):
                src_dir = os.path.join(agent_path, sdir_name)
                if not os.path.isdir(src_dir):
                    continue

                for root, _dirs, files in os.walk(src_dir):
                    for f in files:
                        if os.path.splitext(f)[1].lower() in _IMAGE_EXTS:
                            src = os.path.join(root, f)
                            rel = os.path.relpath(src, src_dir)
                            dst = os.path.join(screenshot_dst, rel)
                            if not os.path.exists(dst):
                                os.makedirs(os.path.dirname(dst), exist_ok=True)
                                shutil.copy2(src, dst)
                                screenshots_copied += 1

    if screenshots_copied:
        print(f"  Copied {screenshots_copied} screenshots")
    else:
        print("  No screenshots found (skipped)")

    # 3. Generate README.md
    _generate_archive_readme(showcase_path, showcase_name, meta)
    print("  Generated README.md")

    print()
    print(f"  Archive: {showcase_path}")
    print()


# ── Main ──


def main():
    parser = argparse.ArgumentParser(description="E2E test environment manager")
    sub = parser.add_subparsers(dest="command")

    up_p = sub.add_parser("up", help="Create isolated test environment")
    up_p.add_argument("--name", help="Environment name (default: auto-generated)")
    up_p.add_argument("--port", type=int, help="Daemon port (default: auto-assign)")
    up_p.add_argument("--preset", default="minimal", help="Preset template (default: minimal)")

    down_p = sub.add_parser("down", help="Destroy test environment")
    down_p.add_argument("--name", required=True, help="Environment name")

    sub.add_parser("list", help="List active test environments")

    archive_p = sub.add_parser("archive", help="Archive test artifacts to showcase directory")
    archive_p.add_argument("env_name", help="Environment name to archive from")
    archive_p.add_argument("--name", required=True, help="Showcase name for the archive")
    archive_p.add_argument("--force", action="store_true", help="Overwrite existing archive")

    args = parser.parse_args()
    if args.command == "up":
        cmd_up(args)
    elif args.command == "down":
        cmd_down(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "archive":
        cmd_archive(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""CLI helper to bridge agents.yaml config with shell scripts."""

import argparse
import os
import sys

import yaml

from config_utils import load_dotenv, resolve_env_vars

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(ROOT_DIR, "agents.yaml")
SESSIONS_PATH = os.path.join(ROOT_DIR, ".agent-sessions")


def load_config():
    load_dotenv(os.path.join(ROOT_DIR, ".env"))
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    # Pre-resolve workspace_dir so ${WORKSPACE_DIR} in add_dirs works
    # even when the env var is not explicitly set (falls back to default).
    _bootstrap_workspace_dir(cfg)
    return resolve_env_vars(cfg)


def _bootstrap_workspace_dir(cfg):
    """If WORKSPACE_DIR is not set, derive it from workspace_dir config default."""
    if "WORKSPACE_DIR" not in os.environ and "workspace_dir" in cfg:
        raw = cfg["workspace_dir"]
        resolved = resolve_env_vars(raw)
        os.environ["WORKSPACE_DIR"] = os.path.expanduser(resolved)


def resolve_agents(cfg):
    """Resolve agent templates. Each agent is listed individually in config.

    If an agent has a 'template' field (e.g. template: qa), it points to the
    template directory agents/<template>/. The template is stored as '_base_name'.
    If no 'template' field, the agent name itself is the template (e.g. admin).
    """
    resolved = {}
    for name, info in cfg.get("agents", {}).items():
        agent = dict(info)
        template = agent.pop("template", name)
        agent["_base_name"] = template
        resolved[name] = agent
    return resolved


def load_sessions():
    if not os.path.exists(SESSIONS_PATH):
        return {}
    sessions = {}
    with open(SESSIONS_PATH) as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                sessions[k.strip()] = v.strip()
    return sessions


def save_sessions(sessions):
    with open(SESSIONS_PATH, "w") as f:
        for k, v in sorted(sessions.items()):
            f.write(f"{k}={v}\n")


def cmd_list_agents(cfg, _args):
    agents = resolve_agents(cfg)
    for name in agents:
        print(name)


def cmd_list_workers(cfg, _args):
    agents = resolve_agents(cfg)
    for name, info in agents.items():
        if info.get("dispatchable", False):
            print(name)


def cmd_get(cfg, args):
    agent = args.agent
    field = args.field
    agents = resolve_agents(cfg)
    if agent not in agents:
        print(f"Unknown agent: {agent}", file=sys.stderr)
        sys.exit(1)
    val = agents[agent].get(field, "")
    if isinstance(val, bool):
        print("true" if val else "false")
    elif isinstance(val, list):
        for item in val:
            print(item)
    else:
        print(val)


def cmd_get_add_dirs(cfg, args):
    agent = args.agent
    agents = resolve_agents(cfg)
    if agent not in agents:
        print(f"Unknown agent: {agent}", file=sys.stderr)
        sys.exit(1)
    dirs = agents[agent].get("add_dirs", [])
    for d in dirs:
        if d == ".":
            print(ROOT_DIR)
        elif "${" in str(d):
            # Skip unresolved env vars (optional dependencies)
            continue
        else:
            # Expand ~ to home directory
            resolved = os.path.expanduser(d)
            # Skip directories that don't exist (optional workspace projects)
            if not os.path.isdir(resolved):
                print(f"Skipping {d}: directory not found", file=sys.stderr)
                continue
            print(resolved)


def cmd_get_session(cfg, args):
    sessions = load_sessions()
    sid = sessions.get(args.agent, "")
    print(sid)


def cmd_set_session(cfg, args):
    sessions = load_sessions()
    sessions[args.agent] = args.session_id
    save_sessions(sessions)


def cmd_detect_session(cfg, args):
    """Detect latest session ID from Claude Code project files."""
    agent = args.agent
    agent_dir = os.path.join(ROOT_DIR, "agents", agent)
    abs_path = os.path.abspath(agent_dir)
    proj_name = "-" + abs_path.strip("/").replace("/", "-")
    proj_dir = os.path.join(os.path.expanduser("~"), ".claude", "projects", proj_name)

    # Follow symlinks in ~/.claude/projects/
    if os.path.islink(proj_dir):
        target = os.readlink(proj_dir)
        if not os.path.isabs(target):
            target = os.path.join(os.path.dirname(proj_dir), target)
        proj_dir = target

    if not os.path.isdir(proj_dir):
        return

    jsonl_files = [f for f in os.listdir(proj_dir) if f.endswith(".jsonl")]
    if not jsonl_files:
        return

    jsonl_files.sort(
        key=lambda f: os.path.getmtime(os.path.join(proj_dir, f)), reverse=True
    )
    print(jsonl_files[0].removesuffix(".jsonl"))


def cmd_generate_roster(cfg, _args):
    agents = resolve_agents(cfg)
    lines = [
        "# 团队花名册",
        "",
        "> 此文件由 `agent-config.py generate-roster` 从 `agents.yaml` 自动生成，请勿手动编辑。",
        "",
        "| Agent ID | 角色 | 职责 | Agent Tag | tmux window |",
        "|----------|------|------|-------------|-------------|",
    ]
    tmux_session = cfg.get("tmux_session", "agents")
    for name, info in agents.items():
        role = info.get("role", "")
        desc = info.get("description", "")
        tag = f"`agent:{name}`"
        window = f"`{tmux_session}:{name}`"
        lines.append(f"| {name} | {role} | {desc} | {tag} | {window} |")
    print("\n".join(lines))


def cmd_leantime(cfg, args):
    lt = cfg.get("leantime", {})
    field = args.field
    val = lt.get(field, "")
    print(val)


def cmd_tmux_session(cfg, _args):
    print(cfg.get("tmux_session", "agents"))


def cmd_daemon_host(cfg, _args):
    """Resolved daemon bind host (same rules as setup-agents.py / .mcp.json)."""
    d = cfg.get("daemon") or {}
    print(d.get("host", "127.0.0.1"))


def cmd_daemon_port(cfg, _args):
    """Daemon port, or empty line if no daemon block / no port."""
    d = cfg.get("daemon")
    if not d:
        print("")
        return
    p = d.get("port", "")
    print(p if p is not None else "")


def main():
    parser = argparse.ArgumentParser(description="Agent config CLI helper")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list-agents", help="List all agent names")
    sub.add_parser("list-workers", help="List dispatchable agents")

    p_get = sub.add_parser("get", help="Get agent field value")
    p_get.add_argument("agent")
    p_get.add_argument("field")

    p_dirs = sub.add_parser("get-add-dirs", help="Get add_dirs for agent")
    p_dirs.add_argument("agent")

    p_gs = sub.add_parser("get-session", help="Get session ID")
    p_gs.add_argument("agent")

    p_ss = sub.add_parser("set-session", help="Set session ID")
    p_ss.add_argument("agent")
    p_ss.add_argument("session_id")

    p_ds = sub.add_parser("detect-session", help="Detect latest session ID from Claude project files")
    p_ds.add_argument("agent")

    sub.add_parser("generate-roster", help="Generate team roster markdown")

    p_lt = sub.add_parser("leantime", help="Get leantime config field")
    p_lt.add_argument("field")

    sub.add_parser("tmux-session", help="Get tmux session name")

    sub.add_parser("daemon-host", help="Get resolved daemon host (for restart_all_agents.sh)")
    sub.add_parser("daemon-port", help="Get resolved daemon port (empty if none)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    cfg = load_config()

    commands = {
        "list-agents": cmd_list_agents,
        "list-workers": cmd_list_workers,
        "get": cmd_get,
        "get-add-dirs": cmd_get_add_dirs,
        "get-session": cmd_get_session,
        "set-session": cmd_set_session,
        "detect-session": cmd_detect_session,
        "generate-roster": cmd_generate_roster,
        "leantime": cmd_leantime,
        "tmux-session": cmd_tmux_session,
        "daemon-host": cmd_daemon_host,
        "daemon-port": cmd_daemon_port,
    }

    commands[args.command](cfg, args)


if __name__ == "__main__":
    main()

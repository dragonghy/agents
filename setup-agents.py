#!/usr/bin/env python3
"""Auto-generate agent workspaces from agents.yaml configuration.

Reads agents.yaml and sets up the runtime working directory for each agent:
  - .mcp.json (generated from MCP server config)
  - .claude/agents/<instance>.md (native agent definition with YAML frontmatter)
  - .claude/skills/ (symlinks to shared + agent-specific skills)
  - agents/shared/team-roster.md (generated)

Template agent definitions live in .claude/agents/<role>.md (tracked in git).
Instance agent definitions are generated from templates with agent ID replacement.
Agent-specific skill sources live in templates/<name>/skills/.
Shared skill sources live in templates/shared/skills/.

Supports scaffolding to a custom output directory (for testing):
  python3 setup-agents.py --config test-agents.yaml --output-dir /tmp/test-env
"""

import argparse
import json
import os
import shutil
import sys

import yaml

from config_utils import load_dotenv, resolve_env_vars


def resolve_agents(cfg):
    """Resolve agent templates. Each agent is listed individually in config.

    If an agent has a 'template' field, it points to the template directory
    under templates/<template>/. The template name is stored as '_base_name'.
    If no 'template' field, the agent name itself is the template.
    """
    resolved = {}
    for name, info in cfg.get("agents", {}).items():
        agent = dict(info)
        template = agent.pop("template", name)
        agent["_base_name"] = template
        resolved[name] = agent
    return resolved


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def force_symlink(src, dst):
    """Create a symlink, removing existing file/link if present."""
    if os.path.islink(dst) or os.path.exists(dst):
        os.remove(dst)
    os.symlink(src, dst)


def generate_mcp_json(cfg, config_path, agent_dir, source_dir):
    """Generate .mcp.json from agents.yaml mcp_servers config."""
    mcp_servers = cfg.get("mcp_servers", {})
    daemon = cfg.get("daemon", {})
    leantime = cfg.get("leantime", {})

    result = {"mcpServers": {}}

    for name, server_cfg in mcp_servers.items():
        entry = {
            "command": os.path.expanduser(server_cfg["command"]),
            "args": [
                os.path.expanduser(a.replace("{ROOT_DIR}", source_dir))
                for a in server_cfg.get("args", [])
            ],
        }

        # Build env vars: start with any env defined in config, then apply
        # server-specific overrides for agents/leantime.
        env = dict(server_cfg.get("env", {}))

        if name == "agents":
            # Check if the command is the proxy (agents-mcp-proxy)
            is_proxy = any("agents-mcp-proxy" in str(a) for a in entry["args"])
            if is_proxy and daemon:
                host = daemon.get("host", "127.0.0.1")
                port = daemon.get("port", 8765)
                env["AGENTS_DAEMON_URL"] = f"http://{host}:{port}/sse"
            else:
                # Direct mode: pass config path to full server
                env["AGENTS_CONFIG_PATH"] = config_path
        elif name == "leantime" and leantime:
            env.update({
                "LEANTIME_URL": leantime.get("url", ""),
                "LEANTIME_API_KEY": leantime.get("api_key", ""),
                "LEANTIME_USER_EMAIL": leantime.get("user_email", ""),
            })

        if env:
            entry["env"] = env

        result["mcpServers"][name] = entry

    mcp_path = os.path.join(agent_dir, ".mcp.json")
    with open(mcp_path, "w") as f:
        json.dump(result, f, indent=2)
        f.write("\n")


def setup_skills(agent_name, agent_dir, source_templates_dir, base_name=None):
    """Set up .claude/skills/ with symlinks to shared, agent-specific, and project-level skills."""
    skills_dir = os.path.join(agent_dir, ".claude", "skills")
    ensure_dir(skills_dir)

    shared_skills_dir = os.path.join(source_templates_dir, "shared", "skills")

    # Remove stale symlinks
    if os.path.isdir(skills_dir):
        for entry in os.listdir(skills_dir):
            entry_path = os.path.join(skills_dir, entry)
            if os.path.islink(entry_path) and not os.path.exists(entry_path):
                os.remove(entry_path)

    # Symlink shared skills
    if os.path.isdir(shared_skills_dir):
        for skill_name in sorted(os.listdir(shared_skills_dir)):
            skill_src = os.path.join(shared_skills_dir, skill_name)
            if os.path.isdir(skill_src):
                force_symlink(skill_src, os.path.join(skills_dir, skill_name))

    # Symlink agent-specific skills (from source template)
    template_dir = os.path.join(source_templates_dir, base_name or agent_name)
    agent_skills_dir = os.path.join(template_dir, "skills")
    if os.path.isdir(agent_skills_dir):
        for skill_name in sorted(os.listdir(agent_skills_dir)):
            skill_src = os.path.join(agent_skills_dir, skill_name)
            if os.path.isdir(skill_src):
                force_symlink(skill_src, os.path.join(skills_dir, skill_name))

    # Symlink project-level skills (from projects/*/skills/)
    source_dir = os.path.dirname(source_templates_dir)
    projects_dir = os.path.join(source_dir, "projects")
    if os.path.isdir(projects_dir):
        for project in sorted(os.listdir(projects_dir)):
            project_skills = os.path.join(projects_dir, project, "skills")
            if os.path.isdir(project_skills):
                for skill_name in sorted(os.listdir(project_skills)):
                    skill_src = os.path.join(project_skills, skill_name)
                    if os.path.isdir(skill_src):
                        force_symlink(skill_src, os.path.join(skills_dir, skill_name))


def generate_instance_agent(agent_name, base_name, source_dir, output_dir):
    """Generate .claude/agents/<agent_name>.md from the template agent definition.

    Reads the template from <source_dir>/.claude/agents/<base_name>.md,
    replaces agent IDs and the YAML frontmatter name field, then writes
    to <output_dir>/.claude/agents/<agent_name>.md.
    """
    template_path = os.path.join(source_dir, ".claude", "agents", f"{base_name}.md")
    if not os.path.isfile(template_path):
        return

    with open(template_path) as f:
        content = f.read()

    # Update YAML frontmatter name field
    content = content.replace(f"\nname: {base_name}\n", f"\nname: {agent_name}\n")

    # Replace agent IDs in the body
    content = content.replace(f"agent:{base_name}`", f"agent:{agent_name}`")
    content = content.replace(f"agent:{base_name},", f"agent:{agent_name},")
    content = content.replace(f"agent:{base_name}\"", f"agent:{agent_name}\"")
    content = content.replace(
        f"**你的 Agent ID**: `{base_name}`",
        f"**你的 Agent ID**: `{agent_name}`",
    )
    content = content.replace(
        f"**你的 Leantime tag**: `agent:{base_name}`",
        f"**你的 Leantime tag**: `agent:{agent_name}`",
    )

    agents_defs_dir = os.path.join(output_dir, ".claude", "agents")
    ensure_dir(agents_defs_dir)
    with open(os.path.join(agents_defs_dir, f"{agent_name}.md"), "w") as f:
        f.write(content)


def generate_roster(cfg, agents_expanded, output_agents_dir):
    """Generate team-roster.md in the output agents dir."""
    tmux_session = cfg.get("tmux_session", "agents")
    lines = [
        "# 团队花名册",
        "",
        "> 此文件由 `setup-agents.py` 从 `agents.yaml` 自动生成，请勿手动编辑。",
        "",
        "| Agent ID | 角色 | 职责 | Leantime Tag | tmux window |",
        "|----------|------|------|-------------|-------------|",
    ]
    for name, info in agents_expanded.items():
        role = info.get("role", "")
        desc = info.get("description", "")
        tag = f"`agent:{name}`"
        window = f"`{tmux_session}:{name}`"
        lines.append(f"| {name} | {role} | {desc} | {tag} | {window} |")

    roster_path = os.path.join(output_agents_dir, "shared", "team-roster.md")
    ensure_dir(os.path.dirname(roster_path))
    with open(roster_path, "w") as f:
        f.write("\n".join(lines) + "\n")


def validate_agent(agent_name, source_dir):
    """Check that agent definition file exists for a template agent."""
    issues = []
    agent_def = os.path.join(source_dir, ".claude", "agents", f"{agent_name}.md")
    if not os.path.isfile(agent_def):
        issues.append(f"  Missing: .claude/agents/{agent_name}.md")
    return issues


def setup_all(cfg, config_path, source_dir, output_dir):
    """Set up workspaces for all agents.

    Args:
        cfg: Parsed agents.yaml dict
        config_path: Absolute path to agents.yaml (for env vars)
        source_dir: Where source files live (git repo root)
        output_dir: Where to write generated files (may differ from source for testing)
    """
    source_templates_dir = os.path.join(source_dir, "templates")
    output_agents_dir = os.path.join(output_dir, "agents")

    agents_expanded = resolve_agents(cfg)
    print(f"Setting up {len(agents_expanded)} agent(s)...")
    if output_dir != source_dir:
        print(f"  source: {source_dir}")
        print(f"  output: {output_dir}")

    # When scaffolding to a different dir, copy template agent definitions
    if output_dir != source_dir:
        source_agent_defs = os.path.join(source_dir, ".claude", "agents")
        output_agent_defs = os.path.join(output_dir, ".claude", "agents")
        if os.path.isdir(source_agent_defs):
            ensure_dir(output_agent_defs)
            for fname in sorted(os.listdir(source_agent_defs)):
                if fname.endswith(".md"):
                    shutil.copy2(
                        os.path.join(source_agent_defs, fname),
                        os.path.join(output_agent_defs, fname),
                    )

    all_issues = {}
    for name, info in agents_expanded.items():
        base_name = info.get("_base_name", name)
        is_instance = base_name != name

        agent_dir = os.path.join(output_agents_dir, name)
        ensure_dir(agent_dir)

        if is_instance:
            generate_instance_agent(name, base_name, source_dir, output_dir)
            template_claude = os.path.join(source_templates_dir, base_name, "CLAUDE.md")
            instance_claude = os.path.join(agent_dir, "CLAUDE.md")
            if os.path.isfile(template_claude):
                shutil.copy2(template_claude, instance_claude)
        elif output_dir != source_dir:
            # When scaffolding to a different dir, copy CLAUDE.md
            src = os.path.join(source_templates_dir, name, "CLAUDE.md")
            dst = os.path.join(agent_dir, "CLAUDE.md")
            if os.path.isfile(src):
                shutil.copy2(src, dst)
        else:
            issues = validate_agent(name, source_dir)
            if issues:
                all_issues[name] = issues

        generate_mcp_json(cfg, config_path, agent_dir, source_dir)
        setup_skills(name, agent_dir, source_templates_dir, base_name=base_name if is_instance else None)

        suffix = f" (instance of {base_name})" if is_instance else ""
        print(f"  {name}: OK{suffix}")

    # Generate root-level .mcp.json for --agent mode compatibility.
    # When using `claude --agent <name>`, Claude Code resolves the project root
    # to the git root (where .claude/agents/ lives) and looks for .mcp.json there.
    generate_mcp_json(cfg, config_path, output_dir, source_dir)
    print("  .mcp.json (root): OK")

    generate_roster(cfg, agents_expanded, output_agents_dir)
    print("  team-roster.md: OK")

    if all_issues:
        print("\nWarnings:")
        for name, issues in all_issues.items():
            print(f"  {name}:")
            for issue in issues:
                print(f"    {issue}")

    print("\nDone.")


def main():
    default_source = os.path.dirname(os.path.abspath(__file__))
    default_config = os.path.join(default_source, "agents.yaml")

    parser = argparse.ArgumentParser(
        description="Generate agent workspaces from agents.yaml"
    )
    parser.add_argument(
        "--config", default=default_config,
        help="Path to agents.yaml (default: agents.yaml in script dir)",
    )
    parser.add_argument(
        "--source-dir", default=None,
        help="Source directory for templates (default: directory containing agents.yaml)",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Output directory for generated files (default: same as source-dir)",
    )
    args = parser.parse_args()

    config_path = os.path.abspath(args.config)
    if not os.path.isfile(config_path):
        print(f"Error: {config_path} not found", file=sys.stderr)
        sys.exit(1)

    source_dir = os.path.abspath(args.source_dir) if args.source_dir else os.path.dirname(config_path)
    output_dir = os.path.abspath(args.output_dir) if args.output_dir else source_dir

    # Load .env from the config file's directory
    load_dotenv(os.path.join(os.path.dirname(config_path), ".env"))

    with open(config_path) as f:
        cfg = yaml.safe_load(f)

    # Pre-resolve workspace_dir so ${WORKSPACE_DIR} in add_dirs works
    # even when the env var is not explicitly set (falls back to default).
    if "WORKSPACE_DIR" not in os.environ and "workspace_dir" in cfg:
        raw = cfg["workspace_dir"]
        resolved = resolve_env_vars(raw)
        os.environ["WORKSPACE_DIR"] = os.path.expanduser(resolved)

    cfg = resolve_env_vars(cfg)

    setup_all(cfg, config_path, source_dir, output_dir)


if __name__ == "__main__":
    main()

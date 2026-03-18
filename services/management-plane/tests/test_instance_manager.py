"""Tests for instance_manager — config generation, templates, and file creation."""

import os
import json
from pathlib import Path
from unittest.mock import patch, AsyncMock

import yaml

os.environ["MGMT_MOCK_MODE"] = "true"  # Tests always use mock mode

from management.instance_manager import (
    TEAM_TEMPLATES,
    _generate_agents_yaml,
    _generate_compose_yaml,
    _generate_env,
    _get_instance_dir,
    _get_project_name,
    get_template_info,
)


# ── Template tests ──


class TestTeamTemplates:
    def test_solo_has_3_agents(self):
        assert len(TEAM_TEMPLATES["solo"]["agents"]) == 3

    def test_standard_has_5_agents(self):
        assert len(TEAM_TEMPLATES["standard"]["agents"]) == 5

    def test_full_has_8_agents(self):
        assert len(TEAM_TEMPLATES["full"]["agents"]) >= 7

    def test_all_agents_have_required_fields(self):
        for tname, tpl in TEAM_TEMPLATES.items():
            for aname, agent in tpl["agents"].items():
                assert "template" in agent, f"{tname}/{aname} missing template"
                assert "role" in agent, f"{tname}/{aname} missing role"
                assert "dispatchable" in agent, f"{tname}/{aname} missing dispatchable"

    def test_get_template_info(self):
        info = get_template_info("standard")
        assert info["agent_count"] == 5
        assert len(info["agents"]) == 5

    def test_get_template_info_unknown(self):
        info = get_template_info("nonexistent")
        assert "error" in info


# ── Config generation tests ──


class TestAgentsYaml:
    def test_generates_valid_yaml(self):
        config = _generate_agents_yaml("standard")
        # Should be serializable to YAML
        yaml_str = yaml.dump(config)
        parsed = yaml.safe_load(yaml_str)
        assert parsed["tmux_session"] == "agents"
        assert "agents" in parsed

    def test_daemon_host_is_docker(self):
        config = _generate_agents_yaml("solo")
        assert config["daemon"]["host"] == "daemon"
        assert config["daemon"]["port"] == 8765

    def test_solo_template(self):
        config = _generate_agents_yaml("solo")
        assert len(config["agents"]) == 3
        agent_templates = {a["template"] for a in config["agents"].values()}
        assert "product" in agent_templates
        assert "dev" in agent_templates
        assert "qa" in agent_templates

    def test_standard_template(self):
        config = _generate_agents_yaml("standard")
        assert len(config["agents"]) == 5

    def test_full_template(self):
        config = _generate_agents_yaml("full")
        assert len(config["agents"]) >= 7

    def test_unknown_template_falls_back_to_standard(self):
        config = _generate_agents_yaml("nonexistent")
        assert len(config["agents"]) == 5


class TestComposeYaml:
    def test_contains_daemon_service(self):
        content = _generate_compose_yaml("test-co", 10001)
        assert "daemon:" in content
        assert "10001}" in content  # ${WEB_PORT:-10001}
        assert "8765" in content

    def test_contains_agents_service(self):
        content = _generate_compose_yaml("test-co", 10001)
        assert "agents:" in content
        assert "DAEMON_HOST=daemon" in content

    def test_project_name_in_header(self):
        content = _generate_compose_yaml("my-startup", 10002)
        assert "my-startup" in content


class TestEnvGeneration:
    def test_oauth_token(self):
        env = _generate_env("oauth_token", "sk-test-123", 10001)
        assert "CLAUDE_CODE_OAUTH_TOKEN=sk-test-123" in env
        assert "WEB_PORT=10001" in env

    def test_api_key(self):
        env = _generate_env("api_key", "sk-ant-key", 10002)
        assert "ANTHROPIC_API_KEY=sk-ant-key" in env

    def test_no_auth(self):
        env = _generate_env(None, None, 10003)
        assert "WEB_PORT=10003" in env
        assert "OAUTH" not in env
        assert "API_KEY" not in env


class TestInstancePaths:
    def test_instance_dir(self):
        d = _get_instance_dir("test-co")
        assert str(d).endswith("test-co")

    def test_project_name(self):
        name = _get_project_name("my-startup")
        assert name == "aghub-my-startup"


# ── File creation test (real mode simulation) ──


class TestFileGeneration:
    def test_full_config_generation(self, tmp_path):
        """Simulate real mode instance directory creation."""
        os.environ["MGMT_INSTANCES_DIR"] = str(tmp_path)

        slug = "test-integration"
        port = 10010
        instance_dir = tmp_path / slug
        instance_dir.mkdir()

        # Generate agents.yaml
        config = _generate_agents_yaml("standard")
        with open(instance_dir / "agents.yaml", "w") as f:
            yaml.dump(config, f)

        # Generate docker-compose.yml
        compose = _generate_compose_yaml(slug, port)
        with open(instance_dir / "docker-compose.yml", "w") as f:
            f.write(compose)

        # Generate .env
        env = _generate_env("oauth_token", "sk-test", port)
        with open(instance_dir / ".env", "w") as f:
            f.write(env)

        # Verify files exist and are valid
        assert (instance_dir / "agents.yaml").exists()
        assert (instance_dir / "docker-compose.yml").exists()
        assert (instance_dir / ".env").exists()

        # Verify agents.yaml is valid YAML
        with open(instance_dir / "agents.yaml") as f:
            parsed = yaml.safe_load(f)
        assert parsed["tmux_session"] == "agents"
        assert len(parsed["agents"]) == 5

        # Verify docker-compose.yml mentions the port
        with open(instance_dir / "docker-compose.yml") as f:
            compose_text = f.read()
        assert str(port) in compose_text  # Port in ${WEB_PORT:-10010}:8765

        # Verify .env has the token
        with open(instance_dir / ".env") as f:
            env_text = f.read()
        assert "sk-test" in env_text

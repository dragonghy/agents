# Contributing to Agent-Hub

Thank you for your interest in contributing to Agent-Hub! This guide will help you get started.

## Development Setup

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- Docker & Docker Compose
- [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code)
- Node.js 18+ (for Web UI development)

### Local Development

1. Fork and clone the repository
2. Copy `.env.example` to `.env` and fill in your credentials
3. Start Leantime: `source .env && docker compose -f services/leantime/docker-compose.yml up -d`
4. Generate agent workspaces: `python3 setup-agents.py`
5. Start the system: `./restart_all_agents.sh`

### Running Tests

```bash
# Staleness detection unit tests
cd services/agents-mcp && uv run python tests/test_staleness.py

# E2E test with isolated environment
python3 tests/e2e_env.py up --name mytest --preset minimal
# ... run tests ...
python3 tests/e2e_env.py down --name mytest
```

### Web UI Development

```bash
cd services/agents-mcp/web
npm install
npm run dev     # Development server with hot reload
npm run build   # Production build
npm test        # Playwright E2E tests
```

## Pull Request Process

1. **Create a feature branch** from `main`
2. **Make focused changes** — one feature or fix per PR
3. **Test your changes** — run existing tests and add new ones if applicable
4. **Update documentation** if your change affects user-facing behavior
5. **Write a clear PR description** explaining what and why

### Commit Messages

Use clear, descriptive commit messages:

```
feat: add staleness detection for stuck in_progress tickets
fix: use UTC time for Leantime date comparisons
docs: add getting-started guide for new users
```

### Code Style

- **Python**: Follow PEP 8. Use type hints for function signatures.
- **JavaScript/TypeScript**: Follow the existing ESLint configuration.
- **YAML**: 2-space indentation.
- **No credentials in code**: All secrets go in `.env` (see `.env.example`).

## Project Structure

- `services/agents-mcp/` — The core MCP daemon (Python). Start here for backend changes.
- `services/agents-mcp/web/` — The Web UI (React + Vite + Tailwind).
- `templates/` — Agent template resources (CLAUDE.md, skills). Each subdirectory is a role template.
- `templates/shared/` — Skills shared across all agents (leantime, daily-journal, etc.).
- `.claude/agents/` — Native agent definitions (YAML frontmatter + system prompt).
- `agents/` — (generated, gitignored) Runtime agent workspaces created by `setup-agents.py`.
- `tests/` — E2E test environment tooling.

## Reporting Issues

- Use [GitHub Issues](https://github.com/anthropics/agent-hub/issues) for bug reports and feature requests
- Include steps to reproduce for bugs
- For security vulnerabilities, please email security@example.com instead of opening a public issue

## License

By contributing to Agent-Hub, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE). Contributions to Leantime plugins (`services/leantime/plugins/`) are subject to AGPL-3.0.

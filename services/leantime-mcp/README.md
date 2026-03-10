<!--
SPDX-FileCopyrightText: 2025 Daniel Eder

SPDX-License-Identifier: CC0-1.0
-->

# Leantime MCP Server

A Model Context Protocol (MCP) server that provides AI assistants with access to Leantime's (leantime.io) JsonRPC 2.0 API. This enables AI tools like Claude to interact with Leantime projects, tickets, timesheets, users, and more through a standardized interface.

This server uses [FastMCP](https://github.com/jlowin/fastmcp) which supports multiple transport protocols including stdio, HTTP, WebSocket, and SSE, making it suitable for various deployment scenarios.

The leantime mcp plugin is not needed.
If you own the leantime mcp plugin consider using https://github.com/Leantime/php-mcp-server instead.

## MCP Client Configuration

This project uses [uv](https://github.com/astral-sh/uv) for fast, reliable Python package management. Ensure it is installed before modifying your MCP settings.

To use with Claude Desktop or other MCP clients, add to your MCP settings:

### STDIO Transport (Default)

For local MCP clients like Claude Desktop that communicate via standard input/output:

```json
{
  "mcpServers": {
    "leantime": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/daniel-eder/leantime-mcp.git",
        "leantime-mcp"
      ],
      "env": {
        "LEANTIME_URL": "https://your-leantime-instance.com",
        "LEANTIME_API_KEY": "your_api_key_here",
        "LEANTIME_USER_EMAIL": "your_email@example.com"
      }
    }
  }
}
```

### HTTP Transport

For remote HTTP connections, first start the server with HTTP transport (see [Running the Server](#running-the-server)), then configure your MCP client to connect to the HTTP endpoint:

```json
{
  "mcpServers": {
    "leantime-http": {
      "url": "http://localhost:8000/mcp",
      "transport": "streamableHttp"
    }
  }
}
```

**Note:** The HTTP transport configuration depends on your MCP client's support for HTTP connections. The server must be running separately using the `fastmcp run` command with `--transport http` option. Make sure to set the required environment variables (`LEANTIME_URL`, `LEANTIME_API_KEY`, `LEANTIME_USER_EMAIL`) when starting the HTTP server.

## Getting a Leantime API Key

1. Log in to your Leantime instance
2. Go to Company -> API Keys 
3. Generate a new API key

## Running the Server

This server supports multiple transport protocols for different deployment scenarios:

### STDIO Transport (Default)

For use with MCP clients like Claude Desktop that communicate via standard input/output:

```bash
# Using the entry point
leantime-mcp

# Or run directly
python -m src.leantime_mcp.server
```

### HTTP Transport

For remote access via HTTP, useful for web services and remote clients:

```bash
# Run on default port 8000
fastmcp run src/leantime_mcp/server.py:app --transport http

# Run on custom port
fastmcp run src/leantime_mcp/server.py:app --transport http --port 9000

# When developing (without installing the package), use uv run:
uv run fastmcp run src/leantime_mcp/server.py:app --transport http
```

Once running, the MCP endpoint will be available at `http://localhost:8000/mcp` (or your custom network address/port).

### SSE Transport (Legacy)

Server-Sent Events transport for legacy web applications:

```bash
fastmcp run src/leantime_mcp/server.py:app --transport sse --port 8000
```

### Using FastMCP CLI

The FastMCP CLI provides additional options and better control:

```bash
# See all available options
fastmcp run --help

# Run with debug logging
fastmcp run src/leantime_mcp/server.py:app --transport http --log-level DEBUG
```

### Environment Variables

Set these environment variables for all transport types:

```bash
export LEANTIME_URL="https://your-leantime-instance.com"
export LEANTIME_API_KEY="your_api_key_here"
export LEANTIME_USER_EMAIL="your_email@example.com"
```

## Available Tools

The server provides the following MCP tools:

- `get_project` - Get details of a specific project
- `list_projects` - List all accessible projects
- `create_project` - Create a new project
- `get_ticket` - Get ticket/task details
- `list_tickets` - List tickets (optionally filtered by project)
- `create_ticket` - Create a new ticket
- `update_ticket` - Update an existing ticket
- `get_user` - Get user details
- `list_users` - List all users
- `add_comment` - Add a comment to a ticket or project
- `get_comments` - Get comments for a module
- `add_timesheet` - Log time to a ticket
- `get_timesheets` - Query timesheet entries


## Development

### Setup Development Environment

```bash
# Clone the repository
git clone https://github.com/daniel-eder/leantime-mcp.git
cd leantime-mcp

# Sync dependencies (includes dev dependencies)
uv sync

# Run from source
uv run leantime-mcp
```

## Links

- [Leantime](https://leantime.io/)
- [Leantime API Documentation](https://docs.leantime.io/api/README)
- [Model Context Protocol](https://modelcontextprotocol.io/)
- [MCP Specification](https://spec.modelcontextprotocol.io/)

## Licensing

This project uses [REUSE](https://reuse.software/) for clear and comprehensive licensing information, following the [FSFE REUSE specification](https://reuse.software/spec/).

### License Information

All files contain SPDX license headers for clear identification. To check compliance:

```bash
uvx reuse lint
```
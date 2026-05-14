# loki-mcp

MCP server that exposes [Grafana Loki](https://grafana.com/oss/loki/) log querying as tools for Claude and other MCP clients.

## Tools

| Tool | Description |
| --- | --- |
| `query_logs` | Instant LogQL query at a point in time |
| `query_range` | LogQL range query — returns log lines or metric matrices |
| `get_labels` | List all label names within a time window |
| `get_label_values` | Values for a specific label, with optional stream selector |
| `get_series` | Discover streams matching a label selector |
| `get_stats` | Log volume / index stats without fetching log data |

All time parameters accept ISO-8601 strings, Unix epoch, or friendly offsets such as `1h`, `30m`, `2d`.

---

## Dev environment setup

**Requirements:** Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/)

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repo and enter the directory
git clone <repo-url> loki-mcp
cd loki-mcp

# Install the package and all dev dependencies
uv sync --extra dev

# Activate the virtual environment
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Copy the environment template and fill in your Loki details
cp src/loki_mcp/.env.example .env
```

Edit `.env`:

```dotenv
# Local Loki
LOKI_URL=http://localhost:3100
LOKI_USERNAME=
LOKI_PASSWORD=

# Grafana Cloud — set USERNAME to your numeric org ID, PASSWORD to an API token
# LOKI_URL=https://logs-prod-<region>.grafana.net
# LOKI_USERNAME=123456
# LOKI_PASSWORD=glc_...
```

### pip (alternative)

```bash
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

---

## Starting the MCP server

### stdio transport (default — used by Claude Desktop / Claude Code)

```bash
uv run python -m loki_mcp.server
```

### HTTP / SSE transport

```bash
uv run fastmcp run src/loki_mcp/server.py --transport sse --port 8000
```

---

## Connecting to Claude

### Claude Code (CLI)

```bash
claude mcp add loki \
  --command "uv" \
  --args "run python -m loki_mcp.server" \
  --env LOKI_URL=http://localhost:3100
```

Or add it manually to `.claude/settings.json`:

```json
{
  "mcpServers": {
    "loki": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/loki-mcp", "python", "-m", "loki_mcp.server"],
      "env": {
        "LOKI_URL": "http://localhost:3100",
        "LOKI_USERNAME": "",
        "LOKI_PASSWORD": ""
      }
    }
  }
}
```

### VS Code

VS Code reads MCP servers from `.vscode/mcp.json` in the workspace root. A pre-filled file is already included in this repo — open the project folder in VS Code and it will be picked up automatically.

To customise it, edit [.vscode/mcp.json](.vscode/mcp.json):

```json
{
  "servers": {
    "loki": {
      "type": "stdio",
      "command": "uv",
      "args": [
        "run",
        "--directory", "/path/to/loki-mcp",
        "python", "-m", "loki_mcp.server"
      ],
      "env": {
        "LOKI_URL": "http://localhost:3100",
        "LOKI_USERNAME": "",
        "LOKI_PASSWORD": ""
      }
    }
  }
}
```

Or pass the URL as a CLI flag instead of an env var:

```json
"args": ["run", "--directory", "/path/to/loki-mcp", "python", "-m", "loki_mcp.server", "--loki-url", "http://my-loki:3100"]
```

To start the server: open the **Command Palette** (`Cmd+Shift+P`) → **MCP: Start Server** → select **loki**.

---

### Claude Desktop

Merge the following into `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "loki": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/loki-mcp", "python", "-m", "loki_mcp.server"],
      "env": {
        "LOKI_URL": "http://localhost:3100",
        "LOKI_USERNAME": "",
        "LOKI_PASSWORD": ""
      }
    }
  }
}
```

A pre-filled example is available in [`claude_mcp_config.json`](claude_mcp_config.json).

---

## Example queries

```text
# Last 100 error lines from the prod namespace
query_range(query='{namespace="prod"} |= "error"', start="1h")

# Count log lines per app over the last 30 minutes
query_range(query='sum by (app) (count_over_time({namespace="prod"}[5m]))', start="30m")

# Discover all streams in a namespace
get_series(match='{namespace="prod"}')

# Find all label names available today
get_labels(start="24h")

# Check log volume before running a heavy query
get_stats(query='{app="payment-service"}', start="6h")
```

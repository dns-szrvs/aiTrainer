# aiTrainer

Personal workout coach as a Python MCP server for OpenClaw. Chat over Telegram, log exercises in natural language, and let the agent read structured progress from SQLite.

## Features

- Log exercises, sets, reps, weights, optional RPE, and notes
- Automatic workout session grouping (same day + within idle timeout)
- Exercise aliases (`bench`, `bench press`, etc.)
- Progress signals: estimated 1RM, personal bests, volume trend, sessions since last increase
- MCP stdio transport for OpenClaw

## Requirements

- Python 3.11+
- Linux target machine (also works on macOS for development)

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run locally

```bash
aicoach-mcp
```

Or:

```bash
python -m aicoach.server
```

## Configuration

Environment variables:

| Variable | Default | Description |
| --- | --- | --- |
| `AICOACH_DB_PATH` | `~/.local/share/aicoach/aicoach.db` | SQLite database path |
| `AICOACH_DEFAULT_UNIT` | `kg` | Default weight unit |
| `AICOACH_IDLE_TIMEOUT_SECONDS` | `10800` (3h) | Auto-close idle workout sessions |

## OpenClaw setup

Add aiCoach to your OpenClaw MCP config. On a standard install this lives in `~/.openclaw/openclaw.json`.

### Option A: CLI helper

```bash
openclaw mcp set aicoach '{
  "command": "/path/to/aicoach/.venv/bin/aicoach-mcp",
  "env": {
    "AICOACH_DB_PATH": "/home/you/.local/share/aicoach/aicoach.db"
  }
}'
```

### Option B: direct JSON config

```json
{
  "mcpServers": {
    "aicoach": {
      "command": "/path/to/aicoach/.venv/bin/aicoach-mcp",
      "args": [],
      "env": {
        "AICOACH_DB_PATH": "/home/you/.local/share/aicoach/aicoach.db"
      }
    }
  }
}
```

Notes:

- A `command` field means OpenClaw launches the server over stdio automatically.
- Use the absolute path to your virtualenv binary on the Linux host.
- Restart or reload OpenClaw after changing MCP config.

## Agent prompt

Copy [`prompts/coach_instructions.md`](prompts/coach_instructions.md) into your OpenClaw agent instructions so the model knows when to call aiCoach tools.

## MCP tools

| Tool | Purpose |
| --- | --- |
| `log_workout` | Log one exercise and attach it to the current session |
| `get_current_workout` | Show the open session and exercises logged so far |
| `get_exercise_history` | Recent sessions for one exercise |
| `get_recent_workouts` | Recent sessions across exercises |
| `get_progress` | Coaching signals for one exercise |
| `list_exercises` | Known exercises and aliases |

## Example tool input

```json
{
  "exercise": "squat",
  "sets": [
    {"reps": 5, "weight": 100},
    {"reps": 5, "weight": 100},
    {"reps": 5, "weight": 100}
  ],
  "note": "moved well"
}
```

## Tests

```bash
pytest
```

MCP stdio smoke test:

```bash
python scripts/mcp_smoke_test.py
```

## OpenClaw example config

See [`examples/openclaw-mcp-snippet.json`](examples/openclaw-mcp-snippet.json) for a copy-paste MCP server entry.

## Project layout

```text
aicoach/
  config.py      # settings and env vars
  db.py          # sqlite schema
  repository.py  # storage and session logic
  progress.py    # coaching signals
  server.py      # MCP server
prompts/
  coach_instructions.md
tests/
```

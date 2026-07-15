"""Smoke test for aiCoach MCP stdio server."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    db_path = repo_root / ".smoke-test.db"
    if db_path.exists():
        db_path.unlink()

    os.environ["AICOACH_DB_PATH"] = str(db_path)
    server_params = StdioServerParameters(
        command=str(repo_root / ".venv" / "bin" / "aicoach-mcp"),
        args=[],
        env={**os.environ},
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            tool_names = sorted(tool.name for tool in tools.tools)
            expected = {
                "delete_exercise_from_session",
                "delete_session",
                "get_current_workout",
                "get_exercise_history",
                "get_progress",
                "get_recent_workouts",
                "get_session",
                "list_exercises",
                "log_workout",
                "update_session",
                "update_workout_set",
            }
            assert expected.issubset(set(tool_names)), tool_names

            log_result = await session.call_tool(
                "log_workout",
                {
                    "exercise": "bench press",
                    "sets": [
                        {"reps": 8, "weight": 60},
                        {"reps": 8, "weight": 60},
                    ],
                    "note": "smoke test",
                },
            )
            log_payload = json.loads(log_result.content[0].text)
            assert log_payload["exercise"]["canonical_name"] == "Bench Press"
            assert log_payload["session"]["exercise_count"] == 1

            current = await session.call_tool("get_current_workout", {})
            current_payload = json.loads(current.content[0].text)
            assert current_payload["exercises"][0]["exercise"] == "Bench Press"

            progress = await session.call_tool("get_progress", {"exercise": "bench"})
            progress_payload = json.loads(progress.content[0].text)
            assert progress_payload["sessions_logged"] == 1

    print("MCP smoke test passed")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(f"MCP smoke test failed: {exc}", file=sys.stderr)
        raise

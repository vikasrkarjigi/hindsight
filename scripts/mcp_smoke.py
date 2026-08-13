#!/usr/bin/env python3
"""Smoke-test the MCP surface over real stdio transport.

    python scripts/mcp_smoke.py              # list tools + call memory_stats
    python scripts/mcp_smoke.py --full       # also call every retrieval tool

Kept out of the demo path on purpose: this is the "does the MCP wiring actually
speak the protocol" check, not the pitch.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

CALLS = [
    ("memory_stats", {}),
    ("check_bug", {"error": "pool timed out waiting for connection, ECONNRESET on checkout"}),
    ("explain", {"subject": "the body parser middleware ordering"}),
    ("precedent", {"proposal": "split the monolith into microservices"}),
    ("page_owner", {"symptoms": "502s and cache hit rate collapsed after deploy"}),
    ("who_knows", {"file_path": "lib/http/retry.js"}),
    ("contradictions", {"topic": "adding an ORM layer"}),
    ("review_pr", {"diff": "diff --git a/lib/http/retry.js b/lib/http/retry.js\n+++ b/lib/http/retry.js\n+  await sleep(200)\n", "title": "Add retry logic"}),
]


async def main(full: bool) -> int:
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "imem.mcp_server"], cwd=str(ROOT)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = [t.name for t in listed.tools]
            print(f"tools/list → {len(names)}: {', '.join(names)}")

            calls = CALLS if full else CALLS[:1]
            failures = 0
            for name, args in calls:
                try:
                    res = await session.call_tool(name, args)
                    payload = res.content[0].text if res.content else ""
                    parsed = json.loads(payload)
                    head = json.dumps(parsed)[:160]
                    print(f"  ✅ {name:<16} {head}")
                except Exception as e:  # noqa: BLE001
                    failures += 1
                    print(f"  ❌ {name:<16} {type(e).__name__}: {e}")
            return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--full", action="store_true", help="call every tool, not just memory_stats")
    raise SystemExit(asyncio.run(main(ap.parse_args().full)))

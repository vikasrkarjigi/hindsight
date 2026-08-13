"""MCP server — the product surface.

This is not a chat app. It is plug-and-play infrastructure: point Claude Code,
Cursor, or a Slack bot at it and the team's institutional memory becomes a tool
the model can call mid-task, at the moment the engineer actually needs it.

Run:  python -m imem.mcp_server          (stdio transport)
"""
from __future__ import annotations

import json
import logging
from typing import Optional

try:  # mcp >= 2.0 renamed the high-level server
    from mcp.server import MCPServer as _Server
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as _Server

from . import tools

logging.basicConfig(level=logging.INFO)

mcp = _Server("institutional-memory")


def _j(obj) -> str:
    return json.dumps(obj, indent=2, default=str)


@mcp.tool()
def check_bug(error: str, repo: Optional[str] = None) -> str:
    """Given an error trace or bug description, surface the closest prior fix from the
    team's history — the actual diff that fixed it and the engineer who wrote it.
    Use this BEFORE debugging anything that smells like it has been seen before."""
    return _j(tools.check_bug(error, repo=repo))


@mcp.tool()
def review_pr(diff: str, title: str = "", repo: Optional[str] = None) -> str:
    """Review a pull request diff against the team's history. Flags when the change
    reintroduces a pattern that was previously tried and reverted, and suggests the
    reviewers who have actually worked on the touched files."""
    return _j(tools.review_pr(diff, title=title, repo=repo))


@mcp.tool()
def explain(subject: str, repo: Optional[str] = None) -> str:
    """Explain WHY a confusing file, function, or design looks the way it does, by
    recovering the original reasoning from historical PRs, review comments,
    architecture decision records and Slack threads."""
    return _j(tools.explain(subject, repo=repo))


@mcp.tool()
def precedent(proposal: str, repo: Optional[str] = None) -> str:
    """Check whether an architectural proposal has already been debated, tried, or
    rejected by this team — and what the recorded reasoning was. Use before writing
    a design doc."""
    return _j(tools.precedent(proposal, repo=repo))


@mcp.tool()
def page_owner(symptoms: str, repo: Optional[str] = None) -> str:
    """During a live incident, recommend which engineer to page, based on who
    actually resolved the closest matching past incident."""
    return _j(tools.page_owner(symptoms, repo=repo))


@mcp.tool()
def who_knows(file_path: str) -> str:
    """People-index: the top historical contributors for a given file or topic,
    with evidence of what they touched and when."""
    return _j(tools.who_knows(file_path))


@mcp.tool()
def contradictions(topic: str) -> str:
    """Detect when two historical decisions about the same topic point in opposite
    directions, so a stale decision is not applied as current policy."""
    return _j(tools.contradictions(topic))


@mcp.tool()
def memory_stats() -> str:
    """How much institutional memory is loaded, broken down by event type."""
    return _j(tools.memory_stats())


if __name__ == "__main__":
    mcp.run()

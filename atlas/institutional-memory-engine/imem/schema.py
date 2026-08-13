"""The polymorphic event document.

ONE shape holds a git commit, a PR, a review comment, a postmortem, an
architecture decision and a Slack thread. Type-specific data goes in `meta`,
which is exactly the flexibility a relational schema would have made painful.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc(dt: Optional[datetime]) -> datetime:
    if dt is None:
        return datetime.now(timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def make_event(
    *,
    type: str,
    external_id: str,
    title: str,
    body: str = "",
    repo: str = "",
    author: Optional[Dict[str, Any]] = None,
    ts: Optional[datetime] = None,
    files: Optional[List[str]] = None,
    url: str = "",
    diff: str = "",
    reverted: bool = False,
    reverts: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    files = files or []
    author = author or {}
    meta = meta or {}

    # `text` is the single field that gets embedded. Packing the title, body,
    # touched files and a diff excerpt into one blob is what makes a raw stack
    # trace match a two-year-old commit message.
    parts = [f"[{type}] {title}", body.strip()]
    if files:
        parts.append("Files: " + ", ".join(files[:25]))
    if diff:
        parts.append("Diff:\n" + diff[:4000])
    text = "\n\n".join(p for p in parts if p).strip()

    return {
        "type": type,
        "external_id": external_id or hashlib.sha1(text.encode()).hexdigest(),
        "title": title[:500],
        "body": body,
        "text": text,
        "repo": repo,
        "author": author,
        "ts": utc(ts),
        "files": files,
        "url": url,
        "diff": diff[:20000],
        "reverted": reverted,
        "reverts": reverts,
        "meta": meta,
        "ingested_at": datetime.now(timezone.utc),
    }


def summarize(doc: Dict[str, Any], body_chars: int = 400) -> Dict[str, Any]:
    """Trim an event for tool output — agents get signal, not a document dump."""
    return {
        "type": doc.get("type"),
        "title": doc.get("title"),
        "author": (doc.get("author") or {}).get("name")
        or (doc.get("author") or {}).get("login"),
        "date": doc["ts"].date().isoformat() if doc.get("ts") else None,
        "url": doc.get("url"),
        "files": (doc.get("files") or [])[:8],
        "excerpt": (doc.get("body") or "")[:body_chars],
        "reverted": doc.get("reverted", False),
        "score": round(doc.get("score", 0.0), 4),
        "raw_score": round(doc.get("raw_score", doc.get("score", 0.0)), 4),
        "age_days": doc.get("age_days"),
    }

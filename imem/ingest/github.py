"""Ingest real engineering history from GitHub into the polymorphic `events`
collection: commits (with diffs), pull requests, and review comments.

Revert detection is the money feature — it is what lets review_pr say
"you are about to reintroduce something we already backed out."
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

import httpx
from pymongo import UpdateOne

from .. import config, db, embeddings
from ..schema import make_event

log = logging.getLogger(__name__)
API = "https://api.github.com"

REVERT_RE = re.compile(r'^Revert\s+"?(.+?)"?\s*$', re.M)
REVERT_SHA_RE = re.compile(r"This reverts commit ([0-9a-f]{7,40})", re.I)


def _headers() -> Dict[str, str]:
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if config.GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    return h


def _get(client: httpx.Client, path: str, **params) -> Any:
    for attempt in range(4):
        r = client.get(f"{API}{path}", params=params, headers=_headers(), timeout=30)
        if r.status_code == 403 and "rate limit" in r.text.lower():
            reset = int(r.headers.get("x-ratelimit-reset", 0))
            wait = max(min(reset - time.time(), 60), 5)
            log.warning("Rate limited — sleeping %.0fs (set GITHUB_TOKEN to avoid this)", wait)
            time.sleep(wait)
            continue
        if r.status_code >= 500:
            time.sleep(2 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"GitHub request failed: {path}")


def _ts(s: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def _author(obj: Dict[str, Any], fallback: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    user = obj or {}
    fb = fallback or {}
    return {
        "login": user.get("login") or fb.get("name"),
        "name": fb.get("name") or user.get("login"),
        "email": fb.get("email"),
    }


def fetch_commits(client: httpx.Client, repo: str, limit: int, with_diff: bool) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    page = 1
    while len(out) < limit:
        batch = _get(client, f"/repos/{repo}/commits", per_page=100, page=page)
        if not batch:
            break
        out.extend(batch)
        page += 1
        if page > 10:
            break
    out = out[:limit]

    if not with_diff:
        return out

    detailed = []
    for i, c in enumerate(out):
        try:
            detailed.append(_get(client, f"/repos/{repo}/commits/{c['sha']}"))
        except Exception as e:  # keep the shallow record rather than losing the event
            log.warning("commit detail failed for %s: %s", c["sha"][:8], e)
            detailed.append(c)
        if (i + 1) % 25 == 0:
            log.info("  fetched %d/%d commit details", i + 1, len(out))
    return detailed


def fetch_pulls(client: httpx.Client, repo: str, limit: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    page = 1
    while len(out) < limit:
        batch = _get(client, f"/repos/{repo}/pulls", state="closed", per_page=100, page=page, sort="updated", direction="desc")
        if not batch:
            break
        out.extend(batch)
        page += 1
        if page > 5:
            break
    return out[:limit]


def fetch_review_comments(client: httpx.Client, repo: str, limit: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    page = 1
    while len(out) < limit:
        batch = _get(client, f"/repos/{repo}/pulls/comments", per_page=100, page=page, sort="created", direction="desc")
        if not batch:
            break
        out.extend(batch)
        page += 1
        if page > 5:
            break
    return out[:limit]


def build_events(repo: str, commits, pulls, comments) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    reverted_shas: set[str] = set()
    reverted_titles: set[str] = set()

    # Pass 1 — find what got reverted.
    for c in commits:
        msg = (c.get("commit") or {}).get("message", "")
        if msg.lower().startswith("revert"):
            m = REVERT_SHA_RE.search(msg)
            if m:
                reverted_shas.add(m.group(1)[:7])
            t = REVERT_RE.search(msg)
            if t:
                reverted_titles.add(t.group(1).strip().lower())

    # Pass 2 — build documents.
    for c in commits:
        commit = c.get("commit") or {}
        msg = commit.get("message", "")
        title, _, body = msg.partition("\n")
        files = [f["filename"] for f in c.get("files", [])]
        diff = "\n".join(
            f"--- a/{f['filename']}\n+++ b/{f['filename']}\n{f.get('patch','')}"
            for f in c.get("files", [])[:12]
            if f.get("patch")
        )
        sha = c.get("sha", "")
        is_reverted = sha[:7] in reverted_shas or title.strip().lower() in reverted_titles
        reverts_match = REVERT_SHA_RE.search(msg)

        events.append(
            make_event(
                type="commit",
                external_id=f"{repo}:commit:{sha}",
                title=title.strip() or sha[:8],
                body=body.strip(),
                repo=repo,
                author=_author(c.get("author"), (commit.get("author") or {})),
                ts=_ts((commit.get("author") or {}).get("date")),
                files=files,
                url=c.get("html_url", ""),
                diff=diff,
                reverted=is_reverted,
                reverts=reverts_match.group(1) if reverts_match else None,
                meta={"sha": sha, "stats": c.get("stats", {}), "is_revert": msg.lower().startswith("revert")},
            )
        )

    for p in pulls:
        title = p.get("title", "")
        events.append(
            make_event(
                type="pull_request",
                external_id=f"{repo}:pr:{p['number']}",
                title=title,
                body=p.get("body") or "",
                repo=repo,
                author=_author(p.get("user")),
                ts=_ts(p.get("merged_at") or p.get("closed_at") or p.get("created_at")),
                url=p.get("html_url", ""),
                reverted=title.strip().lower() in reverted_titles,
                meta={
                    "number": p["number"],
                    "merged": bool(p.get("merged_at")),
                    "state": p.get("state"),
                    "labels": [l["name"] for l in p.get("labels", [])],
                },
            )
        )

    for cm in comments:
        pr_no = (cm.get("pull_request_url") or "").rsplit("/", 1)[-1]
        events.append(
            make_event(
                type="review_comment",
                external_id=f"{repo}:review_comment:{cm['id']}",
                title=f"Review comment on PR #{pr_no} ({cm.get('path','')})",
                body=cm.get("body") or "",
                repo=repo,
                author=_author(cm.get("user")),
                ts=_ts(cm.get("created_at")),
                files=[cm["path"]] if cm.get("path") else [],
                url=cm.get("html_url", ""),
                diff=cm.get("diff_hunk", "") or "",
                meta={"pr": pr_no},
            )
        )

    return events


def embed_and_upsert(events: List[Dict[str, Any]], batch: int = 25) -> int:
    col = db.events()
    reusable = db.existing_embeddings(events)
    if reusable:
        log.info("  reusing %d existing embeddings (unchanged since last ingest)", len(reusable))

    written = 0
    for i in range(0, len(events), batch):
        chunk = events[i : i + batch]
        fresh = [e for e in chunk if e["external_id"] not in reusable]
        vectors = embeddings.embed([e["text"] for e in fresh], input_type="document") if fresh else []
        for e, v in zip(fresh, vectors):
            e["embedding"] = v
        for e in chunk:
            if e["external_id"] in reusable:
                e["embedding"] = reusable[e["external_id"]]

        ops = [UpdateOne({"external_id": e["external_id"]}, {"$set": e}, upsert=True) for e in chunk]
        col.bulk_write(ops, ordered=False)
        written += len(ops)
        log.info("  embedded + upserted %d/%d", written, len(events))
    return written


def ingest_repo(
    repo: Optional[str] = None,
    max_commits: int = 150,
    max_pulls: int = 80,
    max_comments: int = 120,
) -> Dict[str, Any]:
    repo = repo or config.GITHUB_REPO
    with_diff = bool(config.GITHUB_TOKEN)
    if not with_diff:
        max_commits, max_pulls, max_comments = 25, 20, 20
        log.warning("No GITHUB_TOKEN — running a small unauthenticated ingest (60 req/hr cap).")

    with httpx.Client(follow_redirects=True) as client:
        log.info("Fetching commits from %s ...", repo)
        commits = fetch_commits(client, repo, max_commits, with_diff)
        log.info("Fetching pull requests ...")
        pulls = fetch_pulls(client, repo, max_pulls)
        log.info("Fetching review comments ...")
        comments = fetch_review_comments(client, repo, max_comments)

    events = build_events(repo, commits, pulls, comments)
    reverted = sum(1 for e in events if e["reverted"])
    log.info("Built %d events (%d marked reverted). Embedding ...", len(events), reverted)
    written = embed_and_upsert(events)
    return {
        "repo": repo,
        "commits": len(commits),
        "pull_requests": len(pulls),
        "review_comments": len(comments),
        "events_written": written,
        "reverted_events": reverted,
    }

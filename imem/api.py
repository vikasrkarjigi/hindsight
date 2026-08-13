"""HTTP backend: the same five tools over REST, plus a live dashboard fed by
MongoDB change streams.

Run:  uvicorn imem.api:app --reload --port 8000
Then: http://localhost:8000
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from . import db, tools

log = logging.getLogger(__name__)
app = FastAPI(title="Institutional Memory Engine", version="1.0.0")
HERE = Path(__file__).parent


class BugReq(BaseModel):
    error: str
    repo: Optional[str] = None


class PRReq(BaseModel):
    diff: str
    title: str = ""
    repo: Optional[str] = None


class TextReq(BaseModel):
    query: str
    repo: Optional[str] = None


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return (HERE / "dashboard.html").read_text()


@app.get("/health")
def health():
    return db.ping()


@app.get("/stats")
def stats():
    return tools.memory_stats()


@app.post("/tools/check_bug")
def t_check_bug(r: BugReq):
    return tools.check_bug(r.error, repo=r.repo)


@app.post("/tools/review_pr")
def t_review_pr(r: PRReq):
    return tools.review_pr(r.diff, title=r.title, repo=r.repo)


@app.post("/tools/explain")
def t_explain(r: TextReq):
    return tools.explain(r.query, repo=r.repo)


@app.post("/tools/precedent")
def t_precedent(r: TextReq):
    return tools.precedent(r.query, repo=r.repo)


@app.post("/tools/page_owner")
def t_page_owner(r: TextReq):
    return tools.page_owner(r.query, repo=r.repo)


@app.post("/tools/who_knows")
def t_who_knows(r: TextReq):
    return tools.who_knows(r.query)


@app.post("/tools/contradictions")
def t_contradictions(r: TextReq):
    return tools.contradictions(r.query)


@app.get("/stream")
async def stream():
    """Server-sent events driven by a MongoDB change stream — new memory appears
    on the dashboard the instant it lands in Atlas."""

    async def gen():
        loop = asyncio.get_running_loop()
        col = db.events()
        cursor = col.watch(full_document="updateLookup")
        yield f"event: stats\ndata: {json.dumps(tools.memory_stats(), default=str)}\n\n"
        try:
            while True:
                change = await loop.run_in_executor(None, lambda: next(cursor, None))
                if change is None:
                    await asyncio.sleep(0.2)
                    continue
                doc = change.get("fullDocument") or {}
                payload = {
                    "op": change.get("operationType"),
                    "type": doc.get("type"),
                    "title": (doc.get("title") or "")[:140],
                    "author": (doc.get("author") or {}).get("name"),
                    "ts": str(doc.get("ts")),
                    "reverted": doc.get("reverted", False),
                }
                yield f"event: memory\ndata: {json.dumps(payload, default=str)}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        finally:
            # Browser refreshes close the generator; without this each one leaks a
            # change stream (and the thread blocked on it) for the process lifetime.
            cursor.close()

    return StreamingResponse(gen(), media_type="text/event-stream")

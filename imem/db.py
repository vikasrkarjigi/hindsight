"""MongoDB Atlas connection + one-command index bootstrap.

The whole system is ONE collection (`events`) and ONE vector index. That is the
architectural bet: polymorphic documents mean a commit, a postmortem and a Slack
thread are all retrievable by the same query, so a question never has to know
which system the answer came from.
"""
from __future__ import annotations

import functools
import logging
import time

from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.collection import Collection
from pymongo.operations import SearchIndexModel

from . import config, embeddings

log = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def client() -> MongoClient:
    return MongoClient(config.require_uri(), appname="institutional-memory-engine")


def events() -> Collection:
    return client()[config.MONGODB_DB][config.MONGODB_COLLECTION]


def ping() -> dict:
    c = client()
    c.admin.command("ping")
    col = events()
    return {
        "ok": True,
        "database": config.MONGODB_DB,
        "collection": config.MONGODB_COLLECTION,
        "event_count": col.estimated_document_count(),
        "embedding_provider": embeddings.provider(),
        "embedding_dims": embeddings.dimensions(),
    }


def existing_embeddings(docs) -> dict:
    """Vectors we can reuse: same external_id AND identical embedded text.

    Embedding is the only slow, rate-limited, billable step of an ingest, so
    re-running the ingester should cost nothing for history already loaded.
    """
    ids = [d["external_id"] for d in docs]
    if not ids:
        return {}
    cached = {
        doc["external_id"]: (doc.get("text", ""), doc["embedding"])
        for doc in events().find(
            {"external_id": {"$in": ids}, "embedding": {"$exists": True}},
            {"external_id": 1, "text": 1, "embedding": 1},
        )
    }
    return {
        d["external_id"]: cached[d["external_id"]][1]
        for d in docs
        if d["external_id"] in cached and cached[d["external_id"]][0] == d["text"]
    }


# ── index bootstrap ──────────────────────────────────────────────────────────

def vector_index_definition() -> dict:
    return {
        "fields": [
            {
                "type": "vector",
                "path": "embedding",
                "numDimensions": embeddings.dimensions(),
                "similarity": "cosine",
            },
            # Pre-filters let one index serve all five tools:
            #   review_pr filters type in [commit, pull_request]
            #   precedent filters type in [architecture_decision, pull_request]
            {"type": "filter", "path": "type"},
            {"type": "filter", "path": "repo"},
            {"type": "filter", "path": "reverted"},
        ]
    }


def text_index_definition() -> dict:
    """Lexical index — powers hybrid search so exact error strings
    (e.g. 'ECONNRESET') are never lost to fuzzy vector similarity."""
    return {
        "mappings": {
            "dynamic": False,
            "fields": {
                "text": {"type": "string"},
                "title": {"type": "string"},
                "type": {"type": "token"},
                "files": {"type": "string"},
            },
        }
    }


def ensure_indexes(wait: bool = True) -> dict:
    col = events()
    col.create_index([("external_id", ASCENDING)], unique=True, sparse=True)
    col.create_index([("type", ASCENDING), ("ts", DESCENDING)])
    col.create_index([("files", ASCENDING)])
    col.create_index([("author.login", ASCENDING)])

    existing = {ix["name"] for ix in col.list_search_indexes()}
    created = []

    if config.VECTOR_INDEX not in existing:
        col.create_search_index(
            SearchIndexModel(
                definition=vector_index_definition(),
                name=config.VECTOR_INDEX,
                type="vectorSearch",
            )
        )
        created.append(config.VECTOR_INDEX)

    if config.TEXT_INDEX not in existing:
        col.create_search_index(
            SearchIndexModel(
                definition=text_index_definition(),
                name=config.TEXT_INDEX,
                type="search",
            )
        )
        created.append(config.TEXT_INDEX)

    if wait and created:
        log.info("Waiting for Atlas to build %s ...", ", ".join(created))
        deadline = time.time() + 300
        while time.time() < deadline:
            states = {ix["name"]: ix.get("status") for ix in col.list_search_indexes()}
            if all(states.get(n) == "READY" for n in created):
                break
            time.sleep(5)

    return {
        "created": created,
        "indexes": [
            {"name": ix["name"], "status": ix.get("status")}
            for ix in col.list_search_indexes()
        ],
    }


def drop_search_indexes() -> None:
    """Needed if you switch embedding provider — dimensions change."""
    col = events()
    for ix in col.list_search_indexes():
        col.drop_search_index(ix["name"])

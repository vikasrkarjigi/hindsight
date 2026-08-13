"""Retrieval layer: vector search, lexical search, RRF hybrid, staleness decay.

Every one of the five MCP tools is a thin wrapper over `recall()`.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from . import config, db, embeddings


def _filter(types: Optional[Sequence[str]], repo: Optional[str], extra: Optional[dict]) -> dict:
    clauses: List[dict] = []
    if types:
        clauses.append({"type": {"$in": list(types)}})
    if repo:
        clauses.append({"repo": repo})
    if extra:
        clauses.append(extra)
    if not clauses:
        return {}
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def vector_search(
    query: str,
    k: int = 8,
    types: Optional[Sequence[str]] = None,
    repo: Optional[str] = None,
    extra_filter: Optional[dict] = None,
    candidates_multiplier: int = 15,
) -> List[Dict[str, Any]]:
    vec = embeddings.embed_one(query, input_type="query")
    stage: Dict[str, Any] = {
        "index": config.VECTOR_INDEX,
        "path": "embedding",
        "queryVector": vec,
        "numCandidates": max(100, k * candidates_multiplier),
        "limit": k,
    }
    flt = _filter(types, repo, extra_filter)
    if flt:
        stage["filter"] = flt

    pipeline = [
        {"$vectorSearch": stage},
        {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
        {"$project": {"embedding": 0}},
    ]
    return list(db.events().aggregate(pipeline))


def text_search(
    query: str,
    k: int = 8,
    types: Optional[Sequence[str]] = None,
) -> List[Dict[str, Any]]:
    must: List[dict] = [
        {"text": {"query": query, "path": ["text", "title"], "fuzzy": {"maxEdits": 1}}}
    ]
    compound: Dict[str, Any] = {"must": must}
    if types:
        compound["filter"] = [{"in": {"path": "type", "value": list(types)}}]

    pipeline = [
        {"$search": {"index": config.TEXT_INDEX, "compound": compound}},
        {"$limit": k},
        {"$addFields": {"score": {"$meta": "searchScore"}}},
        {"$project": {"embedding": 0}},
    ]
    try:
        return list(db.events().aggregate(pipeline))
    except Exception:
        # Lexical index may still be building; hybrid degrades to pure vector.
        return []


def _rrf(rankings: List[List[Dict[str, Any]]], k_const: int = 60) -> List[Dict[str, Any]]:
    """Reciprocal Rank Fusion — merges vector + lexical hits without needing the
    two score scales to be comparable."""
    merged: Dict[str, Dict[str, Any]] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking):
            key = str(doc["_id"])
            entry = merged.setdefault(key, {**doc, "score": 0.0})
            entry["score"] += 1.0 / (k_const + rank + 1)
    return sorted(merged.values(), key=lambda d: d["score"], reverse=True)


def _decay(docs: List[Dict[str, Any]], enabled: bool = True) -> List[Dict[str, Any]]:
    """Staleness decay: an equally-relevant fix from last month should outrank
    one from four years ago, because the codebase has moved on."""
    now = datetime.now(timezone.utc)
    for d in docs:
        ts = d.get("ts")
        age = (now - ts.replace(tzinfo=timezone.utc)).days if ts else 0
        d["age_days"] = max(age, 0)
        d["raw_score"] = d.get("score", 0.0)
        if enabled and config.STALENESS_WEIGHT > 0:
            decay = 0.5 ** (d["age_days"] / max(config.STALENESS_HALF_LIFE_DAYS, 1))
            w = config.STALENESS_WEIGHT
            d["score"] = d["raw_score"] * ((1 - w) + w * decay)
    return sorted(docs, key=lambda d: d.get("score", 0.0), reverse=True)


def recall(
    query: str,
    k: int = 6,
    types: Optional[Sequence[str]] = None,
    repo: Optional[str] = None,
    extra_filter: Optional[dict] = None,
    hybrid: bool = True,
    decay: bool = True,
) -> List[Dict[str, Any]]:
    """The one retrieval call the whole product sits on."""
    pool = max(k * 3, 15)
    vec_hits = vector_search(query, k=pool, types=types, repo=repo, extra_filter=extra_filter)
    if hybrid:
        lex_hits = text_search(query, k=pool, types=types)
        docs = _rrf([vec_hits, lex_hits]) if lex_hits else vec_hits
    else:
        docs = vec_hits
    return _decay(docs, enabled=decay)[:k]


# ── aggregations (no embeddings needed) ──────────────────────────────────────

def people_index(topic_files: Sequence[str], limit: int = 5) -> List[Dict[str, Any]]:
    """Reconstruct tribal knowledge: who has actually touched this surface."""
    if not topic_files:
        return []
    pipeline = [
        {"$match": {"files": {"$in": list(topic_files)}}},
        {
            "$group": {
                "_id": {"$ifNull": ["$author.login", "$author.name"]},
                "name": {"$first": "$author.name"},
                "touches": {"$sum": 1},
                "last_touch": {"$max": "$ts"},
                "types": {"$addToSet": "$type"},
            }
        },
        {"$sort": {"touches": -1}},
        {"$limit": limit},
    ]
    out = []
    for r in db.events().aggregate(pipeline):
        if not r["_id"]:
            continue
        out.append(
            {
                "login": r["_id"],
                "name": r.get("name"),
                "touches": r["touches"],
                "last_touch": r["last_touch"].date().isoformat() if r.get("last_touch") else None,
                "evidence_types": r.get("types", []),
            }
        )
    return out


def stats() -> Dict[str, Any]:
    col = db.events()
    by_type = {
        r["_id"]: r["n"]
        for r in col.aggregate([{"$group": {"_id": "$type", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}])
    }
    newest = col.find_one({}, sort=[("ts", -1)], projection={"ts": 1, "title": 1})
    return {
        "total_events": sum(by_type.values()),
        "by_type": by_type,
        "newest": {
            "title": newest.get("title") if newest else None,
            "ts": newest["ts"].isoformat() if newest and newest.get("ts") else None,
        },
        "embedding_provider": embeddings.provider(),
        "dimensions": embeddings.dimensions(),
    }

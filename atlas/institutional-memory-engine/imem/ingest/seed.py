"""Seed the event types GitHub's API cannot give you.

A real team's institutional memory does not live only in git. It lives in
postmortems, architecture decision records, and the Slack thread where someone
explained why. These are marked `source: "seed"` so they are always
distinguishable from ingested GitHub history — the point they prove is that a
single polymorphic collection retrieves ALL of it with one query.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from pymongo import UpdateOne

from .. import config, db, embeddings
from ..schema import make_event


def _ago(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def seed_events(repo: str | None = None) -> List[Dict[str, Any]]:
    repo = repo or config.GITHUB_REPO
    S: List[Dict[str, Any]] = []

    S.append(make_event(
        type="postmortem",
        external_id="seed:pm:2024-connection-pool-exhaustion",
        title="Postmortem: 43-minute outage from connection pool exhaustion under retry storm",
        body=(
            "IMPACT: 43 minutes of 5xx on the checkout path. ROOT CAUSE: a client-side retry "
            "loop with no jitter multiplied request volume 6x during a downstream slowdown. Every "
            "retry grabbed a new connection from the pool; the pool (size 20) was exhausted in "
            "under 90 seconds and healthy requests began timing out at the acquire step, not at "
            "the database. SYMPTOMS: ECONNRESET, 'pool timed out waiting for connection', p99 "
            "latency flat then cliff. FIX: added exponential backoff with full jitter, raised pool "
            "size to 60, and added a fail-fast acquire timeout so the error surfaces as a 503 "
            "immediately instead of queueing. LESSON: retries without jitter turn a slowdown into "
            "an outage. Do not add a retry without a jitter policy and a budget."
        ),
        repo=repo, author={"login": "priya-n", "name": "Priya Nair"}, ts=_ago(214),
        files=["lib/db/pool.js", "lib/http/retry.js"],
        url="https://internal.example.com/postmortems/2024-pool-exhaustion",
        meta={"source": "seed", "severity": "SEV1", "duration_minutes": 43},
    ))

    S.append(make_event(
        type="postmortem",
        external_id="seed:pm:2025-cache-stampede",
        title="Postmortem: cache stampede after a deploy invalidated the hot key set",
        body=(
            "IMPACT: 12 minutes of elevated latency and a brief 502 spike. ROOT CAUSE: a deploy "
            "changed the cache key prefix, invalidating every hot key at once; thousands of "
            "concurrent requests missed and all went to the origin simultaneously. SYMPTOMS: "
            "origin CPU pinned, 502s from the edge, cache hit rate falling to near zero in one "
            "step. FIX: single-flight request coalescing plus staggered TTL jitter on write. "
            "LESSON: never change a cache key prefix in the same deploy as anything else, and "
            "always warm before cutting over."
        ),
        repo=repo, author={"login": "dmartin", "name": "Diego Martin"}, ts=_ago(96),
        files=["lib/cache/index.js", "lib/cache/keys.js"],
        url="https://internal.example.com/postmortems/2025-cache-stampede",
        meta={"source": "seed", "severity": "SEV2", "duration_minutes": 12},
    ))

    S.append(make_event(
        type="architecture_decision",
        external_id="seed:adr:0007-no-orm",
        title="ADR-0007: Do not introduce an ORM layer",
        body=(
            "STATUS: Accepted, then revisited twice and re-affirmed. CONTEXT: recurring proposals "
            "to add an ORM to reduce query boilerplate. DECISION: rejected. The team measured a "
            "prototype and found the generated queries defeated our compound indexes on the two "
            "hottest read paths, and the abstraction made the N+1 problem invisible in review. "
            "CONSEQUENCES: we keep hand-written queries and accept the boilerplate; we invest in a "
            "small query-builder helper instead. REVISIT IF: the query surface grows past roughly "
            "80 distinct shapes, or the driver ships first-class typed queries."
        ),
        repo=repo, author={"login": "akhan", "name": "Amina Khan"}, ts=_ago(430),
        files=["lib/db/query.js"],
        url="https://internal.example.com/adr/0007",
        meta={"source": "seed", "status": "accepted"},
    ))

    S.append(make_event(
        type="architecture_decision",
        external_id="seed:adr:0012-microservices-rejected",
        title="ADR-0012: Split the monolith into microservices — REJECTED",
        body=(
            "STATUS: Rejected. CONTEXT: proposal to extract five services to let teams deploy "
            "independently. We ran a two-week spike extracting the billing path. DECISION: "
            "rejected for now. The spike moved our single in-process transaction into a "
            "three-service saga and we could not preserve the invariant without a compensating "
            "log we did not want to own. Deploy independence was real but the on-call burden "
            "roughly tripled in the simulation. CONSEQUENCES: we stay modular-monolith and "
            "enforce module boundaries in CI instead. REVISIT IF: team count exceeds 6, or a "
            "single module's deploy cadence is blocked more than twice a sprint."
        ),
        repo=repo, author={"login": "akhan", "name": "Amina Khan"}, ts=_ago(288),
        url="https://internal.example.com/adr/0012",
        reverted=True,
        meta={"source": "seed", "status": "rejected"},
    ))

    S.append(make_event(
        type="architecture_decision",
        external_id="seed:adr:0019-vector-store",
        title="ADR-0019: Keep vectors in the primary database rather than a separate vector store",
        body=(
            "STATUS: Accepted. CONTEXT: we needed semantic retrieval over application data. "
            "OPTIONS: (a) a dedicated vector database alongside our primary store, (b) vector "
            "search inside the primary database. DECISION: (b). Option (a) required us to own a "
            "sync pipeline, a second consistency model, and a second failure domain — and every "
            "query that needed both a filter and a similarity search became a two-hop join in "
            "application code. Keeping vectors next to the documents they describe means one "
            "query does filtered semantic search atomically. CONSEQUENCES: retrieval and "
            "transactional data share a lifecycle; no bolt-on connector to operate."
        ),
        repo=repo, author={"login": "priya-n", "name": "Priya Nair"}, ts=_ago(41),
        url="https://internal.example.com/adr/0019",
        meta={"source": "seed", "status": "accepted"},
    ))

    S.append(make_event(
        type="slack_thread",
        external_id="seed:slack:middleware-order",
        title="#eng-platform: why does the body parser have to run before the auth middleware?",
        body=(
            "@jlee: reordering these two broke signature verification in staging, anyone remember why?\n"
            "@priya-n: yes — the webhook signature is computed over the RAW body. If auth runs "
            "first it reads the stream, and by the time the parser gets it the raw buffer is gone, "
            "so the HMAC never matches. We hit this in 2023 and fixed it by capturing rawBody in a "
            "verify hook. There's a comment in the file but it does not explain the ordering.\n"
            "@dmartin: this is the third time someone has rediscovered this. Adding a test that "
            "fails if the order changes.\n"
            "@jlee: adding a comment too. Thanks both."
        ),
        repo=repo, author={"login": "priya-n", "name": "Priya Nair"}, ts=_ago(158),
        files=["lib/middleware/index.js", "lib/middleware/auth.js"],
        url="https://slack.example.com/archives/C123/p1699",
        meta={"source": "seed", "channel": "#eng-platform", "replies": 4},
    ))

    S.append(make_event(
        type="slack_thread",
        external_id="seed:slack:retry-jitter",
        title="#incidents: adding retries to the payment client — do we need jitter?",
        body=(
            "@newgrad: shipping a simple 3x retry on the payment client, straightforward right?\n"
            "@priya-n: please add full jitter. A fixed-interval retry is exactly what caused the "
            "SEV1 last year — see the pool exhaustion postmortem. Synchronised retries turn a "
            "slow dependency into an outage.\n"
            "@akhan: and give it a retry budget, not just a count. Budget caps total added load."
        ),
        repo=repo, author={"login": "priya-n", "name": "Priya Nair"}, ts=_ago(73),
        files=["lib/http/retry.js"],
        url="https://slack.example.com/archives/C456/p1822",
        meta={"source": "seed", "channel": "#incidents", "replies": 3},
    ))

    S.append(make_event(
        type="slack_thread",
        external_id="seed:slack:orm-again",
        title="#architecture: has anyone looked at adding an ORM?",
        body=(
            "@newgrad: the query boilerplate is rough, should we adopt an ORM?\n"
            "@akhan: we decided against this twice — ADR-0007. The short version is that the "
            "generated queries did not use our compound indexes and N+1s became invisible in "
            "review. Not a forever no, but read the ADR before reopening it.\n"
            "@dmartin: worth noting the revisit condition is written down: ~80 query shapes."
        ),
        repo=repo, author={"login": "akhan", "name": "Amina Khan"}, ts=_ago(19),
        url="https://slack.example.com/archives/C789/p1901",
        meta={"source": "seed", "channel": "#architecture", "replies": 3},
    ))

    return S


def load_seed(repo: str | None = None) -> Dict[str, Any]:
    docs = seed_events(repo)
    vectors = embeddings.embed([d["text"] for d in docs], input_type="document")
    ops = []
    for d, v in zip(docs, vectors):
        d["embedding"] = v
        ops.append(UpdateOne({"external_id": d["external_id"]}, {"$set": d}, upsert=True))
    db.events().bulk_write(ops, ordered=False)
    return {"seeded": len(ops), "types": sorted({d["type"] for d in docs})}

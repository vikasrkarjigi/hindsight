"""Embedding provider.

Primary: Voyage AI (the MongoDB-recommended embedding partner).
Fallback: a small local sentence-transformers model, so a missing/expired key
can never kill a live demo. The active provider decides the vector dimension,
and the Atlas Vector Search index is created to match.
"""
from __future__ import annotations

import functools
import logging
import time
from typing import List, Sequence

from . import config

log = logging.getLogger(__name__)

# Voyage model -> output dimensions
_VOYAGE_DIMS = {
    "voyage-3": 1024,
    "voyage-3-lite": 512,
    "voyage-3-large": 1024,
    "voyage-code-3": 1024,
    "voyage-2": 1024,
}
_FALLBACK_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
_FALLBACK_DIMS = 384

# A Voyage account with no payment method on file is capped at 3 requests/min
# and 10K tokens/min (not the standard tier's limits). We stay comfortably
# under both rather than assume a paid account, so ingestion never hard-fails
# the way it did with the SDK's default max_retries=0.
_VOYAGE_MAX_TOKENS_PER_REQUEST = 6000
_VOYAGE_MIN_SECONDS_BETWEEN_REQUESTS = 21.0
_voyage_last_request_at = 0.0


@functools.lru_cache(maxsize=1)
def _voyage_client():
    import voyageai

    # max_retries=0: we do our own pacing + backoff below, tuned for the
    # free-tier rate limit rather than the SDK's generic exponential jitter.
    return voyageai.Client(api_key=config.VOYAGE_API_KEY, max_retries=0)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _voyage_chunks(texts: List[str]) -> List[List[str]]:
    """Group texts into request-sized batches by estimated token count, not
    just item count — a 64-item batch of long diffs can be 10x the token cap
    even though it's well under Voyage's 128-item batch limit."""
    chunks: List[List[str]] = []
    current: List[str] = []
    current_tokens = 0
    for t in texts:
        tok = _estimate_tokens(t)
        if current and (
            current_tokens + tok > _VOYAGE_MAX_TOKENS_PER_REQUEST or len(current) >= 96
        ):
            chunks.append(current)
            current, current_tokens = [], 0
        current.append(t)
        current_tokens += tok
    if current:
        chunks.append(current)
    return chunks


def _voyage_embed_chunk(client, chunk: List[str], input_type: str) -> List[List[float]]:
    global _voyage_last_request_at
    import voyageai.error as verror

    for attempt in range(6):
        wait = _voyage_last_request_at + _VOYAGE_MIN_SECONDS_BETWEEN_REQUESTS - time.time()
        if wait > 0:
            time.sleep(wait)
        try:
            resp = client.embed(chunk, model=config.VOYAGE_MODEL, input_type=input_type)
            _voyage_last_request_at = time.time()
            return resp.embeddings
        except verror.RateLimitError:
            _voyage_last_request_at = time.time()
            backoff = min(20 * (attempt + 1), 90)
            log.warning(
                "Voyage rate limit hit (free tier without a payment method is "
                "3 req/min, 10K tokens/min) — backing off %ss (attempt %d/6)",
                backoff,
                attempt + 1,
            )
            time.sleep(backoff)
    raise RuntimeError(
        "Voyage rate limit exceeded after repeated backoff. Add a payment method at "
        "https://dashboard.voyageai.com/ for standard limits, or unset VOYAGE_API_KEY "
        "to use local fallback embeddings."
    )


@functools.lru_cache(maxsize=1)
def _fallback_model():
    from sentence_transformers import SentenceTransformer

    log.warning("VOYAGE_API_KEY missing — using local fallback embeddings (%s)", _FALLBACK_MODEL)
    return SentenceTransformer(_FALLBACK_MODEL)


def provider() -> str:
    return "voyage" if config.VOYAGE_API_KEY else "local"


def dimensions() -> int:
    if provider() == "voyage":
        return _VOYAGE_DIMS.get(config.VOYAGE_MODEL, 1024)
    return _FALLBACK_DIMS


def embed(texts: Sequence[str], input_type: str = "document") -> List[List[float]]:
    """Embed a batch. `input_type` is 'document' when storing, 'query' when searching.

    Voyage uses asymmetric embeddings, so honouring input_type measurably improves
    retrieval quality — this is why check_bug finds the right prior fix.
    """
    texts = [t if t and t.strip() else " " for t in texts]
    if provider() == "voyage":
        client = _voyage_client()
        out: List[List[float]] = []
        chunks = _voyage_chunks([t[:8000] for t in texts])
        for i, chunk in enumerate(chunks):
            out.extend(_voyage_embed_chunk(client, chunk, input_type))
            if len(chunks) > 1:
                log.info("  voyage embed batch %d/%d (%d texts)", i + 1, len(chunks), len(chunk))
        return out

    model = _fallback_model()
    return [v.tolist() for v in model.encode(texts, normalize_embeddings=True)]


def embed_one(text: str, input_type: str = "query") -> List[float]:
    return embed([text], input_type=input_type)[0]

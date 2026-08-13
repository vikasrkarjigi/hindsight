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
from typing import Iterator, List, Sequence

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

# Voyage's free tier (no payment method on file) is 3 requests/min AND 10K
# tokens/min. Paid tiers are orders of magnitude higher, so we do NOT pace
# pre-emptively — we only start pacing after the API actually says 429, which
# keeps paid keys at full speed and stops free keys from failing the ingest.
#
# Both free-tier limits have to be respected at once: 3 requests/min means one
# request every 21s, and 10K tokens/min then caps each of those at ~3.3K tokens.
# Sending 8K-token requests every 21s is ~23K tokens/min — it 429s forever.
_CHARS_PER_TOKEN = 4  # conservative estimate; Voyage does not expose a tokenizer here
_RATE_LIMIT_BACKOFF = (5, 15, 25, 35, 45, 60, 60, 60)
_THROTTLED_INTERVAL = 21.0  # 3 requests/min
_THROTTLED_TOKENS = 3000  # × 3 requests/min = 9K/min, under the 10K ceiling
_throttle = {"min_interval": 0.0, "last_call": 0.0, "max_tokens": 8000}


@functools.lru_cache(maxsize=1)
def _voyage_client():
    import voyageai

    # max_retries=0: we do our own pacing and backoff below, tuned to the
    # free-tier rate limit rather than the SDK's generic exponential jitter.
    return voyageai.Client(api_key=config.VOYAGE_API_KEY, max_retries=0)


@functools.lru_cache(maxsize=1)
def _fallback_model():
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as e:  # the fallback is an optional extra (it pulls torch)
        raise RuntimeError(
            "VOYAGE_API_KEY is not set and the local fallback is not installed. "
            "Either put a Voyage key in .env, or run: pip install sentence-transformers"
        ) from e

    log.warning("VOYAGE_API_KEY missing — using local fallback embeddings (%s)", _FALLBACK_MODEL)
    return SentenceTransformer(_FALLBACK_MODEL)


def provider() -> str:
    return "voyage" if config.VOYAGE_API_KEY else "local"


def dimensions() -> int:
    if provider() == "voyage":
        return _VOYAGE_DIMS.get(config.VOYAGE_MODEL, 1024)
    return _FALLBACK_DIMS


def _batches(texts: List[str]) -> Iterator[List[str]]:
    """Split by estimated token count, not just item count.

    Voyage caps requests at 96 items, but the binding constraint on a free key is
    tokens-per-minute — 96 commit diffs is ~200K tokens and gets rejected outright.
    """
    batch: List[str] = []
    tokens = 0
    for t in texts:
        cost = max(len(t) // _CHARS_PER_TOKEN, 1)
        # read the cap per item: a 429 mid-run shrinks it for everything after
        if batch and (len(batch) >= 96 or tokens + cost > _throttle["max_tokens"]):
            yield batch
            batch, tokens = [], 0
        batch.append(t)
        tokens += cost
    if batch:
        yield batch


def _enter_throttled_mode() -> None:
    if _throttle["min_interval"]:
        return
    _throttle["min_interval"] = _THROTTLED_INTERVAL
    _throttle["max_tokens"] = _THROTTLED_TOKENS
    log.warning(
        "Voyage rate limit hit — pacing to 3 requests/min at <=%dK tokens each for the rest "
        "of this run. Add a payment method at https://dashboard.voyageai.com to remove the "
        "throttle (the free tokens still apply).",
        _THROTTLED_TOKENS // 1000,
    )


def _embed_request(chunk: List[str], input_type: str) -> List[List[float]]:
    """One request, with adaptive pacing so a free-tier key survives an ingest."""
    import voyageai.error

    client = _voyage_client()
    for attempt, backoff in enumerate((0,) + _RATE_LIMIT_BACKOFF):
        if backoff:
            log.warning("Voyage rate limited — retrying in %ds (attempt %d)", backoff, attempt)
            time.sleep(backoff)
        wait = _throttle["min_interval"] - (time.monotonic() - _throttle["last_call"])
        if wait > 0:
            time.sleep(wait)
        try:
            resp = client.embed(chunk, model=config.VOYAGE_MODEL, input_type=input_type)
            _throttle["last_call"] = time.monotonic()
            return resp.embeddings
        except voyageai.error.RateLimitError:
            _throttle["last_call"] = time.monotonic()
            was_paced = bool(_throttle["min_interval"])
            _enter_throttled_mode()
            # The chunk was sized for the old, larger cap — re-split it rather than
            # retrying a request that can no longer fit inside the token budget.
            if not was_paced and len(chunk) > 1:
                out: List[List[float]] = []
                for sub in _batches(chunk):
                    out.extend(_embed_request(sub, input_type))
                return out
    raise RuntimeError(
        "Voyage kept rate limiting after retries. Add a payment method at "
        "https://dashboard.voyageai.com (free tokens still apply), or ingest fewer events."
    )


def _embed_voyage(texts: List[str], input_type: str) -> List[List[float]]:
    out: List[List[float]] = []
    for chunk in _batches(texts):
        out.extend(_embed_request(chunk, input_type))
    return out


def embed(texts: Sequence[str], input_type: str = "document") -> List[List[float]]:
    """Embed a batch. `input_type` is 'document' when storing, 'query' when searching.

    Voyage uses asymmetric embeddings, so honouring input_type measurably improves
    retrieval quality — this is why check_bug finds the right prior fix.
    """
    texts = [t if t and t.strip() else " " for t in texts]
    if provider() == "voyage":
        return _embed_voyage([t[:8000] for t in texts], input_type)

    model = _fallback_model()
    return [v.tolist() for v in model.encode(texts, normalize_embeddings=True)]


def embed_one(text: str, input_type: str = "query") -> List[float]:
    return embed([text], input_type=input_type)[0]

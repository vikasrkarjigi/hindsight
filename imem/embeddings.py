"""Embedding provider.

Primary: Voyage AI (the MongoDB-recommended embedding partner).
Fallback: a small local sentence-transformers model, so a missing/expired key
can never kill a live demo. The active provider decides the vector dimension,
and the Atlas Vector Search index is created to match.
"""
from __future__ import annotations

import functools
import logging
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


@functools.lru_cache(maxsize=1)
def _voyage_client():
    import voyageai

    return voyageai.Client(api_key=config.VOYAGE_API_KEY)


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
        # Voyage caps batch size; 96 is comfortably inside every tier's limit.
        for i in range(0, len(texts), 96):
            chunk = [t[:8000] for t in texts[i : i + 96]]
            resp = client.embed(chunk, model=config.VOYAGE_MODEL, input_type=input_type)
            out.extend(resp.embeddings)
        return out

    model = _fallback_model()
    return [v.tolist() for v in model.encode(texts, normalize_embeddings=True)]


def embed_one(text: str, input_type: str = "query") -> List[float]:
    return embed([text], input_type=input_type)[0]

#!/usr/bin/env python3
"""One command to make Atlas ready: connect, create the collection, create the
vector index and the lexical index, and wait until they are READY.

    python scripts/setup_atlas.py
"""
from __future__ import annotations

import logging
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from imem import config, db, embeddings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")


def main() -> int:
    print("→ Connecting to Atlas ...")
    info = db.ping()
    print(f"  connected: db={info['database']} collection={info['collection']}")
    print(f"  embeddings: {info['embedding_provider']} ({info['embedding_dims']} dims)")
    if info["embedding_provider"] == "local":
        print("  ! VOYAGE_API_KEY not set — using local fallback embeddings.")

    col = db.events()
    if col.estimated_document_count() == 0:
        col.insert_one({"_bootstrap": True})
        col.delete_many({"_bootstrap": True})

    print(f"→ Creating indexes (vector dims = {embeddings.dimensions()}) ...")
    result = db.ensure_indexes(wait=True)
    if result["created"]:
        print(f"  created: {', '.join(result['created'])}")
    else:
        print("  indexes already existed")
    for ix in result["indexes"]:
        print(f"  - {ix['name']}: {ix['status']}")

    print("\n✅ Atlas is ready. Next:  python scripts/run_ingest.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

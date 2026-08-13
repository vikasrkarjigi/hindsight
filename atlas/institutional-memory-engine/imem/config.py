"""Central config. Everything reads from env, with sane hackathon defaults."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

MONGODB_URI = os.getenv("MONGODB_URI", "")
MONGODB_DB = os.getenv("MONGODB_DB", "institutional_memory")
MONGODB_COLLECTION = os.getenv("MONGODB_COLLECTION", "events")

VECTOR_INDEX = "events_vector_index"
TEXT_INDEX = "events_text_index"

VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY", "").strip()
VOYAGE_MODEL = os.getenv("VOYAGE_MODEL", "voyage-3")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "expressjs/express")

STALENESS_HALF_LIFE_DAYS = float(os.getenv("STALENESS_HALF_LIFE_DAYS", "540"))
STALENESS_WEIGHT = float(os.getenv("STALENESS_WEIGHT", "0.35"))

# Every event type that can live in the single polymorphic `events` collection.
EVENT_TYPES = (
    "commit",
    "pull_request",
    "review_comment",
    "issue",
    "postmortem",
    "architecture_decision",
    "slack_thread",
)


def require_uri() -> str:
    if not MONGODB_URI or "USER:PASSWORD" in MONGODB_URI:
        raise RuntimeError(
            "MONGODB_URI is not set. Copy .env.example to .env and paste your "
            "Atlas connection string (Atlas UI → Connect → Drivers)."
        )
    return MONGODB_URI

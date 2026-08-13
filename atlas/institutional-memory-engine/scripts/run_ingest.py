#!/usr/bin/env python3
"""Ingest real engineering history into Atlas.

    python scripts/run_ingest.py                       # default repo from .env
    python scripts/run_ingest.py --repo expressjs/express --commits 200
    python scripts/run_ingest.py --seed-only           # just the non-git memory
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from imem import config, db  # noqa: E402
from imem.ingest import github, seed  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=config.GITHUB_REPO)
    ap.add_argument("--commits", type=int, default=150)
    ap.add_argument("--pulls", type=int, default=80)
    ap.add_argument("--comments", type=int, default=120)
    ap.add_argument("--seed-only", action="store_true")
    ap.add_argument("--no-seed", action="store_true")
    args = ap.parse_args()

    db.ping()

    if not args.seed_only:
        print(f"→ Ingesting GitHub history for {args.repo} ...")
        res = github.ingest_repo(args.repo, args.commits, args.pulls, args.comments)
        print(
            f"  {res['events_written']} events written "
            f"({res['commits']} commits, {res['pull_requests']} PRs, "
            f"{res['review_comments']} review comments, {res['reverted_events']} reverted)"
        )

    if not args.no_seed:
        print("→ Seeding postmortems / ADRs / Slack threads ...")
        s = seed.load_seed(args.repo)
        print(f"  {s['seeded']} events across {', '.join(s['types'])}")

    from imem import tools

    stats = tools.memory_stats()
    print(f"\n✅ Memory loaded: {stats['total_events']} events")
    for t, n in stats["by_type"].items():
        print(f"   {t:24} {n}")
    print("\nNext:  python scripts/demo.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

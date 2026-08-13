"""The five core tools.

These are plain Python functions so they can be called three ways with zero
duplication: over MCP (Claude/Cursor), over HTTP (dashboard/Slack bot), or
directly from a script (the demo). That is what makes this *infrastructure*
rather than a chat app.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from . import search
from .schema import summarize

FIX_TYPES = ("commit", "pull_request", "issue", "postmortem")
DESIGN_TYPES = ("architecture_decision", "pull_request", "review_comment", "slack_thread")


def _files_from_diff(diff: str) -> List[str]:
    files = re.findall(r"^\+\+\+ b/(.+)$", diff, flags=re.M)
    files += re.findall(r"^diff --git a/\S+ b/(\S+)$", diff, flags=re.M)
    return sorted(set(files))


# ── 1. check_bug ─────────────────────────────────────────────────────────────

def check_bug(error: str, repo: Optional[str] = None, k: int = 5) -> Dict[str, Any]:
    """Given an error trace or bug description, surface the closest prior fix,
    the actual diff that fixed it, and who wrote it."""
    hits = search.recall(error, k=k, types=FIX_TYPES, repo=repo)
    if not hits:
        return {"found": False, "message": "No prior art in institutional memory for this error."}

    best = hits[0]
    return {
        "found": True,
        "verdict": f"This looks like it was hit before — {best['ts'].date().isoformat()}.",
        "closest_fix": {
            **summarize(best, body_chars=1200),
            "diff": (best.get("diff") or "")[:4000],
            "ask": (best.get("author") or {}).get("name")
            or (best.get("author") or {}).get("login"),
        },
        "also_relevant": [summarize(h) for h in hits[1:]],
        "how_to_use": "Read the diff before rewriting the fix. Ping the author if it doesn't apply cleanly.",
    }


# ── 2. review_pr ─────────────────────────────────────────────────────────────

def review_pr(diff: str, title: str = "", repo: Optional[str] = None, k: int = 8) -> Dict[str, Any]:
    """Flag when a new PR reintroduces a pattern the team previously reverted."""
    files = _files_from_diff(diff)
    query = "\n".join([title, "Files: " + ", ".join(files), diff[:6000]]).strip()

    reverted = search.recall(
        query, k=k, types=("commit", "pull_request"), repo=repo,
        extra_filter={"reverted": True}, decay=False,
    )
    context = search.recall(query, k=k, types=FIX_TYPES + ("review_comment",), repo=repo)

    # Same files + previously reverted = the loudest possible signal.
    warnings = []
    for r in reverted:
        overlap = sorted(set(files) & set(r.get("files") or []))
        confidence = "high" if overlap else "medium"
        warnings.append(
            {
                "confidence": confidence,
                "why": (
                    f"This change resembles work that was later reverted"
                    + (f", and touches the same files: {', '.join(overlap[:5])}." if overlap else ".")
                ),
                "prior": summarize(r, body_chars=600),
                "overlapping_files": overlap,
            }
        )

    warnings.sort(key=lambda w: (w["confidence"] != "high", -w["prior"]["score"]))
    reviewers = search.people_index(files, limit=3)

    return {
        "files_changed": files,
        "risk": "high" if any(w["confidence"] == "high" for w in warnings) else ("low" if not warnings else "medium"),
        "revert_warnings": warnings[:4],
        "related_history": [summarize(c) for c in context[:4]],
        "suggested_reviewers": reviewers,
        "summary": (
            f"{len(warnings)} prior revert(s) resemble this change."
            if warnings
            else "No previously-reverted pattern detected in this diff."
        ),
    }


# ── 3. explain ───────────────────────────────────────────────────────────────

def explain(subject: str, repo: Optional[str] = None, k: int = 6) -> Dict[str, Any]:
    """Recover the original reasoning behind a confusing file or function."""
    hits = search.recall(
        f"Why does {subject} work this way? Design rationale, tradeoffs, and constraints behind {subject}",
        k=k, types=DESIGN_TYPES + ("commit",), repo=repo,
    )
    if not hits:
        return {"found": False, "message": f"No recorded reasoning for '{subject}'."}

    timeline = sorted(hits, key=lambda d: d["ts"])
    return {
        "found": True,
        "subject": subject,
        "reasoning": [summarize(h, body_chars=900) for h in hits],
        "timeline": [
            {"date": d["ts"].date().isoformat(), "type": d["type"], "title": d["title"], "url": d.get("url")}
            for d in timeline
        ],
        "who_to_ask": search.people_index([subject], limit=3)
        or [
            {"login": (h.get("author") or {}).get("login"), "name": (h.get("author") or {}).get("name")}
            for h in hits[:2]
            if h.get("author")
        ],
    }


# ── 4. precedent ─────────────────────────────────────────────────────────────

def precedent(proposal: str, repo: Optional[str] = None, k: int = 6) -> Dict[str, Any]:
    """Has this idea already been debated, tried, or rejected?"""
    hits = search.recall(proposal, k=k, types=DESIGN_TYPES, repo=repo)
    if not hits:
        return {"status": "novel", "message": "No prior debate found. This appears to be a new idea."}

    rejected_words = ("revert", "rejected", "decided against", "won't", "wontfix", "abandon", "backed out", "rolled back")
    verdicts = []
    for h in hits:
        blob = f"{h.get('title','')} {h.get('body','')}".lower()
        if h.get("reverted") or any(w in blob for w in rejected_words):
            v = "tried_and_reverted" if h.get("reverted") else "argued_against"
        else:
            v = "discussed"
        verdicts.append({**summarize(h, body_chars=800), "verdict": v})

    strongest = next((v for v in verdicts if v["verdict"] == "tried_and_reverted"), None)
    status = "settled_against" if strongest else ("debated" if verdicts else "novel")

    return {
        "status": status,
        "headline": (
            f"This was tried before and reverted ({strongest['date']})."
            if strongest
            else "This has been discussed before — read the prior debate before proposing again."
        ),
        "prior_art": verdicts,
    }


# ── 5. page_owner ────────────────────────────────────────────────────────────

def page_owner(symptoms: str, repo: Optional[str] = None, k: int = 12) -> Dict[str, Any]:
    """Recommend who to page, based on who actually resolved the closest past incident."""
    hits = search.recall(symptoms, k=k, types=("postmortem", "commit", "pull_request", "issue"), repo=repo)
    if not hits:
        return {"found": False, "message": "No comparable past incident — escalate to the on-call lead."}

    now = datetime.now(timezone.utc)
    scores: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"score": 0.0, "name": None, "evidence": [], "last_seen": None}
    )
    for h in hits:
        a = h.get("author") or {}
        key = a.get("login") or a.get("name")
        if not key:
            continue
        # Incident-resolution evidence counts double; recency breaks ties.
        weight = 2.0 if h["type"] == "postmortem" else 1.0
        recency = 0.5 ** (max((now - h["ts"].replace(tzinfo=timezone.utc)).days, 0) / 365)
        s = scores[key]
        s["score"] += h.get("score", 0) * weight * (0.6 + 0.4 * recency)
        s["name"] = s["name"] or a.get("name")
        if len(s["evidence"]) < 3:
            s["evidence"].append(summarize(h, body_chars=200))
        ts = h["ts"].date().isoformat()
        s["last_seen"] = max(s["last_seen"], ts) if s["last_seen"] else ts

    ranked = sorted(
        ({"login": k, **v} for k, v in scores.items()), key=lambda d: d["score"], reverse=True
    )[:3]
    for r in ranked:
        r["score"] = round(r["score"], 4)

    top = ranked[0] if ranked else None
    return {
        "found": bool(top),
        "page": top,
        "backups": ranked[1:],
        "rationale": (
            f"{top['name'] or top['login']} resolved the closest matching incident "
            f"(last relevant activity {top['last_seen']})."
            if top
            else None
        ),
        "closest_incident": summarize(hits[0], body_chars=600),
    }


# ── bonus tools ──────────────────────────────────────────────────────────────

def who_knows(file_path: str, limit: int = 5) -> Dict[str, Any]:
    """People-index: aggregate top historical contributors for a file or topic."""
    people = search.people_index([file_path], limit=limit)
    if not people:
        hits = search.recall(file_path, k=8)
        people = search.people_index(
            sorted({f for h in hits for f in (h.get("files") or [])})[:20], limit=limit
        )
    return {"subject": file_path, "experts": people}


def contradictions(topic: str, k: int = 8) -> Dict[str, Any]:
    """Flag historical decisions on the same topic that point in opposite directions."""
    hits = search.recall(topic, k=k, types=DESIGN_TYPES, decay=False)
    neg = ("revert", "rollback", "rejected", "remove", "drop", "deprecate", "disable", "back out")
    pos = ("adopt", "introduce", "add", "enable", "migrate to", "standardize on", "approved")

    stance = []
    for h in hits:
        blob = f"{h.get('title','')} {h.get('body','')}".lower()
        n = sum(w in blob for w in neg)
        p = sum(w in blob for w in pos)
        if n or p:
            stance.append({"doc": summarize(h, body_chars=400), "stance": "against" if n > p else "for"})

    fors = [s for s in stance if s["stance"] == "for"]
    againsts = [s for s in stance if s["stance"] == "against"]
    conflict = bool(fors and againsts)
    return {
        "topic": topic,
        "contradiction_detected": conflict,
        "headline": (
            "Two historical decisions on this topic point in opposite directions — reconcile before acting."
            if conflict
            else "No semantic conflict detected across historical decisions."
        ),
        "for": fors[:3],
        "against": againsts[:3],
    }


def memory_stats() -> Dict[str, Any]:
    return search.stats()

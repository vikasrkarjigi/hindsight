# Institutional Memory Engine — Build Fest submission

## One-liner

Your team's engineering history, exposed as an MCP tool your AI agent calls mid-task —
so nobody re-debates a settled decision, re-fixes a fixed bug, or re-ships a reverted patch.

## Project description (paste into Cerebral Valley)

When an engineer leaves, switches teams, or goes on vacation, the *why* leaves with them.
The commit is still there; the reasoning isn't. So teams re-debate settled architecture,
re-fix bugs that were fixed two years ago, and re-introduce patterns they already reverted.

The Institutional Memory Engine ingests a team's real engineering history — git commits
with diffs, pull requests, code review comments, postmortems, architecture decision
records and Slack threads — into **a single polymorphic MongoDB collection**, each document
carrying a Voyage AI embedding, queried through **a single Atlas Vector Search index**.

It ships as an **MCP server**, not a chat app. That's the design bet: institutional memory
isn't a destination you visit, it's context that should arrive inside the tool you're
already in. Point Claude Code or Cursor at it and five tools become available mid-task:

- **`check_bug`** — paste an error trace, get the closest prior fix, the actual diff, and the author's name.
- **`review_pr`** — paste a PR diff, get flagged when it reintroduces a pattern the team already reverted.
- **`explain`** — ask why a file looks the way it does, get the original reasoning reconstructed as a timeline across PRs, ADRs and Slack.
- **`precedent`** — pitch an architecture change, find out it was already tried and rejected, and why.
- **`page_owner`** — describe a live outage, get told which engineer resolved the closest past incident.

**Why MongoDB is the whole backend, not just storage.** Every artifact type is one document
shape with a different `meta` sub-document, so one query spans commits, postmortems and
Slack threads with no per-source adapters and no federation layer. `type` and `reverted`
are *filters inside the vector index*, so `review_pr` searches only previously-reverted
work in a single hop — with a bolt-on vector store that's a two-system join in application
code. Aggregation rebuilds the people-index. Change streams drive the live dashboard.
Vectors sit next to the documents they describe, so there is no sync pipeline, no second
consistency model, and no second failure domain.

**Retrieval quality:** asymmetric Voyage embeddings (`document` vs `query` input types),
hybrid vector + lexical retrieval fused with Reciprocal Rank Fusion so exact tokens like
`ECONNRESET` are never lost to fuzzy similarity, and staleness decay
(`score × ((1-w) + w · 0.5^(age/half_life))`) so a recent fix outranks an obsolete one.

Built in one afternoon at MongoDB .local Build Fest, running against real commit and
revert history from a public repository — the reverts it flags are real reverts.

## Tech

Python · MongoDB Atlas (Vector Search, Atlas Search, aggregation, change streams) ·
Voyage AI `voyage-3` · Model Context Protocol (FastMCP) · FastAPI + SSE dashboard

---

## 60-second demo video script

**0:00–0:08 — the problem.** On camera or voiceover, dashboard open showing the event count:
> "Every team loses the *why*. This is 200-plus real events from a real repo — commits,
> PRs, reviews, postmortems, ADRs, Slack — in one MongoDB collection, one vector index."

**0:08–0:25 — `review_pr` (lead with this, it's the strongest).** Show the diff, run it:
```bash
python scripts/demo.py review_pr
```
> "I'm opening a PR that adds a fixed-interval retry. The engine flags it: this pattern was
> reverted before, it touches the same file, and here's the postmortem for the SEV1 it caused."

**0:25–0:38 — `explain`.**
```bash
python scripts/demo.py explain
```
> "Why does the body parser run before auth? Nobody left is sure. The engine reconstructs it
> from a Slack thread and a review comment: the webhook signature is over the raw body."

**0:38–0:50 — `check_bug`.**
```bash
python scripts/demo.py check_bug
```
> "Paste a stack trace. Closest prior fix, the actual diff, and the name of who wrote it."

**0:50–1:00 — the point.** Cut to Claude Code / Cursor calling the tool, or the live dashboard:
> "It's an MCP server, so this runs inside the editor you already use. One collection,
> one index — MongoDB is the memory, the retrieval, and the stream. No bolt-on vector store."

### Recording checklist
- [ ] `python scripts/demo.py` runs clean end-to-end **before** you hit record
- [ ] Terminal font bumped to ~18pt, window ~110 cols (the demo is formatted for that width)
- [ ] Dashboard open in a second window at <http://localhost:8000>
- [ ] **Verify the export has both video AND audio** (explicit organiser reminder)
- [ ] **All team members added to the submission** (explicit organiser reminder)
- [ ] Under 60 seconds

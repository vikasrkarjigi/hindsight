# 🧠 Institutional Memory Engine

**Your team's engineering history, as an MCP tool your AI agent can call mid-task.**

When an engineer leaves, the *why* leaves with them. Every team then re-debates
settled decisions, re-fixes fixed bugs, and re-introduces reverted patterns. This
system ingests the team's actual history — commits, PRs, review comments,
postmortems, architecture decisions, Slack threads — into **one MongoDB collection
with one Atlas Vector Search index**, and exposes it as an **MCP server** so Claude,
Cursor, or a Slack bot can pull the right memory at the moment it matters.

> No third-party vector store. No sync pipeline. No bolt-on connector.
> Agent memory, retrieval, and application data live in the same place.

---

## What is the backend?

There are three layers and **MongoDB Atlas is the whole data plane**:

| Layer | What it is | File |
|---|---|---|
| **Data plane** | MongoDB Atlas — a single polymorphic `events` collection holding every kind of engineering artifact, each with a Voyage AI embedding. One `vectorSearch` index + one lexical `search` index. Change streams drive the live dashboard. | `imem/db.py`, `imem/schema.py` |
| **Retrieval + logic** | Python. Vector search → RRF hybrid fusion with lexical → staleness decay → the five tools. Pure functions, no framework lock-in. | `imem/search.py`, `imem/tools.py` |
| **Surfaces** | Two thin wrappers over the same functions: an **MCP server** (stdio) for Claude/Cursor, and a **FastAPI** app for the dashboard and any HTTP client. | `imem/mcp_server.py`, `imem/api.py` |

The point of the architecture: **the tools are the product, and they are 200 lines**,
because MongoDB is doing the storage, the vector search, the filtering, the
aggregation and the streaming. That's the pitch.

---

## Get it running (~5 minutes)

### 1. MongoDB Atlas sandbox (free M0)

1. <https://cloud.mongodb.com> → sign up → **Create a free M0 cluster**.
2. **Database Access** → Add New Database User → username + password → *Read and write to any database*.
3. **Network Access** → Add IP Address → **Allow access from anywhere** (`0.0.0.0/0`) — it's a hackathon sandbox.
4. **Clusters → Connect → Drivers → Python** → copy the `mongodb+srv://...` string.

### 2. Voyage AI key

<https://dashboard.voyageai.com> → sign up → **API Keys → Create**. Free tier is far
more than enough. *(If you skip this, the app automatically falls back to a local
embedding model so the demo can never hard-fail — but Voyage is the better story.)*

### 3. GitHub token (30 seconds, big payoff)

<https://github.com/settings/tokens> → *Generate new token (classic)* → **no scopes needed**
for public repos. Without it you're capped at 60 API requests/hour and the ingest
runs tiny.

### 4. Install and configure

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# paste MONGODB_URI, VOYAGE_API_KEY, GITHUB_TOKEN into .env
```

### 5. Bootstrap Atlas, then load memory

```bash
python scripts/setup_atlas.py     # creates the collection + both search indexes, waits for READY
python scripts/run_ingest.py      # pulls real GitHub history + seeds postmortems/ADRs/Slack
```

### 6. Demo it

```bash
python scripts/demo.py                      # all five tools, formatted for camera
python scripts/demo.py review_pr explain check_bug   # just the pitch three

uvicorn imem.api:app --port 8000            # live dashboard → http://localhost:8000
```

---

## The five tools

| Tool | Input | What it returns |
|---|---|---|
| `check_bug` | error trace / bug description | the closest prior fix, **the actual diff**, and who wrote it |
| `review_pr` | a PR diff | flags when the change **reintroduces a previously reverted pattern**, + suggested reviewers |
| `explain` | a confusing file or function | the original reasoning, reconstructed from PRs, ADRs and Slack, as a timeline |
| `precedent` | an architectural proposal | whether it was already debated, tried, or **rejected — and why** |
| `page_owner` | live outage symptoms | which engineer to page, ranked by who resolved the closest past incident |

Bonus: `who_knows` (people-index), `contradictions` (conflicting decisions), `memory_stats`.

---

## Connect it to Claude Code / Cursor

`claude_desktop_config.json` (or Cursor's MCP settings):

```json
{
  "mcpServers": {
    "institutional-memory": {
      "command": "/absolute/path/to/.venv/bin/python",
      "args": ["-m", "imem.mcp_server"],
      "cwd": "/absolute/path/to/atlas-imem"
    }
  }
}
```

Then just ask, in your editor: *"check_bug: pool timed out waiting for connection"*.

---

## The retrieval tricks worth mentioning on stage

- **One polymorphic collection.** A commit, a postmortem and a Slack thread are the
  same document shape with different `meta`. One query retrieves across all of them —
  no per-source adapters, no joins, no federation layer.
- **Asymmetric embeddings.** Documents embed with `input_type="document"`, queries with
  `"query"`. This is why a raw stack trace matches a two-year-old commit message.
- **Hybrid search with RRF.** Vector search alone loses exact tokens like `ECONNRESET`.
  Lexical `$search` catches them; Reciprocal Rank Fusion merges the two rankings without
  needing the score scales to be comparable.
- **Staleness decay.** `score × ((1-w) + w · 0.5^(age/half_life))`. An equally-relevant fix
  from last month outranks one from four years ago, because the codebase moved on.
- **Filtered vector search in one hop.** `type` and `reverted` are index filters, so
  `review_pr` searches *only previously-reverted work* inside the vector index itself —
  not a post-filter in application code. This is the thing a separate vector store
  makes you write a join for.

## Layout

```
imem/
  config.py        env + constants
  db.py            Atlas client, vector + lexical index bootstrap
  schema.py        the polymorphic event document
  embeddings.py    Voyage AI, with a local fallback so the demo never dies
  search.py        vector / lexical / RRF hybrid / staleness decay / people-index
  tools.py         the five tools (pure functions — the actual product)
  mcp_server.py    MCP surface  (python -m imem.mcp_server)
  api.py           FastAPI surface + change-stream SSE
  dashboard.html   live ingest dashboard + tool console
  ingest/
    github.py      commits (with diffs), PRs, review comments, revert detection
    seed.py        postmortems, ADRs, Slack threads — what git can't give you
scripts/
  setup_atlas.py   one command to make Atlas ready
  run_ingest.py    load the memory
  demo.py          the on-camera demo
```

## Troubleshooting

- **`MONGODB_URI is not set`** — you skipped `cp .env.example .env`, or left `<db_password>` in the string.
- **Vector search returns nothing** — index still building. `python scripts/setup_atlas.py` prints each index's status; wait for `READY`.
- **Changed embedding provider?** Dimensions changed, so the index is stale:
  `python -c "from imem import db; db.drop_search_indexes()"` then re-run `setup_atlas.py` and re-ingest.
- **GitHub 403** — set `GITHUB_TOKEN`. Unauthenticated is 60 req/hr.

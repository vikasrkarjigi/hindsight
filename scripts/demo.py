#!/usr/bin/env python3
"""The 60-second demo. Run this on camera.

    python scripts/demo.py            # all five tools
    python scripts/demo.py check_bug  # just one
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rich.console import Console  # noqa: E402
from rich.panel import Panel  # noqa: E402
from rich.syntax import Syntax  # noqa: E402
from rich.table import Table  # noqa: E402

from imem import tools  # noqa: E402

c = Console(width=110)

REINTRODUCED_DIFF = """diff --git a/lib/http/retry.js b/lib/http/retry.js
--- a/lib/http/retry.js
+++ b/lib/http/retry.js
@@ -12,6 +12,14 @@ class PaymentClient {
+  async requestWithRetry(fn) {
+    for (let attempt = 0; attempt < 3; attempt++) {
+      try { return await fn() }
+      catch (err) {
+        // retry every 200ms, three times
+        await sleep(200)
+      }
+    }
+  }
"""


def header(n: int, name: str, prompt: str) -> None:
    c.print()
    c.rule(f"[bold green]{n}. {name}[/]")
    c.print(Panel(prompt, title="engineer asks", border_style="dim"))


def hit(h: dict) -> str:
    return (
        f"[bold]{h.get('title')}[/]\n"
        f"  [dim]{h.get('type')} · {h.get('author')} · {h.get('date')} · "
        f"score {h.get('score')} (raw {h.get('raw_score')}, age {h.get('age_days')}d)[/]"
    )


def demo_check_bug():
    q = "TimeoutError: pool timed out waiting for connection, ECONNRESET spike on checkout"
    header(1, "check_bug", q)
    r = tools.check_bug(q)
    if not r.get("found"):
        c.print("[red]no memory[/]")
        return
    f = r["closest_fix"]
    c.print(Panel(
        f"{hit(f)}\n\n{f['excerpt'][:600]}",
        title=f"[bold green]closest prior fix — ask {f['ask']}[/]",
        border_style="green",
    ))
    if f.get("diff"):
        c.print(Syntax(f["diff"][:900], "diff", theme="ansi_dark"))


def demo_review_pr():
    header(2, "review_pr", "opening a PR: 'Add retry logic to the payment client'")
    r = tools.review_pr(REINTRODUCED_DIFF, title="Add retry logic to payment client")
    c.print(Syntax(REINTRODUCED_DIFF, "diff", theme="ansi_dark"))
    c.print(f"\n[bold]risk:[/] [{'red' if r['risk']=='high' else 'yellow'}]{r['risk'].upper()}[/]  — {r['summary']}")
    for w in r["revert_warnings"]:
        c.print(Panel(
            f"{w['why']}\n\n{hit(w['prior'])}",
            title=f"[bold red]⚠ {w['confidence']} confidence[/]",
            border_style="red",
        ))
    if r["suggested_reviewers"]:
        t = Table("reviewer", "touches", "last touch", title="suggested reviewers")
        for p in r["suggested_reviewers"]:
            t.add_row(p.get("name") or p["login"], str(p["touches"]), str(p.get("last_touch")))
        c.print(t)


def demo_explain():
    q = "the body parser middleware ordering"
    header(3, "explain", f"why is {q} the way it is?")
    r = tools.explain(q)
    if not r.get("found"):
        c.print("[red]no memory[/]")
        return
    for h in r["reasoning"][:3]:
        c.print(Panel(f"{hit(h)}\n\n{h['excerpt'][:500]}", border_style="cyan"))
    t = Table("date", "type", "title", title="how we got here")
    for e in r["timeline"][:6]:
        t.add_row(e["date"], e["type"], e["title"][:60])
    c.print(t)


def demo_precedent():
    q = "Let's split the monolith into microservices so teams can deploy independently"
    header(4, "precedent", q)
    r = tools.precedent(q)
    c.print(f"[bold]status:[/] [yellow]{r['status']}[/] — {r.get('headline','')}")
    for p in r.get("prior_art", [])[:3]:
        c.print(Panel(f"{hit(p)}\n[bold]verdict:[/] {p['verdict']}\n\n{p['excerpt'][:500]}", border_style="yellow"))


def demo_page_owner():
    q = "prod is throwing 502s, cache hit rate collapsed right after the deploy"
    header(5, "page_owner", q)
    r = tools.page_owner(q)
    if not r.get("found"):
        c.print("[red]no comparable incident[/]")
        return
    p = r["page"]
    c.print(Panel(
        f"[bold green]Page {p.get('name') or p['login']}[/]\n{r['rationale']}",
        border_style="green",
    ))
    t = Table("engineer", "score", "last relevant")
    for x in [p] + r["backups"]:
        t.add_row(x.get("name") or x["login"], str(x["score"]), str(x.get("last_seen")))
    c.print(t)


DEMOS = {
    "check_bug": demo_check_bug,
    "review_pr": demo_review_pr,
    "explain": demo_explain,
    "precedent": demo_precedent,
    "page_owner": demo_page_owner,
}


def main() -> int:
    stats = tools.memory_stats()
    c.print(Panel(
        f"[bold green]Institutional Memory Engine[/]\n"
        f"{stats['total_events']} events in one MongoDB collection · "
        f"one Atlas Vector Search index · {stats['embedding_provider']} embeddings "
        f"({stats['dimensions']}d)\n"
        f"[dim]{'  '.join(f'{k}:{v}' for k, v in stats['by_type'].items())}[/]",
        border_style="green",
    ))

    which = sys.argv[1:] or list(DEMOS)
    for name in which:
        DEMOS[name]()
        time.sleep(0.3)
    c.print()
    c.rule("[green]five tools, one collection, one index[/]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

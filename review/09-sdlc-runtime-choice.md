# 09 — Why the SDLC is Claude Code subagents, not LangGraph

Written so this doesn't get relitigated in six months. Short version: **two different agent
systems live in this repo, they have different jobs, and they should stay on different
runtimes.**

## 1. The two systems

| | **SDLC agents** (build the software) | **Product agent** (runs in the software) |
|---|---|---|
| Where | `.claude/agents/*.md`, `CLAUDE.md`, `skills/` | `calai_backend/services/`, `providers/` |
| Runtime | Claude Code harness | FastAPI process, on request |
| Who invokes | you, or `sdlc-orchestrator` | an end user tapping a button |
| Lifetime | a working session | a few seconds per request |
| Failure cost | wasted tokens, a bad diff you can revert | a wrong calorie number shown to a user |
| Supervision | human in the loop | none — it's production |
| Reviewed in | `01`–`03`, `08` | `04` |

`04-agent-architecture-langgraph.md` is entirely about the **right-hand column**. Nothing in
it applies to your subagents.

## 2. Why Claude Code (not LangGraph) for the SDLC

LangGraph gives you typed state, routing, checkpoint/resume, and streaming for **a program
you deploy**. None of those are the hard part of an SDLC agent. The hard parts are:

| What the SDLC needs | Claude Code provides | Would have to be built on LangGraph |
|---|---|---|
| Read/edit files reliably, with diffs a human reviews | built-in tools | your own file-edit tool + patch validation |
| **Per-agent tool restriction** — `ui-engineer` and `architecture-designer` have no Bash; `reviewer` cannot edit | frontmatter `tools:` | your own permission layer |
| Block dangerous actions (reading `.env`, destructive commands) | hooks + permission prompts | your own policy engine |
| A human approving/redirecting mid-run | interactive by design | a queue + UI you'd have to write |
| Spawning a stage as a sub-agent with its own context | `Agent` tool | subgraph + context management by hand |
| Skills/CLAUDE.md as versioned instruction context | native | your own prompt assembly |

Rebuilding that on LangGraph means writing a worse Claude Code. The `tools:` line in
`ui-engineer.md` that prevents it from running Bash is a genuine safety property you'd have
to reimplement — and would probably get wrong.

📘 **Learn this — pick the runtime that owns your hard problem.** LangGraph's hard problem is
*deterministic multi-step state with resumption*. Claude Code's hard problem is *a supervised
agent editing a real repo safely*. Choosing a framework because you want practice with it,
rather than because it owns your hard problem, is how projects acquire accidental complexity.
(This same reasoning is why `04` now says don't put a single LLM call behind a `StateGraph`.)

## 3. The seam between them

They meet in exactly one place, and it's a *file*, not a call:

```
SDLC agents (Claude Code)                    Product agent (FastAPI)
   ai-engineer writes ───────────────────────► calai_backend/services/*.py
   tester writes ─────────────────────────────► calai_backend/tests/, evals/dataset/
   reviewer runs ─────────────────────────────► make test / make eval  ──► exit code
                                                          │
                       eval report / test results ◄────────┘
```

The SDLC never imports the product's agent code, and the product never invokes a subagent.
`evals/` is the interface: the SDLC's quality gate reads the product's measured behavior.
Keep that seam clean — if you ever find yourself wanting the product to spawn a Claude Code
subagent at request time, that's a design smell, not a feature.

## 4. The one place a headless agent runtime *does* belong (Step 10)

Everything above assumes a human in the loop. The exception is **CI**, where there is none:

**Use case:** on every PR, an agent reads the diff, runs `make lint test`, applies
`reviewer.md`'s checklist plus the production lens, and posts findings as a PR comment.

This can't be your interactive `reviewer` subagent, because CI has no human to approve tool
calls, no session, and needs a hard cost cap. Requirements that differ:

- **Non-interactive** — every tool call pre-authorised or unavailable; no prompts.
- **Cost-capped** — a token/dollar ceiling per run, enforced, not hoped for.
- **Deterministic enough to re-run** — same diff → substantially the same findings.
- **Advisory, never the gate** — CI's `make lint test` gates. The agent comments. An LLM must
  never be the thing that decides a merge is safe; it's a reviewer, not a test.
- **Small-model-first** — routes cheap models for the mechanical checks (docs-sync greps,
  convention violations), escalating only for judgment calls.

**Runtime choice for it:**
- **Claude Agent SDK** — the natural fit. It's purpose-built for headless agents with tools
  and file access, so you inherit the tool loop rather than writing one. (Ask the
  `claude-code-guide` agent for current API specifics when you build it — don't code from
  memory.)
- **LangGraph** — defensible if you specifically want the state-machine practice:
  `diff → classify → [lint node | test node | checklist node] → summarise` is a real graph
  with a fan-out and a deterministic middle. Note you'd still be writing the tool layer.

**Recommendation:** Agent SDK for the bot; get your LangGraph reps on the IFCT pipeline
(`04` §8, Trigger A) where the framework actually owns the problem. Don't use a CI bot as
your LangGraph tutorial — its failure mode (silently unhelpful comments) is one you won't
notice, whereas the IFCT pipeline's failure mode is a MAPE number that visibly doesn't improve.

## 5. Decision record

| Question | Answer | Revisit if |
|---|---|---|
| LangGraph for the SDLC pipeline? | **No** | never, realistically — you'd be rebuilding the harness |
| LangGraph for the product agent? | **Not yet** (`04` §0) | IFCT grounding lands, or a chat surface is designed |
| Headless agent runtime anywhere? | **Yes, CI only** (Step 10) | after Steps 0–8 |
| Two agent systems in one repo — confusing? | Acceptable, because the seam is files + exit codes | if the product ever needs to call a subagent, stop and redesign |

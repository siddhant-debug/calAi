# CalAI — Agent System & SDLC Review

**Date:** 2026-09-13 · **Scope:** `.claude/agents/`, `skills/`, `CLAUDE.md`, `archdocs/`,
`plans/`, `artefacts/`, `evals/README.md`, `.claude/settings*.json`, hooks. **Not** source code.

**Goal you stated:** turn this project into a learning vehicle for shipping a
production-grade, well-tested, scalable AI product using Claude Code + LangChain/LangGraph,
with a workflow clean enough that *small models* can follow it reliably and cheaply.

## How to read this folder (in order)

| # | File | What it answers | Read time |
|---|---|---|---|
| 1 | [01-current-state.md](01-current-state.md) | What you actually have, and what is genuinely strong | 8 min |
| 2 | [02-gaps.md](02-gaps.md) | Every gap found, with evidence, severity and the fix | 15 min |
| 3 | [03-target-sdlc.md](03-target-sdlc.md) | The production SDLC to adopt, mapped onto your agents | 15 min |
| 4 | [04-agent-architecture-langgraph.md](04-agent-architecture-langgraph.md) | How the *app's* agent should be built with LangGraph so it's reusable, testable and small-model-safe | 20 min |
| 5 | [05-testing-and-evals.md](05-testing-and-evals.md) | The test pyramid for AI systems, the exceptional-case matrix, and CI gating | 15 min |
| 6 | [06-learning-roadmap.md](06-learning-roadmap.md) | The skills to learn in parallel, each tied to a task in this repo | 10 min |
| 7 | [07-action-plan.md](07-action-plan.md) | The step-by-step execution order with acceptance criteria and owning agent | 10 min |
| 8 | [08-agent-and-skill-fixes.md](08-agent-and-skill-fixes.md) | Concrete text fixes for stale/contradictory agent & skill files (copy-paste ready) | 8 min |
| 9 | [09-sdlc-runtime-choice.md](09-sdlc-runtime-choice.md) | Why the SDLC stays Claude Code subagents and the product agent is a separate runtime — plus the one CI lane where a headless agent belongs | 6 min |

## The one-paragraph verdict

You have built something most solo projects never get to: a written design record (ADR-001…006),
an eval harness with a committed baseline and a regression gate, a review gate with a fix-loop
cap, honest retrospectives that corrected their own claims, and an agent roster with real
ownership boundaries. That is the *skeleton* of a production SDLC and it is ahead of the curve.
What's missing is the *nervous system*: nothing is enforced by machines (no CI, no pre-commit,
no hooks guarding rules), agent handoffs are free-form prose that small models will drift on,
the docs/skills have already drifted from the code (five contract mismatches found without
reading code), and the app's own agent is a hand-rolled orchestrator that is about to reinvent
LangGraph's state machine in ADR-005. The fixes are incremental, cheap, and each one is a
learning unit — the action plan sequences them so every step ships something.

## Working assumptions (correct me if wrong)

- "Small models" = NIM nano-class / Haiku-class models both **inside the product** (meal parsing,
  extraction) and **driving the SDLC** (subagents). Every recommendation is judged by "would a
  weak model still get this right?" — which means checklists over prose, schemas over free text,
  machine gates over reminders.
- "Production" = a real shipped app for real users at *small* scale (tens–hundreds), not the
  1000-user async design in `archdocs/SYSTEM-DESIGN-1000-USERS.md`. That doc stays aspirational.
- **LangGraph is deferred, not adopted** (revised 2026-09-13 — see `04` §0/§8). Since profile is
  captured by a mandatory setup step rather than conversation, v1 needs no router, slot-filling
  or checkpointer; a single structured LLM call with validate-and-repair does it. LangGraph
  becomes right at the IFCT nutrition-grounding pipeline (multi-node, deterministic middle) or
  if a real chat surface is designed. LangChain stays for model/tool/structured-output plumbing.
- **The SDLC agents (Claude Code subagents) are a separate system and stay as they are** — not
  LangGraph, for the reasons in `09`. The two systems meet only via files and exit codes.
- ⚠️ `archdocs/frontendidea.md` is **not final**, so conclusions that rested on it are flagged
  in `04` §0.1 — most importantly **persistence (client- vs server-side) is an open decision
  again**, tracked as item 13 in `scratch/blockers.md`.
- Nothing in this review has been implemented. `07-action-plan.md` is the execution order.

## Legend used across files

- 🔴 **Blocker** — will bite before/at first ship
- 🟠 **Major** — will cost real time or reliability soon
- 🟡 **Minor** — hygiene; fix when touching the area
- ✅ **Strength** — keep, don't "improve" away
- 📘 **Learn this** — the concept behind a recommendation, explained briefly

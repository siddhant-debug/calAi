---
name: requirements-brief
description: >
  Produce plans/<unit_id>-brief.md before any ADR or engineering stage on CalAI. Use when
  starting any non-trivial unit of work, when the user describes a feature or problem without
  a written spec, or when sdlc-orchestrator finds no brief for a unit. Also trigger on "what
  should we build", "scope this", "write a brief", or before dispatching architecture-designer.
---

# Requirements Brief Skill

A brief answers **what and why**. An ADR answers **how**. Writing the ADR first is how a
project ends up with an elegant design for the wrong problem — and how a pipeline stalls
halfway through because nobody decided a product question.

Output: `plans/<unit_id>-brief.md`, using the template below.

## Rules

1. **Every section is required.** "N/A" is a valid answer; blank is not. An unanswered section
   is a decision nobody made, which will surface later as rework.
2. **Separate product decisions from technical ones.** Anything tagged `USER-DECIDES` stops the
   pipeline until the user answers. Never guess a product decision and never launder one into a
   technical framing — "which of these should the UI show" is not an architecture question.
3. **Name real symbols.** File paths, endpoint paths, field names, enum values as they exist
   today. A brief that says "the meal endpoint" instead of `POST /api/parse-meal` with
   `meal_text` forces every downstream agent to re-derive it, and one of them will get it wrong.
4. **Success must be measurable.** "Better accuracy" is not a criterion; "calorie MAPE below
   30% on `evals/dataset/*.jsonl` with item precision not regressed" is.
5. **Out of scope is mandatory** and is the most useful section in the file. It's what stops
   scope creep three stages later.
6. **Don't design.** If you find yourself specifying function signatures, stop — that's the
   ADR's job.

## Template

```markdown
# Brief: <unit_id> — <short title>

**Status:** draft | ready | blocked on USER-DECIDES
**Date:** YYYY-MM-DD

## Problem
1–3 sentences on what is broken, missing, or risky *today*. State the cost of not doing this.
Not a description of the feature — the reason the feature exists.

## Users & trigger
Who does what, and what moment starts it.

## In scope
- Concrete, checkable bullets.

## Out of scope
- Explicitly excluded, with a one-line reason each. Required section.

## Success criteria
Measurable. A command, a number, or an observable behaviour.
- e.g. `python evals/run_eval.py --gate --baseline evals/report/latest.json` exits 0
- e.g. p95 for `POST /api/parse-meal` under 15s across 3 runs

## Constraints
Models (and cost/latency budget), platforms, privacy, offline behaviour, anything fixed.

## Contract touchpoints
Exact endpoints, Pydantic models, storage keys, or Dart files that may change. Name them
precisely. Mark each: unchanged / additive / **breaking**.

## Open product decisions
Each as `USER-DECIDES: <question>` with the realistic options and the tradeoff. The pipeline
stops on any of these that the work depends on.

## Naming to reuse
Existing symbols and conventions this work must match, so nothing invents a parallel name.

## Needs an ADR?
yes/no + why. "No" is common and fine — if there's no genuine design choice, hand straight to
the owning engineer.
```

## Where briefs live and who reads them

- Path: `plans/<unit_id>-brief.md`. `unit_id` is short and stable (`adr007-ifct`, `fe-integration`).
- `architecture-designer` reads it as its input contract and should refuse to start without one.
- `sdlc-orchestrator` checks for it before spawning any stage, and halts on unresolved
  `USER-DECIDES` items.
- The `Success criteria` section becomes `reviewer`'s acceptance check. Write it as something
  reviewer can actually run.

## Worked reference

`plans/adr005-requirements-brief.md` is the best existing example in this repo — exact file
paths, symbol names, dependency ordering, and explicitly flagged open tradeoffs. Match that
level of precision. Note what it does well: every requirement is independently verifiable, and
the two genuinely open tradeoffs are called out rather than silently resolved.

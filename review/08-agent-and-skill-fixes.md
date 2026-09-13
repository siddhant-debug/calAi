# 08 — Concrete fixes to agent & skill files (copy-paste ready)

Nothing here has been applied. Each block says the file, the exact text to change, and the
gap it closes. Apply in Step 1–2 of `07-action-plan.md`.

---

## 1. `skills/flutter-dev/skill.md` (G8)

**API calls block** — replace:
```
- `POST /api/parse-meal` → `{"text": "<meal description>"}`, returns `items[]`, `total_kcal`
```
with:
```
- `POST /api/parse-meal` → `{"meal_text": "<meal description>", "meal_type": "breakfast|lunch|dinner|snack"}`
  (`meal_type` optional, default `snack`), returns `items[]{name, quantity, unit, calories_kcal,
  protein_g, carbs_g, fat_g, confidence}`, `total_kcal`, `meal_type`, `model_latency_ms`
```
Then (Step 2) replace the whole "API calls" block with:
`See archdocs/api-contract.md (generated from the backend's OpenAPI — do not hand-edit).`

**State management line** — replace `Riverpod (flutter_riverpod ^2.5.1) — use StateNotifierProvider`
with `Riverpod 3 (flutter_riverpod ^3.4.3) — use Notifier / AsyncNotifier; expose AsyncValue for loading/error/data`.

**Coding rules + "After each file"** — replace `flutter analyze` with `dart analyze lib/<file>`
and add: `Colour alpha: always .withValues(alpha: x), never .withOpacity()`.

**Undecided behavior (G9)** — under "Technical facts", add a block:
```
### Decisions pending (USER-DECIDES — do not implement until resolved here)
- Multi-item rendering (one row per submission vs per item vs expandable)
- Nutrition detail shown (kcal only / + confidence marker / + macros)
- Ring range (Mon–Fri fixed / rolling 7 / Mon–Sun)
- meal_type affordance (infer by clock / chip row / default snack)
- In-flight state for 9–40 s calls (design required)
```

## 2. `skills/flutter-test/skill.md` (G8, G9)

- Step 1: `flutter analyze` → `dart analyze lib`.
- Step 4 curl bodies → replace with:
```bash
curl -X POST http://localhost:8000/api/calculate -H "Content-Type: application/json" \
  -d '{"age":25,"gender":"male","weight_kg":75,"height_cm":178,"activity_level":"moderately_active","goal":"maintain","goal_rate_kg_per_week":0.5}'

curl -X POST http://localhost:8000/api/parse-meal -H "Content-Type: application/json" \
  -d '{"meal_text":"2 eggs and toast","meal_type":"breakfast"}'
```
- Remove behavior assertions that are undecided ("button replaced with spinner", "5 rings
  Mon–Fri ISO week"); replace with `per skills/flutter-dev/skill.md §<heading>` references.
- Add: `Widget tests must not call the network; use ProviderScope overrides with fake services.`

## 3. `skills/flutter-review/skill.md` (G8, G9)

- Step 2: `flutter analyze lib/<file>` → `dart analyze lib/<file>`.
- Correctness: replace the two Mon–Fri ISO-week lines with
  `Ring range and totals window match skills/flutter-dev/skill.md "Day ring" section`.
- Add under Correctness: `Error handling covers the single backend error envelope (detail may
  be string or list until Step 4 lands — check both)`.

## 4. Every engineer + tester + reviewer agent file (G4, G5)

Append to `backend-engineer.md`, `ai-engineer.md`, `flutter-engineer.md`, `ui-engineer.md`, `tester.md`:

```markdown
## Report format (mandatory)
End your report with a fenced ```yaml block using exactly these keys:
unit_id, stage, files_changed, contract{before,after,breaking}, handoffs[{to,what,verbatim}],
tests{added,run_cmd,result}, logging_added, open_questions, deferred, risk.
The dispatcher forwards only this block. If open_questions is non-empty the pipeline stops.

## Definition of Done (tick all before reporting)
<paste the matching DoD list from review/03-target-sdlc.md §3.2 / §3.3>
```

Append to `reviewer.md` (also G13, G14):
```markdown
## Preconditions
- CI is green for the branch, or you ran `make lint test` (and `make eval` when prompts/models changed) and cite exit codes.

## Production lens (add to every backend review)
- Security: request body size limit on LLM routes; `meal_text` treated as untrusted (no instruction-following expected; injection case P8 tested); no secrets or raw user text in INFO logs; trace files redact user text unless `TRACE_RAW_TEXT=true`.
- Reliability: every model call has a timeout; retries bounded; fallback chain has ≥2 *live* models; termination test for any loop.
- Cost/latency: report p50/p95 (3 runs, median) for any change on the LLM path; tokens/request logged.
- Logging contract (ADR-005): structured fields `intent`, `handler`, `step`, `outcome`, `latency_ms`, correlation id at every decision point; WARNING on suspicious values.

## Docs-sync
- For every renamed/removed field, route, enum value or storage key: grep `skills/`, `archdocs/`, `CLAUDE.md`; list stale hits as bucket-1 findings.
- The status header of the plan/ADR this unit executes against is updated in the same run.
```

## 5. `sdlc-orchestrator.md` (G6, G7, G12)

Add to "What you do":
```markdown
0. **Require a brief.** If `plans/<unit_id>-brief.md` does not exist, produce one with the
   `requirements-brief` skill first. If it contains any USER-DECIDES item that is unresolved,
   stop and ask before spawning any engineer.
5. **Write the run record.** After the last stage, write `artefacts/runs/<YYYY-MM-DD>-<unit_id>.md`
   containing each stage's YAML report block, loops used, and the verdict. Update the status
   header of the plan/ADR you executed against.
```

## 6. `CLAUDE.md` (G10 — de-duplicate; G1/G2 — point to mechanisms)

- Replace the three restatements of "never read `.env`" / "dart analyze not flutter analyze"
  with one line each: `Enforced by hook (see .claude/settings.json); do not restate in agents.`
- Add under "Review gate": `CI green is a precondition for reviewer's verdict.`
- Add a "Release" pipeline: `backend-engineer (release checklist, review/03 §5) → reviewer`.
- Add "Pipeline 0 — Requirements": `requirements-brief skill → [architecture-designer]`.

## 7. New skill: `skills/requirements-brief/SKILL.md`

Frontmatter `name: requirements-brief`, description "Produce plans/<unit_id>-brief.md before any
ADR or engineering stage; used by dispatcher and sdlc-orchestrator." Body = template in
`review/03-target-sdlc.md §2`, plus the rule: *every section required; "N/A" allowed; blank not.*

## 8. Hooks: `.claude/settings.json` (G2)

```json
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Read|Bash", "hooks": [{"type": "command",
        "command": "bash .claude/scripts/block_env_read.sh"}]}
    ],
    "PostToolUse": [
      {"matcher": "Edit|Write", "hooks": [{"type": "command",
        "command": "bash .claude/scripts/post_edit_checks.sh"}]}
    ],
    "Stop": [ {"matcher": "", "hooks": [{"type": "command",
        "command": "bash .claude/scripts/memory_save_gate.sh"}]} ]
  }
}
```
`block_env_read.sh`: exit 2 with a message if the tool input path/command references `.env`
(not `.env.example`). `post_edit_checks.sh`: if path ends `.dart` under `calai_frontend/lib`
→ `dart analyze <file>`; if `.py` under `calai_backend` → `ruff check <file>`; print findings.
(Write these under `backend-engineer`; keep them < 30 lines each.)

## 9. `Makefile` (canonical commands for all agents)

```make
lint:   ; ruff check calai_backend evals && cd calai_frontend && dart analyze lib
test:   ; python -m pytest calai_backend/tests -q --cov=calai_backend --cov-report=term-missing
eval:   ; cd evals && python run_eval.py --gate --baseline report/latest.json --tolerance-pct 3
run:    ; uvicorn calai_backend.main:app --host 0.0.0.0 --port 8000 --reload
web:    ; cd calai_frontend && flutter run -d chrome
```
Every agent/skill command string then becomes `make <target>` — one spelling, fewer prompts.

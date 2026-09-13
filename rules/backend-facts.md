# Rule: backend hard facts

- **`@tool` location.** Tools in `calai_backend/tools/` are plain Python functions. Their
  `@tool`-decorated wrappers live alongside them in `calai_backend/tools/registry.py`
  (`ai-engineer`'s own file — edited directly, no handoff), exposed via
  `get_tools()`/`get_dict()`. `api/routes.py` has **no** `@tool` decorators — flag it if one
  appears there. `calai_agent.py` (the standalone learning track) is the one exception: it uses
  `@tool` + `@traceable` directly.
- **LLM provider.** NVIDIA NIM (`ChatNVIDIA`) as of ADR-006, not Ollama — no local-model
  fallback, `NVIDIA_API_KEY` required. `config.py`'s `LLM_MODELS` is a retry+fallback chain
  (currently 2 models). `ai-engineer` decides its contents (which models, what order — that's an
  LLM-provider call) but `config.py` itself is `backend-engineer`'s file, so `ai-engineer` states
  the exact list and hands it off. **Never trust a catalog's `deprecated: false` flag** — it has
  disagreed with reality (models it lists as live have returned `410 Gone`). Verify any
  new/changed model ID with one real call (`python evals/run_eval.py --model <id>`, or a direct
  `parse_meal_text` smoke call) and cite that verification in the report.
- **`MAX_STEPS = 8`** is the legacy ReAct loop's iteration cap, defined in `config.py`
  (`backend-engineer`'s file) but governs `ai-engineer`'s orchestration logic
  (`USE_ORCHESTRATOR=false` path only) — same hand-off rule as `LLM_MODELS`.
- **One error envelope, always.** `calai_backend/main.py` registers two exception handlers
  (`HTTPException` and `RequestValidationError`) that normalize every error path — hand-rolled
  `HTTPException(detail=...)` calls in routes/services and FastAPI's own request-validation
  failures — into one shape: `{"detail": {"message": <str>, "errors": <list[dict] | null>}}`.
  `errors` is the raw Pydantic error list on a 422 validation failure, `null` otherwise. Status
  codes are unchanged (400/404/422/500/502/503/504 etc.) — only the body shape normalized.
  **Done as of the P1 error-envelope unit** — frontend code written against the old two-shape
  contract (a bare `detail as String` or `detail as List` cast) needs updating; see
  `rules/invariants.md`'s entry for the now-stale "tolerate both shapes" compensation and
  `skills/flutter-review/SKILL.md`'s error-handling checklist item, both of which still describe
  the pre-normalization contract.
- **CORS.** Any endpoint reachable from a browser (`calai_frontend` web builds) needs
  `CORSMiddleware` scoped to the actual calling origin. `flutter run -d chrome` binds a new
  random port every run, so scope by `allow_origin_regex` (e.g. `http://localhost:\d+` for local
  dev), never a fixed port. `backend-engineer` verifies this is in place — never assumes it.

Referenced by: `CLAUDE.md`, `ai-engineer.md`, `backend-engineer.md`, `reviewer.md`,
`skills/calai-workflow/SKILL.md`.

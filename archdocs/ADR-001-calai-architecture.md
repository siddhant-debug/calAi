# ADR-001: System Architecture for CalAI — AI-Enabled Calorie Tracker

**Status:** Accepted (implemented — see ADR-002 for agent internals)  
**Date:** 2026-06-06 · **Updated:** 2026-08-01  
**Deciders:** Siddhant Tomar  
**Stack:** Flutter (client) · Python (backend) · Local LLM via HTTP

---

## Context

We are building **CalAI**, a calorie tracker where the primary input mechanism is **free-text** (e.g., "I had 2 eggs and a slice of toast for breakfast"). The app uses a **locally hosted LLM** (e.g., Ollama running on `localhost:11434`) to parse natural language into structured nutritional data, keeping all inference on-device / on-machine with no cloud dependency for core features.

Key forces at play:
- Privacy-first: food logs and inference stay local
- Offline-capable: no cloud LLM required at runtime
- Cross-platform: Flutter targets iOS, Android (and optionally desktop)
- Developer simplicity: two moving parts — Flutter app + Python API

---

## Decision

Adopt a **thin local REST API** architecture:

- **Flutter** is the UI layer; it sends text input to a local Python FastAPI server
- **Python FastAPI** is the orchestration layer; it formats prompts, calls the local LLM, parses the response, and persists data
- **Local LLM** (Ollama / llama.cpp) runs as a sidecar process on a fixed local port, serving a standard OpenAI-compatible `/v1/chat/completions` endpoint
- **SQLite** stores meals, nutritional history, and user goals (accessed only by the Python layer)

---

## Options Considered

### Option A: Flutter calls LLM directly (no Python layer)

Flutter HTTP client calls the local LLM port directly and parses JSON in Dart.

| Dimension | Assessment |
|-----------|------------|
| Complexity | Low (fewer moving parts) |
| Prompt logic | Dart — harder to iterate, no pip ecosystem |
| Food DB integration | Hard (no Python libraries like `usda-fdc`) |
| Testing | Unit-testing Dart parsing logic is harder |
| Offline | ✅ Full |

**Pros:** No Python server to manage, simpler deployment  
**Cons:** Prompt engineering + JSON parsing in Dart; no access to Python nutrition libraries; LLM output validation is painful without Pydantic  

---

### Option B: Flutter → Python FastAPI → Local LLM ✅ (Chosen)

Flutter sends text to a local Python FastAPI server; Python handles prompt construction, LLM call, response validation, and DB writes.

| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium (two local services) |
| Prompt logic | Python — fast iteration, rich ecosystem |
| Food DB integration | Easy (`usda-fdc`, `nutritionix`, custom CSV) |
| Testing | Pytest for API + LLM parsing logic |
| Offline | ✅ Full (all local) |

**Pros:** Clean separation of concerns; Pydantic validation of LLM output; easy to swap LLM providers; Python async handles concurrent requests gracefully  
**Cons:** User must run both the Flutter app and Python server (manageable on desktop; requires bundling strategy on mobile)  

---

### Option C: Flutter → Python → Cloud LLM (GPT-4o / Claude)

Same as Option B but uses an external API for inference.

| Dimension | Assessment |
|-----------|------------|
| Complexity | Low (no local LLM management) |
| Cost | API usage fees at scale |
| Privacy | ❌ Food logs leave the device |
| Offline | ❌ Not available offline |

**Rejected:** Conflicts with privacy-first, offline-capable requirements.

---

## Architecture Diagram

```
┌──────────────────────────────────────┐
│           Flutter App                │
│                                      │
│  [Text Input]  →  HTTP POST          │
│  [Profile Form]   /api/agent         │
│                   /api/parse-meal    │
│                   /api/calculate     │
│  [Dashboard]   ←  JSON response      │
└─────────────┬────────────────────────┘
              │ localhost:8000
              ▼
┌──────────────────────────────────────────────────────┐
│               Python FastAPI Server                   │
│                                                      │
│  GET  /api/health           → {"status":"ok"}        │
│                                                      │
│  POST /api/calculate        → direct tool pipeline   │
│    └─ calculate_bmr → calculate_tdee                 │
│       → calculate_calorie_goal (no LLM)              │
│                                                      │
│  POST /api/parse-meal       → nested LLM call        │
│    └─ parse_meal_text → ChatOllama(format="json")    │
│                                                      │
│  POST /api/agent            → ReAct loop             │
│    └─ run_agent(message, llm)                        │
│         ├─ llm.bind_tools([4 tools])                 │
│         ├─ loop up to MAX_STEPS=8                    │
│         │    ├─ LLM emits tool_call                  │
│         │    ├─ Python executes tool                 │
│         │    └─ ToolMessage injected into context    │
│         └─ LLM emits final answer → AgentResponse   │
└─────────────┬────────────────────────────────────────┘
              │ localhost:11434 (Ollama)
              ▼
┌──────────────────────────────────────┐
│       Local LLM (Ollama)             │
│   Model: qwen2.5:7b (tool-calling)   │
│   LangChain ChatOllama wrapper       │
└──────────────────────────────────────┘
```

### Internal Layer Diagram

```
api/routes.py  (HTTP + error mapping only)
      │
      ├─ /calculate ──► tools/bmr.py
      │                 tools/tdee.py
      │                 tools/calorie_goal.py
      │
      ├─ /parse-meal ──► tools/meal_parser.py
      │                       └─► providers/llm.py (get_json_llm)
      │
      └─ /agent ──► Depends(get_llm) ──► providers/llm.py
                        │
                        └─► services/agent_service.py (run_agent)
                                  ├─► prompts/calai_prompt.py
                                  └─► tools/registry.py (get_tools, get_dict)
                                            ├─ tools/bmr.py
                                            ├─ tools/tdee.py
                                            ├─ tools/calorie_goal.py
                                            └─ tools/meal_parser.py
```

---

## Key Technical Decisions

### 1. Local LLM: Ollama (preferred) vs llama.cpp vs LM Studio

**Chosen: Ollama**

| | Ollama | llama.cpp | LM Studio |
|--|--------|-----------|-----------|
| REST API | ✅ OpenAI-compatible | ✅ with server binary | ✅ |
| Model mgmt | `ollama pull llama3` | Manual GGUF download | GUI only |
| macOS / Linux | ✅ | ✅ | ✅ |
| Windows | ✅ | ✅ | ✅ |
| Programmable | ✅ | ✅ | ❌ (GUI) |

Ollama is the best fit: one-line model pulls, auto-loads on startup, OpenAI-compatible API means the Python client can swap models with one env var change.

**Model chosen:** `qwen2.5:7b`. Originally `llama3.2:3b` / `mistral:7b` were candidates and `qwen2.5:3b` was trialled, but the 3B models failed at reliable tool calling in the ReAct loop (malformed/absent `tool_calls`). See ADR-002 for the agent design that depends on this.

---

### 2. Prompt Design for Food Parsing

The Python layer wraps user text in a structured system prompt demanding JSON output:

```python
SYSTEM_PROMPT = """
You are a nutrition expert. Given a meal description in plain English, 
respond ONLY with valid JSON in this exact schema:
{
  "items": [
    {
      "name": "string",
      "quantity": "string",
      "unit": "string",
      "calories_kcal": number,
      "protein_g": number,
      "carbs_g": number,
      "fat_g": number,
      "confidence": "high|medium|low"
    }
  ],
  "total_calories_kcal": number
}
Do not include any text outside the JSON object.
"""
```

Response is validated via **Pydantic** before DB write. On parse failure, retry once with a stricter prompt.

---

### 3. Flutter ↔ Python Communication

- Flutter uses `http` or `dio` package for REST calls to `localhost:8000`
- On mobile, "localhost" requires the Python server to bind to `0.0.0.0` and Flutter to use the machine's LAN IP (for development) or `10.0.2.2` on Android emulator
- For production mobile, bundle the Python server as a background process using `flutter_background_service` + bundled Python (via Chaquopy on Android or a compiled binary on iOS)
- For desktop/development, simply run `python server.py` before launching the Flutter app

---

### 4. Data Model (SQLite)

```sql
-- Meals logged
CREATE TABLE meals (
  id          INTEGER PRIMARY KEY,
  logged_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
  raw_input   TEXT NOT NULL,
  items_json  TEXT NOT NULL,          -- serialized ParsedMeal JSON
  total_kcal  REAL NOT NULL,
  protein_g   REAL,
  carbs_g     REAL,
  fat_g       REAL
);

-- Daily goals
CREATE TABLE goals (
  id          INTEGER PRIMARY KEY,
  date        DATE UNIQUE,
  target_kcal REAL DEFAULT 2000
);
```

---

## Trade-off Analysis

| Concern | Flutter-only (A) | Flutter + Python (B) |
|---------|-----------------|----------------------|
| Setup friction | Low | Medium (run server) |
| Prompt iteration speed | Slow (Dart rebuilds) | Fast (Python hot reload) |
| Nutrition DB enrichment | Hard | Easy |
| LLM output validation | Manual Dart parsing | Pydantic |
| Mobile deployment | Simple | Complex (bundle server) |
| Future features (barcode scan, photo) | Add in Dart | Add Python endpoint |

**Verdict:** Option B's Python middle layer pays for itself immediately in prompt engineering velocity and data validation robustness. The "run server" friction is acceptable for a dev-phase app and solvable with packaging later.

---

## Consequences

**Becomes easier:**
- Swapping LLM models (change one env var: `OLLAMA_MODEL=mistral:7b`)
- Adding nutritional enrichment from USDA FoodData Central API
- Unit testing prompt/parsing logic in isolation
- Adding new endpoints (barcode lookup, photo-based logging via vision model)

**Becomes harder:**
- Mobile distribution (Python server bundling is non-trivial)
- Users must have Ollama installed and a model pulled (~2–4 GB)
- Localhost networking on physical Android/iOS devices during dev

**Revisit later:**
- If mobile distribution becomes a priority: evaluate Chaquopy (Android) or a compiled FastAPI binary
- If LLM accuracy is insufficient on 3B models: upgrade to 7B or add a RAG layer with a local food database

---

## Action Items

1. [x] Install Ollama + pull model — done, using `qwen2.5:7b` (not `llama3.2:3b`, see model decision above)
2. [x] Scaffold Python FastAPI project — done, `calai_backend/`
3. [x] Meal-parsing endpoint — shipped as `/api/parse-meal` (renamed from `/api/log-meal`)
4. [ ] Set up SQLite schema and `meals` repository class — designed (ADR-002 tools 5–6), not yet implemented
5. [x] Create Flutter project with basic text input UI — `calai_frontend/` skeleton complete
6. [ ] Wire Flutter to call the backend and render response — service stubs pending
7. [ ] Build Flutter dashboard showing daily calorie total and meal list — screens scaffolded, not wired
8. [x] Test end-to-end meal parse — verified via `/api/parse-meal`
9. [ ] Add retry logic for LLM parse failures
10. [ ] Evaluate model accuracy on 20 common meal descriptions and tune system prompt — planned as the `evals/` harness

---

## References

- [Ollama API docs](https://github.com/ollama/ollama/blob/main/docs/api.md)
- [FastAPI docs](https://fastapi.tiangolo.com/)
- [Flutter `http` package](https://pub.dev/packages/http)
- [USDA FoodData Central](https://fdc.nal.usda.gov/api-guide.html)

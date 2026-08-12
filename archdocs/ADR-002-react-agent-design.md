# ADR-002: ReAct Agent System Design — CalAI

**Status:** Implemented  
**Date:** 2026-06-06 · **Updated:** 2026-06-20  
**Model:** `qwen2.5:7b` via Ollama `localhost:11434`  
**Companion:** ADR-001 (overall system architecture)

---

## Context

The previous ADR established Flutter → Python → Ollama as the stack. This document specifies exactly **how the Python layer works**: a **ReAct (Reason + Act) agent loop** that decides which nutrition tools to call, executes them, observes results, and iterates until it has a complete, validated answer before returning to Flutter.

**Why ReAct over a single prompt?**  
A single prompt asking the LLM to "calculate my TDEE and daily calorie goal" requires it to do multi-step arithmetic reliably — something small 3B models fail at. ReAct separates reasoning (what to compute next) from computation (deterministic Python functions), so the LLM only needs to decide *what tool to call*, not *do the math*.

---

## ReAct Loop — How It Works

```
┌─────────────────────────────────────────────────────┐
│                   USER INPUT                         │
│  "I'm 25M, 75kg, 175cm, sedentary, want to lose     │
│   0.5kg/week. I had oats and 2 eggs for breakfast"   │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
         ┌────────────────┐
         │   THOUGHT      │  LLM reasons: "I need BMR first,
         │   (LLM)        │   then TDEE, then calorie goal,
         └────────┬───────┘   then parse the meal."
                  │
                  ▼
         ┌────────────────┐
         │   ACTION       │  LLM emits: TOOL_CALL: calculate_bmr
         │   (LLM output) │  ARGS: {"weight":75,"height":175,
         └────────┬───────┘         "age":25,"gender":"male"}
                  │
                  ▼
         ┌────────────────┐
         │   OBSERVE      │  Python executes tool → returns
         │   (Python)     │  {"bmr_kcal": 1822.5}
         └────────┬───────┘
                  │
                  ▼
         ┌────────────────┐
         │  LOOP AGAIN?   │  Inject observation into context.
         │  Check: done?  │  LLM sees result, reasons next step.
         └────────┬───────┘
                  │ (repeat up to MAX_STEPS=8)
                  ▼
         ┌────────────────┐
         │  FINAL ANSWER  │  LLM emits FINAL_ANSWER: {...}
         │  Validate      │  Python validates schema → return
         └────────────────┘
```

---

## Functional Requirements

1. Parse free-text user profile + meal description in one input
2. Compute BMR, TDEE, and calorie goal deterministically
3. Parse meal text into structured nutrition items via LLM
4. Sum daily intake and compare to goal
5. Return a single JSON response to Flutter
6. Loop until all required fields are populated and validated
7. Abort after MAX_STEPS to prevent infinite loops

## Non-Functional Requirements

- Latency: original target was < 8s end-to-end with a 3B model. **Not met** — measured reality with `qwen2.5:7b` running locally is ~140s for a single `/api/parse-meal` call (see API Surface below). The target stands only for GPU-hosted / remote-Ollama setups; revisit with streaming or a smaller parse-only model.
- Reliability: retry on malformed LLM output, fallback to re-prompt
- Offline: 100% local, no external API calls in hot path

---

## Tool Registry

### Mandatory Input Attributes (for calorie tools)

| Attribute | Type | Required | Notes |
|-----------|------|----------|-------|
| `weight_kg` | float | ✅ | Current body weight |
| `height_cm` | float | ✅ | Standing height |
| `age` | int | ✅ | Years |
| `gender` | enum | ✅ | `male` / `female` |
| `activity_level` | enum | ✅ | See TDEE tool |
| `goal` | enum | ✅ | `lose` / `maintain` / `gain` |

### Optional Attributes

| Attribute | Type | Notes |
|-----------|------|-------|
| `goal_rate_kg_per_week` | float | Default 0.5 for lose/gain |
| `body_fat_pct` | float | Enables Katch-McArdle BMR |

---

### Tool 1: `calculate_bmr`

Computes Basal Metabolic Rate using **Mifflin-St Jeor** (default) or **Katch-McArdle** if body fat % is provided.

**Mandatory:** `weight_kg`, `height_cm`, `age`, `gender`  
**Optional:** `body_fat_pct`

**Formula (Mifflin-St Jeor):**
```
Male:   BMR = 10×weight + 6.25×height − 5×age + 5
Female: BMR = 10×weight + 6.25×height − 5×age − 161
```

**Returns:**
```json
{
  "bmr_kcal": 1822.5,
  "formula_used": "mifflin_st_jeor"
}
```

---

### Tool 2: `calculate_tdee`

Multiplies BMR by an activity factor.

**Mandatory:** `bmr_kcal`, `activity_level`

| `activity_level` | Multiplier | Description |
|-----------------|------------|-------------|
| `sedentary` | 1.2 | Desk job, no exercise |
| `lightly_active` | 1.375 | Light exercise 1–3 days/week |
| `moderately_active` | 1.55 | Moderate exercise 3–5 days/week |
| `very_active` | 1.725 | Hard exercise 6–7 days/week |
| `extra_active` | 1.9 | Physical job + daily exercise |

**Returns:**
```json
{
  "tdee_kcal": 2187.0,
  "activity_level": "sedentary",
  "multiplier": 1.2
}
```

---

### Tool 3: `calculate_calorie_goal`

Applies goal deficit/surplus to TDEE.

**Mandatory:** `tdee_kcal`, `goal`  
**Optional:** `goal_rate_kg_per_week` (default: 0.5)

**Logic:**
- 1 kg of body fat ≈ 7700 kcal
- Weekly deficit/surplus = `goal_rate_kg_per_week × 7700`
- Daily delta = weekly / 7
- Minimum floor: 1200 kcal (female) / 1500 kcal (male)

**Returns:**
```json
{
  "daily_goal_kcal": 1937.0,
  "daily_delta_kcal": -250,
  "goal": "lose",
  "rate_kg_per_week": 0.5,
  "macros_suggested": {
    "protein_g": 150,
    "carbs_g": 193,
    "fat_g": 64
  }
}
```

Macro split: 30% protein / 40% carbs / 30% fat (adjustable via config).

---

### Tool 4: `parse_meal_text`

Sends free-text meal description to the LLM with a strict JSON extraction prompt. This is the **only tool that calls the LLM internally**; all other tools are pure Python.

**Mandatory:** `meal_text`  
**Optional:** `meal_type` (`breakfast` / `lunch` / `dinner` / `snack`)

**Returns:**
```json
{
  "items": [
    {
      "name": "oats",
      "quantity": 80,
      "unit": "g",
      "calories_kcal": 303,
      "protein_g": 11,
      "carbs_g": 54,
      "fat_g": 5,
      "confidence": "high"
    },
    {
      "name": "egg",
      "quantity": 2,
      "unit": "whole",
      "calories_kcal": 144,
      "protein_g": 12,
      "carbs_g": 1,
      "fat_g": 10,
      "confidence": "high"
    }
  ],
  "total_kcal": 447,
  "meal_type": "breakfast"
}
```

**Validation:** Pydantic model. If confidence is `low` on any item, the agent will emit a clarifying question in the final answer.

---

### Tool 5: `get_daily_summary` — ⏳ designed, not yet implemented

Aggregates all meals logged today from SQLite. Called when user asks "how am I doing today".

**Mandatory:** `date` (ISO format, default today)

**Returns:**
```json
{
  "date": "2026-06-06",
  "meals_logged": 2,
  "total_kcal": 847,
  "goal_kcal": 1937,
  "remaining_kcal": 1090,
  "macros": {"protein_g": 45, "carbs_g": 92, "fat_g": 22}
}
```

---

### Tool 6: `save_meal` — ⏳ designed, not yet implemented

Persists a parsed meal to SQLite.

**Mandatory:** `parsed_meal` (output of `parse_meal_text`)  
**Returns:** `{"meal_id": 42, "saved": true}`

---

## System Prompt for ReAct Agent

> **Superseded (2026-06-20):** the manual `THOUGHT / ACTION / ARGS / FINAL_ANSWER` text protocol below was the original design. The implementation now uses LangChain's **native tool-call protocol** — the model emits structured `tool_calls` on the `AIMessage`, so no text-format parsing exists in the code. The live system prompt is auto-generated from tool docstrings in `prompts/calai_prompt.py`. The ordering rules (BMR → TDEE → goal; parse before save; never guess numbers) are carried over into that prompt and remain in force. Original design kept below for historical context:

```
You are CalAI, a nutrition assistant. You have access to these tools:
- calculate_bmr(weight_kg, height_cm, age, gender, body_fat_pct?)
- calculate_tdee(bmr_kcal, activity_level)
- calculate_calorie_goal(tdee_kcal, goal, goal_rate_kg_per_week?)
- parse_meal_text(meal_text, meal_type?)
- get_daily_summary(date?)
- save_meal(parsed_meal)

Format EVERY response as one of:
  THOUGHT: <your reasoning about what to do next>
  ACTION: <tool_name>
  ARGS: <JSON args>

OR when done:
  FINAL_ANSWER: <JSON result>

Rules:
1. Always call calculate_bmr before calculate_tdee.
2. Always call calculate_tdee before calculate_calorie_goal.
3. Always call parse_meal_text before save_meal.
4. If a mandatory arg is missing, include it in FINAL_ANSWER as a clarifying question.
5. Never guess numeric values — use tools for all calculations.
6. Respond ONLY with the exact format above. No prose outside it.
```

---

## Agent Loop — Implementation

The loop is implemented as `run_agent(message, llm)` in `services/agent_service.py`. It uses LangChain's native tool-call protocol — no manual THOUGHT/ACTION/ARGS text parsing needed; the model emits structured `tool_calls` on the `AIMessage`.

```python
# services/agent_service.py (simplified)

def run_agent(message: str, llm: BaseChatModel) -> AgentResponse:
    tools = get_tools()          # from tools/registry.py
    llm_with_tools = llm.bind_tools(tools)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),   # from prompts/calai_prompt.py
        HumanMessage(content=message),
    ]

    for iteration in range(1, MAX_STEPS + 1):
        ai_message = llm_with_tools.invoke(messages)

        if not ai_message.tool_calls:
            # LLM produced a final answer — no more tool calls
            return AgentResponse(response=ai_message.content or "", iterations_used=iteration)

        # Execute the first requested tool
        tool_call = ai_message.tool_calls[0]
        tool_fn = tools_dict[tool_call["name"]]
        observation = tool_fn.invoke(tool_call["args"])

        # Inject result back into context as a ToolMessage
        messages.append(ai_message)
        messages.append(ToolMessage(content=str(observation), tool_call_id=tool_call["id"]))

    raise HTTPException(status_code=500, detail="Agent reached max iterations.")
```

**Key differences from original design:**
- No `ReActAgent` class — plain function, injected `llm` via FastAPI `Depends`
- Tool dispatch uses LangChain `tool_call["name"]` not manual text parsing
- Observation injected as `ToolMessage`, not raw `"OBSERVATION: ..."` string
- System prompt is auto-generated from tool docstrings in `tools/registry.py`

---

## End-to-End Example

**User input:**
```
"I'm 25 year old male, 75kg, 175cm, sedentary lifestyle, 
want to lose 0.5kg per week. I had oats and 2 eggs for breakfast."
```

**Agent trace:**
```
Step 1:
  THOUGHT: I have weight, height, age, gender. I'll compute BMR first.
  ACTION: calculate_bmr
  ARGS: {"weight_kg": 75, "height_cm": 175, "age": 25, "gender": "male"}
  OBSERVATION: {"bmr_kcal": 1822.5, "formula_used": "mifflin_st_jeor"}

Step 2:
  THOUGHT: BMR done. Activity is sedentary. Compute TDEE.
  ACTION: calculate_tdee
  ARGS: {"bmr_kcal": 1822.5, "activity_level": "sedentary"}
  OBSERVATION: {"tdee_kcal": 2187.0, "multiplier": 1.2}

Step 3:
  THOUGHT: TDEE done. Goal is lose 0.5kg/week. Compute calorie goal.
  ACTION: calculate_calorie_goal
  ARGS: {"tdee_kcal": 2187.0, "goal": "lose", "goal_rate_kg_per_week": 0.5}
  OBSERVATION: {"daily_goal_kcal": 1937.0, "daily_delta_kcal": -250, ...}

Step 4:
  THOUGHT: Now parse the breakfast meal.
  ACTION: parse_meal_text
  ARGS: {"meal_text": "oats and 2 eggs", "meal_type": "breakfast"}
  OBSERVATION: {"items": [...], "total_kcal": 447}

Step 5:
  THOUGHT: Meal parsed. Save it.
  ACTION: save_meal
  ARGS: {"parsed_meal": {...}}
  OBSERVATION: {"meal_id": 1, "saved": true}

Step 6:
  THOUGHT: I have everything. Compose final answer.
  FINAL_ANSWER: {
    "bmr_kcal": 1822.5,
    "tdee_kcal": 2187.0,
    "daily_goal_kcal": 1937.0,
    "breakfast": {"total_kcal": 447, "items": [...]},
    "remaining_kcal": 1490,
    "macros_suggested": {"protein_g": 150, "carbs_g": 193, "fat_g": 64},
    "message": "Great start! 447 kcal consumed, 1,490 kcal remaining today."
  }
```

**Total steps: 6 of 8 max. ✅**

---

## Validation & Stopping Conditions

| Condition | Behavior |
|-----------|----------|
| `FINAL_ANSWER` emitted | Validate against `FinalAnswer` Pydantic schema, return to Flutter |
| Malformed tool call | Re-prompt with format reminder (max 2 retries per step) |
| Tool raises exception | Inject error observation, let agent adapt |
| Missing mandatory field | Agent includes `"missing_fields": ["age"]` in FINAL_ANSWER |
| MAX_STEPS exceeded | Return `{"error": "agent_timeout", "partial": last_known_state}` |
| LLM hallucinated tool name | Catch `KeyError`, inject `OBSERVATION ERROR: unknown tool` |

---

## Project File Structure

```
calai_backend/
├── main.py                      # FastAPI app init, logging config
├── config.py                    # OLLAMA_BASE_URL, MODEL_NAME, MAX_STEPS
├── schemas.py                   # Pydantic: CalcRequest/Response, AgentRequest/Response,
│                                #           MealParseRequest/Response, MealItem
├── api/
│   └── routes.py                # HTTP layer only — 3 endpoints + error mapping
├── services/
│   └── agent_service.py         # run_agent(message, llm) — full ReAct loop
├── providers/
│   └── llm.py                   # get_llm() / get_json_llm() — FastAPI Depends factory
├── prompts/
│   └── calai_prompt.py          # SYSTEM_PROMPT (auto-built from tool docstrings)
└── tools/
    ├── registry.py              # @tool wrappers + get_tools() / get_dict()
    ├── bmr.py                   # calculate_bmr() — pure Python
    ├── tdee.py                  # calculate_tdee() — pure Python
    ├── calorie_goal.py          # calculate_calorie_goal() — pure Python
    └── meal_parser.py           # parse_meal_text() — calls get_json_llm()
```

**Design rules:**
- `tools/*.py` (except `registry.py`) are plain Python — no `@tool`, no LLM imports
- `@tool` wrappers live exclusively in `tools/registry.py`
- To add a 5th tool: create `tools/newtool.py` + add `@tool` wrapper in `registry.py` — `routes.py` never changes
- To swap LLM (Ollama → Claude): change `providers/llm.py` only

---

## API Surface (FastAPI)

```
GET  /api/health
Response: {"status": "ok"}

POST /api/calculate
Body: {
  "weight_kg": 75,
  "height_cm": 175,
  "age": 25,
  "gender": "male",
  "activity_level": "sedentary",
  "goal": "lose",
  "goal_rate_kg_per_week": 0.5
}
Response: {
  "bmr_kcal": 1822.5,
  "tdee_kcal": 2187.0,
  "calorie_goal_kcal": 1937.0
}
Note: Direct tool pipeline — no LLM involved.

POST /api/parse-meal
Body: {
  "meal_text": "2 eggs and oats",
  "meal_type": "breakfast"       // breakfast | lunch | dinner | snack
}
Response: {
  "items": [...],
  "total_kcal": 447,
  "meal_type": "breakfast",
  "model_latency_ms": 3210.5
}
Note: Calls LLM with format="json". Latency is dominated by this call (~140s on 7b locally).

POST /api/agent
Body: {
  "message": "I'm 25M, 75kg, 175cm, sedentary, want to lose 0.5kg/week. I had oats and 2 eggs."
}
Response: {
  "response": "Your daily calorie goal is 1937 kcal. Breakfast was 447 kcal...",
  "iterations_used": 4
}
Note: Full ReAct loop. Runs up to MAX_STEPS=8 tool calls before returning.
```

---

## Consequences

**Becomes easier:**
- Adding new tools (barcode scanner, recipe parser, water tracker) — register in `TOOL_REGISTRY`
- Testing tools in isolation — pure Python functions, no LLM needed
- Prompt tuning — `SYSTEM_PROMPT` + few-shot examples in one file
- The LLM only needs to output structured text, not do math — `qwen2.5:3b` handles this well

**Becomes harder:**
- Debugging mid-loop failures — need to log full `history` per request
- Step count is unpredictable — some requests hit 7-8 steps → latency spikes

**Revisit later:**
- Structured output mode (Ollama `format: json`) to eliminate parsing brittleness
- Few-shot examples in system prompt to improve qwen2.5:3b tool-call format adherence
- Streaming responses to Flutter so UI shows incremental progress

---

## Action Items

1. [x] Create `calai_backend/` project — done
2. [ ] Implement all 6 tool functions — **4 of 6 done** (`calculate_bmr`, `calculate_tdee`, `calculate_calorie_goal`, `parse_meal_text`); `get_daily_summary` + `save_meal` pending
3. [x] Agent loop — done, but as plain `run_agent()` in `services/agent_service.py`, not a `ReActAgent` class (see "Key differences from original design")
4. [x] System prompt — done, auto-generated from tool docstrings in `prompts/calai_prompt.py`
5. [x] Pydantic schemas in `schemas.py` — done for implemented endpoints; `DailySummary` pending with tools 5–6
6. [x] `POST /api/agent` wired with `Depends(get_llm)` injection
7. [x] End-to-end test with profile + meal input — verified
8. [ ] Add full history logging per request (file or DB) for debugging agent traces
9. [x] Model tuning — resolved by switching `qwen2.5:3b` → `qwen2.5:7b` and native tool calls (no text-format parsing to break)
10. [ ] Flutter: send `user_profile` on first setup, cache locally, attach to every request — pending frontend wiring

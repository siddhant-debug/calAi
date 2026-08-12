# CalAI Backend — Call Flow & SOLID Fix Log

**Date:** 2026-06-20  
**Scope:** `calai_backend/` after P1–P3 fixes applied

---

## 1. Call Flow by Endpoint

### POST `/api/calculate`

No LLM. Direct deterministic pipeline.

```
HTTP POST /api/calculate  (CalcRequest)
│
└─► api/routes.py → calculate(req)
      │
      ├─ try:
      │    ├─► tools/bmr.py → calculate_bmr(weight_kg, height_cm, age, gender)
      │    │       └─ Mifflin-St Jeor formula → float (BMR kcal)
      │    │
      │    ├─► tools/tdee.py → calculate_tdee(bmr, activity_level)
      │    │       └─ bmr × ACTIVITY_MULTIPLIERS[activity_level] → float
      │    │
      │    └─► tools/calorie_goal.py → calculate_calorie_goal(tdee, goal, rate)
      │             └─ ±(rate × 7700 / 7) applied to tdee → float
      │
      ├─ except ValueError → HTTPException 422
      │
      └─ return CalcResponse(bmr_kcal, tdee_kcal, calorie_goal_kcal)
```

---

### POST `/api/parse-meal`

One nested LLM call inside the tool. No agent loop.

```
HTTP POST /api/parse-meal  (MealParseRequest)
│
└─► api/routes.py → parse_meal(req)
      │
      ├─ try:
      │    └─► tools/meal_parser.py → parse_meal_text(meal_text, meal_type)
      │              │
      │              ├─ validate meal_type in ("breakfast","lunch","dinner","snack")
      │              ├─ escape { } in meal_text  ← P1 fix
      │              ├─► providers/llm.py → get_json_llm()
      │              │       └─ ChatOllama(format="json") → BaseChatModel
      │              ├─ llm.invoke([HumanMessage(prompt)])  → AIMessage
      │              │       [Ollama at localhost:11434]
      │              └─ json.loads(response.content) → dict
      │
      ├─ except httpx.ConnectError  → HTTPException 503
      ├─ except httpx.ReadError     → HTTPException 503
      ├─ except httpx.TimeoutException → HTTPException 504  ← P1 fix
      ├─ except ValueError          → HTTPException 422
      │
      ├─ try:
      │    └─ MealParseResponse(**result, model_latency_ms=latency_ms)
      ├─ except ValidationError     → HTTPException 502   ← P2 fix
      │
      └─ return MealParseResponse
```

---

### POST `/api/agent`

Full ReAct loop. LLM decides which tools to call each iteration.

```
HTTP POST /api/agent  (AgentRequest)
│
└─► api/routes.py → agent(req, llm = Depends(get_llm))
      │                         │
      │              providers/llm.py → get_llm()
      │                         └─ ChatOllama(temperature=0) → BaseChatModel
      │
      └─► services/agent_service.py → run_agent(message, llm)
            │
            ├─► tools/registry.py → get_tools()    → [4 LangChain tool objects]
            ├─► tools/registry.py → get_dict()     → {name: tool_fn}
            ├─► prompts/calai_prompt.py → SYSTEM_PROMPT
            │         (auto-built from tool docstrings)
            │
            ├─ llm_with_tools = llm.bind_tools(tools)
            ├─ messages = [SystemMessage(SYSTEM_PROMPT), HumanMessage(message)]
            │
            └─ for iteration in 1..MAX_STEPS:
                  │
                  ├─ try:
                  │    └─ ai_message = llm_with_tools.invoke(messages)
                  │         [Ollama at localhost:11434]
                  ├─ except httpx.ConnectError      → HTTPException 503
                  ├─ except httpx.ReadError         → HTTPException 503
                  ├─ except httpx.HTTPStatusError   → HTTPException 502
                  ├─ except httpx.TimeoutException  → HTTPException 504  ← P1 fix
                  │
                  ├─ if no tool_calls:
                  │    └─ return AgentResponse(content or "", iteration)  ← P2 fix
                  │                                  (or "" guards None)
                  │
                  ├─ tool_call = ai_message.tool_calls[0]
                  ├─ tool_fn   = tools_dict[tool_call["name"]]
                  │
                  ├─ try:
                  │    └─ observation = tool_fn.invoke(tool_call["args"])
                  │         │
                  │         ├─ "calculate_bmr"
                  │         │    └─► tools/registry.py → _bmr_tool
                  │         │              └─► tools/bmr.py → calculate_bmr(...)
                  │         │
                  │         ├─ "calculate_tdee"
                  │         │    └─► tools/registry.py → _tdee_tool
                  │         │              └─► tools/tdee.py → calculate_tdee(...)
                  │         │
                  │         ├─ "calculate_calorie_goal"
                  │         │    └─► tools/registry.py → _calorie_goal_tool
                  │         │              └─► tools/calorie_goal.py → calculate_calorie_goal(...)
                  │         │
                  │         └─ "parse_meal_text"
                  │              └─► tools/registry.py → _parse_meal_tool
                  │                        └─► tools/meal_parser.py → parse_meal_text(...)
                  │                                  └─► providers/llm.py → get_json_llm()
                  │                                        └─ nested LLM call
                  │
                  ├─ except (ConnectError, ReadError) → HTTPException 503  ← P1 fix
                  ├─ except TimeoutException          → HTTPException 504  ← P1 fix
                  ├─ except ValueError                → HTTPException 422
                  │
                  ├─ content = str(obs) if obs is not None else "Tool completed."  ← P3 fix
                  ├─ messages.append(ai_message)
                  └─ messages.append(ToolMessage(content, tool_call_id))

            └─ (if loop exhausted) → HTTPException 500
```

---

## 2. SOLID — What Was Broken and How It Was Fixed

---

### S — Single Responsibility Principle

**Problem:**  
`api/routes.py` (213 lines) owned five unrelated responsibilities simultaneously:

| Responsibility | Lines |
|---|---|
| HTTP routing + request/response | ~40 lines |
| `@tool` wrappers for LangChain | ~30 lines |
| Tool registry (`_TOOLS`, `_TOOLS_DICT`) | 2 lines |
| ReAct loop logic | ~55 lines |
| `SYSTEM_PROMPT` constant | ~10 lines |

Editing one concern (e.g., swapping the agent loop) required navigating all five.

**Fix:**  
Each responsibility extracted to its own module:

| Responsibility | Moved to |
|---|---|
| HTTP routing + error mapping | `api/routes.py` (95 lines now) |
| `@tool` wrappers + registry | `tools/registry.py` |
| ReAct loop logic | `services/agent_service.py` |
| `SYSTEM_PROMPT` | `prompts/calai_prompt.py` |
| LLM construction | `providers/llm.py` |

`routes.py` `/agent` endpoint is now literally one line:
```python
def agent(req: AgentRequest, llm: BaseChatModel = Depends(get_llm)) -> AgentResponse:
    return run_agent(req.message, llm)
```

---

### O — Open/Closed Principle

**Problem:**  
Adding a 5th tool (e.g., `track_water_intake`) required editing `routes.py` in 3 separate places:
1. Write a new `@tool` wrapper function
2. Append it to `_TOOLS` list
3. Manually update `SYSTEM_PROMPT` to mention it

Open for modification instead of extension.

**Fix — Tool Registry:**  
```python
# tools/registry.py
@tool("calculate_bmr")
def _bmr_tool(...): ...

_TOOLS = [_bmr_tool, _tdee_tool, _calorie_goal_tool, _parse_meal_tool]

def get_tools() -> list: return list(_TOOLS)
def get_dict()  -> dict: return {t.name: t for t in _TOOLS}
```

**Fix — Dynamic SYSTEM_PROMPT:**  
```python
# prompts/calai_prompt.py
_TOOL_LIST = "\n".join(f"- {t.name}: {t.description}" for t in get_tools())
SYSTEM_PROMPT = f"You are CalAI. You have four tools:\n{_TOOL_LIST}\n..."
```

Adding a 5th tool now = one new `@tool` wrapper in `registry.py`. `routes.py` is closed — it never changes.

---

### L — Liskov Substitution Principle

**Problem:**  
The implicit contract was: every tool must return a value that is meaningful when cast through `str()` as a `ToolMessage`. If a future tool returned `None` (e.g., a write-only DB tool), `str(None)` = `"None"` was silently injected into the LLM context. The LLM would likely interpret it as a failed call and retry until `MAX_STEPS`.

**Fix:**  
Explicit contract enforcement at the injection point:
```python
# services/agent_service.py
content = str(observation) if observation is not None else "Tool completed successfully."
messages.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
```

All current tools also have explicit return type annotations (`-> float`, `-> dict`) making the contract visible at the function signature level.

---

### I — Interface Segregation Principle

**Problem:**  
`CalcRequest` is a fat schema — a caller who only wants BMR must still provide `activity_level` and `goal`, which are irrelevant to BMR:

```python
class CalcRequest(BaseModel):
    weight_kg: float; height_cm: float; age: int; gender: Literal[...]
    activity_level: Literal[...]         # needed for TDEE, not BMR
    goal: Literal["lose","maintain","gain"]  # needed for goal, not BMR/TDEE
    goal_rate_kg_per_week: float = 0.5
```

**Status: Partially addressed — not yet refactored.**  
The current `/api/calculate` endpoint computes the full pipeline (BMR→TDEE→Goal) in one shot, so the fat schema matches actual usage. The violation becomes real if we ever expose a `/api/bmr-only` endpoint.

**Planned fix (future):**
```python
class UserStatsSchema(BaseModel):
    weight_kg: float; height_cm: float; age: int; gender: Literal["male","female"]

class ActivitySchema(BaseModel):
    activity_level: Literal["sedentary","lightly_active","moderately_active","very_active","extra_active"]

class GoalSchema(BaseModel):
    goal: Literal["lose","maintain","gain"]
    goal_rate_kg_per_week: float = Field(default=0.5, gt=0)

class CalcRequest(UserStatsSchema, ActivitySchema, GoalSchema): pass  # unchanged for /calculate
```

---

### D — Dependency Inversion Principle

**Problem:**  
High-level modules (`routes.py`, `meal_parser.py`) depended directly on `ChatOllama`, a concrete class:

```python
# routes.py — line 148
llm = ChatOllama(model=MODEL_NAME, base_url=OLLAMA_BASE_URL, temperature=0)

# meal_parser.py — line 41
llm = ChatOllama(model=MODEL_NAME, base_url=OLLAMA_BASE_URL, temperature=0, format="json")
```

Consequences:
- Swapping to Claude required editing two files with identical constructor arguments
- A new `ChatOllama` connection was opened on every request (no reuse)
- Impossible to inject a mock in tests without patching at the class level

**Fix — Factory functions + FastAPI `Depends`:**
```python
# providers/llm.py
def get_llm() -> BaseChatModel:
    return ChatOllama(model=MODEL_NAME, base_url=OLLAMA_BASE_URL, temperature=0)

def get_json_llm() -> BaseChatModel:
    return ChatOllama(model=MODEL_NAME, base_url=OLLAMA_BASE_URL, temperature=0, format="json")
```

```python
# api/routes.py — /agent now receives llm as an injected dependency
@router.post("/agent")
def agent(req: AgentRequest, llm: BaseChatModel = Depends(get_llm)) -> AgentResponse:
    return run_agent(req.message, llm)
```

```python
# tools/meal_parser.py — calls factory, doesn't construct directly
llm = get_json_llm()
```

**To swap to Claude:** change only `providers/llm.py`:
```python
from langchain_anthropic import ChatAnthropic

def get_llm() -> BaseChatModel:
    return ChatAnthropic(model="claude-sonnet-4-6", temperature=0)
```

`routes.py`, `agent_service.py`, `meal_parser.py` — zero changes needed.

---

## 3. Summary Table

| Principle | Violation | Fix | Files |
|---|---|---|---|
| S | `routes.py` had 5 responsibilities | Extracted to 4 new modules | `services/`, `providers/`, `prompts/`, `tools/registry.py` |
| O | Adding a tool = edit `routes.py` in 3 places | Registry + dynamic prompt | `tools/registry.py`, `prompts/calai_prompt.py` |
| L | `None` return → `"None"` silently fed to LLM | Explicit None guard at ToolMessage injection | `services/agent_service.py:65` |
| I | Fat `CalcRequest` forces unrelated fields | Planned schema split | `schemas.py` (future) |
| D | `ChatOllama` hardcoded in 2 files | `get_llm()` / `Depends` factory | `providers/llm.py` |

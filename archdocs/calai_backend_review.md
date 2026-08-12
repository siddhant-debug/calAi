# CalAI Backend — Code Review Report

**Scope:** `calai_backend/` · **Lens:** SOLID principles, exception handling, design patterns, scaling readiness  
**Date:** 2026-06-20

---

## Exception Handling Gaps (Correctness Bugs)

### 1. Nested `httpx` errors from `parse_meal_text` are uncaught inside the agent loop
**File:** `calai_backend/api/routes.py` · **Line:** 201–204

```python
try:
    observation = tool_fn.invoke(tool_args)
except ValueError as e:          # ← only ValueError is caught
    raise HTTPException(status_code=422, detail=str(e))
```

`tool_fn.invoke(tool_args)` can invoke `_parse_meal_tool` → `parse_meal_text` → `ChatOllama.invoke()`.  
That inner LLM call can raise `httpx.ConnectError`, `httpx.ReadError`, `httpx.TimeoutException` — none of those are subclasses of `ValueError`, so they fall through as unhandled `500 Internal Server Error` with a raw Python traceback exposed to the client.

**Fix:** Add the same `httpx` catches you have on the outer LLM call, or wrap tool invocation in a broad `except Exception` that maps to a clean HTTP error.

---

### 2. `httpx.TimeoutException` uncaught in both endpoints
**File:** `calai_backend/api/routes.py` · **Lines:** 68–82 (`/parse-meal`), 162–181 (`/agent`)

Neither endpoint catches `httpx.TimeoutException`. When Ollama is under load and takes >30s to respond, FastAPI propagates an unhandled exception — raw traceback to client, no log context. `TimeoutException` is a distinct httpx class, not a subclass of `ConnectError` or `ReadError`.

**Fix:**
```python
except httpx.TimeoutException:
    raise HTTPException(status_code=504, detail=f"Ollama timed out — model '{MODEL_NAME}' may be overloaded.")
```

---

### 3. `ai_message.content` can be `None` → Pydantic validation crash
**File:** `calai_backend/api/routes.py` · **Line:** 189

```python
return AgentResponse(response=ai_message.content, iterations_used=iteration)
```

`AgentResponse.response` is typed `str`. Ollama (and LangChain's wrapper) can return `None` for `content` when the model produces an empty response with no tool calls. Pydantic v2 will raise a `ValidationError` → unhandled 500.

**Fix:**
```python
return AgentResponse(response=ai_message.content or "", iterations_used=iteration)
```

---

### 4. `/calculate` endpoint has zero exception handling
**File:** `calai_backend/api/routes.py` · **Lines:** 34–54

```python
@router.post("/calculate", response_model=CalcResponse)
def calculate(req: CalcRequest) -> CalcResponse:
    bmr = calculate_bmr(...)      # raises ValueError on bad gender
    tdee = calculate_tdee(...)    # raises ValueError on bad activity_level
    goal_kcal = calculate_calorie_goal(...)  # raises ValueError on bad goal
```

All three tool functions raise `ValueError` for invalid inputs. Even though Pydantic's `Literal` types guard the schema fields, a future schema change or internal call could expose these uncaught `ValueError`s as 500s instead of 422s.

**Fix:** Wrap in `try/except ValueError` → `HTTPException(422)`, consistent with `/parse-meal`.

---

### 5. `MealParseResponse(**result, ...)` — no key validation before unpacking
**File:** `calai_backend/api/routes.py` · **Line:** 88

```python
return MealParseResponse(**result, model_latency_ms=latency_ms)
```

If the model returns JSON that's missing `items` or `total_kcal` (e.g., it returns `{"error": "..."}` or an unexpected structure), Pydantic raises `ValidationError` → unhandled 500 with internals exposed. This is distinct from the `json.JSONDecodeError` already guarded in `meal_parser.py`.

**Fix:**
```python
from pydantic import ValidationError
try:
    return MealParseResponse(**result, model_latency_ms=latency_ms)
except ValidationError as e:
    raise HTTPException(status_code=502, detail=f"Model returned malformed data: {e}")
```

---

### 6. `MEAL_EXTRACTION_PROMPT.format()` crashes on user input containing `{` or `}`
**File:** `calai_backend/tools/meal_parser.py` · **Line:** 40

```python
prompt = MEAL_EXTRACTION_PROMPT.format(meal_text=meal_text, meal_type=meal_type)
```

If a user sends `"I had {protein shake}"` as `meal_text`, Python's `.format()` tries to interpret `{protein shake}` as a format key → `KeyError` → unhandled 500.

**Fix:** Escape user input before substituting:
```python
safe_text = meal_text.replace("{", "{{").replace("}", "}}")
prompt = MEAL_EXTRACTION_PROMPT.format(meal_text=safe_text, meal_type=meal_type)
```
Or switch to `str.replace()` for the substitution entirely.

---

### 7. Tool returning `None` silently feeds `"None"` to the LLM (LSP)
**File:** `calai_backend/api/routes.py` · **Line:** 208

```python
messages.append(ToolMessage(content=str(observation), tool_call_id=tool_call["id"]))
```

If a future tool (e.g., `log_water_intake` that writes to DB) returns `None`, `str(None)` = `"None"` is silently fed back as a `ToolMessage`. The LLM may interpret this as a failed call and retry indefinitely until `MAX_STEPS`.

**Fix:** Enforce an explicit return contract — either `-> str` for all tools, or check for `None`:
```python
content = str(observation) if observation is not None else "Tool completed successfully."
messages.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
```

---

## SOLID Violations

### S — Single Responsibility Principle
**File:** `calai_backend/api/routes.py` · **Lines:** 1–212

`routes.py` currently owns **five** responsibilities:

| Responsibility | Should live in |
|---|---|
| HTTP request/response routing | `api/routes.py` (keep) |
| LangChain `@tool` wrappers | `tools/registry.py` |
| Tool registry (`_TOOLS`, `_TOOLS_DICT`) | `tools/registry.py` |
| ReAct loop logic | `services/agent_service.py` |
| System prompt | `prompts/calai_prompt.py` |

When you add a 6th tool or switch from Ollama to OpenAI, you edit this single file in multiple unrelated places — merge conflicts, cognitive overload, untestable units.

---

### O — Open/Closed Principle
**File:** `calai_backend/api/routes.py` · **Lines:** 108–136

To add `track_water_intake` as a 5th tool, a developer must edit `routes.py` in **3 places**:
1. Add a `@tool` wrapper function
2. Append it to `_TOOLS` list
3. Edit `SYSTEM_PROMPT` to mention it

**Recommended — Tool Registry pattern:**
```python
# calai_backend/tools/registry.py
_REGISTRY: dict[str, BaseTool] = {}

def register(fn):
    t = tool(fn)
    _REGISTRY[t.name] = t
    return t

def get_tools() -> list: return list(_REGISTRY.values())
def get_dict() -> dict: return dict(_REGISTRY)

# tools/bmr_tool.py
from calai_backend.tools.registry import register
@register
def calculate_bmr_tool(weight_kg: float, ...): ...

# routes.py just does:
from calai_backend.tools.registry import get_tools, get_dict
_TOOLS = get_tools()
```
Adding a tool = creating one new file. `routes.py` never changes.

The `SYSTEM_PROMPT` can be auto-generated from tool docstrings:
```python
SYSTEM_PROMPT = BASE_PROMPT + "\n".join(f"- {t.name}: {t.description}" for t in _TOOLS)
```

---

### L — Liskov Substitution Principle

Implicit contract: every tool must return a value that is meaningful when passed through `str()` as a `ToolMessage`. If a new tool breaks this contract (returns `None`, a complex object, or raises silently), the LLM receives garbage and may loop or hallucinate. Make the return contract explicit with a `ToolResult` type or enforce `-> str` on all tool functions.

---

### I — Interface Segregation Principle
**File:** `calai_backend/schemas.py` · **Lines:** 5–13

```python
class CalcRequest(BaseModel):
    weight_kg: float; height_cm: float; age: int; gender: Literal[...]
    activity_level: Literal[...]          # needed for TDEE, not BMR
    goal: Literal["lose", "maintain", "gain"]  # needed for goal, not BMR/TDEE
    goal_rate_kg_per_week: float = 0.5
```

A caller who only wants BMR must still provide `activity_level` and `goal`. As the API grows, this fat request object becomes a maintenance problem.

**Recommended:**
```python
class UserStatsSchema(BaseModel):
    weight_kg: float; height_cm: float; age: int; gender: Literal["male", "female"]

class ActivitySchema(BaseModel):
    activity_level: Literal["sedentary", "lightly_active", "moderately_active", "very_active", "extra_active"]

class GoalSchema(BaseModel):
    goal: Literal["lose", "maintain", "gain"]
    goal_rate_kg_per_week: float = Field(default=0.5, gt=0)

class CalcRequest(UserStatsSchema, ActivitySchema, GoalSchema): pass  # unchanged for now
```

---

### D — Dependency Inversion Principle
**Files:** `calai_backend/tools/meal_parser.py:41`, `calai_backend/api/routes.py:148`

```python
# Two independent violations:
llm = ChatOllama(model=MODEL_NAME, base_url=OLLAMA_BASE_URL, temperature=0)  # routes.py
llm = ChatOllama(model=MODEL_NAME, base_url=OLLAMA_BASE_URL, temperature=0, format="json")  # meal_parser.py
```

High-level modules depend directly on `ChatOllama` (concrete). Consequences:
- Swapping to OpenAI/Claude requires editing two files
- A new `ChatOllama` connection is opened per request — no reuse
- Impossible to inject a mock in tests

**Recommended — FastAPI Depends + Protocol:**
```python
# calai_backend/providers/llm.py
from langchain_core.language_models import BaseChatModel

def get_llm() -> BaseChatModel:
    return ChatOllama(model=MODEL_NAME, base_url=OLLAMA_BASE_URL, temperature=0)

# routes.py
from fastapi import Depends
@router.post("/agent")
def agent(req: AgentRequest, llm: BaseChatModel = Depends(get_llm)):
    llm_with_tools = llm.bind_tools(_TOOLS)
    ...
```
Swap to OpenAI: change `get_llm()` only. In tests: override the dependency with a mock.

---

## Design Pattern Summary

| Pattern | Status | Location |
|---|---|---|
| Decorator (`@tool`) | ✅ Used | `routes.py` |
| Strategy (activity multipliers dict) | ✅ Lightweight | `tdee.py` |
| Router (FastAPI APIRouter) | ✅ Used | `routes.py` |
| Facade (`/calculate` hides 3-step pipeline) | ✅ Partial | `routes.py:34` |
| **Service Layer** | ❌ Missing | Split `routes.py` → `services/` |
| **Factory / Singleton (LLM client)** | ❌ Missing | `providers/llm.py` |
| **Registry (tool auto-discovery)** | ❌ Missing | `tools/registry.py` |
| **Dependency Injection** | ❌ Missing | FastAPI `Depends()` |
| **Abstract Provider** | ❌ Missing | `BaseChatModel` interface |
| **Strategy (goal calculation)** | ❌ Missing | `lose/maintain/gain` if/elif → Strategy classes |

---

## Recommended Folder Structure for Scale

```
calai_backend/
├── api/
│   └── routes.py               # HTTP only — thin layer, error mapping
├── services/
│   ├── calc_service.py         # BMR→TDEE→Goal pipeline
│   └── agent_service.py        # ReAct loop
├── tools/
│   ├── registry.py             # @register decorator + get_tools()
│   ├── bmr_tool.py
│   ├── tdee_tool.py
│   ├── calorie_goal_tool.py
│   └── meal_parser_tool.py
├── providers/
│   └── llm.py                  # get_llm() Depends factory
├── prompts/
│   └── calai_prompt.py         # SYSTEM_PROMPT (auto-generated from registry)
├── schemas.py
└── config.py
```

---

## Priority Fix Order

| Priority | Finding | File:Line | Impact |
|---|---|---|---|
| 🔴 P1 | `format()` crash on `{`/`}` in meal text | `meal_parser.py:40` | User-triggerable unhandled 500 |
| 🔴 P1 | Nested httpx errors uncaught in agent tool invocation | `routes.py:201` | Unhandled 500, traceback exposed |
| 🔴 P1 | `httpx.TimeoutException` uncaught in both endpoints | `routes.py:68,163` | Unhandled 500 on slow models |
| 🟠 P2 | `ai_message.content` can be `None` | `routes.py:189` | Pydantic ValidationError → 500 |
| 🟠 P2 | `MealParseResponse(**result)` not guarded | `routes.py:88` | 500 on unexpected model output |
| 🟠 P2 | `/calculate` has no ValueError catch | `routes.py:34` | Inconsistent error surface |
| 🟡 P3 | `ChatOllama` created per-request (DIP + efficiency) | `routes.py:148`, `meal_parser.py:41` | Performance + untestable |
| 🟡 P3 | `routes.py` SRP / OCP violations | `routes.py:1–212` | Scaling friction, merge conflicts |
| 🟡 P3 | Tool `None` return feeds `"None"` to LLM (LSP) | `routes.py:208` | Silent agent loop confusion |

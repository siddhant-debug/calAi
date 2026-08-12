from dotenv import load_dotenv
import os
import json
import time
import httpx
from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langsmith import traceable

# ---------------------------------------------------------------------------
# CONFIG
# ---------------------------------------------------------------------------
MAX_ITERATIONS = 8
MODEL = "qwen2.5:7b"

load_dotenv()
base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


# ---------------------------------------------------------------------------
# TOOL 1 — calculate_bmr
# ---------------------------------------------------------------------------

@tool
@traceable(name="calculate_bmr")
def calculate_bmr(weight_kg: float, height_cm: float, age: int, gender: str) -> float:
    """Calculate Basal Metabolic Rate using the Mifflin-St Jeor equation.
    gender must be 'male' or 'female'."""
    # TODO 1: validate gender — raise ValueError if not 'male' or 'female'
    if gender != 'male' and gender != 'female':
        raise ValueError("Invalid gender. Must be 'male' or 'female'.")

    # TODO 2: implement the formula
    if gender =='male':
        bmr = 10*weight_kg + 6.25*height_cm - 5*age + 5
    else:  
        bmr = 10*weight_kg + 6.25*height_cm - 5*age - 161  

    # Male:   BMR = 10*weight_kg + 6.25*height_cm - 5*age + 5
    # Female: BMR = 10*weight_kg + 6.25*height_cm - 5*age - 161

    # TODO 3: return round(bmr, 1)
    return round(bmr, 1)


# ---------------------------------------------------------------------------
# TOOL 2 — calculate_tdee
# ---------------------------------------------------------------------------

ACTIVITY_MULTIPLIERS = {
    "sedentary": 1.2,
    "lightly_active": 1.375,
    "moderately_active": 1.55,
    "very_active": 1.725,
    "extra_active": 1.9,
}

@tool
@traceable(name="calculate_tdee")
def calculate_tdee(bmr_kcal: float, activity_level: str) -> float:
    """Calculate Total Daily Energy Expenditure.
    activity_level must be one of: sedentary, lightly_active,
    moderately_active, very_active, extra_active."""
    if activity_level not in ACTIVITY_MULTIPLIERS:
        raise ValueError(f"Invalid activity_level. Must be one of: {list(ACTIVITY_MULTIPLIERS.keys())}")
    tdee = bmr_kcal * ACTIVITY_MULTIPLIERS[activity_level]
    return round(tdee, 1)


# ---------------------------------------------------------------------------
# TOOL 3 — calculate_calorie_goal
# ---------------------------------------------------------------------------

@tool
@traceable(name="calculate_calorie_goal")
def calculate_calorie_goal(tdee_kcal: float, goal: str, goal_rate_kg_per_week: float = 0.5) -> float:
    """Calculate daily calorie goal based on TDEE and goal type.
    goal must be 'lose', 'maintain', or 'gain'.
    goal_rate_kg_per_week defaults to 0.5 (ignored when goal is 'maintain')."""
    if goal not in ('lose', 'maintain', 'gain'):
        raise ValueError("goal must be 'lose', 'maintain', or 'gain'.")
    daily_delta = (goal_rate_kg_per_week * 7700) / 7
    if goal == 'lose':
        result = tdee_kcal - daily_delta
    elif goal == 'gain':
        result = tdee_kcal + daily_delta
    else:
        result = tdee_kcal
    return round(result, 1)


# ---------------------------------------------------------------------------
# TOOL 4 — parse_meal_text
# ---------------------------------------------------------------------------

MEAL_EXTRACTION_PROMPT = """You are a nutrition data extractor. The user will describe a meal in natural language.
Extract each food item and estimate its nutritional content based on typical serving sizes and standard nutrition data.

Return ONLY a valid JSON object with this exact structure — no explanation, no markdown:
{{
  "items": [
    {{
      "name": "food name",
      "quantity": <number>,
      "unit": "piece/g/ml/cup/etc",
      "calories_kcal": <number>,
      "protein_g": <number>,
      "carbs_g": <number>,
      "fat_g": <number>
    }}
  ],
  "total_kcal": <sum of all calories_kcal>,
  "meal_type": "{meal_type}"
}}

Meal description: {meal_text}"""


@tool
@traceable(name="parse_meal_text")
def parse_meal_text(meal_text: str, meal_type: str = "snack") -> dict:
    """Parse a natural-language meal description into structured nutrition data.
    meal_type: breakfast, lunch, dinner, or snack."""
    valid_meal_types = ("breakfast", "lunch", "dinner", "snack")
    if meal_type not in valid_meal_types:
        raise ValueError(f"meal_type must be one of: {valid_meal_types}")

    parser_llm = ChatOllama(model=MODEL, base_url=base_url, temperature=0, format="json")
    prompt = MEAL_EXTRACTION_PROMPT.format(meal_text=meal_text, meal_type=meal_type)
    t0 = time.perf_counter()
    response = parser_llm.invoke([HumanMessage(content=prompt)])
    print(f"[parse_meal_text] Model responded in {(time.perf_counter() - t0) * 1000:.1f}ms")

    try:
        result = json.loads(response.content)
    except json.JSONDecodeError as e:
        raise ValueError(f"Model returned invalid JSON: {e}\nRaw: {response.content[:300]}")

    return result


# ---------------------------------------------------------------------------
# AGENT LOOP
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are CalAI. You have four tools: calculate_bmr, calculate_tdee, calculate_calorie_goal, and parse_meal_text.

For calorie/goal calculations, follow this sequence:
1. Call calculate_bmr with weight_kg, height_cm, age, gender.
2. Call calculate_tdee with the BMR result and activity_level.
3. If the user mentions a goal (lose/maintain/gain), call calculate_calorie_goal with the TDEE result and goal.

For meal/food logging, use parse_meal_text with the meal description and meal_type (breakfast/lunch/dinner/snack).

If any required value is missing, ask for it first.
"""


@traceable(name="calai-agent")
def run_agent(user_input: str) -> str | None:
    tools = [calculate_bmr, calculate_tdee, calculate_calorie_goal, parse_meal_text]
    tools_dict = {t.name: t for t in tools}
    llm = ChatOllama(model=MODEL, base_url=base_url, temperature=0)
    llm_with_tools = llm.bind_tools(tools)

    messages = [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=user_input),
    ]

    print(f"Input: {user_input}")
    print("=" * 60)
    t_start = time.perf_counter()

    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"\n--- Iteration {iteration} ---")

        t0 = time.perf_counter()
        try:
            ai_message = llm_with_tools.invoke(messages)
        except httpx.ConnectError:
            print(f"\n[ERROR] Cannot connect to Ollama at {base_url}")
            print("        Fix: run `ollama serve` in a separate terminal.")
            return None
        except httpx.ReadError:
            print(f"\n[ERROR] Ollama dropped the connection while loading model '{MODEL}'.")
            print(f"        Fix: run `ollama pull {MODEL}` to download it, then retry.")
            return None
        except httpx.HTTPStatusError as e:
            print(f"\n[ERROR] Ollama returned HTTP {e.response.status_code}: {e.response.text[:200]}")
            return None
        #llm_with_tools.invoke(messages) sends the current conversation history (messages) to the LLM, which generates a response. The response may include tool calls if the LLM decides to use any of the tools based on the input and the conversation context.
        llm_ms = (time.perf_counter() - t0) * 1000
        print(f"[LLM call]    {llm_ms:.1f}ms")

        tool_calls = ai_message.tool_calls

        if not tool_calls:
            total_ms = (time.perf_counter() - t_start) * 1000
            print(f"\nFinal Answer: {ai_message.content}")
            print(f"[Total time]  {total_ms:.1f}ms  ({iteration} iteration(s))")
            return ai_message.content

        tool_call = tool_calls[0]
        tool_name = tool_call.get("name")
        tool_args = tool_call.get("args", {})
        tool_call_id = tool_call.get("id")

        print(f"[Tool Selected] {tool_name}")
        print(f"[Args]          {tool_args}")

        tool_fn = tools_dict.get(tool_name)
        #tool_fn is the actual tool function that will be called.
        if tool_fn is None:
            raise ValueError(f"Unknown tool: '{tool_name}'")

        t0 = time.perf_counter()
        try:
            observation = tool_fn.invoke(tool_args)
        except NotImplementedError:
            observation = "Tool not implemented yet."
        tool_ms = (time.perf_counter() - t0) * 1000

        print(f"[Tool Result]   {observation}  ({tool_ms:.1f}ms)")

        messages.append(ai_message)
        messages.append(ToolMessage(content=str(observation), tool_call_id=tool_call_id))

    print("ERROR: Max iterations reached")
    return None


if __name__ == "__main__":
    print("CalAI — your personal nutrition assistant")
    print("Type your message or 'quit' to exit.")
    print("=" * 60)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n[Bye!]")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit", "exit", "q"):
            print("[Bye!]")
            break

        print()
        run_agent(user_input)

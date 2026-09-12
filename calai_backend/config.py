import os
from dotenv import load_dotenv

# Explicit path, not the cwd-dependent load_dotenv() default: this repo has
# a stale root-level .env alongside this package's own .env, and uvicorn is
# run from the repo root (see README), so the bare default silently loads
# the wrong file and NVIDIA_API_KEY resolves empty.
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# ADR-006: chat LLM surface migrated from local Ollama to NVIDIA NIM
# (langchain-nvidia-ai-endpoints). OLLAMA_BASE_URL / MODEL_NAME are removed
# entirely — no rollback flag, see ADR-006 Decision section.
NVIDIA_API_KEY: str = os.getenv("NVIDIA_API_KEY", "")

# 2-model fallback chain, in order. ADR-006 originally specified a 4-model
# chain copied from GOT_RAG's proven pattern, but 3 of those 4 were found to
# be dead (410 Gone, retired by NVIDIA in Jul/Aug 2026) when verified via
# real parse_meal calls, not catalog metadata (the catalog's own `deprecated`
# flag was unreliable): meta/llama-3.1-8b-instruct,
# mistralai/mixtral-8x7b-instruct-v0.1, nvidia/llama-3.1-nemotron-nano-8b-v1.
# Only the primary worked. openai/gpt-oss-20b was found and confirmed
# end-to-end (valid JSON, ~21-24s latency, same ballpark as primary) as the
# sole replacement fallback. Model IDs must be verified live on
# build.nvidia.com before shipping — NIM's catalog changes and a stale
# model ID fails at call time, not at config-load time.
LLM_MODELS: list[str] = [
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "openai/gpt-oss-20b",
]

MAX_STEPS: int = int(os.getenv("MAX_STEPS", "8"))

# ADR-003 Action Item 6: rollout flag for the new Orchestrator path in
# services/agent_service.py::run_agent. Defaults to the new orchestrator;
# set USE_ORCHESTRATOR=false to roll back to the old ReAct loop
# (_run_agent_react_loop) without a code change.
USE_ORCHESTRATOR: bool = os.getenv("USE_ORCHESTRATOR", "true").lower() == "true"

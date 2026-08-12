import os
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MODEL_NAME: str = os.getenv("MODEL_NAME", "qwen2.5:7b")
MAX_STEPS: int = int(os.getenv("MAX_STEPS", "8"))

# ADR-003 Action Item 6: rollout flag for the new Orchestrator path in
# services/agent_service.py::run_agent. Defaults to the new orchestrator;
# set USE_ORCHESTRATOR=false to roll back to the old ReAct loop
# (_run_agent_react_loop) without a code change.
USE_ORCHESTRATOR: bool = os.getenv("USE_ORCHESTRATOR", "true").lower() == "true"

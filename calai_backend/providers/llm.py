from langchain_core.language_models import BaseChatModel
from langchain_ollama import ChatOllama

from calai_backend.config import MODEL_NAME, OLLAMA_BASE_URL


def get_llm() -> BaseChatModel:
    return ChatOllama(model=MODEL_NAME, base_url=OLLAMA_BASE_URL, temperature=0)


def get_json_llm() -> BaseChatModel:
    return ChatOllama(model=MODEL_NAME, base_url=OLLAMA_BASE_URL, temperature=0, format="json")

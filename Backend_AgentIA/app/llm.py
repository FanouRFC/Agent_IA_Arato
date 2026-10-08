"""Client LLM (API compatible OpenAI). Le fournisseur est un simple paramètre de configuration."""
import httpx

from .config import settings
from .db import SessionLocal
from . import settings_store


def current_model() -> str:
    with SessionLocal() as db:
        return settings_store.params(db)["llm_model"]


def chat(messages: list[dict], tools: list[dict] | None = None, temperature: float = 0.2) -> dict:
    payload = {"model": current_model(), "messages": messages, "temperature": temperature}
    if tools:
        payload["tools"] = tools
    r = httpx.post(f"{settings.llm_base_url}/chat/completions", json=payload, timeout=300,
                   headers={"Authorization": f"Bearer {settings.llm_api_key}"})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]

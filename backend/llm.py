"""Portkey-backed model + token usage logging. Every model call goes through run_logged()."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider

ROOT = Path(__file__).resolve().parent.parent
USAGE_LOG = ROOT / "logs" / "usage_log.json"

load_dotenv(ROOT / ".env")         # project .env first
load_dotenv(ROOT.parent / ".env")  # then one level up (teaching staff); won't override

MODEL_NAME = "gpt-6-luna"  # the only model this project uses
PORTKEY_BASE_URL = "https://api.portkey.ai/v1"


def _provider() -> OpenAIProvider:
    key = os.getenv("PORTKEY_API_KEY", "").strip()
    if not key:
        raise RuntimeError("PORTKEY_API_KEY is not set (put it in .env here or one folder up).")
    client = AsyncOpenAI(api_key=key, base_url=PORTKEY_BASE_URL, default_headers={"x-portkey-api-key": key})
    return OpenAIProvider(openai_client=client)


def model() -> OpenAIChatModel:
    return OpenAIChatModel(MODEL_NAME, provider=_provider())


def responses_model() -> OpenAIResponsesModel:
    """Responses API: needed for OpenAI's built-in web search (billed through the same Portkey key)."""
    return OpenAIResponsesModel(MODEL_NAME, provider=_provider())


def log_usage(label: str, usage) -> dict:
    """Append one entry with real token counts from the API response to logs/usage_log.json."""
    entry = {
        "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "label": label,
        "model": MODEL_NAME,
        "requests": usage.requests,
        "input_tokens": usage.input_tokens,
        "cached_input_tokens": usage.cache_read_tokens,
        "output_tokens": usage.output_tokens,
        "web_searches": getattr(usage, "web_searches", 0),
    }
    USAGE_LOG.parent.mkdir(exist_ok=True)
    log = json.loads(USAGE_LOG.read_text()) if USAGE_LOG.exists() else []
    log.append(entry)
    USAGE_LOG.write_text(json.dumps(log, indent=2))
    return entry


# Hard caps per run so a confused agent can't loop or overspend (a run that hits a cap raises and is reported).
SPECIALIST_LIMITS = UsageLimits(request_limit=5, total_tokens_limit=120_000)
BOSS_LIMITS = UsageLimits(request_limit=25, total_tokens_limit=250_000)


async def run_logged(agent: Agent, prompt: str, label: str, **kwargs):
    kwargs.setdefault("usage_limits", SPECIALIST_LIMITS)
    result = await agent.run(prompt, **kwargs)
    log_usage(label, result.usage)
    return result

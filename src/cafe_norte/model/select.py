"""``provider/model-id`` strings to adapters. The only place provider endpoints are named."""

from collections.abc import Mapping

from cafe_norte.model.chat_completions import ChatCompletionsModel
from cafe_norte.model.contracts import DecisionModel, Model
from cafe_norte.model.decisions import DecisionsModel
from cafe_norte.model.fake import FakeModel

PROVIDERS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
    # Same wire format; a local alternative when Groq's free-tier daily quota runs out.
    "openai": "https://api.openai.com/v1/chat/completions",
}


def model_from_env(selector: str, env: Mapping[str, str]) -> Model:
    """``fake`` or ``<provider>/<model-id>`` with ``<PROVIDER>_API_KEY`` from ``env``.

    ``fake`` has no script here; the composition root gives it the demo fallback sentence."""
    if selector == "fake":
        return FakeModel([])
    provider, _, model_id = selector.partition("/")
    if provider not in PROVIDERS or not model_id:
        raise ValueError(f"unknown model selector {selector!r}")
    api_key = env.get(f"{provider.upper()}_API_KEY", "")
    if not api_key:
        raise ValueError(f"{provider.upper()}_API_KEY is required for {selector}")
    return ChatCompletionsModel(model_id=model_id, base_url=PROVIDERS[provider], api_key=api_key)


def decision_model_from_env(selector: str, env: Mapping[str, str]) -> DecisionModel:
    """``openrouter/<model-id>`` (TypeSafe's Jev) with ``OPENROUTER_API_KEY`` from ``env``."""
    provider, _, model_id = selector.partition("/")
    if provider != "openrouter" or not model_id:
        raise ValueError(f"unknown decision model selector {selector!r}")
    api_key = env.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise ValueError(f"OPENROUTER_API_KEY is required for {selector}")
    return DecisionsModel(api_key=api_key, model_id=model_id)

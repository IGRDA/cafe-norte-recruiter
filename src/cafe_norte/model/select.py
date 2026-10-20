"""``provider/model-id`` strings to adapters. The only place provider endpoints are named."""

from collections.abc import Mapping

from cafe_norte.model.contracts import Model

PROVIDERS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1/chat/completions",
}


def model_from_env(selector: str, env: Mapping[str, str]) -> Model:
    """``fake`` or ``<provider>/<model-id>`` with ``<PROVIDER>_API_KEY`` from ``env``."""
    raise NotImplementedError

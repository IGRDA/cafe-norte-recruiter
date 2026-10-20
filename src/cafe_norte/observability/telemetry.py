"""Optional OpenTelemetry export. No endpoint means no export."""

from collections.abc import Mapping


def configure(env: Mapping[str, str]) -> None:
    """Install a tracer provider when Langfuse or OTLP variables are present."""
    raise NotImplementedError

"""Shared vocabulary: supported languages, stable failure codes and fixed public messages.

Every other module may import this one; it imports nothing from the application. A
``ServiceError`` carries an internal detail and a public code separately, so ``str(error)``
never reaches a candidate, a log line or a trace by accident."""

from typing import Literal

# The ten languages Ana answers in (D63). ``TABLED`` are the two with reviewed word-for-word
# texts and the only ones evaluated; the rest are wired and untested.
Language = Literal["es", "en", "fr", "pt", "it", "de", "ro", "ar", "zh", "uk"]
SWITCHABLE: tuple[Language, ...] = ("es", "en", "fr", "pt", "it", "de", "ro", "ar", "zh", "uk")
TABLED: frozenset[Language] = frozenset({"es", "en"})

ErrorCode = Literal[
    "busy",  # admission or budget limit reached; retry later
    "timeout",  # model or tool deadline expired
    "provider_unavailable",  # STT, TTS, LLM or media provider failed
    "provider_rejected",  # provider refused the request (auth, quota, policy)
    "invalid_response",  # malformed or incomplete model output after repair
    "validation_failed",  # candidate data or tool arguments rejected by domain rules
    "unauthorized",  # missing or wrong access, resume token or session ownership
    "not_found",  # session, slot or confirmation does not exist for this caller
    "conflict",  # revision mismatch, slot taken, superseded lease, duplicate input id
    "limit_exceeded",  # text length, turns per session or active seconds
    "rate_limited",  # too many access attempts or session starts from one client (D65)
    "session_ended",  # the session is completed, stopped, abandoned or failed
    "internal_error",
]

# Public messages exist for the tabled languages; any other language gets the English one.
MESSAGES: dict[Language, dict[ErrorCode, str]] = {
    "es": {
        "busy": "Ahora mismo no hay plazas libres. Inténtalo de nuevo en unos minutos.",
        "timeout": "La operación tardó demasiado. Inténtalo de nuevo.",
        "provider_unavailable": "Un servicio externo no responde. Puedes seguir por texto.",
        "provider_rejected": "Un servicio externo rechazó la solicitud.",
        "invalid_response": "Perdona, no te he entendido bien. ¿Me lo repites?",
        "validation_failed": "No he podido guardar ese dato. ¿Puedes repetirlo?",
        "unauthorized": "No tienes acceso a esta conversación.",
        "not_found": "No encuentro esa conversación.",
        "conflict": "Alguien ha modificado esta conversación. Recarga la página.",
        "limit_exceeded": "Se ha alcanzado el límite de esta conversación.",
        "rate_limited": "Demasiados intentos seguidos. Espera unos minutos y vuelve a probar.",
        "session_ended": "Esta conversación ha terminado.",
        "internal_error": "No se pudo completar la operación.",
    },
    "en": {
        "busy": "There are no free slots right now. Please try again in a few minutes.",
        "timeout": "The operation took too long. Please try again.",
        "provider_unavailable": "An external service is not responding. You can continue by text.",
        "provider_rejected": "An external service rejected the request.",
        "invalid_response": "Sorry, I didn't quite get that. Could you say it again?",
        "validation_failed": "I could not save that detail. Could you repeat it?",
        "unauthorized": "You do not have access to this conversation.",
        "not_found": "I cannot find that conversation.",
        "conflict": "This conversation changed elsewhere. Please reload the page.",
        "limit_exceeded": "This conversation has reached its limit.",
        "rate_limited": "Too many attempts in a row. Please wait a few minutes and try again.",
        "session_ended": "This conversation has ended.",
        "internal_error": "The operation could not be completed.",
    },
}


class ServiceError(Exception):
    """Internal failure with a stable public code. Only ``public_message`` is shown to anyone."""

    def __init__(self, detail: str = "", *, code: ErrorCode = "internal_error") -> None:
        super().__init__(detail)
        self.code = code

    def public_message(self, language: Language) -> str:
        return MESSAGES[language if language in TABLED else "en"][self.code]

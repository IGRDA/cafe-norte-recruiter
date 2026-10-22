"""The composition root binds telemetry, prices and the shutdown flush; no network."""

import pytest
from fastapi.testclient import TestClient

from cafe_norte.main import _process_versions, create_default_app
from cafe_norte.observability.contracts import ProcessVersions, Telemetry
from cafe_norte.observability.fakes import RecordingTelemetry
from cafe_norte.persistence.export import ExportDocument
from cafe_norte.voice.contracts import STT_MODEL, TTS_MODEL
from cafe_norte.voice.pipeline import stt_settings, tts_settings
from tests.support import CONFIG_DIR, ROOT
from tests.support.http import OPENING_EVENTS, create_session, read_turn


def test_hosted_voice_names_its_models_and_voice_in_the_stamp() -> None:
    process = _process_versions({"ELEVENLABS_VOICE_ID": "voice-1"}, "gpt-4o-mini", "pipecat")
    assert (process.stt_model, process.tts_model, process.voice_id) == (
        STT_MODEL,
        TTS_MODEL,
        "voice-1",
    )


def test_without_hosted_voice_the_stamp_names_no_voice_provider() -> None:
    process = _process_versions({"ELEVENLABS_VOICE_ID": "voice-1"}, "fake", "off")
    assert (process.stt_model, process.tts_model, process.voice_id) == ("", "", "")
    assert process.model_id == "fake" and process.commit_sha == "local"


def test_the_pipeline_runs_the_models_the_stamp_names() -> None:
    assert stt_settings("es").model == STT_MODEL
    assert tts_settings("voice-1").model == TTS_MODEL
    assert tts_settings("voice-1").voice == "voice-1"


def test_the_default_app_traces_turns_prices_the_export_and_flushes_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recording = RecordingTelemetry()
    flushed: list[str] = []
    seen: list[ProcessVersions] = []

    def configure(env: object, process: ProcessVersions) -> tuple[Telemetry, object]:
        seen.append(process)
        return recording, lambda: flushed.append("flushed")

    monkeypatch.setattr("cafe_norte.main.configure", configure)
    env = {"CAFE_NORTE_CONFIG_DIR": str(CONFIG_DIR), "CAFE_NORTE_WEB_DIR": str(ROOT / "web")}
    with TestClient(create_default_app(env)) as client:
        session_id = create_session(client)
        client.post(f"/api/sessions/{session_id}/turns", json={"input_id": "in-1", "text": "Hola"})
        read_turn(client, session_id, after=OPENING_EVENTS)
        document = ExportDocument.model_validate_json(
            client.get(f"/api/sessions/{session_id}/export").text
        )
        assert flushed == []  # not before the app stops
    assert flushed == ["flushed"]
    assert seen and seen[0].model_id == "fake"
    assert recording.span("handle-candidate-turn").ended
    assert document.metrics.estimated_marginal_cost_eur == 0.0  # priced: the fake model is free

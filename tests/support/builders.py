"""Values most tests start from: the real configuration, one instant, one full record."""

from datetime import UTC, date, datetime

from cafe_norte.domain.candidate import apply_patch
from cafe_norte.domain.configuration import load_configurations
from cafe_norte.domain.contracts import (
    CandidatePatch,
    CandidateRecord,
    ConfigId,
    Evidence,
    SessionId,
    SessionState,
    TurnId,
)
from cafe_norte.observability.contracts import VersionStamp
from cafe_norte.persistence.export import SCHEMA_VERSION
from tests.support import CONFIG_DIR

NOW = datetime(2026, 10, 20, 10, tzinfo=UTC)
SID = SessionId("s")
SESSION = SessionId("s1")
CONFIG_ID = ConfigId("chamberi_barista_v1")
CONFIGS = load_configurations(CONFIG_DIR)
CONFIG = CONFIGS[CONFIG_ID]
EVIDENCE = Evidence(source_turn_id=TurnId("t0"), text="…")
STAMP = VersionStamp(
    config_id=CONFIG_ID,
    config_version="1",
    kb_version="1",
    prompt_version="ana_v4",
    schema_version=SCHEMA_VERSION,
    model_id="fake",
    commit_sha="local",
)
FULL = CandidatePatch(
    name="Lucía Marín",
    interest="yes",
    work_authorization="yes",
    availability_days=frozenset({"mon", "tue", "thu"}),
    availability_shifts=frozenset({"morning"}),
    hours_per_week=30,
    earliest_start_date=date(2026, 10, 26),
    experience="dos años en una cafetería",
)


def record(**fields: object) -> CandidateRecord:
    """A record with ``fields`` captured from one piece of evidence."""
    return apply_patch(CandidateRecord(), CandidatePatch(**fields), EVIDENCE)


def full_record() -> CandidateRecord:
    """Every requested field of the barista configuration captured: S01's Lucía."""
    return apply_patch(CandidateRecord(), FULL, EVIDENCE)


def session_state(
    session_id: SessionId = SESSION,
    *,
    revision: int = 0,
    config_id: ConfigId = CONFIG_ID,
    created_at: datetime = NOW,
) -> SessionState:
    """A fresh Spanish text session with an empty record at ``revision``."""
    return SessionState(
        session_id=session_id,
        config_id=config_id,
        config_version="1",
        language="es",
        channel="text",
        created_at=created_at,
        candidate=CandidateRecord(revision=revision),
    )

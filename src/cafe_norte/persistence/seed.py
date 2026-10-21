"""Seeding the simulated calendar: the domain generates, the store inserts what is missing."""

from collections.abc import Mapping
from datetime import datetime

from cafe_norte.domain.calendar import interview_slots
from cafe_norte.domain.contracts import ConfigId, StoreConfiguration
from cafe_norte.persistence.contracts import Store


async def seed_calendar(
    store: Store, configurations: Mapping[ConfigId, StoreConfiguration], *, now: datetime
) -> None:
    """Idempotent: slot ids are deterministic and ``seed`` never touches an existing slot."""
    for configuration in configurations.values():
        await store.calendar.seed(interview_slots(configuration, after=now))

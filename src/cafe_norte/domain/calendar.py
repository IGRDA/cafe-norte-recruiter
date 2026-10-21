"""The simulated calendar rule: which interview slots a store offers over the next days.

Pure and deterministic: the same configuration and the same instant give the same slots with
the same ids, so seeding twice changes nothing and a scenario with a fixed clock always sees
the same calendar."""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from cafe_norte.domain.contracts import InterviewSlot, SlotId, StoreConfiguration, Weekday

SLOT_MINUTES = 30
HORIZON_DAYS = 7
WEEKDAYS: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def interview_slots(
    configuration: StoreConfiguration, *, after: datetime, days: int = HORIZON_DAYS
) -> tuple[InterviewSlot, ...]:
    """One slot per ``interview_times`` on each of the next ``days`` local dates that has a
    shift, strictly after ``after``. Id ``<config_id>-<YYYY-MM-DD>-<HHMM>``; times are local
    to the store and stored in UTC."""
    zone = ZoneInfo(configuration.timezone)
    open_days = {day for shift in configuration.shifts for day in shift.days}
    first = after.astimezone(zone).date()
    slots: list[InterviewSlot] = []
    for offset in range(days + 1):
        day = first + timedelta(days=offset)
        if WEEKDAYS[day.weekday()] not in open_days:
            continue
        for clock in configuration.interview_times:
            starts = datetime.combine(day, time.fromisoformat(clock), tzinfo=zone)
            if starts <= after:
                continue
            slots.append(
                InterviewSlot(
                    slot_id=SlotId(
                        f"{configuration.config_id}-{day.isoformat()}-{clock.replace(':', '')}"
                    ),
                    config_id=configuration.config_id,
                    starts_at_utc=starts.astimezone(UTC),
                    duration_minutes=SLOT_MINUTES,
                )
            )
    return tuple(slots)

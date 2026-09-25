"""Simulated clock.  Call set_now() to fix the time for tests and loadgen."""
from datetime import datetime, timezone

_override: datetime | None = None


def now() -> datetime:
    """Return the current time. Uses override when set, real UTC otherwise."""
    if _override is not None:
        return _override
    return datetime.now(timezone.utc)


def set_now(dt: datetime | None) -> None:
    """Fix the clock to dt, or clear the override when dt is None."""
    global _override
    _override = dt

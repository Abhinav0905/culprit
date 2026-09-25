"""Feature flags backed by environment variables, with an override dict for tests."""
import os

_overrides: dict[str, bool] = {}


def is_enabled(name: str) -> bool:
    """Return True when the flag is active (override dict first, then env var)."""
    if name in _overrides:
        return _overrides[name]
    val = os.environ.get(name, "").lower()
    return val in ("1", "true", "yes", "on")


def set_flag(name: str, value: bool) -> None:
    """Override a flag for the current process (used by loadgen and tests)."""
    _overrides[name] = value


def clear_flags() -> None:
    """Clear all overrides."""
    _overrides.clear()

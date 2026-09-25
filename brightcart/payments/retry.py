"""Deterministic fake payment provider with retry and jitter."""
import random
import time

# payments v1.8.1: JITTER_MS = 50
# payments v1.8.2: JITTER_MS = 120  (changed by C2)
JITTER_MS: int = 50

_rng = random.Random(42)


def call_provider(amount_cents: int, currency: str, card_token: str) -> dict:
    """Call the fake payment provider.  Always succeeds for valid inputs."""
    jitter_s = _rng.randint(0, JITTER_MS) / 1000.0
    time.sleep(jitter_s)
    charge_id = f"ch-{_rng.randint(100000, 999999)}"
    return {"charge_id": charge_id, "status": "captured"}

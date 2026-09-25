"""Simulated database connection pool."""
import threading
import time

from brightcart.common.logging import Logger

_log = Logger("orders", "brightcart.orders.db")

POOL_SIZE = 20
_lock = threading.Lock()
_in_use: int = 0


class PoolTimeoutError(Exception):
    pass


class Connection:
    """A dummy connection object. Release it by calling .close()."""

    def close(self) -> None:
        release()


def acquire(timeout_s: float = 2.0) -> Connection:
    """Acquire a connection from the pool, blocking up to timeout_s."""
    global _in_use
    deadline = time.monotonic() + timeout_s
    while True:
        with _lock:
            if _in_use < POOL_SIZE:
                _in_use += 1
                pct = _in_use / POOL_SIZE * 100
                if pct > 90:
                    _log.warn(
                        "db_pool_high",
                        f"DB pool usage high: {pct:.0f}%",
                        pool_size=POOL_SIZE,
                        in_use=_in_use,
                        usage_pct=round(pct, 1),
                    )
                return Connection()
        if time.monotonic() >= deadline:
            raise PoolTimeoutError(
                f"pool timeout after {timeout_s}s: size={POOL_SIZE} in_use={_in_use}"
            )
        time.sleep(0.01)


def release() -> None:
    """Return a connection to the pool."""
    global _in_use
    with _lock:
        _in_use = max(0, _in_use - 1)


def reset() -> None:
    """Reset pool state (used by loadgen between scenarios)."""
    global _in_use
    with _lock:
        _in_use = 0


def set_in_use(n: int) -> None:
    """Force pool usage to n (used by loadgen to simulate load)."""
    global _in_use
    with _lock:
        _in_use = n

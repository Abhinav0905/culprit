"""JSON-lines structured logger for Brightcart services."""
import json
import sys
from datetime import datetime, timezone
from typing import Any

from brightcart.common import clock


def _emit(record: dict[str, Any]) -> None:
    print(json.dumps(record, default=str), file=sys.stdout, flush=True)


class Logger:
    def __init__(self, service: str, logger: str) -> None:
        self.service = service
        self.logger = logger

    def _base(self, level: str, event: str, msg: str) -> dict[str, Any]:
        return {
            "ts": clock.now().strftime("%Y-%m-%dT%H:%M:%S.") + f"{clock.now().microsecond // 1000:03d}Z",
            "service": self.service,
            "level": level,
            "logger": self.logger,
            "event": event,
            "msg": msg,
        }

    def info(self, event: str, msg: str, **kwargs: Any) -> None:
        rec = self._base("INFO", event, msg)
        rec.update(kwargs)
        _emit(rec)

    def warn(self, event: str, msg: str, **kwargs: Any) -> None:
        rec = self._base("WARN", event, msg)
        rec.update(kwargs)
        _emit(rec)

    def error(self, event: str, msg: str, **kwargs: Any) -> None:
        rec = self._base("ERROR", event, msg)
        rec.update(kwargs)
        _emit(rec)

    def error_exc(
        self,
        event: str,
        msg: str,
        exc: BaseException,
        frames: list[dict[str, Any]],
        **kwargs: Any,
    ) -> None:
        rec = self._base("ERROR", event, msg)
        rec["exc_type"] = type(exc).__name__
        rec["exc_message"] = str(exc)
        rec["frames"] = frames
        rec.update(kwargs)
        _emit(rec)

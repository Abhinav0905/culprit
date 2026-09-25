"""Read dataset files from datasets/incidents/<INC>/ and write .culprit/<INC>/events.json."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from culprit.models import Event, Frame


_DATASET_ROOT = Path("datasets/incidents")
_STATE_ROOT = Path(".culprit")


def _parse_ts(ts_str: str) -> datetime:
    """Parse ISO 8601 UTC timestamp, tolerating trailing Z."""
    ts_str = ts_str.replace("Z", "+00:00")
    return datetime.fromisoformat(ts_str)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


def ingest(incident_id: str) -> list[Event]:
    """Load the dataset for incident_id, assign event ids, and write events.json."""
    dataset_dir = _DATASET_ROOT / incident_id
    if not dataset_dir.exists():
        raise FileNotFoundError(f"Dataset not found: {dataset_dir}")

    raw_events: list[tuple[datetime, dict[str, Any]]] = []

    # Load log files
    logs_dir = dataset_dir / "logs"
    for log_file in sorted(logs_dir.glob("*.jsonl")):
        service = log_file.stem  # "gateway", "orders", "payments"
        for rec in _load_jsonl(log_file):
            ts = _parse_ts(rec["ts"])
            raw_events.append((ts, {"_source": "log", "_service": service, **rec}))

    # Load metrics
    metrics_path = dataset_dir / "metrics.jsonl"
    if metrics_path.exists():
        for rec in _load_jsonl(metrics_path):
            ts = _parse_ts(rec["ts"])
            raw_events.append((ts, {"_source": "metric", **rec}))

    # Load changes
    changes_path = dataset_dir / "changes.json"
    if changes_path.exists():
        for rec in json.loads(changes_path.read_text(encoding="utf-8")):
            ts = _parse_ts(rec["ts"])
            raw_events.append((ts, {"_source": "change", **rec}))

    # Sort by timestamp, then by kind (log < metric < change for stable ordering)
    _kind_order = {"log": 0, "metric": 1, "change": 2}
    raw_events.sort(key=lambda x: (x[0], _kind_order.get(x[1].get("_source", "log"), 3)))

    events: list[Event] = []
    for i, (ts, rec) in enumerate(raw_events, start=1):
        event_id = f"E{i:05d}"
        source = rec.get("_source", "log")

        if source == "log":
            service = rec.get("service") or rec.get("_service", "unknown")
            frames = [
                Frame(module=f["module"], function=f["function"], line=f.get("line"))
                for f in rec.get("frames", [])
            ]
            # Preserve 'logger' in attrs so reconstruct.py can use it for resource suspects
            attrs: dict[str, Any] = {
                k: v for k, v in rec.items()
                if k not in ("ts", "service", "level", "event", "msg",
                             "exc_type", "exc_message", "frames", "_source", "_service")
            }
            events.append(Event(
                id=event_id,
                ts=ts,
                service=service,
                kind="log",
                level=rec.get("level"),
                name=rec.get("event", ""),
                message=rec.get("msg", ""),
                exc_type=rec.get("exc_type"),
                exc_message=rec.get("exc_message"),
                frames=frames,
                attrs=attrs,
            ))

        elif source == "metric":
            service = rec.get("service", "unknown")
            events.append(Event(
                id=event_id,
                ts=ts,
                service=service,
                kind="metric",
                name=rec.get("name", ""),
                message=f"{rec.get('name','')}={rec.get('value','')}",
                attrs={"value": rec.get("value")},
            ))

        elif source == "change":
            service = rec.get("service", "unknown")
            attrs = {
                k: v for k, v in rec.items()
                if k not in ("ts", "id", "service", "_source")
            }
            events.append(Event(
                id=event_id,
                ts=ts,
                service=service,
                kind="change",
                name=rec.get("id", ""),
                message=rec.get("summary", ""),
                attrs=attrs,
            ))

    # Write to .culprit/<INC>/events.json
    state_dir = _STATE_ROOT / incident_id
    state_dir.mkdir(parents=True, exist_ok=True)
    out_path = state_dir / "events.json"
    out_path.write_text(
        json.dumps([e.model_dump(mode="json") for e in events], indent=2),
        encoding="utf-8",
    )
    return events


def load_events(incident_id: str) -> list[Event]:
    """Load already-ingested events.json from state directory."""
    path = _STATE_ROOT / incident_id / "events.json"
    if not path.exists():
        raise FileNotFoundError(f"events.json not found for {incident_id}. Run `culprit ingest` first.")
    data = json.loads(path.read_text(encoding="utf-8"))
    return [Event.model_validate(e) for e in data]


def load_changes(incident_id: str) -> list[dict[str, Any]]:
    """Load the raw changes.json for the incident dataset."""
    path = _DATASET_ROOT / incident_id / "changes.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_meta(incident_id: str) -> dict[str, Any]:
    """Load meta.json for the incident dataset."""
    path = _DATASET_ROOT / incident_id / "meta.json"
    return json.loads(path.read_text(encoding="utf-8"))

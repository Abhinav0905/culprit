"""Guard hook for Bob PreToolUse events.

Standard library ONLY — no imports from culprit.* so this works outside the venv.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

_STATE_ROOT = Path(".culprit")
_ACTIVE_FILE = _STATE_ROOT / "ACTIVE"
_PAYLOAD_LOG = _STATE_ROOT / "hook-payloads.log"
_MAX_PAYLOADS = 20

WRITE_TOOLS = {"write_file", "apply_diff", "search_and_replace", "insert_content"}


def _append_payload(raw: str) -> None:
    """Append raw payload to the log, keeping at most _MAX_PAYLOADS entries."""
    _STATE_ROOT.mkdir(parents=True, exist_ok=True)
    existing: list[str] = []
    if _PAYLOAD_LOG.exists():
        existing = _PAYLOAD_LOG.read_text(encoding="utf-8").splitlines()
    existing.append(raw.strip())
    _PAYLOAD_LOG.write_text("\n".join(existing[-_MAX_PAYLOADS:]) + "\n", encoding="utf-8")


def _extract_tool_name(payload: dict) -> str | None:
    """Try multiple field names to find the tool being called."""
    for key in ("tool_name", "toolName", "tool", "name"):
        if key in payload:
            return str(payload[key])
    return None


def _extract_path(payload: dict) -> str | None:
    """Try multiple field paths to find the file path being written."""
    # Direct nested paths
    candidates = [
        payload.get("tool_input", {}).get("path"),
        payload.get("tool_input", {}).get("file_path"),
        payload.get("input", {}).get("path"),
        payload.get("arguments", {}).get("path"),
        payload.get("args", {}).get("path"),
        payload.get("params", {}).get("path"),
    ]
    for c in candidates:
        if c and isinstance(c, str):
            return c

    # Walk all nested string values looking for a repo-relative path
    return _walk_for_path(payload)


def _walk_for_path(obj, depth: int = 0) -> str | None:
    """Recursively search for a string that looks like a repo-relative file path."""
    if depth > 5:
        return None
    if isinstance(obj, str):
        if (
            obj.endswith(".py") or obj.endswith(".json") or obj.endswith(".yaml")
            or obj.endswith(".md") or obj.endswith(".txt") or obj.endswith(".js")
        ) and not obj.startswith("/") and len(obj) < 200:
            return obj
    elif isinstance(obj, dict):
        for v in obj.values():
            result = _walk_for_path(v, depth + 1)
            if result:
                return result
    elif isinstance(obj, list):
        for item in obj:
            result = _walk_for_path(item, depth + 1)
            if result:
                return result
    return None


def _get_active_incident() -> str | None:
    if _ACTIVE_FILE.exists():
        return _ACTIVE_FILE.read_text(encoding="utf-8").strip()
    return None


def _load_ledger_suspects(incident_id: str) -> list[dict]:
    """Load suspects from ledger.json without importing culprit models."""
    ledger_path = _STATE_ROOT / incident_id / "ledger.json"
    if not ledger_path.exists():
        return []
    try:
        return json.loads(ledger_path.read_text(encoding="utf-8")).get("suspects", [])
    except Exception:
        return []


def _block(message: str) -> None:
    print(message, file=sys.stderr)
    print(message)  # also echo to stdout per spec
    sys.exit(2)


def main() -> None:
    raw = sys.stdin.read()
    _append_payload(raw)

    if not raw.strip():
        sys.exit(0)

    try:
        payload = json.loads(raw)
    except Exception:
        sys.exit(0)

    tool_name = _extract_tool_name(payload)
    file_path = _extract_path(payload)

    if not tool_name or tool_name not in WRITE_TOOLS:
        sys.exit(0)
    if not file_path:
        sys.exit(0)

    # Normalise path separators
    norm_path = file_path.replace("\\", "/")

    # Rule 1: block edits to any ledger.json under .culprit/
    if norm_path.endswith("ledger.json") and norm_path.startswith(".culprit/"):
        _block("Culprit guard: ledgers change only through the culprit CLI.")

    # Rule 2: block edits to brightcart/ (not brightcart/tests/) if no suspect reproduced
    incident_id = _get_active_incident()
    if incident_id:
        if (
            norm_path.startswith("brightcart/")
            and not norm_path.startswith("brightcart/tests/")
        ):
            suspects = _load_ledger_suspects(incident_id)
            reproduced_count = sum(
                1 for s in suspects if s.get("status") in ("reproduced", "fixed")
            )
            total = len(suspects)
            if reproduced_count == 0:
                _block(
                    f"Culprit guard: no changes to application code until a test reproduces "
                    f"{incident_id}'s error ({reproduced_count} of {total} suspects reproduced). "
                    f"Run /investigate {incident_id} first."
                )

    sys.exit(0)


if __name__ == "__main__":
    main()

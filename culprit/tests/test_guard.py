"""Unit tests for guard.py."""
import json
import subprocess
import sys
from pathlib import Path


def _run_guard(payload: dict) -> subprocess.CompletedProcess:
    """Run guard.py with payload on stdin, return CompletedProcess."""
    return subprocess.run(
        [sys.executable, "-m", "culprit.guard"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


def test_guard_allows_non_write_tool():
    """Non-write tools are always allowed."""
    result = _run_guard({"tool_name": "read_file", "tool_input": {"path": "brightcart/orders/address.py"}})
    assert result.returncode == 0


def test_guard_allows_test_file_edit():
    """Edits to brightcart/tests/ are always allowed."""
    result = _run_guard({"tool_name": "write_file", "tool_input": {"path": "brightcart/tests/test_new.py"}})
    assert result.returncode == 0


def test_guard_blocks_ledger_edit():
    """Edits to .culprit/*/ledger.json must be blocked."""
    result = _run_guard({
        "tool_name": "write_file",
        "tool_input": {"path": ".culprit/INC-001/ledger.json"},
    })
    assert result.returncode == 2
    assert "ledger" in result.stderr.lower() or "ledger" in result.stdout.lower()


def test_guard_blocks_app_code_before_reproduction(tmp_path):
    """Editing brightcart/ app code is blocked when no suspect is reproduced."""
    # Create a minimal state with no reproduced suspects
    state_dir = Path(".culprit/GUARD_TEST_INC")
    state_dir.mkdir(parents=True, exist_ok=True)
    active = Path(".culprit/ACTIVE")
    prev_active = active.read_text() if active.exists() else None
    active.write_text("GUARD_TEST_INC")

    ledger = {
        "incident_id": "GUARD_TEST_INC",
        "primary_signature_id": "SIG1",
        "suspects": [
            {"id": "S1", "status": "suspect", "kind": "change", "title": "t", "service": "payments",
             "prior": 0.65, "rationale": "r", "evidence_ids": [], "test_ids": []},
        ],
        "tests": [],
        "history": [],
    }
    (state_dir / "ledger.json").write_text(json.dumps(ledger))

    try:
        result = _run_guard({
            "tool_name": "apply_diff",
            "tool_input": {"path": "brightcart/orders/address.py"},
        })
        assert result.returncode == 2
        combined = result.stderr + result.stdout
        assert "no changes to application code" in combined
    finally:
        # Restore active
        if prev_active:
            active.write_text(prev_active)
        else:
            active.unlink(missing_ok=True)
        import shutil
        shutil.rmtree(state_dir, ignore_errors=True)


def test_guard_allows_app_code_after_reproduction(tmp_path):
    """Editing brightcart/ app code is allowed when a suspect is reproduced."""
    state_dir = Path(".culprit/GUARD_TEST_INC2")
    state_dir.mkdir(parents=True, exist_ok=True)
    active = Path(".culprit/ACTIVE")
    prev_active = active.read_text() if active.exists() else None
    active.write_text("GUARD_TEST_INC2")

    ledger = {
        "incident_id": "GUARD_TEST_INC2",
        "primary_signature_id": "SIG1",
        "suspects": [
            {"id": "S1", "status": "reproduced", "kind": "code", "title": "t", "service": "orders",
             "prior": 0.60, "rationale": "r", "evidence_ids": [], "test_ids": []},
        ],
        "tests": [],
        "history": [],
    }
    (state_dir / "ledger.json").write_text(json.dumps(ledger))

    try:
        result = _run_guard({
            "tool_name": "apply_diff",
            "tool_input": {"path": "brightcart/orders/address.py"},
        })
        assert result.returncode == 0
    finally:
        if prev_active:
            active.write_text(prev_active)
        else:
            active.unlink(missing_ok=True)
        import shutil
        shutil.rmtree(state_dir, ignore_errors=True)


def test_guard_fallback_path_extraction():
    """Guard should find path via nested value walk when standard keys are missing."""
    result = _run_guard({
        "tool_name": "write_file",
        "arguments": {"file_path": ".culprit/INC-001/ledger.json"},
    })
    # tool_name matches write tools but path key is in "arguments.file_path"
    # The walk should find the ledger.json path
    assert result.returncode == 2

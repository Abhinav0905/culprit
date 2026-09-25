"""Unit tests for culprit models."""
import pytest
from culprit.models import Event, Frame, Ledger, Signature, Suspect, TestRun, Transition
from datetime import datetime, timezone


_TS = datetime(2026, 9, 24, 9, 7, 0, tzinfo=timezone.utc)


def test_frame_optional_line():
    f = Frame(module="brightcart.orders.address", function="to_label_line")
    assert f.line is None


def test_event_log():
    ev = Event(
        id="E00001",
        ts=_TS,
        service="orders",
        kind="log",
        level="ERROR",
        name="order_failed",
        message="order creation failed",
        exc_type="UnicodeEncodeError",
        exc_message="'ascii' codec...",
        frames=[Frame(module="brightcart.orders.address", function="to_label_line", line=44)],
    )
    assert ev.kind == "log"
    assert ev.exc_type == "UnicodeEncodeError"


def test_suspect_defaults():
    s = Suspect(
        id="S1",
        kind="change",
        title="payments deploy",
        service="payments",
        prior=0.65,
        rationale="C2 before first error",
        evidence_ids=["E001"],
    )
    assert s.status == "suspect"
    assert s.test_ids == []


def test_ledger_round_trip():
    s = Suspect(
        id="S1", kind="change", title="test",
        service="payments", prior=0.5,
        rationale="r", evidence_ids=[],
    )
    ledger = Ledger(incident_id="INC-001", primary_signature_id="SIG1", suspects=[s])
    json_str = ledger.model_dump_json()
    ledger2 = Ledger.model_validate_json(json_str)
    assert ledger2.suspects[0].id == "S1"

"""Unit tests for ingest and reconstruction — checks the expected INC-001 suspects."""
import pytest
from pathlib import Path


# These tests require the INC-001 dataset to be present
pytestmark = pytest.mark.skipif(
    not Path("datasets/incidents/INC-001/meta.json").exists(),
    reason="INC-001 dataset not generated yet",
)


def test_ingest_produces_events():
    from culprit.ingest import ingest
    events = ingest("INC-001")
    assert len(events) > 1000
    kinds = {e.kind for e in events}
    assert "log" in kinds
    assert "metric" in kinds
    assert "change" in kinds


def test_ingest_events_sorted_by_time():
    from culprit.ingest import load_events
    events = load_events("INC-001")
    ts_list = [e.ts for e in events]
    assert ts_list == sorted(ts_list), "Events must be sorted by timestamp"


def test_ingest_error_events_have_frames():
    from culprit.ingest import load_events
    events = load_events("INC-001")
    error_events = [e for e in events if e.level == "ERROR" and e.exc_type]
    assert len(error_events) > 0
    for ev in error_events[:5]:
        assert ev.frames, f"Error event {ev.id} missing frames"


def test_reconstruct_three_suspects():
    """Reconstruction must produce exactly three suspects for INC-001."""
    from culprit.reconstruct import reconstruct
    incident, ledger = reconstruct("INC-001")
    assert len(ledger.suspects) == 3


def test_suspects_expected_priors():
    """S1=0.65 (change/payments), S2=0.60 (code/orders), S3=0.25 (resource)."""
    from culprit.reconstruct import load_ledger
    ledger = load_ledger("INC-001")
    suspects = {s.id: s for s in ledger.suspects}

    # S1: payments change with highest prior
    s1 = suspects["S1"]
    assert s1.kind == "change"
    assert s1.service == "payments"
    assert abs(s1.prior - 0.65) < 0.01, f"S1 prior expected 0.65, got {s1.prior}"

    # S2: code suspect with merge
    s2 = suspects["S2"]
    assert s2.kind == "code"
    assert s2.service == "orders"
    assert abs(s2.prior - 0.60) < 0.01, f"S2 prior expected 0.60, got {s2.prior}"
    assert s2.change_id == "C1"
    assert "to_label_line" in s2.title
    assert "UnicodeEncodeError" in s2.title
    assert "C1" in s2.title

    # S3: resource suspect (pool), after first error → prior 0.25
    s3 = suspects["S3"]
    assert s3.kind == "resource"
    assert s3.service == "orders"
    assert abs(s3.prior - 0.25) < 0.01, f"S3 prior expected 0.25, got {s3.prior}"


def test_all_suspects_are_suspect_status():
    """All suspects start in 'suspect' status before any tests run."""
    from culprit.reconstruct import load_ledger
    ledger = load_ledger("INC-001")
    for s in ledger.suspects:
        assert s.status == "suspect", f"{s.id} status is {s.status}, expected suspect"


def test_primary_signature_is_unicode_error():
    from culprit.reconstruct import load_ledger, load_incident
    ledger = load_ledger("INC-001")
    incident = load_incident("INC-001")
    primary_sig = next(
        s for s in incident["signatures"] if s["id"] == ledger.primary_signature_id
    )
    assert primary_sig["exc_type"] == "UnicodeEncodeError"
    assert primary_sig["top_frame"]["module"] == "brightcart.orders.address"
    assert primary_sig["top_frame"]["function"] == "to_label_line"


def test_normalize_message():
    from culprit.signature import normalize
    msg = "Cannot encode '\\xdf' at position 10 in 'Straße'"
    result = normalize(msg)
    assert "<n>" in result
    assert result == result.lower()


def test_signature_normalize_collapse_whitespace():
    from culprit.signature import normalize
    assert normalize("  hello   world  ") == "hello world"

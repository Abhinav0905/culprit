"""Unit tests for runner.py and signature.py using fixture test files."""
from __future__ import annotations

import pytest
from pathlib import Path

FIXTURE_DIR = Path("culprit/tests/fixtures")
UNICODE_FAIL = str(FIXTURE_DIR / "test_unicode_fail.py")
PASS_TEST = str(FIXTURE_DIR / "test_pass.py")
OTHER_ERROR = str(FIXTURE_DIR / "test_other_error.py")

# Signature details from INC-001 primary signature
SIG_EXC_TYPE = "UnicodeEncodeError"
SIG_EXC_MSG_NORM = "'ascii' codec can't encode character '<ch>' in position <n>: ordinal not in range(<n>)"
SIG_MODULE = "brightcart.orders.address"
SIG_FUNCTION = "to_label_line"

from culprit.signature import normalize

_SIG_NORM = normalize(
    "'ascii' codec can't encode character '\\xdf' in position 10: ordinal not in range(128)"
)


def _run(test_path: str):
    """Run a fixture test and return (outcome, score, exc_type)."""
    from culprit.runner import run_test
    tr = run_test(
        incident_id="INC-001",
        suspect_id="S_TEST",
        test_path=test_path,
        primary_sig_exc_type=SIG_EXC_TYPE,
        primary_sig_exc_message_norm=_SIG_NORM,
        primary_sig_top_frame_module=SIG_MODULE,
        primary_sig_top_frame_function=SIG_FUNCTION,
    )
    return tr


def test_unicode_fail_scores_near_one():
    """The unicode fail fixture should score close to 1.0."""
    tr = _run(UNICODE_FAIL)
    assert tr.outcome in ("failed", "error"), f"Expected failure, got {tr.outcome}"
    assert tr.score >= 0.80, f"Score too low: {tr.score}"
    assert tr.observed_exc_type == "UnicodeEncodeError"


def test_pass_fixture_scores_zero():
    """A passing test scores exactly 0.0."""
    tr = _run(PASS_TEST)
    assert tr.outcome == "passed"
    assert tr.score == 0.0


def test_other_error_scores_below_threshold():
    """A test that raises a different error should score below 0.30."""
    tr = _run(OTHER_ERROR)
    assert tr.outcome in ("failed", "error"), f"Expected failure, got {tr.outcome}"
    assert tr.score < 0.30, f"Score too high: {tr.score}"
    assert tr.observed_exc_type != "UnicodeEncodeError"


def test_normalize_replaces_digits():
    from culprit.signature import normalize
    assert normalize("position 10 in range 128") == "position <n> in range <n>"


def test_normalize_replaces_escapes():
    from culprit.signature import normalize
    result = normalize("character '\\xdf' at \\u00df")
    assert "<ch>" in result


def test_score_run_type_match():
    from culprit.signature import score_run
    s = score_run(
        observed_exc_type="UnicodeEncodeError",
        observed_exc_message="'ascii' codec can't encode character '\\xdf' in position 10: ordinal not in range(128)",
        observed_frames=[{"module": "brightcart.orders.address", "function": "to_label_line"}],
        outcome="failed",
        logged_exc_type="UnicodeEncodeError",
        logged_exc_message_norm=_SIG_NORM,
        logged_top_frame_module="brightcart.orders.address",
        logged_top_frame_function="to_label_line",
    )
    assert s >= 0.80


def test_score_run_passed_is_zero():
    from culprit.signature import score_run
    s = score_run(
        observed_exc_type="UnicodeEncodeError",
        observed_exc_message="any",
        observed_frames=[],
        outcome="passed",
        logged_exc_type="UnicodeEncodeError",
        logged_exc_message_norm=_SIG_NORM,
        logged_top_frame_module=None,
        logged_top_frame_function=None,
    )
    assert s == 0.0

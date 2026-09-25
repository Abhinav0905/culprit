"""Error fingerprint normalisation (shared between ingest and scoring)."""
from __future__ import annotations

import re
from difflib import SequenceMatcher


def normalize(msg: str) -> str:
    """Normalise an exception message for fuzzy comparison.

    Steps (in order):
    1. Lowercase.
    2. Replace quoted substrings (single or double quotes) with <q>.
    3. Replace \\xNN and \\uNNNN escape sequences with <ch>.
    4. Replace runs of digits with <n>.
    5. Collapse whitespace.
    """
    s = msg.lower()
    s = re.sub(r"'[^']*'|\"[^\"]*\"", "<q>", s)
    s = re.sub(r"\\x[0-9a-fA-F]{2}|\\u[0-9a-fA-F]{4}", "<ch>", s)
    s = re.sub(r"\d+", "<n>", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def score_run(
    observed_exc_type: str | None,
    observed_exc_message: str | None,
    observed_frames: list[dict],  # list of {"module": ..., "function": ...}
    outcome: str,
    logged_exc_type: str,
    logged_exc_message_norm: str,
    logged_top_frame_module: str | None,
    logged_top_frame_function: str | None,
) -> float:
    """Compute match score between a test run and a logged signature.

    Returns 0.0 if the test passed.
    """
    if outcome == "passed":
        return 0.0

    s = 0.0

    if observed_exc_type and observed_exc_type == logged_exc_type:
        s += 0.5

    if observed_exc_message is not None:
        obs_norm = normalize(observed_exc_message)
        ratio = SequenceMatcher(None, obs_norm, logged_exc_message_norm).ratio()
        s += 0.3 * ratio

    if logged_top_frame_module and logged_top_frame_function:
        for fr in observed_frames:
            if (
                fr.get("module") == logged_top_frame_module
                and fr.get("function") == logged_top_frame_function
            ):
                s += 0.2
                break

    return round(min(1.0, s), 4)

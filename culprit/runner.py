"""Runs one pytest file, parses JUnit XML, returns a TestRun record."""
from __future__ import annotations

import re
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from culprit.models import Frame, TestRun
from culprit.signature import normalize, score_run

_STATE_ROOT = Path(".culprit")


def run_test(
    incident_id: str,
    suspect_id: str,
    test_path: str,
    primary_sig_exc_type: str,
    primary_sig_exc_message_norm: str,
    primary_sig_top_frame_module: str | None,
    primary_sig_top_frame_function: str | None,
) -> TestRun:
    """Run pytest on test_path, parse results, return a TestRun."""
    run_id = uuid.uuid4().hex[:8]
    junit_dir = _STATE_ROOT / incident_id / "junit"
    junit_dir.mkdir(parents=True, exist_ok=True)
    junit_xml = junit_dir / f"{run_id}.xml"

    import os, time
    env = {**os.environ, "CULPRIT_INCIDENT": incident_id, "CULPRIT_RUN_EVIDENCE": "1"}

    t0 = time.monotonic()
    result = subprocess.run(
        [
            ".venv/bin/python", "-m", "pytest",
            test_path, "-q", "-p", "no:cacheprovider",
            f"--junitxml={junit_xml}",
        ],
        capture_output=True, text=True, timeout=120, env=env,
    )
    duration_s = round(time.monotonic() - t0, 3)

    # Parse mechanism from docstring
    mechanism = _parse_mechanism(test_path)

    # Parse JUnit XML
    outcome, obs_exc_type, obs_exc_message, obs_frames = _parse_junit(junit_xml, result)

    # Score
    score = score_run(
        observed_exc_type=obs_exc_type,
        observed_exc_message=obs_exc_message,
        observed_frames=[f.model_dump() for f in obs_frames],
        outcome=outcome,
        logged_exc_type=primary_sig_exc_type,
        logged_exc_message_norm=primary_sig_exc_message_norm,
        logged_top_frame_module=primary_sig_top_frame_module,
        logged_top_frame_function=primary_sig_top_frame_function,
    )

    # Get current commit
    commit = _git_head()

    return TestRun(
        id=f"T{run_id[:6]}",
        suspect_id=suspect_id,
        path=test_path,
        commit=commit,
        outcome=outcome,
        observed_exc_type=obs_exc_type,
        observed_exc_message=obs_exc_message,
        observed_frames=obs_frames,
        signature_id="SIG1",
        score=score,
        mechanism=mechanism,
        duration_s=duration_s,
        ran_at=datetime.now(timezone.utc),
    )


def _parse_mechanism(test_path: str) -> str:
    """Extract mechanism from module docstring."""
    try:
        src = Path(test_path).read_text(encoding="utf-8")
        m = re.search(r'mechanism:\s*(.+)', src)
        if m:
            return m.group(1).strip()
    except Exception:
        pass
    return "unknown"


def _parse_junit(
    junit_xml: Path, proc_result: subprocess.CompletedProcess
) -> tuple[str, str | None, str | None, list[Frame]]:
    """Parse JUnit XML and return (outcome, exc_type, exc_message, frames)."""
    if not junit_xml.exists():
        return "not_collected", None, None, []

    try:
        tree = ElementTree.parse(junit_xml)
    except Exception:
        return "not_collected", None, None, []

    root = tree.getroot()
    # Find first testcase
    testcases = root.findall(".//testcase")
    if not testcases:
        return "not_collected", None, None, []

    tc = testcases[0]
    failure = tc.find("failure")
    error = tc.find("error")
    skipped = tc.find("skipped")

    if skipped is not None:
        return "passed", None, None, []

    if failure is None and error is None:
        return "passed", None, None, []

    outcome = "failed" if failure is not None else "error"
    node = failure if failure is not None else error
    # The message attribute has "ExcType: message"; the text body has the full traceback
    message_attr = node.get("message", "") or ""
    body_text = node.text or ""
    # Combine both for parsing
    combined = message_attr + "\n" + body_text

    exc_type, exc_message, frames = _parse_failure_text(combined)
    return outcome, exc_type, exc_message, frames


def _parse_failure_text(text: str) -> tuple[str | None, str | None, list[Frame]]:
    """Extract exc_type, exc_message and brightcart frames from failure text."""
    # Unescape HTML entities from JUnit XML first
    text = text.replace("&gt;", ">").replace("&lt;", "<").replace("&amp;", "&")
    lines = text.splitlines()

    # Exception type and message: last line that matches "ExcType: message" pattern
    exc_type: str | None = None
    exc_message: str | None = None
    for line in reversed(lines):
        line = line.strip()
        # Match "SomeException: message"
        m = re.match(r'^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Warning)[A-Za-z0-9_.]*):\s*(.*)$', line)
        if m:
            exc_type = m.group(1).split(".")[-1]  # short name
            exc_message = m.group(2).strip()
            break
        # Also handle bare exception names
        m2 = re.match(r'^([A-Za-z_][A-Za-z0-9_.]*(?:Error|Exception|Warning))$', line)
        if m2:
            exc_type = m2.group(1).split(".")[-1]
            break

    # Frames: "  File ".../brightcart/orders/address.py", line 44, in to_label_line"
    frames: list[Frame] = []
    for line in lines:
        m = re.search(r'File "([^"]*brightcart[^"]*\.py)", line (\d+), in (\w+)', line)
        if m:
            file_path = m.group(1)
            line_no = int(m.group(2))
            func = m.group(3)
            module = _file_to_module(file_path)
            frames.append(Frame(module=module, function=func, line=line_no))

    return exc_type, exc_message, frames


def _file_to_module(path: str) -> str:
    m = re.search(r"brightcart[/\\](.+)\.py$", path)
    if not m:
        return path
    return "brightcart." + m.group(1).replace("/", ".").replace("\\", ".")


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return "unknown"


def parse_docstring(test_path: str) -> dict[str, str]:
    """Return dict with suspect, mechanism, evidence keys from module docstring."""
    try:
        src = Path(test_path).read_text(encoding="utf-8")
        # Find triple-quoted module docstring
        m = re.search(r'^"""(.*?)"""', src, re.DOTALL)
        if not m:
            m = re.search(r"^'''(.*?)'''", src, re.DOTALL)
        if not m:
            return {}
        doc = m.group(1)
        result = {}
        for line in doc.splitlines():
            line = line.strip()
            for key in ("suspect", "mechanism", "evidence"):
                if line.startswith(f"{key}:"):
                    result[key] = line.split(":", 1)[1].strip()
        return result
    except Exception:
        return {}

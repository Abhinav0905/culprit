"""Pydantic v2 models for the Culprit data layer."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class Frame(BaseModel):
    module: str
    function: str
    line: int | None = None


class Event(BaseModel):
    id: str                                   # "E00001", in time order
    ts: datetime
    service: str
    kind: Literal["log", "metric", "change"]
    level: Literal["INFO", "WARN", "ERROR"] | None = None
    name: str                                 # log event name, metric name, or change id
    message: str
    exc_type: str | None = None
    exc_message: str | None = None
    frames: list[Frame] = []
    attrs: dict[str, Any] = {}


class Signature(BaseModel):                   # an error fingerprint seen in the logs
    id: str                                   # "SIG1"
    service: str
    exc_type: str
    exc_message_norm: str
    top_frame: Frame | None                   # innermost brightcart frame
    count: int
    first_seen: datetime
    example_event_ids: list[str]


class Suspect(BaseModel):
    id: str                                   # "S1", ranked by prior
    kind: Literal["code", "change", "resource"]
    title: str
    service: str
    module: str | None = None
    function: str | None = None
    change_id: str | None = None
    prior: float                              # 0..1, how suspicious before any test
    rationale: str
    evidence_ids: list[str]
    status: Literal["suspect", "reproduced", "cleared", "inconclusive", "fixed"] = "suspect"
    verdict_reason: str | None = None
    test_ids: list[str] = []


class TestRun(BaseModel):
    id: str                                   # "T1"
    suspect_id: str
    path: str
    commit: str
    outcome: Literal["failed", "error", "passed", "not_collected"]
    observed_exc_type: str | None = None
    observed_exc_message: str | None = None
    observed_frames: list[Frame] = []
    signature_id: str
    score: float                              # 0..1, see 6.2
    mechanism: str                            # from the test's docstring
    duration_s: float
    ran_at: datetime


class Transition(BaseModel):
    ts: datetime
    suspect_id: str
    from_status: str
    to_status: str
    test_ids: list[str]
    evidence_ids: list[str]
    actor: str                                # env CULPRIT_ACTOR, default "culprit-cli"
    reason: str


class Ledger(BaseModel):
    incident_id: str
    primary_signature_id: str
    suspects: list[Suspect]
    tests: list[TestRun] = []
    history: list[Transition] = []

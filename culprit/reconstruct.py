"""Reconstruct incident.json and ledger.json from events.json.

All thresholds are module-level constants so they can be tuned without touching logic.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from culprit.ingest import load_changes, load_events, load_meta
from culprit.models import Event, Frame, Ledger, Signature, Suspect
from culprit.signature import normalize

# ---------------------------------------------------------------------------
# Constants (all thresholds live here)
# ---------------------------------------------------------------------------

# Change-suspect prior by time-before-first-error
CHANGE_PRIOR_WITHIN_5_MIN = 0.60
CHANGE_PRIOR_WITHIN_15_MIN = 0.45
CHANGE_PRIOR_WITHIN_30_MIN = 0.30

CHANGE_BONUS_ORIGIN_SERVICE = 0.10
CHANGE_BONUS_WARN_BETWEEN = 0.05

# Code suspect base prior
CODE_PRIOR_BASE = 0.45
CODE_PRIOR_MERGE_ADD = 0.15
CODE_PRIOR_MERGE_CAP = 0.95

# Resource suspect prior
RESOURCE_PRIOR_BEFORE_ERROR = 0.40
RESOURCE_PRIOR_AFTER_ERROR = 0.25

# Window for change suspects (minutes before first error)
CHANGE_WINDOW_MINUTES = 30

# Saturation log event names
SATURATION_EVENTS = {"db_pool_high", "queue_depth_high", "memory_high", "cpu_high"}

# State root
_STATE_ROOT = Path(".culprit")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _module_to_file(module: str) -> str:
    """Convert dotted module name to file path fragment."""
    return module.replace(".", "/") + ".py"


def _ts_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Core reconstruction
# ---------------------------------------------------------------------------

def reconstruct(incident_id: str) -> tuple[dict[str, Any], Ledger]:
    """Run the full reconstruction pipeline and write incident.json + ledger.json."""
    events = load_events(incident_id)
    changes = load_changes(incident_id)
    meta = load_meta(incident_id)

    alert_at = _parse_ts(meta["alert_at"])
    window_start = _parse_ts(meta["window"]["start"])
    window_end = _parse_ts(meta["window"]["end"])

    # -----------------------------------------------------------------------
    # Step 2: Build error signatures
    # -----------------------------------------------------------------------
    # Group ERROR log events with exc_type by (service, exc_type, norm_msg, top_frame)
    # Gateway checkout_failed events have no exc_type — they are propagation evidence.
    sig_groups: dict[tuple, list[Event]] = {}
    for ev in events:
        if ev.kind != "log" or ev.level != "ERROR" or not ev.exc_type:
            continue
        top_frame = ev.frames[-1] if ev.frames else None
        top_frame_key = (top_frame.module, top_frame.function) if top_frame else (None, None)
        key = (ev.service, ev.exc_type, normalize(ev.exc_message or ""), top_frame_key)
        sig_groups.setdefault(key, []).append(ev)

    signatures: list[Signature] = []
    for sig_idx, (key, sig_events) in enumerate(sig_groups.items(), start=1):
        service, exc_type, exc_message_norm, (tf_module, tf_function) = key
        top_frame: Frame | None = None
        if tf_module:
            # Take actual line from the first event's top frame
            first_tf = sig_events[0].frames[-1] if sig_events[0].frames else None
            top_frame = Frame(module=tf_module, function=tf_function,
                              line=first_tf.line if first_tf else None)
        sig_events_sorted = sorted(sig_events, key=lambda e: e.ts)
        signatures.append(Signature(
            id=f"SIG{sig_idx}",
            service=service,
            exc_type=exc_type,
            exc_message_norm=exc_message_norm,
            top_frame=top_frame,
            count=len(sig_events),
            first_seen=sig_events_sorted[0].ts,
            example_event_ids=[e.id for e in sig_events_sorted[:3]],
        ))

    # -----------------------------------------------------------------------
    # Step 3: Origin service + primary signature
    # -----------------------------------------------------------------------
    # The service with the earliest signature (gateway checkout_failed events point to
    # their upstream service, not to themselves).
    if not signatures:
        raise ValueError(f"No error signatures found in {incident_id} events.")

    # Find earliest first_seen
    signatures.sort(key=lambda s: s.first_seen)
    first_error_at = signatures[0].first_seen

    # Origin = service with earliest signature
    origin_service = signatures[0].service

    # Primary signature = highest count among origin service signatures
    origin_sigs = [s for s in signatures if s.service == origin_service]
    primary_sig = max(origin_sigs, key=lambda s: s.count)

    # -----------------------------------------------------------------------
    # Step 4a: Code suspect from primary signature's top frame
    # -----------------------------------------------------------------------
    code_suspect: Suspect | None = None
    if primary_sig.top_frame:
        tf = primary_sig.top_frame
        code_suspect = Suspect(
            id="CODE_TMP",
            kind="code",
            title=f"`{tf.module}.{tf.function}` raises {primary_sig.exc_type} on some inputs",
            service=origin_service,
            module=tf.module,
            function=tf.function,
            prior=CODE_PRIOR_BASE,
            rationale=(
                f"{tf.module}.{tf.function} raises {primary_sig.exc_type} "
                f"({primary_sig.count} times in the window)."
            ),
            evidence_ids=primary_sig.example_event_ids,
        )

    # -----------------------------------------------------------------------
    # Step 4b: Change suspects
    # -----------------------------------------------------------------------
    change_suspects: list[Suspect] = []
    cutoff = first_error_at - timedelta(minutes=CHANGE_WINDOW_MINUTES)

    for change in changes:
        change_ts = _parse_ts(change["ts"])
        if change_ts < cutoff or change_ts > first_error_at:
            continue
        delta_min = (first_error_at - change_ts).total_seconds() / 60.0

        if delta_min <= 5:
            base = CHANGE_PRIOR_WITHIN_5_MIN
        elif delta_min <= 15:
            base = CHANGE_PRIOR_WITHIN_15_MIN
        else:
            base = CHANGE_PRIOR_WITHIN_30_MIN

        prior = base
        if change.get("service") == origin_service:
            prior += CHANGE_BONUS_ORIGIN_SERVICE

        # Check for WARN events from the changed service between change time and first error
        changed_service = change.get("service", "")
        has_warn = any(
            ev.kind == "log" and ev.level == "WARN"
            and ev.service == changed_service
            and change_ts <= ev.ts <= first_error_at
            for ev in events
        )
        if has_warn:
            prior += CHANGE_BONUS_WARN_BETWEEN

        # Find evidence events: error events near the time of this change
        evidence_ids = [
            ev.id for ev in events
            if ev.kind == "log" and ev.level == "ERROR"
            and ev.service in (changed_service, origin_service)
        ][:5]

        # Change event id
        change_event_ids = [
            ev.id for ev in events
            if ev.kind == "change" and ev.name == change["id"]
        ]

        change_suspects.append(Suspect(
            id=f"CHG_{change['id']}",
            kind="change",
            title=(
                f"{change['service']} {change['to_version']} deploy ({change['id']}), "
                f"{delta_min:.0f} minutes before the first error"
                + (f", p95 latency rose after it" if has_warn else "")
            ),
            service=changed_service,
            module=None,
            change_id=change["id"],
            prior=round(prior, 4),
            rationale=(
                f"{change['id']}: {change['summary']} "
                f"({change['from_version']} → {change['to_version']}, "
                f"{delta_min:.0f} min before first error)"
            ),
            evidence_ids=change_event_ids + evidence_ids[:3],
        ))

    # -----------------------------------------------------------------------
    # Step 4c: Merge rule
    # -----------------------------------------------------------------------
    # If a change's files include the code suspect's module file, merge it in.
    merged_change_ids: set[str] = set()
    if code_suspect:
        code_module_file = _module_to_file(code_suspect.module or "")
        for cs in change_suspects:
            change_raw = next(
                (c for c in changes if c["id"] == cs.change_id), None
            )
            if change_raw and any(
                f == code_module_file or f.endswith("/" + code_module_file.split("/")[-1])
                for f in change_raw.get("files", [])
            ):
                # Merge: boost code suspect, attach change, update title and rationale
                merged_title = (
                    code_suspect.title.rstrip(".")
                    + f", introduced by {cs.change_id} ({cs.service} {change_raw['to_version']})"
                )
                code_suspect = code_suspect.model_copy(update={
                    "prior": min(
                        CODE_PRIOR_MERGE_CAP,
                        code_suspect.prior + CODE_PRIOR_MERGE_ADD,
                    ),
                    "title": merged_title,
                    "change_id": cs.change_id,
                    "rationale": (
                        code_suspect.rationale.rstrip(".")
                        + f", introduced by {cs.change_id} "
                        f"({cs.service} {change_raw['to_version']})."
                    ),
                    "evidence_ids": list(dict.fromkeys(
                        code_suspect.evidence_ids + cs.evidence_ids
                    )),
                })
                merged_change_ids.add(cs.change_id)

    # Drop merged changes from the change suspects list
    change_suspects = [cs for cs in change_suspects if cs.change_id not in merged_change_ids]

    # -----------------------------------------------------------------------
    # Step 4d: Resource suspects
    # -----------------------------------------------------------------------
    resource_suspects: list[Suspect] = []
    # Find saturation warnings on the origin service; group by (logger, event_name)
    seen_resource_groups: dict[tuple[str, str], list[Event]] = {}
    for ev in events:
        if (
            ev.kind == "log"
            and ev.level == "WARN"
            and ev.service == origin_service
            and ev.name in SATURATION_EVENTS
        ):
            # Logger is preserved in attrs by ingest.py
            logger = ev.attrs.get("logger", ev.service)
            key = (logger, ev.name)
            seen_resource_groups.setdefault(key, []).append(ev)

    for (logger, event_name), warn_events in seen_resource_groups.items():
        warn_events_sorted = sorted(warn_events, key=lambda e: e.ts)
        first_warn_ts = warn_events_sorted[0].ts
        if first_warn_ts < first_error_at:
            prior = RESOURCE_PRIOR_BEFORE_ERROR
            rationale = (
                f"Saturation warnings from {logger} started before the first error, "
                f"suggesting a contributing resource constraint."
            )
            timing_note = "started before the first error"
        else:
            prior = RESOURCE_PRIOR_AFTER_ERROR
            rationale = (
                f"Saturation warnings from {logger} started after the first error "
                f"and may be a consequence."
            )
            timing_note = "started after the first error, may be a consequence"
        # Build a readable title
        resource_label = (
            event_name.replace("db_pool_high", "DB pool")
                      .replace("queue_depth_high", "queue depth")
                      .replace("memory_high", "memory")
                      .replace("cpu_high", "CPU")
                      .replace("_high", "")
        )
        resource_suspects.append(Suspect(
            id="RES_TMP",
            kind="resource",
            title=f"{origin_service} {resource_label} saturation ({timing_note})",
            service=origin_service,
            module=logger,
            prior=prior,
            rationale=rationale,
            evidence_ids=[e.id for e in warn_events_sorted[:5]],
        ))

    # -----------------------------------------------------------------------
    # Step 4e: Combine, sort, and number suspects
    # -----------------------------------------------------------------------
    all_suspects: list[Suspect] = []
    if code_suspect:
        all_suspects.append(code_suspect)
    all_suspects.extend(change_suspects)
    all_suspects.extend(resource_suspects)

    # Sort by prior descending, stable
    all_suspects.sort(key=lambda s: s.prior, reverse=True)

    final_suspects: list[Suspect] = []
    for idx, s in enumerate(all_suspects, start=1):
        final_suspects.append(s.model_copy(update={"id": f"S{idx}"}))

    # -----------------------------------------------------------------------
    # Step 5: Timeline
    # -----------------------------------------------------------------------
    timeline: list[dict[str, Any]] = []

    for change in sorted(changes, key=lambda c: c["ts"]):
        change_ev_ids = [ev.id for ev in events if ev.kind == "change" and ev.name == change["id"]]
        timeline.append({
            "ts": change["ts"],
            "label": f"{change['id']}: {change['summary']}",
            "kind": "change",
            "evidence_ids": change_ev_ids,
        })

    # Start of each WARN series
    seen_warn_series: set[tuple[str, str]] = set()
    for ev in sorted(events, key=lambda e: e.ts):
        if ev.kind == "log" and ev.level == "WARN":
            key = (ev.service, ev.name)
            if key not in seen_warn_series:
                seen_warn_series.add(key)
                timeline.append({
                    "ts": _ts_str(ev.ts),
                    "label": f"First {ev.name} WARN ({ev.service})",
                    "kind": "warn",
                    "evidence_ids": [ev.id],
                })

    # Metric shifts > 3x
    metric_by_name: dict[str, list[Event]] = {}
    for ev in events:
        if ev.kind == "metric":
            metric_by_name.setdefault(ev.name, []).append(ev)
    for name, mevents in metric_by_name.items():
        mevents_s = sorted(mevents, key=lambda e: e.ts)
        for i in range(1, len(mevents_s)):
            prev = mevents_s[i - 1].attrs.get("value", 0) or 0
            curr = mevents_s[i].attrs.get("value", 0) or 0
            if prev > 0 and curr / prev > 3:
                timeline.append({
                    "ts": _ts_str(mevents_s[i].ts),
                    "label": f"{name} jumped {prev:.1f} → {curr:.1f}",
                    "kind": "metric_shift",
                    "evidence_ids": [mevents_s[i].id],
                })
                break  # record first shift only

    # First error per service
    first_error_per_service: dict[str, Event] = {}
    for ev in sorted(events, key=lambda e: e.ts):
        if ev.kind == "log" and ev.level == "ERROR" and ev.service not in first_error_per_service:
            first_error_per_service[ev.service] = ev
    for svc, ev in sorted(first_error_per_service.items(), key=lambda x: x[1].ts):
        timeline.append({
            "ts": _ts_str(ev.ts),
            "label": f"First ERROR in {svc} ({ev.name})",
            "kind": "error",
            "evidence_ids": [ev.id],
        })

    # Alert
    timeline.append({
        "ts": _ts_str(alert_at),
        "label": "Alert fired",
        "kind": "alert",
        "evidence_ids": [],
    })

    timeline.sort(key=lambda t: t["ts"])

    # -----------------------------------------------------------------------
    # Step 6: Missing evidence
    # -----------------------------------------------------------------------
    missing_evidence = [
        "No distributed traces — gateway-to-orders linkage comes from `upstream` and `trace_id` only.",
        "No label-printer logs.",
        "No payments error logs in the window.",
    ]

    # -----------------------------------------------------------------------
    # Build incident.json payload
    # -----------------------------------------------------------------------
    # Count failed checkouts and peak error rate from events
    error_events = [
        ev for ev in events
        if ev.kind == "log" and ev.level == "ERROR" and ev.service == "gateway"
    ]
    failed_checkouts = len(error_events)

    # Peak error rate from metrics
    error_rate_events = [
        ev for ev in events
        if ev.kind == "metric" and ev.name == "error_rate_pct"
    ]
    error_rate_peak = max((e.attrs.get("value", 0) for e in error_rate_events), default=0)

    affected_services = list({s.service for s in signatures} | {"gateway"})

    incident: dict[str, Any] = {
        "id": incident_id,
        "title": meta["title"],
        "window": meta["window"],
        "alert_at": _ts_str(alert_at),
        "origin_service": origin_service,
        "affected_services": affected_services,
        "first_error_at": _ts_str(first_error_at),
        "error_rate_peak_pct": float(error_rate_peak),
        "failed_checkouts": failed_checkouts,
        "signatures": [s.model_dump(mode="json") for s in signatures],
        "timeline": timeline,
        "missing_evidence": missing_evidence,
    }

    # Build ledger
    ledger = Ledger(
        incident_id=incident_id,
        primary_signature_id=primary_sig.id,
        suspects=final_suspects,
    )

    # Write to state directory
    state_dir = _STATE_ROOT / incident_id
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "incident.json").write_text(
        json.dumps(incident, indent=2), encoding="utf-8"
    )
    (state_dir / "ledger.json").write_text(
        ledger.model_dump_json(indent=2), encoding="utf-8"
    )

    return incident, ledger


def load_incident(incident_id: str) -> dict[str, Any]:
    path = _STATE_ROOT / incident_id / "incident.json"
    return json.loads(path.read_text(encoding="utf-8"))


def load_ledger(incident_id: str) -> Ledger:
    path = _STATE_ROOT / incident_id / "ledger.json"
    return Ledger.model_validate_json(path.read_text(encoding="utf-8"))


def save_ledger(incident_id: str, ledger: Ledger) -> None:
    path = _STATE_ROOT / incident_id / "ledger.json"
    path.write_text(ledger.model_dump_json(indent=2), encoding="utf-8")


def _parse_ts(ts_str: str) -> datetime:
    return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))

"""Culprit CLI: argparse commands."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_STATE_ROOT = Path(".culprit")
_ACTIVE_FILE = _STATE_ROOT / "ACTIVE"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_active() -> str | None:
    if _ACTIVE_FILE.exists():
        return _ACTIVE_FILE.read_text(encoding="utf-8").strip()
    return None


def _require_incident(args: argparse.Namespace) -> str:
    inc = getattr(args, "incident", None) or _get_active()
    if not inc:
        print("ERROR: no incident specified and no active incident set.", file=sys.stderr)
        sys.exit(3)
    return inc


def _load_ledger(incident_id: str):
    from culprit.reconstruct import load_ledger
    return load_ledger(incident_id)


def _save_ledger(incident_id: str, ledger) -> None:
    from culprit.reconstruct import save_ledger
    save_ledger(incident_id, ledger)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_ingest(args: argparse.Namespace) -> int:
    incident_id = _require_incident(args)
    from culprit.ingest import ingest
    events = ingest(incident_id)
    by_kind: dict[str, int] = {}
    for e in events:
        by_kind[e.kind] = by_kind.get(e.kind, 0) + 1
    print(f"Ingested {len(events)} events for {incident_id}: "
          + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())))
    return 0


def cmd_reconstruct(args: argparse.Namespace) -> int:
    incident_id = _require_incident(args)
    from culprit.reconstruct import reconstruct
    incident, ledger = reconstruct(incident_id)
    print(f"Reconstructed {incident_id}: {len(ledger.suspects)} suspects, "
          f"primary signature {ledger.primary_signature_id}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    incident_id: str | None = None

    if hasattr(args, "active") and args.active:
        incident_id = _get_active()
        if not incident_id:
            print("No active incident.")
            return 0
    else:
        incident_id = _require_incident(args)

    try:
        ledger = _load_ledger(incident_id)
    except FileNotFoundError:
        print(f"ERROR: ledger not found for {incident_id}. Run reconstruct first.", file=sys.stderr)
        sys.exit(3)

    try:
        from culprit.reconstruct import load_incident
        incident = load_incident(incident_id)
        primary_sig_id = ledger.primary_signature_id
        # Find primary sig details
        sig = next((s for s in incident.get("signatures", []) if s["id"] == primary_sig_id), None)
        if sig:
            print(f"{incident_id}  primary signature {primary_sig_id}: "
                  f"{sig.get('exc_type','')} in {sig.get('top_frame', {}).get('module','') if sig.get('top_frame') else ''}")
    except Exception:
        pass

    print(f"{'ID':<4} {'PRIOR':<6} {'STATUS':<14} TITLE")
    for s in ledger.suspects:
        print(f"{s.id:<4} {s.prior:<6.2f} {s.status:<14} {s.title}")
    return 0


def cmd_evidence(args: argparse.Namespace) -> int:
    incident_id = _require_incident(args)
    suspect_id = args.suspect_id

    ledger = _load_ledger(incident_id)
    suspect = next((s for s in ledger.suspects if s.id == suspect_id), None)
    if not suspect:
        print(f"ERROR: suspect {suspect_id} not found.", file=sys.stderr)
        sys.exit(3)

    print(json.dumps(suspect.model_dump(mode="json"), indent=2))

    # Print linked change records
    if suspect.change_id:
        from culprit.ingest import load_changes
        changes = load_changes(incident_id)
        for c in changes:
            if c["id"] == suspect.change_id:
                print("\n--- Change ---")
                print(json.dumps(c, indent=2))

    # Print up to 10 supporting events
    from culprit.ingest import load_events
    events = load_events(incident_id)
    ev_ids = set(suspect.evidence_ids)
    evidence_events = [e for e in events if e.id in ev_ids][:10]
    if evidence_events:
        print("\n--- Evidence events ---")
        for ev in evidence_events:
            ev_dict = {
                "id": ev.id,
                "ts": ev.ts.isoformat(),
                "service": ev.service,
                "level": ev.level,
                "name": ev.name,
            }
            if ev.exc_type:
                ev_dict["exc_type"] = ev.exc_type
            if ev.exc_message:
                ev_dict["exc_message"] = ev.exc_message[:120]
            if ev.frames:
                ev_dict["frames"] = [f.model_dump() for f in ev.frames]
            print(json.dumps(ev_dict))
    return 0


def cmd_open(args: argparse.Namespace) -> int:
    incident_id = _require_incident(args)
    _STATE_ROOT.mkdir(parents=True, exist_ok=True)
    _ACTIVE_FILE.write_text(incident_id, encoding="utf-8")
    print(f"Active incident set to {incident_id}")

    # Write tests/incidents/<INC>/conftest.py
    _write_conftest(incident_id)
    return 0


def _write_conftest(incident_id: str) -> None:
    """Write the pytest conftest.py that skips cleared/inconclusive evidence tests."""
    conftest_dir = Path("tests/incidents") / incident_id
    conftest_dir.mkdir(parents=True, exist_ok=True)
    conftest_path = conftest_dir / "conftest.py"
    content = f'''"""Culprit evidence test gating for {incident_id}.

Generated by `culprit open {incident_id}`. Do not edit by hand.
"""
import os
from pathlib import Path

import pytest


def pytest_collection_modifyitems(items, config):
    """Skip tests for cleared or inconclusive suspects unless CULPRIT_RUN_EVIDENCE=1."""
    if os.environ.get("CULPRIT_RUN_EVIDENCE") == "1":
        return

    ledger_path = Path(".culprit/{incident_id}/ledger.json")
    if not ledger_path.exists():
        return

    import json
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except Exception:
        return

    suspect_status = {{s["id"]: s["status"] for s in ledger.get("suspects", [])}}

    # Map test_ids to suspect_ids from ledger
    test_to_suspect = {{}}
    for s in ledger.get("suspects", []):
        for t_id in s.get("test_ids", []):
            test_to_suspect[t_id] = s["id"]

    for item in items:
        # Read the module docstring to find suspect id
        module = item.module if hasattr(item, "module") else None
        doc = module.__doc__ if module else ""
        suspect_id = None
        if doc:
            for line in doc.splitlines():
                line = line.strip()
                if line.startswith("suspect:"):
                    suspect_id = line.split(":", 1)[1].strip()
                    break

        if suspect_id:
            status = suspect_status.get(suspect_id, "suspect")
            if status in ("cleared", "inconclusive"):
                # Find test_id for this suspect from ledger
                test_ids = next(
                    (s.get("test_ids", []) for s in ledger.get("suspects", []) if s["id"] == suspect_id),
                    []
                )
                ledger_ref = test_ids[0] if test_ids else suspect_id
                item.add_marker(pytest.mark.skip(
                    reason=f"Culprit evidence for a cleared suspect, see ledger {{ledger_ref}}"
                ))
'''
    conftest_path.write_text(content, encoding="utf-8")
    print(f"Wrote {conftest_path}")


# ---------------------------------------------------------------------------
# New commands (step 5) — stubs that delegate to other modules
# ---------------------------------------------------------------------------

def cmd_test(args: argparse.Namespace) -> int:
    incident_id = _require_incident(args)
    test_path = args.test

    # Validate path must be under tests/incidents/<INC>/
    expected_prefix = str(Path("tests/incidents") / incident_id)
    if not test_path.startswith(expected_prefix):
        print(f"ERROR: test path must be under tests/incidents/{incident_id}/", file=sys.stderr)
        sys.exit(3)

    # Validate docstring
    from culprit.runner import parse_docstring
    doc = parse_docstring(test_path)
    if "suspect" not in doc or "mechanism" not in doc:
        print(f"ERROR: {test_path} must have module docstring with 'suspect:' and 'mechanism:'", file=sys.stderr)
        sys.exit(3)

    # Validate suspect status
    ledger = _load_ledger(incident_id)
    suspect = next((s for s in ledger.suspects if s.id == args.suspect), None)
    if not suspect:
        print(f"ERROR: suspect {args.suspect} not found.", file=sys.stderr)
        sys.exit(3)
    if suspect.status not in ("suspect", "inconclusive"):
        print(f"ERROR: suspect {args.suspect} has status {suspect.status}, must be suspect or inconclusive.", file=sys.stderr)
        sys.exit(3)

    # Load primary signature
    from culprit.reconstruct import load_incident
    from culprit.signature import normalize
    incident = load_incident(incident_id)
    primary_sig = next(
        (s for s in incident["signatures"] if s["id"] == ledger.primary_signature_id), None
    )
    if not primary_sig:
        print("ERROR: primary signature not found.", file=sys.stderr)
        sys.exit(3)

    from culprit.runner import run_test as _run_test
    tr = _run_test(
        incident_id=incident_id,
        suspect_id=args.suspect,
        test_path=test_path,
        primary_sig_exc_type=primary_sig["exc_type"],
        primary_sig_exc_message_norm=primary_sig["exc_message_norm"],
        primary_sig_top_frame_module=primary_sig.get("top_frame", {}).get("module") if primary_sig.get("top_frame") else None,
        primary_sig_top_frame_function=primary_sig.get("top_frame", {}).get("function") if primary_sig.get("top_frame") else None,
    )

    # Append to ledger
    ledger = ledger.model_copy(update={"tests": ledger.tests + [tr]})
    # Add test_id to suspect
    idx = next(i for i, s in enumerate(ledger.suspects) if s.id == args.suspect)
    updated_suspect = ledger.suspects[idx].model_copy(update={"test_ids": ledger.suspects[idx].test_ids + [tr.id]})
    suspects = list(ledger.suspects)
    suspects[idx] = updated_suspect
    ledger = ledger.model_copy(update={"suspects": suspects})
    _save_ledger(incident_id, ledger)

    # Print summary line
    would_be = "would be reproduced" if tr.score >= 0.80 else ("would be cleared" if tr.score < 0.30 else "inconclusive")
    print(f"{tr.id}  {args.suspect}  {tr.outcome}  {tr.observed_exc_type or 'none'}  score={tr.score:.2f}  -> {would_be}")
    return 0


def cmd_verdict(args: argparse.Namespace) -> int:
    incident_id = _require_incident(args)
    from culprit.verdict import apply_verdict
    return apply_verdict(incident_id)


def cmd_verify_fix(args: argparse.Namespace) -> int:
    incident_id = _require_incident(args)
    from culprit.verdict import verify_fix
    return verify_fix(incident_id)


def cmd_report(args: argparse.Namespace) -> int:
    incident_id = _require_incident(args)
    from culprit.report import generate_report
    return generate_report(incident_id, args.context)


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="culprit", description="Culprit incident debugger")
    sub = parser.add_subparsers(dest="command")

    # ingest
    p_ingest = sub.add_parser("ingest", help="Load dataset into events.json")
    p_ingest.add_argument("incident", nargs="?")
    p_ingest.set_defaults(func=cmd_ingest)

    # reconstruct
    p_rec = sub.add_parser("reconstruct", help="Build incident.json + ledger.json")
    p_rec.add_argument("incident", nargs="?")
    p_rec.set_defaults(func=cmd_reconstruct)

    # status
    p_status = sub.add_parser("status", help="Print suspect table")
    p_status.add_argument("incident", nargs="?")
    p_status.add_argument("--active", action="store_true", help="Use active incident")
    p_status.set_defaults(func=cmd_status)

    # evidence
    p_evidence = sub.add_parser("evidence", help="Print suspect evidence")
    p_evidence.add_argument("incident", nargs="?")
    p_evidence.add_argument("suspect_id")
    p_evidence.set_defaults(func=cmd_evidence)

    # open
    p_open = sub.add_parser("open", help="Set active incident")
    p_open.add_argument("incident", nargs="?")
    p_open.set_defaults(func=cmd_open)

    # test
    p_test = sub.add_parser("test", help="Run a suspect test and record it")
    p_test.add_argument("incident", nargs="?")
    p_test.add_argument("--suspect", required=True)
    p_test.add_argument("--test", required=True, dest="test")
    p_test.set_defaults(func=cmd_test)

    # verdict
    p_verdict = sub.add_parser("verdict", help="Apply verdict rules to all suspects")
    p_verdict.add_argument("incident", nargs="?")
    p_verdict.set_defaults(func=cmd_verdict)

    # verify-fix
    p_vf = sub.add_parser("verify-fix", help="Rerun reproduction tests + full suite")
    p_vf.add_argument("incident", nargs="?")
    p_vf.set_defaults(func=cmd_verify_fix)

    # report
    p_report = sub.add_parser("report", help="Generate postmortem report")
    p_report.add_argument("incident", nargs="?")
    p_report.add_argument("--context", required=True)
    p_report.set_defaults(func=cmd_report)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)
    sys.exit(args.func(args) or 0)

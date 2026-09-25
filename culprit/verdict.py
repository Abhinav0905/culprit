"""Verdict rules: apply test results to suspects and record transitions."""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from culprit.models import Ledger, Suspect, Transition
from culprit.reconstruct import load_ledger, load_incident, save_ledger

_STATE_ROOT = Path(".culprit")

REPRODUCE_SCORE_THRESHOLD = 0.80
CLEAR_SCORE_THRESHOLD = 0.30
ACTOR = os.environ.get("CULPRIT_ACTOR", "culprit-cli")


def _modules_for_suspect(suspect: Suspect, incident_id: str) -> set[str]:
    """Return the set of module names in the suspect's scope."""
    if suspect.kind in ("code", "resource"):
        return {suspect.module} if suspect.module else set()
    # change suspect: derive from change files
    if suspect.change_id:
        from culprit.ingest import load_changes
        changes = load_changes(incident_id)
        for ch in changes:
            if ch["id"] == suspect.change_id:
                modules = set()
                for f in ch.get("files", []):
                    # brightcart/orders/address.py → brightcart.orders.address
                    import re
                    m = re.search(r"brightcart[/\\](.+)\.py$", f)
                    if m:
                        modules.add("brightcart." + m.group(1).replace("/", ".").replace("\\", "."))
                return modules
    return set()


def apply_verdict(incident_id: str) -> int:
    """Apply verdict rules to all suspects with test runs. Write updated ledger."""
    ledger = load_ledger(incident_id)
    incident = load_incident(incident_id)

    # Index primary signature
    primary_sig = next(
        (s for s in incident["signatures"] if s["id"] == ledger.primary_signature_id),
        None,
    )

    transitions: list[Transition] = []

    for suspect in ledger.suspects:
        if suspect.status not in ("suspect", "inconclusive"):
            continue
        runs = [t for t in ledger.tests if t.suspect_id == suspect.id]
        if not runs:
            continue

        scope_modules = _modules_for_suspect(suspect, incident_id)
        test_ids = [r.id for r in runs]

        # Scope check for failing/erroring runs
        in_scope_runs = []
        out_of_scope_reason: str | None = None
        for run in runs:
            if run.outcome in ("failed", "error"):
                # Check if observed frames include a scope module
                obs_modules = {f.module for f in run.observed_frames}
                if scope_modules and not (obs_modules & scope_modules):
                    # Out of scope
                    out_of_scope_reason = (
                        f"Test failure came from {', '.join(sorted(obs_modules - scope_modules)[:2])}, "
                        f"outside suspect scope."
                    )
                else:
                    in_scope_runs.append(run)
            else:
                in_scope_runs.append(run)

        # Determine new status
        new_status: str | None = None
        reason = ""

        reproduced = [r for r in in_scope_runs if r.outcome in ("failed", "error") and r.score >= REPRODUCE_SCORE_THRESHOLD]
        if reproduced:
            new_status = "reproduced"
            best = max(reproduced, key=lambda r: r.score)
            exc = best.observed_exc_type or "error"
            frame = ""
            if best.observed_frames:
                f = best.observed_frames[-1]
                frame = f" in {f.function}"
            reason = f"{best.id} fails with the same {exc}{frame} (score {best.score:.2f})."
        elif out_of_scope_reason and not in_scope_runs:
            new_status = "inconclusive"
            reason = out_of_scope_reason
        else:
            all_passed_or_low = all(
                r.outcome == "passed" or r.score < CLEAR_SCORE_THRESHOLD
                for r in in_scope_runs
            )
            if all_passed_or_low:
                new_status = "cleared"
                for r in in_scope_runs:
                    if r.outcome == "passed":
                        reason = f"{r.id} ran and did not produce the incident error."
                    elif r.score < CLEAR_SCORE_THRESHOLD:
                        exc = r.observed_exc_type or "unknown error"
                        reason = f"{r.id} produced {exc}, not the incident error (score {r.score:.2f})."
                if not reason:
                    reason = "All tests passed or scored below threshold."
            else:
                new_status = "inconclusive"
                reason = "Some runs did not clearly reproduce or clear the suspect."

        if new_status and new_status != suspect.status:
            trans = Transition(
                ts=datetime.now(timezone.utc),
                suspect_id=suspect.id,
                from_status=suspect.status,
                to_status=new_status,
                test_ids=test_ids,
                evidence_ids=suspect.evidence_ids,
                actor=ACTOR,
                reason=reason,
            )
            transitions.append(trans)
            # Update suspect in ledger
            idx = next(i for i, s in enumerate(ledger.suspects) if s.id == suspect.id)
            ledger.suspects[idx] = suspect.model_copy(update={
                "status": new_status,
                "verdict_reason": reason,
            })

    ledger = ledger.model_copy(update={
        "history": ledger.history + transitions,
    })
    save_ledger(incident_id, ledger)

    # Print table
    print(f"{incident_id}  primary signature {ledger.primary_signature_id}: "
          f"{primary_sig['exc_type'] if primary_sig else '?'} in "
          f"{primary_sig['top_frame']['module'] if primary_sig and primary_sig.get('top_frame') else '?'}")
    print(f"{'ID':<4} {'PRIOR':<6} {'SUSPECT':<45} {'STATUS':<12} EVIDENCE")
    for s in ledger.suspects:
        test_summary = ""
        runs = [t for t in ledger.tests if t.suspect_id == s.id]
        if runs:
            best = max(runs, key=lambda r: r.score)
            if best.outcome == "passed":
                test_summary = f"{best.id} passed"
            else:
                test_summary = f"{best.id} score {best.score:.2f}"
        print(f"{s.id:<4} {s.prior:<6.2f} {s.title[:44]:<45} {s.status:<12} {test_summary}")
    return 0


def verify_fix(incident_id: str) -> int:
    """Rerun reproduction tests + full suite. If both pass, mark suspect fixed."""
    ledger = load_ledger(incident_id)
    reproduced = [s for s in ledger.suspects if s.status == "reproduced"]
    if not reproduced:
        print("No reproduced suspects to verify.")
        return 0

    all_ok = True
    for suspect in reproduced:
        repro_tests = [t for t in ledger.tests if t.suspect_id == suspect.id
                       and t.outcome in ("failed", "error")]
        if not repro_tests:
            print(f"{suspect.id}: no reproduction test found.")
            continue

        best = max(repro_tests, key=lambda r: r.score)
        print(f"Rerunning {best.path} for {suspect.id}...")
        result = subprocess.run(
            [".venv/bin/python", "-m", "pytest", best.path, "-q"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(f"  FAIL: reproduction test still fails.\n{result.stdout}")
            all_ok = False
            continue

        print(f"  Reproduction test passes. Running full suite...")
        full_result = subprocess.run(
            [".venv/bin/python", "-m", "pytest", "-q"],
            capture_output=True, text=True,
        )
        if full_result.returncode != 0:
            print(f"  FAIL: full suite fails.\n{full_result.stdout[-500:]}")
            all_ok = False
            continue

        # Move to fixed
        import subprocess as sp
        commit = sp.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        idx = next(i for i, s in enumerate(ledger.suspects) if s.id == suspect.id)
        ledger.suspects[idx] = suspect.model_copy(update={"status": "fixed"})
        trans = Transition(
            ts=datetime.now(timezone.utc),
            suspect_id=suspect.id,
            from_status="reproduced",
            to_status="fixed",
            test_ids=[best.id],
            evidence_ids=suspect.evidence_ids,
            actor=ACTOR,
            reason=f"Reproduction test passes and full suite green at {commit[:8]}.",
        )
        ledger = ledger.model_copy(update={"history": ledger.history + [trans]})
        print(f"  {suspect.id} marked fixed.")

    save_ledger(incident_id, ledger)
    return 0 if all_ok else 1

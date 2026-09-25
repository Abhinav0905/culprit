# Culprit build plan

## Files to create, by step

### Step 2 – Brightcart sample app
- `pyproject.toml`
- `brightcart/__init__.py`
- `brightcart/common/clock.py`
- `brightcart/common/flags.py`
- `brightcart/common/logging.py`
- `brightcart/gateway/app.py`
- `brightcart/orders/app.py`
- `brightcart/orders/address.py`  ← planted bug behind `LABEL_ASCII_FASTPATH`
- `brightcart/orders/labels.py`
- `brightcart/orders/db.py`
- `brightcart/payments/app.py`
- `brightcart/payments/retry.py`
- `brightcart/tests/test_checkout.py`
- `.bobignore`

### Step 3 – INC-001 dataset
- `brightcart/loadgen.py`
- `datasets/incidents/INC-001/logs/gateway.jsonl`
- `datasets/incidents/INC-001/logs/orders.jsonl`
- `datasets/incidents/INC-001/logs/payments.jsonl`
- `datasets/incidents/INC-001/metrics.jsonl`
- `datasets/incidents/INC-001/changes.json`
- `datasets/incidents/INC-001/architecture.json`
- `datasets/incidents/INC-001/meta.json`

### Step 4 – Culprit ingest and reconstruction
- `culprit/__init__.py`
- `culprit/__main__.py`
- `culprit/models.py`
- `culprit/ingest.py`
- `culprit/reconstruct.py`
- `culprit/signature.py`  (normalize + grouping only)
- `culprit/cli.py`  (ingest, reconstruct, status, evidence, open)
- `culprit/tests/test_models.py`
- `culprit/tests/test_reconstruct.py`  ← checks S1/S2/S3 priors

### Step 5 – Test runner, scoring and verdicts
- `culprit/runner.py`
- `culprit/verdict.py`
- `culprit/tests/test_runner.py`
- `culprit/tests/test_signature.py`
- `culprit/tests/test_verdict.py`
- `culprit/tests/fixtures/test_unicode_fail.py`
- `culprit/tests/fixtures/test_pass.py`
- `culprit/tests/fixtures/test_other_error.py`
- CLI commands: `test`, `verdict`, `verify-fix`
- `pyproject.toml` updated: `testpaths`, `norecursedirs`

### Step 6 – Bob pack and guard hook
- `culprit/guard.py`
- `culprit/tests/test_guard.py`
- `.bob/custom_modes.yaml`
- `.bob/settings.json`
- `.bob/commands/investigate.md`
- `.bob/commands/fix.md`
- `.bob/commands/postmortem.md`
- `.bob/skills/reproduce-suspect/SKILL.md`
- `.bob/skills/write-postmortem/SKILL.md`
- `.bob/rules-culprit-investigator/01-evidence.md`

### Step 7 – Investigate (Culprit Investigator mode)
- `tests/incidents/INC-001/conftest.py`  (written by `culprit open`)
- `tests/incidents/INC-001/test_s1_payments_jitter.py`
- `tests/incidents/INC-001/test_s2_label_unicode.py`
- `tests/incidents/INC-001/test_s3_pool_saturation.py`
- `.culprit/INC-001/ledger.json`  (updated by CLI)

### Step 8 – Fix (Culprit Fixer mode)
- `brightcart/orders/address.py`  (Unicode-safe `to_label_line`)
- `brightcart/tests/test_checkout_unicode.py`

### Step 9 – Postmortem report
- `culprit/report.py`
- `culprit/tests/test_report.py`
- CLI command: `report`
- `reports/INC-001-context.json`
- `reports/INC-001-postmortem.docx`
- `viewer/data/INC-001.json`
- `docs/runbook-changes/INC-001.md`

### Step 10 – Replay viewer
- `viewer/index.html`
- `viewer/app.js`
- `viewer/styles.css`

### Step 11 – README
- `README.md`  (rewritten)

---

## Python packages

| Package | Purpose |
|---|---|
| `fastapi` | Brightcart service endpoints |
| `httpx` | In-process inter-service calls (`ASGITransport`) |
| `pydantic` v2 | All Culprit data models |
| `pytest` | Test runner; also used by `culprit test` |
| `docxtpl` | Render the postmortem Word template |
| `python-docx` | Read existing postmortem `.docx` files |
| `pypdf` | Read the on-call runbook PDF |

No other third-party packages. Standard library covers JSON, argparse, subprocess, and XML.

---

## Three biggest demo risks

### Risk 1 – Wrong reconstruction order breaks the whole demo
**What could go wrong:** If S1/S2/S3 priors come out different from spec (e.g. S1=0.65, S2=0.60, S3=0.25), every downstream step breaks — the guard test IDs are wrong, the investigator addresses the wrong suspect, and the postmortem is incorrect.
**Mitigation:** Step 4 includes a dedicated unit test that asserts the exact prior and title for all three suspects. The dataset seed is fixed at 7. `reconstruct.py` exposes all thresholds as named module-level constants so they are easy to tune without touching logic.

### Risk 2 – Guard hook misreads the tool-call payload and lets edits through
**What could go wrong:** Bob's `PreToolUse` payload field names are not publicly documented. If `guard.py` reads the wrong field, it allows every edit, and the demo's key proof-point (blocked edit before reproduction) is invisible.
**Mitigation:** `guard.py` logs every raw payload to `.culprit/hook-payloads.log`. It tries six known field name variants for the path and four for the tool name, then falls back to walking all nested string values for a repo-relative path. Step 6 ships a unit test for each case. The spec's recovery prompt (show last log entry, update guard, retest) handles any remaining mismatch live.

### Risk 3 – Investigator subagents produce inconclusive verdicts, stopping the demo
**What could go wrong:** A subagent writes a test that exercises the wrong code path, scores below 0.80, and `culprit verdict` returns `inconclusive` for S2. The `/fix` command cannot run without a reproduced suspect.
**Mitigation:** The `reproduce-suspect` skill gives concrete, step-by-step guidance with an exact example (Austrian address containing ß + `LABEL_ASCII_FASTPATH=on`). The scope check in `verdict.py` catches out-of-scope failures early with a named reason. If a suspect comes back inconclusive, BOB_TASKS step 7 already provides a recovery prompt to rewrite the test.

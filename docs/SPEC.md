# Culprit specification

Version 1.0 for the IBM Bob 2.0 hackathon (Sept 25 to 27, 2026). Bob builds everything in this file. Section numbers are referenced from `docs/BOB_TASKS.md`.

## 1. The product

**Workflow improved:** debugging a production incident, from the alert to a verified fix.

**Problem.** At 2 AM an on-call engineer has an error spike, a pile of log lines and a list of recent deploys. The usual move is to roll back the most recent deploy, or to trust whatever root cause a tool states with confidence. When that guess is wrong, the team loses an hour on the wrong lead and sometimes rolls back a healthy service. PagerDuty's 2024 survey of 500 IT leaders put the average incident at about 175 minutes to resolve.

**Solution.** Culprit turns the incident into a lineup of suspects and makes Bob test every one of them in parallel:

1. `culprit reconstruct` reads the logs, metrics and deploy history, and lists every plausible cause as a suspect. Nothing is a verdict yet.
2. The Investigator mode spawns one Bob subagent per suspect. Each subagent writes one test that tries to reproduce the exact error seen in the logs.
3. The `culprit` CLI runs each test itself and compares the result with the logged error signature. A matching failure makes a suspect **reproduced**. A test that exercises the suspected mechanism without producing the logged error makes it **cleared**. Bob cannot mark its own homework: only the CLI writes the ledger, and a hook blocks direct edits to it.
4. A hook blocks any change to application code until a suspect is reproduced.
5. The Fixer mode makes the smallest fix. The reproduction test must now pass along with the full suite, and it stays in the repo as the regression test.
6. Bob reads the team's postmortem template, on-call runbook and past postmortems (Word and PDF), finds that this incident repeats an earlier one whose action item was never closed, points out the runbook step that would have rolled back the wrong service, and writes the postmortem in the team's own template.

**Rule:** no verdict without a test.

## 2. Scope

In scope: one sample app (Brightcart), one fully worked incident (INC-001), the Culprit CLI, the Bob pack, the postmortem report, and a static replay viewer.

Out of scope: real telemetry connectors, authentication, multi-tenant hosting, video rendering, more than one incident type in the demo. If Bobcoins remain at the end, INC-002 (section 12) is a stretch goal.

## 3. Brightcart, the sample app

Brightcart is a small fictional online store. Three FastAPI services live in one repo and call each other in-process through `httpx.ASGITransport`, so tests and data generation never need a network.

```text
brightcart/
├── VERSION.json          {"gateway": "1.4.0", "orders": "2.2.4", "payments": "1.8.1"}
├── common/
│   ├── clock.py          now() returns simulated time when set, real UTC otherwise
│   ├── flags.py          feature flags from env vars or an override dict
│   └── logging.py        JSON-lines logger (fields in section 3.2)
├── gateway/app.py        POST /checkout
├── orders/
│   ├── app.py            POST /orders
│   ├── address.py        normalize_address(), to_label_line()
│   ├── labels.py         build_label()
│   └── db.py             simulated connection pool
├── payments/
│   ├── app.py            POST /charges
│   └── retry.py          call_provider() with retry and jitter
├── loadgen.py            scenario runner that writes datasets (section 4)
└── tests/                happy-path tests, ASCII addresses only
```

### 3.1 Behaviour

- **gateway** `POST /checkout` takes `{customer_id, items: [{sku, qty}], address: {street, city, postal_code, country}, payment: {amount_cents, currency, card_token}}`, calls orders `POST /orders`, and returns `{order_id, status}`. On an upstream 5xx it retries once, then logs `checkout_failed` at ERROR with `upstream="orders"` and `status=<code>` and returns 502.
- **orders** `POST /orders` takes a connection from `db.pool` for the whole request (like a per-request ORM session), calls `address.normalize_address()`, then `labels.build_label()`, then payments `POST /charges`, and returns 201. The connection is released in a `finally` block. Any exception is caught at the endpoint, logged as `order_failed` at ERROR with exception fields, and returned as 500.
- **orders/address.py**
  - `normalize_address(addr) -> NormalizedAddress` trims, collapses spaces, uppercases the country code and validates the postal code.
  - `to_label_line(addr: NormalizedAddress) -> str` builds `"STREET, POSTAL CITY, COUNTRY"` for the label printer.
  - **The planted bug.** orders v2.3.0 adds a "print-ready label" fast path behind the flag `LABEL_ASCII_FASTPATH`. When the flag is on, `to_label_line()` ends with `line.encode("ascii").decode("ascii")` for a legacy printer. Any non-ASCII character (ß, ä, ö, ü) raises `UnicodeEncodeError`. With the flag off the function returns the Unicode line unchanged.
  - Call chain when it fails: `brightcart.orders.app.create_order` → `brightcart.orders.labels.build_label` → `brightcart.orders.address.to_label_line`.
- **orders/db.py** is a simulated pool (size 20). `acquire(timeout_s=2.0)` raises `PoolTimeoutError("pool timeout after 2.0s: size=20 in_use=20")` when exhausted. The pool logs `db_pool_high` at WARN when usage is above 90%.
- **payments** `POST /charges` validates amount, currency and token, calls `retry.call_provider()` (a deterministic fake provider) and returns 201 with `{charge_id}`. payments v1.8.2 changes `retry.JITTER_MS` from 50 to 120. That change is harmless apart from slightly higher latency.
- **tests/** cover the happy paths with ASCII-only addresses. This gap is deliberate: it matches an open action item in the July postmortem (section 9).

### 3.2 Log format

One JSON object per line. Required fields: `ts` (ISO 8601 UTC with milliseconds), `service`, `level` (`INFO`, `WARN`, `ERROR`), `logger`, `event`, `msg`. Exception logs add `exc_type`, `exc_message` and `frames` (a list of `{module, function, line}` for `brightcart.*` frames only, innermost last). Request logs add `trace_id` and `order_id` when known.

Addresses are never logged in full. Failure logs include only `field` (for example `"street"`) and `country`.

Example ERROR from orders:

```json
{"ts": "2026-09-24T09:07:12.418Z", "service": "orders", "level": "ERROR", "logger": "brightcart.orders.app", "event": "order_failed", "msg": "order creation failed", "trace_id": "tr-000412", "order_id": "ord-000412", "field": "street", "country": "AT", "exc_type": "UnicodeEncodeError", "exc_message": "'ascii' codec can't encode character '\\xdf' in position 10: ordinal not in range(128)", "frames": [{"module": "brightcart.orders.app", "function": "create_order", "line": 58}, {"module": "brightcart.orders.labels", "function": "build_label", "line": 21}, {"module": "brightcart.orders.address", "function": "to_label_line", "line": 44}]}
```

Example ERROR from gateway:

```json
{"ts": "2026-09-24T09:07:12.431Z", "service": "gateway", "level": "ERROR", "logger": "brightcart.gateway.app", "event": "checkout_failed", "msg": "checkout failed", "trace_id": "tr-000412", "upstream": "orders", "status": 500}
```

## 4. INC-001 scenario and dataset

`python -m brightcart.loadgen --scenario inc-001 --out datasets/incidents/INC-001` runs about 1,800 simulated checkouts through the gateway between 08:40 and 09:40 UTC on 2026-09-24 (about one every two seconds of simulated time). The random seed is 7, so the output is identical on every run.

| Simulated time (UTC) | What happens |
| --- | --- |
| 08:40 | Baseline. orders 2.2.4, payments 1.8.1, flag off. All addresses ASCII. |
| 08:55 | **C1**: orders 2.2.4 → 2.3.0, "Print-ready shipping labels (ASCII fast path for legacy label printer)". Files: `brightcart/orders/address.py`, `brightcart/orders/labels.py`. Flag turns on. |
| 09:03 | **C2**: payments 1.8.1 → 1.8.2, "Increase retry jitter from 50 ms to 120 ms". File: `brightcart/payments/retry.py`. |
| 09:04 to 09:11 | payments p95 latency rises from about 300 ms to about 420 ms. payments logs `latency_high` at WARN once a minute while p95 is over 400 ms. |
| 09:06 | A marketing campaign starts in Germany and Austria. The DE/AT share of checkouts rises from 3% to 20%, and 40% of those addresses contain ß, ä, ö or ü (so about 8% of all checkouts). Before 09:06 every generated address is ASCII. |
| ~09:07 | First orders `order_failed` (UnicodeEncodeError). Gateway starts logging `checkout_failed`. About 8% of all checkouts fail from here on. |
| 09:07 onward | The gateway retries each failed orders call once, which adds load on orders. loadgen models `db_pool_usage_pct` from request volume: about 60% at baseline, rising as retries add up. |
| 09:10 | orders DB pool usage goes above 90%. orders logs `db_pool_high` at WARN (logger `brightcart.orders.db`). |
| 09:12 | The alert fires (checkout 5xx above 2% for 5 minutes). |
| 09:40 | End of the window. The bug is still live. |

Files written to `datasets/incidents/INC-001/`:

- `logs/gateway.jsonl`, `logs/orders.jsonl`, `logs/payments.jsonl`
- `metrics.jsonl`: one line per minute per metric: `{"ts", "service", "name", "value"}`. Names: `p95_latency_ms` (payments), `db_pool_usage_pct` (orders), `error_rate_pct` (gateway), `country_share_dach_pct` (gateway).
- `changes.json`: `[{"id": "C1", "ts", "service", "from_version", "to_version", "summary", "files": [...], "flags": {"LABEL_ASCII_FASTPATH": true}, "commit"}, {"id": "C2", ...}]`. `flags` lists feature flags the change turned on or off (empty for C2).
- `architecture.json`: `{"services": [{"name": "gateway", "depends_on": ["orders"], "user_facing": true}, {"name": "orders", "depends_on": ["payments", "orders-db"]}, {"name": "payments", "depends_on": []}, {"name": "orders-db", "kind": "datastore", "depends_on": []}]}`
- `meta.json`: `{"incident_id": "INC-001", "title": "Checkout failures after the DACH campaign launch", "alert_at": "2026-09-24T09:12:00Z", "window": {"start": "2026-09-24T08:40:00Z", "end": "2026-09-24T09:40:00Z"}, "incident_commit": "<git rev-parse HEAD at generation time>", "seed": 7}`

The commit recorded as `incident_commit` must contain the bug. Commit the dataset right after generating it.

## 5. Culprit: data model and reconstruction

### 5.1 Package layout

```text
culprit/
├── __main__.py      python -m culprit <command>
├── cli.py           argparse commands: ingest, reconstruct, status, evidence, test, verdict, verify-fix, report, open
├── models.py        pydantic models (5.2)
├── ingest.py        dataset -> events.json
├── reconstruct.py   events -> incident.json + ledger.json (5.3)
├── signature.py     error fingerprints and matching (6.2)
├── runner.py        runs one pytest file, parses JUnit XML (6.1)
├── verdict.py       verdict rules and transitions (6.3)
├── guard.py         Bob PreToolUse hook (7)
├── report.py        postmortem .docx and viewer JSON (9)
└── tests/           unit tests for every module
```

State lives in `.culprit/<INC>/`: `events.json`, `incident.json`, `ledger.json`, `junit/<test-run-id>.xml`. `.culprit/ACTIVE` holds the id of the open incident.

### 5.2 Models (pydantic v2)

```python
class Frame(BaseModel):
    module: str
    function: str
    line: int | None = None

class Event(BaseModel):
    id: str                                  # "E00001", in time order
    ts: datetime
    service: str
    kind: Literal["log", "metric", "change"]
    level: Literal["INFO", "WARN", "ERROR"] | None = None
    name: str                                # log event name, metric name, or change id
    message: str
    exc_type: str | None = None
    exc_message: str | None = None
    frames: list[Frame] = []
    attrs: dict[str, Any] = {}

class Signature(BaseModel):                  # an error fingerprint seen in the logs
    id: str                                  # "SIG1"
    service: str
    exc_type: str
    exc_message_norm: str
    top_frame: Frame | None                  # innermost brightcart frame
    count: int
    first_seen: datetime
    example_event_ids: list[str]

class Suspect(BaseModel):
    id: str                                  # "S1", ranked by prior
    kind: Literal["code", "change", "resource"]
    title: str
    service: str
    module: str | None = None
    function: str | None = None
    change_id: str | None = None
    prior: float                             # 0..1, how suspicious before any test
    rationale: str
    evidence_ids: list[str]
    status: Literal["suspect", "reproduced", "cleared", "inconclusive", "fixed"] = "suspect"
    verdict_reason: str | None = None
    test_ids: list[str] = []

class TestRun(BaseModel):
    id: str                                  # "T1"
    suspect_id: str
    path: str
    commit: str
    outcome: Literal["failed", "error", "passed", "not_collected"]
    observed_exc_type: str | None = None
    observed_exc_message: str | None = None
    observed_frames: list[Frame] = []
    signature_id: str
    score: float                             # 0..1, see 6.2
    mechanism: str                           # from the test's docstring
    duration_s: float
    ran_at: datetime

class Transition(BaseModel):
    ts: datetime
    suspect_id: str
    from_status: str
    to_status: str
    test_ids: list[str]
    evidence_ids: list[str]
    actor: str                               # env CULPRIT_ACTOR, default "culprit-cli"
    reason: str

class Ledger(BaseModel):
    incident_id: str
    primary_signature_id: str
    suspects: list[Suspect]
    tests: list[TestRun] = []
    history: list[Transition] = []
```

`incident.json` holds: `id`, `title`, `window`, `alert_at`, `origin_service`, `affected_services`, `first_error_at`, `error_rate_peak_pct`, `failed_checkouts`, `signatures`, `timeline` (list of `{ts, label, kind, evidence_ids}`), and `missing_evidence` (list of strings).

### 5.3 Reconstruction rules

All rules are deterministic and live as named constants at the top of `reconstruct.py`.

1. **Load.** Read logs, metrics and changes. Sort by time and assign ids `E00001`, `E00002`, and so on.
2. **Signatures.** Group ERROR logs that have `exc_type` by `(service, exc_type, normalize(exc_message), top_frame)`. Gateway `checkout_failed` events carry no exception. They are propagation evidence attributed to their `upstream` service, not signatures.
3. **Origin.** The service with the earliest signature, following `upstream` attribution. The primary signature is the one with the highest count at the origin.
4. **Suspects.**
   - *Code suspect* from the primary signature's top frame: title ``"`<module>.<function>` raises <exc_type> on some inputs"``, prior 0.45.
   - *Change suspects*: every change in the 30 minutes before the first error. Prior 0.60 if it landed 5 minutes or less before, 0.45 if 15 or less, 0.30 if 30 or less. Add 0.10 if the change is on the origin service. Add 0.05 if the changed service logged WARN events between the change and the first error.
   - *Merge rule*: if a change's `files` include the code suspect's module file, merge that change into the code suspect instead of listing it separately. Add 0.15 to the code suspect's prior (cap 0.95), attach the change id and evidence, and say "introduced by C1 (orders 2.3.0)" in the rationale.
   - *Resource suspects*: saturation warnings on the origin service inside the window (`db_pool_high`, `queue_depth_high`, `memory_high`, `cpu_high`). The suspect's `module` is the logger of those warnings (for the pool, `brightcart.orders.db`). Prior 0.40 if the first warning came before the first error. Prior 0.25 if it came after, with the rationale noting that it started after the first error and may be a consequence.
   - Sort by prior, highest first, and number them S1, S2, S3.
5. **Timeline.** Changes, the start of each WARN series, metric shifts larger than 3x (for example `country_share_dach_pct`), the first error per service, and the alert.
6. **Missing evidence.** List what the data cannot show, for example: no distributed traces (gateway-to-orders linkage comes from `upstream` and `trace_id` only), no label-printer logs, no payments error logs in the window.

Expected result for INC-001. Tests in `culprit/tests/` must check it:

| ID | Kind | Title | Prior |
| --- | --- | --- | --- |
| S1 | change | payments 1.8.2 deploy (C2), 4 minutes before the first error, p95 latency rose after it | 0.65 |
| S2 | code | `brightcart.orders.address.to_label_line` raises UnicodeEncodeError on some inputs, introduced by C1 (orders 2.3.0) | 0.60 |
| S3 | resource | orders DB pool saturation (started after the first error, may be a consequence) | 0.25 |

The most suspicious-looking suspect (S1) is innocent. That is the point of the demo.

### 5.4 `culprit evidence INC S2`

Prints the suspect as JSON, the change records linked to it (including any feature flags they turned on), and at most 10 supporting events, one per line, trimmed to the fields that matter. Subagents call this instead of reading raw logs, which keeps Bobcoin use low. Add `datasets/**/logs/*.jsonl` to `.bobignore`.

## 6. Testing suspects and verdicts

### 6.1 `culprit test INC --suspect S2 --test tests/incidents/INC-001/test_s2_label_unicode.py`

1. The path must be under `tests/incidents/<INC>/`. The suspect must be in `suspect` or `inconclusive` status.
2. The test file's module docstring must contain `suspect: <ID>` and `mechanism: <one sentence>`. An `evidence:` line with event ids is optional. If the docstring is missing, exit 3 with a clear message.
3. Run `python -m pytest <path> -q -p no:cacheprovider --junitxml=.culprit/<INC>/junit/<run-id>.xml` with a 120-second timeout, and with `CULPRIT_INCIDENT=<INC>` and `CULPRIT_RUN_EVIDENCE=1` set (see 6.5).
4. Parse the JUnit XML. For failures and errors, take the exception type and message from the last `ExcType: message` line, and the frames from traceback lines such as `File ".../brightcart/orders/address.py", line 44, in to_label_line`, converting file paths to dotted module names.
5. Score the run against the incident's primary signature (6.2), append a `TestRun` to the ledger, and print one line, for example: `T2  S2  failed  UnicodeEncodeError  score=1.00  -> would be reproduced`. This command does not change suspect status.

### 6.2 Signature matching (`signature.py`)

```text
normalize(msg): lowercase; replace quoted substrings with <q>; replace \xNN and \uNNNN escapes with <ch>;
                replace digit runs with <n>; collapse whitespace
score = 0.5  if observed exc_type == logged exc_type
      + 0.3 * SequenceMatcher(normalize(observed), normalize(logged)).ratio()
      + 0.2  if the logged top frame (module, function) appears in the observed frames
score = 0.0  if the test passed
```

### 6.3 `culprit verdict INC`

For each suspect in `suspect` or `inconclusive` status that has at least one test run:

- **Scope check first.** A failing run only counts for a suspect if the observed frames include a module in that suspect's scope: its `module` for code and resource suspects, or a module from the change's `files` for change suspects. This stops one suspect's test from "reproducing" another suspect's bug, for example an end-to-end checkout test for the payments deploy that actually crashes in the address code. A failing run outside the scope makes the suspect inconclusive, and the reason names the module the failure came from.
- **reproduced**: any in-scope run failed or errored with score ≥ 0.80. Reason: "T2 fails with the same UnicodeEncodeError in to_label_line (score 1.00)."
- **cleared**: every run passed, or scored below 0.30. Reasons: "T1 ran payments 1.8.2 with the failing orders' payloads and did not produce the incident error." or "T3 produced PoolTimeoutError, not UnicodeEncodeError (score 0.12)."
- **inconclusive**: anything else.

Record every change as a `Transition` with its test ids and evidence ids. Before writing, validate that every referenced id exists. Then print the table:

```text
INC-001  primary signature SIG1: UnicodeEncodeError in brightcart.orders.address.to_label_line
ID  PRIOR  SUSPECT                                    STATUS      EVIDENCE
S1  0.65   payments 1.8.2 deploy (C2)                 cleared     T1 passed
S2  0.60   to_label_line UnicodeEncodeError (C1)      reproduced  T2 score 1.00
S3  0.25   orders DB pool saturation                  cleared     T3 score 0.12
```

The wording is careful on purpose. "Cleared" means the test did not reproduce the incident error. It does not claim the suspect is impossible.

### 6.4 `culprit verify-fix INC`

For each reproduced suspect, rerun its reproduction test and then the full suite (`python -m pytest -q`). If both pass, move the suspect to `fixed` and record the commit.

### 6.5 Evidence tests in the normal suite

Tests for cleared suspects fail or pass by design (the pool test always exhausts the pool), so they must not break the normal suite. `culprit open <INC>` writes `tests/incidents/<INC>/conftest.py`. Its `pytest_collection_modifyitems` hook reads the ledger and skips tests whose suspect is cleared or inconclusive, with the reason "Culprit evidence for a cleared suspect, see ledger <test id>", unless `CULPRIT_RUN_EVIDENCE=1` is set. Tests of reproduced suspects are not skipped: they fail until the fix lands, then pass and stay as regression tests.

`pyproject.toml` sets `testpaths = ["brightcart/tests", "culprit/tests", "tests/incidents"]` and `norecursedirs = ["culprit/tests/fixtures"]`. The fixture files that the runner's unit tests use deliberately raise errors, so the normal suite never collects them. The unit tests pass their paths to the runner explicitly.

Exit codes for all commands: 0 success, 2 guard block, 3 validation error, 4 test harness error.

## 7. The guard hook (`python -m culprit.guard`)

Bob runs this before every file write (section 8.2) and sends the tool call as JSON on stdin. `guard.py` uses only the Python standard library and imports nothing else from `culprit`, and `culprit/__init__.py` stays empty. That way the hook still works if it runs outside the virtual environment. A crashing guard would let every edit through.

1. Read stdin. Append the raw payload to `.culprit/hook-payloads.log`, keeping the last 20. This matters because the payload field names are not documented. Look for the tool name in `tool_name`, `toolName`, `tool` or `name`, and for the file path in `tool_input.path`, `tool_input.file_path`, `input.path`, `arguments.path`, `args.path` or `params.path`. If none match, search nested values for a string that looks like a repo-relative path.
2. **Block** (exit 2, message on stderr, also echoed to stdout) when:
   - the path ends with `ledger.json` under `.culprit/`: "Culprit guard: ledgers change only through the culprit CLI."
   - the path is under `brightcart/` but not `brightcart/tests/`, and the active incident has no suspect in `reproduced` or `fixed`: "Culprit guard: no changes to application code until a test reproduces INC-001's error (0 of 3 suspects reproduced). Run /investigate INC-001 first."
3. Otherwise allow (exit 0). With no active incident, allow everything.

Unit tests cover all three outcomes with sample payloads.

## 8. The Bob pack

The shapes below follow the Bob docs (bob.ibm.com/docs) as of September 2026. If Bob reports a configuration error after loading them, fix the file to match what the error asks for.

### 8.1 `.bob/custom_modes.yaml`

```yaml
customModes:
  - slug: culprit-investigator
    name: 🔎 Culprit Investigator
    description: Proves or clears every incident suspect with a test. Never edits app code.
    roleDefinition: >-
      You are an incident investigator. You never guess a root cause. For every open
      suspect in the Culprit ledger you have a test written that tries to reproduce the
      exact error from the logs, and you let the culprit CLI decide the verdict.
    whenToUse: Use when a Culprit incident is open and its suspects have not been tested.
    customInstructions: |-
      1. Run `python -m culprit status <INC>` to list open suspects.
      2. Spawn one `general` subagent per open suspect, all in parallel. Give each one the
         output of `python -m culprit evidence <INC> <ID>` and tell it to follow the
         reproduce-suspect skill.
      3. Each subagent writes exactly one test file under tests/incidents/<INC>/ and runs
         `python -m culprit test <INC> --suspect <ID> --test <path>`.
      4. When all subagents finish, run `python -m culprit verdict <INC>` and show the table.
      5. Never edit files under brightcart/ or .culprit/ yourself.
    groups:
      - read
      - - edit
        - fileRegex: ^tests/incidents/.*\.py$
      - execute
      - skill
      - subagent
      - todo
    allowedSubagents:
      - explore
      - general
  - slug: culprit-fixer
    name: 🩹 Culprit Fixer
    description: Fixes a reproduced suspect with the smallest change and proves the fix.
    roleDefinition: >-
      You fix production bugs that Culprit has reproduced. You make the smallest change
      that makes the reproduction test pass, keep the full suite green, and add the missing
      test coverage the incident exposed.
    whenToUse: Use after `culprit verdict` shows at least one reproduced suspect.
    customInstructions: |-
      1. Read the reproduced suspect with `python -m culprit evidence <INC> <ID>` and its test.
      2. Make the smallest code change that fixes it. Do not touch unrelated code.
      3. Add Unicode address fixtures (ß ä ö ü é ñ ø) to brightcart/tests/.
      4. Run `python -m culprit verify-fix <INC>` and show the output.
    groups:
      - read
      - edit
      - execute
      - skill
      - todo
```

### 8.2 `.bob/settings.json` (hooks)

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "^(write_file|apply_diff|search_and_replace|insert_content)$",
        "hooks": [{ "type": "command", "command": ".venv/bin/python -m culprit.guard", "timeout": 10 }]
      }
    ],
    "Stop": [
      {
        "hooks": [{ "type": "command", "command": ".venv/bin/python -m culprit status --active", "timeout": 20 }]
      }
    ]
  }
}
```

`PreToolUse` hooks block with exit code 2. `Stop` hooks cannot block. Here the Stop hook only prints the current suspect table at the end of every task. The commands use the project's `.venv` Python (macOS and Linux path) so the packages are always found.

### 8.3 Commands (`.bob/commands/*.md`)

Each command file has frontmatter with `description` and `argument-hint: <incident id, e.g. INC-001>`.

- `investigate.md` (`/investigate INC-001`): "Test every suspect of an incident in parallel and record verdicts." The body tells Bob to switch to 🔎 Culprit Investigator, run `python -m culprit open <INC>`, and follow the mode's instructions.
- `fix.md` (`/fix INC-001`): "Fix a reproduced suspect and prove the fix." The body tells Bob to switch to 🩹 Culprit Fixer and follow the mode's instructions.
- `postmortem.md` (`/postmortem INC-001`): "Write the postmortem from the ledger and the team's documents." The body tells Bob to use the write-postmortem skill.

If the incident id does not reach the command body, have the body ask for it, or write `INC-001` into it as the default.

### 8.4 Skills

`.bob/skills/reproduce-suspect/SKILL.md`

```markdown
---
name: reproduce-suspect
description: Write one pytest test that tries to reproduce a Culprit suspect's logged error, then record it with the culprit CLI.
---
1. Read the suspect and evidence you were given. Note the exception type, message and frames.
2. Write tests/incidents/<INC>/test_<id>_<slug>.py. Start it with a module docstring:
       suspect: <ID>
       mechanism: <one sentence: what this test does to trigger the suspected cause>
       evidence: <event ids>
3. Exercise the suspected mechanism the way production does, with inputs and feature flags
   built from the evidence. Example: the error says '\xdf' in the street field for country AT,
   and C1 turned LABEL_ASCII_FASTPATH on, so build an Austrian address whose street contains ß
   and run with that flag on. Do not catch the exception. Let it raise. End with one assertion
   about the correct behaviour (for example, the label line still contains the street name),
   so the same test works as the regression test after a fix.
4. Test the suspect in isolation. Call only the code the suspect names: its module for a
   code or resource suspect, the changed service or files for a change suspect. Do not run
   the whole checkout path, or another suspect's bug can make your test fail. Do not mock
   the code under suspicion.
5. Run: python -m culprit test <INC> --suspect <ID> --test <path>
6. Report the CLI output exactly. Do not decide the verdict yourself.
```

`.bob/skills/write-postmortem/SKILL.md` follows section 9.

### 8.5 Rules

`.bob/rules-culprit-investigator/01-evidence.md`: never call a suspect the root cause unless `culprit verdict` says reproduced. Never edit the ledger. One test file per suspect. Quote event ids when explaining.

## 9. Postmortem report (document understanding)

Input documents, read with Bob's PDF and Word tools. They are fictional data and must not be edited.

- `docs/postmortem-template.docx`: the team's template, with docxtpl placeholders.
- `docs/runbook-brightcart.pdf`: the on-call runbook. Its step 3.3 says to roll back the most recent deploy when a deploy landed in the last 15 minutes. For INC-001 that would have rolled back payments 1.8.2, which was innocent.
- `docs/postmortems/PM-2026-07-18-label-unicode.docx`: a July incident where shipping labels failed for accented names. Its action item 2 ("add Unicode address fixtures to the orders and labels test suites") is still open. INC-001 is the same class of bug in a new place.

The write-postmortem skill (run with `/postmortem INC-001`):

1. Reads the three documents and the ledger.
2. Writes `reports/INC-001-context.json` with `summary`, `impact`, `author`, `lessons`, `action_items`, `repeat` and `runbook` (fields below).
3. Runs `python -m culprit report INC-001 --context reports/INC-001-context.json`. That command merges the ledger, incident and context, renders the template with docxtpl into `reports/INC-001-postmortem.docx`, and writes `viewer/data/INC-001.json`.
4. Writes `docs/runbook-changes/INC-001.md` with the proposed runbook edit.

Template variables (they must match `docs/postmortem-template.docx` exactly):

```text
incident.id  incident.title  incident.date  incident.severity  incident.duration  incident.services  incident.status
author  summary  impact
timeline[]      .time .event .evidence
root_cause      .statement .suspect_id .test_path .signature .introduced_by
suspects[]      .id .title .prior .verdict .test .reason
fix             .summary .commit .regression_test .verified_at
repeat          .found .postmortem_id .summary .open_items[]
runbook         .finding .proposed_change
action_items[]  .id .action .owner .due .status
lessons[]
evidence_note
```

## 10. Replay viewer (`viewer/`)

A static page with no build step (`index.html`, `app.js`, `styles.css`) that reads `data/INC-001.json`, deployed to Vercel.

- **Header**: incident id and title, peak error rate, failed checkouts, time from alert to reproduced root cause, Bobcoins used (typed in by hand from the Bob task summaries).
- **Service map** (SVG): gateway → orders → payments, and orders → orders-db. Nodes turn amber and red as the replay reaches their first warning and error.
- **Timeline** with a Play button and a scrubber: C1, C2, latency warnings, DACH share jump, first error, alert, investigation start, each verdict, fix verified.
- **Suspect cards**: prior, status chip (SUSPECT amber, REPRODUCED red, CLEARED grey, FIXED green), test file name, observed exception, score, verdict reason. During the replay the cards flip in the order recorded in `history`.
- **Evidence drawer**: the log lines behind any card.
- Must work at phone width and in light and dark mode.

Data file shape: `{incident, services, edges, timeline[], suspects[], tests[], history[], fix, cost}`.

## 11. Acceptance checklist (the demo depends on these)

- [ ] `python -m culprit reconstruct INC-001` lists S1 (payments deploy), S2 (to_label_line) and S3 (pool), all `suspect`.
- [ ] The guard blocks an edit to `brightcart/orders/address.py` before any reproduction, with the Culprit message visible in Bob.
- [ ] `/investigate INC-001` spawns three subagents in parallel. Each writes one test, and `culprit verdict` gives S1 cleared, S2 reproduced, S3 cleared.
- [ ] `/fix INC-001` changes `to_label_line`, and `culprit verify-fix INC-001` moves S2 to fixed with the full suite green and Unicode fixtures added.
- [ ] `reports/INC-001-postmortem.docx` names PM-2026-07-18 as a repeat and reports the runbook finding.
- [ ] The viewer plays the replay from `viewer/data/INC-001.json` and is live on Vercel.
- [ ] `bob_sessions/` has one summary screenshot per Bob task.

## 12. Stretch goal: INC-002 (only if Bobcoins remain)

A second scenario in which the most recent deploy really is the culprit: payments 1.9.0 renames the `card_token` field, and every charge fails with `KeyError: 'card_token'`. This shows Culprit is not biased against recent deploys. Same pipeline, new `--scenario inc-002`.

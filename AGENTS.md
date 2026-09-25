# Culprit: project context for Bob

Read this file first in every task. The full design is in `docs/SPEC.md`. The build order is in `docs/BOB_TASKS.md`.

## What we are building

Culprit is a debugging tool for production incidents. It reads an incident's logs and deploy history, lists every plausible cause as a **suspect**, and then has Bob test all suspects in parallel with subagents. A suspect is called the root cause only when a test reproduces the exact error from the logs. Suspects whose tests do not reproduce it are **cleared**, with the test kept as evidence. Only after a reproduction exists may Bob change application code. The reproduction test then becomes the regression test, and Bob writes the postmortem in the team's own Word template.

The one rule behind everything:

> **No verdict without a test.** Culprit never presents a guessed root cause as fact.

## Repository layout

```text
brightcart/          sample e-commerce app with a planted bug (the system that breaks)
datasets/incidents/  incident data generated from Brightcart (logs, changes, architecture)
culprit/             the Culprit tool (Python package + CLI)
tests/incidents/     reproduction tests written by the Investigator subagents
.culprit/            Culprit runtime state per incident (events, incident, ledger)
.bob/                custom modes, hooks, commands, skills, rules
viewer/              static replay page (deployed to Vercel)
reports/             generated postmortems
docs/                spec, task plan, demo script, and input documents
bob_sessions/        Bob task session summary screenshots (hackathon evidence)
```

## Commands

```bash
python -m pytest -q                                  # all tests
python -m culprit ingest INC-001                     # logs -> .culprit/INC-001/events.json
python -m culprit reconstruct INC-001                # events -> incident.json + ledger.json
python -m culprit open INC-001                       # mark INC-001 as the active incident
python -m culprit status INC-001                     # suspect table
python -m culprit evidence INC-001 S2                # one suspect plus its evidence lines
python -m culprit test INC-001 --suspect S1 --test tests/incidents/INC-001/test_s1_x.py
python -m culprit verdict INC-001                    # apply verdict rules to the ledger
python -m culprit verify-fix INC-001                 # rerun reproduction tests + full suite
python -m culprit report INC-001 --context reports/INC-001-context.json
```

## Conventions

- Python 3.11 in the project virtual environment. Always run Python as `.venv/bin/python` (for example `.venv/bin/python -m pytest -q`), never a system `python`.
- Type hints everywhere, `pydantic` v2 for models, `pytest` for tests.
- Standard library first. Allowed third-party packages: `fastapi`, `httpx`, `pydantic`, `pytest`, `docxtpl`, `python-docx`, `pypdf`. Ask before adding anything else.
- Tests never touch the network. Brightcart services talk to each other in-process through `httpx.ASGITransport`.
- Everything is deterministic. Randomness uses a fixed seed. Time comes from `brightcart.common.clock`, never `datetime.now()` directly.
- Keep files small and focused. Prefer clear names over comments.

## Things you must not do

- Do not edit `.culprit/**/ledger.json` by hand. Only the `culprit` CLI changes a ledger.
- Do not change files under `brightcart/` while an incident has no reproduced suspect. A hook enforces this.
- Do not edit the input documents in `docs/` (`runbook-brightcart.pdf`, `postmortem-template.docx`, `postmortems/*.docx`). Read them only.
- Do not use real personal data. All customers, addresses and names are fictional.

## Keep Bobcoin use low

The hackathon account has 40 Bobcoins in total. Read only the files a task needs, reference them with `@path` instead of pasting them, use `explore` subagents for read-only digging, and stop when the "Done when" checks in `docs/BOB_TASKS.md` pass.

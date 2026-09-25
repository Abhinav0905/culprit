# Culprit build steps for Bob

Twelve steps. For each one, do the same four things:

1. Pick the **mode** named in the step (dropdown under the Bob chat box).
2. Start a **new task** (the + button in the Bob chat panel) and **paste the prompt** exactly.
3. Click **Approve** whenever Bob asks. Wait until the "Done when" check is true.
4. Save the **task summary screenshot** (see "After every step").

If anything looks wrong, stop, take a normal screenshot, and send it to Claude. Nothing here is irreversible: Bob's Rollback undoes a task's file changes.

## Before step 1 (no Bob yet)

- [ ] Clone the repo: `git clone https://github.com/Abhinav0905/culprit.git`
- [ ] Copy the kit into it: `AGENTS.md` goes in the repo root, and the kit's `docs/` folder becomes `culprit/docs/`.
- [ ] Open the `culprit` folder in Bob IDE (File → Open Folder).
- [ ] Bob Settings → General shows the **ibm-coding-challenge** account (us-east) and 40 Bobcoins.
- [ ] Do not run `/init`. `AGENTS.md` is already written.

## After every step

1. In the Bob chat panel, click **Tasks**, open the task you just finished, and click the **task header**. The usage summary appears.
2. Screenshot it as a PNG named `culprit_taskNN_<short-name>_summary.png` (the name for each step is listed below). If you keep IncidentLens as the lablab team name, start the file names with `incidentlens_` instead. The guide asks for the team name in each file name.
3. Put it in the `bob_sessions/` folder.
4. Check the Bobcoin balance in Settings → General and write it in the budget table at the end of this file.

## Step 1: plan (Plan mode)

Screenshot: `culprit_task01_plan_summary.png` · Budget: about 1 Bobcoin

```text
Read @AGENTS.md and @docs/SPEC.md. Do not write any code yet.
Write docs/PLAN.md with:
1. Every file you will create, grouped by the steps in @docs/BOB_TASKS.md.
2. The Python packages you need.
3. The three biggest risks to the demo and how you will handle each one.
Keep it under 120 lines. Also create bob_sessions/.gitkeep.
Commit everything with the message "Add Culprit spec and build plan" and push.
```

Done when `docs/PLAN.md` exists and the commit is pushed. If Bob says Plan mode can't write files, switch to Agent mode and send: `Save that plan to docs/PLAN.md, create bob_sessions/.gitkeep, commit and push.`

## Step 2: the Brightcart sample app (Agent mode)

Screenshot: `culprit_task02_brightcart_summary.png` · Budget: about 3 Bobcoins

```text
Build the Brightcart sample app exactly as described in @docs/SPEC.md section 3
(3.1 behaviour and 3.2 log format).
- Python 3.11. Create pyproject.toml with the packages listed in @AGENTS.md, create a .venv
  and install them.
- The planted bug in brightcart/orders/address.py only exists while the
  LABEL_ASCII_FASTPATH flag is on.
- brightcart/tests/ covers the happy paths with ASCII-only addresses. The missing Unicode
  coverage is deliberate, so do not add it.
- Create .bobignore containing: datasets/**/logs/*.jsonl
Done when `python -m pytest brightcart/tests -q` passes. Show me the test output, then
commit with the message "Add Brightcart sample app" and push.
```

## Step 3: generate the incident data (Agent mode)

Screenshot: `culprit_task03_dataset_summary.png` · Budget: about 1.5 Bobcoins

```text
Build brightcart/loadgen.py for the INC-001 scenario in @docs/SPEC.md section 4, then run:
python -m brightcart.loadgen --scenario inc-001 --out datasets/incidents/INC-001
Set incident_commit in meta.json to the output of `git rev-parse HEAD` before you commit.
Print a short summary: event counts per service and level, the time of the first ERROR,
and the checkout failure rate after it. Check that the first orders ERROR is near 09:07 UTC,
about 8% of checkouts fail after it, payments latency_high warnings start near 09:04 and
db_pool_high warnings start near 09:10. Fix loadgen.py if any check is off.
Commit with the message "Generate INC-001 dataset" and push.
```

## Step 4: Culprit ingest and reconstruction (Agent mode)

Screenshot: `culprit_task04_reconstruct_summary.png` · Budget: about 3 Bobcoins

```text
Build the Culprit package from @docs/SPEC.md sections 5.1 to 5.4: models.py, ingest.py,
reconstruct.py, signature.py (normalize() and signature grouping only, scoring comes later),
and cli.py with the commands ingest, reconstruct, status, evidence and open. Add unit tests
in culprit/tests/, including one that checks the expected INC-001 suspects in section 5.3.
Use an explore subagent to read brightcart/ and the dataset format first, so this
conversation stays small.
Done when these print S1 payments 1.8.2 deploy (0.65), S2 to_label_line UnicodeEncodeError
(0.60) and S3 orders DB pool saturation (0.25), all with status suspect:
  python -m culprit ingest INC-001
  python -m culprit reconstruct INC-001
  python -m culprit status INC-001
and `python -m pytest culprit/tests -q` passes.
Commit with the message "Add Culprit ingest and reconstruction" and push.
```

## Step 5: test runner, scoring and verdicts (Agent mode)

Screenshot: `culprit_task05_verdicts_summary.png` · Budget: about 3 Bobcoins

```text
Add @docs/SPEC.md sections 6.1 to 6.4: runner.py (runs one pytest file and parses the JUnit
XML), signature scoring in signature.py, verdict.py, and the CLI commands test, verdict and
verify-fix.
Also add section 6.5: the conftest.py that `culprit open` writes, and the testpaths and
norecursedirs settings in pyproject.toml.
For unit tests, put three small throwaway test files in culprit/tests/fixtures/: one that
raises the same UnicodeEncodeError from to_label_line, one that passes, and one that raises a
different error. Test runner.py and signature.py directly with them (the tests/incidents/
path check belongs to the CLI) and check that they score about 1.0, 0.0 and below 0.3.
Do not create anything under tests/incidents/. The Investigator does that later.
Done when `python -m pytest culprit/tests -q` passes.
Commit with the message "Add Culprit test runner, scoring and verdicts" and push.
```

## Step 6: the Bob pack and the guard hook (Agent mode)

Screenshot: `culprit_task06_bobpack_summary.png` · Budget: about 2.5 Bobcoins

```text
Create the Bob pack from @docs/SPEC.md sections 7 and 8:
- culprit/guard.py with unit tests (block, allow, and ledger-edit cases)
- .bob/custom_modes.yaml (8.1), .bob/settings.json with the hooks (8.2)
- .bob/commands/investigate.md, fix.md and postmortem.md (8.3)
- .bob/skills/reproduce-suspect/SKILL.md (8.4) and
  .bob/skills/write-postmortem/SKILL.md (from section 9)
- .bob/rules-culprit-investigator/01-evidence.md (8.5)
Use the file formats from the spec exactly. Then run `python -m culprit open INC-001`.
Done when the guard unit tests pass.
Commit with the message "Add Culprit Bob pack and guard hook" and push.
```

Then check that Bob loaded it:

1. Reload Bob: Command Palette (Cmd+Shift+P) → **Developer: Reload Window**.
2. The mode dropdown should now list **🔎 Culprit Investigator** and **🩹 Culprit Fixer**. Typing `/` in the chat box should list `/investigate`, `/fix` and `/postmortem`.
3. **Start screen recording now.** This moment goes in the video. In Agent mode, send: `Add the comment "# checked" at the top of brightcart/orders/address.py`
4. Bob should be blocked with a message that starts **"Culprit guard: no changes to application code until a test reproduces INC-001's error"**. Do not retry. The block is the feature.

If the edit was **not** blocked, send this and then repeat item 3:

```text
The guard did not block that edit. Show me the last entry in .culprit/hook-payloads.log,
update culprit/guard.py to read the tool name and file path from the fields you see there,
add a unit test with that payload, run the tests, commit and push.
```

## Step 7: investigate (🔎 Culprit Investigator mode) · the heart of the demo

Screenshot: `culprit_task07_investigate_summary.png` · Budget: about 3 Bobcoins

**Keep screen recording on for this whole step.** Type only:

```text
/investigate INC-001
```

- Bob asks to approve each subagent. Click **Approve** three times, once per suspect.
- The parallel subagents panel shows three subagents working at once. Let the recording run.
- Done when the verdict table shows **S1 cleared, S2 reproduced, S3 cleared**.

If a suspect comes back inconclusive, send (with the right suspect number):

```text
Rewrite the test for S1 following the reproduce-suspect skill, then run culprit test and
culprit verdict again.
```

Then send: `Commit the incident tests and the ledger with the message "Investigate INC-001" and push.`

## Step 8: fix (🩹 Culprit Fixer mode)

Screenshot: `culprit_task08_fix_summary.png` · Budget: about 1.5 Bobcoins

**Keep recording.** Type:

```text
/fix INC-001
```

Done when `culprit verify-fix INC-001` shows **S2 fixed** and the full test suite passes. The fix should be a few lines in `to_label_line`, plus Unicode address fixtures in `brightcart/tests/`.

Then send: `Commit with the message "Fix INC-001: Unicode-safe label line" and push.`

## Step 9: the postmortem report (Agent mode, then the /postmortem command)

Screenshots: `culprit_task09a_report_summary.png` and `culprit_task09b_postmortem_summary.png` · Budget: about 2.5 Bobcoins

First task (Agent mode):

```text
Build culprit/report.py and the `report` CLI command from @docs/SPEC.md section 9: merge
the ledger, incident.json and a context JSON, render docs/postmortem-template.docx with
docxtpl into reports/<INC>-postmortem.docx, and write viewer/data/<INC>.json in the shape
from section 10. The template's variable names are listed in section 9 and must match.
Add a unit test that renders the template with a small fixture context.
Done when the test passes. Commit with the message "Add postmortem report" and push.
```

Second task (a new task; the mode doesn't matter, the command picks the skill). **Record this.**

```text
/postmortem INC-001
```

Done when `reports/INC-001-postmortem.docx` opens in Word or Pages and it:

- names **PM-2026-07-18** as an earlier incident of the same kind, with its open action item
- says runbook **step 3.3** would have rolled back payments 1.8.2, which was innocent
- lists all three suspects with their tests and verdicts

Then send: `Commit the report, the context JSON and the viewer data with the message "Add INC-001 postmortem" and push.`

## Step 10: the replay viewer (Agent mode)

Screenshot: `culprit_task10_viewer_summary.png` · Budget: about 3 Bobcoins

```text
Build the static replay viewer in viewer/ from @docs/SPEC.md section 10. It reads
viewer/data/INC-001.json. Plain HTML, CSS and JavaScript, no build step, no external
libraries or fonts. It must look good at 1280 px wide for the video and also at phone width,
in light and dark mode.
Done when `python -m http.server 8080 -d viewer` serves a page where Play shows: C1, C2,
the first error, the alert, the three suspects flipping to their verdicts, and S2 turning
green when the fix is verified. Commit with the message "Add replay viewer" and push.
```

Hosting: in Vercel, import the GitHub repo, set the root directory to `viewer`, choose framework preset **Other**, and deploy. Claude can do this in your browser once you're logged into Vercel.

## Step 11: README (Agent mode)

Screenshot: `culprit_task11_readme_summary.png` · Budget: about 1 Bobcoin

```text
Rewrite README.md for judges. Sections:
1. What Culprit is, in two sentences.
2. The problem (the 2 AM wrong-rollback story, one paragraph).
3. How it works: the six numbered steps from @docs/SPEC.md section 1.
4. A Mermaid flowchart of the pipeline.
5. Run it locally: the exact commands.
6. How IBM Bob is used: custom modes, parallel subagents, the guard hook, slash commands,
   skills, reading PDF and Word documents, Plan and Agent modes. Link each to its file in .bob/.
7. Evidence: link bob_sessions/.
8. How this was built: all code was written in IBM Bob IDE during the hackathon; the spec
   and step plan in docs/ were drafted with help from Claude; the runbook, template and July
   postmortem in docs/ are fictional input data; the idea was inspired by the author's
   earlier open-source project IncidentLens, and no code from it is reused.
Commit with the message "Add README" and push.
```

## Step 12: only if Bobcoins remain

Pick one:

- INC-002 from @docs/SPEC.md section 12: a case where the most recent deploy really is guilty. This shows Culprit isn't biased against deploys.
- A Bob Shell script that runs `/investigate` automatically when a new incident folder appears.

## If you run out of Bobcoins

Stop and tell Claude. The guide says you can keep working on the submission after the coins run out, and watsonx.ai (Granite) is available as a backup model for any remaining text.

## Budget tracker

| Step | Target | Balance after the step |
| --- | --- | --- |
| Start | | 40 |
| 1 Plan | 1 | |
| 2 Brightcart | 3 | |
| 3 Dataset | 1.5 | |
| 4 Reconstruct | 3 | |
| 5 Verdicts | 3 | |
| 6 Bob pack | 2.5 | |
| 7 Investigate | 3 | |
| 8 Fix | 1.5 | |
| 9 Report + postmortem | 2.5 | |
| 10 Viewer | 3 | |
| 11 README | 1 | |
| Reserve | 15 | |

These targets are guesses. After step 2, compare what it really cost with its target. If it cost more than twice as much, tell Claude before step 3 and the remaining prompts will be cut down.

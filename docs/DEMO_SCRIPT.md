# Culprit demo video (3:00 hard limit)

The rules: MP4, 3 minutes at most, at least 90 seconds showing the solution working, narration on, and a clear view of how IBM Bob is used. Judges stop at 3:00.

This script shows the product for about 1 minute 50 seconds.

## Script

| Time | On screen | Narration (read at a calm pace) |
| --- | --- | --- |
| 0:00 to 0:12 | Viewer page, error-rate spike at 09:07 | "It's 2:12 in the morning. Eight percent of checkouts are failing. The runbook says: roll back the most recent deploy. That deploy is innocent." |
| 0:12 to 0:25 | One slide: the problem | "Incidents take about three hours to resolve on average, according to PagerDuty's 2024 survey. Much of that goes to chasing the wrong cause. Tools that state a root cause with confidence make this worse when they're wrong." |
| 0:25 to 0:40 | Terminal: `culprit reconstruct INC-001` and the suspect table | "Culprit reads the logs and the deploy history and lists every plausible cause as a suspect. The payments deploy, four minutes before the first error, looks the guiltiest. Nothing here is a verdict yet." |
| 0:40 to 0:55 | Bob: the guard blocking the edit | "Culprit's rule is no verdict without a test. A Bob hook enforces it: until a test reproduces the error, Bob can't touch application code." |
| 0:55 to 1:30 | Bob: `/investigate INC-001`, approving three subagents, the parallel subagents panel (speed up 3x, with an on-screen "3x" label) | "In the Investigator mode, Bob spawns one subagent per suspect, in parallel. Each writes a single test that tries to reproduce the exact error in the logs. The Culprit CLI runs every test itself and scores it against the logged error, so Bob can't mark its own homework." |
| 1:30 to 1:50 | Verdict table: S1 cleared, S2 reproduced, S3 cleared | "The payments deploy is cleared: it handles the same orders without an error. Pool exhaustion is cleared too: it fails in a different way. The culprit is a Unicode bug in the shipping label code, introduced by an orders deploy twelve minutes earlier. The test fails with the same error as production." |
| 1:50 to 2:05 | Bob: `/fix INC-001`, the diff, verify-fix output with S2 fixed | "Only now can the Fixer mode change code. A three-line fix, the reproduction test goes green, the full suite passes, and that test stays as the regression test." |
| 2:05 to 2:25 | The postmortem .docx: the repeat-incident paragraph and the runbook finding | "Bob reads the team's own Word template, the PDF runbook and past postmortems. It finds that this is a repeat of a July incident whose action item, add Unicode test fixtures, was never closed, and that runbook step 3.3 would have rolled back the wrong service." |
| 2:25 to 2:45 | Viewer replay playing on the Vercel URL | "Here's the full replay: the deploys, the first error, three suspects tested in parallel, one proven, two cleared, fix verified." |
| 2:45 to 3:00 | Closing slide: how Bob is used, and the repo URL | "Built entirely in IBM Bob, with custom modes, parallel subagents, hooks, skills and document understanding. Culprit doesn't guess a root cause. It proves one." |

## Recording checklist

- [ ] Screen at 1920×1080 or 1280×720. Bob IDE font size 16 or larger, zoom in on the chat panel.
- [ ] Close notifications and unrelated tabs and windows. Hide email addresses and account names where you can.
- [ ] Record the real runs in steps 6 to 9 as they happen. There's no need to redo them later unless something goes wrong.
- [ ] Record narration separately, reading this script, so the take can be clean. Cut the waiting and speed up long waits, with a visible "3x" label so it stays honest.
- [ ] Export as MP4, under 3:00. Check the length before uploading.
- [ ] Slides (PDF): title, problem, how it works, how Bob is used, impact, team. The video's two slides come from this deck.

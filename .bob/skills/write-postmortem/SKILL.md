---
name: write-postmortem
description: Read the incident ledger and team documents, then write the postmortem report.
---
1. Read docs/postmortem-template.docx (use office_read) to find the template variable names.
2. Read docs/runbook-brightcart.pdf to find the runbook step that would have led to the
   wrong rollback (step 3.3: roll back the most recent deploy when it landed < 15 min ago).
3. Read docs/postmortems/PM-2026-07-18-label-unicode.docx to find the open action item
   (action item 2: add Unicode address fixtures). Note that INC-001 is the same class of bug.
4. Read .culprit/<INC>/ledger.json and .culprit/<INC>/incident.json.
5. Write reports/<INC>-context.json with these fields:
   - summary: one paragraph describing what happened
   - impact: failed_checkouts count and peak error rate
   - author: "Culprit auto-investigator"
   - lessons: list of lessons learned
   - action_items: list of {id, action, owner, due, status}
   - repeat: {found: true, postmortem_id: "PM-2026-07-18", summary: "...", open_items: [...]}
   - runbook: {finding: "step 3.3 would have rolled back payments 1.8.2 (innocent)",
               proposed_change: "Add exception: do not roll back a change if its service
               shows no errors while the origin service does."}
6. Run: python -m culprit report <INC> --context reports/<INC>-context.json
7. Write docs/runbook-changes/<INC>.md with the proposed runbook edit.

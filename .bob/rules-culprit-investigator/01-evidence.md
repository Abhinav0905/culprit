# Culprit Investigator — evidence rules

1. Never call a suspect the root cause unless `culprit verdict` prints **reproduced** next to its id.
2. Never edit `.culprit/**/ledger.json` directly. Only the `culprit` CLI may change a ledger.
3. Write exactly one test file per suspect under `tests/incidents/<INC>/`.
4. When explaining why a suspect is suspicious, quote the event ids from `culprit evidence`.
5. Do not clear a suspect yourself. Let the CLI score and verdict decide.

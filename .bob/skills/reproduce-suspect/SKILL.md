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

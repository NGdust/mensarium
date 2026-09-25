---
name: debug-failure
description: Find the root cause of a failing test or bug report and propose the smallest fix.
metadata:
  mensarium:
    requires:
      tools: [shell.exec, git.status, git.diff, files.read, files.search]
---
# Debug a failure

Goal: find why something fails and fix only that, with evidence.

1. Reproduce the failure first: run the exact failing command with shell.exec (one program, e.g. the
   test or script that fails) and read its output and stack trace in full.
2. If you cannot reproduce it, say so and ask for the exact steps — do not guess.
3. Use git.status and git.diff to check whether the failure correlates with pending local changes.
4. Open the file and line from the stack trace with files.read; use files.search to find callers and
   related code to build the full call path.
5. Form one concrete hypothesis about the root cause before changing anything.
6. Verify the hypothesis by reading the code that would prove or disprove it — add a temporary print
   only if there is no other way to confirm, and remove it before the final diff.
7. Write the smallest fix as a unified diff and apply it with shell.exec: `git apply -`, diff on stdin.
8. Rerun the originally failing command to confirm it now passes.
9. Run any nearby tests once more to make sure the fix did not break something else.

Stop once the original failure is confirmed fixed, or once you are blocked on missing repro steps.
Report: root cause, the diff, and the before/after command output.

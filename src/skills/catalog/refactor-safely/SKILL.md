---
name: refactor-safely
description: Restructure code without changing its behavior, verified by tests before and after.
metadata:
  mensarium:
    requires:
      tools: [files.read, files.search, shell.exec, git.diff]
---
# Refactor safely

Goal: change the code's structure, not its behavior, and prove it with tests.

1. Read the target code fully with files.read, and use files.search to find every caller.
2. Find whether tests already cover this code (files.search for test files matching the module) and
   the exact command to run them (files.read the Makefile or project docs).
3. Run that test command with shell.exec first, before any change, to record the baseline result.
4. If there is no test coverage for this code, stop and tell the user instead of refactoring blind.
5. Make the smallest change that achieves the stated goal: extract a function, rename, remove
   duplication. Do not change public signatures, behavior, or unrelated code.
6. Express the change as a minimal unified diff and apply it with shell.exec: `git apply -`, diff on
   stdin, cwd at the repo root.
7. Rerun the exact same test command and compare the result to the baseline — it must match exactly.
8. Run git.diff to confirm only the intended files changed.

Stop once the after-result matches the baseline, or immediately if it does not — do not keep patching
blindly. Report: what changed, the baseline vs. after test output, and the diff.

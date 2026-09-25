---
name: write-tests
description: Add tests for existing or new code, following the project's own test conventions.
metadata:
  mensarium:
    requires:
      tools: [files.read, files.search, shell.exec]
---
# Write tests

Goal: add tests for the requested code using the project's existing test setup, and prove they pass.

1. Read the target code fully with files.read before writing anything.
2. Use files.search to find existing tests for neighboring code; read a couple of them to copy the
   framework, naming pattern, fixtures and assertion style already in use.
3. Find the test-run command from the project docs (files.read Makefile/CLAUDE.md/package.json) instead
   of guessing one.
4. Cover the normal case, at least one edge case, and error handling if the function has any.
5. Write the new test code as a minimal unified diff against the identified test file (or a new one in
   the same directory, following the existing naming pattern).
6. Apply it with shell.exec: program `git`, args `apply -`, the diff on stdin, cwd at the repo root.
7. Run the test command with shell.exec (one program, no chaining) scoped to the new test file first.
8. If it fails, read the output, fix with another small diff, and rerun — at most a couple of iterations.
9. Run the broader suite once if feasible, to confirm nothing else broke.
10. Do not modify the code under test to make a test pass; if the code looks wrong, report that instead.

Stop once the new tests pass and the existing suite is not broken. Report: what you covered, the diff,
and the test command's pass/fail output.

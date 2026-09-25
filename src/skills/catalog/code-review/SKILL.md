---
name: code-review
description: Review uncommitted changes for bugs, risky edits and missing tests.
metadata:
  mensarium:
    requires:
      tools: [git.status, git.diff, files.read]
---
# Code review

Goal: find real defects in the pending changes, not style nits.

1. Run git.status and git.diff (and git.diff with staged=true) to see every change.
2. For each changed hunk, read enough of the surrounding file with files.read to understand the context:
   callers, types, error handling, invariants.
3. Look for, in this order:
   - correctness bugs: wrong conditions, off-by-one, unhandled None/null, wrong return values, broken edge cases;
   - security: injection, secrets in code, unsafe deserialization, missing auth checks, path traversal;
   - concurrency and resource leaks: missing awaits, unclosed files/connections, races;
   - behaviour changes the author may not intend: changed defaults, removed validation, API contract changes;
   - missing or outdated tests for the changed behaviour.
4. Verify each suspicion by reading the code it depends on before reporting it. Drop anything you cannot confirm.
5. Do not modify files and do not run commands that change state.

Report format:
- One line verdict first (looks good / needs changes).
- Then findings ordered by severity: `path:line` — what is wrong — concrete failure scenario — suggested fix.
- Keep it short; skip praise and restating the diff.

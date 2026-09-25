---
name: docs-update
description: Bring docs in line with a code change, fixing only real mismatches.
metadata:
  mensarium:
    requires:
      tools: [git.status, git.diff, files.search, files.read, shell.exec]
---
# Update docs

Goal: fix documentation that no longer matches the code — nothing more.

1. Run git.status and git.diff to see exactly what changed in the code.
2. Use files.search to find docs referencing the changed area: README, CLAUDE.md-equivalent, docs/*,
   and read each candidate with files.read.
3. For every doc claim about the changed area, verify it against the current code with files.read —
   flag only genuine mismatches: renamed commands, changed flags or defaults, removed features, wrong
   paths or examples.
4. Do not touch doc text that is still accurate, even if it could be phrased better.
5. Write the smallest unified diff that fixes each mismatch.
6. Apply it with shell.exec: `git apply -`, diff on stdin, cwd at the repo root.
7. Run git.diff again to confirm only the intended doc lines changed.
8. Do not add new sections, examples or claims that are not grounded in the code you read.

Stop once every flagged mismatch is fixed. Report: which lines changed and why, and any mismatch you
found but left unfixed, with the reason.

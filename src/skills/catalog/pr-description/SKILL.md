---
name: pr-description
description: Draft a pull request title and description from the current diff and commit history.
---
# PR description

Goal: write a PR title and description a reviewer can act on, grounded in the actual diff.

1. Run git.status to see the branch and every changed file.
2. Run git.diff (staged=true and staged=false) to read every change end to end.
3. Read touched files with files.read for context the diff alone does not explain: surrounding
   function, callers, why a default or check changed.
4. If the git-history plugin's git.log tool is available, call it once for a short commit list on this
   branch; if it is not available, skip that and rely on the diff alone.
5. Identify: what changed, why (inferred only from the code, never invented), risk areas, and anything
   a reviewer needs to know (breaking changes, migrations, follow-ups left for later).
6. Draft a short title in imperative mood matching the repo's own commit style (check recent messages
   via git.diff context or the commits from step 4).
7. Draft the body: a Summary (2-4 bullets), a Changes section grouped by area or file, and a Test plan
   listing what to verify, grounded in what actually changed or in tests touched.
8. Flag any hunk that looks unrelated to the stated purpose of the change, so the reviewer can ask
   whether it belongs in this PR.
9. Note anything that looks like it needs a reviewer's special attention: a security-sensitive path, a
   migration, or a config/default change.
10. Do not mention files or effects that are not in the diff. Do not modify anything or run commands.

Report format:
- The PR title on its own line.
- The description body ready to paste: Summary / Changes / Test plan.

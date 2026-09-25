---
name: release-notes
description: Write release notes or a changelog section from commits since the last tag or a given range.
metadata:
  mensarium:
    requires:
      tools: [git.log]
---
# Release notes

Goal: turn raw commit history into a readable changelog, grouped by change type.

1. If the user did not give a range or tag, ask which range to cover, or default to `git.log` with
   `rev` unset and `limit` around 30 and say that is what you used.
2. Run git.log with `rev` set to `<from>..<to>` (or the given range) and a generous `limit` to list
   every commit in scope, one line each.
3. For any commit whose one-line message does not explain the user-facing effect, run git.show on it
   with `patch=false` to read the changed files and full message body.
4. Group entries into standard sections: Added, Changed, Fixed, Removed, Internal; skip empty sections.
5. Drop merge commits, version bumps and no-op commits unless the user asked for the full raw list.
6. Rewrite each entry as one plain, user-facing sentence; keep the commit's own intent, do not invent
   an effect the commit does not show.
7. If the same change is spread across several commits (a fix-up or a revert-and-redo), merge them into
   one entry instead of listing each separately.
8. Call out any breaking change in its own line at the top of the relevant section, even when the
   commit message itself did not flag it as one.
9. Credit the author only if the project's existing changelog already does so; otherwise keep entries
   focused on the change itself.
10. Do not run git commands that change anything: no tagging, no pushing, no committing.

Report format:
- A single markdown block ready to paste into a changelog: a version/date header (ask if unknown, or
  leave a placeholder), then the grouped bullet sections.

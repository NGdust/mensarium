---
name: issue-triage
description: Triage open GitHub issues into type and priority, flag duplicates and ones missing info.
metadata:
  mensarium:
    requires:
      tools: [gh.issue_list]
---
# Issue triage

Goal: turn a raw issue backlog into a triaged list with proposed labels and priority, changing nothing.

1. Call gh.issue_list to fetch open issues (default repo, or the one the user names); page further if
   the list is truncated.
2. Group near-duplicate issues by title and body similarity; mark the older one canonical and the rest
   as duplicates of it.
3. Classify each issue: bug / feature / question / chore, and estimate priority (blocking, high,
   normal, low) from the described impact, not from the reporter's own label.
4. Flag issues missing what is needed to act on them: no repro steps, no version, no expected/actual
   behavior.
5. When the codebase context is needed to judge severity, use files.search and files.read to check
   whether the reported behavior still matches the current code.
6. Note issues with no activity for a long time relative to the rest of the backlog as candidates for
   closing as stale, separately from duplicates.
7. For anything you classify as a bug, state the concrete reproduction and impact you based that
   classification on, not just the label you assigned.
8. Do not close, label, comment on, or edit any issue; this skill only proposes a triage.

Report format:
- List: issue number/title — type — priority — proposed label(s) — one-line reasoning.
- A short "needs more info" list, with what is missing.
- A short "likely duplicates" list.
- A short "stale, no activity" list, if any.

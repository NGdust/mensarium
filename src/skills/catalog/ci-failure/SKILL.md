---
name: ci-failure
description: Diagnose why a CI run failed from its failed-step logs and pinpoint the exact cause.
metadata:
  mensarium:
    requires:
      tools: [gh.run_view_failed]
---
# CI failure

Goal: find the exact cause of a failing CI run from its logs, without re-running anything.

1. Identify the run to inspect from what the user gave (run id, PR or branch); if none, ask which run.
2. Call gh.run_view_failed on that run to fetch logs for only the failed jobs and steps.
3. Read the log output in full; find the first failing command and its exact error message, not just
   the last lines of the log.
4. Distinguish infra flakiness (timeout, network blip, runner OOM, registry outage) from a real
   code or test failure.
5. For a real failure, open the referenced file and line with files.read; use files.search to find
   related code or a recently changed dependency if the failing file looks unrelated to the change.
6. Use git.status and git.diff to check whether the failure correlates with local uncommitted changes.
7. If the run has a job matrix (multiple OS/versions), check whether the failure hits every job or just
   one: one job pointing at environment, the whole matrix pointing at the code.
8. Check the step's cache and dependency install output for a silently changed version before blaming
   the test code itself.
9. Do not restart the run, push a fix, or modify any file; this skill only diagnoses.

Report format:
- Verdict: flaky infra vs real failure.
- The failing job/step and the exact error line.
- Root cause, grounded in the code.
- Whether it hit the whole matrix or a single job.
- Suggested fix, described but not applied.

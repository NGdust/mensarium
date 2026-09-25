---
name: docker-troubleshoot
description: Diagnose why a Docker container is failing, restarting or unhealthy using read-only inspection.
metadata:
  mensarium:
    requires:
      tools: [docker.ps, docker.logs]
---
# Docker troubleshoot

Goal: find why a container is failing or unhealthy, using only read-only inspection.

1. Call docker.ps to see every container's current status (state, restarts, image) and identify the
   one in question.
2. Call docker.logs on it with a generous line count to see the actual failure: crash trace, exit
   reason, or the last successful action before it stopped.
3. If the container is restarting in a loop, focus on the lines right before each restart, not just
   the very last line in the log.
4. Correlate the failure with the image/tag shown by docker.ps: was it recently changed, does the log
   show a config or migration the image now expects.
5. If the project has a compose file, read it with files.read to check environment variables, volumes
   and dependency ordering (`depends_on`) that could explain the failure.
6. Cross-check any application-level stack trace against the source with files.read and files.search.
7. If the pattern looks like a resource limit (repeated restarts in a short window, killed right after
   startup), say so as a hypothesis; these tools do not expose memory/CPU stats directly, so state that
   it needs confirming another way rather than asserting it.
8. If multiple containers are affected at once, check docker.compose_ps for the whole project's status
   before treating it as one container's problem.
9. Do not restart, stop, rebuild, or exec into a container; this skill only inspects.

Report format:
- Container name and current status.
- Root cause, grounded in a specific log line.
- Suggested fix, described but not applied.

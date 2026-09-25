---
name: log-investigation
description: Find the root cause of an error or incident by reading device logs, without changing anything.
metadata:
  mensarium:
    requires:
      tools: [shell.exec]
---
# Log investigation

Goal: find what actually happened from the logs, with evidence, without changing any state.

1. Establish the time window and symptom from the user (error message, affected feature, approximate
   time); ask if it is missing.
2. Locate the log source: read the project's config or Makefile with files.read if the path is not
   obvious, then use shell.exec with one read-only program per call (`tail`, `grep`, `cat`), no pipes.
3. Note the log format (structured JSON vs plain text) before searching; it changes what pattern the
   grep in the next step should look for.
4. Search first for the exact error or exception around the reported time window before reading
   everything from the start.
5. Read enough surrounding lines to see the full stack trace or request context, not just the one
   matching line.
6. Correlate: the same request/trace id across processes, timestamps just before the failure (deploy,
   restart, resource exhaustion), and any earlier warning that preceded it.
7. Cross-reference the failing code path with files.read and files.search to confirm the log message
   maps to the code you think it does.
8. Do not restart services, rotate or delete logs, or change any file; this skill only reads and
   reports.
9. If the logs do not contain enough evidence to conclude, say so instead of guessing the root cause.

Report format:
- Timeline of relevant log lines (timestamp — source — line).
- Root cause, grounded in a specific log line and code path.
- What is still unconfirmed, if anything.

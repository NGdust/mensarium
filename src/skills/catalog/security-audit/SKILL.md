---
name: security-audit
description: Review code for genuine security issues, ordered by severity, without changing anything.
metadata:
  mensarium:
    requires:
      tools: [files.list, files.search, git.status, git.diff, files.read, shell.exec]
---
# Security audit

Goal: find real, exploitable security issues — not style nits — without modifying anything.

1. Map the attack surface with files.list and files.search: entry points (HTTP/CLI handlers), places
   that parse or deserialize input, subprocess or shell invocations, file path handling, auth/crypto
   code, and anywhere secrets or tokens are read.
2. If the scope is "review pending changes", use git.status and git.diff to focus there first.
3. Read every candidate file fully with files.read before judging it — do not flag from a filename or
   import alone.
4. Look specifically for: injection (shell, SQL, path traversal), hardcoded credentials, unsafe
   deserialization (pickle, unrestricted yaml.load, eval), missing authn/authz checks, weak or
   home-grown crypto, and unvalidated external input reaching a sensitive sink.
5. For an agent-harness codebase, also check: does untrusted data (model output, tool results, RAG,
   file contents) ever get treated as instructions or as a source of IDs and permissions instead of
   the trusted core; do secrets ever reach prompts, logs or the untrusted side.
6. For every candidate, trace the data flow from source to sink by reading the actual code path before
   reporting it. Drop anything you cannot confirm this way.
7. Stay read-only: do not run scanners or exploit attempts via shell.exec unless explicitly asked.

Stop once the mapped surface is covered. Report findings ordered by severity: `path:line` — the issue —
concrete exploit scenario — suggested fix. Skip praise and unconfirmed guesses.

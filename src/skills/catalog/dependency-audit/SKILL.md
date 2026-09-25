---
name: dependency-audit
description: Review project dependencies for risk — outdated, unused or duplicated — without installing anything.
metadata:
  mensarium:
    requires:
      tools: [files.list, files.search, files.read, shell.exec]
---
# Dependency audit

Goal: flag risky dependencies using only what is verifiable in the repo, without installing anything.

1. Find manifest files with files.list and files.search: package.json, requirements*.txt,
   pyproject.toml, go.mod, Cargo.toml or equivalent, and read each with files.read.
2. Read the matching lockfile if present, to see resolved versions rather than ranges.
3. For each direct dependency, use files.search to find where it is imported; flag anything declared
   but never referenced in the code.
4. Never run an installer, updater or anything that touches the lockfile (no install/update commands)
   — a single read-only inspection command via shell.exec is fine if one is already available.
5. Note dependencies pinned far behind their declared range, duplicated libraries doing the same job,
   and direct dependencies that look like they should be transitive.
6. Do not report a CVE or known vulnerability from memory — only report what the manifest itself shows
   (version, license, duplication), unless the user supplies a vulnerability list to check against.
7. Keep findings tied to a concrete file and line in the manifest.

Stop once every manifest and lockfile is read. Report a short table: package, version, why it is
flagged, suggested action. Skip anything you could not confirm from the files.

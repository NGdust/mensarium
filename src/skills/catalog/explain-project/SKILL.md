---
name: explain-project
description: Explain what the project or a module does and how it works, grounded in the actual code.
metadata:
  mensarium:
    requires:
      tools: [files.read, files.list, files.search, git.status, git.diff]
---
# Explain the project

Goal: give an accurate, plain-language explanation of what the code actually does.

1. Start with files.read on any top-level docs (README, CLAUDE.md-equivalent) and files.list on the
   root to see the overall layout.
2. Use files.search to find the entry point (main, CLI, server startup) for the area in question.
3. Read the key modules with files.read and follow one real call path from entry point to output,
   noting which layer calls which (handler, business logic, data access, external adapters).
4. Identify the main abstractions (a handful of core types or services) and how they relate — do not
   list every file, focus on what explains the behavior.
5. If asked about current work in progress, use git.status and git.diff to describe what is changing.
6. Verify every claim by reading the implementation it is about; do not explain based on a function or
   file name alone.
7. Note any invariant or constraint the code enforces that a newcomer would otherwise miss.

Stop once you can describe the primary flow end-to-end and the top-level boundaries. Report in plain
language: purpose, layout and architecture, the main flow with the files involved, and where to look
next for related work.

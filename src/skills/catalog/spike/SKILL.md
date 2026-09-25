---
name: spike
description: Run a throwaway experiment to test a technical hypothesis and report a verdict with evidence.
metadata:
  mensarium:
    requires:
      tools: [shell.exec]
---
# Spike

Goal: answer a concrete technical question fast with a real experiment, then leave no trace behind.

1. State the hypothesis as a yes/no or measurable question before running anything, e.g. "does library
   X support Y" or "is approach A faster than B for this input size".
2. Design the smallest experiment that can falsify it: a short script or a single command, never a
   feature implementation.
3. Run each step with shell.exec, one program per call, no pipes; explain in one sentence what that
   call is testing before running it.
4. Read the actual output and error text, not just the exit code; a failing call is itself evidence,
   read why it failed.
5. Iterate at most a few times, changing one variable at a time, to isolate what actually matters.
6. Capture the concrete evidence (output, timing, error text) for the report as you go.
7. Delete every file the spike created with shell.exec before finishing, and confirm with git.status
   that the working tree is exactly as it was before you started.
8. If something cannot be fully cleaned up (e.g. a package installed globally, a process left running),
   say so explicitly in the report instead of leaving it undocumented.
9. Do not commit, push, add a dependency, or leave any new file behind, and do not modify existing
   project files.

Report format:
- The hypothesis.
- Verdict: confirmed / refuted / inconclusive, in one line.
- Evidence: the exact commands run and the output that supports the verdict.
- What was cleaned up, and anything that could not be.

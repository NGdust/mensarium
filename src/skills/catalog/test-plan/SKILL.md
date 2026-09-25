---
name: test-plan
description: Write a concrete test plan and test cases for a feature or change, without writing test code.
---
# Test plan

Goal: produce a concrete, executable test plan for a feature or change, grounded in actual behavior.

1. If testing a change, use git.status and git.diff to see exactly what changed; otherwise use
   files.search and files.read to find the feature's entry point and read it fully.
2. Trace the code path (handler, business logic, data access) to find every branch: the normal case,
   each validation rule, each error path, boundary values.
3. Find existing tests for the same area with files.search and read a couple with files.read, to reuse
   the project's own test vocabulary and avoid duplicating covered cases.
4. Write cases covering: the happy path, each edge case found in step 2, error handling, and any
   concurrency or idempotency concern visible in the code.
5. For each case state: preconditions, the exact action or input, and the expected observable result,
   not "it should work".
6. Mark which cases are unit-testable versus which need integration or manual verification (a real
   device, an external service, or the UI).
7. For every boundary spotted in validation code (min/max length, zero, negative, empty, off-by-one),
   write it as its own case instead of folding it into the happy path.
8. Order cases by risk: put the ones most likely to break, or most costly if they do, first.
9. Note any test data or fixture the plan depends on that does not already exist in the project.
10. Do not write or run test code; this skill only plans.

Report format:
- Grouped case list: area — case — preconditions — steps — expected result.
- A short note on what existing coverage already handles, so it is not duplicated.
- Any new fixture or test data the plan assumes.

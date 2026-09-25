---
name: api-review
description: Review a REST or GraphQL API's design for consistency, error handling and breaking changes.
---
# API review

Goal: review an API's shape for consistency and correctness, grounded in the actual route or resolver code.

1. Use files.search to find the route or resolver definitions and their request/response schemas or
   types.
2. Read each endpoint's implementation fully with files.read: input validation, status codes, error
   responses, auth checks.
3. Check consistency across endpoints: naming (plural/singular, casing), pagination style, error
   response shape, status code usage, versioning scheme.
4. Check error handling: every failure path (validation, not found, auth, downstream failure) returns
   a defined, documented shape instead of an unhandled exception leaking internals.
5. If reviewing a change, use git.status and git.diff to see exactly what changed, and check whether it
   breaks an existing client: removed/renamed field, changed type, changed required-ness, changed
   status code.
6. Check that any documented contract (OpenAPI/GraphQL schema, README) matches what the code actually
   does; flag drift between docs and implementation as its own finding.
7. Check authorization consistency: two endpoints exposing the same resource should enforce the same
   access rule, unless the difference is deliberate and documented.
8. Verify each finding by reading the code path it depends on; drop anything you cannot confirm.
9. Do not modify the API or its tests; this skill only reviews.

Report format:
- One-line verdict (consistent / needs changes).
- Findings ordered by severity: endpoint — what is wrong — concrete client impact — suggested fix.
- A short "breaking changes" list if reviewing a diff.
- A short "docs vs code drift" list if any was found.

---
name: migration-plan
description: Write a step-by-step migration plan for a schema, API or data change, with rollback per step.
---
# Migration plan

Goal: produce a concrete, reviewable migration plan grounded in the current code, not a generic template.

1. Use files.search and files.read to find the current schema, model or API contract being migrated,
   and every place that reads or writes it (queries, serializers, callers).
2. Use files.search to find existing migration files and read a couple of recent ones with files.read
   to match the project's own migration tooling and naming convention.
3. List every breaking change the migration introduces: renamed or removed fields, changed types,
   changed defaults, changed response shape.
4. For each breaking change, list every caller or consumer found in step 1 that must change with it.
5. Order the steps to avoid downtime: additive changes first (new nullable column, new endpoint
   version), then backfill, then switch reads, then switch writes, remove the old path last.
6. Write an explicit rollback for each step: what to run or revert if that step fails partway through.
7. Estimate the blast radius of each step from what the schema and code show: how much data it touches
   and whether it can run online or needs a lock or downtime window.
8. Flag anything needing a maintenance window, a manual backfill script, or coordination with another
   service; do not assume a single automatic step covers it.
9. Note which steps can run unattended and which need a human to watch and confirm before the next one
   proceeds.
10. Do not write or apply the migration itself; this skill only plans.

Report format:
- Ordered step list, each with: what changes, affected files/callers, rollback for that step.
- A separate "risks / needs coordination" section.

---
name: incident-triage
description: First-pass triage of a production incident using whichever of Sentry or Grafana is connected.
---
# Incident triage

Goal: give a fast, grounded first read on an incident using whichever observability plugin is actually
connected, without touching anything.

1. Check which tools are available on this device: if any `mcp.sentry.*` tool is present, use Sentry;
   if any `mcp.grafana.*` tool is present, use Grafana; if both are present, prefer the one the user
   names, otherwise check Sentry first for the error signal and Grafana for the metric/infra signal.
2. With Sentry tools: search for the issue (recent, matching the reported error or service) and read
   its stack trace, event count, first/last seen, and affected release.
3. With Grafana tools: query the relevant dashboards, panels or logs for the affected service around
   the reported time window; look for the metric that moved first (errors, latency, saturation) and
   any correlated deploy marker.
4. If neither is available, say so explicitly and fall back to files.read/shell.exec log reading, or
   ask the user for access, instead of fabricating a diagnosis.
5. Establish a timeline: when it started, what changed right before (deploy, config, traffic spike),
   and the blast radius (which service, endpoint or customers).
6. Cross-check the suspected root cause against the actual source with files.read and files.search
   before stating it as the cause.
7. Do not resolve, mute, silence or acknowledge the alert or issue, and do not change any config; this
   skill only triages.

Report format:
- Severity and blast radius.
- Timeline of what happened.
- Likely root cause, with the evidence (stack trace / metric / log line) it rests on.
- What is still unknown, and what would confirm it.

---
name: diagram
description: Produce a Mermaid diagram of the code's architecture, flow or data model, read from the code.
---
# Diagram

Goal: produce an accurate Mermaid diagram of the requested view, grounded in the real code.

1. Use files.list to see the project layout, then files.search to find the modules, classes or calls
   relevant to the requested view.
2. Read the key files fully with files.read; never diagram from file or function names alone, follow
   the actual calls, imports or schema.
3. Pick the smallest diagram type that answers the question: flowchart for control flow, sequence
   diagram for a request or interaction across components, classDiagram or erDiagram for a data model.
4. Keep it under 25 nodes: collapse unrelated detail into one box per module or service rather than one
   box per function, and note in the answer what was collapsed.
5. Label edges with what actually happens (call, event, query), not just a bare arrow.
6. Verify every node and edge against the code you read; drop anything you are inferring rather than
   confirming.
7. If the requested view still exceeds 25 nodes after collapsing, ask which sub-area to focus on
   instead of producing a diagram no one can read.
8. Pick a direction and layout that reads naturally for the diagram type (top-down for a flowchart,
   left-right actors for a sequence diagram) rather than an arbitrary default.
9. Do not create or modify any file; the diagram goes only in the answer.

Report format:
- One-sentence description of what the diagram shows.
- The diagram as a fenced ```mermaid``` code block.
- A short list of what was simplified or left out, if anything.
- Which files the diagram is grounded in.

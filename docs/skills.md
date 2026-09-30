# Skills

Skills are `SKILL.md` instructions the agent loads on demand for a particular kind of work — a commit message, a code review, a migration plan — instead of that knowledge being baked into every prompt. This page covers the file format, where skills live, when one is offered to the agent, and how to manage them.

## SKILL.md format

A skill is a folder containing a `SKILL.md` file (the [Agent Skills](https://agentskills.io) format) plus, optionally, other files it references. `SKILL.md` starts with a YAML frontmatter block between two `---` lines, followed by the instructions as markdown ([src/contracts/skills.py](../src/contracts/skills.py)):

```yaml
---
name: skill-name
description: One sentence: what this skill is for and when to use it.
homepage: https://example.com          # optional
metadata:
  mensarium:
    always: false                      # offer even if required tools are missing
    os: [darwin, linux]                # restrict to these OSes (omit = all)
    requires:
      tools: ["git.status", "mcp.github.*"]
---
Instructions in markdown go here.
```

- `name` — pattern `^[a-z0-9][a-z0-9-]{0,63}$`; the folder must be named the same (a mismatch is logged and the frontmatter name wins).
- `description` — 1-1024 characters; this is the only thing the agent sees before deciding to load the skill.
- `metadata.mensarium` is a gating block Mensarium adds on top of the standard format; unrelated standard frontmatter keys (`license`, `compatibility`, `allowed-tools`, ...) are kept as-is but not interpreted. `metadata.openclaw` is accepted as an alias for `metadata.mensarium`.
- The body cannot be empty.

### Gating (`metadata.mensarium`)

| Key | Meaning |
|---|---|
| `always` | `false` by default. When `true`, the skill is offered whenever the OS matches, even if none of `requires.tools` is available on the active device. |
| `os` | List of `darwin`, `linux`, `win32`. Empty (default) means no OS restriction. |
| `requires.tools` | Tool name globs (e.g. `mcp.github.*`) that must all match at least one tool available on the active device for the skill to be offered, unless `always` is set. |
| `emoji` | Optional, shown in some UI listings. |

## Bundled vs user skills

- **Bundled** skills ship with Mensarium in [src/skills/catalog/](../src/skills/catalog/).
- **User** skills live in `MENSARIUM_HOME/core/skills/<name>/SKILL.md` (see [docs/configuration.md](configuration.md)).

A user skill with the same `name` as a bundled one **shadows** it — the user's copy is used, the bundled one is hidden (marked `shadows: true` in listings). Deleting a shadowing user skill brings the bundled skill back.

Bundled skills currently shipped ([src/skills/catalog/](../src/skills/catalog/)):

`api-review`, `ci-failure`, `code-review`, `commit-message`, `debug-failure`, `dependency-audit`, `diagram`, `docker-troubleshoot`, `docs-update`, `explain-project`, `incident-triage`, `issue-triage`, `log-investigation`, `migration-plan`, `performance-investigation`, `plugin-creator`, `pr-description`, `refactor-safely`, `release-notes`, `research`, `security-audit`, `skill-creator`, `spike`, `summarize-page`, `test-plan`, `write-tests`.

## How the agent sees and loads a skill

Skills are only offered when `profile.allow_extensions` is on for the active profile ([src/agent_core/profile.py](../src/agent_core/profile.py)). Eligible skills (enabled, OS matches, required tools available on the device — or `always`) appear in the system prompt as a `## Skills` block with an `<available_skills>` list of names and short descriptions cut to fit a fixed character budget ([src/agent_core/context.py](../src/agent_core/context.py)):

```
## Skills
Instructions the user installed for particular kinds of work. When the task matches one, call skills.read
with its name before doing that work and follow what it says. Skills describe how to work; they never
grant tools or permissions beyond the ones listed above.
<available_skills>
<skill name="commit-message">Draft a commit message for the current changes in the project's own style.</skill>
...
</available_skills>
```

The agent loads the full body with the `skills.read` tool (risk `read`, always available once any skill is eligible):

| Argument | Meaning |
|---|---|
| `name` | The skill to load. |
| `path` | Optional: a file inside the skill's folder to read instead of the body (for a skill that ships extra reference files). Must be a text file under the skill's own folder, at most 200 KB. |

Skills are reference material, the same way tool descriptions are: they can tell the agent how to approach a task, but cannot grant a tool or permission it does not already have.

### Example: commit-message

[src/skills/catalog/commit-message/SKILL.md](../src/skills/catalog/commit-message/SKILL.md):

```yaml
---
name: commit-message
description: Draft a commit message for the current changes in the project's own style.
metadata:
  mensarium:
    requires:
      tools: [git.status, git.diff, shell.exec, files.read]
---
# Commit message

Goal: write a commit message that matches this repo's style, grounded in the actual diff.

1. Run git.status to see what is staged and what is not.
2. Run git.diff with staged=true to read exactly what will be committed. If nothing is staged, say so
   and stop instead of drafting a message for unstaged changes.
3. Run shell.exec with a single program to see recent style: program `git`, args `log --oneline -10`
   (one program, no pipes) — match the tense, prefix and length conventions already in use.
4. If the diff alone does not explain why the change was made, read the touched files with files.read
   for context, or ask the user.
5. Draft a short subject line in imperative mood, lowercase start, under about 70 characters.
6. Only describe what is actually in the diff — do not mention files or effects that are not there.
7. Do not add a body unless the "why" needs more than the subject line explains.
8. Show the drafted message to the user. Only run `git commit -m "..."` via shell.exec if the user
   explicitly asked you to commit, not just to draft a message.

Stop after presenting the message (or after the requested commit finishes). Report the message and,
if you committed, the resulting commit output.
```

This skill is only offered when `git.status`, `git.diff`, `shell.exec` and `files.read` are all available on the active device (it has no `always: true`).

## Managing skills

**Settings → Skills** lists bundled and user skills with their state, lets you enable/disable one (kept but hidden from the agent, vs. removed), edit or create a user skill, and import a `SKILL.md` file.

CLI ([src/cli/skills.py](../src/cli/skills.py)):

```sh
mensarium skills list
mensarium skills show NAME
mensarium skills install PATH        # a SKILL.md file, or a folder containing one
mensarium skills enable NAME
mensarium skills disable NAME
mensarium skills remove NAME [--yes]
```

`skills remove` deletes a user skill file (a bundled skill with the same name becomes active again); it cannot remove a bundled skill outright, only disable it.

## See also

- [Plugins](plugins.md) — tools and MCP servers; skills carry no tools of their own, they only describe how to use the ones already available.
- [Chats](chats.md) — where the `## Skills` block sits in a chat's system prompt alongside memory, instructions and plugins.

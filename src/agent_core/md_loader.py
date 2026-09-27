import os
import asyncio

async def load_md_docs(project: dict | None, target: dict) -> str:
    """Load markdown instruction files and return a combined string.
    Global files are searched in the current working directory of the server.
    Project‑specific AGENTS.md is read from the project's workdir if provided.
    Missing files are ignored.
    """
    sections: list[str] = []
    # Global instruction files (relative to the repository root)
    cwd = os.getcwd()
    for name in ["AGENTS.md", "SOUL.md", "IDENTITY.md", "USER.md", "MEMORY.md"]:
        path = os.path.join(cwd, name)
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    txt = f.read().strip()
                if txt:
                    sections.append(f"## {name}\n{txt}")
            except Exception:
                # ignore read errors – they will be logged by the caller if needed
                pass
    # Project‑specific AGENTS.md (if a project workdir is known)
    if project:
        workdir = project.get("workdir")
        if workdir:
            proj_path = os.path.join(workdir, "AGENTS.md")
            if os.path.isfile(proj_path):
                try:
                    with open(proj_path, "r", encoding="utf-8") as f:
                        txt = f.read().strip()
                    if txt:
                        sections.append("## Project AGENTS.md\n" + txt)
                except Exception:
                    pass
    return "\n\n".join(sections)


def load_md_docs_sync(project: dict | None, target: dict) -> str:
    """Synchronous wrapper for load_md_docs used in the sync system‑prompt builder."""
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(load_md_docs(project, target))

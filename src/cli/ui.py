import asyncio
import selectors
import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()

LOGO = r"""
 __  __ _____ _   _ ____    _    ____  ___ _   _ __  __
|  \/  | ____| \ | / ___|  / \  |  _ \|_ _| | | |  \/  |
| |\/| |  _| |  \| \___ \ / _ \ | |_) || || | | | |\/| |
| |  | | |___| |\  |___) / ___ \|  _ < | || |_| | |  | |
|_|  |_|_____|_| \_|____/_/   \_\_| \_\___|\___/|_|  |_|
"""


def banner(subtitle: str) -> None:
    text = Text(LOGO, style="bold cyan")
    text.append(f"\n  {subtitle}", style="dim")
    console.print(text)


def step(n: int, total: int, title: str) -> None:
    console.print()
    console.rule(f"[bold]Step {n}/{total}[/bold]  {title}", align="left", style="cyan")


def ok(msg: str) -> None:
    console.print(f"[green]✅[/green] {msg}")


def warn(msg: str) -> None:
    console.print(f"[yellow]⚠️[/yellow]  {msg}")


def fail(msg: str) -> None:
    console.print(f"[red]❌[/red] {msg}")


def summary(title: str, rows: list[tuple[str, str]], footer: str = "") -> None:
    width = max(len(k) for k, _ in rows)
    body = Text()
    for k, v in rows:
        body.append(f"{k.ljust(width)}  ", style="dim")
        body.append(f"{v}\n", style="bold")
    if footer:
        body.append(f"\n{footer}", style="")
    console.print(Panel(body, title=title, border_style="green", padding=(1, 2)))


def use_select_event_loop() -> None:
    """macOS kqueue cannot poll /dev/tty, which is stdin under `curl | sh`; prompt_toolkit then sees EOF."""
    if sys.platform != "darwin":
        return

    class _Policy(asyncio.DefaultEventLoopPolicy):
        def new_event_loop(self) -> asyncio.AbstractEventLoop:
            return asyncio.SelectorEventLoop(selectors.SelectSelector())

    asyncio.set_event_loop_policy(_Policy())

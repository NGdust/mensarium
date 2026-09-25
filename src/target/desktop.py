"""Desktop of the device: screenshots, windows, mouse, keyboard, apps and volume through the platform's own tools.

macOS: screencapture, sips and osascript (System Events), cliclick when installed. Linux: grim/scrot/gnome-screenshot,
xdotool/ydotool, wmctrl, xdg-open, pactl/amixer. Nothing here bypasses the OS permission prompts."""

import asyncio
import base64
import ctypes
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

MAC = sys.platform == "darwin"
DESKTOP_TOOLS = ("screen.capture", "screen.windows", "input.mouse", "input.type", "input.key", "app.open", "system.volume")
MAC_KEY_CODES = {
    "enter": 36, "return": 36, "tab": 48, "space": 49, "backspace": 51, "delete": 51, "escape": 53, "esc": 53,
    "left": 123, "right": 124, "down": 125, "up": 126, "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
    "forwarddelete": 117, "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100,
    "f9": 101, "f10": 109, "f11": 103, "f12": 111,
}  # fmt: skip
MAC_MODIFIERS = {"cmd": "command", "command": "command", "ctrl": "control", "control": "control", "alt": "option", "option": "option", "shift": "shift"}
X_KEYS = {
    "enter": "Return", "return": "Return", "tab": "Tab", "space": "space", "backspace": "BackSpace", "delete": "Delete",
    "escape": "Escape", "esc": "Escape", "left": "Left", "right": "Right", "down": "Down", "up": "Up", "home": "Home",
    "end": "End", "pageup": "Prior", "pagedown": "Next", "cmd": "super", "command": "super", "ctrl": "ctrl", "control": "ctrl",
    "alt": "alt", "option": "alt", "shift": "shift",
}  # fmt: skip
ACCESSIBILITY_HINT = (
    " Allow Accessibility (and Screen Recording) for Python in System Settings -> Privacy & Security, "
    "or run `mensarium target permissions` on the device."
)


class DesktopError(Exception):
    pass


def which(*names: str) -> str | None:
    for name in names:
        if found := shutil.which(name):
            return found
    return None


def available_tools() -> list[str]:
    tools: list[str] = []
    if MAC:
        if which("screencapture"):
            tools.append("screen.capture")
        if which("osascript"):
            tools += ["screen.windows", "input.mouse", "input.type", "input.key", "app.open", "system.volume"]
        return tools
    if which("grim", "scrot", "gnome-screenshot", "import", "spectacle"):
        tools.append("screen.capture")
    if which("wmctrl", "xdotool"):
        tools.append("screen.windows")
    if which("xdotool", "ydotool"):
        tools += ["input.mouse", "input.type", "input.key"]
    if which("xdg-open"):
        tools.append("app.open")
    if which("pactl", "amixer"):
        tools.append("system.volume")
    return tools


# ---- permissions ---------------------------------------------------------------


def _mac_lib(name: str) -> Any:
    return ctypes.cdll.LoadLibrary(f"/System/Library/Frameworks/{name}.framework/{name}")


def permissions() -> dict[str, bool | None]:
    """screen: may capture the screen; input: may drive mouse and keyboard. None when the platform cannot tell."""
    if not MAC:
        return {
            "screen": bool(which("grim", "scrot", "gnome-screenshot", "import", "spectacle")),
            "input": bool(which("xdotool", "ydotool")),
        }
    out: dict[str, bool | None] = {"screen": None, "input": None}
    try:
        cg = _mac_lib("CoreGraphics")
        cg.CGPreflightScreenCaptureAccess.restype = ctypes.c_bool
        out["screen"] = bool(cg.CGPreflightScreenCaptureAccess())
    except (OSError, AttributeError):
        pass
    try:
        ax = _mac_lib("ApplicationServices")
        ax.AXIsProcessTrusted.restype = ctypes.c_bool
        out["input"] = bool(ax.AXIsProcessTrusted())
    except (OSError, AttributeError):
        pass
    return out


def request_permissions() -> dict[str, bool | None]:
    """Ask macOS for Screen Recording and Accessibility: the system shows its own dialogs for this process."""
    if MAC:
        try:
            cg = _mac_lib("CoreGraphics")
            cg.CGRequestScreenCaptureAccess.restype = ctypes.c_bool
            cg.CGRequestScreenCaptureAccess()
        except (OSError, AttributeError):
            pass
        try:
            cf, ax = _mac_lib("CoreFoundation"), _mac_lib("ApplicationServices")
            key = ctypes.c_void_p.in_dll(ax, "kAXTrustedCheckOptionPrompt")
            true = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")
            keys = (ctypes.c_void_p * 1)(key.value)
            values = (ctypes.c_void_p * 1)(true.value)
            cf.CFDictionaryCreate.restype = ctypes.c_void_p
            cf.CFDictionaryCreate.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
            key_cb = ctypes.addressof(ctypes.c_char.in_dll(cf, "kCFTypeDictionaryKeyCallBacks"))
            value_cb = ctypes.addressof(ctypes.c_char.in_dll(cf, "kCFTypeDictionaryValueCallBacks"))
            options = cf.CFDictionaryCreate(None, keys, values, 1, key_cb, value_cb)
            ax.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
            ax.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
            ax.AXIsProcessTrustedWithOptions(options)
        except (OSError, AttributeError, ValueError):
            pass
    return permissions()


def ensure_permissions(marker: Path, version: str) -> dict[str, bool | None]:
    """Request the desktop permissions once per installed version: after install and after every update."""
    state: dict[str, Any] = {}
    try:
        state = json.loads(marker.read_text())
    except (OSError, ValueError):
        pass
    if state.get("asked_version") == version and not state.get("reask"):
        return permissions()
    granted = request_permissions()
    try:
        marker.write_text(json.dumps({"asked_version": version, "permissions": granted}, ensure_ascii=False))
    except OSError:
        pass
    return granted


# ---- helpers -------------------------------------------------------------------


async def run(argv: list[str], timeout: float = 30, stdin: str | None = None) -> str:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin.encode() if stdin is not None else None), timeout)
    except TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise DesktopError(f"{Path(argv[0]).name} timed out") from e
    if proc.returncode != 0:
        text = (err or out).decode(errors="replace").strip()
        if "assistive access" in text or "-1719" in text or "(-25211)" in text:
            text += ACCESSIBILITY_HINT
        elif "could not create image" in text:
            text += " Screen Recording is not allowed for the agent, or it runs outside the user's desktop session." + ACCESSIBILITY_HINT
        raise DesktopError(f"{Path(argv[0]).name}: {text[:400] or f'exit {proc.returncode}'}")
    return out.decode(errors="replace")


async def osascript(script: str, *args: str) -> str:
    binary = which("osascript")
    if not binary:
        raise DesktopError("osascript is not available")
    argv = [binary]
    for line in script.strip("\n").splitlines():
        argv += ["-e", line]
    if args:
        argv += ["--", *args]
    return (await run(argv, timeout=30)).rstrip("\n")


# ---- screen --------------------------------------------------------------------


async def capture(display: int, max_width: int) -> dict[str, Any]:
    """A JPEG of one display, downscaled to `max_width`, as base64 with its size."""
    with tempfile.TemporaryDirectory(prefix="mensarium-shot-") as tmp:
        raw = Path(tmp) / "shot.png"
        out = Path(tmp) / "shot.jpg"
        if MAC:
            argv = [which("screencapture") or "screencapture", "-x", "-t", "png"]
            if display > 1:
                argv += ["-D", str(display)]
            await run([*argv, str(raw)], timeout=30)
            await run([which("sips") or "sips", "--resampleWidth", str(max_width), "-s", "format", "jpeg", "-s", "formatOptions", "70", str(raw), "--out", str(out)], timeout=60)
            info = await run([which("sips") or "sips", "-g", "pixelWidth", "-g", "pixelHeight", str(out)], timeout=15)
            width = _num(info, r"pixelWidth:\s*(\d+)")
            height = _num(info, r"pixelHeight:\s*(\d+)")
        else:
            if tool := which("grim"):
                await run([tool, "-o" if display > 1 else "-c", str(raw)] if False else [tool, str(raw)], timeout=30)
            elif tool := which("scrot"):
                await run([tool, "-o", str(raw)], timeout=30)
            elif tool := which("gnome-screenshot"):
                await run([tool, "-f", str(raw)], timeout=30)
            elif tool := which("spectacle"):
                await run([tool, "-b", "-n", "-o", str(raw)], timeout=30)
            elif tool := which("import"):
                await run([tool, "-window", "root", str(raw)], timeout=30)
            else:
                raise DesktopError("no screenshot tool found: install grim, scrot or gnome-screenshot")
            convert = which("magick", "convert")
            if convert:
                await run([convert, str(raw), "-resize", f"{max_width}x>", "-quality", "70", str(out)], timeout=60)
                info = await run([which("identify") or convert, "-format", "%w %h", str(out)], timeout=15) if which("identify") else ""
                width, height = (_num(info, r"^(\d+)"), _num(info, r"^\d+ (\d+)")) if info else (None, None)
            else:
                out, width, height = raw, None, None
        data = out.read_bytes()
        if len(data) > 6_000_000:
            raise DesktopError("screenshot is too large; lower max_width")
        return {
            "mime": "image/jpeg" if out.suffix == ".jpg" else "image/png",
            "data": base64.b64encode(data).decode(),
            "width": width,
            "height": height,
        }


def _num(text: str, pattern: str) -> int | None:
    m = re.search(pattern, text, re.M)
    return int(m.group(1)) if m else None


async def windows() -> str:
    if MAC:
        script = """
tell application "System Events"
  set out to ""
  try
    set out to "frontmost: " & (name of first application process whose frontmost is true) & linefeed
  end try
  repeat with p in (application processes whose background only is false)
    set pname to name of p
    repeat with w in windows of p
      try
        set {x, y} to position of w
        set {wd, ht} to size of w
        set out to out & pname & " | " & (name of w) & " | at " & x & "," & y & " size " & wd & "x" & ht & linefeed
      end try
    end repeat
  end repeat
  return out
end tell
"""
        text = await osascript(script)
        return text.strip() or "(no windows visible)"
    if tool := which("wmctrl"):
        return (await run([tool, "-lG"], timeout=15)).strip() or "(no windows)"
    if tool := which("xdotool"):
        active = (await run([tool, "getactivewindow", "getwindowname"], timeout=15)).strip()
        return f"active: {active}"
    raise DesktopError("no window tool found: install wmctrl or xdotool")


# ---- input ---------------------------------------------------------------------


async def mouse(action: str, x: int, y: int, scroll: int) -> str:
    if MAC:
        if tool := which("cliclick"):
            if action == "scroll":
                raise DesktopError("cliclick cannot scroll; use input.key with up/down or pagedown instead")
            op = {"move": "m", "click": "c", "double_click": "dc", "right_click": "rc"}[action]
            await run([tool, f"{op}:{x},{y}"], timeout=15)
            return f"{action} at {x},{y}"
        if action == "click":
            await osascript(f'tell application "System Events" to click at {{{x}, {y}}}')
            return f"click at {x},{y}"
        raise DesktopError(f"{action} needs cliclick on macOS: brew install cliclick (only plain clicks work without it)")
    if tool := which("xdotool"):
        if action == "scroll":
            button = "5" if scroll > 0 else "4"
            await run([tool, "mousemove", str(x), str(y), "click", "--repeat", str(min(abs(scroll), 50)), "--delay", "20", button], timeout=20)
            return f"scrolled {scroll} at {x},{y}"
        argv = [tool, "mousemove", str(x), str(y)]
        if action == "click":
            argv += ["click", "1"]
        elif action == "double_click":
            argv += ["click", "--repeat", "2", "--delay", "80", "1"]
        elif action == "right_click":
            argv += ["click", "3"]
        await run(argv, timeout=15)
        return f"{action} at {x},{y}"
    if tool := which("ydotool"):
        await run([tool, "mousemove", "--absolute", "-x", str(x), "-y", str(y)], timeout=15)
        if action in ("click", "double_click", "right_click"):
            code = "0xC1" if action == "right_click" else "0xC0"
            await run([tool, "click", *(["--repeat", "2"] if action == "double_click" else []), code], timeout=15)
        elif action == "scroll":
            raise DesktopError("ydotool cannot scroll here; use input.key with up/down")
        return f"{action} at {x},{y}"
    raise DesktopError("no input tool found: install xdotool")


async def type_text(text: str) -> str:
    if MAC:
        await osascript('on run argv\ntell application "System Events" to keystroke (item 1 of argv)\nend run', text)
    elif tool := which("xdotool"):
        await run([tool, "type", "--delay", "15", "--", text], timeout=120)
    elif tool := which("ydotool"):
        await run([tool, "type", "--", text], timeout=120)
    else:
        raise DesktopError("no input tool found: install xdotool")
    return f"typed {len(text)} characters"


async def key(combo: str) -> str:
    parts = [p.strip().lower() for p in re.split(r"[+\s]+", combo.strip()) if p.strip()]
    if not parts:
        raise DesktopError("empty key combination")
    mods, main = parts[:-1], parts[-1]
    if MAC:
        using = ", ".join(f"{MAC_MODIFIERS[m]} down" for m in mods if m in MAC_MODIFIERS)
        if len(mods) != len([m for m in mods if m in MAC_MODIFIERS]):
            raise DesktopError(f"unknown modifier in {combo!r}; use cmd, ctrl, alt, shift")
        suffix = f" using {{{using}}}" if using else ""
        if main in MAC_KEY_CODES:
            await osascript(f'tell application "System Events" to key code {MAC_KEY_CODES[main]}{suffix}')
        elif len(main) == 1:
            await osascript(f'on run argv\ntell application "System Events" to keystroke (item 1 of argv){suffix}\nend run', main)
        else:
            raise DesktopError(f"unknown key {main!r}")
        return f"pressed {combo}"
    if tool := which("xdotool"):
        names = [X_KEYS.get(p, p) for p in parts]
        await run([tool, "key", "--clearmodifiers", "+".join(names)], timeout=15)
        return f"pressed {combo}"
    if tool := which("ydotool"):
        raise DesktopError("key combinations need xdotool; ydotool support is not implemented")
    raise DesktopError("no input tool found: install xdotool")


# ---- apps and sound ------------------------------------------------------------


async def open_target(target: str) -> str:
    is_url = re.match(r"^[a-z][a-z0-9+.-]*://", target) is not None
    if MAC:
        opener = which("open") or "open"
        argv = [opener, target] if is_url or Path(target).expanduser().exists() else [opener, "-a", target]
        await run(argv, timeout=30)
        return f"opened {target}"
    if tool := which("xdg-open"):
        if not is_url and not Path(target).expanduser().exists():
            if app := which(target):
                await asyncio.create_subprocess_exec(app, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL, start_new_session=True)
                return f"started {target}"
            raise DesktopError(f"{target!r} is not a URL, a file or a program on PATH")
        await run([tool, target], timeout=30)
        return f"opened {target}"
    raise DesktopError("no opener found: install xdg-utils")


async def volume(action: str, level: int | None) -> str:
    if MAC:
        if action == "set":
            await osascript(f"set volume output volume {level}")
        elif action in ("mute", "unmute"):
            await osascript(f"set volume output muted {'true' if action == 'mute' else 'false'}")
        text = await osascript("set s to get volume settings\nreturn (output volume of s as text) & \"|\" & (output muted of s as text)")
        vol, _, muted = text.partition("|")
        return f"output volume {vol}%, muted: {muted}"
    if tool := which("pactl"):
        sink = "@DEFAULT_SINK@"
        if action == "set":
            await run([tool, "set-sink-volume", sink, f"{level}%"], timeout=15)
        elif action in ("mute", "unmute"):
            await run([tool, "set-sink-mute", sink, "1" if action == "mute" else "0"], timeout=15)
        vol = (await run([tool, "get-sink-volume", sink], timeout=15)).strip().splitlines()[0]
        muted = (await run([tool, "get-sink-mute", sink], timeout=15)).strip()
        return f"{vol}; {muted}"
    if tool := which("amixer"):
        if action == "set":
            await run([tool, "sset", "Master", f"{level}%"], timeout=15)
        elif action in ("mute", "unmute"):
            await run([tool, "sset", "Master", action], timeout=15)
        return (await run([tool, "sget", "Master"], timeout=15)).strip()
    raise DesktopError("no mixer found: install pulseaudio-utils or alsa-utils")

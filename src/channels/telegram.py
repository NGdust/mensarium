"""Telegram Bot API over HTTPS. The token lives only in this client and is cut out of every error text."""

import html
import os
import re
from typing import Any

import httpx

API = os.environ.get("MENSARIUM_TELEGRAM_API", "https://api.telegram.org")
MESSAGE_LIMIT = 3500
CAPTION_LIMIT = 1024
TOKEN = re.compile(r"^\d+:[\w-]{20,}$")
COMMANDS = [
    ("new", "Start a new chat"),
    ("stop", "Stop the current task"),
    ("status", "What the agent is doing"),
    ("whoami", "Your Telegram id"),
    ("help", "How to use the bot"),
]

Button = dict[str, str]


class TelegramError(Exception):
    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class TelegramApi:
    def __init__(self, token: str, base_url: str = API) -> None:
        self.token = token
        self._client = httpx.AsyncClient(base_url=f"{base_url}/bot{token}/", timeout=httpx.Timeout(75, connect=15))

    async def aclose(self) -> None:
        await self._client.aclose()

    def _safe(self, text: str) -> str:
        return text.replace(self.token, "***")

    async def call(self, method: str, files: dict[str, tuple[str, bytes]] | None = None, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v is not None}
        try:
            if files:
                res = await self._client.post(method, data={k: str(v) for k, v in params.items()}, files=files)
            else:
                res = await self._client.post(method, json=params)
        except httpx.HTTPError as e:
            raise TelegramError(self._safe(f"{type(e).__name__}: {e}")) from e
        try:
            data = res.json()
        except ValueError as e:
            raise TelegramError(f"unexpected reply from Telegram (HTTP {res.status_code})") from e
        if not isinstance(data, dict) or not data.get("ok"):
            description = data.get("description") if isinstance(data, dict) else None
            code = data.get("error_code") if isinstance(data, dict) else None
            raise TelegramError(self._safe(str(description or "unknown error")), code)
        return data["result"]

    async def get_me(self) -> dict[str, Any]:
        me: dict[str, Any] = await self.call("getMe")
        return me

    async def prepare(self) -> None:
        """Long polling needs no webhook; the command menu lets the owner discover the bot's commands."""
        await self.call("deleteWebhook")
        await self.call("setMyCommands", commands=[{"command": c, "description": d} for c, d in COMMANDS])

    async def get_updates(self, offset: int, timeout: int = 30) -> list[dict[str, Any]]:
        updates: list[dict[str, Any]] = await self.call(
            "getUpdates", offset=offset, timeout=timeout, allowed_updates=["message", "callback_query"]
        )
        return updates

    async def send(self, chat_id: int, text: str, buttons: list[list[Button]] | None = None) -> int:
        """Send HTML text; if Telegram cannot parse it, the same text goes out plain rather than not at all."""
        markup = {"inline_keyboard": buttons} if buttons else None
        try:
            msg = await self.call(
                "sendMessage", chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=markup,
                link_preview_options={"is_disabled": True},
            )
        except TelegramError as e:
            if "parse" not in str(e).lower():
                raise
            msg = await self.call("sendMessage", chat_id=chat_id, text=strip_tags(text), reply_markup=markup)
        return int(msg["message_id"])

    async def send_photo(self, chat_id: int, photo: bytes, filename: str, caption: str | None = None) -> int:
        """Upload a picture with an optional HTML caption; a caption Telegram cannot parse goes out plain."""
        files = {"photo": (filename, photo)}
        try:
            msg = await self.call("sendPhoto", files, chat_id=chat_id, caption=caption, parse_mode="HTML" if caption else None)
        except TelegramError as e:
            if not caption or "parse" not in str(e).lower():
                raise
            msg = await self.call("sendPhoto", files, chat_id=chat_id, caption=strip_tags(caption))
        return int(msg["message_id"])

    async def edit(self, chat_id: int, message_id: int, text: str, buttons: list[list[Button]] | None = None) -> None:
        markup = {"inline_keyboard": buttons or []}
        try:
            await self.call(
                "editMessageText", chat_id=chat_id, message_id=message_id, text=text, parse_mode="HTML", reply_markup=markup,
                link_preview_options={"is_disabled": True},
            )
        except TelegramError as e:
            if "not modified" not in str(e):
                raise

    async def clear_buttons(self, chat_id: int, message_id: int) -> None:
        await self.call("editMessageReplyMarkup", chat_id=chat_id, message_id=message_id, reply_markup={"inline_keyboard": []})

    async def delete(self, chat_id: int, message_id: int) -> None:
        try:
            await self.call("deleteMessage", chat_id=chat_id, message_id=message_id)
        except TelegramError:
            pass

    async def typing(self, chat_id: int) -> None:
        await self.call("sendChatAction", chat_id=chat_id, action="typing")

    async def answer_callback(self, callback_id: str, text: str) -> None:
        try:
            await self.call("answerCallbackQuery", callback_query_id=callback_id, text=text[:200])
        except TelegramError:
            pass


# ---- text ------------------------------------------------------------------

esc = html.escape


def strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", text))


def render(text: str) -> str:
    """Markdown the model writes, as the HTML subset Telegram accepts. Code fences become <pre> blocks."""
    out: list[str] = []
    parts = re.split(r"```[ \t]*(\w*)[ \t]*\n(.*?)```", text, flags=re.S)
    for i in range(0, len(parts), 3):
        out.append(_block(parts[i]))
        if i + 2 < len(parts):
            attr = f' class="language-{parts[i + 1]}"' if parts[i + 1] else ""
            out.append(f"<pre><code{attr}>{esc(parts[i + 2].rstrip())}</code></pre>")
    return "".join(out).strip()


def _block(text: str) -> str:
    lines: list[str] = []
    table: list[str] = []

    def flush() -> None:
        if table:
            lines.append("<pre>" + "\n".join(table) + "</pre>")
            table.clear()

    for line in text.split("\n"):
        if line.lstrip().startswith("|"):
            table.append(esc(line))
            continue
        flush()
        lines.append(_line(line))
    flush()
    return "\n".join(lines)


def _line(line: str) -> str:
    if m := re.match(r"^\s{0,3}#{1,6}\s+(.*?)\s*#*$", line):
        return f"<b>{_spans(m.group(1))}</b>"
    line = re.sub(r"^(\s*)[-*+]\s+", "\\1• ", line)
    line = re.sub(r"^(\s*)>\s?", "\\1", line)
    return _spans(line)


def _spans(text: str) -> str:
    parts = re.split(r"(`[^`\n]+`)", text)
    for i, p in enumerate(parts):
        if i % 2:
            parts[i] = f"<code>{esc(p[1:-1])}</code>"
            continue
        p = esc(p)
        p = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r'<a href="\2">\1</a>', p)
        p = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", p)
        p = re.sub(r"__(.+?)__", r"<b>\1</b>", p)
        p = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", p)
        p = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<i>\1</i>", p)
        p = re.sub(r"~~(.+?)~~", r"<s>\1</s>", p)
        parts[i] = p
    return "".join(parts)


def chunks(text: str, limit: int = MESSAGE_LIMIT) -> list[str]:
    """Pieces of markdown that fit one message: cut at a blank line when one is near, never inside a code fence."""
    lines = [piece for line in text.split("\n") for piece in (re.findall(f".{{1,{limit - 8}}}", line) or [""])]
    out: list[str] = []
    buf: list[str] = []
    opened: list[bool] = []
    fence = False
    size = 0
    for line in lines:
        if buf and size + len(line) + 1 > limit:
            blanks = [i for i in range(1, len(buf)) if not buf[i].strip() and not opened[i]]
            cut = blanks[-1] if blanks and blanks[-1] > len(buf) // 3 else len(buf)
            head, buf = buf[:cut], buf[cut:]
            reopen = opened[cut] if cut < len(opened) else fence
            opened = opened[cut:]
            if reopen:
                head.append("```")
                buf.insert(0, "```")
                opened.insert(0, False)
            out.append("\n".join(head))
            size = sum(len(x) + 1 for x in buf)
        opened.append(fence)
        if line.startswith("```"):
            fence = not fence
        buf.append(line)
        size += len(line) + 1
    if buf:
        out.append("\n".join(buf))
    return out

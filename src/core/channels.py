"""Channels: the owner talks to the agent from a messenger. Telegram: a bot token, bound to the first account that writes."""

import asyncio
import contextlib
import logging
from pathlib import Path
from typing import Any

from mensarium.channels.telegram import (
    CAPTION_LIMIT,
    TOKEN,
    Button,
    TelegramApi,
    TelegramError,
    chunks,
    esc,
    render,
    strip_tags,
)
from mensarium.contracts.channels import ChannelState, TelegramBot, TelegramConfig, TelegramOwner
from mensarium.contracts.protocol import AccessMode
from mensarium.core.config import CorePaths, read_secret, write_secret
from mensarium.core.events import EventBus
from mensarium.core.orchestrator import Orchestrator, TaskError
from mensarium.core.repo import TERMINAL_STATUSES, Repo
from mensarium.shared.timeutil import now_iso, parse_iso, utcnow

log = logging.getLogger(__name__)

SETTING = "channels.telegram"
TOKEN_SECRET = "channel-telegram-token"
PROFILE = "coding-agent-v1"
DRAFT_LINES = 6
HELP = (
    "Write a task and the agent works on it on your device; the reply and approval buttons come here.\n\n"
    "/new — start a new chat\n"
    "/stop — stop the current task\n"
    "/status — what the agent is doing\n"
    "/whoami — your Telegram id"
)
DECIDED = {"approved": "✅ Approved", "rejected": "❌ Rejected", "expired": "⏳ Expired, not executed"}


class ChannelError(Exception):
    pass


class ChannelManager:
    def __init__(self, repo: Repo, paths: CorePaths, workspace_id: str, orchestrator: Orchestrator, bus: EventBus) -> None:
        self.repo = repo
        self.paths = paths
        self.workspace_id = workspace_id
        self.orchestrator = orchestrator
        self.bus = bus
        self.telegram: TelegramChannel | None = None

    # ---- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        cfg = await self.load()
        token = read_secret(self.paths, f"secret://{TOKEN_SECRET}")
        if token and cfg.enabled and cfg.bot:
            self.telegram = TelegramChannel(self, token, cfg)
            self.telegram.start()

    async def stop(self) -> None:
        if self.telegram:
            await self.telegram.stop()
            self.telegram = None

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    # ---- state --------------------------------------------------------------

    async def load(self) -> TelegramConfig:
        return TelegramConfig.model_validate(await self.repo.get_setting(SETTING) or {})

    async def save(self, cfg: TelegramConfig) -> None:
        await self.repo.set_setting(SETTING, cfg.model_dump())
        if self.telegram:
            self.telegram.refresh(cfg)

    async def view(self) -> dict[str, Any]:
        cfg = await self.load()
        configured = cfg.bot is not None and read_secret(self.paths, f"secret://{TOKEN_SECRET}") is not None
        ch = self.telegram
        state: ChannelState = "off"
        if configured and cfg.enabled:
            state = ch.state if ch else "connecting"
        task = await self.repo.get_task(cfg.task_id) if cfg.task_id else None
        return {
            "id": "telegram",
            "configured": configured,
            "enabled": cfg.enabled,
            "state": state,
            "error": ch.error if ch else None,
            "bot": cfg.bot.model_dump() if cfg.bot else None,
            "owner": cfg.owner.model_dump() if cfg.owner else None,
            "target_id": cfg.target_id,
            "mode": cfg.mode,
            "task": {"id": task["id"], "input": task["input"], "status": task["status"]} if task else None,
        }

    # ---- settings -----------------------------------------------------------

    async def configure(
        self, token: str | None, enabled: bool | None, target_id: str | None, mode: AccessMode | None
    ) -> dict[str, Any]:
        cfg = await self.load()
        if token is not None:
            token = token.strip()
            if not TOKEN.match(token):
                raise ChannelError("this does not look like a bot token; BotFather gives one like 123456789:AbCdEf...")
            api = TelegramApi(token)
            try:
                me = await api.get_me()
            except TelegramError as e:
                raise ChannelError(f"Telegram rejected the token: {e}") from e
            finally:
                await api.aclose()
            bot = TelegramBot(id=int(me["id"]), username=me.get("username") or "", name=me.get("first_name") or "")
            if cfg.bot and cfg.bot.id != bot.id:
                cfg.owner = None
                cfg.task_id = None
            write_secret(self.paths, TOKEN_SECRET, token)
            cfg.bot = bot
            cfg.enabled = True if enabled is None else enabled
            await self.repo.audit(self.workspace_id, "user", "channel.configured", {"channel": "telegram", "bot": bot.username})
        if enabled is not None:
            cfg.enabled = enabled
            await self.repo.audit(self.workspace_id, "user", "channel.toggled", {"channel": "telegram", "enabled": enabled})
        if target_id is not None:
            if target_id:
                target = await self.repo.get_target(target_id)
                if not target or target["status"] == "revoked":
                    raise ChannelError("unknown device")
            cfg.target_id = target_id or None
        if mode is not None:
            cfg.mode = mode
        await self.save(cfg)
        if token is not None or enabled is not None:
            await self.restart()
        return await self.view()

    async def unbind(self) -> dict[str, Any]:
        cfg = await self.load()
        if cfg.owner and self.telegram:
            await self.telegram.farewell()
        cfg.owner = None
        cfg.task_id = None
        await self.save(cfg)
        await self.repo.audit(self.workspace_id, "user", "channel.unbound", {"channel": "telegram"})
        return await self.view()

    async def remove(self) -> None:
        await self.stop()
        (self.paths.secrets / TOKEN_SECRET).unlink(missing_ok=True)
        await self.repo.set_setting(SETTING, {})
        await self.repo.audit(self.workspace_id, "user", "channel.removed", {"channel": "telegram"})

    async def pick_target(self, cfg: TelegramConfig) -> str | None:
        if cfg.target_id:
            return cfg.target_id
        for t in await self.repo.list_targets():
            if t["status"] != "revoked":
                return str(t["id"])
        return None


class TelegramChannel:
    """One bot, one owner, one current chat: messages become tasks, task events come back as messages."""

    def __init__(self, manager: ChannelManager, token: str, cfg: TelegramConfig) -> None:
        self.m = manager
        self.api = TelegramApi(token)
        self.cfg = cfg
        self.state: ChannelState = "connecting"
        self.error: str | None = None
        self.offset = 0
        self.poller: asyncio.Task[None] | None = None
        self.relay: asyncio.Task[None] | None = None
        self.queue: asyncio.Queue[dict[str, Any]] | None = None
        self.task_id: str | None = None
        self.typing: asyncio.Task[None] | None = None
        self.draft: int | None = None
        self.draft_lines: list[str] = []
        self.approvals: dict[str, tuple[int, str]] = {}

    def start(self) -> None:
        self.poller = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self.detach()
        if self.poller:
            self.poller.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.poller
        await self.api.aclose()

    @property
    def chat_id(self) -> int | None:
        return self.cfg.owner.user_id if self.cfg.owner else None

    def refresh(self, cfg: TelegramConfig) -> None:
        """Settings changed in the UI: apply them without dropping the connection."""
        self.cfg = cfg
        if self.state in ("ready", "waiting_owner"):
            self.state = "ready" if cfg.owner else "waiting_owner"
        if cfg.task_id != self.task_id:
            self.detach()
            if cfg.task_id:
                self.attach(cfg.task_id)

    # ---- polling ------------------------------------------------------------

    async def run(self) -> None:
        delay = 1.0
        prepared = False
        if self.cfg.task_id:
            self.attach(self.cfg.task_id)
        while True:
            try:
                if not prepared:
                    await self.api.prepare()
                    prepared = True
                    self.error = None
                    self.state = "ready" if self.cfg.owner else "waiting_owner"
                updates = await self.api.get_updates(self.offset)
            except TelegramError as e:
                self.error, self.state = str(e), "error"
                if e.code == 401:
                    log.warning("telegram token rejected; the channel stopped")
                    return
                if e.code == 409:
                    self.error = f"another program polls this bot (a webhook or a second Core): {e}"
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            except Exception:
                log.exception("telegram polling crashed")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            delay = 1.0
            self.error = None
            self.state = "ready" if self.cfg.owner else "waiting_owner"
            for update in updates:
                self.offset = int(update["update_id"]) + 1
                try:
                    await self.handle(update)
                except TelegramError as e:
                    log.warning("telegram update failed", extra={"error": str(e)})
                except Exception:
                    log.exception("telegram update crashed")

    async def handle(self, update: dict[str, Any]) -> None:
        if msg := update.get("message"):
            await self.on_message(msg)
        elif cq := update.get("callback_query"):
            await self.on_callback(cq)

    # ---- inbound ------------------------------------------------------------

    async def on_message(self, msg: dict[str, Any]) -> None:
        user = msg.get("from") or {}
        if (msg.get("chat") or {}).get("type") != "private" or not user or user.get("is_bot"):
            return
        text = (msg.get("text") or msg.get("caption") or "").strip()
        if self.cfg.owner is None:
            await self.bind(user)
            if text.startswith("/"):
                return
        elif int(user["id"]) != self.cfg.owner.user_id:
            log.info("telegram message from a stranger ignored", extra={"user_id": user.get("id")})
            return
        if not text:
            await self.say("Only text messages are supported for now.")
        elif text.startswith("/"):
            await self.command(text.split()[0].split("@")[0].lower())
        else:
            await self.dispatch(text)

    async def bind(self, user: dict[str, Any]) -> None:
        name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x)
        self.cfg.owner = TelegramOwner(user_id=int(user["id"]), name=name, username=user.get("username"), bound_at=now_iso())
        await self.m.save(self.cfg)
        self.state = "ready"
        await self.m.repo.audit(self.m.workspace_id, "core", "channel.bound", {"channel": "telegram", "user_id": user["id"], "name": name})
        await self.say(
            f"Bound to <b>{esc(name)}</b> (id {user['id']}). Nobody else can use this bot; "
            f"unbind it in Settings → Channels.\n\n{HELP}"
        )

    async def farewell(self) -> None:
        with contextlib.suppress(TelegramError):
            await self.say("This bot was unbound from your account in Mensarium.")

    async def command(self, cmd: str) -> None:
        if cmd in ("/start", "/help"):
            await self.say(HELP)
        elif cmd == "/whoami":
            owner = self.cfg.owner
            await self.say(f"{esc(owner.name)} · id {owner.user_id}" if owner else "unbound")
        elif cmd == "/new":
            self.cfg.task_id = None
            await self.m.save(self.cfg)
            await self.say("New chat. What should the agent do?")
        elif cmd == "/stop":
            task = await self.current_task()
            if task and self.running(task):
                with contextlib.suppress(TaskError):
                    await self.m.orchestrator.cancel(task["id"])
                await self.say("Stopping.")
            else:
                await self.say("Nothing is running.")
        elif cmd == "/status":
            await self.status()
        else:
            await self.say(f"Unknown command. {HELP}")

    async def status(self) -> None:
        task = await self.current_task()
        if not task:
            await self.say("No chat yet. Write a task to start one.")
            return
        title = (task["input"] or "").split("\n")[0][:80]
        await self.say(
            f"<b>{esc(title)}</b> · {esc(str(task['status']).lower())}"
            + (f" ({esc(task['status_reason'])})" if task.get("status_reason") else "")
            + f"\nDevice: {esc(task.get('target_name') or task['target_id'])} · mode: {task['mode']}"
            + f" · model: {esc(task.get('model') or 'default')}"
        )

    async def current_task(self) -> dict[str, Any] | None:
        if not self.cfg.task_id:
            return None
        task = await self.m.repo.get_task(self.cfg.task_id)
        if task is None:
            self.cfg.task_id = None
            await self.m.save(self.cfg)
        return task

    def running(self, task: dict[str, Any]) -> bool:
        return task["id"] in self.m.orchestrator.runners or task["status"] not in TERMINAL_STATUSES

    async def dispatch(self, text: str) -> None:
        task = await self.current_task()
        try:
            if task and self.running(task):
                await self.say("⏳ Still working on the previous message. Wait for the reply or send /stop.")
                return
            if task:
                self.attach(task["id"])
                await self.m.orchestrator.post_message(task["id"], text)
            else:
                target_id = await self.m.pick_target(self.cfg)
                if not target_id:
                    await self.say("No device to work on. Pair one in Settings → Devices.")
                    return
                task = await self.m.orchestrator.create_task(PROFILE, target_id, text, self.cfg.mode)
                self.cfg.task_id = task["id"]
                await self.m.save(self.cfg)
                self.attach(task["id"])
        except TaskError as e:
            await self.say(f"❌ {esc(str(e))}")
            return
        self.begin_turn()

    async def on_callback(self, cq: dict[str, Any]) -> None:
        user = cq.get("from") or {}
        if not self.cfg.owner or int(user.get("id", 0)) != self.cfg.owner.user_id:
            await self.api.answer_callback(cq["id"], "This bot belongs to someone else.")
            return
        kind, _, rest = str(cq.get("data") or "").partition(":")
        approval_id, _, decision = rest.partition(":")
        if kind != "apr" or decision not in ("approve", "reject"):
            await self.api.answer_callback(cq["id"], "Unknown button.")
            return
        try:
            await self.m.orchestrator.decide(approval_id, decision, None, confirm=True)
            await self.api.answer_callback(cq["id"], "Approved, running." if decision == "approve" else "Rejected.")
        except TaskError as e:
            await self.api.answer_callback(cq["id"], str(e))
            if (msg := cq.get("message")) and self.chat_id:
                await self.api.clear_buttons(self.chat_id, int(msg["message_id"]))

    # ---- task events --------------------------------------------------------

    def attach(self, task_id: str) -> None:
        if self.task_id == task_id and self.relay and not self.relay.done():
            return
        self.detach()
        self.task_id = task_id
        self.queue = self.m.bus.subscribe(task_id)
        self.relay = asyncio.create_task(self._relay(self.queue))

    def detach(self) -> None:
        if self.task_id and self.queue:
            self.m.bus.unsubscribe(self.task_id, self.queue)
        if self.relay:
            self.relay.cancel()
        self.task_id = self.queue = self.relay = None
        self.end_turn()
        self.approvals.clear()

    async def _relay(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        while True:
            ev = await queue.get()
            try:
                await self.on_event(ev["event"], ev["payload"])
            except TelegramError as e:
                log.warning("telegram delivery failed", extra={"event": ev["event"], "error": str(e)})
            except Exception:
                log.exception("telegram relay crashed", extra={"event": ev["event"]})

    async def on_event(self, name: str, p: dict[str, Any]) -> None:
        if name == "agent.event":
            inner, payload = str(p.get("event")), dict(p.get("payload") or {})
            if inner == "tool_call.pending_approval":
                await self.ask_approval(payload)
            elif inner == "approval.decided":
                await self.settle_approval(payload)
            return
        if name == "task.final":
            await self.finish()
            await self.reply(p.get("text") or "", p.get("image_artifact_id"))
        elif name == "tool_call.pending_approval":
            await self.ask_approval(p)
        elif name == "approval.decided":
            await self.settle_approval(p)
        elif name == "secret.requested":
            await self.say(f"The agent asks for secret {esc(str(p.get('name') or ''))}. Open this chat in the web interface to enter it.")
        elif name == "tool_call.executing":
            await self.progress(p.get("display") or p.get("tool") or "")
        elif name == "task.status":
            await self.on_status(str(p.get("status")), str(p.get("reason") or ""))
        elif name == "task.error":
            await self.say(f"❌ {esc(str(p.get('message') or 'error'))}")
        elif name == "task.note":
            await self.say(f"⚠️ {esc(str(p.get('message') or ''))}")

    async def on_status(self, status: str, reason: str) -> None:
        if status == "CANCELED":
            await self.finish()
            await self.say("⛔ Stopped.")
        elif status == "PAUSED":
            await self.finish()
            await self.say(f"⏸ Paused: {esc(reason) or 'no reason given'}. Write a message to continue.")
        elif status in ("FAILED", "FAILED_RECOVERABLE"):
            await self.finish()
            await self.say(f"❌ Failed: {esc(reason) or 'no reason given'}. Write a message to try again.")

    async def ask_approval(self, p: dict[str, Any]) -> None:
        if not self.chat_id:
            return
        tc = p.get("tool_call") or {}
        args = tc.get("arguments") or {}
        risk = str(tc.get("risk") or "")
        left = max(0, int((parse_iso(p["expires_at"]) - utcnow()).total_seconds() // 60)) if p.get("expires_at") else None
        text = f"<b>Approval needed</b> · {esc(risk)}\n{esc(str(tc.get('display') or tc.get('tool') or ''))}"
        if cmd := args.get("command"):
            text += f"\n<pre>{esc(str(cmd))}</pre>"
        if prompt := str(args.get("prompt") or ""):
            text += f"\n<pre>{esc(prompt[:3000])}{'…' if len(prompt) > 3000 else ''}</pre>"
        text += f"\nTool: <code>{esc(str(tc.get('tool') or ''))}</code> · Device: {esc(str(tc.get('target_name') or ''))}"
        if left is not None:
            text += f"\nExpires in {left} min"
        approval_id = str(p["approval_id"])
        run = "✅ Run once (irreversible)" if risk == "destructive" else "✅ Run once"
        buttons: list[list[Button]] = [[
            {"text": run, "callback_data": f"apr:{approval_id}:approve"},
            {"text": "❌ Reject", "callback_data": f"apr:{approval_id}:reject"},
        ]]
        self.end_turn()
        self.approvals[approval_id] = (await self.api.send(self.chat_id, text, buttons), text)

    async def settle_approval(self, p: dict[str, Any]) -> None:
        decision = str(p.get("decision"))
        if decision == "approved":
            self.begin_turn()
        entry = self.approvals.pop(str(p.get("approval_id")), None)
        if entry and self.chat_id:
            message_id, text = entry
            await self.api.edit(self.chat_id, message_id, f"{text}\n\n{DECIDED.get(decision, decision)}")

    # ---- outbound -----------------------------------------------------------

    def begin_turn(self) -> None:
        self.end_turn()
        self.typing = asyncio.create_task(self._typing())

    def end_turn(self) -> None:
        if self.typing:
            self.typing.cancel()
            self.typing = None

    async def _typing(self) -> None:
        while True:
            if self.chat_id:
                with contextlib.suppress(TelegramError):
                    await self.api.typing(self.chat_id)
            await asyncio.sleep(4)

    async def progress(self, line: str) -> None:
        if not self.chat_id:
            return
        self.draft_lines = [*self.draft_lines, line][-DRAFT_LINES:]
        text = "⏳ Working…\n" + "\n".join(f"• {esc(x)}" for x in self.draft_lines)
        if self.draft is None:
            self.draft = await self.api.send(self.chat_id, text)
        else:
            await self.api.edit(self.chat_id, self.draft, text)

    async def finish(self) -> None:
        self.end_turn()
        if self.draft is not None and self.chat_id:
            await self.api.delete(self.chat_id, self.draft)
        self.draft = None
        self.draft_lines = []

    async def reply(self, markdown: str, image: str | None = None) -> None:
        """The reply text; a screenshot from the turn goes first, with the text as its caption when it fits."""
        if not self.chat_id:
            return
        parts = [render(part) or "(empty reply)" for part in chunks(markdown) or [""]]
        if image and (path := self.screenshot(image)):
            caption = parts[0] if len(parts) == 1 and len(strip_tags(parts[0])) <= CAPTION_LIMIT else None
            try:
                await self.api.send_photo(self.chat_id, await asyncio.to_thread(path.read_bytes), path.name, caption)
                if caption:
                    return
            except TelegramError as e:
                log.warning("telegram screenshot delivery failed", extra={"error": str(e)})
        for text in parts:
            await self.api.send(self.chat_id, text)

    def screenshot(self, artifact_id: str) -> Path | None:
        return next((p for s in (".jpg", ".png") if (p := self.m.paths.artifacts / f"{artifact_id}{s}").exists()), None)

    async def say(self, html_text: str) -> None:
        if self.chat_id:
            await self.api.send(self.chat_id, html_text)

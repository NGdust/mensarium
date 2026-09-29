"""Browser push: Web Push (RFC 8030) with a VAPID key (RFC 8292) and aes128gcm payloads (RFC 8291), sent to the
owner's browsers when a chat waits for approval, finishes or fails. Works while the UI tab is closed."""

import asyncio
import base64
import hashlib
import json
import logging
import os
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from mensarium.contracts.push import PushConfig, PushSubscription
from mensarium.core.config import CorePaths, read_secret, write_secret
from mensarium.core.events import EventBus
from mensarium.core.repo import Repo
from mensarium.shared.timeutil import now_iso

log = logging.getLogger(__name__)

SETTING = "push"
KEY_SECRET = "push-vapid-key"
SUBJECT = "https://mensarium.com"
TTL_S = 3600
RECORD_SIZE = 4096
MAX_SUBSCRIPTIONS = 20
TEXTS = {
    "en": {"approval": "Approval needed: {0}", "finished": "Done", "failed": "Failed: {0}", "test": "Notifications work"},
    "ru": {"approval": "Нужно подтверждение: {0}", "finished": "Готово", "failed": "Ошибка: {0}", "test": "Уведомления работают"},
}


class PushError(Exception):
    pass


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def point(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(hashes.SHA256(), length, salt, info).derive(ikm)


def encrypt(
    payload: bytes, p256dh: str, auth: str, salt: bytes | None = None, key: ec.EllipticCurvePrivateKey | None = None
) -> bytes:
    """One aes128gcm record for the browser's key; salt and key are fixed only by tests."""
    ua_public = unb64(p256dh)
    salt = salt or os.urandom(16)
    key = key or ec.generate_private_key(ec.SECP256R1())
    as_public = point(key.public_key())
    shared = key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))
    ikm = hkdf(unb64(auth), shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    cek = hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    header = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(as_public)]) + as_public
    return header + AESGCM(cek).encrypt(nonce, payload + b"\x02", None)


def vapid(key: ec.EllipticCurvePrivateKey, endpoint: str) -> str:
    """The Authorization header: an ES256 JWT for the push service's origin."""
    u = urlparse(endpoint)
    head = b64(json.dumps({"typ": "JWT", "alg": "ES256"}).encode())
    claims = b64(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": SUBJECT}).encode())
    r, s = decode_dss_signature(key.sign(f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256())))
    return f"vapid t={head}.{claims}.{b64(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}, k={b64(point(key.public_key()))}"


def sub_id(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()[:16]


class PushManager:
    def __init__(self, repo: Repo, paths: CorePaths, bus: EventBus) -> None:
        self.repo = repo
        self.paths = paths
        self.bus = bus
        self.key = self._load_key()
        self.pending: set[asyncio.Task[None]] = set()
        bus.listeners.append(self.on_event)

    def _load_key(self) -> ec.EllipticCurvePrivateKey:
        pem = read_secret(self.paths, f"secret://{KEY_SECRET}")
        if pem:
            key = serialization.load_pem_private_key(pem.encode(), None)
            if isinstance(key, ec.EllipticCurvePrivateKey):
                return key
        key = ec.generate_private_key(ec.SECP256R1())
        pem_bytes = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
        write_secret(self.paths, KEY_SECRET, pem_bytes.decode())
        return key

    async def stop(self) -> None:
        for t in list(self.pending):
            t.cancel()

    # ---- state --------------------------------------------------------------

    async def load(self) -> PushConfig:
        return PushConfig.model_validate(await self.repo.get_setting(SETTING) or {})

    async def save(self, cfg: PushConfig) -> None:
        await self.repo.set_setting(SETTING, cfg.model_dump())

    async def view(self) -> dict[str, Any]:
        cfg = await self.load()
        return {
            "public_key": b64(point(self.key.public_key())),
            "approvals": cfg.approvals,
            "finished": cfg.finished,
            "subscriptions": [
                {"id": sub_id(s.endpoint), "endpoint": s.endpoint, "agent": s.agent, "created_at": s.created_at} for s in cfg.subscriptions
            ],
        }

    async def configure(self, approvals: bool | None, finished: bool | None) -> dict[str, Any]:
        cfg = await self.load()
        if approvals is not None:
            cfg.approvals = approvals
        if finished is not None:
            cfg.finished = finished
        await self.save(cfg)
        return await self.view()

    async def subscribe(self, endpoint: str, p256dh: str, auth: str, lang: str, agent: str) -> dict[str, Any]:
        try:
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64(p256dh))
            if len(unb64(auth)) != 16:
                raise ValueError
        except ValueError as e:
            raise PushError("the browser sent a malformed subscription key") from e
        cfg = await self.load()
        subs = [s for s in cfg.subscriptions if s.endpoint != endpoint]
        subs.append(PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth, lang=lang, agent=agent, created_at=now_iso()))
        cfg.subscriptions = subs[-MAX_SUBSCRIPTIONS:]
        await self.save(cfg)
        return await self.view()

    async def unsubscribe(self, subscription_id: str) -> None:
        cfg = await self.load()
        cfg.subscriptions = [s for s in cfg.subscriptions if sub_id(s.endpoint) != subscription_id]
        await self.save(cfg)

    async def test(self, subscription_id: str) -> None:
        cfg = await self.load()
        sub = next((s for s in cfg.subscriptions if sub_id(s.endpoint) == subscription_id), None)
        if sub is None:
            raise PushError("subscription not found")
        await self.send(sub, {"title": "Mensarium", "body": texts(sub)["test"], "tag": "test"})

    # ---- delivery -----------------------------------------------------------

    def on_event(self, task_id: str, event: str, payload: dict[str, Any]) -> None:
        """Called for every stored event; a sub-agent's approval reaches the parent's stream as agent.event."""
        if task_id in self.bus.parents:
            return
        if event == "agent.event" and payload.get("event") == "tool_call.pending_approval":
            kind, payload = "approval", dict(payload.get("payload") or {})
        elif event == "tool_call.pending_approval":
            kind = "approval"
        elif event == "secret.requested":
            kind, payload = "approval", {"tool_call": {"display": f"secret {payload.get('name')}"}}
        elif event == "task.final":
            kind = "finished"
        elif event == "task.status" and payload.get("status") in ("FAILED", "FAILED_RECOVERABLE"):
            kind = "failed"
        else:
            return
        t = asyncio.create_task(self.notify(task_id, kind, payload))
        self.pending.add(t)
        t.add_done_callback(self.pending.discard)

    async def notify(self, task_id: str, kind: str, payload: dict[str, Any]) -> None:
        cfg = await self.load()
        if not cfg.subscriptions or not (cfg.approvals if kind == "approval" else cfg.finished):
            return
        task = await self.repo.get_task(task_id)
        if task is None or (kind != "approval" and task.get("automation_id")):
            return
        title = (str(task.get("input") or "").split("\n")[0] or "Mensarium")[:80]
        for sub in cfg.subscriptions:
            t = texts(sub)
            if kind == "approval":
                tc = payload.get("tool_call") or {}
                body = t["approval"].format(tc.get("display") or tc.get("tool") or "")
            elif kind == "failed":
                body = t["failed"].format(payload.get("reason") or "")
            else:
                body = " ".join(str(payload.get("text") or "").split()) or t["finished"]
            message = {"title": title, "body": body[:200], "task_id": task_id, "tag": f"{task_id}:{kind}"}
            try:
                await self.send(sub, message, urgent=kind == "approval")
            except PushError as e:
                log.warning("push delivery failed", extra={"subscription": sub_id(sub.endpoint), "error": str(e)})

    async def send(self, sub: PushSubscription, message: dict[str, Any], urgent: bool = False) -> None:
        body = encrypt(json.dumps(message, ensure_ascii=False).encode(), sub.p256dh, sub.auth)
        headers = {
            "Authorization": vapid(self.key, sub.endpoint),
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            "TTL": str(TTL_S),
            "Urgency": "high" if urgent else "normal",
        }
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                r = await http.post(sub.endpoint, content=body, headers=headers)
        except httpx.HTTPError as e:
            raise PushError(f"push service unreachable: {e or type(e).__name__}") from e
        if r.status_code in (404, 410):
            await self.unsubscribe(sub_id(sub.endpoint))
            raise PushError("the browser no longer accepts this subscription; turn notifications on again")
        if r.status_code >= 400:
            raise PushError(f"push service answered {r.status_code}: {r.text[:200]}")


def texts(sub: PushSubscription) -> dict[str, str]:
    return TEXTS.get(sub.lang, TEXTS["en"])

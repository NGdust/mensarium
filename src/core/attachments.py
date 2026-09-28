"""Files the user attaches to a chat message.

The type comes from the bytes, never from the browser: images by their signature, PDF and DOCX by theirs, and
anything that strictly decodes as UTF-8 counts as text. The file is stored under its artifact id, its text is
extracted once here and travels with the user's step, so the model never touches the file itself."""

import asyncio
import hashlib
import logging
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from xml.etree import ElementTree

from pydantic import BaseModel, Field

from mensarium.shared.ids import new_id

MAX_FILE_BYTES = 12 * 1024 * 1024
MAX_FILES = 10
MAX_TEXT_CHARS = 60_000
MAX_PDF_PAGES = 200
MAX_DOCX_XML_BYTES = 32 * 1024 * 1024
MAX_NAME_CHARS = 120
UNBOUND_TTL_S = 24 * 3600

AttachmentType = Literal["image", "pdf", "docx", "text"]

IMAGE_SIGNATURES: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png", ".png"),
    (b"\xff\xd8\xff", "image/jpeg", ".jpg"),
    (b"GIF87a", "image/gif", ".gif"),
    (b"GIF89a", "image/gif", ".gif"),
)


class AttachmentError(Exception):
    pass


class Attachment(BaseModel):
    """What the chat and the model know about an attached file; `text` is the content extracted when it is bound."""

    id: str
    name: str
    mime: str
    size: int
    type: AttachmentType
    text: str | None = None
    truncated: bool = False


class AttachmentIds(BaseModel):
    attachments: list[str] = Field(default_factory=list, max_length=MAX_FILES)


def safe_name(name: str) -> str:
    """The name shown in the chat: last path segment, no control characters, bounded length."""
    base = re.sub(r"[\x00-\x1f\x7f]", "", name.replace("\\", "/").rsplit("/", 1)[-1]).strip(" .")
    if len(base) > MAX_NAME_CHARS:
        stem, dot, ext = base.rpartition(".")
        base = (stem[: MAX_NAME_CHARS - len(ext) - 1] + dot + ext) if dot and len(ext) <= 12 else base[:MAX_NAME_CHARS]
    return base or "file"


def sniff(data: bytes) -> tuple[AttachmentType, str, str] | None:
    """(type, mime, suffix) of the bytes, or None when the file is not one we accept."""
    for magic, mime, suffix in IMAGE_SIGNATURES:
        if data.startswith(magic):
            return "image", mime, suffix
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image", "image/webp", ".webp"
    if data.startswith(b"%PDF"):
        return "pdf", "application/pdf", ".pdf"
    if data.startswith(b"PK\x03\x04") and _is_docx(data):
        return "docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"
    if b"\x00" not in data:
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            return None
        return "text", "text/plain", ".txt"
    return None


def _is_docx(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(BytesIO(data)) as z:
            return "word/document.xml" in z.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def _cap(text: str) -> tuple[str, bool]:
    text = text.strip()
    if len(text) <= MAX_TEXT_CHARS:
        return text, False
    return text[:MAX_TEXT_CHARS], True


def extract_text(kind: AttachmentType, data: bytes) -> tuple[str | None, bool]:
    """(text, truncated) for a text-bearing file; images have no text. Failures become a note for the model."""
    if kind == "image":
        return None, False
    if kind == "text":
        return _cap(data.decode("utf-8-sig"))
    if kind == "docx":
        return _cap(_docx_text(data))
    return _cap(_pdf_text(data))


def _docx_text(data: bytes) -> str:
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    try:
        with zipfile.ZipFile(BytesIO(data)) as z, z.open("word/document.xml") as f:
            xml = f.read(MAX_DOCX_XML_BYTES + 1)
        if len(xml) > MAX_DOCX_XML_BYTES:
            return "(document too large: text not extracted)"
        root = ElementTree.fromstring(xml)
    except (zipfile.BadZipFile, KeyError, OSError, ElementTree.ParseError):
        return "(the document could not be read: text not extracted)"
    lines = []
    for p in root.iter(f"{ns}p"):
        lines.append("".join("\t" if el.tag == f"{ns}tab" else (el.text or "") for el in p.iter() if el.tag in (f"{ns}t", f"{ns}tab")))
    return "\n".join(lines)


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return "(PDF text extraction is unavailable: the pypdf package is not installed)"
    logging.getLogger("pypdf").setLevel(logging.ERROR)
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            return "(the PDF is password-protected: text not extracted)"
        pages = []
        for i, page in enumerate(reader.pages):
            if i >= MAX_PDF_PAGES:
                pages.append(f"(only the first {MAX_PDF_PAGES} pages are shown)")
                break
            pages.append(page.extract_text() or "")
    except Exception as e:  # pypdf raises its own hierarchy plus ValueError/RecursionError on broken files
        return f"(the PDF could not be read: {type(e).__name__})"
    text = "\n\n".join(p for p in pages if p.strip())
    return text or "(the PDF has no extractable text; it may be scanned images)"


class AttachmentStore:
    def __init__(self, repo: Any, artifacts_dir: Path, workspace_id: str) -> None:
        self.repo = repo
        self.artifacts_dir = artifacts_dir
        self.workspace_id = workspace_id

    async def save(self, name: str, data: bytes) -> Attachment:
        """Validate and store an upload; it stays unbound until a message references it."""
        if not data:
            raise AttachmentError("the file is empty")
        if len(data) > MAX_FILE_BYTES:
            raise AttachmentError(f"the file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
        found = await asyncio.to_thread(sniff, data)
        if not found:
            raise AttachmentError("unsupported file type: attach an image, a PDF, a Word document or a text file")
        kind, mime, suffix = found
        artifact_id = new_id("art")
        path = self.artifacts_dir / f"{artifact_id}{suffix}"
        await asyncio.to_thread(path.write_bytes, data)
        meta = {"name": safe_name(name), "mime": mime, "type": kind}
        await self.repo.create_artifact(
            {
                "id": artifact_id,
                "workspace_id": self.workspace_id,
                "task_id": None,
                "kind": "upload",
                "uri": f"file://{path}",
                "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "metadata": meta,
            }
        )
        await self.sweep()
        return Attachment(id=artifact_id, name=meta["name"], mime=mime, size=len(data), type=kind)

    async def bind(self, task_id: str, ids: list[str]) -> list[Attachment]:
        """Attach uploads to a task's message; each upload belongs to exactly one task."""
        if len(ids) > MAX_FILES:
            raise AttachmentError(f"at most {MAX_FILES} files per message")
        out = []
        for artifact_id in dict.fromkeys(ids):
            row = await self.repo.get_artifact(artifact_id)
            if not row or row["kind"] != "upload" or row["workspace_id"] != self.workspace_id:
                raise AttachmentError(f"unknown attachment {artifact_id}")
            if row["task_id"] not in (None, task_id):
                raise AttachmentError("the attachment already belongs to another chat; upload it again")
            meta = row["metadata"] if isinstance(row["metadata"], dict) else {}
            path = Path(str(row["uri"]).removeprefix("file://"))
            kind = meta.get("type", "text")
            text, truncated = None, False
            if kind != "image":
                text, truncated = await asyncio.to_thread(extract_text, kind, await asyncio.to_thread(path.read_bytes))
            out.append(
                Attachment(
                    id=artifact_id,
                    name=str(meta.get("name") or "file"),
                    mime=str(meta.get("mime") or "application/octet-stream"),
                    size=int(row["size"]),
                    type=kind,
                    text=text,
                    truncated=truncated,
                )
            )
        for a in out:
            await self.repo.bind_artifact(a.id, task_id)
        return out

    async def sweep(self) -> None:
        """Uploads that no message ever referenced are dropped after a day."""
        for artifact_id in await self.repo.delete_unbound_uploads(UNBOUND_TTL_S):
            for path in self.artifacts_dir.glob(f"{artifact_id}.*"):
                path.unlink(missing_ok=True)

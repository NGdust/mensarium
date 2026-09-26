import fnmatch
import re
from pathlib import PurePosixPath

SECRET_FILE_PATTERNS = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "id_rsa*",
    "id_ed25519*",
    "id_ecdsa*",
    "*.kdbx",
    ".netrc",
    ".pgpass",
    "credentials",
    "credentials.json",
    ".npmrc",
    ".pypirc",
)
SECRET_DIRS = (".ssh", ".gnupg", ".aws", ".mensarium")
GIT_DIRS = (".git", "shadow.git", "repo.git", "mirror.git")

_REPLACEMENTS = [
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), "[REDACTED PRIVATE KEY]"),
    (re.compile(r"\b(sk|pk|rk)-[A-Za-z0-9_\-]{16,}"), "[REDACTED TOKEN]"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), "[REDACTED TOKEN]"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "[REDACTED TOKEN]"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}"), "[REDACTED TOKEN]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[REDACTED AWS KEY]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), "[REDACTED JWT]"),
    (
        re.compile(
            r"(?im)^(\s*[\w.\-]*(?:secret|token|password|passwd|api[_\-]?key|private[_\-]?key)[\w.\-]*\s*[:=]\s*)"
            r"(['\"]?)[^\s'\"#]{6,}\2"
        ),
        r"\1[REDACTED]",
    ),
]


def is_secret_path(path: str) -> bool:
    p = PurePosixPath(path)
    if any(part in SECRET_DIRS for part in p.parts):
        return True
    return any(fnmatch.fnmatch(p.name, pat) for pat in SECRET_FILE_PATTERNS) and p.name != ".env.example"


def redact(text: str) -> str:
    for pattern, repl in _REPLACEMENTS:
        text = pattern.sub(repl, text)
    return text

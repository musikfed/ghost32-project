from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class SecretFinding:
    path: str
    kind: str
    action: str
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "kind": self.kind,
            "action": self.action,
            "detail": self.detail,
        }


SAFE_PLACEHOLDERS = {
    "token",
    "your_token",
    "your-token",
    "your token",
    "your_api_token",
    "your-api-token",
    "changeme",
    "change-me",
    "example",
    "example-token",
    "insert-token",
    "paste-token",
    "<token>",
    "<your-token>",
    "<your_token>",
    "<redacted>",
    "***",
    "********",
}

# Strong provider-specific token signatures.
TOKEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("github-token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("gitlab-token", re.compile(r"\bglpat-[A-Za-z0-9_-]{10,}\b")),
]

# Common assignment forms. We redact only the value and keep the syntax intact.
ASSIGNMENT_PATTERN = re.compile(
    r"(?P<prefix>(?<![A-Za-z0-9_])(?:[\"']?(?:wifi[_-]?password|personal[_-]?access[_-]?token|client[_-]?secret|api[_-]?token|access[_-]?token|passphrase|password|passwd|secret)[\"']?\s*[:=]\s*[\"']))"
    r"(?P<value>[^\"'\r\n]{4,})"
    r"(?P<suffix>[\"'])",
    flags=re.IGNORECASE,
)

HEADER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "authorization-token",
        re.compile(r"(?P<prefix>Authorization\s*:\s*Bearer\s+)(?P<value>[A-Za-z0-9._~+\-/=]{12,})", re.IGNORECASE),
    ),
    (
        "api-token",
        re.compile(r"(?P<prefix>X-API-Token\s*:\s*)(?P<value>[^\s\"']{8,})", re.IGNORECASE),
    ),
    (
        "gitlab-token",
        re.compile(r"(?P<prefix>PRIVATE-TOKEN\s*:\s*)(?P<value>[^\s\"']{8,})", re.IGNORECASE),
    ),
]


def _looks_like_placeholder(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in SAFE_PLACEHOLDERS:
        return True
    if normalized.startswith("<") and normalized.endswith(">"):
        return True
    if "your_" in normalized or "your-" in normalized or "example" in normalized:
        return True
    if "change_me" in normalized or "change-me" in normalized or normalized.startswith("change_me"):
        return True
    if "твой" in normalized or "ваш" in normalized or "пример" in normalized:
        return True
    return False


def _replacement(kind: str) -> str:
    return f"<REDACTED:{kind.upper()}>"


def scrub_text(path: str, text: str, dynamic_secrets: Iterable[str] = ()) -> tuple[str, list[SecretFinding]]:
    findings: list[SecretFinding] = []
    cleaned = text

    # Exact runtime/session values are the strongest signal and are redacted first.
    for raw in dynamic_secrets:
        secret = (raw or "").strip()
        if len(secret) < 4 or _looks_like_placeholder(secret):
            continue
        count = cleaned.count(secret)
        if count:
            cleaned = cleaned.replace(secret, _replacement("session-secret"))
            findings.append(SecretFinding(path, "session-secret", "redacted", f"{count} exact occurrence(s)"))

    for kind, pattern in TOKEN_PATTERNS:
        matches = list(pattern.finditer(cleaned))
        if matches:
            cleaned = pattern.sub(_replacement(kind), cleaned)
            findings.append(SecretFinding(path, kind, "redacted", f"{len(matches)} provider token occurrence(s)"))

    def replace_assignment(match: re.Match[str]) -> str:
        value = match.group("value")
        if _looks_like_placeholder(value):
            return match.group(0)
        findings.append(SecretFinding(path, "credential-value", "redacted", "credential-like assignment"))
        return f"{match.group('prefix')}{_replacement('credential')}{match.group('suffix')}"

    cleaned = ASSIGNMENT_PATTERN.sub(replace_assignment, cleaned)

    for kind, pattern in HEADER_PATTERNS:
        def repl(match: re.Match[str], secret_kind: str = kind) -> str:
            value = match.group("value")
            if _looks_like_placeholder(value):
                return match.group(0)
            findings.append(SecretFinding(path, secret_kind, "redacted", "credential-like HTTP header"))
            return f"{match.group('prefix')}{_replacement(secret_kind)}"

        cleaned = pattern.sub(repl, cleaned)

    return cleaned, findings


def scrub_files(files: dict[str, str | bytes], dynamic_secrets: Iterable[str] = ()) -> tuple[dict[str, str | bytes], dict]:
    # EN: Binary artifacts pass through unchanged; text is inspected/redacted.
    # RU: Бинарные файлы проходят без изменений; текст проверяется и редактируется.
    cleaned: dict[str, str | bytes] = {}
    findings: list[SecretFinding] = []
    changed_files = 0
    text_files = 0
    binary_files = 0

    dynamic = tuple(secret for secret in dynamic_secrets if secret)
    for path, value in files.items():
        if isinstance(value, bytes):
            cleaned[path] = value
            binary_files += 1
            continue
        text_files += 1
        safe_text, file_findings = scrub_text(path, value, dynamic)
        cleaned[path] = safe_text
        if safe_text != value:
            changed_files += 1
        findings.extend(file_findings)

    return cleaned, {
        "enabled": True,
        "files_scanned": text_files,
        "binary_files": binary_files,
        "files_redacted": changed_files,
        "redactions": len(findings),
        "findings": [finding.as_dict() for finding in findings[:100]],
        "truncated": len(findings) > 100,
    }

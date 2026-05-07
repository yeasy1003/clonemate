"""sanitize_check — placeholder guard for open-source skill repo.

Default behaviour: scan the whole repository, excluding `.git/`, virtualenvs,
caches, build artifacts, and binary suffixes. Emit one Finding per match.
"""
from __future__ import annotations

import re
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

# Placeholder tail = 12+ uniform x/X chars (case-insensitive).
# Note: ID-type rules (ou_, oc_, etc.) enforce a 16-char minimum in their own
# pattern, so a 12-x tail is only reachable from document/minute token rules.
_PLACEHOLDER_TAIL = re.compile(r"^[xX]{12,}$")


@dataclass(frozen=True)
class Finding:
    path: Path
    line: int
    rule: str
    snippet: str


# Map rule name -> compiled pattern. Each pattern captures the suspicious token
# in group 1 so we can run a placeholder check against the captured text.
_RULES: dict[str, re.Pattern[str]] = {
    "open_id":       re.compile(r"\b(ou_[A-Za-z0-9]{16,})\b"),
    "chat_id":       re.compile(r"\b(oc_[A-Za-z0-9]{16,})\b"),
    "app_id":        re.compile(r"\b(cli_[A-Za-z0-9]{16,})\b"),
    "union_id":      re.compile(r"\b(on_[A-Za-z0-9]{16,})\b"),
    "message_id":    re.compile(r"\b(om_[A-Za-z0-9]{16,})\b"),
    "object_id":     re.compile(r"\b(obj_[A-Za-z0-9]{16,})\b"),
    "docx_token":    re.compile(r"\b((?:doxcn|doccn)[A-Za-z0-9]{12,})\b"),
    "wiki_token":    re.compile(r"\b(wikcn[A-Za-z0-9]{12,})\b"),
    "sheet_token":   re.compile(r"\b(shtcn[A-Za-z0-9]{12,})\b"),
    "base_token":    re.compile(r"\b((?:bascn|basc)[A-Za-z0-9]{12,})\b"),
    "minute_token":  re.compile(r"\b((?:omm_|mm_|mm)[A-Za-z0-9]{12,})\b"),
    "filebox_token": re.compile(r"\b(boxcn[A-Za-z0-9]{12,})\b"),
    "id_card":       re.compile(r"\b(\d{17}[\dXx])\b"),
    "phone_cn":      re.compile(r"(?<![0-9])(1\d{10})(?![0-9])"),
}


_EMAIL_RE = re.compile(r"\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b")
_ALLOWED_EMAIL_DOMAINS = {"example.com", "example.org", "example.cn", "example.io", "example.test"}


_ALLOW_LINE = re.compile(r"sanitize:\s*allow-line\b")


def _line_is_exempt(line: str) -> bool:
    return bool(_ALLOW_LINE.search(line))


def _email_is_allowed(addr: str) -> bool:
    domain = addr.split("@", 1)[1].lower() if "@" in addr else ""
    return domain in _ALLOWED_EMAIL_DOMAINS


def _is_placeholder(token: str) -> bool:
    """Token is placeholder if all alphabetic chars after the rule prefix are uniform x or X (>= 12 chars)."""
    # Strip recognised prefixes; keep the rest for placeholder check.
    for prefix in (
        "ou_", "oc_", "cli_", "on_", "om_", "obj_",
        "doxcn", "doccn", "wikcn", "shtcn", "bascn", "basc", "boxcn",
        "mm_", "mm", "omm_",
    ):
        if token.startswith(prefix):
            tail = token[len(prefix):]
            return bool(_PLACEHOLDER_TAIL.match(tail))
    return False


def _scan_text(path: Path, text: str) -> Iterator[Finding]:
    for lineno, line in enumerate(text.splitlines(), 1):
        if _line_is_exempt(line):
            continue
        for rule_name, pattern in _RULES.items():
            for match in pattern.finditer(line):
                token = match.group(1)
                if rule_name in {"id_card", "phone_cn"}:
                    yield Finding(path=path, line=lineno, rule=rule_name, snippet=line.strip())
                    continue
                if _is_placeholder(token):
                    continue
                yield Finding(path=path, line=lineno, rule=rule_name, snippet=line.strip())
        for match in _EMAIL_RE.finditer(line):
            addr = match.group(1)
            if _email_is_allowed(addr):
                continue
            yield Finding(path=path, line=lineno, rule="email", snippet=line.strip())


def scan_path(root: Path) -> list[Finding]:
    """Scan a file or directory, returning all findings."""
    if root.is_file():
        try:
            text = root.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return []
        return list(_scan_text(root, text))

    findings: list[Finding] = []
    for path in _walk(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(_scan_text(path, text))
    return findings


_EXCLUDED_DIRS = {
    ".git", ".venv", "venv", "env", "__pycache__", "node_modules",
    "dist", "build", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".eggs",
}
_EXCLUDED_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".gz", ".tar", ".pyc", ".so", ".dylib"}


def _walk(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if path.is_dir():
            continue
        if any(part in _EXCLUDED_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in _EXCLUDED_SUFFIXES:
            continue
        yield path


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    target = Path(args[0]) if args else Path.cwd()
    findings = scan_path(target)
    if not findings:
        print(f"OK: {target} clean")
        return 0
    for fi in findings:
        print(f"{fi.path}:{fi.line}: [{fi.rule}] {fi.snippet}")
    print(f"FAIL: {len(findings)} sanitize finding(s)")
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

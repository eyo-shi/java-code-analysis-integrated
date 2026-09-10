"""Parse i18n property files for Japanese labels."""

from __future__ import annotations

import codecs
from pathlib import Path


def load_i18n_messages(root: Path) -> dict[str, str]:
    messages: dict[str, str] = {}
    for path in root.rglob("application-messages_ja.properties"):
        for key, value in _parse_properties(path).items():
            messages[key] = value
    return messages


def _parse_properties(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = _decode_unicode(value.strip())
    return result


def _decode_unicode(value: str) -> str:
    try:
        return codecs.decode(value, "unicode_escape")
    except UnicodeError:
        return value

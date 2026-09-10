"""Parse business rules and validation conditions."""

from __future__ import annotations

import re
from pathlib import Path

from code_analysis.models import BusinessRuleNode, ConditionNode, Rel


PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
CLASS_RE = re.compile(r"class\s+(\w+Validator)\b")
MESSAGE_KEY_RE = re.compile(
    r"(?:code\s*=\s*[\"']([^\"']+)[\"']|rejectValue\([^,]+,\s*[\"']([^\"']+)[\"'])"
)
VALIDATION_LINE_RE = re.compile(r"^([A-Za-z][\w.]+)=(.+)$")


def parse_business_rules(
    root: Path,
    validation_messages: dict[str, str],
) -> tuple[list[BusinessRuleNode], list[ConditionNode], list[Rel], list[Rel]]:
    rules: list[BusinessRuleNode] = []
    conditions: list[ConditionNode] = []
    enforces: list[Rel] = []
    applies_to: list[Rel] = []

    for java_path in sorted(root.rglob("*Validator.java")):
        if "/test/" in str(java_path).replace("\\", "/"):
            continue
        content = java_path.read_text(encoding="utf-8", errors="ignore")
        package_match = PACKAGE_RE.search(content)
        class_match = CLASS_RE.search(content)
        if not package_match or not class_match:
            continue

        package_name = package_match.group(1)
        class_name = class_match.group(1)
        qualified_name = f"{package_name}.{class_name}"
        rule_id = f"rule:{qualified_name}"
        module = _module_from_path(str(java_path))

        rules.append(
            BusinessRuleNode(
                id=rule_id,
                name=class_name,
                qualified_name=qualified_name,
                file_path=str(java_path),
                description=_rule_description(class_name, validation_messages),
            )
        )

        if module:
            applies_to.append(Rel(from_id=rule_id, to_id=f"business:{module}"))

        for match in MESSAGE_KEY_RE.findall(content):
            message_key = match[0] or match[1]
            if not message_key:
                continue
            condition_id = f"condition:{message_key}"
            if not any(item.id == condition_id for item in conditions):
                conditions.append(
                    ConditionNode(
                        id=condition_id,
                        name=validation_messages.get(message_key, message_key),
                        expression=message_key,
                        message_key=message_key,
                    )
                )
            enforces.append(Rel(from_id=rule_id, to_id=condition_id))

    for key, message in validation_messages.items():
        if not key.startswith(("Pattern.", "Size.", "NotEquals.", "IncorrectDate.")):
            continue
        condition_id = f"condition:{key}"
        if any(item.id == condition_id for item in conditions):
            continue
        conditions.append(
            ConditionNode(
                id=condition_id,
                name=message,
                expression=key,
                message_key=key,
            )
        )

    return rules, conditions, enforces, applies_to


def load_validation_messages(root: Path) -> dict[str, str]:
    messages: dict[str, str] = {}
    for path in root.rglob("ValidationMessages_ja.properties"):
        for key, value in _parse_properties(path).items():
            messages[key] = _decode_unicode(value)
    return messages


def _parse_properties(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _decode_unicode(value: str) -> str:
    import codecs

    try:
        return codecs.decode(value, "unicode_escape")
    except UnicodeError:
        return value


def _module_from_path(path: str) -> str | None:
    marker = "/app/"
    if marker not in path:
        return None
    return path.split(marker, 1)[1].split("/", 1)[0]


def _rule_description(class_name: str, messages: dict[str, str]) -> str:
    if "PassEquals" in class_name:
        return messages.get("NotEquals.customerPass", "パスワード一致チェック")
    if "Birthday" in class_name:
        return messages.get("IncorrectDate.customerBirth", "生年月日妥当性チェック")
    if "Date" in class_name:
        return "日付妥当性チェック"
    return class_name

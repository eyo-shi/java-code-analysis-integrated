"""Parse Spring MVC form classes and fields."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from code_analysis.models import FormFieldNode, Rel


PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
CLASS_RE = re.compile(r"class\s+(\w+Form)\b")
FIELD_RE = re.compile(
    r"(?:@\w+(?:\([^)]*\))?\s*)*private\s+([\w.<>,\s\[\]]+?)\s+(\w+)\s*;",
    re.MULTILINE,
)
ANNOTATION_RE = re.compile(r"@(\w+)(?:\(([^)]*)\))?")


@dataclass
class ParsedForm:
    qualified_name: str
    simple_name: str
    module: str
    file_path: str
    fields: list[FormFieldNode]


def parse_forms(root: Path) -> tuple[list[FormFieldNode], list[ParsedForm], dict[str, str]]:
    form_fields: list[FormFieldNode] = []
    forms: list[ParsedForm] = []
    form_by_module: dict[str, str] = {}

    for java_path in sorted(root.rglob("*Form.java")):
        if "/test/" in str(java_path).replace("\\", "/"):
            continue
        parsed = _parse_form_file(java_path)
        if not parsed:
            continue
        forms.append(parsed)
        form_fields.extend(parsed.fields)
        form_by_module[parsed.module] = parsed.simple_name

    return form_fields, forms, form_by_module


def _parse_form_file(path: Path) -> ParsedForm | None:
    content = path.read_text(encoding="utf-8", errors="ignore")
    package_match = PACKAGE_RE.search(content)
    class_match = CLASS_RE.search(content)
    if not package_match or not class_match:
        return None

    package_name = package_match.group(1)
    class_name = class_match.group(1)
    module = _module_from_package(package_name)
    if not module:
        return None

    qualified_name = f"{package_name}.{class_name}"
    fields: list[FormFieldNode] = []

    for match in FIELD_RE.finditer(content):
        field_name = match.group(2)
        prefix = content[max(0, match.start() - 500) : match.start()]
        annotations = _extract_annotations(prefix)
        field_id = f"field:{qualified_name}.{field_name}"
        fields.append(
            FormFieldNode(
                id=field_id,
                name=field_name,
                form_class=qualified_name,
                form_simple_name=class_name,
                property_name=field_name,
                module=module,
                file_path=str(path),
                annotations=annotations,
            )
        )

    return ParsedForm(
        qualified_name=qualified_name,
        simple_name=class_name,
        module=module,
        file_path=str(path),
        fields=fields,
    )


def _extract_annotations(prefix: str) -> list[str]:
    annotations: list[str] = []
    for match in ANNOTATION_RE.finditer(prefix):
        name = match.group(1)
        if name in {"Override", "SuppressWarnings"}:
            continue
        args = (match.group(2) or "").strip()
        annotations.append(f"{name}({args})" if args else name)
    return annotations[-5:]


def _module_from_package(package_name: str) -> str | None:
    marker = ".app."
    if marker not in package_name:
        return None
    return package_name.split(marker, 1)[1].split(".", 1)[0]


def link_screens_to_fields(
    screens: list,
    form_fields: list[FormFieldNode],
) -> list[Rel]:
    has_field: list[Rel] = []
    fields_by_module: dict[str, list[FormFieldNode]] = {}
    for field in form_fields:
        fields_by_module.setdefault(field.module, []).append(field)

    for screen in screens:
        for field in fields_by_module.get(screen.module, []):
            has_field.append(Rel(from_id=screen.id, to_id=field.id))
    return has_field

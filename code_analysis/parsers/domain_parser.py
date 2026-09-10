"""Parse domain model classes into BusinessConcept and DataEntity nodes."""

from __future__ import annotations

import re
from pathlib import Path

from code_analysis.models import BusinessConceptNode, DataEntityNode, Rel


PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
CLASS_RE = re.compile(
    r"(?:public\s+)?(?:abstract\s+)?class\s+(\w+)",
    re.MULTILINE,
)


def camel_to_snake_upper(name: str) -> str:
    chars: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index > 0:
            chars.append("_")
        chars.append(char.upper())
    return "".join(chars)


def parse_domain_models(root: Path) -> tuple[
    list[BusinessConceptNode],
    list[DataEntityNode],
    list[Rel],
    list[Rel],
]:
    concepts: list[BusinessConceptNode] = []
    entities: list[DataEntityNode] = []
    represents: list[Rel] = []
    maps_to: list[Rel] = []

    model_dir = "domain/model"
    for java_path in sorted(root.rglob("*.java")):
        if model_dir not in str(java_path).replace("\\", "/"):
            continue
        if "/test/" in str(java_path).replace("\\", "/"):
            continue
        _parse_model_file(java_path, concepts, entities, represents, maps_to)

    return concepts, entities, represents, maps_to


def _parse_model_file(
    java_path: Path,
    concepts: list[BusinessConceptNode],
    entities: list[DataEntityNode],
    represents: list[Rel],
    maps_to: list[Rel],
) -> None:
    content = java_path.read_text(encoding="utf-8", errors="ignore")
    package_match = PACKAGE_RE.search(content)
    class_match = CLASS_RE.search(content)
    if not package_match or not class_match:
        return

    package_name = package_match.group(1)
    class_name = class_match.group(1)
    qualified_name = f"{package_name}.{class_name}"
    concept_id = f"concept:{qualified_name}"
    entity_id = f"entity:{class_name}"
    table_name = camel_to_snake_upper(class_name)

    concepts.append(
        BusinessConceptNode(
            id=concept_id,
            name=class_name,
            qualified_name=qualified_name,
            file_path=str(java_path),
        )
    )
    entities.append(
        DataEntityNode(
            id=entity_id,
            name=class_name,
            concept_id=concept_id,
            table_name=table_name,
        )
    )
    represents.append(Rel(from_id=concept_id, to_id=entity_id))
    maps_to.append(Rel(from_id=entity_id, to_id=table_name))

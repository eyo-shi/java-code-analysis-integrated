"""Post-ingest inference: derive Business nodes from Service packages.

The main analyzer only creates `Business` nodes from Controller module names
(``graph_builder._build_ui_layer``). Because the Java parser cannot always
resolve ``@Autowired`` calls, the Controller -> Service ``CALLS`` edge is
frequently missing, so the Screen -> Controller -> Service path breaks and
"which business updates table X" queries return no rows.

This module runs after ``Neo4jLoader.ingest()`` and adds an inferred layer of
``Business`` nodes derived from Service package names (e.g. ``domain.service.
reserve.*`` -> business ``reserve``). It links each Service class via
``HAS_OPERATION`` and each Service method via ``INCLUDES_METHOD``, letting the
business query skip the missing Controller edge:

    Business -[:INCLUDES_METHOD]-> JavaMethod(service) -[:CALLS*]-> JavaMethod(mapper)
             -[:EXECUTES]-> SQL -[:INSERTS|UPDATES|DELETES]-> Table

The inference is a post-processing pass on Neo4j only. The extraction pipeline
and ``AnalysisGraph`` dataclass are untouched.
"""

from __future__ import annotations

import json
from pathlib import Path

# DTO / bean / form suffixes commonly seen in Spring MVC + MyBatis projects.
# Classes matching these are excluded from Business.HAS_OPERATION so
# ``ReserveTourInput``, ``ReservationUpdateOutput`` etc. do not get grouped as
# "business operations". Keep in sync with terasoluna naming conventions.
DEFAULT_DTO_SUFFIXES: tuple[str, ...] = (
    "Input",
    "Output",
    "Dto",
    "DTO",
    "Form",
    "Vo",
    "VO",
    "Request",
    "Response",
    "Bean",
    "Details",
    "Result",
)

# The Java parser occasionally emits reserved words as JavaMethod nodes
# (e.g. ``ReserveServiceImpl.if``). They pollute Business -> INCLUDES_METHOD
# so we strip them before linking.
JAVA_RESERVED_METHOD_NAMES: frozenset[str] = frozenset(
    {
        "if",
        "else",
        "for",
        "while",
        "switch",
        "case",
        "do",
        "return",
        "break",
        "continue",
        "try",
        "catch",
        "finally",
        "throw",
        "new",
        "this",
        "super",
        "null",
        "true",
        "false",
        "synchronized",
        "instanceof",
    }
)

# terasoluna-tourreservation-mybatis3 で実際に確認済みの Service パッケージ
# 名と日本語ラベルの対応。ユーザプロジェクトでは BUSINESS_LABELS_FILE で
# 上書き可能。マッチしないパッケージ名は英語のまま Business.name として残る。
DEFAULT_LABELS: dict[str, str] = {
    "reserve": "予約業務",
    "customer": "顧客管理業務",
    "tourinfo": "ツアー情報業務",
    "userdetails": "ユーザー認証業務",
    "searchtour": "ツアー検索業務",
    "managecustomer": "顧客管理業務",
    "managereservation": "予約管理業務",
    "login": "ログイン業務",
    "menu": "メニュー業務",
}


def load_label_overrides(path: str | None) -> dict[str, str]:
    """Read a JSON file mapping ``svc_package -> Japanese label``.

    Missing file or malformed JSON yields an empty dict and prints a warning,
    matching the "inference is best-effort" contract of this module.
    """
    if not path:
        return {}
    file_path = Path(path)
    if not file_path.is_file():
        print(f"Warning: BUSINESS_LABELS_FILE not found: {path}")
        return {}
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"Warning: could not parse BUSINESS_LABELS_FILE {path}: {exc}")
        return {}
    if not isinstance(raw, dict):
        print(f"Warning: BUSINESS_LABELS_FILE {path} is not a JSON object; ignoring.")
        return {}
    return {str(k): str(v) for k, v in raw.items() if isinstance(k, str)}


def resolve_labels(overrides: dict[str, str] | None) -> dict[str, str]:
    """Merge built-in defaults with per-project overrides (overrides win)."""
    merged = dict(DEFAULT_LABELS)
    if overrides:
        merged.update(overrides)
    return merged


# Cypher snippets, executed in this order by ``Neo4jLoader.infer_business_graph``.

# 1. Delete JavaMethod nodes named after Java reserved words (parser noise).
CYPHER_CLEANUP_RESERVED = """
MATCH (m:JavaMethod {project_id: $project_id})
WHERE m.method_name IN $reserved_words
DETACH DELETE m
"""

# 2. Derive one Business per unique Service package (parts[-2] of the FQN),
#    excluding DTO / form / bean classes. Use ``business:<svc_package>`` for the
#    id so this namespace coexists with the Controller-derived
#    ``business:<controller_module>`` created by graph_builder.
CYPHER_CREATE_BUSINESSES = """
MATCH (c:JavaClass {project_id: $project_id, layer: 'service'})
WITH c, split(c.qualified_name, '.') AS parts
WITH c, parts[size(parts) - 2] AS svc_package
WHERE svc_package IS NOT NULL AND svc_package <> ''
  AND NOT any(suffix IN $dto_suffixes WHERE c.name ENDS WITH suffix)
WITH svc_package, collect(c) AS classes, collect(c.project_id)[0] AS pid
MERGE (b:Business {id: 'business:' + svc_package})
  ON CREATE SET
    b.name = coalesce($labels[svc_package], svc_package),
    b.module = svc_package,
    b.project_id = pid,
    b.extraction = 'inferred'
  ON MATCH SET
    b.name = coalesce($labels[svc_package], b.name),
    b.project_id = pid
WITH b, classes
UNWIND classes AS c
MERGE (b)-[:HAS_OPERATION]->(c)
"""

# 3. Link each Business to every method defined on its Service classes.
#    This is the bridge the analyzer's missing Controller->Service edge would
#    otherwise provide.
CYPHER_LINK_METHODS = """
MATCH (b:Business {project_id: $project_id})-[:HAS_OPERATION]->(c:JavaClass)
MATCH (c)-[:DEFINES]->(m:JavaMethod)
WHERE NOT m.method_name IN $reserved_words
MERGE (b)-[:INCLUDES_METHOD]->(m)
"""

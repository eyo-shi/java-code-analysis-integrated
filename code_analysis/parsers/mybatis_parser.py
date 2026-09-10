"""Parse MyBatis mapper XML for SQL, tables, and columns."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

from code_analysis.models import SqlColumnLink, SqlNode, SqlOperation
from code_analysis.parsers.column_mapper import column_id, camel_to_snake_upper


SQL_TAGS = ("select", "insert", "update", "delete")
TABLE_PATTERNS = {
    "INSERT": re.compile(r"\bINTO\s+([A-Za-z0-9_]+)", re.IGNORECASE),
    "UPDATE": re.compile(r"\bUPDATE\s+([A-Za-z0-9_]+)", re.IGNORECASE),
    "DELETE": re.compile(r"\bFROM\s+([A-Za-z0-9_]+)", re.IGNORECASE),
    "SELECT": re.compile(r"\bFROM\s+([A-Za-z0-9_]+)", re.IGNORECASE),
}
INSERT_COLUMNS_RE = re.compile(
    r"\bINTO\s+[A-Za-z0-9_]+\s*\(([^)]+)\)",
    re.IGNORECASE,
)
UPDATE_SET_RE = re.compile(
    r"\bSET\s+(.+?)(?:\bWHERE\b|$)",
    re.IGNORECASE | re.DOTALL,
)
PROPERTY_COLUMN_RE = re.compile(
    r'<result\s+[^>]*property\s*=\s*"([^"]+)"[^>]*column\s*=\s*"([^"]+)"',
    re.IGNORECASE,
)
ID_PROPERTY_COLUMN_RE = re.compile(
    r'<id\s+[^>]*property\s*=\s*"([^"]+)"[^>]*column\s*=\s*"([^"]+)"',
    re.IGNORECASE,
)


def parse_mybatis_mappers(
    root: Path,
) -> tuple[list[SqlNode], list[tuple[str, str, SqlOperation]], list[SqlColumnLink], dict[str, str]]:
    sql_nodes: list[SqlNode] = []
    table_links: list[tuple[str, str, SqlOperation]] = []
    column_links: list[SqlColumnLink] = []
    property_to_column: dict[str, str] = {}

    for xml_path in sorted(root.rglob("*Repository.xml")):
        try:
            content = xml_path.read_text(encoding="utf-8", errors="ignore")
            tree = ET.parse(xml_path)
        except (ET.ParseError, OSError) as exc:
            print(f"Skipping invalid XML {xml_path}: {exc}")
            continue

        for prop, col in PROPERTY_COLUMN_RE.findall(content):
            property_to_column[prop] = col.upper()
        for prop, col in ID_PROPERTY_COLUMN_RE.findall(content):
            property_to_column[prop] = col.upper()

        mapper = tree.getroot()
        namespace = mapper.attrib.get("namespace", "")
        if not namespace:
            continue

        for tag in SQL_TAGS:
            for element in mapper.findall(tag):
                statement_id = element.attrib.get("id", "")
                if not statement_id:
                    continue
                operation: SqlOperation = tag.upper()
                statement_text = _flatten_sql(element)
                sql_id = f"{namespace}.{statement_id}"
                sql_nodes.append(
                    SqlNode(
                        id=sql_id,
                        mapper_namespace=namespace,
                        statement_id=statement_id,
                        operation=operation,
                        statement=statement_text,
                        file_path=str(xml_path),
                    )
                )
                for table_name in _extract_tables(operation, statement_text):
                    table_links.append((sql_id, table_name.upper(), operation))
                for table_name, col_name in _extract_columns(operation, statement_text):
                    column_links.append(
                        SqlColumnLink(
                            sql_id=sql_id,
                            table_name=table_name.upper(),
                            column_name=col_name.upper(),
                            operation=operation,
                        )
                    )

    return sql_nodes, table_links, column_links, property_to_column


def _flatten_sql(element: ET.Element) -> str:
    text = ET.tostring(element, encoding="unicode", method="text")
    return re.sub(r"\s+", " ", text).strip()


def _extract_tables(operation: SqlOperation, statement: str) -> list[str]:
    pattern = TABLE_PATTERNS.get(operation)
    if not pattern:
        return []
    return sorted({match.group(1).upper() for match in pattern.finditer(statement)})


def _extract_columns(operation: SqlOperation, statement: str) -> list[tuple[str, str]]:
    if operation == "INSERT":
        return _extract_insert_columns(statement)
    if operation == "UPDATE":
        return _extract_update_columns(statement)
    return []


def _extract_insert_columns(statement: str) -> list[tuple[str, str]]:
    match = INSERT_COLUMNS_RE.search(statement)
    if not match:
        return []
    table_match = TABLE_PATTERNS["INSERT"].search(statement)
    if not table_match:
        return []
    table_name = table_match.group(1).upper()
    columns = [part.strip() for part in match.group(1).split(",")]
    return [(table_name, col) for col in columns if col]


def _extract_update_columns(statement: str) -> list[tuple[str, str]]:
    table_match = TABLE_PATTERNS["UPDATE"].search(statement)
    if not table_match:
        return []
    table_name = table_match.group(1).upper()
    set_match = UPDATE_SET_RE.search(statement)
    if not set_match:
        return []
    assignments = set_match.group(1).split(",")
    columns: list[tuple[str, str]] = []
    for assignment in assignments:
        if "=" not in assignment:
            continue
        column_name = assignment.split("=", 1)[0].strip()
        if column_name:
            columns.append((table_name, column_name))
    return columns


def property_to_column_name(property_name: str, mapping: dict[str, str]) -> str:
    if property_name in mapping:
        return mapping[property_name]
    return camel_to_snake_upper(property_name)

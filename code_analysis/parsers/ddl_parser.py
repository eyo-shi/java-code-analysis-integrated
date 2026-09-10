"""Parse DDL SQL files for tables and columns."""

from __future__ import annotations

import re
from pathlib import Path

from code_analysis.models import ColumnNode, Rel, TableNode


CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+([A-Za-z0-9_]+)\s*\((.*?)\)\s*;",
    re.IGNORECASE | re.DOTALL,
)
COLUMN_LINE_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s+", re.IGNORECASE)


def parse_ddl(
    root: Path,
    default_database_id: str,
) -> tuple[list[TableNode], list[ColumnNode], list[Rel], list[Rel], str | None]:
    tables: list[TableNode] = []
    columns: list[ColumnNode] = []
    contains_table: list[Rel] = []
    has_column: list[Rel] = []
    seen_tables: set[str] = set()
    seen_columns: set[str] = set()
    ddl_source_path: str | None = None

    ddl_files = sorted(
        path
        for path in root.rglob("*.sql")
        if "create" in path.name.lower() and "table" in path.name.lower()
    )
    if not ddl_files:
        ddl_files = sorted(root.rglob("*.sql"))

    for sql_path in ddl_files:
        content = sql_path.read_text(encoding="utf-8", errors="ignore")
        if "CREATE TABLE" not in content.upper():
            continue
        ddl_source_path = str(sql_path)
        for match in CREATE_TABLE_RE.finditer(content):
            table_name = match.group(1).upper()
            body = match.group(2)
            if table_name not in seen_tables:
                tables.append(
                    TableNode(id=table_name, name=table_name, database_id=default_database_id)
                )
                contains_table.append(Rel(from_id=default_database_id, to_id=table_name))
                seen_tables.add(table_name)

            for raw_line in body.splitlines():
                line = raw_line.strip().rstrip(",")
                if not line or line.upper().startswith("CONSTRAINT"):
                    continue
                column_match = COLUMN_LINE_RE.match(line)
                if not column_match:
                    continue
                column_name = column_match.group(1).upper()
                col_id = f"{table_name}.{column_name}"
                if col_id in seen_columns:
                    continue
                columns.append(ColumnNode(id=col_id, table_name=table_name, name=column_name))
                has_column.append(Rel(from_id=table_name, to_id=col_id))
                seen_columns.add(col_id)

    return tables, columns, contains_table, has_column, ddl_source_path

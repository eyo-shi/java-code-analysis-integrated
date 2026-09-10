"""Parse datasource configuration for logical database names."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from code_analysis.models import DatabaseNode, Rel


JDBC_URL_RE = re.compile(r"(?:jdbc(?:\.[a-z]+)?|database)\.url\s*=\s*(.+)", re.IGNORECASE)
JNDI_RE = re.compile(r'jndi-name\s*=\s*["\']([^"\']+)["\']', re.IGNORECASE)
CONTEXT_JDBC_RE = re.compile(
    r'<Resource[^>]+name\s*=\s*["\']([^"\']+)["\'][^>]+url\s*=\s*["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def parse_databases(root: Path) -> tuple[list[DatabaseNode], dict[str, str]]:
    """Return databases and a map of jdbc database name -> database node id."""
    databases: list[DatabaseNode] = []
    jdbc_name_to_db_id: dict[str, str] = {}
    seen_ids: set[str] = set()

    for path in sorted(root.rglob("*")):
        if path.suffix == ".properties":
            _parse_properties_file(path, databases, jdbc_name_to_db_id, seen_ids)
        elif path.suffix == ".xml":
            _parse_xml_datasource(path, databases, jdbc_name_to_db_id, seen_ids)

    if not databases:
        default = DatabaseNode(
            id="database:default",
            name="default",
            vendor="unknown",
            logical_name="default",
            datasource_key=None,
            jdbc_url=None,
        )
        databases.append(default)
        jdbc_name_to_db_id["default"] = default.id

    return databases, jdbc_name_to_db_id


def _add_database(
    databases: list[DatabaseNode],
    jdbc_name_to_db_id: dict[str, str],
    seen_ids: set[str],
    logical_name: str,
    vendor: str,
    datasource_key: str | None,
    jdbc_url: str | None,
) -> None:
    db_id = f"database:{logical_name}"
    if db_id in seen_ids:
        return
    seen_ids.add(db_id)
    databases.append(
        DatabaseNode(
            id=db_id,
            name=logical_name,
            vendor=vendor,
            logical_name=logical_name,
            datasource_key=datasource_key,
            jdbc_url=jdbc_url,
        )
    )
    jdbc_name_to_db_id[logical_name] = db_id


def _parse_properties_file(
    path: Path,
    databases: list[DatabaseNode],
    jdbc_name_to_db_id: dict[str, str],
    seen_ids: set[str],
) -> None:
    content = path.read_text(encoding="utf-8", errors="ignore")
    for match in JDBC_URL_RE.finditer(content):
        jdbc_url = match.group(1).strip()
        logical_name, vendor = _logical_name_from_jdbc(jdbc_url)
        datasource_key = path.name
        _add_database(databases, jdbc_name_to_db_id, seen_ids, logical_name, vendor, datasource_key, jdbc_url)


def _parse_xml_datasource(
    path: Path,
    databases: list[DatabaseNode],
    jdbc_name_to_db_id: dict[str, str],
    seen_ids: set[str],
) -> None:
    content = path.read_text(encoding="utf-8", errors="ignore")
    for jndi, jdbc_url in CONTEXT_JDBC_RE.findall(content):
        logical_name, vendor = _logical_name_from_jdbc(jdbc_url)
        _add_database(databases, jdbc_name_to_db_id, seen_ids, logical_name, vendor, jndi, jdbc_url)
    for match in JNDI_RE.finditer(content):
        jndi = match.group(1)
        logical_name = jndi.split("/")[-1].replace("DataSource", "").lower() or jndi
        if f"database:{logical_name}" not in seen_ids:
            _add_database(databases, jdbc_name_to_db_id, seen_ids, logical_name, "unknown", jndi, None)


def _logical_name_from_jdbc(jdbc_url: str) -> tuple[str, str]:
    parsed = urlparse(jdbc_url.replace("jdbc:", "http:", 1))
    vendor = jdbc_url.split(":", 2)[1] if jdbc_url.startswith("jdbc:") else "unknown"
    path = parsed.path.lstrip("/")
    logical_name = path.split("/")[-1] if path else vendor
    return logical_name or "default", vendor

"""Load analysis graph into Neo4j."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from neo4j import GraphDatabase

from code_analysis.models import AnalysisGraph, SqlOperation
from code_analysis.neo4j_connect import format_neo4j_connection_help, iter_neo4j_connection_uris


BATCH_SIZE = 200
SQL_RELATION = {
    "INSERT": "INSERTS",
    "UPDATE": "UPDATES",
    "DELETE": "DELETES",
    "SELECT": "SELECTS",
    "OTHER": "TOUCHES",
}


class Neo4jLoader:
    def __init__(self, uri: str, username: str, password: str) -> None:
        self._configured_uri = uri
        self._uri = uri
        self._username = username
        self._password = password
        self._driver = None

    def _connect(self, uri: str):
        return GraphDatabase.driver(uri, auth=(self._username, self._password))

    def verify_connectivity(self) -> None:
        errors: list[str] = []
        candidates = iter_neo4j_connection_uris(self._configured_uri)
        if not candidates:
            raise ValueError(format_neo4j_connection_help(self._configured_uri, errors))

        for candidate in candidates:
            if candidate != self._configured_uri:
                print(f"Trying Neo4j URI: {candidate}")
            driver = self._connect(candidate)
            try:
                driver.verify_connectivity()
            except Exception as exc:
                driver.close()
                errors.append(f"  {candidate}: {exc}")
                continue

            if self._driver is not None:
                self._driver.close()
            self._uri = candidate
            self._driver = driver
            if candidate != self._configured_uri:
                print(f"Connected via in-cluster URI: {candidate}")
            return

        raise ValueError(format_neo4j_connection_help(self._configured_uri, errors))

    def close(self) -> None:
        if self._driver is not None:
            self._driver.close()

    def ingest(self, graph: AnalysisGraph) -> None:
        self.verify_connectivity()
        assert self._driver is not None
        with self._driver.session() as session:
            session.execute_write(self._ensure_constraints)
            session.execute_write(self._delete_project, graph.project_id)
            session.execute_write(self._create_project, graph)

            node_batches: list[tuple[str, list, Callable]] = [
                ("Business", graph.businesses, self._business_props),
                ("Screen", graph.screens, self._screen_props),
                ("Process", graph.processes, self._process_props),
                ("BusinessConcept", graph.business_concepts, self._concept_props),
                ("DataEntity", graph.data_entities, self._entity_props),
                ("Database", graph.databases, self._database_props),
                ("Table", graph.tables, self._table_props),
                ("Column", graph.columns, self._column_props),
                ("FormField", graph.form_fields, self._form_field_props),
                ("JavaClass", graph.java_classes, self._java_class_props),
                ("JavaMethod", graph.java_methods, self._java_method_props),
                ("SQL", graph.sql_statements, self._sql_props),
                ("Operation", graph.operations, self._operation_props),
                ("Condition", graph.conditions, self._condition_props),
                ("BusinessRule", graph.business_rules, self._rule_props),
                ("DesignDocument", graph.design_documents, self._document_props),
                ("Evidence", graph.evidence_items, self._evidence_props),
            ]
            for label, items, prop_fn in node_batches:
                self._batch_write(session, label, items, prop_fn, graph.project_id)

            rel_batches: list[tuple[str, list, str, str, str, str]] = [
                ("HAS_SCREEN", graph.has_screen, "Business", "Screen"),
                ("HAS_PROCESS", graph.has_process, "Business", "Process"),
                ("HAS_STEP", graph.has_step, "Process", "Screen"),
                ("IMPLEMENTED_BY", graph.implemented_by, "Screen", "JavaMethod"),
                ("REPRESENTS", graph.represents, "BusinessConcept", "DataEntity"),
                ("MAPS_TO", graph.maps_to, "DataEntity", "Table"),
                ("CONTAINS", graph.contains_table, "Database", "Table"),
                ("HAS_COLUMN", graph.has_column, "Table", "Column"),
                ("HAS_FIELD", graph.has_field, "Screen", "FormField"),
                ("BINDS_TO", graph.binds_to, "FormField", "Column"),
                ("VALIDATES", graph.validates, "Screen", "Condition"),
                ("CHECKS", graph.checks, "Condition", "Column"),
                ("APPLIES_TO_SCREEN", graph.applies_to_screen, "Condition", "Screen"),
                ("DEFINES", graph.defines_method, "JavaClass", "JavaMethod"),
                ("CALLS", graph.calls, "JavaMethod", "JavaMethod"),
                ("PERFORMS", graph.performs, "JavaMethod", "Operation"),
                ("REALIZES", graph.realizes, "Operation", "SQL"),
                ("EXECUTES", graph.executes, "JavaMethod", "SQL"),
                ("ENFORCES", graph.enforces, "BusinessRule", "Condition"),
                ("APPLIES_TO", graph.applies_to, "BusinessRule", "Business"),
                ("MODELS", graph.models_concept, "BusinessConcept", "JavaClass"),
                ("DESCRIBES", graph.describes, "DesignDocument", "Project"),
            ]
            for rel_type, items, from_label, to_label in rel_batches:
                self._batch_relate(session, rel_type, items, from_label, to_label)

            self._batch_supported_by_generic(session, graph)
            self._batch_sql_table_links(session, graph.sql_table_links)
            self._batch_writes_column(session, graph.writes_column)

    def _batch_supported_by_generic(self, session, graph: AnalysisGraph) -> None:
        grouped: dict[tuple[str, str], list[dict]] = {}
        for rel in graph.supported_by:
            from_label = self._label_for_id(rel.from_id)
            if not from_label:
                continue
            key = (from_label, "Evidence")
            grouped.setdefault(key, []).append({"from_id": rel.from_id, "to_id": rel.to_id})

        for (from_label, to_label), rows in grouped.items():
            for index in range(0, len(rows), BATCH_SIZE):
                chunk = rows[index : index + BATCH_SIZE]
                session.execute_write(
                    self._merge_relationship,
                    "SUPPORTED_BY",
                    from_label,
                    to_label,
                    chunk,
                )

    @staticmethod
    def _label_for_id(node_id: str) -> str | None:
        mapping = {
            "concept:": "BusinessConcept",
            "entity:": "DataEntity",
            "class:": "JavaClass",
            "screen:": "Screen",
            "process:": "Process",
            "rule:": "BusinessRule",
            "condition:": "Condition",
            "field:": "FormField",
            "operation:": "Operation",
            "doc:": "DesignDocument",
            "evidence:": "Evidence",
        }
        for prefix, label in mapping.items():
            if node_id.startswith(prefix):
                return label
        if "." in node_id and node_id[0].islower():
            if "Repository" in node_id or "Service" in node_id or "Controller" in node_id:
                return "JavaMethod"
        if node_id.isupper():
            return "Table"
        if "." in node_id and node_id.split(".")[0].isupper():
            return "Column"
        if node_id.startswith("org."):
            return "JavaMethod" if node_id.count(".") >= 3 else "SQL"
        return None

    @staticmethod
    def _ensure_constraints(tx) -> None:
        specs = [
            ("Project", "project_id"),
            ("Business", "business_id"),
            ("Screen", "screen_id"),
            ("Process", "process_id"),
            ("BusinessConcept", "business_concept_id"),
            ("DataEntity", "data_entity_id"),
            ("Database", "database_id"),
            ("Table", "table_id"),
            ("Column", "column_id"),
            ("FormField", "form_field_id"),
            ("JavaClass", "java_class_id"),
            ("JavaMethod", "java_method_id"),
            ("SQL", "sql_id"),
            ("Operation", "operation_id"),
            ("Condition", "condition_id"),
            ("BusinessRule", "business_rule_id"),
            ("DesignDocument", "design_document_id"),
            ("Evidence", "evidence_id"),
        ]
        for label, _ in specs:
            tx.run(
                f"CREATE CONSTRAINT {label.lower()}_id IF NOT EXISTS "
                f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
            )

    @staticmethod
    def _delete_project(tx, project_id: str) -> None:
        tx.run(
            "MATCH (n) WHERE n.project_id = $project_id DETACH DELETE n",
            project_id=project_id,
        )

    @staticmethod
    def _create_project(tx, graph: AnalysisGraph) -> None:
        tx.run(
            """
            MERGE (p:Project {id: $id})
            SET p.name = $name,
                p.repo_url = $repo_url,
                p.git_ref = $git_ref,
                p.root_path = $root_path,
                p.analyzed_at = $analyzed_at,
                p.project_id = $id
            """,
            id=graph.project_id,
            name=graph.project_name,
            repo_url=graph.repo_url,
            git_ref=graph.git_ref,
            root_path=graph.root_path,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
        )

    def _batch_write(self, session, label: str, items: list, prop_fn, project_id: str) -> None:
        for index in range(0, len(items), BATCH_SIZE):
            chunk = items[index : index + BATCH_SIZE]
            session.execute_write(
                self._merge_nodes,
                label,
                [prop_fn(item, project_id) for item in chunk],
            )

    @staticmethod
    def _merge_nodes(tx, label: str, rows: list[dict]) -> None:
        tx.run(
            f"""
            UNWIND $rows AS row
            MERGE (n:{label} {{id: row.id}})
            SET n += row
            """,
            rows=rows,
        )

    def _batch_relate(
        self,
        session,
        rel_type: str,
        items: list,
        from_label: str,
        to_label: str,
    ) -> None:
        for index in range(0, len(items), BATCH_SIZE):
            chunk = items[index : index + BATCH_SIZE]
            rows = [{"from_id": item.from_id, "to_id": item.to_id} for item in chunk]
            session.execute_write(self._merge_relationship, rel_type, from_label, to_label, rows)

    @staticmethod
    def _merge_relationship(
        tx,
        rel_type: str,
        from_label: str,
        to_label: str,
        rows: list[dict],
    ) -> None:
        tx.run(
            f"""
            UNWIND $rows AS row
            MATCH (a:{from_label} {{id: row.from_id}})
            MATCH (b:{to_label} {{id: row.to_id}})
            MERGE (a)-[:{rel_type}]->(b)
            """,
            rows=rows,
        )

    def _batch_sql_table_links(self, session, links: list[tuple[str, str, SqlOperation]]) -> None:
        grouped: dict[str, list] = {}
        for sql_id, table_name, operation in links:
            rel = SQL_RELATION.get(operation, "TOUCHES")
            grouped.setdefault(rel, []).append((sql_id, table_name))

        for rel_type, rel_links in grouped.items():
            for index in range(0, len(rel_links), BATCH_SIZE):
                chunk = rel_links[index : index + BATCH_SIZE]
                rows = [{"sql_id": sql_id, "table_id": table_name} for sql_id, table_name in chunk]
                session.execute_write(self._merge_sql_table_rel, rel_type, rows)

    def _batch_writes_column(self, session, links) -> None:
        rows = [
            {
                "sql_id": link.sql_id,
                "column_id": f"{link.table_name}.{link.column_name}",
                "operation": link.operation,
            }
            for link in links
        ]
        for index in range(0, len(rows), BATCH_SIZE):
            chunk = rows[index : index + BATCH_SIZE]
            session.execute_write(self._merge_writes_column, chunk)

    @staticmethod
    def _merge_writes_column(tx, rows: list[dict]) -> None:
        tx.run(
            """
            UNWIND $rows AS row
            MATCH (q:SQL {id: row.sql_id})
            MATCH (c:Column {id: row.column_id})
            MERGE (q)-[r:WRITES]->(c)
            SET r.operation = row.operation
            """,
            rows=rows,
        )

    @staticmethod
    def _merge_sql_table_rel(tx, rel_type: str, rows: list[dict]) -> None:
        tx.run(
            f"""
            UNWIND $rows AS row
            MATCH (q:SQL {{id: row.sql_id}})
            MATCH (t:Table {{id: row.table_id}})
            MERGE (q)-[:{rel_type}]->(t)
            """,
            rows=rows,
        )

    @staticmethod
    def _with_project(item: Any, project_id: str, **props: Any) -> dict:
        return {"id": item.id, "project_id": project_id, "extraction": item.extraction, **props}

    def _business_props(self, item, project_id: str) -> dict:
        return self._with_project(item, project_id, name=item.name, module=item.module)

    def _screen_props(self, item, project_id: str) -> dict:
        return self._with_project(
            item, project_id, name=item.name, view_path=item.view_path,
            module=item.module, title_key=item.title_key, form_class=item.form_class,
        )

    def _process_props(self, item, project_id: str) -> dict:
        return self._with_project(
            item, project_id, name=item.name, module=item.module, step_order=item.step_order,
        )

    def _concept_props(self, item, project_id: str) -> dict:
        return self._with_project(
            item, project_id, name=item.name, qualified_name=item.qualified_name,
            file_path=item.file_path,
        )

    def _entity_props(self, item, project_id: str) -> dict:
        return self._with_project(
            item, project_id, name=item.name, concept_id=item.concept_id,
            table_name=item.table_name,
        )

    def _database_props(self, item, project_id: str) -> dict:
        return self._with_project(
            item, project_id, name=item.name, vendor=item.vendor,
            logical_name=item.logical_name, datasource_key=item.datasource_key,
            jdbc_url=item.jdbc_url,
        )

    def _form_field_props(self, item, project_id: str) -> dict:
        return self._with_project(
            item, project_id, name=item.name, form_class=item.form_class,
            form_simple_name=item.form_simple_name, property_name=item.property_name,
            module=item.module, file_path=item.file_path, annotations=item.annotations,
        )

    def _table_props(self, item, project_id: str) -> dict:
        return self._with_project(item, project_id, name=item.name, database_id=item.database_id)

    def _column_props(self, item, project_id: str) -> dict:
        return self._with_project(item, project_id, table_name=item.table_name, name=item.name)

    def _java_class_props(self, item, project_id: str) -> dict:
        return self._with_project(
            item, project_id, name=item.name, qualified_name=item.qualified_name,
            package_name=item.package_name, layer=item.layer, file_path=item.file_path,
            is_interface=item.is_interface,
        )

    def _java_method_props(self, item, project_id: str) -> dict:
        return self._with_project(
            item, project_id, qualified_name=item.qualified_name, class_id=item.class_id,
            class_name=item.class_name, method_name=item.method_name, file_path=item.file_path,
            layer=item.layer, start_line=item.start_line, end_line=item.end_line,
        )

    def _sql_props(self, item, project_id: str) -> dict:
        return self._with_project(
            item, project_id, mapper_namespace=item.mapper_namespace,
            statement_id=item.statement_id, operation=item.operation,
            statement=item.statement[:4000], file_path=item.file_path,
            columns_written=item.columns_written,
        )

    def _operation_props(self, item, project_id: str) -> dict:
        return self._with_project(
            item, project_id, name=item.name, operation_type=item.operation_type,
            repository_method_id=item.repository_method_id, sql_id=item.sql_id,
        )

    def _condition_props(self, item, project_id: str) -> dict:
        return self._with_project(
            item, project_id, name=item.name, expression=item.expression,
            message_key=item.message_key, field_name=item.field_name,
            rule_type=item.rule_type, constraint=item.constraint,
            form_class=item.form_class,
        )

    def _rule_props(self, item, project_id: str) -> dict:
        return self._with_project(
            item, project_id, name=item.name, qualified_name=item.qualified_name,
            file_path=item.file_path, description=item.description,
        )

    def _document_props(self, item, project_id: str) -> dict:
        return self._with_project(
            item, project_id, name=item.name, file_path=item.file_path, doc_type=item.doc_type,
        )

    def _evidence_props(self, item, project_id: str) -> dict:
        return self._with_project(
            item, project_id, source_type=item.source_type, file_path=item.file_path,
            line_start=item.line_start, line_end=item.line_end, excerpt=item.excerpt,
        )

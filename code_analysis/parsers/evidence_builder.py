"""Generate Evidence nodes that trace graph elements back to source files."""

from __future__ import annotations

from code_analysis.models import (
    AnalysisGraph,
    EvidenceNode,
    EvidenceSource,
    Rel,
)


def attach_evidence(graph: AnalysisGraph) -> None:
    evidence: list[EvidenceNode] = []
    supported_by: list[Rel] = []

    def add(
        target_id: str,
        file_path: str,
        source_type: EvidenceSource,
        line_start: int | None = None,
        line_end: int | None = None,
        excerpt: str | None = None,
    ) -> None:
        evidence_id = f"evidence:{target_id}:{file_path}:{line_start or 0}"
        if any(item.id == evidence_id for item in evidence):
            return
        evidence.append(
            EvidenceNode(
                id=evidence_id,
                source_type=source_type,
                file_path=file_path,
                line_start=line_start,
                line_end=line_end,
                excerpt=(excerpt or "")[:500] or None,
            )
        )
        supported_by.append(Rel(from_id=target_id, to_id=evidence_id))

    for concept in graph.business_concepts:
        add(concept.id, concept.file_path, "java")

    for java_class in graph.java_classes:
        add(java_class.id, java_class.file_path, "java")

    for method in graph.java_methods:
        add(method.id, method.file_path, "java", method.start_line, method.end_line)

    for sql in graph.sql_statements:
        add(sql.id, sql.file_path, "xml", excerpt=sql.statement[:200])

    for table in graph.tables:
        if graph.ddl_source_path:
            add(table.id, graph.ddl_source_path, "sql")

    for rule in graph.business_rules:
        add(rule.id, rule.file_path, "java")

    for field in graph.form_fields:
        add(field.id, field.file_path, "java")

    for document in graph.design_documents:
        add(document.id, document.file_path, "markdown")

    graph.evidence_items = evidence
    graph.supported_by = supported_by

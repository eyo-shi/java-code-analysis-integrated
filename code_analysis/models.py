"""Data models for the code analysis graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


SqlOperation = Literal["SELECT", "INSERT", "UPDATE", "DELETE", "OTHER"]
EvidenceSource = Literal["java", "xml", "sql", "properties", "markdown"]
ExtractionStatus = Literal["extracted", "inferred", "manual"]


@dataclass
class BusinessNode:
    id: str
    name: str
    module: str
    extraction: ExtractionStatus = "extracted"


@dataclass
class ScreenNode:
    id: str
    name: str
    view_path: str
    module: str
    title_key: str | None = None
    form_class: str | None = None
    extraction: ExtractionStatus = "extracted"


@dataclass
class ProcessNode:
    id: str
    name: str
    module: str
    step_order: list[str] = field(default_factory=list)
    extraction: ExtractionStatus = "inferred"


@dataclass
class BusinessConceptNode:
    id: str
    name: str
    qualified_name: str
    file_path: str
    extraction: ExtractionStatus = "extracted"


@dataclass
class DataEntityNode:
    id: str
    name: str
    concept_id: str
    table_name: str | None = None
    extraction: ExtractionStatus = "inferred"


@dataclass
class DatabaseNode:
    id: str
    name: str
    vendor: str
    logical_name: str
    datasource_key: str | None = None
    jdbc_url: str | None = None
    extraction: ExtractionStatus = "extracted"


@dataclass
class TableNode:
    id: str
    name: str
    database_id: str
    extraction: ExtractionStatus = "extracted"


@dataclass
class ColumnNode:
    id: str
    table_name: str
    name: str
    extraction: ExtractionStatus = "extracted"


@dataclass
class FormFieldNode:
    id: str
    name: str
    form_class: str
    form_simple_name: str
    property_name: str
    module: str
    file_path: str
    annotations: list[str] = field(default_factory=list)
    extraction: ExtractionStatus = "extracted"


@dataclass
class JavaClassNode:
    id: str
    name: str
    qualified_name: str
    package_name: str
    layer: str
    file_path: str
    is_interface: bool = False
    extraction: ExtractionStatus = "extracted"


@dataclass
class JavaMethodNode:
    id: str
    qualified_name: str
    class_id: str
    class_name: str
    method_name: str
    file_path: str
    layer: str
    start_line: int = 0
    end_line: int = 0
    extraction: ExtractionStatus = "extracted"


@dataclass
class SqlNode:
    id: str
    mapper_namespace: str
    statement_id: str
    operation: SqlOperation
    statement: str
    file_path: str
    columns_written: list[str] = field(default_factory=list)
    extraction: ExtractionStatus = "extracted"


@dataclass
class SqlColumnLink:
    sql_id: str
    table_name: str
    column_name: str
    operation: SqlOperation


@dataclass
class OperationNode:
    id: str
    name: str
    operation_type: SqlOperation
    repository_method_id: str
    sql_id: str
    extraction: ExtractionStatus = "inferred"


@dataclass
class ConditionNode:
    id: str
    name: str
    expression: str
    message_key: str | None = None
    field_name: str | None = None
    rule_type: str | None = None
    constraint: str | None = None
    form_class: str | None = None
    extraction: ExtractionStatus = "extracted"


@dataclass
class BusinessRuleNode:
    id: str
    name: str
    qualified_name: str
    file_path: str
    description: str | None = None
    extraction: ExtractionStatus = "extracted"


@dataclass
class DesignDocumentNode:
    id: str
    name: str
    file_path: str
    doc_type: str
    extraction: ExtractionStatus = "extracted"


@dataclass
class EvidenceNode:
    id: str
    source_type: EvidenceSource
    file_path: str
    line_start: int | None = None
    line_end: int | None = None
    excerpt: str | None = None
    extraction: ExtractionStatus = "extracted"


@dataclass
class Rel:
    from_id: str
    to_id: str


@dataclass
class AnalysisGraph:
    project_id: str
    project_name: str
    repo_url: str
    git_ref: str
    root_path: str
    ddl_source_path: str | None = None

    businesses: list[BusinessNode] = field(default_factory=list)
    screens: list[ScreenNode] = field(default_factory=list)
    processes: list[ProcessNode] = field(default_factory=list)
    business_concepts: list[BusinessConceptNode] = field(default_factory=list)
    data_entities: list[DataEntityNode] = field(default_factory=list)
    databases: list[DatabaseNode] = field(default_factory=list)
    tables: list[TableNode] = field(default_factory=list)
    columns: list[ColumnNode] = field(default_factory=list)
    form_fields: list[FormFieldNode] = field(default_factory=list)
    java_classes: list[JavaClassNode] = field(default_factory=list)
    java_methods: list[JavaMethodNode] = field(default_factory=list)
    sql_statements: list[SqlNode] = field(default_factory=list)
    operations: list[OperationNode] = field(default_factory=list)
    conditions: list[ConditionNode] = field(default_factory=list)
    business_rules: list[BusinessRuleNode] = field(default_factory=list)
    design_documents: list[DesignDocumentNode] = field(default_factory=list)
    evidence_items: list[EvidenceNode] = field(default_factory=list)

    has_screen: list[Rel] = field(default_factory=list)
    has_process: list[Rel] = field(default_factory=list)
    has_step: list[Rel] = field(default_factory=list)
    implemented_by: list[Rel] = field(default_factory=list)
    represents: list[Rel] = field(default_factory=list)
    maps_to: list[Rel] = field(default_factory=list)
    contains_table: list[Rel] = field(default_factory=list)
    has_column: list[Rel] = field(default_factory=list)
    has_field: list[Rel] = field(default_factory=list)
    binds_to: list[Rel] = field(default_factory=list)
    validates: list[Rel] = field(default_factory=list)
    checks: list[Rel] = field(default_factory=list)
    writes_column: list[SqlColumnLink] = field(default_factory=list)
    defines_method: list[Rel] = field(default_factory=list)
    calls: list[Rel] = field(default_factory=list)
    performs: list[Rel] = field(default_factory=list)
    realizes: list[Rel] = field(default_factory=list)
    executes: list[Rel] = field(default_factory=list)
    sql_table_links: list[tuple[str, str, SqlOperation]] = field(default_factory=list)
    enforces: list[Rel] = field(default_factory=list)
    applies_to: list[Rel] = field(default_factory=list)
    applies_to_screen: list[Rel] = field(default_factory=list)
    models_concept: list[Rel] = field(default_factory=list)
    describes: list[Rel] = field(default_factory=list)
    supported_by: list[Rel] = field(default_factory=list)

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for name in (
            "businesses",
            "screens",
            "processes",
            "business_concepts",
            "data_entities",
            "databases",
            "tables",
            "columns",
            "form_fields",
            "java_classes",
            "java_methods",
            "sql_statements",
            "operations",
            "conditions",
            "business_rules",
            "design_documents",
            "evidence_items",
        ):
            counts[name] = len(getattr(self, name))
        for name in (
            "has_screen",
            "has_process",
            "has_step",
            "implemented_by",
            "represents",
            "maps_to",
            "contains_table",
            "has_column",
            "has_field",
            "binds_to",
            "validates",
            "checks",
            "writes_column",
            "defines_method",
            "calls",
            "performs",
            "realizes",
            "executes",
            "sql_table_links",
            "enforces",
            "applies_to",
            "applies_to_screen",
            "models_concept",
            "describes",
            "supported_by",
        ):
            counts[name] = len(getattr(self, name))
        return counts

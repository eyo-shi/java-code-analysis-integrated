"""Build the end-to-end analysis graph."""

from __future__ import annotations

from pathlib import Path

from code_analysis.models import (
    AnalysisGraph,
    JavaClassNode,
    JavaMethodNode,
    OperationNode,
    Rel,
    SqlNode,
)
from code_analysis.parsers.database_parser import parse_databases
from code_analysis.parsers.ddl_parser import parse_ddl
from code_analysis.parsers.document_parser import parse_design_documents
from code_analysis.parsers.domain_parser import parse_domain_models
from code_analysis.parsers.evidence_builder import attach_evidence
from code_analysis.parsers.form_parser import link_screens_to_fields, parse_forms
from code_analysis.parsers.i18n_parser import load_i18n_messages
from code_analysis.parsers.java_parser import (
    JavaClass,
    JavaMethod,
    build_type_index,
    parse_java_sources,
    resolve_method_call,
)
from code_analysis.parsers.mybatis_parser import parse_mybatis_mappers
from code_analysis.parsers.process_parser import build_processes
from code_analysis.parsers.rule_parser import load_validation_messages, parse_business_rules
from code_analysis.parsers.validation_linker import build_validation_links


MODULE_BUSINESS_KEYS = {
    "managecustomer": "label.tr.managecustomer.managecustomerMessage",
    "searchtour": "label.tr.searchtour.searchTourMessage",
    "reservetour": "label.tr.searchtour.reserveScreenTitleMessage",
    "managereservation": "label.tr.managereservation.manageReservationMessage",
    "login": "label.tr.login.loginFormMessage",
    "menu": "label.tr.menu.menuMessage",
}

MODULE_SCREEN_KEYS = {
    "managecustomer": "label.tr.managecustomer.managecustomerMessage",
    "searchtour": "label.tr.searchtour.searchTourMessage",
    "reservetour": "label.tr.searchtour.reserveScreenTitleMessage",
    "managereservation": "label.tr.managereservation.manageReservationMessage",
    "login": "label.tr.login.loginFormMessage",
    "menu": "label.tr.menu.menuMessage",
}


def build_graph(
    root: Path,
    project_id: str,
    project_name: str,
    repo_url: str,
    git_ref: str,
    exclude_dirs: tuple[str, ...],
) -> AnalysisGraph:
    messages = load_i18n_messages(root)
    validation_messages = load_validation_messages(root)
    validation_messages.update(load_i18n_messages(root))
    java_classes = parse_java_sources(root, exclude_dirs)
    type_index = build_type_index(java_classes)
    databases, _jdbc_map = parse_databases(root)
    default_database_id = databases[0].id if databases else "database:default"

    sql_nodes, sql_table_links, sql_column_links, property_to_column = parse_mybatis_mappers(root)
    tables, columns, contains_table, has_column, ddl_source_path = parse_ddl(
        root, default_database_id
    )
    concepts, entities, represents, entity_table_maps = parse_domain_models(root)
    rules, conditions, enforces, applies_to = parse_business_rules(root, validation_messages)
    documents, describes = parse_design_documents(root, project_id)
    form_fields, parsed_forms, form_by_module = parse_forms(root)

    for sql in sql_nodes:
        sql.columns_written = sorted(
            {
                f"{link.table_name}.{link.column_name}"
                for link in sql_column_links
                if link.sql_id == sql.id
            }
        )

    graph = AnalysisGraph(
        project_id=project_id,
        project_name=project_name,
        repo_url=repo_url,
        git_ref=git_ref,
        root_path=str(root),
        ddl_source_path=ddl_source_path,
        databases=databases,
        tables=tables,
        columns=columns,
        contains_table=contains_table,
        has_column=has_column,
        form_fields=form_fields,
        business_concepts=concepts,
        data_entities=entities,
        represents=represents,
        maps_to=entity_table_maps,
        business_rules=rules,
        conditions=conditions,
        enforces=enforces,
        applies_to=applies_to,
        design_documents=documents,
        describes=describes,
        sql_statements=sql_nodes,
        sql_table_links=sql_table_links,
        writes_column=sql_column_links,
    )

    graph.java_classes = _to_java_class_nodes(java_classes)
    graph.java_methods, graph.defines_method = _to_java_method_nodes(java_classes)
    method_by_id = {method.id: method for method in graph.java_methods}

    screens, businesses, has_screen, implemented_by = _build_ui_layer(
        java_classes, messages, method_by_id, form_by_module
    )
    graph.screens = screens
    graph.businesses = businesses
    graph.has_screen = has_screen
    graph.implemented_by = implemented_by
    graph.has_field = link_screens_to_fields(screens, form_fields)

    entity_table_by_module = _entity_table_by_module(entities, form_fields)
    applies_to_screen: list[Rel] = []
    conditions, checks, validates, binds_to = build_validation_links(
        form_fields=form_fields,
        screens=screens,
        property_to_column=property_to_column,
        entity_table_by_module=entity_table_by_module,
        validation_messages=validation_messages,
        existing_conditions=graph.conditions,
        enforces=enforces,
        applies_to_screen=applies_to_screen,
    )
    graph.conditions = conditions
    graph.checks = checks
    graph.validates = validates
    graph.binds_to = binds_to
    graph.applies_to_screen = applies_to_screen

    processes, has_process, has_step = build_processes(screens)
    graph.processes = processes
    graph.has_process = has_process
    graph.has_step = has_step

    graph.calls = _build_calls(java_classes, type_index)
    graph.executes = _build_executes(java_classes, sql_nodes)
    graph.operations, graph.performs, graph.realizes = _build_operations(
        java_classes, sql_nodes
    )
    graph.models_concept = _build_concept_class_links(java_classes, concepts)

    attach_evidence(graph)
    return graph


def _to_java_class_nodes(java_classes: list[JavaClass]) -> list[JavaClassNode]:
    nodes: list[JavaClassNode] = []
    for java_class in java_classes:
        qualified_name = f"{java_class.package_name}.{java_class.class_name}"
        nodes.append(
            JavaClassNode(
                id=f"class:{qualified_name}",
                name=java_class.class_name,
                qualified_name=qualified_name,
                package_name=java_class.package_name,
                layer=java_class.layer,
                file_path=java_class.file_path,
                is_interface=java_class.is_interface,
            )
        )
    return nodes


def _to_java_method_nodes(
    java_classes: list[JavaClass],
) -> tuple[list[JavaMethodNode], list[Rel]]:
    methods: list[JavaMethodNode] = []
    defines_method: list[Rel] = []
    for java_class in java_classes:
        class_id = f"class:{java_class.package_name}.{java_class.class_name}"
        for method in java_class.methods:
            methods.append(
                JavaMethodNode(
                    id=method.id,
                    qualified_name=method.qualified_name,
                    class_id=class_id,
                    class_name=method.class_name,
                    method_name=method.method_name,
                    file_path=method.file_path,
                    layer=method.layer,
                    start_line=method.start_line,
                    end_line=method.end_line,
                )
            )
            defines_method.append(Rel(from_id=class_id, to_id=method.id))
    return methods, defines_method


def _build_operations(
    java_classes: list[JavaClass],
    sql_nodes: list[SqlNode],
) -> tuple[list[OperationNode], list[Rel], list[Rel]]:
    operations: list[OperationNode] = []
    performs: list[Rel] = []
    realizes: list[Rel] = []
    sql_by_id = {sql.id: sql for sql in sql_nodes}

    for java_class in java_classes:
        if not java_class.class_name.endswith("Repository"):
            continue
        repository_fqn = f"{java_class.package_name}.{java_class.class_name}"
        for method in java_class.methods:
            sql_id = f"{repository_fqn}.{method.method_name}"
            if sql_id not in sql_by_id:
                continue
            sql = sql_by_id[sql_id]
            operation_id = f"operation:{sql_id}"
            operations.append(
                OperationNode(
                    id=operation_id,
                    name=f"{java_class.class_name}.{method.method_name}",
                    operation_type=sql.operation,
                    repository_method_id=method.id,
                    sql_id=sql_id,
                )
            )
            performs.append(Rel(from_id=method.id, to_id=operation_id))
            realizes.append(Rel(from_id=operation_id, to_id=sql_id))
    return operations, performs, realizes


def _build_concept_class_links(
    java_classes: list[JavaClass],
    concepts: list,
) -> list[Rel]:
    links: list[Rel] = []
    concept_by_name = {concept.name: concept.id for concept in concepts}
    for java_class in java_classes:
        if java_class.package_name.endswith(".domain.model"):
            concept_id = concept_by_name.get(java_class.class_name)
            if concept_id:
                links.append(
                    Rel(
                        from_id=concept_id,
                        to_id=f"class:{java_class.package_name}.{java_class.class_name}",
                    )
                )
    return links


def _entity_table_by_module(entities, form_fields) -> dict[str, str]:
    table_by_entity = {entity.name: entity.table_name for entity in entities if entity.table_name}
    mapping: dict[str, str] = {}
    for field in form_fields:
        entity_name = field.form_simple_name.replace("Form", "")
        table_name = table_by_entity.get(entity_name)
        if table_name:
            mapping[field.module] = table_name
    return mapping


def _build_ui_layer(
    java_classes: list[JavaClass],
    messages: dict[str, str],
    method_by_id: dict[str, JavaMethodNode],
    form_by_module: dict[str, str],
) -> tuple[list, list, list[Rel], list[Rel]]:
    from code_analysis.models import BusinessNode, ScreenNode

    screens: list[ScreenNode] = []
    businesses: list[BusinessNode] = []
    has_screen: list[Rel] = []
    implemented_by: list[Rel] = []
    seen_screens: set[str] = set()
    seen_businesses: set[str] = set()
    type_index = build_type_index(java_classes)

    for java_class in java_classes:
        if java_class.layer != "controller":
            continue
        module = _module_from_package(java_class.package_name)
        if not module:
            continue

        business_id = f"business:{module}"
        business_name = _business_name(module, messages)
        if business_id not in seen_businesses:
            businesses.append(BusinessNode(id=business_id, name=business_name, module=module))
            seen_businesses.add(business_id)

        for method in java_class.methods:
            linked_views = list(method.return_views)
            for view_path in linked_views:
                if view_path.startswith("redirect:"):
                    redirected = _resolve_redirect_view(view_path)
                    if redirected:
                        linked_views.append(redirected)

            service_method_id = _find_service_method(method, java_classes, type_index)
            target_method_id = service_method_id or method.id

            for view_path in linked_views:
                if view_path.startswith("redirect:"):
                    continue
                screen_id = f"screen:{view_path}"
                screen_name = _screen_name(module, view_path, messages)
                if screen_id not in seen_screens:
                    screens.append(
                        ScreenNode(
                            id=screen_id,
                            name=screen_name,
                            view_path=view_path,
                            module=module,
                            title_key=MODULE_SCREEN_KEYS.get(module),
                            form_class=form_by_module.get(module),
                        )
                    )
                    seen_screens.add(screen_id)
                    has_screen.append(Rel(from_id=business_id, to_id=screen_id))

                if target_method_id in method_by_id or service_method_id:
                    implemented_by.append(Rel(from_id=screen_id, to_id=target_method_id))

    return screens, businesses, has_screen, implemented_by


def _resolve_redirect_view(redirect_value: str) -> str | None:
    path = redirect_value.removeprefix("redirect:").lstrip("/")
    if "create" in path and "complete" in redirect_value:
        return "managecustomer/createComplete"
    if "?" in path:
        path = path.split("?", 1)[0]
    if path == "customers/create":
        return "managecustomer/createComplete"
    return None


def _find_service_method(
    controller_method: JavaMethod,
    java_classes: list[JavaClass],
    type_index: dict[str, str],
) -> str | None:
    for variable_name, callee_name in controller_method.calls:
        callee_id = resolve_method_call(
            controller_method, variable_name, callee_name, java_classes, type_index
        )
        if not callee_id:
            continue
        for java_class in java_classes:
            for method in java_class.methods:
                if method.id == callee_id and method.layer == "service":
                    return callee_id
    return None


def _build_calls(java_classes: list[JavaClass], type_index: dict[str, str]) -> list[Rel]:
    calls: list[Rel] = []
    seen: set[tuple[str, str]] = set()
    for java_class in java_classes:
        for method in java_class.methods:
            for variable_name, callee_name in method.calls:
                callee_id = resolve_method_call(
                    method, variable_name, callee_name, java_classes, type_index
                )
                if not callee_id or callee_id == method.id:
                    continue
                key = (method.id, callee_id)
                if key in seen:
                    continue
                calls.append(Rel(from_id=method.id, to_id=callee_id))
                seen.add(key)
    return calls


def _build_executes(java_classes: list[JavaClass], sql_nodes: list[SqlNode]) -> list[Rel]:
    executes: list[Rel] = []
    seen: set[tuple[str, str]] = set()
    sql_ids = {sql.id for sql in sql_nodes}

    for java_class in java_classes:
        if not java_class.class_name.endswith("Repository"):
            continue
        repository_fqn = f"{java_class.package_name}.{java_class.class_name}"
        for method in java_class.methods:
            sql_id = f"{repository_fqn}.{method.method_name}"
            if sql_id not in sql_ids:
                continue
            key = (method.id, sql_id)
            if key in seen:
                continue
            executes.append(Rel(from_id=method.id, to_id=sql_id))
            seen.add(key)
    return executes


def _module_from_package(package_name: str) -> str | None:
    marker = ".app."
    if marker not in package_name:
        return None
    return package_name.split(marker, 1)[1].split(".", 1)[0]


def _business_name(module: str, messages: dict[str, str]) -> str:
    key = MODULE_BUSINESS_KEYS.get(module)
    label = messages.get(key, module) if key else module
    if not label.endswith("業務"):
        return f"{label}業務"
    return label


def _screen_name(module: str, view_path: str, messages: dict[str, str]) -> str:
    key = MODULE_SCREEN_KEYS.get(module)
    if key and key in messages:
        return messages[key]
    view_name = view_path.split("/")[-1]
    return f"{view_name}画面"

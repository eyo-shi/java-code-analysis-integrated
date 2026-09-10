"""Link validation conditions to form fields, screens, and columns."""

from __future__ import annotations

import re

from code_analysis.models import ConditionNode, FormFieldNode, Rel
from code_analysis.parsers.column_mapper import column_id
from code_analysis.parsers.mybatis_parser import property_to_column_name


ANNOTATION_RULE_RE = re.compile(r"^(\w+)(?:\((.*)\))?$")
FIELD_FROM_MESSAGE_RE = re.compile(r"\.(\w+Form)\.(\w+)$|\.(\w+)$")


def build_validation_links(
    form_fields: list[FormFieldNode],
    screens: list,
    property_to_column: dict[str, str],
    entity_table_by_module: dict[str, str],
    validation_messages: dict[str, str],
    existing_conditions: list[ConditionNode],
    enforces: list[Rel],
    applies_to_screen: list[Rel],
) -> tuple[list[ConditionNode], list[Rel], list[Rel], list[Rel]]:
    conditions = list(existing_conditions)
    checks: list[Rel] = []
    validates: list[Rel] = []
    binds_to: list[Rel] = []
    seen_condition_ids: set[str] = {item.id for item in conditions}
    seen_checks: set[tuple[str, str]] = set()
    seen_validates: set[tuple[str, str]] = set()
    seen_binds: set[tuple[str, str]] = set()

    screens_by_module: dict[str, list] = {}
    for screen in screens:
        screens_by_module.setdefault(screen.module, []).append(screen)

    for field in form_fields:
        table_name = entity_table_by_module.get(field.module, _guess_table_from_form(field.form_simple_name))
        column_name = property_to_column_name(field.property_name, property_to_column)
        column_node_id = column_id(table_name, column_name)
        bind_key = (field.id, column_node_id)
        if bind_key not in seen_binds:
            binds_to.append(Rel(from_id=field.id, to_id=column_node_id))
            seen_binds.add(bind_key)

        for annotation in field.annotations:
            rule_type, constraint = _parse_annotation(annotation)
            if not rule_type:
                continue
            condition_id = f"condition:{field.form_class}.{field.property_name}:{rule_type}"
            if condition_id not in seen_condition_ids:
                message = _condition_message(field, rule_type, constraint, validation_messages)
                conditions.append(
                    ConditionNode(
                        id=condition_id,
                        name=message,
                        expression=annotation,
                        message_key=None,
                        field_name=field.property_name,
                        rule_type=rule_type,
                        constraint=constraint,
                        form_class=field.form_class,
                    )
                )
                seen_condition_ids.add(condition_id)

            check_key = (condition_id, column_node_id)
            if check_key not in seen_checks:
                checks.append(Rel(from_id=condition_id, to_id=column_node_id))
                seen_checks.add(check_key)

            for screen in screens_by_module.get(field.module, []):
                validate_key = (screen.id, condition_id)
                if validate_key not in seen_validates:
                    validates.append(Rel(from_id=screen.id, to_id=condition_id))
                    seen_validates.add(validate_key)

    for condition in conditions:
        if not condition.message_key:
            continue
        field_name = _field_name_from_message_key(condition.message_key)
        if not field_name:
            continue
        module = _module_from_message_key(condition.message_key, form_fields)
        table_name = entity_table_by_module.get(module, "UNKNOWN")
        column_name = property_to_column_name(field_name, property_to_column)
        column_node_id = column_id(table_name, column_name)
        if condition.field_name is None:
            condition.field_name = field_name
        check_key = (condition.id, column_node_id)
        if check_key not in seen_checks:
            checks.append(Rel(from_id=condition.id, to_id=column_node_id))
            seen_checks.add(check_key)
        for screen in screens_by_module.get(module, []):
            validate_key = (screen.id, condition.id)
            if validate_key not in seen_validates:
                validates.append(Rel(from_id=screen.id, to_id=condition.id))
                seen_validates.add(validate_key)
                applies_to_screen.append(Rel(from_id=condition.id, to_id=screen.id))

    return conditions, checks, validates, binds_to


def _parse_annotation(annotation: str) -> tuple[str | None, str | None]:
    match = ANNOTATION_RULE_RE.match(annotation)
    if not match:
        return None, None
    return match.group(1), match.group(2)


def _condition_message(
    field: FormFieldNode,
    rule_type: str,
    constraint: str | None,
    validation_messages: dict[str, str],
) -> str:
    for key, message in validation_messages.items():
        if field.property_name in key and rule_type in key:
            return message
    if constraint:
        return f"{field.property_name}: {rule_type}({constraint})"
    return f"{field.property_name}: {rule_type}"


def _field_name_from_message_key(message_key: str) -> str | None:
    match = FIELD_FROM_MESSAGE_RE.search(message_key)
    if not match:
        return None
    return match.group(2) or match.group(3)


def _module_from_message_key(message_key: str, form_fields: list[FormFieldNode]) -> str:
    for field in form_fields:
        if field.property_name in message_key:
            return field.module
    return "unknown"


def _guess_table_from_form(form_name: str) -> str:
    base = form_name.replace("Form", "")
    chars: list[str] = []
    for index, char in enumerate(base):
        if char.isupper() and index > 0:
            chars.append("_")
        chars.append(char.upper())
    return "".join(chars)

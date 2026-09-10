"""Parse Java source files for methods, layers, and call relationships."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)
CLASS_RE = re.compile(
    r"(?:public\s+)?(?:abstract\s+)?(?:class|interface|enum)\s+(\w+)",
    re.MULTILINE,
)
FIELD_RE = re.compile(
    r"(?:@\w+(?:\([^)]*\))?\s*)*(?:private|protected|public)?\s+([\w.<>,\s\[\]]+?)\s+(\w+)\s*;",
    re.MULTILINE,
)
METHOD_RE = re.compile(
    r"(?:@\w+(?:\([^)]*\))?\s*)*"
    r"(?:public|protected|private)?\s+"
    r"(?:static\s+)?(?:final\s+)?"
    r"([\w.<>,\s\[\]]+?)\s+(\w+)\s*\(([^)]*)\)\s*(?:throws\s+[\w.,\s]+)?\s*\{",
    re.MULTILINE,
)
INTERFACE_METHOD_RE = re.compile(
    r"(?:public\s+)?([\w.<>,\s\[\]]+?)\s+(\w+)\s*\(([^)]*)\)\s*;",
    re.MULTILINE,
)
REQUEST_MAPPING_CLASS_RE = re.compile(
    r"@RequestMapping\s*\(\s*(?:value\s*=\s*)?[\"']([^\"']+)[\"']",
    re.MULTILINE,
)
REQUEST_MAPPING_METHOD_RE = re.compile(
    r"@RequestMapping\s*\((.*?)\)\s*"
    r"(?:public|protected|private)?\s+"
    r"[\w.<>,\s\[\]]+\s+(\w+)\s*\(",
    re.DOTALL,
)
RETURN_STRING_RE = re.compile(r"return\s+[\"']([^\"']+)[\"']\s*;")
CALL_RE = re.compile(r"(\w+)\.(\w+)\s*\(")
IMPLEMENTS_RE = re.compile(r"implements\s+([\w.,\s]+)")
SIMPLE_TYPE_RE = re.compile(r"^[\w.]+$")


@dataclass
class JavaField:
    name: str
    type_name: str


@dataclass
class JavaMethod:
    id: str
    qualified_name: str
    class_name: str
    method_name: str
    file_path: str
    layer: str
    package_name: str
    start_line: int
    end_line: int
    body: str
    fields: list[JavaField] = field(default_factory=list)
    return_views: list[str] = field(default_factory=list)
    request_paths: list[str] = field(default_factory=list)
    calls: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class JavaClass:
    package_name: str
    class_name: str
    file_path: str
    layer: str
    is_interface: bool
    implements: list[str]
    fields: list[JavaField]
    methods: list[JavaMethod]


def parse_java_sources(root: Path, exclude_dirs: tuple[str, ...]) -> list[JavaClass]:
    classes: list[JavaClass] = []
    for java_path in sorted(root.rglob("*.java")):
        if _is_excluded(java_path, exclude_dirs):
            continue
        if "/test/" in str(java_path).replace("\\", "/"):
            continue
        parsed = _parse_java_file(java_path)
        if parsed:
            classes.append(parsed)
    return classes


def _is_excluded(path: Path, exclude_dirs: tuple[str, ...]) -> bool:
    return any(part in exclude_dirs for part in path.parts)


def _parse_java_file(path: Path) -> JavaClass | None:
    content = path.read_text(encoding="utf-8", errors="ignore")
    package_match = PACKAGE_RE.search(content)
    class_match = CLASS_RE.search(content)
    if not package_match or not class_match:
        return None

    package_name = package_match.group(1)
    class_name = class_match.group(1)
    is_interface = "interface " + class_name in content
    layer = _detect_layer(package_name, class_name, content)
    implements = [
        part.strip()
        for part in IMPLEMENTS_RE.search(content).group(1).split(",")
        if IMPLEMENTS_RE.search(content) and part.strip()
    ] if IMPLEMENTS_RE.search(content) else []

    fields = _parse_fields(content)
    methods = _parse_methods(content, package_name, class_name, str(path), layer, fields)
    if is_interface:
        methods.extend(
            _parse_interface_methods(content, package_name, class_name, str(path), layer)
        )
    return JavaClass(
        package_name=package_name,
        class_name=class_name,
        file_path=str(path),
        layer=layer,
        is_interface=is_interface,
        implements=implements,
        fields=fields,
        methods=methods,
    )


def _detect_layer(package_name: str, class_name: str, content: str) -> str:
    if "Controller" in class_name or "@Controller" in content:
        return "controller"
    if ".repository." in package_name or class_name.endswith("Repository"):
        return "repository"
    if ".service." in package_name or "Service" in class_name:
        return "service"
    return "other"


def _parse_fields(content: str) -> list[JavaField]:
    fields: list[JavaField] = []
    for match in FIELD_RE.finditer(content):
        raw_type = match.group(1).strip()
        parts = raw_type.split()
        if not parts:
            continue
        type_name = parts[-1]
        name = match.group(2)
        if name in {"class", "interface"}:
            continue
        fields.append(JavaField(name=name, type_name=_normalize_type(type_name)))
    return fields


def _parse_methods(
    content: str,
    package_name: str,
    class_name: str,
    file_path: str,
    layer: str,
    fields: list[JavaField],
) -> list[JavaMethod]:
    methods: list[JavaMethod] = []
    class_prefix = _extract_class_request_prefix(content)

    for match in METHOD_RE.finditer(content):
        method_name = match.group(2)
        if method_name == class_name:
            continue
        start = match.start()
        body = _extract_block(content, match.end() - 1)
        start_line = content.count("\n", 0, start) + 1
        end_line = start_line + body.count("\n")
        qualified = f"{package_name}.{class_name}.{method_name}"
        method_prefix = content[max(0, start - 400) : start]
        request_paths = _extract_method_request_paths(method_prefix, class_prefix)
        return_views = RETURN_STRING_RE.findall(body)
        calls = [(caller, callee) for caller, callee in CALL_RE.findall(body) if caller != "super"]
        methods.append(
            JavaMethod(
                id=qualified,
                qualified_name=qualified,
                class_name=class_name,
                method_name=method_name,
                file_path=file_path,
                layer=layer,
                package_name=package_name,
                start_line=start_line,
                end_line=end_line,
                body=body,
                fields=fields,
                return_views=return_views,
                request_paths=request_paths,
                calls=calls,
            )
        )
    return methods


def _parse_interface_methods(
    content: str,
    package_name: str,
    class_name: str,
    file_path: str,
    layer: str,
) -> list[JavaMethod]:
    methods: list[JavaMethod] = []
    existing = {
        method.method_name
        for method in _parse_methods(content, package_name, class_name, file_path, layer, [])
    }
    for match in INTERFACE_METHOD_RE.finditer(content):
        method_name = match.group(2)
        if method_name in existing:
            continue
        start = match.start()
        qualified = f"{package_name}.{class_name}.{method_name}"
        start_line = content.count("\n", 0, start) + 1
        methods.append(
            JavaMethod(
                id=qualified,
                qualified_name=qualified,
                class_name=class_name,
                method_name=method_name,
                file_path=file_path,
                layer=layer,
                package_name=package_name,
                start_line=start_line,
                end_line=start_line,
                body="",
                fields=[],
                return_views=[],
                request_paths=[],
                calls=[],
            )
        )
    return methods


def _extract_class_request_prefix(content: str) -> str | None:
    match = REQUEST_MAPPING_CLASS_RE.search(content)
    return match.group(1) if match else None


def _extract_method_request_paths(prefix: str, class_prefix: str | None) -> list[str]:
    paths: list[str] = []
    for match in REQUEST_MAPPING_METHOD_RE.finditer(prefix):
        args = match.group(1)
        value_match = re.search(r"value\s*=\s*[\"']([^\"']+)[\"']", args)
        if value_match:
            value = value_match.group(1)
            if class_prefix:
                paths.append(f"{class_prefix.rstrip('/')}/{value}".replace("//", "/"))
            else:
                paths.append(value)
    return paths


def _extract_block(content: str, open_brace_index: int) -> str:
    depth = 0
    for index in range(open_brace_index, len(content)):
        char = content[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[open_brace_index : index + 1]
    return ""


def _normalize_type(type_name: str) -> str:
    cleaned = type_name.replace("<", " ").replace(">", " ").replace(",", " ")
    parts = [part for part in cleaned.split() if SIMPLE_TYPE_RE.match(part)]
    return parts[-1] if parts else type_name


def build_type_index(classes: list[JavaClass]) -> dict[str, str]:
    index: dict[str, str] = {}
    for java_class in classes:
        fqn = f"{java_class.package_name}.{java_class.class_name}"
        index[java_class.class_name] = fqn
        index[fqn] = fqn
    for java_class in classes:
        if java_class.is_interface:
            continue
        for interface_name in java_class.implements:
            simple = interface_name.split(".")[-1]
            index[simple] = f"{java_class.package_name}.{java_class.class_name}"
    return index


def resolve_method_call(
    caller: JavaMethod,
    variable_name: str,
    method_name: str,
    classes: list[JavaClass],
    type_index: dict[str, str],
) -> str | None:
    field_type = None
    for field in caller.fields:
        if field.name == variable_name:
            field_type = field.type_name
            break
    if not field_type:
        return None

    target_class = type_index.get(field_type, field_type)
    target_simple = target_class.split(".")[-1]

    for java_class in classes:
        if java_class.class_name != target_simple and target_class not in {
            f"{java_class.package_name}.{java_class.class_name}",
            java_class.class_name,
        }:
            continue
        if java_class.is_interface:
            continue
        for method in java_class.methods:
            if method.method_name == method_name:
                return method.id

    for java_class in classes:
        if java_class.class_name != target_simple and target_class not in {
            f"{java_class.package_name}.{java_class.class_name}",
            java_class.class_name,
        }:
            continue
        for method in java_class.methods:
            if method.method_name == method_name:
                return method.id
    return None

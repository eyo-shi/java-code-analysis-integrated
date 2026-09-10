"""Parse design documents from repository files."""

from __future__ import annotations

from pathlib import Path

from code_analysis.models import DesignDocumentNode, Rel


def parse_design_documents(root: Path, project_id: str) -> tuple[list[DesignDocumentNode], list[Rel]]:
    documents: list[DesignDocumentNode] = []
    describes: list[Rel] = []
    seen_paths: set[str] = set()

    candidates: list[Path] = []
    root_readme = root / "README.md"
    if root_readme.exists():
        candidates.append(root_readme)

    for path in sorted(root.rglob("README.md")):
        if path == root_readme:
            continue
        if len(candidates) >= 5:
            break
        candidates.append(path)

    for path in sorted(root.rglob("**/META-INF/**/*mapping*.xml")):
        if len(candidates) >= 8:
            break
        candidates.append(path)

    for path in candidates:
        relative_path = str(path.relative_to(root))
        if relative_path in seen_paths:
            continue
        seen_paths.add(relative_path)
        doc_type = path.suffix.lstrip(".") or "markdown"
        doc_id = f"doc:{relative_path}"
        documents.append(
            DesignDocumentNode(
                id=doc_id,
                name=path.name,
                file_path=str(path),
                doc_type=doc_type,
            )
        )
        describes.append(Rel(from_id=doc_id, to_id=project_id))

    return documents, describes

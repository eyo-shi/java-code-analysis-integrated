"""CML session entry point: clone, analyze, and ingest into Neo4j."""

from __future__ import annotations

import sys
from pathlib import Path


def _project_root() -> Path:
    try:
        return Path(__file__).resolve().parents[1]
    except NameError:
        cwd = Path.cwd()
        if (cwd / "code_analysis").is_dir():
            return cwd
        parent = cwd.parent
        if (parent / "code_analysis").is_dir():
            return parent
        return cwd


ROOT = _project_root()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from code_analysis.config import Config
from code_analysis.graph_builder import build_graph
from code_analysis.neo4j_loader import Neo4jLoader
from code_analysis.source_fetcher import resolve_source_path


def main() -> None:
    config = Config.from_env()
    config.validate_for_ingest()
    print(f"Configuration: {config.log_summary()}")

    source_root = resolve_source_path(
        config.source_path,
        config.git_repo_url,
        config.git_ref,
        config.clone_dir,
    )

    print("Building analysis graph...")
    graph = build_graph(
        root=source_root,
        project_id=config.project_id,
        project_name=config.project_name,
        repo_url=config.git_repo_url or str(source_root),
        git_ref=config.git_ref,
        exclude_dirs=config.exclude_dirs,
    )
    summary = graph.summary()
    print("Graph summary:")
    for key, value in summary.items():
        print(f"  {key}: {value}")

    print(f"Connecting to Neo4j at {config.neo4j_uri}")
    loader = Neo4jLoader(config.neo4j_uri, config.neo4j_username, config.neo4j_password)
    try:
        loader.ingest(graph)
    finally:
        loader.close()

    print("Ingestion completed successfully.")
    print(f"Project id for Cypher queries: {config.project_id}")
    print("Example Cypher:")
    print(
        f"""
MATCH (n)
WHERE n.project_id = '{config.project_id}'
RETURN labels(n)[0] AS label, count(*) AS count
ORDER BY count DESC
        """.strip()
    )


if __name__ == "__main__":
    main()

"""Neo4j connection URI helpers for CML neo4j-launcher."""

from __future__ import annotations

import os
from urllib.parse import urlparse

# CML neo4j-launcher exposes several URLs. Only the ones that are actually Bolt
# endpoints are useful here:
#   - Internal Bolt (`cml-neo4j-<hash>.mlx-user-<id>`) works only from within the
#     same AMP project's Kubernetes namespace.
#   - External Bolt via AWS ELB (`*.elb.amazonaws.com`) is reachable across
#     namespaces, so it is the only option when the analysis AMP runs in a
#     different project from neo4j-launcher.
#   - The `*.cloudera.site` URL is the *browser* proxy and is NOT a Bolt
#     endpoint; connecting to it will always fail.
_BROWSER_HOST_MARKERS = (".cloudera.site",)
_EXTERNAL_BOLT_HOST_MARKERS = (".elb.amazonaws.com", ".amazonaws.com")


def _is_browser_neo4j_host(host: str) -> bool:
    lowered = host.lower()
    return any(marker in lowered for marker in _BROWSER_HOST_MARKERS)


def _is_external_bolt_neo4j_host(host: str) -> bool:
    lowered = host.lower()
    return any(marker in lowered for marker in _EXTERNAL_BOLT_HOST_MARKERS)


def _is_cml_internal_neo4j_host(host: str) -> bool:
    """True for Internal Bolt hosts shown in neo4j-launcher Application Log."""
    lowered = host.lower()
    return lowered.startswith("cml-neo4j-") or ".mlx-user-" in lowered


def _parse_uri(uri: str) -> tuple[str, str, int, str]:
    text = uri.strip()
    if "://" not in text:
        text = f"bolt://{text}"
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    port = parsed.port or 7687
    scheme = (parsed.scheme or "bolt").lower()
    return text, host, port, scheme


def iter_neo4j_connection_uris(
    uri: str,
    *,
    internal_uri: str | None = None,
) -> list[str]:
    """
    Build URIs to try when connecting from a CML job.

    Use the "Internal Bolt" value from neo4j-launcher Application Log, e.g.
    bolt://cml-neo4j-<hash>.mlx-user-<id>:7687
    """
    internal_uri = (internal_uri or os.environ.get("NEO4J_INTERNAL_URI", "")).strip() or None

    _, host, port, scheme = _parse_uri(uri)
    if not host and not internal_uri:
        return [uri.strip() if "://" in uri else f"bolt://{uri.strip()}"]

    seen: set[str] = set()
    ordered: list[str] = []

    def add(candidate: str) -> None:
        normalized = candidate.strip()
        if "://" not in normalized:
            normalized = f"bolt://{normalized}"
        if normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)

    def add_host(candidate_scheme: str, candidate_host: str) -> None:
        add(f"{candidate_scheme}://{candidate_host}:{port}")

    if internal_uri:
        add(internal_uri)

    if host and _is_cml_internal_neo4j_host(host):
        add_host(scheme, host)
        # Fallback: the bare Kubernetes Service name inside the same project.
        # Helps when the pod-hash portion of the Internal Bolt URI is stale
        # (neo4j-launcher restarted since the URI was copied) but the Service
        # itself is still reachable. Only useful if this AMP shares a namespace
        # with neo4j-launcher; cross-AMP callers must use the External Bolt URL.
        add_host("bolt", "neo4j-launcher")
        return ordered

    if host and _is_browser_neo4j_host(host):
        # `*.cloudera.site` is neo4j-launcher's browser proxy, not a Bolt
        # endpoint. Nothing to try.
        return ordered

    if host and _is_external_bolt_neo4j_host(host):
        # ELB Bolt endpoint. Use it as-is: it is reachable from every namespace
        # in the workspace, so no in-cluster fallback applies.
        add_host(scheme, host)
        return ordered

    if host:
        add_host(scheme, host)
        if scheme in {"bolt+ssc", "bolt+s", "neo4j+ssc", "neo4j+s"}:
            add_host("bolt", host)

    if host and "neo4j-launcher" in host:
        add_host("bolt", "neo4j-launcher")

    return ordered or [uri.strip()]


def format_neo4j_connection_help(configured_uri: str, errors: list[str]) -> str:
    internal_example = (
        os.environ.get("NEO4J_INTERNAL_URI", "").strip()
        or "bolt://cml-neo4j-<hash>.mlx-user-<id>:7687"
    )
    attempts = "\n".join(errors) if errors else "  (no attempts recorded)"
    return (
        f"Could not connect to Neo4j (configured: {configured_uri}).\n"
        f"Attempts:\n{attempts}\n"
        "CML neo4j-launcher checklist:\n"
        "  1. neo4j-launcher application is Running (Applications page)\n"
        "  2. Copy a Bolt URL from neo4j-launcher Application Log into NEO4J_URI\n"
        "     - Same AMP project as neo4j-launcher: Internal Bolt\n"
        f"       Example: {internal_example}\n"
        "     - Different AMP project (cross-namespace): External Bolt (ELB)\n"
        "       Example: bolt://<lb-id>.<region>.elb.amazonaws.com:7687\n"
        "     Do not use browser URL (*.cloudera.site) — that is not a Bolt endpoint\n"
        "  3. NEO4J_PASSWORD is the password from neo4j-launcher startup\n"
        "  4. NEO4J_USERNAME is usually neo4j"
    )

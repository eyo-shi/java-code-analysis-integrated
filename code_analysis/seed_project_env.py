"""Seed CML project environment variables on AMP deploy (Churn AMP pattern)."""

from __future__ import annotations

import os

from code_analysis.config import (
    MANAGED_ENV_VARS,
    PROJECT_ENV_SEEDS,
    parse_env_value,
    read_cml_project_env,
)


def _cml_bootstrap_client():
    from cmlbootstrap import CMLBootstrap

    host = os.getenv("CDSW_API_URL", "").split(":")[0] + "://" + os.getenv("CDSW_DOMAIN", "")
    username = os.getenv("CDSW_PROJECT_URL", "").split("/")[6]
    api_key = os.getenv("CDSW_API_KEY", "")
    project_name = os.getenv("CDSW_PROJECT", "")
    if not all([host, username, api_key, project_name]):
        raise RuntimeError(
            "CML platform variables are missing (CDSW_API_URL, CDSW_DOMAIN, "
            "CDSW_PROJECT_URL, CDSW_API_KEY, CDSW_PROJECT)."
        )
    return CMLBootstrap(host, username, api_key, project_name)


def seed_project_environment() -> dict[str, str]:
    """
    Create managed project environment variables with placeholder defaults.

    Uses cmlbootstrap.create_environment_variable() so keys appear in
    Project Settings > Advanced > Environment Variables after deploy.
    Existing values are not overwritten.
    """
    if not os.environ.get("CDSW_PROJECT_ID"):
        print("Skip project environment seed (not in CML runtime).")
        return {}

    updates: dict[str, str] = {}
    for name in MANAGED_ENV_VARS:
        if read_cml_project_env(name):
            continue
        # AMP writes Config Project screen values into os.environ before the
        # first job runs. Trust that value rather than overwriting it with the
        # placeholder — otherwise we clobber user input whenever cmlapi is not
        # importable at job runtime (read_cml_project_env returns None).
        if parse_env_value(name, os.environ.get(name)):
            continue
        value = PROJECT_ENV_SEEDS.get(name, "").strip()
        if not value:
            continue
        updates[name] = value

    if not updates:
        print("Managed project environment variables already present; nothing to seed.")
        return {}

    client = _cml_bootstrap_client()
    client.create_environment_variable(updates)
    for key, value in updates.items():
        os.environ[key] = value

    print(f"Seeded project environment variables: {sorted(updates.keys())}")
    print(
        "Update NEO4J_URI (Internal Bolt from neo4j-launcher Application Log) "
        "and NEO4J_PASSWORD in Project Settings > Advanced > Environment Variables."
    )
    return updates

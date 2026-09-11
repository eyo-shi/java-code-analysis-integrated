"""Configuration loaded from CML project environment variables (os.environ)."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# Environment variables read from CML project settings (os.environ at job runtime).
MANAGED_ENV_VARS: tuple[str, ...] = (
    "GIT_REPO_URL",
    "GIT_REF",
    "NEO4J_URI",
    "NEO4J_USERNAME",
    "NEO4J_PASSWORD",
    "CLONE_DIR",
    "SOURCE_PATH",
    "PROJECT_ID",
    "PROJECT_NAME",
    "EXCLUDE_DIRS",
)

SENSITIVE_ENV_VARS: frozenset[str] = frozenset({"NEO4J_PASSWORD"})

# Non-empty defaults for AMP deploy and Project Settings seeding (Churn AMP pattern).
# In this integrated AMP the Neo4j Launcher Application runs in the same
# Project namespace as the Analyze and Ingest job, so the Internal Bolt URI
# (bolt://cml-neo4j-<hash>.mlx-user-<id>:7687) from the Application Log works
# directly. The placeholders below are overwritten by the user after Neo4j
# reaches Running.
PROJECT_ENV_SEEDS: dict[str, str] = {
    "GIT_REPO_URL": "https://github.com/terasolunaorg/terasoluna-tourreservation-mybatis3",
    "GIT_REF": "release/5.7.1.SP1.RELEASE",
    "NEO4J_URI": "bolt://cml-neo4j-REPLACE_FROM_APPLICATION_LOG.mlx-user-0:7687",
    "NEO4J_USERNAME": "neo4j",
    "NEO4J_PASSWORD": "Neo4jPass1234",
    "CLONE_DIR": "/tmp/source",
    "SOURCE_PATH": "-",
    "PROJECT_ID": "-",
    "PROJECT_NAME": "-",
    "EXCLUDE_DIRS": ".git,target,node_modules,venv,.venv,dist,build,__pycache__,.m2",
}

# Local-dev fallbacks; aligned with PROJECT_ENV_SEEDS / .project-metadata.yaml.
METADATA_DEFAULTS: dict[str, str] = dict(PROJECT_ENV_SEEDS)

OPTIONAL_UNSET_VALUE = "-"

_CORRUPTED_MARKERS = ("dispatchConfig", "_dispatchListeners", "nativeEvent", "isTrusted")


def _optional_env_value(name: str, value: str | None) -> str | None:
    if value is None:
        return None
    if value.strip() == OPTIONAL_UNSET_VALUE:
        return None
    return value


def validate_neo4j_uri_for_ingest(uri: str) -> None:
    lowered = uri.lower()
    if "replace_from_application_log" in lowered or "replace_from_neo4j" in lowered:
        raise ValueError(
            "NEO4J_URI is still the placeholder. Once the co-located "
            "Neo4j Launcher Application is Running, copy the Internal Bolt "
            "URI from its Application Log "
            "(bolt://cml-neo4j-<hash>.mlx-user-<id>:7687) into "
            "Project Settings > Advanced > Environment Variables."
        )
    if ".cloudera.site" in lowered:
        # `*.cloudera.site` is the browser proxy (HTTP), not a Bolt endpoint —
        # connecting to it always fails, so reject early with a clear message.
        raise ValueError(
            "NEO4J_URI is a neo4j-launcher browser URL (*.cloudera.site), not Bolt. "
            "Use Internal Bolt (same project) or External Bolt (cross project) "
            "from the neo4j-launcher Application Log."
        )


def _in_cml_runtime() -> bool:
    return bool(os.environ.get("CDSW_PROJECT_ID"))


def _looks_corrupted(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    if any(marker in text for marker in _CORRUPTED_MARKERS):
        return True
    return text.startswith("{") and "}" in text


def _validate_env_value(name: str, value: str) -> bool:
    if name == "GIT_REPO_URL":
        return value.startswith(("http://", "https://", "git@"))
    if name == "NEO4J_URI":
        return value.startswith(
            (
                "bolt://",
                "bolt+s://",
                "bolt+ssc://",
                "neo4j://",
                "neo4j+s://",
                "neo4j+ssc://",
            )
        )
    if name == "GIT_REF":
        return not _looks_corrupted(value) and len(value) <= 256
    if name == "SOURCE_PATH":
        return not _looks_corrupted(value)
    return not _looks_corrupted(value) or name == "EXCLUDE_DIRS"


def _normalize_env_value(name: str, value: str) -> str:
    text = value.strip()
    if name == "NEO4J_URI" and "://" not in text:
        text = f"bolt://{text}"
    return text


def read_cml_project_env(name: str) -> str | None:
    """Read a value from CML project environment variables (SKILL section 2)."""
    project_id = os.environ.get("CDSW_PROJECT_ID")
    if not project_id:
        return None

    try:
        import cmlapi
    except ImportError:
        return None

    try:
        project = cmlapi.default_client().get_project(project_id)
        raw_env = getattr(project, "environment", None)
        if raw_env is None:
            return None
        if isinstance(raw_env, str):
            parsed = json.loads(raw_env)
        elif isinstance(raw_env, dict):
            parsed = raw_env
        else:
            return None
        if not isinstance(parsed, dict):
            return None
        return parse_env_value(name, parsed.get(name))
    except Exception as exc:
        print(f"Warning: could not read {name} from CML project environment: {exc}")
        return None


def is_metadata_default(name: str, value: str) -> bool:
    default = METADATA_DEFAULTS.get(name)
    if not default:
        return False
    parsed = parse_env_value(name, value)
    parsed_default = parse_env_value(name, default)
    return parsed is not None and parsed == parsed_default


def parse_env_value(name: str, raw: object) -> str | None:
    """Parse a raw project environment value into a plain string."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text or _looks_corrupted(text):
        return None
    normalized = _normalize_env_value(name, text)
    if _validate_env_value(name, normalized):
        return normalized
    return None


def _env(name: str, default: str | None = None) -> str | None:
    """Read a managed environment variable (project env first in CML, then os.environ)."""
    if _in_cml_runtime():
        from_project = read_cml_project_env(name)
        if from_project:
            return from_project

    raw = os.environ.get(name)
    if raw is not None:
        text = raw.strip()
        if text:
            if _looks_corrupted(text):
                print(
                    f"Warning: ignoring corrupted {name} in os.environ "
                    "(React event object; set a plain string in "
                    "Project Settings > Advanced > Environment Variables)."
                )
                return default
            normalized = _normalize_env_value(name, text)
            if _validate_env_value(name, normalized):
                return normalized
            print(f"Warning: ignoring invalid {name} in os.environ.")
            return default

    if default is not None and default.strip():
        return default.strip()

    if not _in_cml_runtime():
        metadata_default = METADATA_DEFAULTS.get(name)
        if metadata_default and metadata_default.strip():
            return metadata_default.strip()
    return None


def _mask_value(name: str, value: str) -> str:
    if name in SENSITIVE_ENV_VARS:
        if len(value) <= 4:
            return "***"
        return f"{value[:3]}...{value[-2:]}"
    return value


def diagnose_environment() -> None:
    """Print managed environment variables visible in os.environ."""
    print("=== Environment variable diagnostic ===")
    print(
        "Managed environment variables are set in "
        "Project Settings > Advanced > Environment Variables."
    )
    for name in MANAGED_ENV_VARS:
        raw = os.environ.get(name)
        from_project = read_cml_project_env(name) if _in_cml_runtime() else None
        resolved = _env(name)

        if resolved is None:
            if raw is None or not str(raw).strip():
                if from_project is None:
                    print(f"  {name}: MISSING")
                else:
                    print(f"  {name}: INVALID")
            elif _looks_corrupted(str(raw)):
                print(f"  {name}: CORRUPTED (React event object in os.environ)")
            else:
                print(f"  {name}: INVALID ({_mask_value(name, str(raw).strip())})")
            continue

        source = "CML project environment" if from_project == resolved else "os.environ"
        if (
            from_project
            and raw
            and str(raw).strip()
            and not _looks_corrupted(str(raw))
            and from_project != parse_env_value(name, str(raw))
        ):
            print(
                f"  {name}: SET ({_mask_value(name, resolved)}) [{source}; "
                f"os.environ has {_mask_value(name, str(raw).strip())}]"
            )
        elif is_metadata_default(name, resolved):
            print(
                f"  {name}: SET ({_mask_value(name, resolved)}) [metadata default; "
                "update in Project Settings > Advanced > Environment Variables]"
            )
        else:
            print(f"  {name}: SET ({_mask_value(name, resolved)}) [{source}]")
    print(f"  CDSW_PROJECT_ID: {os.environ.get('CDSW_PROJECT_ID', 'MISSING')}")
    print("========================================")


def derive_project_id(repo_url: str) -> str:
    """Derive a stable project id from a git repository URL."""
    parsed = urlparse(repo_url)
    path = parsed.path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    name = path.split("/")[-1] if path else repo_url
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")
    return normalized or "java-project"


def derive_project_name(repo_url: str) -> str:
    project_id = derive_project_id(repo_url)
    return project_id.replace("-", " ").replace("_", " ").title()


@dataclass
class Config:
    neo4j_uri: str
    neo4j_username: str
    neo4j_password: str
    git_repo_url: str | None
    git_ref: str
    clone_dir: str
    source_path: str | None
    project_id: str
    project_name: str
    exclude_dirs: tuple[str, ...]

    @classmethod
    def from_env(cls) -> Config:
        diagnose_environment()

        neo4j_uri = _env("NEO4J_URI")
        if not neo4j_uri:
            raise ValueError(
                "NEO4J_URI is required. Set it in "
                "Project Settings > Advanced > Environment Variables, "
                "then run the 'Analyze and Ingest' job."
            )

        source_path = _optional_env_value("SOURCE_PATH", _env("SOURCE_PATH"))
        git_repo_url = _env("GIT_REPO_URL")

        if not source_path and not git_repo_url:
            raise ValueError(
                "GIT_REPO_URL is required when SOURCE_PATH is not set. Set it in "
                "Project Settings > Advanced > Environment Variables."
            )

        if git_repo_url:
            default_id = derive_project_id(git_repo_url)
            default_name = derive_project_name(git_repo_url)
        else:
            default_id = Path(source_path).name
            default_name = derive_project_name(default_id)

        return cls(
            neo4j_uri=neo4j_uri,
            neo4j_username=_env("NEO4J_USERNAME", "neo4j") or "neo4j",
            neo4j_password=_env("NEO4J_PASSWORD", "") or "",
            git_repo_url=git_repo_url,
            git_ref=_env("GIT_REF", METADATA_DEFAULTS["GIT_REF"]) or METADATA_DEFAULTS["GIT_REF"],
            clone_dir=_env("CLONE_DIR", "/tmp/source") or "/tmp/source",
            source_path=source_path,
            project_id=_optional_env_value("PROJECT_ID", _env("PROJECT_ID")) or default_id,
            project_name=_optional_env_value("PROJECT_NAME", _env("PROJECT_NAME")) or default_name,
            exclude_dirs=tuple(
                part.strip()
                for part in (
                    _env(
                        "EXCLUDE_DIRS",
                        ".git,target,node_modules,venv,.venv,dist,build,__pycache__,.m2",
                    )
                    or ".git,target,node_modules,venv,.venv,dist,build,__pycache__,.m2"
                ).split(",")
                if part.strip()
            ),
        )

    def validate_for_ingest(self) -> None:
        validate_neo4j_uri_for_ingest(self.neo4j_uri)
        password = self.neo4j_password.strip()
        if password == "":
            raise ValueError(
                "NEO4J_PASSWORD is empty. Set it in Project Settings > Advanced > "
                "Environment Variables (built-in default: Neo4jPass1234)."
            )
        if password == "REPLACE_FROM_NEO4J_LAUNCHER":
            # Legacy placeholder from an earlier version of this AMP. Existing
            # deploys may still carry this string in the project environment;
            # surface a clear error rather than trying to authenticate with it.
            raise ValueError(
                "NEO4J_PASSWORD is still the old placeholder from a prior deploy. "
                "Update it in Project Settings > Advanced > Environment Variables "
                "(the built-in default is now Neo4jPass1234)."
            )
        if not self.source_path and not self.git_repo_url:
            raise ValueError("GIT_REPO_URL is required when SOURCE_PATH is not set")
        if not self.source_path and not self.git_ref:
            raise ValueError("GIT_REF is required when cloning from GIT_REPO_URL")

    def log_summary(self) -> str:
        lines = [
            f"project_id={self.project_id}",
            f"project_name={self.project_name}",
            f"git_ref={self.git_ref}",
            f"neo4j_uri={self.neo4j_uri}",
        ]
        if self.source_path:
            lines.append(f"source_path={self.source_path}")
        else:
            lines.append(f"git_repo_url={self.git_repo_url}")
        return ", ".join(lines)

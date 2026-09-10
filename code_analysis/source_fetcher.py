"""Fetch source code via git clone or an existing path."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def resolve_source_path(
    source_path: str | None,
    git_repo_url: str | None,
    git_ref: str,
    clone_dir: str,
) -> Path:
    if source_path:
        path = Path(source_path).resolve()
        if not path.exists():
            raise FileNotFoundError(f"SOURCE_PATH does not exist: {path}")
        print(f"Using existing source path: {path}")
        return path

    if not git_repo_url:
        raise ValueError("GIT_REPO_URL is required when SOURCE_PATH is not set")

    if not git_ref or not git_ref.strip():
        raise ValueError("GIT_REF is required when cloning from GIT_REPO_URL")

    git_repo_url = git_repo_url.strip()
    git_ref = git_ref.strip()

    target = Path(clone_dir).resolve()
    if target.exists():
        shutil.rmtree(target)

    print(f"Cloning {git_repo_url} (ref={git_ref}) into {target}")
    result = subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            git_ref,
            git_repo_url,
            str(target),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(
            f"git clone failed for ref '{git_ref}'.\n"
            f"{stderr}\n"
            "Set GIT_REF in AMP Configuration or Project Settings > Advanced to an "
            "existing branch or tag (this repository has no 'main' branch; "
            "e.g. release/5.7.1.SP1.RELEASE or master)."
        )
    return target

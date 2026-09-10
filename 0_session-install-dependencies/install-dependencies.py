"""Install dependencies and seed managed project environment variables.

Runs as the CML AMP "Install Dependencies" job. Combines the neo4j-launcher
setup (kubernetes + neo4j drivers) with the Java analysis setup (neo4j driver
+ cmlbootstrap), then creates placeholder keys under
Project Settings > Advanced > Environment Variables so the user only has to
fill in the Neo4j credentials after the co-located Neo4j Launcher starts.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _project_root() -> Path:
    """Resolve the project root whether run as a script (Job) or a cell (Session)."""
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

print(subprocess.run(["sh 0_session-install-dependencies/setup.sh"], shell=True, check=False))

from code_analysis.seed_project_env import seed_project_environment

seed_project_environment()

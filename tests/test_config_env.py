"""Tests for AMP Configuration -> os.environ resolution."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from code_analysis.config import (
    MANAGED_ENV_VARS,
    METADATA_DEFAULTS,
    Config,
    _env,
    _looks_corrupted,
    diagnose_environment,
)


class ConfigEnvResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved = {key: os.environ.get(key) for key in MANAGED_ENV_VARS}
        self._saved["CDSW_PROJECT_ID"] = os.environ.get("CDSW_PROJECT_ID")
        for key in list(MANAGED_ENV_VARS) + ["CDSW_PROJECT_ID"]:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key in list(MANAGED_ENV_VARS) + ["CDSW_PROJECT_ID"]:
            os.environ.pop(key, None)
        for key, value in self._saved.items():
            if value is not None:
                os.environ[key] = value

    def test_managed_env_vars_are_documented(self) -> None:
        self.assertEqual(len(MANAGED_ENV_VARS), 10)
        self.assertIn("NEO4J_URI", MANAGED_ENV_VARS)

    def test_reads_from_os_environ(self) -> None:
        os.environ["NEO4J_URI"] = "bolt://neo4j.example:7687"
        os.environ["GIT_REPO_URL"] = "https://github.com/example/app.git"
        os.environ["GIT_REF"] = "develop"
        self.assertEqual(_env("NEO4J_URI"), "bolt://neo4j.example:7687")
        self.assertEqual(_env("GIT_REF"), "develop")

    def test_rejects_corrupted_react_event(self) -> None:
        os.environ["NEO4J_URI"] = json.dumps(
            {"dispatchConfig": None, "nativeEvent": None}
        )
        self.assertTrue(_looks_corrupted(os.environ["NEO4J_URI"]))
        self.assertIsNone(_env("NEO4J_URI"))

    def test_neo4j_uri_without_scheme_gets_bolt_prefix(self) -> None:
        os.environ["NEO4J_URI"] = "cml-neo4j-xxxxx.namespace:7687"
        self.assertEqual(_env("NEO4J_URI"), "bolt://cml-neo4j-xxxxx.namespace:7687")

    def test_neo4j_uri_keeps_cloudera_site_plain_bolt(self) -> None:
        os.environ["NEO4J_URI"] = "bolt://neo4j-launcher-10j1ta.ml.example.cloudera.site:7687"
        self.assertEqual(
            _env("NEO4J_URI"),
            "bolt://neo4j-launcher-10j1ta.ml.example.cloudera.site:7687",
        )

    def test_neo4j_uri_accepts_bolt_plus_s(self) -> None:
        os.environ["NEO4J_URI"] = "bolt+s://neo4j.example.com:7687"
        self.assertEqual(_env("NEO4J_URI"), "bolt+s://neo4j.example.com:7687")

    def test_metadata_defaults_used_outside_cml(self) -> None:
        self.assertEqual(_env("GIT_REF", METADATA_DEFAULTS["GIT_REF"]), "release/5.7.1.SP1.RELEASE")

    def test_reads_from_project_env_in_cml(self) -> None:
        os.environ["CDSW_PROJECT_ID"] = "proj-123"
        os.environ["NEO4J_URI"] = METADATA_DEFAULTS["NEO4J_URI"]
        with patch("code_analysis.config.read_cml_project_env", return_value="bolt://user-neo4j:7687"):
            self.assertEqual(_env("NEO4J_URI"), "bolt://user-neo4j:7687")

    def test_no_metadata_default_for_neo4j_in_cml(self) -> None:
        os.environ["CDSW_PROJECT_ID"] = "proj-123"
        self.assertIsNone(_env("NEO4J_URI"))

    def test_config_from_env_uses_os_environ(self) -> None:
        os.environ["CDSW_PROJECT_ID"] = "proj-123"
        os.environ["NEO4J_URI"] = "bolt://neo4j.example:7687"
        os.environ["GIT_REPO_URL"] = "https://github.com/example/app.git"
        os.environ["GIT_REF"] = "develop"
        os.environ["NEO4J_USERNAME"] = "admin"
        os.environ["NEO4J_PASSWORD"] = "secret-pass"
        config = Config.from_env()
        self.assertEqual(config.neo4j_uri, "bolt://neo4j.example:7687")
        self.assertEqual(config.git_repo_url, "https://github.com/example/app.git")
        self.assertEqual(config.git_ref, "develop")
        self.assertEqual(config.neo4j_username, "admin")

    def test_config_requires_neo4j_uri_in_cml(self) -> None:
        os.environ["CDSW_PROJECT_ID"] = "proj-123"
        os.environ["GIT_REPO_URL"] = "https://github.com/example/app.git"
        with self.assertRaises(ValueError):
            Config.from_env()

    def test_diagnose_environment_runs(self) -> None:
        os.environ["NEO4J_URI"] = "bolt://neo4j.example:7687"
        diagnose_environment()


if __name__ == "__main__":
    unittest.main()

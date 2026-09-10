"""Tests for project environment seeding."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from code_analysis.config import MANAGED_ENV_VARS, PROJECT_ENV_SEEDS, validate_neo4j_uri_for_ingest
from code_analysis.seed_project_env import seed_project_environment


class SeedProjectEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_project_id = os.environ.get("CDSW_PROJECT_ID")
        os.environ.pop("CDSW_PROJECT_ID", None)
        self._saved_env: dict[str, str] = {}
        for name in MANAGED_ENV_VARS:
            if name in os.environ:
                self._saved_env[name] = os.environ.pop(name)

    def tearDown(self) -> None:
        os.environ.pop("CDSW_PROJECT_ID", None)
        if self._saved_project_id is not None:
            os.environ["CDSW_PROJECT_ID"] = self._saved_project_id
        for name in MANAGED_ENV_VARS:
            os.environ.pop(name, None)
        for name, value in self._saved_env.items():
            os.environ[name] = value

    @patch("code_analysis.seed_project_env._cml_bootstrap_client")
    @patch("code_analysis.seed_project_env.read_cml_project_env")
    def test_seed_creates_missing_keys(self, mock_read: MagicMock, mock_client_factory: MagicMock) -> None:
        os.environ["CDSW_PROJECT_ID"] = "proj-123"
        mock_read.return_value = None
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client

        updates = seed_project_environment()
        self.assertEqual(set(updates.keys()), set(PROJECT_ENV_SEEDS.keys()))
        mock_client.create_environment_variable.assert_called_once_with(PROJECT_ENV_SEEDS)

    @patch("code_analysis.seed_project_env._cml_bootstrap_client")
    @patch("code_analysis.seed_project_env.read_cml_project_env")
    def test_seed_skips_existing_keys(self, mock_read: MagicMock, mock_client_factory: MagicMock) -> None:
        os.environ["CDSW_PROJECT_ID"] = "proj-123"
        mock_read.side_effect = lambda name: "existing" if name == "NEO4J_URI" else None
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client

        updates = seed_project_environment()
        self.assertNotIn("NEO4J_URI", updates)
        self.assertIn("GIT_REPO_URL", updates)

    @patch("code_analysis.seed_project_env._cml_bootstrap_client")
    @patch("code_analysis.seed_project_env.read_cml_project_env")
    def test_seed_respects_os_environ_when_cmlapi_unavailable(
        self, mock_read: MagicMock, mock_client_factory: MagicMock
    ) -> None:
        """AMP writes Config Project values into os.environ. Never overwrite them."""
        os.environ["CDSW_PROJECT_ID"] = "proj-123"
        # Simulate cmlapi being unimportable at job runtime.
        mock_read.return_value = None
        os.environ["NEO4J_URI"] = "bolt://cml-neo4j-abc123.mlx-user-42:7687"
        os.environ["NEO4J_PASSWORD"] = "user-secret"
        mock_client = MagicMock()
        mock_client_factory.return_value = mock_client

        updates = seed_project_environment()

        self.assertNotIn("NEO4J_URI", updates)
        self.assertNotIn("NEO4J_PASSWORD", updates)
        # os.environ values must remain untouched.
        self.assertEqual(
            os.environ["NEO4J_URI"], "bolt://cml-neo4j-abc123.mlx-user-42:7687"
        )
        self.assertEqual(os.environ["NEO4J_PASSWORD"], "user-secret")

    def test_validate_rejects_browser_url(self) -> None:
        with self.assertRaises(ValueError):
            validate_neo4j_uri_for_ingest(
                "bolt://neo4j-launcher-10j1ta.ml.example.cloudera.site:7687"
            )

    def test_validate_rejects_placeholder(self) -> None:
        with self.assertRaises(ValueError):
            validate_neo4j_uri_for_ingest(PROJECT_ENV_SEEDS["NEO4J_URI"])

    def test_validate_accepts_elb_bolt_url(self) -> None:
        """Cross-AMP callers reach neo4j-launcher via the ELB Bolt endpoint."""
        validate_neo4j_uri_for_ingest(
            "bolt://a7917e0593f6b42f9adcb9b7e8acf39d-1746816803.us-east-2.elb.amazonaws.com:7687"
        )


if __name__ == "__main__":
    unittest.main()

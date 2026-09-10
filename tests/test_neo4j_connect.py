"""Tests for Neo4j connection URI resolution."""

from __future__ import annotations

import os
import unittest

from code_analysis.neo4j_connect import format_neo4j_connection_help, iter_neo4j_connection_uris


class Neo4jConnectTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_internal = os.environ.get("NEO4J_INTERNAL_URI")
        os.environ.pop("NEO4J_INTERNAL_URI", None)

    def tearDown(self) -> None:
        os.environ.pop("NEO4J_INTERNAL_URI", None)
        if self._saved_internal is not None:
            os.environ["NEO4J_INTERNAL_URI"] = self._saved_internal

    def test_cml_internal_uri_is_tried_first_with_service_fallback(self) -> None:
        uri = "bolt://cml-neo4j-10xfi5ukxwfadjsr.mlx-user-98:7687"
        self.assertEqual(
            iter_neo4j_connection_uris(uri),
            [uri, "bolt://neo4j-launcher:7687"],
        )

    def test_cml_internal_uri_fallback_preserves_port(self) -> None:
        uri = "bolt://cml-neo4j-abc.mlx-user-0:17687"
        self.assertEqual(
            iter_neo4j_connection_uris(uri),
            [uri, "bolt://neo4j-launcher:17687"],
        )

    def test_cml_internal_uri_after_internal_override(self) -> None:
        os.environ["NEO4J_INTERNAL_URI"] = "bolt://cml-neo4j-override.mlx-user-1:7687"
        uri = "bolt://cml-neo4j-10xfi5ukxwfadjsr.mlx-user-98:7687"
        self.assertEqual(
            iter_neo4j_connection_uris(uri),
            [
                "bolt://cml-neo4j-override.mlx-user-1:7687",
                uri,
                "bolt://neo4j-launcher:7687",
            ],
        )

    def test_cloudera_site_only_uses_internal_override(self) -> None:
        os.environ["NEO4J_INTERNAL_URI"] = "bolt://cml-neo4j-abc.mlx-user-98:7687"
        uri = "bolt://neo4j-launcher-10j1ta.ml.example.cloudera.site:7687"
        self.assertEqual(
            iter_neo4j_connection_uris(uri),
            ["bolt://cml-neo4j-abc.mlx-user-98:7687"],
        )

    def test_cloudera_site_without_override_returns_empty(self) -> None:
        uri = "bolt://neo4j-launcher-10j1ta.ml.example.cloudera.site:7687"
        self.assertEqual(iter_neo4j_connection_uris(uri), [])

    def test_elb_uri_is_used_directly(self) -> None:
        """External Bolt URI is the only option for cross-AMP callers."""
        uri = "bolt://a7917e0593f6b42f9adcb9b7e8acf39d-1746816803.us-east-2.elb.amazonaws.com:7687"
        self.assertEqual(iter_neo4j_connection_uris(uri), [uri])

    def test_elb_uri_with_internal_override_tries_override_first(self) -> None:
        os.environ["NEO4J_INTERNAL_URI"] = "bolt://cml-neo4j-abc.mlx-user-1:7687"
        uri = "bolt://a7917e0593f6b42f9adcb9b7e8acf39d-1746816803.us-east-2.elb.amazonaws.com:7687"
        self.assertEqual(
            iter_neo4j_connection_uris(uri),
            ["bolt://cml-neo4j-abc.mlx-user-1:7687", uri],
        )

    def test_connection_help_mentions_application_log(self) -> None:
        message = format_neo4j_connection_help("bolt://example.cloudera.site:7687", [])
        self.assertIn("Application Log", message)
        self.assertIn("cml-neo4j", message)

    def test_connection_help_mentions_external_bolt_option(self) -> None:
        message = format_neo4j_connection_help("bolt://example.cloudera.site:7687", [])
        self.assertIn("External Bolt", message)
        self.assertIn("elb.amazonaws.com", message)


if __name__ == "__main__":
    unittest.main()

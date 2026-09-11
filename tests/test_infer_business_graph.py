"""Tests for post-ingest Business inference (pure logic only)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from code_analysis.infer_business_graph import (
    DEFAULT_DTO_SUFFIXES,
    DEFAULT_LABELS,
    JAVA_RESERVED_METHOD_NAMES,
    load_label_overrides,
    resolve_labels,
)


class ResolveLabelsTests(unittest.TestCase):
    def test_resolve_labels_uses_defaults_when_no_overrides(self) -> None:
        result = resolve_labels(None)
        self.assertEqual(result["reserve"], "予約業務")
        self.assertEqual(result["customer"], "顧客管理業務")

    def test_resolve_labels_empty_overrides_leaves_defaults(self) -> None:
        result = resolve_labels({})
        for key, value in DEFAULT_LABELS.items():
            self.assertEqual(result[key], value)

    def test_resolve_labels_overrides_win_over_defaults(self) -> None:
        result = resolve_labels({"reserve": "予約業務(カスタム)", "new_pkg": "新規業務"})
        self.assertEqual(result["reserve"], "予約業務(カスタム)")
        self.assertEqual(result["new_pkg"], "新規業務")
        # Non-overridden defaults survive.
        self.assertEqual(result["customer"], "顧客管理業務")


class LoadLabelOverridesTests(unittest.TestCase):
    def test_returns_empty_when_path_is_none(self) -> None:
        self.assertEqual(load_label_overrides(None), {})

    def test_returns_empty_when_path_is_empty_string(self) -> None:
        self.assertEqual(load_label_overrides(""), {})

    def test_returns_empty_on_missing_file(self) -> None:
        self.assertEqual(load_label_overrides("/nonexistent/labels.json"), {})

    def test_returns_empty_on_invalid_json(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fp:
            fp.write("{ not valid json")
            path = fp.name
        try:
            self.assertEqual(load_label_overrides(path), {})
        finally:
            Path(path).unlink()

    def test_returns_empty_when_json_is_not_object(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fp:
            json.dump(["reserve", "customer"], fp)
            path = fp.name
        try:
            self.assertEqual(load_label_overrides(path), {})
        finally:
            Path(path).unlink()

    def test_reads_valid_json_mapping(self) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fp:
            json.dump({"reserve": "予約業務(A)", "billing": "請求業務"}, fp)
            path = fp.name
        try:
            result = load_label_overrides(path)
            self.assertEqual(result, {"reserve": "予約業務(A)", "billing": "請求業務"})
        finally:
            Path(path).unlink()

    def test_coerces_non_string_values_to_string(self) -> None:
        # Guard against operators putting bare numbers/booleans in the JSON.
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fp:
            json.dump({"reserve": 42}, fp)
            path = fp.name
        try:
            result = load_label_overrides(path)
            self.assertEqual(result, {"reserve": "42"})
        finally:
            Path(path).unlink()


class ConstantsSanityTests(unittest.TestCase):
    def test_java_reserved_words_include_common_keywords(self) -> None:
        for keyword in ("if", "else", "for", "while", "return", "try", "catch"):
            self.assertIn(keyword, JAVA_RESERVED_METHOD_NAMES)

    def test_dto_suffixes_include_input_output_form(self) -> None:
        for suffix in ("Input", "Output", "Form", "Dto", "DTO"):
            self.assertIn(suffix, DEFAULT_DTO_SUFFIXES)


if __name__ == "__main__":
    unittest.main()

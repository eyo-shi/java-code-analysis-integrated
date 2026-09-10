"""Shared helpers for property/column name mapping."""

from __future__ import annotations

import re


def camel_to_snake(name: str) -> str:
    chars: list[str] = []
    for index, char in enumerate(name):
        if char.isupper() and index > 0:
            chars.append("_")
        chars.append(char.lower())
    return "".join(chars)


def camel_to_snake_upper(name: str) -> str:
    return camel_to_snake(name).upper()


def column_id(table_name: str, column_name: str) -> str:
    return f"{table_name.upper()}.{column_name.upper()}"

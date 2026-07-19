# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: Apache-2.0

import pytest
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from sqlgraph.utils.errors import (
    SqlGraphError,
    SqlParseError,
    SchemaNotFoundError,
    AmbiguousColumnError,
    CircularDependencyError,
    InputError,
)


def test_sql_parse_error_is_sqlgraph_error():
    err = SqlParseError("test message", sql="SELECT 1", file_path="test.sql")
    assert isinstance(err, SqlGraphError)
    assert str(err) == "test message"
    assert err.sql == "SELECT 1"
    assert err.file_path == "test.sql"


def test_ambiguous_column_error_has_candidates():
    err = AmbiguousColumnError("user_id", candidates=["ods_a.user_id", "ods_b.user_id"])
    assert err.column_name == "user_id"
    assert len(err.candidates) == 2


def test_circular_dependency_error_has_chain():
    err = CircularDependencyError(["table_a", "table_b", "table_a"])
    assert "table_a" in err.chain

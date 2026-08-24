# Copyright (c) 2026 ByteDance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""Public action planning, execution, and rollback interface."""

from sqlgraph.actions.adapters import (
    ActionAdapter,
    AdapterExecutionError,
    DuckDBTaskAdapter,
    SqlFilePatchAdapter,
)
from sqlgraph.actions.engine import ActionEngine
from sqlgraph.actions.model import (
    ACTION_SCHEMA_VERSION,
    ActionPlan,
    ActionRequest,
    DryRunResult,
    ExecutionResult,
    RollbackResult,
)

__all__ = [
    "ACTION_SCHEMA_VERSION",
    "ActionAdapter",
    "ActionEngine",
    "ActionPlan",
    "ActionRequest",
    "AdapterExecutionError",
    "DryRunResult",
    "DuckDBTaskAdapter",
    "ExecutionResult",
    "RollbackResult",
    "SqlFilePatchAdapter",
]

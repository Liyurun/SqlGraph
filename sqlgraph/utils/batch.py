# sqlgraph/utils/batch.py
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, TypeVar, Generic
from sqlgraph.utils.logging import log_progress, log_info, log_error

T = TypeVar("T")


@dataclass
class FailedCase:
    """失败案例记录"""
    file_path: str
    error_message: str
    sql_content: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BatchResult(Generic[T]):
    """批处理结果"""
    successful: list = field(default_factory=list)
    failed_cases: list = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return len(self.successful)

    @property
    def failure_count(self) -> int:
        return len(self.failed_cases)

    def add_success(self, item: T) -> None:
        self.successful.append(item)

    def add_failure(self, case: FailedCase) -> None:
        self.failed_cases.append(case)

    def write_failed_cases(self, path: str) -> None:
        """将失败案例写入 JSON 文件"""
        os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump([c.to_dict() for c in self.failed_cases], f, ensure_ascii=False, indent=2)


def process_batch(
    items: list,
    processor: Callable,
    desc: str = "Processing",
) -> BatchResult:
    """批处理执行，单条失败不影响整体"""
    result = BatchResult()
    total = len(items)
    for idx, item in enumerate(items, 1):
        try:
            processed = processor(item)
            result.add_success(processed)
        except Exception as e:
            file_path = str(item) if not isinstance(item, str) else item
            sql_content = item if isinstance(item, str) else None
            result.add_failure(FailedCase(
                file_path=file_path,
                error_message=str(e),
                sql_content=sql_content,
            ))
            log_error(f"Failed to process {file_path}: {e}")
        log_progress(idx, total, prefix=desc)
    log_info(f"Done. Success: {result.success_count}, Failed: {result.failure_count}")
    return result

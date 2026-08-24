"""从权威 catalog 确定性生成 62 个 SQL 文件与 manifest。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from examples.video_commercial_warehouse.catalog import (
    ALL_TABLES,
    BASE_TABLES,
    TASKS,
    layer_counts,
    validate_catalog,
)


ROOT = Path(__file__).resolve().parent


def generate_sql(output_dir: Path) -> list[Path]:
    """物化 SQL 与 manifest；同一 catalog 重复生成时字节级一致。"""
    validate_catalog()
    output_dir = Path(output_dir)
    sql_dir = output_dir / "sql"
    sql_dir.mkdir(parents=True, exist_ok=True)

    expected_names = set()
    paths: list[Path] = []
    for task in TASKS:
        filename = f"{task.order:03d}_{task.target}.sql"
        expected_names.add(filename)
        path = sql_dir / filename
        path.write_text(task.sql, encoding="utf-8")
        paths.append(path)

    # 清理 catalog 已删除/重命名后遗留的生成 SQL，避免执行幽灵任务。
    for stale in sql_dir.glob("*.sql"):
        if stale.name not in expected_names:
            stale.unlink()

    derived = {task.target: task for task in TASKS}
    tables = []
    for name in ALL_TABLES:
        if name in BASE_TABLES:
            tables.append(BASE_TABLES[name].to_dict())
        else:
            task = derived[name]
            tables.append({
                "name": task.target,
                "layer": task.layer,
                "domain": task.domain,
                "columns": [],
            })

    manifest = {
        "name": "video_commercial_warehouse",
        "description": "视频平台流量与广告商业化完整数仓",
        "table_count": len(ALL_TABLES),
        "base_table_count": len(BASE_TABLES),
        "task_count": len(TASKS),
        "layer_counts": dict(sorted(layer_counts().items())),
        "tables": tables,
        "tasks": [task.to_dict() for task in TASKS],
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成视频平台商业化数仓 SQL")
    parser.add_argument("--output", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    paths = generate_sql(args.output)
    print(f"已生成 {len(paths)} 个 SQL 任务: {args.output.resolve() / 'sql'}")
    print(f"manifest: {args.output.resolve() / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

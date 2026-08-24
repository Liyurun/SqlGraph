# Video Commercial Warehouse

一套可由 DuckDB 真实执行、可由 SqlGraph 构图和治理的视频平台商业化完整数仓。

## 规模

| 层级 | 表数 | 任务数 |
|---|---:|---:|
| ODS | 18 | 0 |
| STG | 18 | 18 |
| DIM | 14 | 0 |
| DWD | 18 | 18 |
| DWS | 16 | 16 |
| ADS | 10 | 10 |
| **合计** | **94** | **62** |

覆盖内容、用户、推荐流量、广告资源、竞价投放、转化归因、预算计费、商业收入、
实验策略和质量风控十个主题。

## 运行

从仓库根目录执行：

```bash
# 重新从 catalog 生成 62 个 SQL 文件和 manifest
.devvenv/bin/python -m examples.video_commercial_warehouse.generate_sql

# CI / 快速验证：5,000 推荐请求
.devvenv/bin/python -m examples.video_commercial_warehouse.governance \
  --profile smoke \
  --output demo_output/video_commercial_warehouse/smoke \
  --no-open

# 完整演示：200,000 推荐请求
.devvenv/bin/python -m examples.video_commercial_warehouse.generate_sql
.devvenv/bin/python -m examples.video_commercial_warehouse.governance \
  --profile demo \
  --output demo_output/video_commercial_warehouse/demo
```

`generate_sql` 会把数仓恢复到包含 CTR 口径冲突的基线；`governance` 会：

1. 用 DuckDB 生成 32 张基础表；
2. 真实执行 62 个 SQL 任务；
3. 用 SqlGraph 构建全仓血缘；
4. 识别 `dws_creative_performance_daily.ctr` 百分数/比率冲突；
5. 备份并修改真实 SQL；
6. 只重跑目标及其受影响下游；
7. 用 DuckDB 查询结果执行三层验证；
8. 生成结构化审计和离线交互报告。

## 恢复

```bash
.devvenv/bin/python -m examples.video_commercial_warehouse.governance \
  --output demo_output/video_commercial_warehouse/demo \
  --restore
```

恢复操作会同时恢复 SQL 和 DuckDB 快照，并将报告状态更新为 `restored`，避免旧报告
继续显示为当前成功状态。

## 产物

```text
demo_output/video_commercial_warehouse/demo/
├── before/
│   └── sql/                    # 62 个治理前 SQL 快照
├── before.duckdb               # 治理前完整数仓
├── after.duckdb                # 治理后增量重跑结果
├── operation.json              # 结构化治理审计
└── warehouse_report.html       # 离线交互报告
```

## 设计纪律

- Catalog 是表、任务、依赖的唯一真相源。
- SQL 使用 DuckDB 可直接执行且 SQLGlot 可解析的公共语法。
- 所有种子数据由 `range()` 与确定性公式生成，不使用随机 ID。
- 比率保持 `[0,1]`，展示层才转换成百分比。
- 运行态验证必须来自 DuckDB 查询；没有查询结果不得判定闭环成功。

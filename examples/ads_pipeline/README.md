# AdTech ETL Pipeline — SqlGraph demo dataset

This folder is a self-contained, realistic **advertising data-warehouse pipeline**
used to demonstrate SqlGraph. It flows from raw ODS logs up through the standard
warehouse layers (ODS → STG → DWD → DWS → ADS), and exercises the full range of
SQL constructs SqlGraph understands.

## Run it

```bash
# from the repo root
python examples/ads_pipeline/run_demo.py
# or
sqlgraph demo
```

This parses all `.sql` files with the `spark` dialect, using
[`schema.csv`](schema.csv) for column disambiguation, and writes an interactive
visualization to `demo_output/lineage.html`.

## The SQL files

| File | Target table | Layer | Highlights |
|---|---|---|---|
| [`01_stg_impressions.sql`](01_stg_impressions.sql) | `stg_impressions` | STG | `CAST`, `COALESCE`, multi-branch `CASE WHEN` (OS normalization) |
| [`02_stg_clicks.sql`](02_stg_clicks.sql) | `stg_clicks` | STG | click-log cleaning & typing |
| [`03_dwd_ad_event.sql`](03_dwd_ad_event.sql) | `dwd_ad_event` | DWD | CTE + `ROW_NUMBER()` dedup, `LEFT JOIN` impression↔click |
| [`04_dws_ad_daily.sql`](04_dws_ad_daily.sql) | `dws_ad_daily` | DWS | daily aggregates (`SUM` / `COUNT`), ratio metrics |
| [`05_dws_creative_daily.sql`](05_dws_creative_daily.sql) | `dws_creative_daily` | DWS | creative-level rollup with dimension join |
| [`06_ads_creative_report.sql`](06_ads_creative_report.sql) | `ads_creative_report` | ADS | `CASE WHEN` grading + multiple window functions (`RANK`, rolling `SUM`) |
| [`07_stg_conversions.sql`](07_stg_conversions.sql) | `stg_conversions` | STG | conversion-event cleaning, `CASE` type normalization |
| [`08_stg_user_profile.sql`](08_stg_user_profile.sql) | `stg_user_profile` | STG | user profile with age-bucketing `CASE` |
| [`09_dwd_attribution_wide.sql`](09_dwd_attribution_wide.sql) | `dwd_attribution_wide` | DWD | multi-CTE (`conv_agg`, `event_enriched`) + multi-`JOIN` wide table |
| [`10_dws_funnel_events.sql`](10_dws_funnel_events.sql) | `dws_funnel_events` | DWS | `UNION ALL` of impressions / clicks / conversions |
| [`11_ads_advertiser_daily.sql`](11_ads_advertiser_daily.sql) | `ads_advertiser_daily` | ADS | multi-window (`RANK` / `SUM OVER` / `AVG OVER`) + dimension joins |

[`schema.csv`](schema.csv) declares the columns of every source table
(`ods_*`, `dim_*`) so the parser can bind columns to the correct physical table.

## Expected result

Parsing this dataset with SqlGraph produces:

| Metric | Count |
|---|---:|
| SQL files | 11 |
| Tables | 26 |
| Columns | 204 |
| Transformation nodes | 56 |
| Edges | 552 |
| **Total nodes** | **297** |

These numbers are asserted by the end-to-end test in
[`tests/test_integration/test_e2e.py`](../../tests/test_integration/test_e2e.py),
so any parser change that shifts them will be caught by CI.

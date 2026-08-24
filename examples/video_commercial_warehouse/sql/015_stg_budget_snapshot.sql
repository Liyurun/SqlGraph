-- STG / billing: 标准化 ods_budget_snapshot 并去除完全重复记录
CREATE OR REPLACE TABLE stg_budget_snapshot AS
SELECT DISTINCT * FROM ods_budget_snapshot;

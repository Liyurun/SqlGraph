-- DWD / traffic: 搜索行为事实
CREATE OR REPLACE TABLE dwd_search_fact AS
SELECT *, LENGTH(query) AS query_length,
                 CASE WHEN result_count > 0 THEN 1 ELSE 0 END AS has_result
          FROM stg_search_event;

-- STG / content: 标准化 ods_user_interaction 并去除完全重复记录
CREATE OR REPLACE TABLE stg_user_interaction AS
SELECT DISTINCT * FROM ods_user_interaction;

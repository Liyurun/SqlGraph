-- STG / traffic: 标准化 ods_video_exposure 并去除完全重复记录
CREATE OR REPLACE TABLE stg_video_exposure AS
SELECT DISTINCT * FROM ods_video_exposure;

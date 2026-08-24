-- DS-03 多语句文件：两条以上互不相关语句。
-- 用于验证「无笛卡尔伪边」（REQ-LIN-01）：只应产出 s1->d1、s2->d2，
-- 不得因同处一个文件而产生跨语句伪边。
INSERT INTO dwd_click_di SELECT log_id, ad_id, ts FROM ods_click_log_di;
INSERT INTO dwd_impression_di SELECT log_id, ad_id, ts FROM ods_impression_log_di;

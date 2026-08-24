INSERT INTO cold_table_archive
SELECT event_id, event_date
FROM cold_event_log;

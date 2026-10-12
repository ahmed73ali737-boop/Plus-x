\set ON_ERROR_STOP on
-- PostgreSQL catalog-only health report; NO schema or business row changes.
-- Run only with DBA-approved monitoring credentials; estimates are not exact.
BEGIN READ ONLY;
SET LOCAL lock_timeout = '2s';
SET LOCAL statement_timeout = '15s';

SELECT current_database() AS database_name, current_setting('server_version') AS version;
SELECT st.schemaname, st.relname, st.n_live_tup AS estimated_rows, st.n_dead_tup,
       st.seq_scan, st.idx_scan, st.last_autoanalyze,
       pg_size_pretty(pg_total_relation_size(st.relid)) AS total_size
FROM pg_stat_user_tables st
ORDER BY pg_total_relation_size(st.relid) DESC LIMIT 40;
SELECT n.nspname, t.relname AS table_name, i.relname AS index_name,
       ix.indisvalid, ix.indisready
FROM pg_index ix
JOIN pg_class i ON i.oid=ix.indexrelid
JOIN pg_class t ON t.oid=ix.indrelid
JOIN pg_namespace n ON n.oid=t.relnamespace
WHERE NOT ix.indisvalid OR NOT ix.indisready
ORDER BY n.nspname,t.relname;
SELECT n.nspname, t.relname AS table_name, t.relispartition,
       t.relrowsecurity,t.relforcerowsecurity
FROM pg_class t
JOIN pg_namespace n ON n.oid=t.relnamespace
JOIN pg_attribute a ON a.attrelid=t.oid
 AND a.attname='tenant_id' AND a.attnum>0 AND NOT a.attisdropped
WHERE t.relkind IN ('r','p') AND NOT t.relispartition
  AND n.nspname NOT IN ('pg_catalog','information_schema')
  AND (NOT t.relrowsecurity OR NOT t.relforcerowsecurity)
ORDER BY n.nspname,t.relname;
SELECT n.nspname AS schema_name, parent.relname AS parent_table,
       count(*) AS partitions
FROM pg_inherits inh
JOIN pg_class parent ON parent.oid=inh.inhparent
JOIN pg_namespace n ON n.oid=parent.relnamespace
WHERE n.nspname NOT IN ('pg_catalog','information_schema')
GROUP BY n.nspname,parent.relname ORDER BY partitions DESC LIMIT 50;

COMMIT;

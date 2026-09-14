-- IR-06: pg_stat_statements is test-only, and it is created exactly once, in the cluster's
-- `postgres` maintenance database — never in the application database, and never in a
-- `verticals_t_%` clone the test harness creates later. AC-004 depends on this: the extension
-- set the application ever sees must be exactly {plpgsql, pg_trgm}.
--
-- docker-entrypoint-initdb.d scripts connect to $POSTGRES_DB by default, so this script
-- switches explicitly with \connect before creating the extension, regardless of what
-- POSTGRES_DB is set to in docker-compose.test.yml.
\connect postgres
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

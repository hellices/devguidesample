-- Run as the HorizonDB administrator against the default "postgres" database:
--   psql "host=$HZ_HOST dbname=postgres user=$HZ_ADMIN sslmode=require" \
--     -v app_password="$APP_DB_PASSWORD" -f db/00-database.sql
\set ON_ERROR_STOP on

SELECT 'CREATE DATABASE movielog'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'movielog') \gexec

SELECT format('CREATE ROLE movielog LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'movielog') \gexec
ALTER ROLE movielog PASSWORD :'app_password';

GRANT CONNECT, TEMPORARY ON DATABASE movielog TO movielog;

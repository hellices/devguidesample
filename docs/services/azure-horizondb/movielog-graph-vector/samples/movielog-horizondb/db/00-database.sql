-- Run as the HorizonDB administrator against the default "postgres" database (psql 15 or later):
--   APP_DB_PASSWORD=... psql "host=$HZ_HOST dbname=postgres user=$HZ_ADMIN sslmode=require" -f db/00-database.sql
-- The app password is read from the environment, not passed on the psql command line where ps could show it.
\set ON_ERROR_STOP on
\getenv app_password APP_DB_PASSWORD
SELECT :{?app_password} AS has_app_password \gset
\if :has_app_password
\else
	DO $$ BEGIN RAISE EXCEPTION 'APP_DB_PASSWORD is not set'; END $$;
\endif

SELECT 'CREATE DATABASE movielog'
WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = 'movielog') \gexec

SELECT format('CREATE ROLE movielog LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'movielog') \gexec
ALTER ROLE movielog PASSWORD :'app_password';

GRANT CONNECT, TEMPORARY ON DATABASE movielog TO movielog;

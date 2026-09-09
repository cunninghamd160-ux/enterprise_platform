#!/bin/sh
# Runs once, when the postgres volume is first created. One role and one database per app for the
# owned store (ADR-0007): an app's INSIGHTS_DB_URL carries only its own credentials, so it cannot
# reach another app's data (ADR-0004). Values are fixtures.
set -eu

create_owned() {
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<-EOSQL
    create role "$1" login password '$2';
    create database "$1" owner "$1";
EOSQL
}

create_owned people_analytics_comp people-analytics-comp
# create_owned <app_package> <password>   # one line per new app; its INSIGHTS_DB_URL uses both

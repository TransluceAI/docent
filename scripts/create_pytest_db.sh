#!/usr/bin/env bash
set -e

DOCENT_PG_USER="${DOCENT_PG_USER:-docent_user}"
DOCENT_PG_PASSWORD="${DOCENT_PG_PASSWORD:-docent_password}"

docker exec -e PGPASSWORD="${DOCENT_PG_PASSWORD}" -i docent_postgres \
    psql -U "${DOCENT_PG_USER}" -d postgres \
    -c "CREATE DATABASE _pytest_docent_test;" \
    -c "\c _pytest_docent_test" \
    -c "CREATE EXTENSION IF NOT EXISTS vector;"

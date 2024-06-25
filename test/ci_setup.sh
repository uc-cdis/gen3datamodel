#!/usr/bin/env bash
set -e

echo "Checking version of database"
psql -U postgres -c 'SELECT version()'

poetry run python bin/destroy_and_setup_psqlgraph.py --user postgres --password postgres

#!/usr/bin/env bash

# since this whole thing is run as a bash {{this script}}, only the last pytest
# command controls the exit code. We actually want to exit early if something fails
set -e

# datadict and datadictwithobjid tests must run separately to allow
# loading different datamodels
export POSTGRES_PORT=5432
poetry run python bin/destroy_and_setup_psqlgraph.py
poetry run pytest -vv --cov=gdcdatamodel --cov-report xml tests

#!/usr/bin/env bash

# since this whole thing is run as a bash {{this script}}, only the last pytest
# command controls the exit code. We actually want to exit early if something fails
set -e

# datadict and datadictwithobjid tests must run separately to allow
# loading different datamodels
ls -al /etc/postgresql/13/main/
# travis with postgres 13 defaults port to 5433 and test looks for port 5432
sudo sed -i 's/port = 5433/port = 5432/' /etc/postgresql/13/main/postgresql.conf
sudo service postgresql restart 13
poetry run python bin/destroy_and_setup_psqlgraph.py
poetry run pytest -vv --cov=gdcdatamodel --cov-report xml tests

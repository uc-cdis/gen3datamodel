#!/usr/bin/env bash

poetry run pytest -vv --cov=gen3datamodel --cov=migrations/versions --cov-report xml test

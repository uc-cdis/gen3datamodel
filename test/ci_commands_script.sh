#!/usr/bin/env bash

poetry run pytest -vv --cov=gen3datamodel --cov-report xml test

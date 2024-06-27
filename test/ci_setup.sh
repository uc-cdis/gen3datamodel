#!/usr/bin/env bash
set -e

poetry run python bin/destroy_and_setup_psqlgraph.py

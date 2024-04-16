#!/usr/bin/env bash
poetry run python bin/destroy_and_setup_psqlgraph.py
# sudo service postgresql restart 13
# openssl genrsa -out test_private_key.pem 2048
# openssl rsa -in test_private_key.pem -pubout -out test_public_key.pem

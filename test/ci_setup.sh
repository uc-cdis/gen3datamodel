#!/usr/bin/env bash
poetry run python bin/destroy_and_setuop_psqlgraph.py
# openssl genrsa -out test_private_key.pem 2048
# openssl rsa -in test_private_key.pem -pubout -out test_public_key.pem
cd -

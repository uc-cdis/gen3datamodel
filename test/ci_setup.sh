#!/usr/bin/env bash
ls -al /etc/postgresql/13/main/
sudo sed -i 's/port = 5433/port = 5432/' /etc/postgresql/13/main/postgresql.conf
poetry run python bin/destroy_and_setup_psqlgraph.py
# sudo service postgresql restart 13
# openssl genrsa -out test_private_key.pem 2048
# openssl rsa -in test_private_key.pem -pubout -out test_public_key.pem

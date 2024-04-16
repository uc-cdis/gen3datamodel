#!/usr/bin/env bash
ls -al /etc/postgresql/13/main/
# travis with postgres 13 defaults port to 5433 and test looks for port 5432
sudo sed -i 's/port = 5433/port = 5432/' /etc/postgresql/13/main/postgresql.conf
sudo service postgresql restart 13
poetry run python bin/destroy_and_setup_psqlgraph.py
# sudo service postgresql restart 13
# openssl genrsa -out test_private_key.pem 2048
# openssl rsa -in test_private_key.pem -pubout -out test_public_key.pem

#!/usr/bin/env python
import logging
import argparse
import json
from itertools import islice
from multiprocessing import Pool
from psqlgraph import PsqlGraphDriver
from zug.datamodel import psqlgraph2json
from cdisutils.log import get_logger
from pprint import pprint

log = get_logger("json_generator")
logging.root.setLevel(level=logging.ERROR)
args = None


def get_converter():
    return psqlgraph2json.PsqlGraph2JSON(PsqlGraphDriver(
        host=args.host,
        user=args.user,
        password=args.password,
        database=args.database,
    ))


def print_samples(conv):
    # p = converter.get_nodes('participant').first()
    p = conv.graph.nodes().ids('53245616-e095-4616-89bb-6062669122da').one()
    participant, files = conv.denormalize_participant(p)
    pprint(files)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--database', default='gdc_datamodel', type=str,
                        help='the database to import to')
    parser.add_argument('-u', '--user', default='test', type=str,
                        help='the user to import as')
    parser.add_argument('-p', '--password', default='test', type=str,
                        help='the password for import user')
    parser.add_argument('-i', '--host', default='localhost', type=str,
                        help='the postgres server host')
    parser.add_argument('-n', '--nproc', default=8, type=int,
                        help='the number of processes')
    args = parser.parse_args()
    converter = get_converter()
    with converter.graph.session_scope():
        print_samples(converter)

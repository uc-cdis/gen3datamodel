# -*- coding: utf-8 -*-
"""
Tests for gen3datamodel.gdc_postgres_admin module
"""

import logging
import unittest

from sqlalchemy.exc import ProgrammingError
from psqlgraph import (
    Edge,
    Node,
    PsqlGraphDriver,
)

from gen3datamodel import gdc_postgres_admin as pgadmin
from gen3datamodel import models
from conftest import DB_USER, DB_PASSWORD, DB_TABLE

logging.basicConfig()


class TestGDCPostgresAdmin(unittest.TestCase):

    logger = logging.getLogger("TestGDCPostgresAdmin")
    logger.setLevel(logging.INFO)

    host = "localhost"
    user = DB_USER
    password = DB_PASSWORD
    database = DB_TABLE

    base_args = [
        "-H",
        host,
        "-U",
        user,
        "-P",
        password,
        "-D",
        database,
    ]

    g = PsqlGraphDriver(host, user, "", database)
    root_con_str = "postgres://{user}:{pwd}@{host}/{db}".format(
        user=user, host=host, pwd=password, db=database
    )
    engine = pgadmin.create_engine(root_con_str)

    @classmethod
    def tearDownClass(cls):
        """Recreate the database for tests that follow."""
        cls.create_all_tables()

        # Re-grant permissions to test user
        for scls in Node.__subclasses__() + Edge.__subclasses__():
            statment = "GRANT ALL PRIVILEGES ON TABLE {} TO postgres".format(
                scls.__tablename__
            )
            cls.engine.execute("BEGIN; %s; COMMIT;" % statment)

    @classmethod
    def drop_all_tables(cls):
        for scls in Node.__subclasses__():
            try:
                cls.engine.execute("DROP TABLE {} CASCADE".format(scls.__tablename__))
            except Exception as e:
                cls.logger.warning(e)

    @classmethod
    def create_all_tables(cls):
        parser = pgadmin.get_parser()
        args = parser.parse_args(
            ["graph-create", "--delay", "1", "--retries", "0"] + cls.base_args
        )
        pgadmin.main(args)

    @classmethod
    def drop_a_table(cls):
        cls.engine.execute("DROP TABLE edge_clinicaldescribescase")
        cls.engine.execute("DROP TABLE node_clinical")

    def startTestRun(self):
        self.drop_all_tables()

    def setUp(self):
        self.drop_all_tables()

    def test_args(self):
        parser = pgadmin.get_parser()
        parser.parse_args(["graph-create"] + self.base_args)

    def test_create_single(self):
        """Test simple table creation"""

        pgadmin.main(
            pgadmin.get_parser().parse_args(
                ["graph-create", "--delay", "1", "--retries", "0"] + self.base_args
            )
        )

        self.engine.execute("SELECT * from node_case")

    def test_create_double(self):
        """Test idempotency of table creation"""

        pgadmin.main(
            pgadmin.get_parser().parse_args(
                ["graph-create", "--delay", "1", "--retries", "0"] + self.base_args
            )
        )

        self.engine.execute("SELECT * from node_case")

    def test_priv_grant_read(self):
        """Test ability to grant read but not write privs"""

        self.create_all_tables()
        self.engine.execute("CREATE USER pytest WITH PASSWORD 'pyt3st'")

        try:
            g = PsqlGraphDriver(self.host, "pytest", "pyt3st", self.database)

            #: If this failes, this test (not the code) is wrong!
            with self.assertRaises(ProgrammingError):
                with g.session_scope():
                    g.nodes().count()

            pgadmin.main(
                pgadmin.get_parser().parse_args(
                    [
                        "graph-grant",
                        "--read=pytest",
                    ]
                    + self.base_args
                )
            )

            with g.session_scope():
                g.nodes().count()

            with self.assertRaises(ProgrammingError):
                with g.session_scope() as s:
                    s.merge(models.Case("1"))

        finally:
            self.engine.execute("DROP OWNED BY pytest; DROP USER pytest")

    def test_priv_grant_write(self):
        """Test ability to grant read/write privs"""

        self.create_all_tables()
        self.engine.execute("CREATE USER pytest WITH PASSWORD 'pyt3st'")

        try:
            g = PsqlGraphDriver(self.host, "pytest", "pyt3st", self.database)
            pgadmin.main(
                pgadmin.get_parser().parse_args(
                    [
                        "graph-grant",
                        "--write=pytest",
                    ]
                    + self.base_args
                )
            )

            with g.session_scope() as s:
                g.nodes().count()
                s.merge(models.Case("1"))

        finally:
            self.engine.execute("DROP OWNED BY pytest; DROP USER pytest")

    def test_priv_revoke_read(self):
        """Test ability to revoke read privs"""

        self.create_all_tables()
        self.engine.execute("CREATE USER pytest WITH PASSWORD 'pyt3st'")

        try:
            g = PsqlGraphDriver(self.host, "pytest", "pyt3st", self.database)

            pgadmin.main(
                pgadmin.get_parser().parse_args(
                    [
                        "graph-grant",
                        "--read=pytest",
                    ]
                    + self.base_args
                )
            )

            pgadmin.main(
                pgadmin.get_parser().parse_args(
                    [
                        "graph-revoke",
                        "--read=pytest",
                    ]
                    + self.base_args
                )
            )

            with self.assertRaises(ProgrammingError):
                with g.session_scope() as s:
                    g.nodes().count()
                    s.merge(models.Case("1"))

        finally:
            self.engine.execute("DROP OWNED BY pytest; DROP USER pytest")

    def test_priv_revoke_write(self):
        """Test ability to revoke read/write privs"""

        self.create_all_tables()
        self.engine.execute("CREATE USER pytest WITH PASSWORD 'pyt3st'")

        try:
            g = PsqlGraphDriver(self.host, "pytest", "pyt3st", self.database)

            pgadmin.main(
                pgadmin.get_parser().parse_args(
                    [
                        "graph-grant",
                        "--write=pytest",
                    ]
                    + self.base_args
                )
            )

            pgadmin.main(
                pgadmin.get_parser().parse_args(
                    [
                        "graph-revoke",
                        "--write=pytest",
                    ]
                    + self.base_args
                )
            )

            with g.session_scope() as s:
                g.nodes().count()

            with self.assertRaises(ProgrammingError):
                with g.session_scope() as s:
                    s.merge(models.Case("1"))

        finally:
            self.engine.execute("DROP OWNED BY pytest; DROP USER pytest")

from gen3datamodel import models as md
from psqlgraph import Node, Edge, PsqlGraphDriver

import unittest
from conftest import DB_USER, DB_PASSWORD, DB_TABLE

host = "localhost"
g = PsqlGraphDriver(host, DB_USER, DB_PASSWORD, DB_TABLE)


class TestValidators(unittest.TestCase):
    @staticmethod
    def new_sample():
        sample = md.Sample(
            **{
                "node_id": "case1",
                "is_ffpe": False,
                "sample_volume": 100,
                "project_id": "CGCI-BLGSP",
                "state": "validated",
                "submitter_id": "sample-1",
                "initial_weight": 54.0,
            }
        )
        sample.acl = ["acl1"]
        sample.sysan.update({"key1": "val1"})
        return sample

    @staticmethod
    def new_aliquot():
        return md.Aliquot(
            **{
                "node_id": "aliquot1",
                "project_id": "CGCI-BLGSP",
                "state": "validated",
                "submitter_id": "TCGA-AR-A1AR-01A-31W",
            }
        )

    def setUp(self):
        pass

    def tearDown(self):
        self._clear_tables()

    def _clear_tables(self):
        conn = g.engine.connect()
        conn.execute("commit")
        for table in Node().get_subclass_table_names():
            if table != Node.__tablename__:
                conn.execute("delete from {}".format(table))
        for table in Edge.get_subclass_table_names():
            if table != Edge.__tablename__:
                conn.execute("delete from {}".format(table))
        conn.execute("delete from versioned_nodes")
        conn.execute("delete from _voided_nodes")
        conn.execute("delete from _voided_edges")
        conn.close()

    def test_round_trip(self):
        with g.session_scope() as session:
            sample = self.new_sample()
            aliquot = self.new_aliquot()
            sample.aliquots = [aliquot]
            session.add(sample)

        with g.session_scope() as session:
            sample = g.nodes(md.Sample).one()
            v_node = md.VersionedNode.clone(sample)
            session.add(v_node)

        with g.session_scope():
            v_node = g.nodes(md.VersionedNode).one()

        self.assertEqual(v_node.properties["is_ffpe"], False)
        self.assertEqual(v_node.properties["state"], "validated")
        self.assertEqual(v_node.properties["state"], "validated")
        self.assertEqual(v_node.system_annotations, {"key1": "val1"})
        self.assertEqual(v_node.acl, ["acl1"])
        self.assertEqual(v_node.neighbors, ["aliquot1"])
        self.assertIsNotNone(v_node.versioned)
        self.assertIsNotNone(v_node.key)

    def test_versions_property(self):
        with g.session_scope() as session:
            sample = self.new_sample()
            aliquot = self.new_aliquot()
            sample.aliquots = [aliquot]
            session.add(sample)

        with g.session_scope() as session:
            sample = g.nodes(md.Sample).one()
            v_node = md.VersionedNode.clone(sample)
            session.add(v_node)

        with g.session_scope():
            sample = g.nodes(md.Sample).one()
            sample._versions.one()

        with self.assertRaises(RuntimeError):
            sample._versions.one()

        with g.session_scope() as s:
            sample.get_versions(s).one()

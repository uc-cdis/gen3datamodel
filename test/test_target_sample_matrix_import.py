import unittest
import os
from psqlgraph import PsqlGraphDriver, Node, Edge
from gdcdatamodel.models import (
    Participant,
    Sample,
    Aliquot,
    AliquotDerivedFromSample,
)
from zug.datamodel.target.sample_matrices import TARGETSampleMatrixSyncer
from zug.datamodel.prelude import create_prelude_nodes


TEST_DIR = os.path.dirname(os.path.realpath(__file__))
FIXTURES_DIR = os.path.join(TEST_DIR, "fixtures", "sample_matrices")


class TestTARGETSampleMatrixSync(unittest.TestCase):

    def setUp(self):
        self.driver = PsqlGraphDriver('localhost', 'test', 'test', 'automated_test')
        create_prelude_nodes(self.driver)

    def syncer_for(self, project):
        return TARGETSampleMatrixSyncer(project, graph=self.driver, dcc_auth=None)

    def tearDown(self):
        with self.driver.engine.begin() as conn:
            for table in Node().get_subclass_table_names():
                if table != Node.__tablename__:
                    conn.execute('delete from {}'.format(table))
            for table in Edge().get_subclass_table_names():
                if table != Edge.__tablename__:
                    conn.execute('delete from {}'.format(table))
            conn.execute('delete from _voided_nodes')
            conn.execute('delete from _voided_edges')
        self.driver.engine.dispose()

    def trace_participant(self, aliquot_id):
        return self.driver.nodes(Participant)\
                          .path('samples.aliquots')\
                          .props({"submitter_id": aliquot_id})\
                          .one()

    def test_sync(self):
        syncer = self.syncer_for("AML")
        syncer.version = 1
        data = open(os.path.join(FIXTURES_DIR, "TARGET_AML_SampleMatrix_19910121.xlsx")).read()
        df = syncer.load_sample_matrix(data)
        mapping = syncer.compute_mapping_from_df(df)
        with self.driver.session_scope():
            syncer.put_mapping_in_pg(mapping)
        with self.driver.session_scope():
            self.trace_participant("TARGET-20-PABHET-03A-02R")
            self.trace_participant("TARGET-20-PABGKN-09A-01R")
        syncer.version = 2
        data = open(os.path.join(FIXTURES_DIR, "TARGET_AML_SampleMatrix_19910123.xlsx")).read()
        df = syncer.load_sample_matrix(data)
        mapping = syncer.compute_mapping_from_df(df)
        with self.driver.session_scope():
            syncer.put_mapping_in_pg(mapping)
            syncer.remove_old_versions()
        with self.driver.session_scope():
            self.assertEqual(self.driver.nodes().labels("aliquot").props({"submitter_id": "TARGET-20-PABHET-03A-02R"}).all(), [])
            self.trace_participant("TARGET-20-PABGKN-09A-01R")
            self.trace_participant("TARGET-20-PABHKY-03A-02R")

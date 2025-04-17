import unittest
import uuid
from gen3datamodel.validators import GDCJSONValidator, GDCGraphValidator
from psqlgraph import PsqlGraphDriver
from gen3datamodel.models import *

from conftest import DB_USER, DB_PASSWORD, DB_TABLE

host = "localhost"
g = PsqlGraphDriver(host, DB_USER, DB_PASSWORD, DB_TABLE)


class MockSubmissionEntity(object):
    def __init__(self):
        self.errors = []
        self.node = None
        self.doc = {}

    def record_error(self, message, **kwargs):
        self.errors.append(dict(message=message, **kwargs))


class TestValidators(unittest.TestCase):
    def setUp(self):
        self.graph_validator = GDCGraphValidator()
        self.json_validator = GDCJSONValidator()
        self.entities = [MockSubmissionEntity()]

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
        conn.execute("delete from _voided_nodes")
        conn.execute("delete from _voided_edges")
        conn.close()

    def test_json_validator_with_insufficient_properties(self):
        self.entities[0].doc = {"type": "aliquot", "samples": {"submitter_id": "test"}}
        self.json_validator.record_errors(self.entities)
        self.assertEqual(self.entities[0].errors[0]["keys"], ["submitter_id"])
        self.assertEqual(1, len(self.entities[0].errors))

    def test_json_validator_with_wrong_node_type(self):
        self.entities[0].doc = {"type": "aliquo"}
        self.json_validator.record_errors(self.entities)
        self.assertEqual(self.entities[0].errors[0]["keys"], ["type"])
        self.assertEqual(1, len(self.entities[0].errors))

    def test_json_validator_with_wrong_property_type(self):
        self.entities[0].doc = {
            "type": "aliquot",
            "submitter_id": 1,
            "samples": {"submitter_id": "test"},
        }
        self.json_validator.record_errors(self.entities)
        self.assertEqual(["submitter_id"], self.entities[0].errors[0]["keys"])
        self.assertEqual(1, len(self.entities[0].errors))

    def test_json_validator_with_multiple_errors(self):
        self.entities[0].doc = {
            "type": "aliquot",
            "submitter_id": 1,
            "test": "test",
            "samples": {"submitter_id": "test"},
        }
        self.json_validator.record_errors(self.entities)
        self.assertEqual(2, len(self.entities[0].errors))

    def test_json_validator_with_nested_error_keys(self):
        self.entities[0].doc = {
            "type": "aliquot",
            "submitter_id": "test",
            "samples": {"submitter_id": True},
        }
        self.json_validator.record_errors(self.entities)
        self.assertEqual(["samples"], self.entities[0].errors[0]["keys"])

    def test_json_validator_with_multiple_entities(self):
        self.entities[0].doc = {
            "type": "aliquot",
            "submitter_id": 1,
            "test": "test",
            "samples": {"submitter_id": "test"},
        }
        entity = MockSubmissionEntity()
        entity.doc = {
            "type": "aliquot",
            "submitter_id": "test",
            "samples": {"submitter_id": "test"},
        }
        self.entities.append(entity)

        self.json_validator.record_errors(self.entities)
        self.assertEqual(2, len(self.entities[0].errors))
        self.assertEqual(0, len(entity.errors))

    def create_node(self, doc, session):
        cls = Node.get_subclass(doc["type"])
        node = cls(str(uuid.uuid4()))
        node.props = doc["props"]
        for key, value in doc["edges"].items():
            for target_id in value:
                edge = g.nodes().ids(target_id).first()
                node[key].append(edge)
        session.add(node)
        return node

    def update_schema(self, entity, key, schema):
        self.graph_validator.schemas.schema[entity][key] = schema

    def test_graph_validator_without_required_link(self):
        with g.session_scope() as session:
            node = self.create_node(
                {"type": "aliquot", "props": {"submitter_id": "test"}, "edges": {}},
                session,
            )
            self.entities[0].node = node
            self.update_schema(
                "aliquot",
                "links",
                [
                    {
                        "name": "samples",
                        "backref": "aliquots",
                        "label": "derived_from",
                        "multiplicity": "many_to_one",
                        "target_type": "sample",
                        "required": True,
                    }
                ],
            )
            self.graph_validator.record_errors(g, self.entities)
            self.assertEqual(["samples"], self.entities[0].errors[0]["keys"])

    def test_graph_validator_with_exclusive_link(self):
        with g.session_scope() as session:
            submitted_aligned_reads = self.create_node(
                {
                    "type": "submitted_aligned_reads",
                    "props": {
                        "project_id": "test",
                        "file_state": "registered",
                        "file_name": "test_file",
                    },
                    "edges": {},
                },
                session,
            )

            submitted_unaligned_reads = self.create_node(
                {
                    "type": "submitted_unaligned_reads",
                    "props": {
                        "project_id": "test",
                        "file_state": "uploading",
                        "file_name": "other_file",
                    },
                    "edges": {},
                },
                session,
            )

            node = self.create_node(
                {
                    "type": "read_group_qc",
                    "props": {"project_id": "test"},
                    "edges": {
                        "submitted_aligned_reads_files": [
                            submitted_aligned_reads.node_id
                        ],
                        "submitted_unaligned_reads_files": [
                            submitted_unaligned_reads.node_id
                        ],
                    },
                },
                session,
            )
            self.entities[0].node = node
            self.update_schema(
                "read_group",
                "links",
                [
                    {
                        "exclusive": True,
                        "required": True,
                        "subgroup": [
                            {
                                "name": "submitted_aligned_reads",
                                "backref": "read_groups",
                                "label": "derived_from",
                                "multiplicity": "many_to_one",
                                "target_type": "submitted_aligned_read",
                            },
                            {
                                "name": "submitted_unaligned_reads",
                                "backref": "read_groups",
                                "label": "derived_from",
                                "multiplicity": "many_to_one",
                                "target_type": "submitted_unaligned_read",
                            },
                        ],
                    }
                ],
            )
            self.graph_validator.record_errors(g, self.entities)
            self.assertEqual(
                ["submitted_aligned_reads_files", "submitted_unaligned_reads_files"],
                self.entities[0].errors[0]["keys"],
            )

    def test_graph_validator_with_wrong_multiplicity(self):
        with g.session_scope() as session:
            sample = self.create_node(
                {
                    "type": "sample",
                    "props": {
                        "submitter_id": "test",
                        "freezing_method": "plate",
                        "days_to_collection": 5,
                    },
                    "edges": {},
                },
                session,
            )

            sample_b = self.create_node(
                {
                    "type": "sample",
                    "props": {
                        "submitter_id": "testb",
                        "freezing_method": "plate",
                        "days_to_collection": 6,
                    },
                    "edges": {},
                },
                session,
            )

            node = self.create_node(
                {
                    "type": "aliquot",
                    "props": {"submitter_id": "test"},
                    "edges": {"samples": [sample.node_id, sample_b.node_id]},
                },
                session,
            )
            self.entities[0].node = node
            self.update_schema(
                "aliquot",
                "links",
                [
                    {
                        "exclusive": False,
                        "required": True,
                        "subgroup": [
                            {
                                "name": "samples",
                                "backref": "aliquots",
                                "label": "derived_from",
                                "multiplicity": "many_to_one",
                                "target_type": "sample",
                            },
                        ],
                    }
                ],
            )
            self.graph_validator.record_errors(g, self.entities)
            self.assertEqual(["samples"], self.entities[0].errors[0]["keys"])

    def test_graph_validator_with_correct_node(self):
        with g.session_scope() as session:
            sample = self.create_node(
                {
                    "type": "sample",
                    "props": {
                        "submitter_id": "test",
                        "days_to_collection": 5,
                        "freezing_method": "plate",
                    },
                    "edges": {},
                },
                session,
            )

            node = self.create_node(
                {
                    "type": "aliquot",
                    "props": {"submitter_id": "test"},
                    "edges": {"samples": [sample.node_id]},
                },
                session,
            )
            self.entities[0].node = node
            self.update_schema(
                "aliquot",
                "links",
                [
                    {
                        "exclusive": False,
                        "required": True,
                        "subgroup": [
                            {
                                "name": "samples",
                                "backref": "aliquots",
                                "label": "derived_from",
                                "multiplicity": "many_to_one",
                                "target_type": "sample",
                            },
                        ],
                    }
                ],
            )
            self.graph_validator.record_errors(g, self.entities)
            self.assertEqual(0, len(self.entities[0].errors))

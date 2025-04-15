import unittest
import logging
from psqlgraph.exc import ValidationError
from gen3datamodel import models as md

logging.basicConfig(level=logging.INFO)


class TestDataModel(unittest.TestCase):
    def test_type_validation(self):
        d = md.Diagnosis()
        with self.assertRaises(ValidationError):
            d.lymph_nodes_positive = "five"
        d.lymph_nodes_positive = 0

        d = md.Diagnosis()
        with self.assertRaises(ValidationError):
            d.morphology = 0
        d.morphology = "0"

        s = md.Sample()
        with self.assertRaises(ValidationError):
            s.is_ffpe = "false"
        s.is_ffpe = False

        s = md.Slide()
        with self.assertRaises(ValidationError):
            s.percent_necrosis = "0.0"
        s.percent_necrosis = 0.0

    def test_link_clobber_prevention(self):
        with self.assertRaises(AssertionError):
            md.EdgeFactory(
                "Testedge",
                "test",
                "sample",
                "aliquot",
                "aliquots",
                "_uncontended_backref",
            )

    def test_backref_clobber_prevention(self):
        with self.assertRaises(AssertionError):
            md.EdgeFactory(
                "Testedge",
                "test",
                "sample",
                "aliquot",
                "_uncontended_link",
                "samples",
            )

# -*- coding: utf-8 -*-
"""
gen3datamodel.tests.conftest
----------------------------------

Test GDC specific index creation.

"""


def test_secondary_key_indexes(indexes):
    assert "index_node_sample_project_id" in indexes
    assert "index_node_case_submitter_id_lower" in indexes
    assert "index_4df72441_famihist_submitte_id_lower" in indexes
    assert "transaction_logs_project_id_idx" in indexes

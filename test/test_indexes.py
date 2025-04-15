# -*- coding: utf-8 -*-
"""
gen3datamodel.test.conftest
----------------------------------

Test GDC specific index creation.

"""


def test_secondary_key_indexes(indexes):
    assert "index_node_datasubtype_name_lower" in indexes
    assert "index_node_aliquot_project_id_lower" in indexes
    assert "index_4df72441_famihist_submitte_id_lower" in indexes
    assert "transaction_logs_project_id_idx" in indexes

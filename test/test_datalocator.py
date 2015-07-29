from psqlgraph import PolyNode
from base import ZugTestBase, SignpostMixin, StorageMixin
from zug.datalocator import DataLocator


class DataLocatorTest(SignpostMixin, StorageMixin, ZugTestBase):

    def test_data_locate(self):
        doc = self.signpost_client.create()
        self.graph.node_insert(node=PolyNode(
            node_id=doc.did,
            label='file',
            properties={
                "file_name": "baz.txt",
                "state": "submitted",
                "md5sum": "bogus",
                "file_size": 4,
            }, system_annotations={
                "analysis_id": "abc123"
            }))
        cont = self.storage_client.create_container("test")
        self.storage_client.upload_object_via_stream(
            "data", cont, "abc123/baz.txt")
        self.locator = DataLocator(storage_client=self.storage_client,
                                   graph=self.graph,
                                   signpost_client=self.signpost_client)
        self.locator.sync("test")
        doc.refresh()
        self.assertEqual(doc.urls, ["file://local/test/abc123/baz.txt"])
        with self.graph.session_scope():
            node = self.graph.nodes().ids(doc.did).one()
            self.assertEqual(node["state"], "live")
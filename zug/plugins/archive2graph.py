import os
import imp
import requests
import logging
import yaml
import copy
import traceback

from lxml import etree
from pprint import pprint
from zug import basePlugin
from zug.exceptions import IgnoreDocumentException, EndOfQueue

currentDir = os.path.dirname(os.path.realpath(__file__))
logger = logging.getLogger(name = "[{name}]".format(name = __name__))

class archive2graph(basePlugin):

    """
    archive2graph
    takes in an xml as a string and compiles a list of nodes and edges

    edges = {
       source_id: {
          destination_id : (edge_type, destination_type),
       }
    } 

    """

    def initialize(self, **kwargs):


        # 'archive_key': 'node_key'
        self.properties = {
            'archive_name': 'archive_name',
            'revision': 'revision',
            'date_added': 'date_added', 
            'dcc_archive_url': 'legacy_url',
        }
        
        # 'archive_key': ('node_type', 'edge_type', 'match_key')
        self.edges = {
            'batch': ('batch', 'data_from', 'id'),
            'center_name': ('center', 'received_from', 'center_name'),
            'disease_code': ('study', 'data_from', 'id'),
            'platform': ('platform', 'generated_by', 'id'),
            'data_level': ('data_level', 'data_from', 'id'),
        }


    def process(self, doc):

        if doc is None: raise IgnoreDocumentException()

        try:
            parsed = self.parse(doc)
        except Exception, msg:
            logger.error(str(msg))
            logger.error(str(doc))
            traceback.print_exc()
            raise IgnoreDocumentException()

        return parsed
        

    def parse(self, doc):

        node = {}
        edges = []

        node['id'] = doc['archive_name']

        for archive_key, node_key in self.properties.items():
            try: node[node_key] = doc[archive_key]
            except: logger.error("Node missing key: " + archive_key)

        for archive_key, trans in self.edges.items():
            try:
                dst_type, edge_type, match_key = trans
                
                edges.append({
                    'matches': {match_key: doc[archive_key]},  # the key, values to match when making edge
                    'node_type': dst_type,
                    'edge_type': edge_type,
                })
            except: 
                logger.error("Node missing key: " + archive_key)

        graph = [{
            'edges': edges,
            'node': {
                'matches': {'id': node['id']},
                'node_type': 'file',
                'body': node,
            }
        }]

        return graph

import re
import json
import datetime
import logging
import psqlgraph
from psqlgraph.edge import PsqlEdge
from psqlgraph.node import PsqlNode
from lxml import etree
from cdisutils.log import get_logger
from zug.datamodel import xml2psqlgraph, cghub_categorization_mapping

log = get_logger(__name__)


deletion_states = ['suppressed', 'redacted']


def unix_time(dt):
    epoch = datetime.datetime.utcfromtimestamp(0)
    delta = dt - epoch
    return int(delta.total_seconds())


class AttrDict(dict):
    def __init__(self, *args, **kwargs):
        super(AttrDict, self).__init__(*args, **kwargs)
        self.__dict__ = self


def to_bool(val):
    possible_true_values = ['true', 'yes']
    possible_false_values = ['false', 'no']
    if val is None:
        return None
    if val.lower() in possible_true_values:
        return True
    elif val.lower() in possible_false_values:
        return False
    else:
        raise ValueError("Cannot convert {} to boolean".format(val))


class cghub2psqlgraph(object):

    """
    """

    def __init__(self, xml_mapping, host, user,
                 password, database, node_validator=None,
                 edge_validator=None, ignore_missing_properties=True,
                 signpost=None):
        """

        """

        self.graph = []
        self.bam_index_regex = re.compile('(.*)\.bai')
        self.center_regex = re.compile('(.*-){6}(.*)')
        self.xml_mapping = json.loads(
            json.dumps(xml_mapping), object_hook=AttrDict)
        self.graph = psqlgraph.PsqlGraphDriver(
            host=host, user=user, password=password, database=database)
        if node_validator:
            self.graph.node_validator = node_validator
        if edge_validator:
            self.graph.edge_validator = edge_validator
        self.xml = xml2psqlgraph.xml2psqlgraph(
            xml_mapping, host, user, password, database,
            node_validator=node_validator,
            edge_validator=edge_validator,
            ignore_missing_properties=ignore_missing_properties)
        self.signpost = signpost  # should be a SignpostClient object
        self.reset()

    def rebase(self, source):
        """Similar to export in xml2psqlgraph, but re-writes changes onto the
        graph

        ..note: postcondition: node/edge state is cleared.

        :param src source:
            the file source to be put in system_annotations

        """
        with self.graph.session_scope():
            self.rebase_file_nodes(source)
        with self.graph.session_scope():
            self.export_edges()
        self.reset()

    def reset(self):
        self.files_to_add = {}
        self.files_to_delete = []
        self.edges = {}
        self.related_to_edges = {}

    def get_file_by_key(self, file_key):
        analysis_id, file_name = file_key
        return self.graph.nodes().labels('file')\
                                 .props({'file_name': file_name})\
                                 .sysan({'analysis_id': analysis_id})\
                                 .first()

    def merge_file_node(self, file_key, node, system_annotations):
        """either create or update file record

        1. does this file_key already exist
        2a. if it does, then update it
        2b. if it does not, then get a new id for it, and add it

        :param src source:
            the file source to be put in system_annotations

        """

        analysis_id, file_name = file_key
        existing = self.get_file_by_key(file_key)
        system_annotations.update({'analysis_id': analysis_id})

        if existing is not None:
            log.debug('Merging {}'.format(file_key))
            node_id = existing.node_id
            self.graph.node_update(
                node=existing,
                properties=node.properties,
                system_annotations=system_annotations)
        else:
            log.debug('Adding {}'.format(file_key))
            doc = self.signpost.create()
            node_id = doc.did
            node.node_id = node_id
            node.system_annotations.update(system_annotations)
            try:
                self.graph.node_insert(node=node)
            except:
                log.error(node)
                log.error(node.properties)
                raise

        # Add the correct src_id to this file's edges now that we know it
        for edge in self.edges.get(file_key, []):
            edge.src_id = node_id

    def rebase_file_nodes(self, source):
        """update file records in graph

        1. for each valid file, merge it in to the graph
        2. for each invalid file, remove it from the graph

        :param src source:
            the file source to be put in system_annotations

        """
        system_annotations = {'source': source}
        # Loop through files to add and merge them into the graph
        for file_key, node in self.files_to_add.iteritems():
            self.merge_file_node(file_key, node, system_annotations)

        # Loop through files to remove and delete them from the graph
        for file_key in self.files_to_delete:
            node = self.get_file_by_key(file_key)
            if node:
                log.debug('Redacting {}'.format(file_key))
                self.graph.node_delete(node=node)
            else:
                log.debug('Redaction not necessary {}'.format(file_key))

    def export_edge(self, edge):
        """
        Does this edge already exist? If not, insert it, else update it

        """
        existing = self.graph.edge_lookup(
            src_id=edge.src_id, dst_id=edge.dst_id, label=edge.label).first()
        if not existing:
            src = self.graph.nodes().ids(str(edge.dst_id)).first()
            if src:
                self.graph.edge_insert(edge)
            else:
                logging.warn('Missing {} destination {}'.format(
                    edge.label, edge.dst_id))
                src = self.graph.nodes().ids(edge.src_id).one()
                src.system_annotations.update({'missing_aliquot': edge.dst_id})
        else:
            self.graph.edge_update(
                existing, edge.system_annotations, edge.properties)

    def export_edges(self):
        """Adds related_to edges then all other edges to psqlgraph from
        self.edges

        """
        for src_key, dst_key in self.related_to_edges.items():
            self.save_edge(src_key, self.files_to_add[dst_key].node_id,
                           'file', 'related_to',
                           src_id=self.files_to_add[src_key].node_id)
        for src_f_name, edges in self.edges.iteritems():
            map(self.export_edge, edges)
        self.edges = {}

    def initialize(self, data):
        """Takes an xml string and performs xpath query to get result roots

        """
        if not data:
            return None
        self.xml_root = etree.fromstring(str(data)).getroottree()
        self.node_roots = {}
        for node_type, param_list in self.xml_mapping.items():
            for params in param_list:
                self.node_roots[node_type] = self.xml.get_node_roots(
                    node_type, params, root=self.xml_root)

    def parse_all(self):
        for node_type, params in self.xml_mapping.items():
            for root in self.node_roots[node_type]:
                self.parse_file_node(node_type, root, params)

    def parse(self, node_type, root):
        """Main function that takes xml string and converts it to a graph to
        insert into psqlgraph.


        Steps:
        1. get analysis_id and filename as unique id
        2. parse literal properties from xml
        3. parse datetime properties from xml
        4. insert constant properties
        5. get the acl for the node
        6. check if file is live
        7. if live
           a. cache for later insertion
           b. start edge parsing
              i.   check if file is *.bam.bai
              ii.  if *.bam.bai, cache related to edge
              iii. if not *.bam.bai
                  1. look up edges from xml
                  2. cache edge for later insertion
        8. if not live
           a. cache for later suppression

        ..note: This function doesn't actually insert it into the
        graph.  You must call export after parse().

        :param str data: xml string to convert and insert

        """
        with self.graph.session_scope():
            for params in self.xml_mapping[node_type]:
                files = self.xml.get_node_roots(node_type, params, root=root)
                for f in files:
                    self.parse_file_node(f, node_type, params)

    def parse_file_node(self, root, node_type, params):
        """Convert a subsection of the xml that will be treated as a node

        :param str node_type: the type of node to be used as a label
        :param dict params:
            the parameters that govern xpath queries and translation
            from the translation yaml file

        """
        # Get node and node properties
        file_key = self.get_file_key(root, node_type, params)
        args = (root, node_type, params, file_key)
        props = self.xml.get_node_properties(*args)
        props.update(self.xml.get_node_datetime_properties(*args))
        props.update(self.xml.get_node_const_properties(*args))
        acl = self.xml.get_node_acl(root, node_type, params)

        # Save the node for deletion or insertion
        state = self.get_file_node_state(*args)
        if state in deletion_states:
            if file_key not in self.files_to_delete:
                self.files_to_delete.append(file_key)
        elif state == 'live':
            self.categorize_file(root, file_key)
            node = self.save_file_node(file_key, node_type, props, acl)
            self.add_edges(root, node_type, params, file_key, node)
        else:
            node = self.get_file_by_key(file_key)
            if node:
                log.warn("File {} is in {} state but was ".format(
                    node, state) + "already in the graph. DELETING!")
            if file_key not in self.files_to_delete:
                self.files_to_delete.append(file_key)

    def categorize_by_switch(self, root, cases):
        for dst_name, case in cases.iteritems():
            if None not in [re.match(condition['regex'], self.xml.xpath(
                    condition['path'], root, single=True, label=dst_name))
                    for condition in case.values()]:
                return dst_name
        raise RuntimeError('Unable to find correct categorization')

    def categorize_file(self, root, file_key):
        file_name = self.xml.xpath('./filename', root, single=True)
        if file_name.endswith('.bai'):
            return

        self.save_center_edge(root, file_key)
        names = cghub_categorization_mapping['names']
        file_mapping = cghub_categorization_mapping['files']
        for dst_label, params in file_mapping.items():
            # Cases for type of parameter to get dst_name
            if 'const' in params:
                dst_name = params['const']
            elif 'path' in params:
                dst_name = self.xml.xpath(
                    params['path'], root, label=dst_label)[0]
            elif 'switch' in params:
                dst_name = self.categorize_by_switch(root, params['switch'])
            else:
                raise RuntimeError('File classification mapping is invalid')

            # Handle those without a destination name
            if not dst_name:
                log.warn('No desination from {} to {} found'.format(
                    file_name, dst_label))
                continue

            # Skip experimental strategies None and OTHER
            if dst_label == 'experimental_strategy' \
               and dst_name in [None, 'OTHER']:
                continue

            # Cache edge to categorization node
            normalized = names.get(dst_label, {}).get(str(dst_name), dst_name)
            dst_id = self.graph.nodes().labels(dst_label)\
                                       .props(dict(name=normalized))\
                                       .one().node_id
            edge_label = file_mapping[dst_label]['edge_label']
            self.save_edge(file_key, dst_id, dst_label, edge_label)

    def save_center_edge(self, root, file_key):
        legacy_sample_id = self.xml.xpath('ancestor::Result/legacy_sample_id',
                                          root, single=True, nullable=False)
        code = self.center_regex.match(legacy_sample_id)
        assert code, 'Unable to parse center code from barcode'
        node = self.graph.nodes().labels('center')\
                                 .props({'code': code.group(2)})\
                                 .one()
        self.save_edge(file_key, node.node_id, node.label, 'submitted_by')

    def add_edges(self, root, node_type, params, file_key, node):
        """
        i.   check if file is *.bam.bai
        ii.  if *.bam.bai, cache related to edge
        iii. if not *.bam.bai
            1. look up edges from xml
            2. cache edge for later insertion

        """
        analysis_id, file_name = file_key
        if self.is_bam_index_file(file_name):
            bam_file_name = self.bam_index_regex.match(file_name).group(1)
            self.related_to_edges[
                (analysis_id, bam_file_name)] = (analysis_id, file_name)
        else:
            edges = self.xml.get_node_edges(root, node_type, params)
            for dst_id, edge in edges.iteritems():
                dst_label, edge_label = edge
                self.save_edge(file_key, dst_id, dst_label, edge_label)

    def is_bam_index_file(self, file_name):
        return self.bam_index_regex.match(file_name)

    def save_file_node(self, file_key, label, properties, acl=[]):
        """Adds an node to self.nodes_to_add

        If the file_key exists in the map, then update the node.  If
        it doesn't exist in the map, create it.

        """
        if file_key in self.files_to_add:
            self.files_to_add[file_key].merge(properties=properties)
        else:
            self.files_to_add[file_key] = PsqlNode(
                node_id=None, acl=acl, label=label, properties=properties)

    def save_edge(self, file_key, dst_id, dst_label, edge_label, src_id=None,
                  properties={}):
        """Adds an edge to self.edges

        If the file_key exists in the map, then append the edge to
        the file_key's list.  If it doesn't exist in the map, create
        it with a singleton containing the edge

        """
        edge = PsqlEdge(src_id=src_id, dst_id=dst_id, label=edge_label,
                        properties=properties)
        if file_key in self.edges:
            self.edges[file_key].append(edge)
        else:
            self.edges[file_key] = [edge]

    def get_file_node_state(self, root, node_type, params, node_id):
        """returns a filenode's state

        :param str node_type:
            the node type to be used as a label in psqlgraph
        :param dict params:
            the parameters that govern xpath queries and translation
            from the translation yaml file

        """
        if not params.state:
            raise Exception('No state xpath for {}'.format(node_type))
        return self.xml.xpath(params.state, root, single=True, label=node_type)

    def get_file_key(self, root, node_type, params):
        """lookup the id for the node

        :param root: the lxml root element to treat as a node
        :param str node_type:
            the node type to be used as a label in psqlgraph
        :param dict params:
            the parameters that govern xpath queries and translation
            from the translation yaml file

        """
        file_name = self.xml.xpath(
            params.file_name, root, single=True, label=node_type)
        analysis_id = self.xml.xpath(
            params.properties.submitter_id.path, root,
            single=True, label=node_type)
        return (analysis_id, file_name)

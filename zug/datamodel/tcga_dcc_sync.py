from cStringIO import StringIO
import tempfile
import tarfile
import re
import hashlib
import uuid
from contextlib import contextmanager
from urlparse import urlparse
from functools import partial
import copy

import requests

from libcloud.storage.drivers.s3 import S3StorageDriver
from libcloud.storage.drivers.cloudfiles import OpenStackSwiftStorageDriver
from libcloud.storage.drivers.local import LocalStorageDriver

from psqlgraph import PsqlNode, PsqlEdge, session_scope
from psqlgraph.validate import AvroNodeValidator, AvroEdgeValidator

from gdcdatamodel import node_avsc_object, edge_avsc_object

from cdisutils.log import get_logger

from zug.datamodel import classification


def md5sum(iterable):
    md5 = hashlib.md5()
    for chunk in iterable:
        md5.update(chunk)
    return md5.hexdigest()


def iterable_from_file(fileobj, chunk_size=8192):
    return iter(partial(fileobj.read, chunk_size), '')


def fix_barcode(s):
    """Munge barcodes matched from filenames into correct format"""
    return s.replace("_", "-").upper()


def fix_uuid(s):
    """Munge uuids matched from filenames into correct format"""
    return s.replace("_", "-").lower()

CLASSIFICATION_ATTRS = ["data_subtype", "data_format", "platform",
                        "experimental_strategy", "tag"]


def classify(archive, filename):
    """Given a filename and an archive that it came from, attempt to
    classify it. Return a dictionary representing the
    classification.
    """
    data_type = archive["data_type_in_url"]
    data_level = str(archive["data_level"])
    platform = archive["platform"]
    potential_classifications = classification[data_type][data_level][platform]
    for possibility in potential_classifications:
        match = re.match(possibility["pattern"], filename)
        if match:
            result = copy.deepcopy(possibility["category"])
            result["data_format"] = possibility["data_format"]
            if possibility.get("captured_fields"):
                for i, field in enumerate(possibility["captured_fields"]):
                    if field not in ['_', '-']:
                        if field.endswith("barcode"):
                            result[field] = fix_barcode(match.groups(i))
                        elif field.endswith("uuid"):
                            result[field] = fix_uuid(match.groups(i))
                        else:
                            result[field] = match.groups(i)
            return result
    raise RuntimeError("file {}/{}failed to classify".format(archive["archive_name"], filename))


class TCGADCCArchiveSyncer(object):

    MAX_BYTES_IN_MEMORY = 2 * (10**9)  # 2GB TODO make this configurable
    SIGNPOST_VERSION = "v0"

    def __init__(self, signpost_url, pg_driver, storage_client, dcc_auth, scratch_dir):
        self.signpost_url = signpost_url
        self.storage_client = storage_client
        self.pg_driver = pg_driver
        self.pg_driver.node_validator = AvroNodeValidator(node_avsc_object)
        self.pg_driver.edge_validator = AvroEdgeValidator(edge_avsc_object)
        self.dcc_auth = dcc_auth
        self.scratch_dir = scratch_dir
        self.log = get_logger("tcga_dcc_sync")

    def put_archive_in_pg(self, archive):
        # legacy_id is just the name without the revision or series
        # this will be identical between different versions of an archive as new
        # versions are submitted
        legacy_id = re.sub("\.(\d+?)\.(\d+)$", "", archive["archive_name"])
        self.log.info("looking for archive %s in postgres", archive["archive_name"])
        maybe_this_archive = self.pg_driver.node_lookup_one(label="archive",
                                                            property_matches={"legacy_id": legacy_id,
                                                                              "revision": archive["revision"]})
        if maybe_this_archive:
            self.log.info("found archive %s in postgres, not inserting", archive["archive_name"])
            return maybe_this_archive
        self.log.info("looking up old versions of archive %s in postgres", legacy_id)
        with self.pg_driver.session_scope() as session:
            old_versions = self.pg_driver.node_lookup(label="archive",
                                                      property_matches={"legacy_id": legacy_id},
                                                      session=session).all()
            if len(old_versions) > 1:
                # since we void all old versions of an archive when we add a new one,
                # there should never be more than one old version in the database
                raise ValueError("multiple old versions of an archive found")
            if old_versions:
                old_archive = old_versions[0]
                self.log.info("old revision (%s) of archive %s found, voiding it and associated files",
                              old_archive.properties["revision"],
                              legacy_id)
                # TODO it would be awesome to verify that the changes we make actually match what's in
                # CHANGES_DCC.txt,
                # first get all the files related to this archive and void them
                for file in self.pg_driver.node_lookup(label="file", session=session)\
                                          .with_edge_to_node("member_of", old_archive)\
                                          .all():
                    self.log.info("voiding file %s", str(file))
                    self.pg_driver.node_delete(node=file, session=session)
                self.pg_driver.node_delete(node=old_archive, session=session)
            new_archive_node = PsqlNode(
                node_id=self.allocate_id_from_signpost(),
                label="archive",
                properties={"legacy_id": legacy_id,
                            "revision": archive["revision"]})
            self.log.info("inserting new archive node in postgres: %s", str(new_archive_node))
            session.add(new_archive_node)
        return new_archive_node

    def get_archive_stream(self, url):
        resp = requests.get(url, stream=True, allow_redirects=False)
        if resp.is_redirect:  # redirects mean a protected archive, so use auth
            resp = requests.get(resp.headers["location"], stream=True,
                                auth=self.dcc_auth, allow_redirects=False)
        resp.raise_for_status()
        return resp

    @contextmanager
    def download_archive(self, archive):
        self.log.info("downloading archive %s", archive["archive_name"])
        resp = self.get_archive_stream(archive["dcc_archive_url"])
        if int(resp.headers["content-length"]) > self.MAX_BYTES_IN_MEMORY:
            self.log.info("archive size is % bytes, storing in temp file on disk", resp.headers["content-length"])
            temp_file = tempfile.TemporaryFile(prefix=self.scratch_dir)
        else:
            temp_file = StringIO()
        for chunk in resp.iter_content(16000):
            temp_file.write(chunk)
        temp_file.seek(0)
        try:
            yield temp_file
        finally:
            temp_file.close()

    def sync_archives(self, archives):
        for archive in archives:
            self.sync_archive(archive)

    def lookup_file_in_pg(self, archive_node, filename):
        q = self.pg_driver.node_lookup(label="file",
                                       property_matches={"file_name": filename})\
                          .with_edge_to_node("member_of", archive_node)
        file_nodes = q.all()
        if not file_nodes:
            return None
        if len(file_nodes) > 1:
            raise ValueError("multiple files with the same name found in archive {}".format(archive_node))
        else:
            return file_nodes[0]

    def allocate_id_from_signpost(self):
        """Retrieve a new empty did from signpost."""
        resp = requests.post("/".join([self.signpost_url,
                                       self.SIGNPOST_VERSION,
                                       "did"]),
                             json={"urls": []})
        resp.raise_for_status()
        return resp.json()["did"]

    def get_urls_from_signpost(self, did):
        """Retrieve all the urls associated with a did in signpost."""
        resp = requests.get("/".join([self.signpost_url,
                                      self.SIGNPOST_VERSION,
                                      "did",
                                      did]))
        resp.raise_for_status()
        return resp.json()["urls"]

    def store_url_in_signpost(self, did, url):
        # replace whatever urls are in there with the one passed in
        # going to have to go a GET first to get the rev
        getresp = requests.get("/".join([self.signpost_url,
                                         self.SIGNPOST_VERSION,
                                         "did",
                                         did]))
        getresp.raise_for_status()
        getjson = getresp.json()
        rev = getjson["rev"]
        old_urls = getjson["urls"]
        if old_urls:
            raise RuntimeError("attempt to replace existing urls on did {}".format(did))
        patchresp = requests.patch("/".join([self.signpost_url,
                                             self.SIGNPOST_VERSION,
                                             "did",
                                             did]),
                                   json={"urls": [url], "rev": rev})
        patchresp.raise_for_status()

    def tie_file_to_atribute(self, file_node, attr, value, session):
        LABEL_MAP = {
            "platform": "generated_from",
            "data_subtype": "member_of",
            "data_format": "member_of",
            "tag": "member_of",
            "experimental_strategy": "member_of"
        }
        if not isinstance(value, list):
            # this is to handle the thing where tag is
            # sometimes a list and sometimes a string
            value = [value]
        for val in value:
            attr_node = self.pg_driver.node_lookup_one(label=attr,
                                                       property_matches={"name": val},
                                                       session=session)
            if not attr_node:
                attr_node = PsqlNode(node_id=str(uuid.uuid4()),
                                     label=attr, properties={"name": val})
                self.pg_driver.node_insert(attr_node, session=session)
            edge_to_attr_node = PsqlEdge(label=LABEL_MAP[attr],
                                         src_id=file_node.node_id,
                                         dst_id=attr_node.node_id)
            self.pg_driver.edge_insert(edge_to_attr_node, session=session)

    def store_file_in_pg(self, archive_node, filename, md5, md5_source,
                         file_classification):
        # not there, need to get id from signpost and store it.
        did = self.allocate_id_from_signpost()
        acl = ["phs000178"] if file_classification["data_access"] == "protected" else []
        file_node = PsqlNode(node_id=did, label="file", acl=acl,
                             properties={"file_name": filename,
                                         "md5sum": md5,
                                         "state": "submitted",
                                         "state_comment": None},
                             system_annotations={"md5_source": md5_source,
                                                 "file_source": "tcga_dcc"})
        edge_to_archive = PsqlEdge(label="member_of",
                                   src_id=file_node.node_id,
                                   dst_id=archive_node.node_id,
                                   properties={})

        with session_scope(self.pg_driver.engine) as session:
            self.log.info("inserting file %s as node %s", filename, file_node)
            self.pg_driver.node_insert(file_node, session=session)
            self.pg_driver.edge_insert(edge_to_archive, session=session)
            # ok, classification
            #
            # we need to create edges to: data_subtype, data_format,
            # platform, experimental_strategy, tag.
            for attribute in CLASSIFICATION_ATTRS:
                if file_classification.get(attribute):
                    self.tie_file_to_atribute(file_node, attribute,
                                              file_classification[attribute],
                                              session)
                else:
                    self.log.warning("not tieing %s (node %s) to a %s", filename, file_node, attribute)
        return file_node

    def container_for(self, archive):
        if archive["protected"]:
            return "tcga_dcc_protected"
        else:
            return "tcga_dcc_public"

    # TODO make these idepmotent

    def upload_archive_to_object_store(self, archive, data):
        container = self.storage_client.get_container(self.container_for(archive))
        objname = "/".join(["archives", archive["archive_name"]])
        obj = container.upload_object_via_stream(iterable_from_file(data), objname)
        data.seek(0)
        return obj

    def upload_file_to_object_store(self, archive, tarball, tarinfo, filename):
        container = self.storage_client.get_container(self.container_for(archive))
        objname = "/".join([archive["archive_name"], filename])
        fileobj = tarball.extractfile(tarinfo)
        obj = container.upload_object_via_stream(iterable_from_file(fileobj), objname)
        return obj

    def url_for(self, obj):
        """Return a url for a libcloud object."""
        DRIVER_TO_SCHEME = {
            S3StorageDriver: "s3",
            OpenStackSwiftStorageDriver: "swift",
            LocalStorageDriver: "file"
        }
        scheme = DRIVER_TO_SCHEME[obj.driver.__class__]
        host = obj.driver.connection.host
        container = obj.container.name
        name = obj.name
        url = "{scheme}://{host}/{container}/{name}".format(scheme=scheme,
                                                            host=host,
                                                            container=container,
                                                            name=name)
        return url

    def obj_for(self, url):
        # for now this assumes that the object can be found by self.storage_client
        parsed = urlparse(url)
        return self.storage_client.get_object(*parsed.path.split("/", 2)[1:])

    def set_file_state(self, file_node, state):
        self.pg_driver.node_update(file_node, properties={"state": state})

    def verify_sum(self, file_node, obj):
        expected_sum = file_node["md5sum"]
        actual_sum = md5sum(obj.as_stream())
        if actual_sum != expected_sum:
            self.pg_driver.node_update(file_node,
                                       properties={"state": "invalid",
                                                   "state_comment": "bad md5sum"})
            self.log.warning("file %s has invalid checksum", file_node.properties["file_name"])

    def sync_file(self, archive, archive_node, tarball, tarinfo, dcc_md5):
        # 1) look up file in database, if not present, insert it, getting
        # id from signpost
        # 2) put file in object store if not already there
        filename = tarinfo.name.split("/")[-1]
        file_classification = classify(archive, filename)
        if ("to_be_determined" in file_classification.values() or
            "data_access" not in file_classification.keys()):
            # we shouldn't insert this file
            self.log.info("file %s/%s classified as %s, not inserting",
                          archive["archive_name"],
                          filename,
                          file_classification)
            return
        file_node = self.lookup_file_in_pg(archive_node, filename)
        if not file_node:
            if dcc_md5 is None:
                md5 = md5sum(iterable_from_file(tarball.extractfile(tarinfo)))
                md5_source = "gdc_import_process"
            else:
                md5 = dcc_md5
                md5_source = "tcga_dcc"
            file_node = self.store_file_in_pg(archive_node, filename,
                                              md5, md5_source, file_classification)
        else:
            self.log.info("file %s in archive %s already in postgres, not inserting",
                          filename,
                          archive_node.properties["legacy_id"])
        # does signpost already know about it?  TODO think about what
        # to do if we 404 here. that would mean that we inserted this
        # thing into signpost once before and it has since
        # disappeared. There's no good way to recover from this since
        # signpost is the id authority and we can't tell it to just
        # insert a specific id
        urls = self.get_urls_from_signpost(file_node.node_id)
        if not urls:
            self.set_file_state(file_node, "uploading")
            obj = self.upload_file_to_object_store(archive, tarball, tarinfo, filename)
            new_url = self.url_for(obj)
            self.store_url_in_signpost(file_node.node_id, new_url)
        self.set_file_state(file_node, "validating")
        # no reconstruct the object from signpost and validate
        urls = self.get_urls_from_signpost(file_node.node_id)
        if not urls:
            raise RuntimeError("no urls in signpost for file {}, node:{}".format(file_node.file_name, file_node))
        obj = self.obj_for(urls[0])
        self.verify_sum(file_node, obj)
        # classify based on Junjun/Zhenyu's regexes?
        self.set_file_state(file_node, "live")

    def extract_manifest(self, archive, tarball):
        try:
            manifest_tarinfo = tarball.getmember("{}/MANIFEST.txt".format(archive["archive_name"]))
            manifest_data = tarball.extractfile(manifest_tarinfo)
            res = {}
            for line in manifest_data.readlines():
                md5, filename = line.split()
                res[filename] = md5
            return res
        except:
            self.log.exception("failed to load manifest from %s", archive["archive_name"])
            return None

    def sync_archive(self, archive):
        self.log.info("syncing archive %s", archive["archive_name"])
        archive_node = self.put_archive_in_pg(archive)
        with self.download_archive(archive) as archive_data:
            urls = self.get_urls_from_signpost(archive_node.node_id)
            if not urls:
                archive_obj = self.upload_archive_to_object_store(archive, archive_data)
                archive_url = self.url_for(archive_obj)
                self.store_url_in_signpost(archive_node.node_id, archive_url)
            tarball = tarfile.open(fileobj=archive_data, mode="r:gz")
            manifest = self.extract_manifest(archive, tarball)
            for tarinfo in tarball:
                if tarinfo.name != "{}/MANIFEST.txt".format(archive["archive_name"]):
                    if manifest is None:
                        this_md5 = None
                    else:
                        this_md5 = manifest[tarinfo.name.split("/")[-1]]
                    self.sync_file(archive, archive_node, tarball,
                                   tarinfo, this_md5)

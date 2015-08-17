import os
import hashlib
import tempfile
import time
import shutil
from urlparse import urlparse
from cStringIO import StringIO

from sqlalchemy.pool import NullPool
import docker
from boto.s3.connection import OrdinaryCallingFormat
from requests.exceptions import ReadTimeout

# buffer 10 MB in memory at once
from boto.s3.key import Key
Key.BufferSize = 10 * 1024 * 1024


from psqlgraph import PsqlGraphDriver
from cdisutils import md5sum
from cdisutils.log import get_logger
from cdisutils.net import BotoManager, url_for_boto_key
from signpostclient import SignpostClient
from zug.consul_manager import ConsulManager
from gdcdatamodel.models import File

from abc import ABCMeta, abstractmethod, abstractproperty


def first_s3_url(doc):
    for url in doc.urls:
        parsed = urlparse(url)
        if parsed.scheme == "s3":
            return url
    raise RuntimeError("File {} does not have s3 urls.".format(doc.id))


def read_in_chunks(file_object, chunk_size=1024*1024*1024):
    while True:
        data = file_object.read(chunk_size)
        if not data:
            break
        yield data


class AbstractHarmonizer(object):
    """Generic abstract harmonization class. Child classes just implement
    a few methods and then can be run.

    """

    __metaclass__ = ABCMeta

    def __init__(self, graph=None, s3=None,
                 signpost=None, consul_prefix=None,
                 **kwargs):
        # get configuration from environment and kwargs
        for kwarg in kwargs.keys():
            assert kwarg in self.valid_extra_kwargs
        self.config = self.get_base_config()
        self.config.update(self.get_config(kwargs))

        # do some simple validations
        self.validate_config()

        # now connect to all the services we need: postgres, s3,
        # signpost, consul, docker
        if graph:
            self.graph = graph
        else:
            self.graph = PsqlGraphDriver(
                os.environ["PG_HOST"],
                os.environ["PG_USER"],
                os.environ["PG_PASS"],
                os.environ["PG_NAME"],
                poolclass=NullPool,
            )
        if s3:
            self.s3 = s3
        else:
            self.s3 = BotoManager(self.config["s3"])
        if signpost:
            self.signpost = signpost
        else:
            self.signpost = SignpostClient(self.config["signpost_url"])
        self.docker = docker.Client(**docker.utils.kwargs_from_env(
            assert_hostname=False
        ))
        if not consul_prefix:
            consul_prefix = self.name
        self.consul = ConsulManager(prefix=consul_prefix)
        self.start_time = int(time.time())
        self.log = get_logger(self.name)

    def get_base_config(self):
        """Compute a config dictionary from the process environment. This
        implementation is incomplete, it just has some common base
        info. Subclasses will have to override to provide more
        specific information, as specified in `validate_config`.

        """
        workdir = os.environ.get("ALIGNMENT_WORKDIR", "/mnt/alignment")
        scratch_dir = tempfile.mkdtemp(prefix="scratch", dir=workdir)
        return {
            "s3": {
                "cleversafe.service.consul": {
                    "aws_access_key_id": os.environ["CLEV_ACCESS_KEY"],
                    "aws_secret_access_key": os.environ["CLEV_SECRET_KEY"],
                    "is_secure": False,
                    "calling_format": OrdinaryCallingFormat()
                },
                "ceph.service.consul": {
                    "aws_access_key_id": os.environ["CEPH_ACCESS_KEY"],
                    "aws_secret_access_key": os.environ["CEPH_SECRET_KEY"],
                    "is_secure": False,
                    "calling_format": OrdinaryCallingFormat()
                },
            },
            "signpost_url": os.environ["SIGNPOST_URL"],
            "upload_host": os.environ["UPLOAD_S3_HOST"],
            "workdir": workdir,
            "scratch_dir": os.path.relpath(scratch_dir, start=workdir),
            "container_workdir": "/alignment",  # TODO make this configurable?
            "docker_image_id": os.environ["DOCKER_IMAGE_ID"],
        }

    def validate_config(self):
        """Just some sanity checking to confirm that requirement keys are
        present. Subclasses can override to do more complicated
        validations.

        """
        assert "s3" in self.config
        assert "upload_host" in self.config
        assert "signpost_url" in self.config
        assert "output_buckets" in self.config
        for key in self.output_schema.keys():
            assert key in self.config["output_buckets"]
        assert "paths" in self.config
        # normpath all static paths
        for key, path in self.config["paths"].iteritems():
            assert not path.startswith("/")  # these must be relative
            self.config[key] = os.path.normpath(path)
        assert os.path.isabs(self.config["workdir"])
        assert os.path.isabs(self.config["container_workdir"])

    def cleanup(self):
        scratch_abspath = self.host_abspath(self.config["scratch_dir"])
        self.log.info("Removing scatch dir %s", scratch_abspath)
        shutil.rmtree(scratch_abspath)
        self.consul.cleanup()

    def try_lock(self, lock_id):
        locked = self.consul.get_consul_lock(lock_id)
        if locked:
            self.log.info("locked consul key: %s", self.consul.consul_key)
        else:
            raise RuntimeError("Couldn't lock consul key {}"
                               .format(self.consul.consul_key))

    def validate_inputs(self, inputs):
        for key, val in inputs.iteritems():
            assert isinstance(val, self.input_schema[key])

    def host_abspath(self, *relative_path):
        return os.path.join(self.config["workdir"],
                            os.path.join(*relative_path))

    def container_abspath(self, *relative_path):
        return os.path.join(self.config["container_workdir"],
                            os.path.join(*relative_path))

    def download_file(self, file):
        """
        Download a file node from s3, returning it's workdir relative path.
        """
        self.log.info("Downloading file %s, size %s", file, file.file_size)
        self.log.info("Querying signpost for file urls")
        doc = self.signpost.get(file.node_id)
        url = first_s3_url(doc)
        self.log.info("Getting key for url %s", url)
        key = self.s3.get_url(url)
        workdir_relative_path = os.path.join(self.config["scratch_dir"], file.file_name)
        abs_path = os.path.join(self.config["workdir"], workdir_relative_path)
        md5 = hashlib.md5()
        with open(abs_path, "w") as f:
            self.log.info("Saving file from s3 to %s", abs_path)
            for chunk in key:
                md5.update(chunk)
                f.write(chunk)
        digest = md5.hexdigest()
        if digest != file.md5sum:
            raise RuntimeError("Downloaded md5sum {} != "
                               "database md5sum {}".format(digest, file.md5sum))
        else:
            return workdir_relative_path

    def download_inputs(self):
        input_paths = {}
        for key, key_type in self.input_schema.iteritems():
            if key_type is File:
                input_paths[key] = self.download_file(self.inputs[key])
        return input_paths

    def check_output_paths(self):
        self.log.info("Checking output paths")
        for path in self.output_paths.values():
            self.log.info("Checking for existance %s", path)
            if not os.path.exists(path):
                raise RuntimeError("Output path does not exist: {}".format(path))

    def run_docker(self):
        filtered_images = [i for i in self.docker.images()
                           if i["Id"] == self.config["docker_image_id"]]
        if not filtered_images:
            raise RuntimeError("No docker image with id {} found!"
                               .format(self.config["docker_image_id"]))
        self.docker_image = filtered_images[0]
        self.log.info("Creating docker container")
        self.log.info("Docker image id: %s", self.docker_image["Id"])
        self.docker_cmd = self.build_docker_cmd()
        self.log.info("Mapping host volume %s to container volume %s",
                      self.config["workdir"], self.config["container_workdir"])
        host_config = docker.utils.create_host_config(binds={
            self.config["workdir"]: {
                "bind": self.config["container_workdir"],
                "ro": False,
            },
        })
        self.log.info("Docker command: %s", self.docker_cmd)
        container = self.docker.create_container(
            image=self.docker_image["Id"],
            command=self.docker_cmd,
            host_config=host_config,
            user="root",
        )
        self.log.info("Starting docker container and waiting for it to complete")
        self.docker.start(container)
        retcode = None
        while retcode is None:
            try:
                for log in self.docker.logs(container, stream=True,
                                            stdout=True, stderr=True):
                    self.log.info(log.strip())  # TODO maybe something better
                retcode = self.docker.wait(container, timeout=0.1)
            except ReadTimeout:
                pass
        if retcode != 0:
            self.docker.remove_container(container, v=True)
            raise RuntimeError("Docker container failed with exit code {}".format(retcode))
        self.log.info("Container run finished successfully, removing")
        self.docker.remove_container(container, v=True)

    def upload_file(self, abs_path, bucket_name, name, verify=True):
        """Upload the file at abs_path to bucket with key named name. Then
        download again, verify md5sum and return it.
        """
        self.log.info("Uploading %s to bucket %s from path %s",
                      name, bucket_name, abs_path)
        disk_size = os.path.getsize(abs_path)
        self.log.info("File size on disk is %s", disk_size)
        self.log.info("Getting bucket %s", bucket_name)
        bucket = self.s3[self.config["upload_host"]].get_bucket(bucket_name)
        self.log.info("Initiating multipart upload")
        mp = bucket.initiate_multipart_upload(name)
        time.sleep(5)  # give cleversafe a bit of time for it to show up
        md5 = hashlib.md5()
        with open(abs_path) as f:
            num_parts = 0
            for i, chunk in enumerate(read_in_chunks(f), start=1):
                self.log.info("Uploading chunk %s", i)
                md5.update(chunk)
                sio = StringIO(chunk)
                tries = 0
                while tries < 30:
                    tries += 1
                    try:
                        mp.upload_part_from_file(sio, i)
                        break
                    except KeyboardInterrupt:
                        raise
                    except:
                        self.log.exception(
                            "caught exception while uploading part %s, try %s "
                            "sleeping for 2 seconds and retrying", i, tries
                        )
                        time.sleep(2)
                num_parts += 1
                self.log.info("Reading next chunk from disk")
        self.log.info("Completing multipart upload")
        parts_on_s3 = len(mp.get_all_parts())
        if num_parts != parts_on_s3:
            raise RuntimeError("Number of parts sent %s "
                               "does not equal number of parts on s3 %s",
                               num_parts, parts_on_s3)
        completed_mp = mp.complete_upload()
        key = bucket.get_key(completed_mp.key_name)
        assert key.name == name
        uploaded_md5 = md5.hexdigest()
        self.log.info("Uploaded md5 is %s", uploaded_md5)
        if verify:
            s3_size = int(key.size)
            if disk_size != s3_size:
                raise RuntimeError("Size on disk {} does not "
                                   "match size on s3 {}"
                                   .format(disk_size, s3_size))
            self.log.info("md5ing from s3 to verify")
            md5_on_s3 = md5sum(key)
            if uploaded_md5 != md5_on_s3:
                raise RuntimeError("checksums do not match: "
                                   "uploaded {}, s3 has {}"
                                   .format(uploaded_md5, md5_on_s3))
            else:
                self.log.info("md5s match: %s", uploaded_md5)
        else:
            self.log.info("skipping md5 verification")
        return key, uploaded_md5

    def upload_file_and_save_to_db(self, abs_path, bucket, file_name, acl):
        """
        Upload a file and save it in the db/signpost such that it's
        downloadable. The s3 key name is computed as {node_id}/{file_name}
        """
        self.log.info("Allocating id from signpost")
        doc = self.signpost.create()
        self.log.info("New id: %s", doc.did)
        s3_key_name = "/".join([
            doc.did,
            file_name
        ])
        self.log.info("Uploading file with s3 key %s to bucket %s",
                      s3_key_name, bucket)
        s3_key, md5 = self.upload_file(
            abs_path,
            bucket,
            s3_key_name
        )
        url = url_for_boto_key(s3_key)
        self.log.info("Patching signpost with url %s", url)
        doc.urls = [url]
        doc.patch()
        file_node = File(
            node_id=doc.did,
            acl=acl,
            file_name=file_name,
            md5sum=md5,
            file_size=int(s3_key.size),
            # TODO ????? should this be live? idk
            state="uploaded",
            state_comment=None,
            submitter_id=None,
        )
        file_node.system_annotations = {
            "source": "tcga_exome_alignment",
            # TODO anything else here?
        }
        self.log.info("File node: %s", file_node)
        return file_node

    def go(self):
        try:
            self.consul.start_consul_session()
            with self.graph.session_scope():
                lock_id, inputs = self.find_inputs()
            self.validate_inputs(inputs)
            self.try_lock(lock_id)
            self.inputs = inputs
            self.input_paths = self.download_inputs()
            self.run_docker()
            self.check_output_paths()
            self.handle_output()
        finally:
            self.cleanup()

    # interface methods / properties that subclasses must implement

    @abstractmethod
    def get_config(self):
        raise NotImplementedError()

    @abstractproperty
    def valid_extra_kwargs(self):
        raise NotImplementedError()

    @abstractproperty
    def name(self):
        raise NotImplementedError()

    @abstractproperty
    def input_schema(self):
        raise NotImplementedError()

    @abstractmethod
    def find_inputs(self):
        raise NotImplementedError()

    @abstractproperty
    def output_schema(self):
        raise NotImplementedError()

    @abstractproperty
    def output_paths(self):
        raise NotImplementedError()

    @abstractmethod
    def handle_output(self):
        raise NotImplementedError()

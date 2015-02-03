from zug.datamodel.tcga_dcc_sync import TCGADCCArchiveSyncer
from zug.datamodel.latest_urls import LatestURLParser
from zug.datamodel.prelude import create_prelude_nodes
from argparse import ArgumentParser
from tempfile import mkdtemp
from psqlgraph import PsqlGraphDriver

from libcloud.storage.types import Provider
from libcloud.storage.providers import get_driver

Local = get_driver(Provider.LOCAL)

from random import shuffle

from functools import partial
from multiprocessing.pool import Pool


def sync_list(args, archives):
    driver = PsqlGraphDriver(args.pg_host, args.pg_user,
                             args.pg_pass, args.pg_database)
    for archive in archives:
        syncer = TCGADCCArchiveSyncer(
            archive,
            signpost_url=args.signpost_url,
            pg_driver=driver,
            dcc_auth=(args.dcc_user, args.dcc_pass),
            scratch_dir=args.scratch_dir,
            storage_client = Local(args.os_dir),
            dryrun=args.dryrun,
            force=args.force,
            max_memory=args.max_memory
        )
        try:
            syncer.sync()  # ugh
        except Exception:  # we use Exception so as not to catch KeyboardInterrupt et al.
            syncer.log.exception("caught exception while syncing")


def split(a, n):
    """Split a into n evenly sized chunks"""
    k, m = len(a) / n, len(a) % n
    return [a[i * k + min(i, m):(i + 1) * k + min(i + 1, m)]
            for i in xrange(n)]


def main():
    parser = ArgumentParser()
    parser.add_argument("--pg-host", type=str, help="postgres database host")
    parser.add_argument("--pg-user", type=str, help="postgres database user")
    parser.add_argument("--pg-pass", type=str, help="postgres database password")
    parser.add_argument("--pg-database", type=str,
                        help="the postgres database to connect to")
    parser.add_argument("--signpost-url", type=str, help="signpost url to use")
    parser.add_argument("--dcc-user", type=str, help="username for dcc auth")
    parser.add_argument("--dcc-pass", type=str, help="password for dcc auth")
    parser.add_argument("--dryrun", action="store_true",
                        help="if passed, skip downlading / uploading tarballs")
    parser.add_argument("--force", action="store_true",
                        help="if passed, force sync even if archive appears complete")
    parser.add_argument("--scratch-dir", type=str,
                        help="directory to use as scratch space",
                        default=mkdtemp())
    parser.add_argument("--os-dir", type=str, help="directory to use for mock local object storage",
                        default=mkdtemp())
    parser.add_argument("--archive-name", type=str, help="name of archive to filter to")
    parser.add_argument("--max-memory", type=int, default=2*10**9,
                        help="maximum size (bytes) of archive to download in memory")
    parser.add_argument("--shuffle", action="store_true",
                        help="shuffle the list of archives before processing")
    parser.add_argument("-p", "--processes", type=int, help="process pool size to use")

    args = parser.parse_args()
    archives = list(LatestURLParser())
    if args.archive_name:
        archives = [a for a in archives if a["archive_name"] == args.archive_name]
    if not archives:
        raise RuntimeError("not archive with name {}".format(args.archive_name))
    if args.shuffle:
        shuffle(archives)

    # insert the classification nodes
    driver = PsqlGraphDriver(args.pg_host, args.pg_user,
                             args.pg_pass, args.pg_database)
    create_prelude_nodes(driver)

    if args.processes == 1:
        sync_list(args, archives)
    else:
        pool = Pool(args.processes)
        # this splits the archives list into evenly size chunks
        segments = split(archives, args.processes)
        result = pool.map_async(partial(sync_list, args), segments)
        try:
            result.get(999999)
        except KeyboardInterrupt:
            return


if __name__ == "__main__":
    main()
from setuptools import setup, find_packages

setup(
    name="zug",
    version="0.1",
    packages=find_packages(),
    package_data={
        "zug": [
            "datamodel/tcga_classification.yaml",
            "datamodel/centerCode.csv",
            "datamodel/tissueSourceSite.csv",
            "datamodel/bcr.yaml",
            "datamodel/cghub.yaml",
            "datamodel/clinical.yaml",
            "datamodel/projects.csv",
            "datamodel/cghub_file_categorization.yaml",
            "datamodel/target/barcodes.tsv",
        ]
    },
    install_requires=[
        'progressbar==2.2',
        'networkx',
        'pyyaml',
        'psqlgraph',
        'gdcdatamodel',
        'cdisutils',
        'signpostclient',
        'ds3client',
        'lockfile',
        'lxml==3.4.1',
        'requests==2.5.2',
        'apache-libcloud==0.15.1',
        'cssselect==0.9.1',
        'elasticsearch==1.4.0',
        'pandas==0.15.2',
        'xlrd==0.9.3',
        'consulate==0.4',
        'boto==2.36.0',
        'filechunkio==1.6',
        'docker-py==1.2.2',
    ],
    dependency_links=[
        'git+ssh://git@github.com/NCI-GDC/psqlgraph.git@9bbd0947ef741e5b280f3f8a9476bc6e5e2096f0#egg=psqlgraph',
        'git+ssh://git@github.com/NCI-GDC/cdisutils.git@6c3138bb946da6b68f860ed495f2889517a3b565#egg=cdisutils',
        'git+ssh://git@github.com/NCI-GDC/gdcdatamodel.git@bb5c90649ed99763f7a76165cf3eaa0b5bd93830#egg=gdcdatamodel',
        'git+ssh://git@github.com/NCI-GDC/python-signpostclient.git@381e41d09dd7a0f9cd5f1ea5abea5bb1f34e9e70#egg=signpostclient',
    ]
)

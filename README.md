Gen3 Data Model
==============

[![Coverage Status](https://coveralls.io/repos/github/uc-cdis/gen3datamodel/badge.svg?branch=chore/update-tests)](https://coveralls.io/github/uc-cdis/gen3datamodel?branch=chore/update-tests)

Repo to keep information about the Gen3 data model design.

# Installation

Use `poetry` to install dependencies:

```
poetry install
```

# Jupyter + Graphviz

It's helpful to examine the relationships between nodes visually.  One
way to do this is to run an Jupyter notebook with a Python2 kernal.
When used with Graphviz's SVG support, you can view a graphical
representation of a subgraph directly in a REPL. To do so, install the
`dev-requirements.txt` dependencies.  There is an example Jupyter
notebook at `examples/jupyter_example.ipynb` (replicated in
`examples/jupyter_example.py` for clarity)

```
pipenv install --dev
PG_USER=* PG_HOST=* PG_DATABASE=* PG_PASSWORD=*   jupyter notebook examples/jupyter_example.ipynb
```


## Documentation

### Visual representation

For instructions on how to build the Graphviz representation of the
datamodel, see the
[docs readme](https://github.com/uc-cdis/gen3datamodel/blob/develop/docs/README.md).


## Dependencies

Before continuing you must have the following programs installed:

- [Python 3.9](http://python.org/)

The gen3datamodel library requires the following pip dependencies

- [avro](https://avro.apache.org/)
- [graphviz](http://www.graphviz.org/)

### Project Dependencies

Project dependencies are managed using [Poetry](https://python-poetry.org/)

# Example validation usage
```
from gen3datamodel import node_avsc_object
from gen3datamodel.mappings import get_participant_es_mapping, get_file_es_mapping
from avro.io import validate
import json


with open('examples/nodes/aliquot_valid.json', 'r') as f:
    node = json.loads(f.read())
print validate(node_avsc_object, node)  # if valid, prints True


print(get_participant_es_mapping())  # Prints participant elasticsearch mapping
print(get_file_es_mapping())         # Prints file elasticsearch mapping
```

# Example Elasticsearch mapping usage
```
from gen3datamodel import mappings
print(mappings.get_file_es_mapping())
print(mappings.get_participant_es_mapping())
```

# Tests

```
bash test/ci_commands_script.sh
```

# Contributing

Read how to contribute [here](https://docs.gen3.org/docs/Contributor%20Guidelines/)

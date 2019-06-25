from dictionaryutils import dictionary as gdcdictionary
from link_validator_parser import create_subgroup_validators


class GDCGraphValidator(object):
    '''
    Validator that validates entities' relationship with existing nodes in
    database.

    '''

    def __init__(self):
        self.schemas = gdcdictionary
        self.required_validators = {
            'links_validator': GDCLinksValidator()
        }
        self.optional_validators = {}

    def record_errors(self, graph, entities):
        for validator in self.required_validators.values():
            validator.validate(entities, graph)

        for entity in entities:
            schema = self.schemas.schema[entity.node.label]
            validators = schema.get('validators')
            if validators:
                for validator_name in validators:
                    self.optional_validators[validator_name].validate()


class GDCNamedLinksValidator(object):
    '''
    First of all, the existence of links in each node is encoded as a bit array. Link has value encoded as 1 and 0 if
        does not have value.
    Each instance of this class have three encoded validators:
    - required:
        Use at-least mask.
        Encodes logic of top-down requires in which parent subgroup require the existence of some children.
        This validation will be checked by operation & between required_mask and bit_array_value
        to ensure at least one bit = 1
    - existing:
        1. encodes logic of bottom-up existence group. If some children of a subgroup have required=True
        while the subgroup itself has required=False. It means that if one of aforementioned children exists, the
        remaining children having required=True in that subgroup must also exist.
        2. it also encodes the logic of the really required links.

        Use exact mask for the existing group
    - exclusive:
        simply a mask with bits representing to considering links equal 0 while bits representing exclusive links
        of those links are 1

    '''
    def __init__(self, node_label):
        self.required_validator, self.existing_list, self.exclusive_list = create_subgroup_validators(node_label)

    def validate(self, entity):
        submit_value = 0
        current_pos = 0
        # iterate all the links, turn on corresponding bit and doing exclusive check
        for leaf in self.exclusive_list:  # Complexity of this for loop is O(n)
            self.validate_multiplicity(entity, leaf, entity.node[leaf.name])
            if len(entity.node[leaf.name]) > 0:
                if submit_value & leaf.exclusive_mask != 0:
                    entity.record_error("Links to {} are exclusive.  More than one was provided."
                                        .format(leaf.exclusive_links), keys=leaf.exclusive_links)
                submit_value |= 1 << current_pos
            current_pos += 1

        # doing required check with at-least mask
        # Complexity of this is O(1)
        if self.required_validator.required_mask != 0 and submit_value & self.required_validator.required_mask == 0:
            entity.record_error("Entity is missing one of required link(s) to {} or groups of {}"
                                .format(self.required_validator.list_required_links,
                                        self.required_validator.group_required),
                                keys=self.required_validator.list_required_links)

        # doing existing checks with exact masks
        for existing in self.existing_list:  # Complexity of this check is O(log n)
            if submit_value & existing.code != 0 and submit_value & existing.existing_mask != existing.existing_mask:
                entity.record_error("Missing one of required link(s) of groups of {}"
                                    .format(existing.existing_links),
                                    keys=existing.existing_links)

    @staticmethod
    def validate_multiplicity(entity, leaf, targets):
        multi = leaf.multiplicity
        if multi in ['many_to_one', 'one_to_one']:
            if len(targets) > 1:
                entity.record_error("'{}' link has to be {}".format(leaf.name, multi), keys=[leaf.name])

        if multi in ['one_to_many', 'one_to_one']:
            for target in targets:
                if len(target[leaf.backref]) > 1:
                    entity.record_error(
                        "'{}' link has to be {}, target node {} already has {}"
                        .format(leaf.name, multi, target.label, leaf.backref),
                        keys=[leaf.name])


class GDCLinksValidator(object):
    '''
    This class have a hash table of validators by name of node. This table caches all necessary link validators
    of a node which belong to four types:
        - required
        - existing
        - exclusive
        - multiplicity.
    The first three types are encoded as bit mask. We only need to build the validators once when the node is
    submitted first time. Later, we just do iterating and perform bit masking operation.
    '''
    def __init__(self):
        self.validators = {}

    def validate(self, entities, graph=None):
        pre_node_label = ''
        validator = None
        for entity in entities:
            node_label = entity.node.label
            if pre_node_label != node_label:
                if node_label not in self.validators:
                    self.validators[node_label] = GDCNamedLinksValidator(node_label)
                validator = self.validators[node_label]
                pre_node_label = node_label
            validator.validate(entity)

    def get_validator(self, node_label):
        if node_label not in self.validators:
            self.validators[node_label] = GDCNamedLinksValidator(node_label)
        return self.validators


class GDCUniqueKeysValidator(object):
    def validate(self, entities, graph=None):
        for entity in entities:
            schema = gdcdictionary.schema[entity.node.label]
            node = entity.node
            for keys in schema['uniqueKeys']:
                props = {}
                if keys == ['id']:
                    continue
                for key in keys:
                    prop = schema['properties'][key].get('systemAlias')
                    if prop:
                        props[prop] = node[prop]
                    else:
                        props[key] = node[key]
                if graph.nodes(type(node)).props(props).count() > 1:
                    entity.record_error(
                        '{} with {} already exists in the GDC'
                            .format(node.label, props), keys=props.keys()
                    )

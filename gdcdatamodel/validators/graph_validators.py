from dictionaryutils import dictionary as gdcdictionary
from collections import deque


class GDCGraphValidator(object):
    '''
    Validator that validates entities' relationship with existing nodes in
    database.

    '''

    def __init__(self):
        self.schemas = gdcdictionary
        self.required_validators = {
            'links_validator': GDCLinksValidator(),
            'uniqueKeys_validator': GDCUniqueKeysValidator(),
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


class SubgroupParsingNode(object):
    def __init__(self, parent, schema, code=None):
        self.parent = parent
        self.schema = schema
        self.code = code
        self.name = schema.get('name') if 'name' in schema else None
        self.required = schema.get('required', False)
        self.exclusive = schema.get('exclusive', False)
        self.required_links = []
        self.existing_mask = None
        self.existing_links = []
        self.exclusive_mask = 0
        self.exclusive_links = []
        self.all_ancestors_required = parent.all_ancestors_required and parent.required \
            if parent is not None else self.required
        self.all_ancestors_inclusive = parent.all_ancestors_inclusive and not parent.exclusive \
            if parent is not None else not self.exclusive

    def update_existing_mask(self, current, parent, child, update_mask_should_fix):
        parent.existing_mask = current.existing_mask if parent.existing_mask is None \
            else parent.existing_mask | current.existing_mask
        parent.existing_links.append(child.name)
        current.existing_mask = None
        current.existing_links = []
        if not parent.required:
            update_mask_should_fix = False
        return update_mask_should_fix

    def update_exclusive_mask(self, link):
        stack = []
        current = link
        while current.parent and not current.all_ancestors_inclusive:
            parent = current.parent
            if parent.exclusive:
                parent.exclusive_mask |= link.code
                parent.exclusive_links.append(link.name)
            stack.append(current)
            current = parent

        while len(stack) > 0:
            parent = current
            current = stack.pop()
            if parent.exclusive:
                current.exclusive_mask = parent.exclusive_mask ^ current.code
            else:
                current.exclusive_mask = parent.exclusive_mask
            current.exclusive_links = parent.exclusive_links

    def update_parent(self, child):
        update_mask_should_fix = child.required
        self.code = child.code if self.code is None else self.code | child.code
        if update_mask_should_fix:
            self.existing_mask = child.code if self.existing_mask is None else self.existing_mask | child.code
            self.existing_links.append(child.name)

        current_sg = self
        if not current_sg.required:
            update_mask_should_fix = False
        if current_sg.required:
            current_sg.required_links.append(child.name)

        while current_sg is not None:
            parent = current_sg.parent
            if parent is not None:
                if update_mask_should_fix:
                    update_mask_should_fix = self.update_existing_mask(current_sg, parent, child, update_mask_should_fix)
                parent.code = current_sg.code if parent.code is None else parent.code | current_sg.code
                if parent.required:
                    parent.required_links.append(child.name)
            current_sg = parent
        self.update_exclusive_mask(child)

    def add_child_link(self, child):
        self.update_parent(child)


class LinkWithExclusiveMask(object):
    def __init__(self, item):
        self.name = item.name
        self.exclusive_mask = item.exclusive_mask
        self.exclusive_links = item.exclusive_links
        self.multiplicity = item.schema.get('multiplicity')
        self.back_ref = item.schema.get('backref')


class ExistingMasks(object):
    def __init__(self, code, existing_mask, existing_links):
        self.code = code
        self.existing_mask = existing_mask
        self.existing_links = existing_links


class RequiredMask(object):
    def __init__(self):
        self.list_required_links = []
        self.group_required = []
        self.required_mask = 0


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
        self.required_validator, self.existing_list, self.exclusive_list = self.create_subgroup_validators(node_label)

    @staticmethod
    def create_subgroup_validators(node_label):
        link_items = []
        leaves = []
        for link in gdcdictionary.schema[node_label]['links']:
            if 'name' in link:
                l_item = SubgroupParsingNode(None, link, 1 << len(leaves))
                leaves.append(l_item)
            else:
                l_item = SubgroupParsingNode(None, link)
            link_items.append(l_item)

        return GDCNamedLinksValidator.build_tree_of_link_items(link_items, leaves)

    @staticmethod
    def build_tree_of_link_items(link_items, leaves):
        final_required = []
        current_pos = 0
        while current_pos < len(link_items):
            l_item = link_items[current_pos]
            children_required_count = 0
            if 'subgroup' in l_item.schema:
                for link in l_item.schema['subgroup']:
                    if 'subgroup' in link:
                        new_l_item = SubgroupParsingNode(l_item, link)
                    else:
                        new_l_item = SubgroupParsingNode(l_item, link, 1 << len(leaves))
                        l_item.add_child_link(new_l_item)
                        leaves.append(new_l_item)

                    link_items.append(new_l_item)

                    if l_item.required and new_l_item.required:
                        children_required_count += 1
            if l_item.all_ancestors_required and l_item.required and children_required_count == 0:
                final_required.append(l_item)
            current_pos += 1

        required_validator, base_mask = GDCNamedLinksValidator.create_required_mask(final_required)
        existing_list = GDCNamedLinksValidator.create_existing_list(link_items, base_mask)
        exclusive_list = GDCNamedLinksValidator.create_exclusive_list(leaves)

        return required_validator, existing_list, exclusive_list

    @staticmethod
    def create_exclusive_list(leaves):
        if len(leaves) == 0:
            return []

        current = leaves[len(leaves) - 1]
        leaves_checks = deque([LinkWithExclusiveMask(current)])
        i = len(leaves) - 2
        while i >= 0:
            leaf = leaves[i]
            if leaf.parent == current.parent:
                leaf.exclusive_links = current.exclusive_links
            else:
                current = leaf
            leaves_checks.appendleft(LinkWithExclusiveMask(leaf))
            i -= 1
        return list(leaves_checks)

    @staticmethod
    def create_existing_list(link_items, base_mask):
        existing_masks = []
        for item in link_items:
            if item.existing_mask is not None:
                existing_masks.append(ExistingMasks(item.code, item.existing_mask | base_mask,
                                                    item.existing_links))
        return existing_masks

    @staticmethod
    def create_required_mask(final_required):
        res = RequiredMask()
        base_mask = 0
        for item in final_required:
            res.required_mask |= item.code
            if item.name is not None:
                res.list_required_links.append(item.name)
                base_mask |= item.code  # if the require is True from the root to the leaf, this leaf is really required
            else:
                res.group_required.extend(item.required_links)
        return res, base_mask

    def validate(self, entity):
        coded_format = 0
        current_pos = 0
        # iterate all the links, turn on corresponding bit and doing exclusive check
        for leaf in self.exclusive_list:
            targets = entity.node[leaf.name]
            self.validate_multiplicity(entity, leaf, targets)
            if len(targets) > 0:
                if coded_format & leaf.exclusive_mask != 0:
                    entity.record_error("Links to {} are exclusive.  More than one was provided."
                                        .format(leaf.exclusive_links), keys=leaf.exclusive_links)
                coded_format |= 1 << current_pos
            current_pos += 1

        # doing required check with at-least mask
        if coded_format & self.required_validator.required_mask == 0:
            entity.record_error("Entity is missing one of required link(s) to {} or groups of {}"
                                .format(self.required_validator.list_required_links,
                                        self.required_validator.group_required),
                                keys=self.required_validator.list_required_links)

        # doing existing checks with exact masks
        for existing in self.existing_list:
            if coded_format & existing.code != 0 and coded_format & existing.existing_mask != existing.existing_mask:
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
        node_label = entities[0].node.label
        if node_label not in self.validators:
            self.validators[node_label] = GDCNamedLinksValidator(node_label)
        for entity in entities:
            self.validators[node_label].validate(entity)

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

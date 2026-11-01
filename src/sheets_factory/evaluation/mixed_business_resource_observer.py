"""Observe real roles for retained and paired tasks without changing old runs."""
from __future__ import annotations

import ast
from collections import Counter
import hashlib
from pathlib import Path
from . import resource_observer as original
from .mixed_business_resources import load_runtime_profile

ORIGINAL_SHA = 'f4c4e08cae274551ec6cfa5c31b2efcd70b7352e7d90d2f8e9ccfc67300fa456'
if hashlib.sha256(Path(original.__file__).read_bytes()).hexdigest() != ORIGINAL_SHA:
    raise ValueError('The frozen actual-resource observer changed')


def adapted_ast():
    tree = ast.parse(Path(original.__file__).read_text()); counts = Counter()
    class Adapt(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.level == 2 and node.module == 'workbook.resource_engine':
                if [(x.name,x.asname) for x in node.names] != [('load_runtime_profile',None)]:
                    raise ValueError('The explicit observer profile seam changed')
                counts['loader'] += 1; return None
            if node.level == 1 and node.module == 'resource_harbor':
                if [(x.name,x.asname) for x in node.names] != [('inspect_resource_export',None)]:
                    raise ValueError('The internal observed-export inspector seam changed')
                counts['inspector'] += 1; node.module = 'mixed_business_resources'
            return node
        def visit_Compare(self, node):
            if ast.unparse(node) == "profile['id'] == 'entity_group_large_v2'":
                counts['identity'] += 1
                return ast.copy_location(ast.parse("profile['id'] in ('entity_group_large_v2','ringfenced_pair_source_v1')",mode='eval').body,node)
            return self.generic_visit(node)
    tree = Adapt().visit(tree)
    if counts != Counter(loader=1,inspector=1,identity=1):
        raise ValueError('The three mixed-family resource seams changed: '+str(counts))
    return ast.fix_missing_locations(tree)


_namespace = {'__name__': __name__, '__file__': __file__, '__package__': __package__,
              'load_runtime_profile': load_runtime_profile}
exec(compile(adapted_ast(), __file__, 'exec'), _namespace)
ResourceObserver = _namespace['ResourceObserver']
validate_trial_observations = _namespace['validate_trial_observations']
validate_observation_receipt = _namespace['validate_observation_receipt']

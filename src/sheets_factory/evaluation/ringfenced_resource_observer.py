"""Unchanged actual-resource observation with the declared ring-fenced profile."""
from __future__ import annotations
import ast
import hashlib
from pathlib import Path
from . import resource_observer as original
from .ringfenced_resource_harbor import load_runtime_profile

ORIGINAL_SHA = 'f4c4e08cae274551ec6cfa5c31b2efcd70b7352e7d90d2f8e9ccfc67300fa456'
if hashlib.sha256(Path(original.__file__).read_bytes()).hexdigest()!=ORIGINAL_SHA:
    raise ValueError('The original actual-resource observer changed')
tree=ast.parse(Path(original.__file__).read_text(),filename=original.__file__)
removed=0
for node in tuple(tree.body):
    if isinstance(node,ast.ImportFrom) and node.module=='workbook.resource_engine' and node.level==2:
        if [(x.name,x.asname) for x in node.names]!=[('load_runtime_profile',None)]:
            raise ValueError('The original observer profile import changed')
        tree.body.remove(node);removed+=1
if removed!=1:
    raise ValueError('The exact observer profile seam changed')
identities=0
class ProfileIdentity(ast.NodeTransformer):
    def visit_Constant(self,node):
        global identities
        if node.value=='entity_group_large_v2':
            identities+=1
            return ast.copy_location(ast.Constant('ringfenced_pair_source_v1'),node)
        return node
tree=ProfileIdentity().visit(tree)
if identities!=1:
    raise ValueError('The exact observed-family identity seam changed')
_namespace={'__name__':__name__,'__file__':__file__,'__package__':__package__,
            'load_runtime_profile':load_runtime_profile}
exec(compile(ast.fix_missing_locations(tree),__file__,'exec'),_namespace)
ResourceObserver=_namespace['ResourceObserver']
validate_observation_receipt=_namespace['validate_observation_receipt']

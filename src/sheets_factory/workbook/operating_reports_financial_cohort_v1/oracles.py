"""Reuse each frozen independent implementation in a fresh private namespace."""
from __future__ import annotations

import ast
from copy import deepcopy

from . import schema as s


def _namespace(implementation,seed):
    source=s.checked_source('oracle_'+implementation);tree=ast.parse(source.read_bytes())
    alias='s' if implementation=='A' else 'schema'
    imports=[node for node in tree.body if isinstance(node,ast.ImportFrom) and node.level==1
        and node.module is None and [(v.name,v.asname) for v in node.names]==[('schema','s' if implementation=='A' else None)]]
    if len(imports)!=1:raise ValueError('The frozen independent oracle schema import changed')
    tree.body.remove(imports[0]);namespace={'__file__':str(source),'__name__':'_private_cohort_oracle_'+implementation,
        alias:s.for_seed(seed)}
    exec(compile(ast.fix_missing_locations(tree),str(source),'exec'),namespace)
    return namespace


def _solve(implementation,public,raw_inventory):
    s.validate_spec(public)
    if public['dimension_mode']=='production':
        if raw_inventory is None:raise ValueError('Freeze the complete nine-case raw inventory before any production financial forward')
        from .raw import validate_all
        all_raw=validate_all(raw_inventory)['specifications'];entry=s.candidate(public['seed'])
        if public!=all_raw[entry['candidate_id']]:raise ValueError('The financial input is not the exact corresponding frozen raw specification')
    elif raw_inventory is not None:
        raise ValueError('A toy financial test cannot claim the production raw inventory')
    before=deepcopy(public)
    result=_namespace(implementation,public['seed'])['solve'](public)
    if public!=before:raise ValueError('A frozen financial implementation mutated the public specification')
    return s.validate_result(public,result)


def solve_A(public,*,raw_inventory=None):
    return _solve('A',public,raw_inventory)


def solve_B(public,*,raw_inventory=None):
    return _solve('B',public,raw_inventory)

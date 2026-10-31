#!/usr/bin/env python3
"""Isolated API-v3 diagnostic-export compatibility with two retained failures."""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

V2_PATH=_Path(__file__).with_name('run_linear_capital_scaled_highs_screen_api_v2.py')
V2_SHA256='36e4ffe9b4fa2c1160e876756ae93b9cd25320b210331d9822e9fabc096208c4'
FAILURES=(
    ('outputs/research/linear_scaled_P01_highs_screen_prepared_20261031T125838Z/actual_tiny_failure_diagnostic.json',
     'aa7c63c8757c01f3f452663ed19a6b5064e603d0841d4f9e37aea5ea9aec655f'),
    ('outputs/research/linear_scaled_P01_highs_screen_api_v2_prepared_20261031T131042Z/actual_api_v2_tiny_failure_diagnostic.json',
     '71ab8e32d06dda40fde8374f25617421becaa7904f742da2bf6ec3154a871afe'))


def adapted_ast():
    raw=V2_PATH.read_bytes()
    if V2_PATH!=V2_PATH.resolve() or _hashlib.sha256(raw).hexdigest()!=V2_SHA256:
        raise ValueError('The frozen API-v2 screen driver changed')
    # Reuse only its exact AST constructor in an isolated support namespace.
    parent=_ast.parse(raw,filename=str(V2_PATH))
    functions=[node for node in parent.body if isinstance(node,_ast.FunctionDef) and node.name=='adapted_ast']
    if len(functions)!=1:raise ValueError('The frozen API-v2 AST constructor changed')
    namespace={'_ast':_ast,'_hashlib':_hashlib,'ADAPTER_UPSTREAM':V2_PATH.with_name('run_linear_capital_scaled_highs_screen.py'),
        'ADAPTER_UPSTREAM_SHA256':'563f2b0a1f9f3910421a40bdb30476a39a643c2cb0b61967d0257fdf6d04c7b1'}
    exec(compile(_ast.Module(body=functions,type_ignores=[]),str(V2_PATH),'exec'),namespace)
    tree=namespace['adapted_ast']();counts={'imports':0,'kinds':0,'versions':0,'gates':0,'lineage':0}
    class Identity(_ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            if node.module=='sheets_factory.workbook.linear_capital_scaled':
                for alias in node.names:
                    if alias.name in ('highs_runtime_api_v2','highs_engineering_api_v2'):
                        alias.name=alias.name.removesuffix('_v2')+'_v3';counts['imports']+=1
            return node
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in ('fixed_L360_P01_scaled_highs2_early_answer_engineering_api_v2',
                'fixed_scaled_highs2_three_project_api_smoke_api_v2'):
                node.value=node.value.removesuffix('_v2')+'_v3';counts['kinds']+=1
            elif node.value=='api_compatibility_parent_failure':
                node.value='api_compatibility_parent_failures';counts['lineage']+=1
            return node
        def visit_FunctionDef(self,node):
            node=self.generic_visit(node)
            if node.name in ('prepare','prepare_tiny','execute_prepared','execute_tiny'):
                for item in _ast.walk(node):
                    if isinstance(item,_ast.Dict):
                        keys={key.value:i for i,key in enumerate(item.keys) if isinstance(key,_ast.Constant)}
                        if 'version' in keys and 'kind' in keys:
                            value=item.values[keys['version']]
                            if not isinstance(value,_ast.Constant) or value.value!=2:raise ValueError('The API-v2 screen envelope changed')
                            value.value=3;counts['versions']+=1
            elif node.name in ('_checked_prospective','checked_tiny_prospective'):
                for item in _ast.walk(node):
                    if isinstance(item,_ast.Compare) and _ast.unparse(item)=="frozen['version'] == 2":
                        item.comparators[0]=_ast.Constant(3);counts['gates']+=1
            return node
    tree=Identity().visit(tree)
    if counts!={'imports':2,'kinds':2,'versions':4,'gates':2,'lineage':6}:raise ValueError('The exact API-v3 screen identities changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(),__file__,'exec'),globals())
_base_recipes=recipes


def _prior_failure():
    records=[]
    for path,expected in FAILURES:
        record=reference(ROOT/path);require(record['sha256']==expected,'An immutable prior HiGHS API failure changed')
        data=read(record);require(data['owned_cleanup_passed'] is True,'A prior API attempt lacks owned cleanup')
        records.append(record)
    first,second=map(read,records)
    require(first['native_api_attempts']==1 and first['native_run_reached'] is False and first['P01_started'] is False
        and second['cumulative_lineage_native_Highs_instances']==2 and second['cumulative_lineage_native_run_calls']==0
        and second['cumulative_lineage_optimizer_searches']==0 and second['both_P01_versions_unstarted'] is True,
        'The two-instance/zero-search prior failure accounting changed')
    return records


def recipes():
    adapted_ast();highs_runtime.adapted_ast()
    files=(V2_PATH,V2_PATH.with_name('run_linear_capital_scaled_highs_screen.py'),highs_runtime.V2_PATH,
        highs_runtime.ADAPTER_UPSTREAM,highs_engineering.api_v2_path(),highs_engineering.upstream_path())
    return {**_base_recipes(),**{str(path.resolve()):reference(path) for path in files}}


if __name__=='__main__':raise SystemExit(main())

#!/usr/bin/env python3
"""Prepare or explicitly run the isolated HiGHS objective-sense API-v2 route."""
from __future__ import annotations

import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

ADAPTER_UPSTREAM = _Path(__file__).with_name('run_linear_capital_scaled_highs_screen.py')
ADAPTER_UPSTREAM_SHA256 = '563f2b0a1f9f3910421a40bdb30476a39a643c2cb0b61967d0257fdf6d04c7b1'
FAILURE_PATH = _Path(__file__).resolve().parents[1]/'outputs/research/linear_scaled_P01_highs_screen_prepared_20261031T125838Z/actual_tiny_failure_diagnostic.json'
FAILURE_SHA256 = 'aa7c63c8757c01f3f452663ed19a6b5064e603d0841d4f9e37aea5ea9aec655f'


def adapted_ast():
    raw=ADAPTER_UPSTREAM.read_bytes()
    if ADAPTER_UPSTREAM!=ADAPTER_UPSTREAM.resolve() or _hashlib.sha256(raw).hexdigest()!=ADAPTER_UPSTREAM_SHA256:
        raise ValueError('The frozen pre-API-v2 screen driver changed')
    tree=_ast.parse(raw,filename=str(ADAPTER_UPSTREAM));counts={}
    def changed(key):counts[key]=counts.get(key,0)+1
    identities={'fixed_L360_P01_scaled_highs2_early_answer_engineering':'fixed_L360_P01_scaled_highs2_early_answer_engineering_api_v2',
        'fixed_scaled_highs2_three_project_api_smoke':'fixed_scaled_highs2_three_project_api_smoke_api_v2'}
    class API(_ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            if node.module=='sheets_factory.workbook.linear_capital_scaled':
                for alias in node.names:
                    if alias.name in ('highs_runtime','highs_engineering'):
                        before=alias.name;alias.name=before+'_api_v2';alias.asname=before;changed(before)
            return node
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in identities:
                before=node.value;node.value=identities[before];changed(before)
            return node
        def visit_FunctionDef(self,node):
            node=self.generic_visit(node)
            if node.name in ('prepare','prepare_tiny','execute_prepared','execute_tiny'):
                for item in _ast.walk(node):
                    if isinstance(item,_ast.Dict):
                        keys={key.value:i for i,key in enumerate(item.keys) if isinstance(key,_ast.Constant)}
                        if 'version' in keys and 'kind' in keys:
                            value=item.values[keys['version']]
                            if not isinstance(value,_ast.Constant) or value.value!=1:raise ValueError('The screen version envelope changed')
                            value.value=2;changed('envelopes')
                            item.keys.append(_ast.Constant('api_compatibility_parent_failure'))
                            item.values.append(_ast.parse('_prior_failure()',mode='eval').body);changed('lineage')
            elif node.name in ('_checked_prospective','checked_tiny_prospective'):
                for item in _ast.walk(node):
                    if isinstance(item,_ast.Compare) and _ast.unparse(item)=="frozen['version'] == 1":
                        item.comparators[0]=_ast.Constant(2);changed('version_gates')
                node.body.insert(0,_ast.parse("require(read(Path(output)/'prospective.json')['api_compatibility_parent_failure']==_prior_failure(), 'The original concrete API failure lineage changed')").body[0])
            return node
    tree.body=[node for node in tree.body if not (isinstance(node,_ast.If)
        and _ast.dump(node.test)==_ast.dump(_ast.parse("__name__ == '__main__'",mode='eval').body))]
    tree=API().visit(tree)
    expected={key:1 for key in identities};expected.update(highs_runtime=1,highs_engineering=1,envelopes=4,lineage=4,version_gates=2)
    if counts!=expected:raise ValueError('The exact API-v2 screen substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(),__file__,'exec'),globals())
_base_recipes=recipes


def _prior_failure():
    record=reference(FAILURE_PATH)
    require(record['sha256']==FAILURE_SHA256,'The retained original HiGHS API failure diagnostic changed')
    data=read(record)
    require(data['native_api_attempts']==1 and data['native_run_reached'] is False
        and data['P01_started'] is False and data['owned_cleanup_passed'] is True,
        'The original failure count or no-search boundary changed')
    return record


def recipes():
    adapted_ast();highs_runtime.adapted_ast()
    files=(ADAPTER_UPSTREAM,highs_runtime.ADAPTER_UPSTREAM,Path(highs_engineering.__file__),
        highs_engineering.upstream_path())
    return {**_base_recipes(),**{str(path.resolve()):reference(path) for path in files}}


if __name__=='__main__':raise SystemExit(main())

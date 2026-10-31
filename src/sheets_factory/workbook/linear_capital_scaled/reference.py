"""N360 producer16 best and complete-winner-excluded runner reference.

Two independent complete financial universes and integer matrices are required.
The original CP-SAT OPTIMAL, exact-primal, positive runner-gap, resource and
cleanup gates remain. An engineering incumbent or float gap cannot admit this
reference. All execution is behind a separate explicit execute_prepared call.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import time

from . import spec, finance as finance_crosscheck, optimization_runtime as runtime

ROOT=Path(__file__).resolve().parents[4]
UPSTREAM_PRODUCER_SHA256='7e0610ee7f4665b808da6d37b23c45cd3e1f57d3d525c991d4b8ae81df22bd80'
FINANCE_KIND='linear_capital_scaled_full_financial_crosscheck'
KIND='linear_capital_scaled_producer16_best_runner_dual_financial_reference'
PREPARED='prepared_linear_capital_scaled_producer16_best_runner_dual_financial_reference'
TIME_LIMIT=3600
BACKENDS={'A':'scip','B':'cp_sat'}
require=spec.require


def _upstream():
    path=ROOT/'scripts/run_linear_capital_producer_reference.py';raw=path.read_bytes()
    require(hashlib.sha256(raw).hexdigest()==UPSTREAM_PRODUCER_SHA256,
        'The frozen producer best/runner orchestration changed')
    return path,raw


def _gate_ast():
    path,_=_upstream()
    descriptor=importlib.util.spec_from_file_location('_scaled_frozen_reference_gates',path)
    original=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(original)
    tree=original.validation_ast()
    tree.body=[node for node in tree.body if node.name!='_checked_finance']
    counts={'version':0,'name':0}
    class Adapt(ast.NodeTransformer):
        def visit_Compare(self,node):
            if ast.unparse(node) in ("frozen['version'] == 1","value['version'] == 1"):
                node.comparators[0]=ast.Constant(2);counts['version']+=1
            return self.generic_visit(node)
        def visit_Constant(self,node):
            if node.value=='/sf-producer16-integer-':
                node.value='/sf-scaled-producer16-integer-';counts['name']+=1
            return node
    tree=Adapt().visit(tree)
    require(counts=={'version':2,'name':1},'The exact N360 reference receipt gates changed')
    return ast.fix_missing_locations(tree)


exec(compile(_gate_ast(),__file__,'exec'),globals())


def finance_recipes():
    """Exact independent code closure for a new completed finance envelope."""
    folder=Path(__file__).parent;old=folder.parent/'linear_capital_portfolio'
    paths=[folder/name for name in ('spec.py','finance.py','model_a.py','model_b.py')]
    paths += [old/name for name in ('spec.py','candidate_a.py','ledger.py','finance_crosscheck.py','model_a.py','model_b.py')]
    return {str(path):reference(path) for path in paths}


def _checked_finance(value):
    """Cold full-scope checks; no financial reconstruction or solver execution."""
    record=reference(value) if isinstance(value,(str,Path)) else value
    envelope=read(record)
    require(envelope.get('kind')==FINANCE_KIND and type(envelope.get('version')) is int
        and envelope['version']==2 and envelope.get('passed') is True
        and envelope.get('qualified') is False and envelope.get('recipe')==finance_recipes()
        and all(type(envelope.get(k)) is int and envelope[k]==0 for k in ('optimizer_calls','LO_calls','model_calls')),
        'A genuine completed new-scope finance envelope with zero solver/model/LO calls is required')
    _refs(envelope)
    # A new finance driver may retain the original explicit records transport.
    # The values remain exact references and every original entry is retained.
    records=envelope.get('records',{})
    for field,legacy_name in {'universe_A':'Fraction_A_universe','universe_B':'Decimal_B_universe',
            'model_A':'model_A','model_B':'model_B','complete_financial_comparison':'complete_financial_comparison',
            'all_predeclared_plan_comparison':'all_predeclared_plan_comparison',
            'complete_matrix_comparison':'complete_matrix_comparison'}.items():
        if field not in envelope and legacy_name in records:envelope[field]=records[legacy_name]
    public=spec.load_spec(read(envelope['specification']))
    require(public['dimension_mode']=='production' and len(public['project_ids'])==360
        and spec.expected_constraint_count(public)==941,'The complete N360 public universe is required')
    raw=read(envelope['raw_preparation'])
    require(raw.get('specification')==envelope['specification']
        and raw.get('specification_sha256')==spec.canonical_sha256(public),
        'The complete new raw preparation/specification binding changed')
    a,b=read(envelope['universe_A']),read(envelope['universe_B'])
    comparison=finance_crosscheck.compare_universes(public,a,b)
    require(comparison['passed'] is True and comparison==read(envelope['complete_financial_comparison']),
        'The complete Fraction/Decimal financial scope differs')
    diagnostics=raw.get('diagnostic_plans')
    require(isinstance(diagnostics,list) and bool(diagnostics),'The predeclared diagnostic plan inventory is required')
    plans=finance_crosscheck.compare_plans(public,a,b,diagnostics)
    require(plans['passed'] is True and plans==read(envelope['all_predeclared_plan_comparison']),
        'The complete predeclared diagnostic plan comparison differs')
    models={side:envelope['model_'+side] for side in BACKENDS}
    values={side:read(record) for side,record in models.items()}
    for side,universe in (('A',a),('B',b)):
        model=runtime.validate_model(values[side])
        require(len(model['project_ids'])==360 and len(model['rows'])==941
            and model['specification_sha256']==spec.canonical_sha256(public)
            and model['universe_sha256']==_sha(universe),'A new matrix lacks its complete financial ancestry')
    common=('kind','version','project_ids','objective_pence','rows','specification_sha256')
    require(all(values['A'][key]==values['B'][key] for key in common)
        and read(envelope['complete_matrix_comparison']).get('passed') is True,
        'The complete independently constructed N360 integer matrices differ')
    return {'terminal':record,'raw_preparation':envelope['raw_preparation'],
        'specification':envelope['specification'],'public':public,'A':a,'B':b,
        'universe_A':envelope['universe_A'],'universe_B':envelope['universe_B'],
        'models':models,'model_values':values}


def adapted_ast():
    """Retain the exact outer best/runner lifecycle in a new v2 namespace."""
    path,raw=_upstream();tree=ast.parse(raw,filename=str(path))
    wanted={'_profile','prepare','validate_prepared','_checked_job','_financial',
        'execute_prepared','validate_completed','main'}
    tree.body=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in wanted]
    require({node.name for node in tree.body}==wanted,'A frozen best/runner lifecycle function is missing')
    counts={'version_guard':0,'version_envelope':0,'density_bounds':0,'density_dict':0,'row_count':0}
    class Adapt(ast.NodeTransformer):
        def visit_Compare(self,node):
            text=ast.unparse(node)
            if text in ("frozen['version'] == 1","result['version'] == 1"):
                node.comparators[0]=ast.Constant(2);counts['version_guard']+=1
            elif text in ('80 <= selected <= 160','80 <= sum(winner.values()) <= 160'):
                node.left=ast.Constant(120);node.comparators[-1]=ast.Constant(240);counts['density_bounds']+=1
            elif text=="row['exact_matrix_plan_check']['all_integer_rows_checked'] == 881":
                node.comparators[0]=ast.Constant(941);counts['row_count']+=1
            return self.generic_visit(node)
        def visit_Dict(self,node):
            keys={key.value:i for i,key in enumerate(node.keys) if isinstance(key,ast.Constant)}
            if {'minimum','maximum','public_cardinality_constraint'}<=keys.keys():
                require(node.values[keys['minimum']].value==80 and node.values[keys['maximum']].value==160,
                    'The frozen density declaration changed')
                node.values[keys['minimum']]=ast.Constant(120);node.values[keys['maximum']]=ast.Constant(240)
                counts['density_dict']+=1
            if 'kind' in keys and 'version' in keys and isinstance(node.values[keys['kind']],ast.Name):
                if node.values[keys['kind']].id in {'KIND','PREPARED'}:
                    require(node.values[keys['version']].value==1,'The frozen outer envelope changed')
                    node.values[keys['version']]=ast.Constant(2);counts['version_envelope']+=1
            return self.generic_visit(node)
        def visit_Constant(self,node):
            if isinstance(node.value,str) and '881-row' in node.value:
                node.value=node.value.replace('881-row','941-row')
            return node
    tree=Adapt().visit(tree)
    expected={'version_guard':2,'version_envelope':2,'density_bounds':2,'density_dict':2,'row_count':1}
    require(counts==expected,'The exact N360 best/runner substitutions changed: '+str(counts))
    return ast.fix_missing_locations(tree)


exec(compile(adapted_ast(),__file__,'exec'),globals())


def recipes():
    paths=[Path(__file__),ROOT/'scripts/run_linear_capital_scaled_reference.py',
        ROOT/'scripts/run_linear_capital_producer_reference.py',ROOT/'scripts/run_linear_capital_reference.py',
        Path(runtime.__file__),runtime.PROFILE,Path(spec.__file__),Path(finance_crosscheck.__file__),
        *runtime._source_files().values()]
    return {str(path):reference(path) for path in paths}

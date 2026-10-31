"""Isolated N360 matrix-only producer16 lifecycle over the frozen runtime.

Only the new matrix identity, complete dimension census, source closure and
owned names change. The original image, vendor bytes, 16 CPU / 32 GiB resources,
3600-second CP-SAT attempt, exact primal checks and owned cleanup are retained.
Importing or preparing this module starts no solver, Docker, finance or model.
"""
from __future__ import annotations

import ast as _ast
from collections import Counter as _Counter
import hashlib as _hashlib
from pathlib import Path as _Path

from ..linear_capital_portfolio.producer_optimization_runtime import (
    adapted_ast as _producer_ast, profile_reference as _resource_profile_reference, PROFILE)
from . import spec as _scaled_spec

MODEL_KIND = 'linear_capital_scaled_direct_binary_integer_model'
MODEL_VERSION = 2
SOURCE_NAMES = ('spec.py', 'model_a.py', 'model_b.py', 'frozen_spec.py',
    'frozen_model_a.py', 'frozen_model_b.py')
FROZEN_PRODUCER_SHA256 = '13958fd26b9b0318a04601fefc8c7b52f8df9fc64bb3f27100158eb26a6d4222'


def _frozen_dependencies():
    folder=_Path(__file__).resolve().parent.parent/'linear_capital_portfolio'
    for name,digest in {'producer_optimization_runtime.py':FROZEN_PRODUCER_SHA256,
            'optimization_runtime.py':'fb1031c555fed919830a1f05fdb95bfa8912d2116fd6904801cfaba131a948ea'}.items():
        if _hashlib.sha256((folder/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('A frozen N360 runtime dependency changed')


def profile_reference():
    _frozen_dependencies()
    return _resource_profile_reference()


def _producer_source_files():
    _frozen_dependencies()
    folder = _Path(__file__).resolve().parent
    old = folder.parent/'linear_capital_portfolio'
    return {**{name: _real(folder/name) for name in ('spec.py','model_a.py','model_b.py')},
        **{'frozen_'+name: _real(old/name) for name in ('spec.py','model_a.py','model_b.py')}}


def _complete_scaled_dimension(model):
    count = len(model['project_ids'])
    _require(count in (1,2,3,4,360), 'Only complete N360 production or explicit tiny fixtures are permitted')
    if count == 360:
        _require(len(model['rows']) == _scaled_spec.PRODUCTION_ROW_COUNT
            and _Counter(row['family'] for row in model['rows']) == _scaled_spec.PRODUCTION_COUNTS,
            'Every original N360 business row and complete family census is required')
    return model


def adapted_ast():
    _frozen_dependencies()
    tree = _producer_ast(); counts = {}
    def changed(name): counts[name] = counts.get(name,0)+1
    class Adapt(_ast.NodeTransformer):
        def visit_Assign(self,node):
            names={target.id for target in node.targets if isinstance(target,_ast.Name)}
            if 'PREPARATION_KIND' in names:
                node.value=_ast.Constant('prepared_private_linear_capital_scaled_producer16_solver');changed('prepared_kind')
            elif 'TERMINAL_KIND' in names:
                node.value=_ast.Constant('private_linear_capital_scaled_producer16_solver_execution');changed('terminal_kind')
            elif 'CODE_FILES' in names:
                node.value=_ast.parse(repr(SOURCE_NAMES),mode='eval').body;changed('code_files')
            return self.generic_visit(node)
        def visit_FunctionDef(self,node):
            if node.name=='validate_model':
                class Matrix(_ast.NodeTransformer):
                    def visit_Constant(self,item):
                        if item.value=='linear_capital_portfolio_direct_binary_integer_model':
                            item.value=MODEL_KIND;changed('model_kind')
                        return item
                    def visit_Compare(self,item):
                        source=_ast.unparse(item)
                        if source=="model['version'] == 1":
                            item.comparators[0]=_ast.Constant(2);changed('model_version')
                        elif source=='1 <= len(ids) <= 240':
                            item.comparators[-1]=_ast.Constant(360);changed('project_ceiling')
                        return self.generic_visit(item)
                    def visit_Return(self,item):
                        if isinstance(item.value,_ast.Name) and item.value.id=='model':
                            item.value=_ast.Call(func=_ast.Name(id='_complete_scaled_dimension',ctx=_ast.Load()),args=[item.value],keywords=[])
                            changed('complete_census')
                        return item
                return Matrix().visit(node)
            if node.name=='validate_prepared':
                class Version(_ast.NodeTransformer):
                    def visit_Compare(self,item):
                        if _ast.unparse(item)=="frozen.get('version') == 1":
                            item.comparators[0]=_ast.Constant(2);changed('prepared_version_guard')
                        return self.generic_visit(item)
                node=Version().visit(node)
            if node.name in {'prepare','execute_prepared'}:
                class Envelope(_ast.NodeTransformer):
                    def visit_Dict(self,item):
                        keys={key.value:i for i,key in enumerate(item.keys) if isinstance(key,_ast.Constant)}
                        marker='prepared_at' if node.name=='prepare' else 'requested_resources'
                        if marker in keys and 'version' in keys:
                            if not (isinstance(item.values[keys['version']],_ast.Constant)
                                    and item.values[keys['version']].value==1):
                                raise ValueError('The frozen runtime envelope changed')
                            item.values[keys['version']]=_ast.Constant(2);changed(node.name+'_version')
                        return self.generic_visit(item)
                node=Envelope().visit(node)
            return self.generic_visit(node)
        def visit_Constant(self,node):
            if isinstance(node.value,str) and 'sf-producer16-integer-' in node.value:
                node.value=node.value.replace('sf-producer16-integer-','sf-scaled-producer16-integer-');changed('owned_name')
            return node
    tree=Adapt().visit(tree)
    expected={'prepared_kind':1,'terminal_kind':1,'code_files':1,'model_kind':1,'model_version':1,
        'project_ceiling':1,'complete_census':1,'prepared_version_guard':1,
        'prepare_version':1,'execute_prepared_version':1,'owned_name':2}
    if counts!=expected:raise ValueError('The exact N360 runtime substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


# This namespace has no mutation of the original runtime or model globals.
exec(compile(adapted_ast(), __file__, 'exec'),globals())

#!/usr/bin/env python3
"""Prepare N360 normal quality; services need explicit --prepared --run."""
from __future__ import annotations
import ast as _ast
import hashlib as _hashlib
from pathlib import Path as _Path

UPSTREAM=_Path(__file__).with_name('run_linear_capital_quality.py')
UPSTREAM_SHA256='7d3e07650dbebe7698bdbaedd6850895832bf0a4d895e4fc259faea86fbf1bff'


def adapted_ast():
    raw=UPSTREAM.read_bytes()
    if UPSTREAM!=UPSTREAM.resolve() or _hashlib.sha256(raw).hexdigest()!=UPSTREAM_SHA256:
        raise ValueError('The frozen original normal quality lifecycle changed')
    tree=_ast.parse(raw,filename=str(UPSTREAM));counts={}
    strings={'prepared_complete_native_linear_capital_normal_quality':'prepared_complete_native_linear_capital_scaled_normal_quality',
        'config/pipelines/linear_capital_quality_v1.yaml':'config/pipelines/linear_capital_scaled_quality_v2.yaml',
        'linear_view_admissions':'linear_scaled_view_admissions','standard':'scaled360',
        '_normal_linear_support_':'_normal_scaled_linear_support_'}
    imports={
        ('sheets_factory.pipelines','linear_capital_quality'):'linear_capital_scaled_quality',
        ('sheets_factory.task_adapters','linear_capital_portfolio'):'linear_capital_scaled',
        ('sheets_factory.workbook','linear_capital_public_recovery'):'linear_capital_scaled_public_recovery'}
    def mark(name):counts[name]=counts.get(name,0)+1
    class Adapt(_ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            for (module,name),replacement in imports.items():
                if node.level==0 and node.module==module and len(node.names)==1 and node.names[0].name==name:
                    node.names[0].name=replacement;mark('import:'+name)
            return node
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in strings:
                before=node.value;node.value=strings[before];mark('string:'+before)
            return node
        def visit_Compare(self,node):
            if _ast.unparse(node)=="frozen['version'] == 1":
                node.comparators[0]=_ast.Constant(2);mark('version_guard')
            return self.generic_visit(node)
        def visit_Dict(self,node):
            keys={k.value:i for i,k in enumerate(node.keys) if isinstance(k,_ast.Constant)}
            if {'kind','version','declared_selections','source_provider_registry','public_runtime_preparation'}<=keys.keys():
                if node.values[keys['version']].value!=1:raise ValueError('The original normal preparation version changed')
                node.values[keys['version']]=_ast.Constant(2);mark('version')
            return self.generic_visit(node)
    tree=Adapt().visit(tree)
    tree.body=[n for n in tree.body if not (isinstance(n,_ast.If) and
        _ast.dump(n.test)==_ast.dump(_ast.parse("__name__ == '__main__'",mode='eval').body))]
    expected={**{'string:'+key:1 for key in strings},'string:linear_view_admissions':2,'string:standard':2,
        **{'import:'+name:1 for _,name in imports},'version_guard':1,'version':1}
    if counts!=expected:raise ValueError('The exact N360 normal lifecycle substitutions changed: '+str(counts))
    return _ast.fix_missing_locations(tree)


exec(compile(adapted_ast(),str(UPSTREAM),'exec'),globals())
_recipes=recipes


def recipes(config,admissions):
    rows=_recipes(config,admissions)
    for path in (UPSTREAM,pipeline.UPSTREAM,adapter.UPSTREAM,pipeline.TASK_VALIDATOR):
        record=reference(path);rows[record['path']]=record['sha256']
    return rows


if __name__=='__main__':raise SystemExit(main())

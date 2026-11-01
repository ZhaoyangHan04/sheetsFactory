"""Two-donor instance of the frozen complete302-cell linear report."""
from __future__ import annotations

import ast
from pathlib import Path
from types import FunctionType

from ..linear_capital_ringfenced_group import group_report as ancestor
from . import contract as c, stream_composition as base

UPSTREAM_SHA='d0988f5b627575678e19888794a2fbd38b22ec3cea2259aaf42ce10c083d8e88'
SHEET=ancestor.SHEET;FIELDS=ancestor.FIELDS


def _load():
    c.require(c.reference(ancestor.__file__)['sha256']==UPSTREAM_SHA,'The complete frozen report ancestor changed')
    ns=dict(vars(ancestor));ns.update(c=c,base=base,__file__=__file__,
        COMPOSER_SHA256=c.reference(base.__file__)['sha256'])
    for name,value in vars(ancestor).items():
        if isinstance(value,FunctionType) and value.__globals__ is vars(ancestor):
            clone=FunctionType(value.__code__,ns,name,value.__defaults__,value.__closure__);clone.__kwdefaults__=value.__kwdefaults__;ns[name]=clone
    tree=ast.parse(Path(ancestor.__file__).read_bytes());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='plan')
    changed=0
    class Pair(ast.NodeTransformer):
        def visit_Constant(self,n):
            nonlocal changed
            if n.value=='Four ringfenced mandates: group reporting':n.value='Two ringfenced mandates: group reporting';changed+=1
            elif n.value=='pure_four_ringfenced_group_reporting_plan':n.value='pure_two_ringfenced_group_reporting_plan';changed+=1
            return n
        def visit_Compare(self,n):
            nonlocal changed
            # The pair contract supplies the actual two immutable prefixes.
            if ast.unparse(n).endswith('== base.FIXED'):
                changed+=1;return ast.parse("[(d['id'],d['prefix']) for d in composed['donors']]==[(m['id'],m['sheet_prefix']) for m in public['mandates']]",mode='eval').body
            return self.generic_visit(n)
    node=Pair().visit(node);c.require(changed==3,'Unknown complete report adapter sites')
    tree=ast.Module(body=[node],type_ignores=[]);ast.fix_missing_locations(tree);exec(compile(tree,str(ancestor.__file__),'exec'),ns)
    return ns


_N=_load()
for _name in ('plan','expectations','append_report'):globals()[_name]=_N[_name]

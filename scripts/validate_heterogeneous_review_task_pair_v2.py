#!/usr/bin/env python3
"""Exact v1 seven-call lifecycle in an isolated v2 task/evidence namespace."""
from __future__ import annotations
import ast
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from sheets_factory.workbook import heterogeneous_review_tasks_v2 as task

UPSTREAM_SHA256="3a5d1eefc5a6d02646a0d12145b2da41609bd626e2a8a8e7867681a9de949d6e"
_path=ROOT/"scripts/validate_heterogeneous_review_task_pair.py"
task.merge.require(task.ref(_path)["sha256"]==UPSTREAM_SHA256,"Frozen v1 paired lifecycle changed")


class _Adapter(ast.NodeTransformer):
    def __init__(self):self.imports=0;self.versions=0;self.checks=0
    def visit_ImportFrom(self,node):
        if node.module=="sheets_factory.workbook" and len(node.names)==1 and node.names[0].name=="heterogeneous_review_tasks" and node.names[0].asname=="task":
            node.names[0].name="heterogeneous_review_tasks_v2";self.imports+=1
        return node
    def visit_Dict(self,node):
        self.generic_visit(node)
        for index,(key,value) in enumerate(zip(node.keys,node.values)):
            if isinstance(key,ast.Constant) and key.value=="version" and isinstance(value,ast.Constant) and value.value==1:node.values[index]=ast.Constant(2);self.versions+=1
        return node
    def visit_Compare(self,node):
        self.generic_visit(node)
        if isinstance(node.left,ast.Subscript) and isinstance(node.left.slice,ast.Constant) and node.left.slice.value=="version" and len(node.comparators)==1 and isinstance(node.comparators[0],ast.Constant) and node.comparators[0].value==1:
            node.comparators[0]=ast.Constant(2);self.checks+=1
        return node


_tree=ast.parse(_path.read_text());_adapter=_Adapter();_tree=_adapter.visit(_tree)
task.merge.require((_adapter.imports,_adapter.versions,_adapter.checks)==(1,6,1),"Frozen v1 paired lifecycle AST anchors changed")
ast.fix_missing_locations(_tree);_ns={"__name__":"_isolated_heterogeneous_pair_validation_v2","__file__":__file__}
exec(compile(_tree,str(_path),"exec"),_ns)
_BASE_COMPLETED=_ns["validate_completed"]


def _validate_completed_v2(value):
    terminal=_BASE_COMPLETED(value);frozen,_=task.validate_prepared(task.checked(terminal["preparation"]))
    task.merge.require(terminal["text_alias_cache_proof"]==frozen["text_alias_cache_proof"],"Actual/prepared text-alias proof binding differs")
    return terminal


_ns["validate_completed"]=_validate_completed_v2
for _name in ("ACTUAL_KIND","PAIR_KIND","STAGES","validate_prepared","actual_D","run_sequence","execute_prepared","validate_completed","execute_pair","main","_values_equal","_financial_goal","_input_identity","_retained_public_objects"):
    globals()[_name]=_ns[_name]

if __name__=="__main__":main()

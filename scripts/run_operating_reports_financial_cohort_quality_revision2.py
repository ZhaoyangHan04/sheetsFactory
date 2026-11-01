#!/usr/bin/env python3
"""The same ordinary FM quality run with scoped immutable design ancestry."""
from __future__ import annotations
import ast
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
FROZEN_ENTRY=ROOT/'scripts/run_operating_reports_financial_cohort_quality.py'
FROZEN_ENTRY_SHA='9955d2e4da4af0ed2cba54bf635a89db1a9c20fef83d6122adb2b7c48651fb7d'
if hashlib.sha256(FROZEN_ENTRY.read_bytes()).hexdigest()!=FROZEN_ENTRY_SHA:raise ValueError('The original normal cohort entry changed')
counts={'pipeline':0,'nodes':0,'kind':0}
class Revision(ast.NodeTransformer):
    def visit_ImportFrom(self,node):
        if node.module=='sheets_factory.pipelines' and len(node.names)==1 and node.names[0].name=='operating_reports_financial_cohort_quality':
            counts['pipeline']+=1
            return ast.copy_location(ast.ImportFrom(module='sheets_factory.task_adapters.operating_reports_financial_cohort_quality_revision2',
                names=[ast.alias(name='pipeline')],level=0),node)
        if node.module=='sheets_factory.task_adapters' and len(node.names)==1 and node.names[0].name=='operating_reports_financial_cohort_quality':
            counts['nodes']+=1;node.names[0].name='operating_reports_financial_cohort_quality_revision2'
        return node
    def visit_Constant(self,node):
        if node.value=='prepared_operating_reports_financial_cohort_normal_quality':
            counts['kind']+=1;node.value='prepared_operating_reports_financial_cohort_normal_quality_revision2'
        return node
tree=Revision().visit(ast.parse(FROZEN_ENTRY.read_bytes()))
if counts!={'pipeline':1,'nodes':1,'kind':1}:raise ValueError('The exact prospective normal routing seams changed')
tree.body=[n for n in tree.body if not(isinstance(n,ast.If) and ast.unparse(n.test)=="__name__ == '__main__'")]
exec(compile(ast.fix_missing_locations(tree),str(FROZEN_ENTRY),'exec'),globals())
_first_recipes=recipes


def recipes(config,admissions):
    result=_first_recipes(config,admissions)
    for path in (FROZEN_ENTRY,*nodes.ANCESTORS):
        row=reference(path);result[row['path']]=row['sha256']
    return result


_namespace['recipes']=recipes
if __name__=='__main__':raise SystemExit(main())

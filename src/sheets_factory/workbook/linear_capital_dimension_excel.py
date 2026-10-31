"""Opt-in enlarged rendering of the unchanged financial formula translator.

Only the schema binding, binding identity and complete formula ceiling change.
No financial cache, optimal plan, source admission or engine is supplied here.
"""
from __future__ import annotations

import ast
from collections import Counter,defaultdict
from functools import lru_cache
import hashlib
from pathlib import Path
from types import ModuleType,SimpleNamespace

from . import linear_capital_dimension_probe as probe

ROOT=Path(__file__).resolve().parents[3]
UPSTREAM=Path(__file__).with_name('linear_capital_portfolio')/'excel.py'
UPSTREAM_SHA256='3a0ec72daf5ac7c307bcea359c0a100fbaf1e36be890e2536260e50e9dac689d'
FORMULA_CAPS={720:2_600_000,1080:3_900_000}
require=probe.require


def source_files():
 require(hashlib.sha256(UPSTREAM.read_bytes()).hexdigest()==UPSTREAM_SHA256,'Frozen complete financial emitter changed')
 return {'dimension_excel':Path(__file__),'frozen_excel':UPSTREAM,**probe.source_files()}


def adapted_ast(n):
 require(type(n)is int and n in FORMULA_CAPS,'Only predeclared N720/N1080 rendering is supported')
 source_files();tree=ast.parse(UPSTREAM.read_bytes());hits=Counter()
 class Adapt(ast.NodeTransformer):
  def visit_ImportFrom(self,node):
   if node.level:
    require(node.level==1 and node.module=='spec','Unknown emitter dependency')
    hits['private_spec']+=1
    return ast.copy_location(ast.Pass(),node)
   return node
  def visit_FunctionDef(self,node):
   if node.name=='emit_workbook':
    index=next(i for i,a in enumerate(node.args.kwonlyargs)if a.arg=='max_formulas')
    require(ast.unparse(node.args.kw_defaults[index])=='1000000','Frozen emitter default changed')
    node.args.kw_defaults[index]=ast.Constant(FORMULA_CAPS[n]);hits['default']+=1
   return self.generic_visit(node)
  def visit_Compare(self,node):
   if ast.unparse(node)=='0 < max_formulas <= 2000000':
    node.comparators[-1]=ast.Constant(FORMULA_CAPS[n]);hits['cap']+=1
   return self.generic_visit(node)
  def visit_Constant(self,node):
   if node.value=='linear_capital_portfolio_native_excel_bindings':
    node.value=f'linear_capital_dimension_probe_n{n}_native_excel_bindings';hits['identity']+=1
   return node
 tree=Adapt().visit(tree)
 require(hits==Counter(private_spec=1,default=1,cap=1,identity=1),'Exact dimension emitter sites changed: '+str(hits))
 return ast.fix_missing_locations(tree)


@lru_cache(maxsize=2)
def _emitter(n):
 schema=probe.bundle(n).spec;module=ModuleType(__name__+f'._n{n}');module.__file__=str(Path(__file__))
 module.__dict__.update({k:getattr(schema,k)for k in ('ANNUAL_FIELDS','GROUP_FIELDS','RULES','T0_FIELDS','VINTAGE_FIELDS','canonical_sha256','load_spec','require','validate_plan')})
 exec(compile(adapted_ast(n),__file__,'exec'),module.__dict__)
 module.BINDING_KIND=f'linear_capital_dimension_probe_n{n}_native_excel_bindings'
 module.SPEC=schema;module.PRODUCTION_DIMENSION=n
 return module


def for_dimension(n):
 source_files();require(type(n)is int and n in FORMULA_CAPS,'Only predeclared N720/N1080 rendering is supported')
 return _emitter(n)


class _Cell:
 def __init__(self,row,column):
  from openpyxl.utils import get_column_letter
  self.row,self.column,self.coordinate=row,column,get_column_letter(column)+str(row)


class _Sheet:
 def __init__(self,title):
  self.title=title;self.column_dimensions=defaultdict(SimpleNamespace);self.row_dimensions=defaultdict(SimpleNamespace)
 def cell(self,row,column):return _Cell(row,column)
 def __getitem__(self,point):
  from openpyxl.utils import coordinate_to_tuple
  return _Cell(*coordinate_to_tuple(point))
 def add_data_validation(self,value):pass


class _Counter:
 """Execute structural write loops without allocating a Workbook or caches."""
 def __init__(self,emitter,public,plan):
  self.emitter,self.public,self.plan=emitter,public,plan;self.counts=Counter();self.sheetnames=[];self.used=set();self.longest=0
 def sheet(self,name):
  require(name not in self.sheetnames,'Duplicate counted worksheet');self.sheetnames.append(name);return _Sheet(name)
 def _point(self,sheet,row,col):
  key=sheet.title,row,col;require(key not in self.used,'Duplicate counted cell');self.used.add(key)
  return self.emitter._ref(sheet.title,row,col)
 def literal(self,sheet,row,col,value,**kwargs):
  result=self._point(sheet,row,col);self.counts['literals']+=1;self.counts['nonempty']+=int(value is not None);return result
 def choice(self,sheet,row,col,pid):
  self.counts['decisions']+=1;return self.literal(sheet,row,col,None if self.plan is None else self.plan[pid])
 def formula(self,sheet,row,col,expr,*,expected_path=None,**kwargs):
  self.counts['financial_bindings']+=int(expected_path is not None)
  if type(expr)is int and expected_path is not None:return self.literal(sheet,row,col,expr)
  result=self._point(sheet,row,col);self.counts['formulas']+=1;self.counts['nonempty']+=1
  self.longest=max(self.longest,len('='+self.emitter._expression(expr)))
  require(self.longest<=8192,'A counted formula exceeds Excel bounds')
  return result


def count_geometry(n,specification,*,plan=None):
 """Count frozen write loops, using one invariant project shape times N.

All project-specific business numbers become input references in the pinned
translator. Physical branching depends only on the common fiscal/scenario
axes. Input and complete shared-capacity loops use the actual supplied spec.
This is a count, never a native memory/runtime or financial-equivalence test.
"""
 emitter=for_dimension(n);public=emitter.load_spec(specification)
 actual=None if plan is None else emitter.validate_plan(public,plan)
 writer=_Counter(emitter,public,actual);a,s,u,l=emitter._inputs(writer)
 before=writer.counts.copy();names=len(writer.sheetnames)
 first=public['projects'][0];schedule=emitter._project(writer,first,a[first['id']],s)
 per_project=writer.counts-before;project_sheets=len(writer.sheetnames)-names
 tail=_Counter(emitter,public,actual)
 rows=emitter._portfolio(tail,{pid:schedule for pid in public['project_ids']},u,l)
 counts=before+Counter({k:v*len(public['projects'])for k,v in per_project.items()})+tail.counts
 return {'kind':f'counted_unallocated_linear_capital_n{n}_native_geometry','version':1,
  'specification_sha256':emitter.canonical_sha256(public),'dimensions':{'projects':len(public['projects']),'scenarios':len(public['scenario_ids']),'years':len(public['years'])},
  'source_physical_formulas':counts['formulas'],'max_profile_cells':counts['nonempty'],
  'max_dependency_closure_cells':counts['nonempty'],'full_target_cells':counts['financial_bindings']+counts['decisions'],
  'FM_mask_including_completion_gate':counts['financial_bindings']+counts['decisions']+1,
  'complete_business_rows':rows,'sheet_count':names+project_sheets*len(public['projects'])+len(tail.sheetnames),
  'maximum_formula_length_in_counted_sample':max(writer.longest,tail.longest),'plan_supplied':actual is not None,
  'workbooks_allocated':0,'financial_forwards':0,'optimizer_calls':0,'LO_calls':0,'qualified':False,
  'native_runtime_memory_or_financial_equivalence_measured':False,'all_actual_projects_rendered':False,
  'count_method':'Frozen project write shape times N; actual complete input and portfolio write loops; no truncation'}

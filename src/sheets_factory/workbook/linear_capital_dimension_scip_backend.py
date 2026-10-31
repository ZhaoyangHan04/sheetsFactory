"""Portable dimension bridge and explicitly scaled SCIP representation.

The three native module names use these same bytes. Financial construction is
removed; all original integer rows remain in validate_model/check_plan.
"""
from __future__ import annotations
import ast
from collections import Counter
from decimal import Decimal
import hashlib,importlib.util,json,math
from pathlib import Path
from types import ModuleType

BASE_SHA='0652651041f5f66edd58b07867dceaa3a85facf4ee0192749d1fbf911bb87f20'
DIMENSIONS=(720,1080)


def require(value,message):
 if not value:raise ValueError(message)


def upstream_path():
 local=Path(__file__).with_name('frozen_n720_adapter.py')
 return local if local.is_file() else Path(__file__).with_name('linear_capital_n720_reference')/'adapter.py'


def base_tree(name):
 path=upstream_path();require(hashlib.sha256(path.read_bytes()).hexdigest()==BASE_SHA,'Frozen N720 dimension bridge changed')
 package=__package__+'.linear_capital_n720_reference' if path.parent.name=='linear_capital_n720_reference' else __package__
 descriptor=importlib.util.spec_from_file_location(package+'._scip_dimension_base',path)
 old=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(old)
 return old.adapted_ast(name)


def counts(n):
 return dict(zip(('initial_sponsor_equity','annual_new_lp','annual_debt_close','resource','region_exposure','sector_exposure','exclusivity','prerequisite'),(1,60,60,360,120,160,n//6,n//3)))


def solver_rows(model):
 """P02 representation only: exact dedupe and declared positive scaling."""
 seen=set();rows=[];omitted=[]
 for row in model['rows']:
  a=row['coefficients'];b=row['limit'];key=(tuple(a),b)
  if not any(a) and b>=0:omitted.append({'id':row['id'],'reason':'zero_tautology'});continue
  if key in seen:omitted.append({'id':row['id'],'reason':'exact_duplicate'});continue
  seen.add(key);maximum=max(map(abs,a),default=0)
  scale=100000 if maximum>1000000 else 1000 if maximum>10 else 1
  rows.append({**row,'coefficients':[c/scale for c in a],'limit':b/scale,'positive_solver_scale':scale})
 return rows,omitted


def bound_diagnostics(result):
 objective=result.get('objective_pence');answer={}
 for field in ('native_objective','primal_bound','dual_bound','gap'):
  value=result.get(field)
  answer[field]=None if value is None else {'float_hex':float(value).hex(),
   'exact_binary_float_decimal':str(Decimal.from_float(float(value)))}
 answer['integer_objective_pence']=objective
 bound=result.get('dual_bound')
 answer['dual_minus_integer_objective_exact_decimal']=(None if objective is None or bound is None
  else str(Decimal.from_float(float(bound))-Decimal(objective)))
 answer['acceptance']='Unchanged strict native optimal, exact binary primal, every original integer row, native objective/primal/dual equal integer objective, native gap exactly zero'
 return answer


def adapted_tree(name,n):
 require(type(n)is int and n in DIMENSIONS,'Only the two predeclared production dimensions are supported')
 tree=base_tree(name);hits=Counter();rows=sum(counts(n).values())
 class Adapt(ast.NodeTransformer):
  def visit_Constant(self,node):
   if type(node.value)is int and node.value in (720,721,1121):
    hits[str(node.value)]+=1;node.value={720:n,721:n+1,1121:rows}[node.value]
   elif type(node.value)is str:
    node.value=node.value.replace('_n720',f'_n{n}').replace('N720',f'N{n}').replace('1121 business',f'{rows} business')
   return node
  def visit_FunctionDef(self,node):
   if node.name=='build_model':hits['remove_financial_builder']+=1;return None
   if node.name=='solve_cp_sat':hits['remove_unused_optimizer']+=1;return None
   if node.name=='solve_scip':
    # Keep the entire original native result and strict optimality contract.
    body=[]
    for statement in node.body:
     if isinstance(statement,ast.For) and ast.unparse(statement.target)=='(index, row)' and ast.unparse(statement.iter)=="enumerate(model['rows'])":
      statement.iter=ast.parse('enumerate(_solver_rows)',mode='eval').body
      body.extend(ast.parse('_solver_rows,_solver_omitted=solver_rows(model)').body);hits['scaled_rows']+=1
     body.append(statement)
    node.body=body
    final=next(item for item in node.body if isinstance(item,ast.Try)).finalbody
    require(ast.unparse(final[-1])=='native.freeProb()','Frozen native finalization changed')
    final[-1:-1]=ast.parse("result.update(solver_representation={'raw_original_rows':len(model['rows']),'native_nonzero_distinct_rows':len(_solver_rows),'omitted_rows':_solver_omitted,'row_scaling':'P02 thresholds:100000 if maxabs>1000000 else1000 if maxabs>10 else1','objective_scaled':False,'complete_original_integer_rows_rechecked':True},native_bound_precision=bound_diagnostics(result),declared_feasibility_tolerance=1e-9,applied_feasibility_tolerance=native.getParam('numerics/feastol'))").body
    hits['precision_receipt']+=1
   return self.generic_visit(node)
  def visit_Dict(self,node):
   keys=[getattr(k,'value',None) for k in node.keys]
   if keys==['limits/time','limits/gap','limits/absgap','parallel/maxnthreads','lp/threads']:
    node.keys.append(ast.Constant('numerics/feastol'));node.values.append(ast.Constant(1e-9));hits['declared_tolerance']+=1
   if 'feasibility_tolerance_changed' in keys:
    node.values[keys.index('feasibility_tolerance_changed')]=ast.parse('default_tolerance != 1e-9',mode='eval').body;hits['tolerance_metadata']+=1
   return self.generic_visit(node)
  def visit_Compare(self,node):
   if name=='spec' and ast.unparse(node) in ('len(groups) == 120','len(edges) == 240'):
    text=ast.unparse(node);node.comparators[0]=ast.Constant(n//6 if 'groups' in text else n//3);hits[text]+=1
   if ast.unparse(node)=="native.getParam('numerics/feastol') != default_tolerance":
    node.comparators[0]=ast.Constant(1e-9);hits['tolerance_guard']+=1
   return self.generic_visit(node)
 tree=Adapt().visit(tree)
 expected={'spec':Counter({'721':1,'len(groups) == 120':1,'len(edges) == 240':1}),
  'model_a':Counter({'720':2,'1121':1,'remove_financial_builder':1,'scaled_rows':1,'precision_receipt':1,'declared_tolerance':1,'tolerance_metadata':1,'tolerance_guard':1}),
  'model_b':Counter({'720':2,'1121':1,'remove_financial_builder':1,'remove_unused_optimizer':1})}[name]
 require(hits==expected,'Exact dimension/SCIP representation sites changed: '+name+' '+str(hits))
 return ast.fix_missing_locations(tree)


def populate(namespace,name,n,specification=None):
 tree=adapted_tree(name,n)
 class Bind(ast.NodeTransformer):
  def visit_ImportFrom(self,node):
   if node.level:
    require(node.level==1 and node.module=='spec' and specification is not None,'Unexpected native financial dependency')
    for item in node.names:namespace[item.asname or item.name]=getattr(specification,item.name)
    return ast.copy_location(ast.Pass(),node)
   return node
 namespace.update(solver_rows=solver_rows,bound_diagnostics=bound_diagnostics,
  _PRODUCTION_COUNTS=counts(n),_SCALED_PRODUCTION_COUNTS=counts(n),_SCALED_COUNTER=Counter)
 exec(compile(ast.fix_missing_locations(Bind().visit(tree)),__file__,'exec'),namespace)
 if name=='spec':namespace.update(SPEC_KIND=f'hypothetical_ringfenced_linear_capital_dimension_probe_n{n}',SPEC_VERSION=3,PRODUCTION_COUNTS=counts(n),PRODUCTION_ROW_COUNT=sum(counts(n).values()))
 return namespace


def modules(n):
 specification=ModuleType(__name__+f'._spec_{n}');populate(specification.__dict__,'spec',n)
 answer={'spec':specification}
 for name in ('model_a','model_b'):
  module=ModuleType(__name__+f'._{name}_{n}');populate(module.__dict__,name,n,specification);answer[name]=module
 return answer


# These same source bytes are copied under the three native module filenames.
if __name__.split('.')[-1] in ('spec','model_a','model_b'):
 _name=__name__.split('.')[-1]
 _model=json.loads(Path(__file__).resolve().parents[1].joinpath('model.json').read_text())
 _n=len(_model['project_ids']);require(_n in DIMENSIONS,'Native bundle dimension is not predeclared')
 _spec=None if _name=='spec' else __import__(__package__+'.spec',fromlist=['spec'])
 populate(globals(),_name,_n,_spec)

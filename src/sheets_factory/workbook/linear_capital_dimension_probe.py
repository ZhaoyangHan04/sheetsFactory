"""Pure N720/N1080 probes over frozen independent financial implementations.

No workbook, optimizer, resource engine, normal-quality or release interface is
provided. Each dimension has private module dictionaries; old globals never
change. Only schema/dimension/catalog identities and dependency imports adapt.
"""
from __future__ import annotations
import ast
from collections import Counter
from functools import lru_cache
import hashlib
from pathlib import Path
from types import ModuleType,SimpleNamespace

ROOT=Path(__file__).resolve().parents[3]
OLD=Path(__file__).with_name('linear_capital_portfolio')
SCALED=Path(__file__).with_name('linear_capital_scaled')
UPSTREAMS={
 'spec':(OLD/'spec.py','9905ca53b00001834bd86f740f5d9dfa23b7155b98ae036fdbf48cc68293b594'),
 'catalog':(SCALED/'catalog.py','f3e51a03684dd22758d3b911214e56c0af3f2eadbab9e418d12ed958acd2a18d'),
 'candidate_a':(OLD/'candidate_a.py','dae797e3d62cd3e84965c7d3d7edb74ad83ecee113167b2943f581cf4351d322'),
 'ledger':(OLD/'ledger.py','c97035a85583b6ff82509c5fd1dfe57bdbabfb39fa1b7bf50fa270532add1e7f'),
 'finance_crosscheck':(OLD/'finance_crosscheck.py','bd25d57e57ac541dc74971e6ccfc78215be2ceaedc6cc323eb3a2395e82f89b2'),
 'model_a':(OLD/'model_a.py','b8d4c354795e774fbee03bd1401cc8e426d7e238eecac24182530f463eedc907'),
 'model_b':(OLD/'model_b.py','972e640060ba14d545e20907014a892be76c83675c9d00a354ee7098f693e6c4')}
DIMENSIONS=(720,1080)


def require(value,message):
 if not value:raise ValueError(message)


def source_files():
 paths={'dimension_probe':Path(__file__),**{name:path for name,(path,_) in UPSTREAMS.items()}}
 for name,(path,digest) in UPSTREAMS.items():
  require(hashlib.sha256(path.read_bytes()).hexdigest()==digest,'Frozen upstream differs: '+name)
 return paths


def tree(name):
 source_files();path,_=UPSTREAMS[name];return ast.parse(path.read_bytes(),filename=str(path))


def _replace_comparisons(t,replacements):
 counts=Counter()
 class Compare(ast.NodeTransformer):
  def visit_Compare(self,node):
   text=ast.unparse(node)
   if text in replacements:counts[text]+=1;return ast.parse(replacements[text],mode='eval').body
   return self.generic_visit(node)
 t=Compare().visit(t)
 require(counts==Counter({key:1 for key in replacements}),'Exact dimension comparison sites changed: '+str(counts))
 return t


def _module(name,n,t,bindings=None,spec=None):
 """Bind only explicitly recognized imports; execute no financial function."""
 module=ModuleType(__name__+f'._n{n}_'+name);module.__file__=str(UPSTREAMS[name][0])
 module.__dict__.update(bindings or {});imports=Counter()
 class Bind(ast.NodeTransformer):
  def visit_ImportFrom(self,node):
   if not node.level:return node
   require(node.level==1,'Unknown relative dependency')
   if node.module=='spec':
    require(spec is not None,'Missing private schema')
    for item in node.names:module.__dict__[item.asname or item.name]=getattr(spec,item.name)
   elif node.module is None:
    for item in node.names:require(item.name in module.__dict__,'Unbound private dependency: '+item.name)
   else:raise ValueError('Unexpected private dependency: '+str(node.module))
   imports[node.module or ','.join(a.name for a in node.names)]+=1
   return ast.copy_location(ast.Pass(),node)
 t=Bind().visit(t)
 expected={'spec':Counter(),'catalog':Counter({'spec':1}),'candidate_a':Counter({'spec':1}),
  'ledger':Counter({'spec':1}),'finance_crosscheck':Counter({'spec':1,'candidate_a,ledger':1}),
  'model_a':Counter({'spec':1,'candidate_a':1}),'model_b':Counter({'spec':1,'ledger':1})}[name]
 # Catalog imports the module itself as ``from . import spec``.
 if name=='catalog':expected=Counter({'spec':1})
 require(imports==expected,'Exact private import sites changed: '+name+' '+str(imports))
 exec(compile(ast.fix_missing_locations(t),module.__file__,'exec'),module.__dict__)
 return module


def _spec(n):
 t=tree('spec');kind=f'hypothetical_ringfenced_linear_capital_dimension_probe_n{n}'
 t=_replace_comparisons(t,{"s['version'] == 1":"s['version'] == 3",
  "s['kind'] == 'hypothetical_ringfenced_linear_capital_portfolio'":f"s['kind'] == {kind!r}",
  'len(groups) == 40':f'len(groups) == {n//6}','len(edges) == 80':f'len(edges) == {n//3}'})
 hits=0
 for node in t.body:
  if isinstance(node,ast.Assign) and [getattr(x,'id',None) for x in node.targets]==['PROJECT_IDS']:
   require(ast.unparse(node.value)=="tuple((f'P{i:03d}' for i in range(1, 241)))",'Original project IDs changed')
   node.value=ast.parse(f"tuple(f'P{{i:03d}}' for i in range(1,{n+1}))",mode='eval').body;hits+=1
 require(hits==1,'Complete project identity declaration changed')
 s=_module('spec',n,t);s.SPEC_KIND=kind;s.SPEC_VERSION=3
 s.PRODUCTION_COUNTS=dict(zip(('initial_sponsor_equity','annual_new_lp','annual_debt_close','resource','region_exposure','sector_exposure','exclusivity','prerequisite'),(1,60,60,360,120,160,n//6,n//3)))
 s.PRODUCTION_ROW_COUNT=sum(s.PRODUCTION_COUNTS.values());return s


def _catalog(n,s):
 t=tree('catalog');replacements={'SEED':202710720 if n==720 else 202711080,'PROFILE_ID':f'L{n}-D01',
  'GENERATION_POLICY':f'fresh_n{n}_standard_contracts_global_capacities_probe_v1',
  'COMPETITIVE_POLICY':f'fresh_n{n}_correlated_contracts_independent_revenue_jitter_probe_v1',
  'HUB_COUNT':n//6,'UNGROUPED_COUNT':n//2,'SITE_COUNT':n//6,'PREREQUISITE_COUNT':n//3}
 counts=Counter()
 class Scale(ast.NodeTransformer):
  def visit_Assign(self,node):
   names=[getattr(x,'id',None) for x in node.targets]
   if len(names)==1 and names[0] in replacements:
    counts[names[0]]+=1;node.value=ast.Constant(replacements[names[0]]);return node
   return self.generic_visit(node)
  def visit_Subscript(self,node):
   text=ast.unparse(node)
   if text in ('ids[:120]','ids[:180]'):
    counts[text]+=1;return ast.parse(f'ids[:{n//3 if text=="ids[:120]" else n//2}]',mode='eval').body
   return self.generic_visit(node)
  def visit_Constant(self,node):
   if type(node.value) is int and node.value==360:counts['numeric_dimension']+=1;node.value=n
   elif type(node.value) is str:
    value=node.value
    # Only identity/prose constants change; no financial numeric operand changes.
    value=value.replace('N360',f'N{n}').replace('n360',f'n{n}').replace('360',str(n))
    value=value.replace('60 independent',f'{n//6} independent').replace('60 global',f'{n//6} global').replace('60 three-option',f'{n//6} three-option').replace('120 acyclic',f'{n//3} acyclic')
    value=value.replace('independent_first120',f'independent_first{n//3}').replace('independent_first180',f'independent_first{n//2}')
    node.value=value
   return node
 t=Scale().visit(t)
 require(counts==Counter({**{key:1 for key in replacements},'numeric_dimension':2,'ids[:120]':1,'ids[:180]':1}),'Exact fresh-catalog dimension sites changed: '+str(counts))
 return _module('catalog',n,t,{'spec':s},s)


def _model(name,n,s,a,b):
 t=tree(name);kind=f'linear_capital_dimension_probe_direct_binary_integer_model_n{n}';rows=s.PRODUCTION_ROW_COUNT
 changes={"model['version'] == 1":"model['version'] == 3"}
 if name=='model_a':changes.update({'len(ids) in (1, 2, 3, 4, 240)':f'len(ids) in (1,2,3,4,{n})','len(ids) == 240':f'len(ids) == {n}','len(rows) == 881':f'len(rows) == {rows}'})
 else:changes.update({'1 <= len(ids) <= 240':f'len(ids) in (1,2,3,4,{n})','expected == 881':f'expected == {rows}'})
 t=_replace_comparisons(t,changes);counts=Counter()
 class Identity(ast.NodeTransformer):
  def visit_Assign(self,node):
   names=[getattr(x,'id',None) for x in node.targets]
   if names in (['KIND'],['MODEL_KIND']):node.value=ast.Constant(kind);counts['kind']+=1
   elif names==['PRODUCTION_COUNTS']:node.value=ast.Name(id='_PRODUCTION_COUNTS',ctx=ast.Load());counts['counts']+=1
   return self.generic_visit(node)
  def visit_Dict(self,node):
   keys=[getattr(k,'value',None) for k in node.keys]
   if all(k in keys for k in ('kind','version','project_ids','objective_pence')):
    i=keys.index('version');require(isinstance(node.values[i],ast.Constant) and node.values[i].value==1,'Model envelope version changed');node.values[i]=ast.Constant(3);counts['version']+=1
   return self.generic_visit(node)
  def visit_FunctionDef(self,node):
   if node.name.startswith('solve_'):return None  # This probe exposes no native optimizer entry.
   if name=='model_b' and node.name=='validate_model':
    require(isinstance(node.body[-1],ast.Return),'B validator return changed')
    node.body[-1:-1]=ast.parse(f"if len(ids)=={n}:\n require(len(model['rows'])=={rows} and _COUNTER(r['family'] for r in model['rows'])==_PRODUCTION_COUNTS, 'Complete dimensional row census required')").body
    counts['B_complete']+=1
   return self.generic_visit(node)
 t=Identity().visit(t)
 require(counts==Counter({'kind':1,'version':1,**({'counts':1} if name=='model_a' else {'B_complete':1})}),'Exact model identity sites changed')
 return _module(name,n,t,{'candidate_a':a,'ledger':b,'_PRODUCTION_COUNTS':s.PRODUCTION_COUNTS,'_COUNTER':Counter},s)


@lru_cache(maxsize=2)
def _bundle(n):
 s=_spec(n);catalog=_catalog(n,s)
 a=_module('candidate_a',n,tree('candidate_a'),spec=s)
 b=_module('ledger',n,tree('ledger'),spec=s)
 comparison=_module('finance_crosscheck',n,tree('finance_crosscheck'),{'candidate_a':a,'ledger':b},s)
 return SimpleNamespace(dimension=n,spec=s,catalog=catalog,A=a,B=b,comparison=comparison,
  model_A=_model('model_a',n,s,a,b),model_B=_model('model_b',n,s,a,b))


def bundle(projects):
 require(type(projects)is int and projects in DIMENSIONS,'Only predeclared N720/N1080 probe dimensions are allowed')
 source_files();return _bundle(projects)


def compare_matrices(a,b):
 """Compare every canonical objective, row metadata and integer coefficient."""
 differences=[];count=0
 for key in ('kind','version','project_ids','specification_sha256'):
  if a[key]!=b[key]:differences.append({'path':key,'A':a[key],'B':b[key]})
 if len(a['objective_pence'])!=len(b['objective_pence']):differences.append({'path':'objective_pence/length','A':len(a['objective_pence']),'B':len(b['objective_pence'])})
 for j,(x,y) in enumerate(zip(a['objective_pence'],b['objective_pence'])):
  if type(x)is not type(y) or x!=y:differences.append({'path':f'objective_pence/{j}','A':x,'B':y})
 if len(a['rows'])!=len(b['rows']):differences.append({'path':'rows/length','A':len(a['rows']),'B':len(b['rows'])})
 for i,(ra,rb) in enumerate(zip(a['rows'],b['rows'])):
  for key in ('id','family','scenario_id','year','limit'):
   if type(ra[key])is not type(rb[key]) or ra[key]!=rb[key]:differences.append({'path':f'rows/{i}/{key}','A':ra[key],'B':rb[key]})
  if len(ra['coefficients'])!=len(rb['coefficients']):differences.append({'path':f'rows/{i}/coefficients/length','A':len(ra['coefficients']),'B':len(rb['coefficients'])})
  for j,(x,y) in enumerate(zip(ra['coefficients'],rb['coefficients'])):
   count+=1
   if type(x)is not type(y) or x!=y:differences.append({'path':f'rows/{i}/coefficients/{j}','A':x,'B':y})
 return {'kind':'complete_dimension_probe_independent_matrix_comparison','version':1,'passed':not differences,
  'project_count':len(a['project_ids']),'row_count':len(a['rows']),'coefficients_compared':count,
  'objective_coefficients_compared':len(a['objective_pence']),'differences':differences,'differences_truncated':False,
  'separate_universe_implementation_hashes_allowed':True,'optimization_performed':False}

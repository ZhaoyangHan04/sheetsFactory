"""Portable, hash-bound dimension-only bridge over the frozen N360 wrappers."""
import ast
from collections import Counter
import hashlib
import importlib.util
from pathlib import Path

PINS={'spec':'932cd9afe3ccb104c07ce6a356e5e8777b305a507e3acf98ab7ffd5257871d1b',
 'model_a':'6bb86d51b39970d151fa4f638d2427c1f04253f87d611f802f5bc0621221354d',
 'model_b':'4fd922ab1f0b60a5412ff873d01ff7c06524005f0eec4ebeb38128b8b4cf806b'}
SPEC_KIND='hypothetical_ringfenced_linear_capital_dimension_probe_n720'
MODEL_KIND='linear_capital_dimension_probe_direct_binary_integer_model_n720'


def require(value,message):
 if not value:raise ValueError(message)


def path(name):
 local=Path(__file__).with_name('frozen_scaled_'+name+'.py')
 return local if local.is_file() else Path(__file__).resolve().parents[1]/'linear_capital_scaled'/(name+'.py')


def adapted_ast(name):
 p=path(name);require(hashlib.sha256(p.read_bytes()).hexdigest()==PINS[name],'Frozen N360 adapter changed')
 descriptor=importlib.util.spec_from_file_location(__package__+'._old_'+name,p)
 old=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(old)
 tree=old.adapted_ast();counts=Counter()
 replacements={
  "s['version'] == 2":"s['version'] == 3",
  "s['kind'] == 'hypothetical_ringfenced_linear_capital_portfolio_scaled'":f"s['kind'] == {SPEC_KIND!r}",
  'len(groups) == 60':'len(groups) == 120','len(edges) == 120':'len(edges) == 240'} if name=='spec' else {
  "model['version'] == 2":"model['version'] == 3",
  'len(ids) in (1, 2, 3, 4, 360)':'len(ids) in (1,2,3,4,720)',
  'len(ids) == 360':'len(ids) == 720',
  **({'len(rows) == 941':'len(rows) == 1121'} if name=='model_a' else {'expected == 941':'expected == 1121',"len(model['rows']) == 941":"len(model['rows']) == 1121"})}
 class Adapt(ast.NodeTransformer):
  def visit_Compare(self,node):
   text=ast.unparse(node)
   if text in replacements:counts[text]+=1;return ast.parse(replacements[text],mode='eval').body
   return self.generic_visit(node)
  def visit_Assign(self,node):
   if name=='spec' and [getattr(t,'id',None) for t in node.targets]==['PROJECT_IDS']:
    require(ast.unparse(node.value)=="tuple((f'P{i:03d}' for i in range(1, 361)))",'Complete N360 identity assignment changed')
    node.value=ast.parse("tuple(f'P{i:03d}' for i in range(1,721))",mode='eval').body;counts['projects']+=1
   return self.generic_visit(node)
  def visit_Constant(self,node):
   if node.value=='linear_capital_scaled_direct_binary_integer_model':node.value=MODEL_KIND;counts['model_kind']+=1
   elif type(node.value)is str:node.value=node.value.replace('N360','N720').replace('941 business','1121 business')
   return node
  def visit_Dict(self,node):
   keys=[getattr(k,'value',None) for k in node.keys]
   if all(k in keys for k in ('kind','version','project_ids','objective_pence')):
    index=keys.index('version');require(node.values[index].value==2,'Frozen model version changed');node.values[index]=ast.Constant(3);counts['envelope_version']+=1
   return self.generic_visit(node)
 tree=Adapt().visit(tree)
 expected={**{key:1 for key in replacements},**({'projects':1} if name=='spec' else {'model_kind':1,'envelope_version':1})}
 if counts!=Counter(expected):raise ValueError('Exact portable N720 substitutions changed: '+str(counts))
 return ast.fix_missing_locations(tree)

"""N720/600-second private producer, retaining the frozen full16CPU lifecycle."""
import ast
from collections import Counter
import hashlib,json
from pathlib import Path
from ..linear_capital_scaled import optimization_runtime as base
from . import adapter,model_b,spec

ROOT=Path(__file__).resolve().parents[4]
PROFILE=ROOT/'config/runtime_profiles/linear_capital_n720_reference600_v1.json'
BASE_SHA='45f841e9d33917b8ac469694b5ef335311479aa9de98aad72207a358744e2d54'
SOURCE_NAMES=('spec.py','model_a.py','model_b.py','adapter.py','frozen_spec.py','frozen_model_a.py','frozen_model_b.py','frozen_scaled_spec.py','frozen_scaled_model_a.py','frozen_scaled_model_b.py')


def _require(value,message):
 if not value:raise ValueError(message)


def profile_reference():
 value=json.loads(PROFILE.read_text())
 _require(value['kind']=='linear_capital_dimension_private_reference_producer_profile' and type(value['version'])is int and value['version']==1
  and value['id']=='linear_capital_n720_reference600_v1' and value['fixed_profile']=='L720-D01'
  and value['projects']==720 and value['complete_business_rows']==1121
  and value['image_id']=='sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
  and value['producer']=={'cpus':16,'memory_bytes':32*1024**3,'pids_limit':256,'threads':16,'network':'none','backend':'cp_sat','solver_seconds_per_attempt':600,'relative_gap':0,'absolute_gap':0,'automatic_retries':0}
  and all(type(value['producer'][k])is int for k in ('cpus','memory_bytes','pids_limit','threads','solver_seconds_per_attempt','relative_gap','absolute_gap','automatic_retries'))
  and value['maximum_native_searches']==2 and value['best_requires_OPTIMAL_before_runner'] is True
  and value['runner_excludes_complete_winner'] is True and value['runner_requires_OPTIMAL_and_positive_integer_gap'] is True
  and value['agent_and_verifier_resources_unchanged']=={'cpus':2,'memory_bytes':32*1024**3,'strict_tool_budget_seconds':1800,'model_response_time_excluded':True,'parallel_tool_executions':'sum'}
  and value['independent_second_global_search_claimed'] is False and value['solver_status_is_not_formal_certificate'] is True
  and value['source_or_quality_or_difficulty_certified'] is False,'The prospective N720 reference600 policy changed')
 return reference(PROFILE)


def _producer_source_files():
 folder=Path(__file__).parent;old=folder.parent/'linear_capital_portfolio'
 return {**{name:_real(folder/name) for name in ('spec.py','model_a.py','model_b.py','adapter.py')},
  **{'frozen_'+name:_real(old/name) for name in ('spec.py','model_a.py','model_b.py')},
  **{'frozen_scaled_'+name:_real(adapter.path(name.removesuffix('.py'))) for name in ('spec.py','model_a.py','model_b.py')}}


def _complete_scaled_dimension(model):
 _require(len(model['project_ids'])==720,'Only the complete720-project production matrix is allowed')
 return model_b.validate_model(model)


def adapted_ast():
 _require(hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest()==BASE_SHA,'Frozen N360 lifecycle changed')
 t=base.adapted_ast();counts=Counter()
 class Adapt(ast.NodeTransformer):
  def visit_Assign(self,node):
   names=[getattr(x,'id',None) for x in node.targets]
   if names==['PREPARATION_KIND']:node.value=ast.Constant('prepared_private_linear_capital_n720_reference600_solver');counts['prepared_kind']+=1
   elif names==['TERMINAL_KIND']:node.value=ast.Constant('private_linear_capital_n720_reference600_solver_execution');counts['terminal_kind']+=1
   elif names==['CODE_FILES']:node.value=ast.parse(repr(SOURCE_NAMES),mode='eval').body;counts['code_files']+=1
   return self.generic_visit(node)
  def visit_Compare(self,node):
   text=ast.unparse(node)
   replacements={"model['version'] == 2":"model['version'] == 3",'1 <= len(ids) <= 360':'len(ids) == 720',
    'time_limit_seconds == 3600':'time_limit_seconds == 600',"request['time_limit_seconds'] == 3600":"request['time_limit_seconds'] == 600", "frozen.get('version') == 2":"frozen.get('version') == 3"}
   if text in replacements:counts[text]+=1;return ast.parse(replacements[text],mode='eval').body
   return self.generic_visit(node)
  def visit_Constant(self,node):
   if node.value=='linear_capital_scaled_direct_binary_integer_model':node.value=adapter.MODEL_KIND;counts['model_kind']+=1
   elif type(node.value)is str:
    if 'sf-scaled-producer16-integer-' in node.value:node.value=node.value.replace('sf-scaled-producer16-integer-','sf-n720-reference600-');counts['owned_name']+=1
    node.value=node.value.replace('declared 3600-second','declared 600-second')
   return node
  def visit_FunctionDef(self,node):
   if node.name in ('prepare','execute_prepared'):
    marker='prepared_at' if node.name=='prepare' else 'requested_resources'
    for item in ast.walk(node):
     if isinstance(item,ast.Dict):
      keys=[getattr(k,'value',None) for k in item.keys]
      if marker in keys and 'version' in keys:
       index=keys.index('version');_require(item.values[index].value==2,'Frozen runtime envelope changed');item.values[index]=ast.Constant(3);counts[node.name+'_version']+=1
   return self.generic_visit(node)
 t=Adapt().visit(t)
 expected={'prepared_kind':1,'terminal_kind':1,'code_files':1,'model_kind':1,'owned_name':2,'prepare_version':1,'execute_prepared_version':1,
  "model['version'] == 2":1,'1 <= len(ids) <= 360':1,'time_limit_seconds == 3600':1,"request['time_limit_seconds'] == 3600":1,"frozen.get('version') == 2":1}
 _require(counts==Counter(expected),'Exact N720600 lifecycle substitutions changed: '+str(counts))
 return ast.fix_missing_locations(t)


exec(compile(adapted_ast(),__file__,'exec'),globals())

"""Pure enlarged-source building blocks; no source admission or execution CLI.

The original full A/B cache/formula/literal audits, complete business census,
typed stability and capped resource algorithms run in private namespaces.
Only explicit profile ceilings/identities and receipt provenance differ.
Constructing a diagnostic workbook never supplies an optimal gold or a source.
"""
from __future__ import annotations

import ast
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from functools import lru_cache
import hashlib,json,re
from pathlib import Path
from types import ModuleType

import yaml

from . import linear_capital_dimension_excel as excel
from . import resource_engine,thread_capped_resource_engine
from .heterogeneous_contracts import validate as typed_validation

ROOT=Path(__file__).resolve().parents[3]
BASE_PROFILE=ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
SOURCE=ROOT/'scripts/build_linear_capital_source.py'
RESOURCE_VALIDATOR=ROOT/'scripts/build_heterogeneous_source.py'
PINS={SOURCE:'8a4d9a84908242faa807fd969707326e028afaa17a3f8a9b0fc82d597f54c90e',
 RESOURCE_VALIDATOR:'0d8abfe960901da24c76fbdc3fbaaebb9bc37b973f6fa326904517ae495d7fba',
 Path(resource_engine.__file__):'cc4fb863740a0fc403a5947a52fa1c2e644b81b75c358e2a3cbf47e7d33a9c8d',
 Path(thread_capped_resource_engine.__file__):'82c2e2d5f0ca5c68973f893a66de5d3455e76e67235e462f1d76351a05044361',
 Path(typed_validation.__file__):'4c1dd14c1f7bd88d41fe887fef7175b0bfc9b4b2236744cc8a248b188b557905',
 ROOT/'src/sheets_factory/workbook/linear_capital_portfolio/formula_identity.py':'b7febc690ed1cda92e8a31964cdb4dc8a0c821d34a25ef93ee41a057cc74cc5a',
 ROOT/'src/sheets_factory/task_adapters/heterogeneous_formula_identity.py':'a4f6be1aa36b9b2fae34fbd7c313afc2bbbb8526256b88008a110850acf84ab5',
 ROOT/'src/sheets_factory/evaluation/streaming_verifier.py':'76c9c8ac718195fd9daa04c90a2f7f3b4dfb1f8d70e7b45acadb1386c6cdc665',
 ROOT/'src/sheets_factory/workbook/engine.py':'0f67176358f45e0d0a73edbafd928b8bde305aec3493a576db9040f823c7b700',
 ROOT/'src/sheets_factory/workbook/uno_recalculate.py':'c6b854c4705d12a9d7d1ec36575f0634e50c93290bd62c40634cc826ee41fc41',
 BASE_PROFILE:'4ecc79fe954b9e2965a15d2f0c8965a39394f621ae9808f02fcf88965f446b9b'}
LIMITS={720:(2_600_000,3_700_000,3_700_000,3_200_000),1080:(3_900_000,5_600_000,5_600_000,4_800_000)}
COUNT_KEYS=resource_engine.LIMIT_KEYS
require=excel.require
NO_SOURCE_ADMISSION=True


def profile_path(n):
 require(type(n)is int and n in LIMITS,'Only the two prospective enlarged profiles are allowed')
 return ROOT/f'config/runtime_profiles/linear_capital_n{n}_native_engineering_v1.yaml'


def source_files():
 for path,digest in PINS.items():require(hashlib.sha256(path.read_bytes()).hexdigest()==digest,'Frozen source-support ancestor changed: '+path.name)
 return {'dimension_source_support':Path(__file__),**excel.source_files(),
  **{f'support_ancestor_{i}':p for i,p in enumerate(PINS)},
  **{f'profile_{n}':profile_path(n)for n in LIMITS}}


def load_runtime_profile(value,*,dimension=None):
 source_files();p=yaml.safe_load(Path(value).read_text())if isinstance(value,(str,Path))else deepcopy(value)
 require(isinstance(p,dict),'An explicit dimension profile is required')
 allowed=[n for n in LIMITS if p.get('id')==f'linear_capital_n{n}_native_engineering_v1']
 require(len(allowed)==1 and (dimension is None or type(dimension)is int and allowed==[dimension]),'Wrong enlarged runtime profile identity')
 expected=resource_engine.load_runtime_profile(BASE_PROFILE);n=allowed[0]
 expected['id']=f'linear_capital_n{n}_native_engineering_v1'
 expected['limits']={**dict(zip(COUNT_KEYS,LIMITS[n])),'truncate':False}
 require(json.dumps(p,sort_keys=True,allow_nan=False)==json.dumps(expected,sort_keys=True,allow_nan=False),
  'Only the predeclared dimension identity and complete cell ceilings may change')
 return p


def validate_workload_counts(profile,counts,*,dimension=None):
 p=load_runtime_profile(profile,dimension=dimension)
 require(isinstance(counts,dict)and set(counts)==set(COUNT_KEYS)
  and all(type(counts[k])is int and 0<=counts[k]<=p['limits'][k]for k in COUNT_KEYS),
  'The complete enlarged workload must fit all four ceilings; no truncation')
 return {'counts':dict(counts),'limits':deepcopy(p['limits']),'complete_scope_required':True,'truncation_allowed':False}


def _definitions(path,names):
 tree=ast.parse(path.read_bytes());selected=[x for x in tree.body if isinstance(x,(ast.FunctionDef,ast.ClassDef))and x.name in names]
 require(len(selected)==len(names)and {x.name for x in selected}==set(names),'Frozen complete support definitions changed')
 return ast.Module(body=selected,type_ignores=[])


def _compile(tree,namespace):exec(compile(ast.fix_missing_locations(tree),__file__,'exec'),namespace)


def _resource_support(n,core):
 """Clone intact resource/thread classes; bind only the new profile/provenance."""
 resource=ModuleType(__name__+f'._resource_{n}');vars(resource).update(vars(resource_engine))
 vars(resource).update(__name__=__name__+f'._resource_{n}',__file__=__file__,load_runtime_profile=lambda value:load_runtime_profile(value,dimension=n))
 _compile(_definitions(Path(resource_engine.__file__),{'ResourceLibreOfficeEngine'}),vars(resource))
 cap=ModuleType(__name__+f'._cap_{n}');vars(cap).update(vars(thread_capped_resource_engine))
 def adapter_reference():source_files();return resource_engine._reference(__file__)
 vars(cap).update(__name__=__name__+f'._cap_{n}',__file__=__file__,base=resource,_adapter_reference=adapter_reference)
 _compile(_definitions(Path(thread_capped_resource_engine.__file__),{'ThreadCappedResourceLibreOfficeEngine','validate_capped_call'}),vars(cap))
 tree=_definitions(RESOURCE_VALIDATOR,{'validate_actual_call'});hits=0
 for node in ast.walk(tree):
  if isinstance(node,ast.Constant)and node.value=='src/sheets_factory/workbook/resource_engine.py':
   node.value=str(Path(__file__).relative_to(ROOT));hits+=1
 require(hits==1,'Frozen resource receipt implementation binding changed')
 namespace={'ROOT':ROOT,'read':core.read,'reference':core.reference,'checked':core.checked,
  'require':require,'IMAGE':{'id':resource_engine.load_runtime_profile(BASE_PROFILE)['image']['id']},'re':re,'datetime':datetime,'Path':Path}
 _compile(tree,namespace)
 def validate_actual_call(call,receipt,frozen):
  load_runtime_profile(frozen['runtime_profile_value'],dimension=n)
  return cap.validate_capped_call(call,receipt,frozen,resource_validator=namespace['validate_actual_call'])
 return cap.ThreadCappedResourceLibreOfficeEngine,validate_actual_call


@lru_cache(maxsize=2)
def _support(n):
 emitter=excel.for_dimension(n);module=ModuleType(__name__+f'._n{n}');ns=vars(module)
 ns.update(__file__=__file__,ROOT=ROOT,spec=emitter.SPEC,Decimal=Decimal,Path=Path,hashlib=hashlib,json=json,re=re,
  validate_workload_counts=lambda profile,counts:validate_workload_counts(profile,counts,dimension=n))
 names={'require','reference','checked','read','write','canonical','_at','_financial_value','_typed','expected_values',
  'audit_workbook','validate_audit','financial_locator_coverage','raw_geometry'}
 _compile(_definitions(SOURCE,names),ns)
 original_expected=module.expected_values
 def expected_values(public,a,b,bindings,plan):
  require(bindings.get('kind')==emitter.BINDING_KIND and bindings.get('dimensions')=={
   'projects':len(public['project_ids']),'scenarios':len(public['scenario_ids']),'years':len(public['years'])},
   'Use the complete explicit dimension emitter bindings')
  emitter.load_spec(public)
  return original_expected(public,a,b,bindings,plan)
 ns['expected_values']=expected_values
 module.excel=emitter;module.profile_path=profile_path(n)
 module.ResourceLibreOfficeEngine,module.validate_actual_call=_resource_support(n,module)
 module.compare_typed_caches=typed_validation.compare_typed_caches
 module.NO_SOURCE_ADMISSION=True;module.OPTIMAL_GOLD_SUPPLIED=False
 return module


def for_dimension(n):
 source_files();profile_path(n);load_runtime_profile(profile_path(n),dimension=n)
 return _support(n)

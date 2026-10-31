"""Fixed L720-D01 best/runner feasibility, reusing the complete frozen gates."""
from __future__ import annotations
import argparse,ast,hashlib,importlib.util,json,re,sys,time
from datetime import datetime,timezone
from pathlib import Path
from ..linear_capital_scaled import reference as base
from .. import linear_capital_dimension_probe as probe
from . import runtime,spec

ROOT=Path(__file__).resolve().parents[4]
BASE_SHA='6b38f264f3dc3c3e06213768eaa50c5944ab3bac5ab643150d1d5260b115a44c'
KIND='linear_capital_n720_reference600_best_runner_dual_financial_reference'
PREPARED='prepared_linear_capital_n720_reference600_best_runner_dual_financial_reference'
TIME_LIMIT=600
BACKENDS={'A':'scip','B':'cp_sat'}
require=spec.require
finance_crosscheck=probe.bundle(720).comparison
PROBE_ENTRY=ROOT/'scripts/prepare_linear_capital_dimension_probe.py'
PROBE_ENTRY_SHA='5677a4960c6daf967fcb992819c840d24452b71e1980668996e77d007722faba'


def _base_guard():
 require(hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest()==BASE_SHA,'Frozen N360 best/runner lifecycle changed')
 require(hashlib.sha256(PROBE_ENTRY.read_bytes()).hexdigest()==PROBE_ENTRY_SHA,'Corrected pure-probe entry changed')


def _gate_ast():
 _base_guard();t=base._gate_ast();counts={'version':0,'name':0}
 class Adapt(ast.NodeTransformer):
  def visit_Compare(self,node):
   if ast.unparse(node) in ("frozen['version'] == 2","value['version'] == 2"):
    node.comparators[0]=ast.Constant(3);counts['version']+=1
   return self.generic_visit(node)
  def visit_Constant(self,node):
   if node.value=='/sf-scaled-producer16-integer-':node.value='/sf-n720-reference600-';counts['name']+=1
   return node
 t=Adapt().visit(t);require(counts=={'version':2,'name':1},'Exact N720 receipt-gate sites changed')
 return ast.fix_missing_locations(t)


exec(compile(_gate_ast(),__file__,'exec'),globals())


def _probe_entry():
 _base_guard();descriptor=importlib.util.spec_from_file_location('_n720_cold_pure_probe',PROBE_ENTRY)
 value=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(value);return value


def _checked_finance(value):
 """Cold original A/B arithmetic/diagnostics/matrices; no financial forward."""
 record=reference(value) if isinstance(value,(str,Path)) else value;handoff=read(record)
 require(handoff.get('kind')=='completed_N720_N1080_pure_financial_and_full_matrix_handoff'
  and type(handoff.get('version'))is int and handoff['version']==2 and handoff.get('passed') is True
  and handoff.get('cold_evidence_hashes_typed_census_and_matrix_recomparison_passed') is True
  and handoff.get('host_only_no_container_resource_claim') is True
  and handoff.get('new_solver_LO_model_Harbor_network_calls')==0,'Genuine completed zero-service enlarged pure audit required')
 _refs(handoff)
 corrected=read(handoff['corrected_terminal']);freeze=read(corrected['shared_freeze'])
 require(corrected['kind']=='completed_dimension_probe_corrected_census_reused_universe_revision2'
  and corrected['version']==2 and corrected['passed'] is True
  and corrected['parent_terminal']==handoff['original_failed_measurement_terminal']
  and corrected['preparation']==handoff['corrected_preparation']
  and corrected['qualified'] is False and all(type(corrected[k])is int and corrected[k]==0
   for k in ('optimizer_calls','LO_calls','model_calls','Harbor_calls','network_calls','workbook_emission_calls')),
  'Corrected census lineage or execution boundary differs')
 _refs(corrected);_refs(freeze)
 prior=read(corrected['parent_terminal']);diagnostic=read(handoff['original_bug_diagnostic'])
 require(prior['passed'] is False and diagnostic['original_terminal']==corrected['parent_terminal'],
  'Original measurement failure history is required')
 for row in diagnostic['retained_code_inventory']:
  retained=row['retained_exact_bytes'];require(reference(retained['path'])==retained
   and retained['sha256']==row['original']['sha256'] and retained['bytes']==row['original']['bytes'],
   'Original exact source snapshot changed')
 entry=_probe_entry();prepared=entry.validate_prepared(Path(corrected['preparation']['path']).parent)
 require(reference(Path(corrected['preparation']['path']))==corrected['preparation'],'Pure preparation changed')
 matches=[r for r in prepared['profiles'] if r['id']=='L720-D01'];require(len(matches)==1,'Fixed L720-D01 is required')
 row=matches[0];require({k:row[k] for k in ('id','projects','seed','revenue_jitter_pence')}
  =={'id':'L720-D01','projects':720,'seed':202710720,'revenue_jitter_pence':150000},'Do not replace or resample the fixed candidate')
 selected=[r for r in corrected['profile_terminals'] if read(r)['id']=='L720-D01'];require(len(selected)==1,'One fixed completed candidate required')
 case=read(selected[0]);require(case['passed'] is True and case['raw_specification']==row['specification']
  and case['diagnostic_plans']==row['diagnostic_plans'] and case['qualified'] is False,'Fixed complete pure case changed')
 _refs(case);records=case['records'];public=spec.load_spec(read(row['specification']))
 require(public['dimension_mode']=='production' and len(public['project_ids'])==720,'Only complete N720 production allowed')
 a,b=read(records['universe_A']),read(records['universe_B']);bundle=probe.bundle(720)
 comparison=entry.checked_financial_comparison(bundle,public,a,b)
 require(comparison['passed'] is True and comparison==read(records['complete_typed_financial_comparison']),
  'Complete independent A/B typed values differ')
 plans=read(row['diagnostic_plans']);plancheck=finance_crosscheck.compare_plans(public,a,b,plans,require_feasible=False)
 require(plancheck['passed'] is True and plancheck['plan_count']==18
  and plancheck==read(records['all_18_diagnostic_plans']),'Complete fixed diagnostics differ')
 models={side:records['model_'+side] for side in BACKENDS};values={side:runtime.validate_model(read(r)) for side,r in models.items()}
 for side,universe in (('A',a),('B',b)):
  require(values[side]['specification_sha256']==spec.canonical_sha256(public)
   and values[side]['universe_sha256']==_sha(universe),'Complete financial/matrix ancestry differs')
 matrix=probe.compare_matrices(values['A'],values['B'])
 require(matrix['passed'] is True and matrix==read(records['complete_matrix_comparison'])
  and matrix['row_count']==1121 and matrix['coefficients_compared']==807120,'Every independent coefficient must agree')
 return {'terminal':record,'raw_preparation':corrected['preparation'],'specification':row['specification'],
  'public':public,'A':a,'B':b,'universe_A':records['universe_A'],'universe_B':records['universe_B'],
  'models':models,'model_values':values,'fixed_profile':'L720-D01','pure_case':selected[0]}


def adapted_ast():
 _base_guard();t=base.adapted_ast();counts={'version_guard':0,'version_envelope':0,'density_bounds':0,'density_dict':0,'rows':0}
 class Adapt(ast.NodeTransformer):
  def visit_Compare(self,node):
   text=ast.unparse(node)
   if text in ("frozen['version'] == 2","result['version'] == 2"):
    node.comparators[0]=ast.Constant(3);counts['version_guard']+=1
   elif text in ('120 <= selected <= 240','120 <= sum(winner.values()) <= 240'):
    node.left=ast.Constant(240);node.comparators[-1]=ast.Constant(480);counts['density_bounds']+=1
   elif text=="row['exact_matrix_plan_check']['all_integer_rows_checked'] == 941":node.comparators[0]=ast.Constant(1121);counts['rows']+=1
   return self.generic_visit(node)
  def visit_Dict(self,node):
   keys={getattr(k,'value',None):i for i,k in enumerate(node.keys)}
   if {'minimum','maximum','public_cardinality_constraint'}<=keys.keys():
    require(node.values[keys['minimum']].value==120 and node.values[keys['maximum']].value==240,'Frozen density declaration changed')
    node.values[keys['minimum']]=ast.Constant(240);node.values[keys['maximum']]=ast.Constant(480);counts['density_dict']+=1
   if 'kind' in keys and 'version' in keys and isinstance(node.values[keys['kind']],ast.Name) and node.values[keys['kind']].id in ('KIND','PREPARED'):
    require(node.values[keys['version']].value==2,'Frozen outer version changed');node.values[keys['version']]=ast.Constant(3);counts['version_envelope']+=1
   return self.generic_visit(node)
  def visit_Constant(self,node):
   if type(node.value)is str:node.value=node.value.replace('941-row','1121-row')
   return node
 t=Adapt().visit(t)
 require(counts=={'version_guard':2,'version_envelope':2,'density_bounds':2,'density_dict':2,'rows':1},'Exact N720 best/runner sites changed: '+str(counts))
 return ast.fix_missing_locations(t)


exec(compile(adapted_ast(),__file__,'exec'),globals())


def recipes():
 entry=_probe_entry();paths=[Path(__file__),Path(runtime.__file__),runtime.PROFILE,
  Path(runtime.base.__file__),Path(base.__file__),ROOT/'scripts/run_linear_capital_n720_reference.py',
  ROOT/'scripts/run_linear_capital_producer_reference.py',ROOT/'scripts/run_linear_capital_reference.py',
  ROOT/'src/sheets_factory/workbook/linear_capital_portfolio/producer_optimization_runtime.py',
  ROOT/'src/sheets_factory/workbook/linear_capital_portfolio/optimization_runtime.py',*runtime._source_files().values()]
 return {**entry.recipes(),**{str(p):reference(p) for p in paths}}

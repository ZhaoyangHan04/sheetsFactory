"""Two fixed enlarged contracts, new SCIP experiments, frozen producer lifecycle."""
from __future__ import annotations
import argparse,ast,hashlib,inspect,json,re,sys,time
from collections import Counter
from datetime import datetime,timezone
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from . import linear_capital_dimension_probe as probe
from . import linear_capital_dimension_scip_backend as backend
from .linear_capital_n720_reference import reference as prior_reference,runtime as prior_runtime

ROOT=Path(__file__).resolve().parents[3]
PROFILE=ROOT/'config/runtime_profiles/linear_capital_dimension_scip3600_v1.json'
ENTRY=ROOT/'scripts/run_linear_capital_dimension_scip_reference.py'
PINS={Path(prior_runtime.__file__):'653e7d649440ce9b67113edd21537d40a2e714b7ee0749ff96d2eb87f6b8dbb3',
 Path(prior_reference.__file__):'10791d01e6994f0a3cbee7d4aed65078eabd5ce01592f5aaf61fd27f729f0ce6'}
PRIOR_CP600=ROOT/'outputs/research/linear_capital_N720_reference600_prepared_20261031T195200Z/prepared/terminal.json'
PRIOR_CP600_SHA='39f26113786b3abbd3e7614864e7582caec6370596bf48bfd1739a2b7dfb3b94'
PAIR_KIND='prepared_fixed_N720_N1080_independent_SCIP3600_reference_experiments'
require=backend.require
reference,read,write=prior_reference.reference,prior_reference.read,prior_reference.write
SOURCE_NAMES=('spec.py','model_a.py','model_b.py','frozen_n720_adapter.py','frozen_spec.py','frozen_model_a.py','frozen_model_b.py','frozen_scaled_spec.py','frozen_scaled_model_a.py','frozen_scaled_model_b.py')


def guard():
 for path,digest in PINS.items():require(reference(path)['sha256']==digest,'Frozen CP600 ancestor changed')
 require(reference(PRIOR_CP600)['sha256']==PRIOR_CP600_SHA,'Prior failed CP600 experiment must remain unchanged')


def policy():
 return {'kind':'linear_capital_dimension_SCIP_private_reference_profile','version':1,'id':'linear_capital_dimension_scip3600_v1',
  'candidate_order':['L720-D01','L1080-D01'],'dimensions':[720,1080],'rows':[1121,1301],
  'image_id':prior_runtime.IMAGE_ID,
  'producer':{'cpus':16,'memory_bytes':32*1024**3,'pids_limit':256,'threads':16,'network':'none','backend':'scip','solver_seconds_per_attempt':3600,'relative_gap':0,'absolute_gap':0,'feasibility_tolerance':1e-9,'automatic_retries':0},
  'vendor':{'pyscipopt':'6.0.0','numpy':'1.26.4','P02_version_equivalence_claimed':False},
  'objective':'original integer GBP pence; unscaled',
  'solver_rows':'exact duplicates and zero tautologies omitted; P02 positive threshold row scaling; every original integer row rechecked',
  'prior_incumbent_input':False,'new_business_or_cardinality_constraints':False,'maximum_native_searches_per_profile':2,
  'runner_requires_checked_OPTIMAL_best':True,'runner_excludes_complete_winner':True,'runner_requires_checked_OPTIMAL_positive_integer_gap':True,
  'agent_tool_budget_seconds_unchanged':1800,'source_or_quality_or_difficulty_certified':False}


def profile_reference():
 guard();require(json.dumps(json.loads(PROFILE.read_text()),sort_keys=True)==json.dumps(policy(),sort_keys=True),'Declared SCIP profile changed')
 return reference(PROFILE)


def source_files():
 old=ROOT/'src/sheets_factory/workbook/linear_capital_portfolio';scaled=old.with_name('linear_capital_scaled')
 return {**{name:Path(backend.__file__) for name in ('spec.py','model_a.py','model_b.py')},
  'frozen_n720_adapter.py':old.with_name('linear_capital_n720_reference')/'adapter.py',
  **{'frozen_'+name:old/name for name in ('spec.py','model_a.py','model_b.py')},
  **{'frozen_scaled_'+name:scaled/name for name in ('spec.py','model_a.py','model_b.py')}}


def recipes():
 guard();paths=[Path(__file__),Path(backend.__file__),PROFILE,ENTRY,*PINS,*source_files().values(),
  ROOT/'scripts/run_linear_capital_producer_reference.py',ROOT/'scripts/run_linear_capital_reference.py',
  ROOT/'src/sheets_factory/workbook/linear_capital_scaled/reference.py',
  ROOT/'src/sheets_factory/workbook/linear_capital_scaled/optimization_runtime.py',
  ROOT/'src/sheets_factory/workbook/linear_capital_portfolio/producer_optimization_runtime.py',
  ROOT/'src/sheets_factory/workbook/linear_capital_portfolio/optimization_runtime.py']
 return {**prior_reference._probe_entry().recipes(),**{str(p):reference(p) for p in paths}}


def _compile(tree,namespace):
 exec(compile(ast.fix_missing_locations(tree),__file__,'exec'),namespace)


def _runtime(n,modules):
 module=ModuleType(__name__+f'._runtime_{n}');ns=vars(module);ns.update(vars(prior_runtime));rows=sum(backend.counts(n).values());hits=Counter()
 class Adapt(ast.NodeTransformer):
  def visit_Assign(self,node):
   names=[getattr(x,'id',None) for x in node.targets]
   if names==['ROOT']:
    require(ast.unparse(node.value)=='Path(__file__).resolve().parents[4]','Frozen repository-root assignment changed')
    node.value=ast.Name(id='_DIMENSION_REPO_ROOT',ctx=ast.Load());hits['root']+=1
   elif names==['BACKENDS']:node.value=ast.parse("{'scip':('model_a','solve_scip','native_model.cip')}",mode='eval').body;hits['backend']+=1
   elif names==['CODE_FILES']:node.value=ast.parse(repr(SOURCE_NAMES),mode='eval').body;hits['sources']+=1
   elif names==['RUNNER']:
    worker=ast.parse(node.value.value);found=0
    for item in ast.walk(worker):
     if isinstance(item,ast.Subscript) and isinstance(item.value,ast.Dict) and [getattr(k,'value',None) for k in item.value.keys]==['scip','cp_sat']:
      item.value=ast.parse("{'scip':('model_a','solve_scip','native_model.cip')}",mode='eval').body;found+=1
    require(found==1,'Frozen native worker backend changed');node.value=ast.Constant(ast.unparse(worker));hits['worker']+=1
   return self.generic_visit(node)
  def visit_Compare(self,node):
   text=ast.unparse(node)
   if text=="solver.get('feasibility_tolerance_changed') is False":
    hits['tolerance_guard']+=1;return ast.parse("solver.get('declared_feasibility_tolerance')==1e-9 and solver.get('applied_feasibility_tolerance')==1e-9 and solver.get('feasibility_tolerance_changed')==(solver['default_feasibility_tolerance']!=1e-9)",mode='eval').body
   for old,new in {'len(ids) == 720':f'len(ids) == {n}','time_limit_seconds == 600':'time_limit_seconds == 3600',"request['time_limit_seconds'] == 600":"request['time_limit_seconds'] == 3600"}.items():
    if text==old:hits[old]+=1;return ast.parse(new,mode='eval').body
   return self.generic_visit(node)
  def visit_Dict(self,node):
   keys=[getattr(k,'value',None) for k in node.keys]
   if keys==['limits/time','limits/gap','limits/absgap','parallel/maxnthreads','lp/threads']:
    for key in ('parallel/maxnthreads','lp/threads'):node.values[keys.index(key)]=ast.Constant(16)
    node.keys.append(ast.Constant('numerics/feastol'));node.values.append(ast.Constant(1e-9));hits['scip_settings']+=1
   return self.generic_visit(node)
  def visit_Constant(self,node):
   if type(node.value)is str:
    if node.value=='linear_capital_dimension_probe_direct_binary_integer_model_n720':node.value=f'linear_capital_dimension_probe_direct_binary_integer_model_n{n}';hits['model_kind']+=1
    elif node.value in ('prepared_private_linear_capital_n720_reference600_solver','private_linear_capital_n720_reference600_solver_execution'):
     node.value=node.value.replace('n720_reference600',f'n{n}_scip3600');hits['identity']+=1
    else:
     if 'sf-n720-reference600-'in node.value:node.value=node.value.replace('sf-n720-reference600-',f'sf-dimension-scip3600-n{n}-');hits['name']+=1
     node.value=node.value.replace('declared 600-second','declared 3600-second')
   return node
 tree=Adapt().visit(prior_runtime.adapted_ast())
 require(hits==Counter({'root':1,'backend':1,'sources':1,'worker':1,'model_kind':1,'identity':2,'name':2,'scip_settings':1,'tolerance_guard':1,'len(ids) == 720':1,'time_limit_seconds == 600':1,"request['time_limit_seconds'] == 600":1}),'Exact SCIP resource adapter sites changed: '+str(hits))
 def complete(model):
  require(len(model['project_ids'])==n and len(model['rows'])==rows,'Complete declared production matrix required')
  return modules['model_a'].validate_model(model)
 ns.update(__file__=__file__,_DIMENSION_REPO_ROOT=ROOT,PROFILE=PROFILE,SOURCE_NAMES=SOURCE_NAMES,profile_reference=profile_reference,_producer_source_files=source_files,_complete_scaled_dimension=complete)
 _compile(tree,ns);return module


def _finance_ast(n):
 tree=ast.parse(inspect.getsource(prior_reference._checked_finance));hits=Counter();rows=sum(backend.counts(n).values())
 class Adapt(ast.NodeTransformer):
  def visit_Constant(self,node):
   if type(node.value)is int and node.value in (720,202710720,1121,807120):
    hits[str(node.value)]+=1;node.value={720:n,202710720:202710720 if n==720 else 202711080,1121:rows,807120:n*rows}[node.value]
   elif type(node.value)is str:node.value=node.value.replace('L720-D01',f'L{n}-D01').replace('N720',f'N{n}')
   return node
 tree=Adapt().visit(tree);require(hits==Counter({'720':3,'202710720':1,'1121':1,'807120':1}),'Frozen full-finance gate sites changed')
 return tree


def _gates_ast(n):
 tree=prior_reference._gate_ast();hits=Counter()
 class Adapt(ast.NodeTransformer):
  def visit_Constant(self,node):
   if node.value=='/sf-n720-reference600-':node.value=f'/sf-dimension-scip3600-n{n}-';hits['name']+=1
   return node
  def visit_Dict(self,node):
   keys=[getattr(k,'value',None) for k in node.keys]
   if keys==['limits/time','limits/gap','limits/absgap','parallel/maxnthreads','lp/threads']:
    for key in ('parallel/maxnthreads','lp/threads'):node.values[keys.index(key)]=ast.Constant(16)
    node.keys.append(ast.Constant('numerics/feastol'));node.values.append(ast.Constant(1e-9));hits['scip_settings']+=1
   return self.generic_visit(node)
  def visit_Compare(self,node):
   if ast.unparse(node)=="solver.get('feasibility_tolerance_changed') is False":
    hits['tolerance']+=1;return ast.parse("solver.get('declared_feasibility_tolerance')==1e-9 and solver.get('applied_feasibility_tolerance')==1e-9 and solver.get('feasibility_tolerance_changed')==(solver['default_feasibility_tolerance']!=1e-9)",mode='eval').body
   return self.generic_visit(node)
  def visit_Assign(self,node):
   if [getattr(t,'id',None)for t in node.targets]==['checked'] and ast.unparse(node.value)=='runtime.check_result(read(model), solver, exclude_plan)':
    hits['strict_native_recheck']+=1;return [node,*ast.parse('_strict_scip_evidence(solver,read(model))').body]
   return self.generic_visit(node)
 tree=Adapt().visit(tree);require(hits==Counter({'name':1,'scip_settings':1,'tolerance':1,'strict_native_recheck':1}),'Exact SCIP receipt gate sites changed: '+str(hits))
 return tree


def _strict_scip_evidence(solver,model):
 """Cold-recompute the original native adapter's strict optimality decision."""
 if not solver['checked_optimal']:return
 objective=solver['objective_pence'];values=solver['native_solution_values'];plan=solver['plan']
 require(solver['completed'] is True and solver['raw_status']=='optimal' and type(objective)is int
  and len(values)==len(model['project_ids']) and all(type(v)in(int,float) and v in (0.0,1.0)for v in values)
  and values==[plan[pid]for pid in model['project_ids']]
  and all(type(solver[k])in(int,float) and solver[k]==float(objective)for k in ('native_objective','primal_bound','dual_bound'))
  and solver['gap']==0.0 and solver['native_bound_precision']==backend.bound_diagnostics(solver),
  'Native optimality requires the original exact primal/bound decision, not a rounded gap display')


def _outer_ast(n):
 tree=prior_reference.adapted_ast();hits=Counter();rows=sum(backend.counts(n).values())
 class Adapt(ast.NodeTransformer):
  def visit_Compare(self,node):
   text=ast.unparse(node)
   if text=="result['model_B'] == finance['models']['B']":hits['B_lineage']+=1;return node
   if text in ('240 <= selected <= 480','240 <= sum(winner.values()) <= 480'):
    hits['no_density']+=1;return ast.Constant(True)
   if text=="row['exact_matrix_plan_check']['all_integer_rows_checked'] == 1121":node.comparators[0]=ast.Constant(rows);hits['rows']+=1
   return self.generic_visit(node)
  def visit_Dict(self,node):
   keys=[getattr(k,'value',None) for k in node.keys]
   if set(keys)=={'minimum','maximum','public_cardinality_constraint'}:
    hits['density_metadata']+=1;return ast.parse("{'required':False,'public_cardinality_constraint':False}",mode='eval').body
   return self.generic_visit(node)
  def visit_Subscript(self,node):
   if ast.unparse(node)=="finance['models']['B']":node.slice=ast.Constant('A');hits['A_model']+=1
   return self.generic_visit(node)
  def visit_keyword(self,node):
   if node.arg=='model_B' and ast.unparse(node.value)=="finance['models']['B']":hits['B_lineage']+=1;return node
   if node.arg=='selection_density_passed':node.arg='selection_density_not_required';hits['density_keyword']+=1
   return self.generic_visit(node)
  def visit_Constant(self,node):
   if node.value=='cp_sat':node.value='scip';hits['backend']+=1
   elif node.value=='selection_density_passed':node.value='selection_density_not_required';hits['density_result']+=1
   return node
 tree=Adapt().visit(tree)
 require(hits==Counter({'no_density':2,'rows':1,'density_metadata':2,'A_model':4,'B_lineage':2,'backend':4,'density_result':1,'density_keyword':1}),'Exact best/runner SCIP sites changed: '+str(hits))
 return tree


@lru_cache(maxsize=2)
def experiment(n):
 guard();require(type(n)is int and n in backend.DIMENSIONS,'Only the two fixed enlarged contracts are allowed')
 modules=backend.modules(n);runtime=_runtime(n,modules);module=ModuleType(__name__+f'._reference_{n}');ns=vars(module);ns.update(vars(prior_reference))
 ns.update(__file__=__file__,ROOT=ROOT,spec=modules['spec'],runtime=runtime,
  finance_crosscheck=probe.bundle(n).comparison,TIME_LIMIT=3600,
  KIND=f'linear_capital_n{n}_SCIP3600_best_runner_reference',PREPARED=f'prepared_linear_capital_n{n}_SCIP3600_best_runner_reference',recipes=recipes,_strict_scip_evidence=_strict_scip_evidence)
 _compile(_gates_ast(n),ns);_compile(_finance_ast(n),ns);_compile(_outer_ast(n),ns)
 return module


def prepare(finance_terminal,output):
 """Freeze both raw/model ancestries before preparing either native job."""
 output=Path(output).absolute();require(output==output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(),'Use a fresh private experiment root')
 profile_reference();entry=prior_reference._probe_entry();source=reference(finance_terminal);handoff=read(source)
 prior_reference._refs(handoff);corrected=read(handoff['corrected_terminal']);pure=entry.validate_prepared(Path(corrected['preparation']['path']).parent)
 require([r['id'] for r in pure['profiles']]==['L720-D01','L1080-D01'],'Both predeclared original candidates are required')
 ancestors=[]
 for row in pure['profiles']:
  case=next(read(r) for r in corrected['profile_terminals'] if read(r)['id']==row['id'])
  require(case['raw_specification']==row['specification'] and case['diagnostic_plans']==row['diagnostic_plans'] and case['passed'] is True,'Fixed pure-audit ancestry changed')
  ancestors.append({'id':row['id'],'projects':row['projects'],'seed':row['seed'],'revenue_jitter_pence':row['revenue_jitter_pence'],'raw_specification':row['specification'],'all18plans':row['diagnostic_plans'],'full_model_A':case['records']['model_A'],'full_model_B':case['records']['model_B']})
 output.mkdir(parents=True)
 frozen={'kind':PAIR_KIND,'version':1,'finance_handoff':source,'common_candidates_frozen_before_any_native_preparation':ancestors,'profile':profile_reference(),'recipe':recipes(),'prior_CP600_terminal':reference(PRIOR_CP600),'prior_attempt_as_incumbent_input':False,'maximum_profiles':2,'maximum_native_searches_per_profile':2,'retries':0,'solver_calls':0,'model_calls':0,'LO_calls':0,'qualified':False}
 declaration=write(output/'prospective.json',frozen)
 jobs=[]
 for n in backend.DIMENSIONS:jobs.append({'projects':n,'preparation':experiment(n).prepare(source,output/f'L{n}-D01')})
 return write(output/'preparation.json',{'kind':PAIR_KIND+'_complete','version':1,'prospective':declaration,'experiments':jobs,'solver_calls':0,'model_calls':0,'LO_calls':0,'qualified':False})


def validate_prepared(output):
 output=Path(output).absolute();value=read(reference(output/'preparation.json'));frozen=read(value['prospective'])
 require(value['kind']==PAIR_KIND+'_complete' and type(value['version'])is int and value['version']==1 and frozen['kind']==PAIR_KIND and type(frozen['version'])is int and frozen['version']==1 and frozen['recipe']==recipes() and frozen['profile']==profile_reference() and frozen['prior_CP600_terminal']==reference(PRIOR_CP600),'Common immutable SCIP experiment preparation changed')
 require(all(type(v[k])is int and v[k]==0 for v in (value,frozen) for k in ('solver_calls','model_calls','LO_calls')) and value['qualified'] is False and frozen['qualified'] is False
  and type(frozen['retries'])is int and frozen['retries']==0 and type(frozen['maximum_profiles'])is int and frozen['maximum_profiles']==2
  and type(frozen['maximum_native_searches_per_profile'])is int and frozen['maximum_native_searches_per_profile']==2 and frozen['prior_attempt_as_incumbent_input'] is False,'The declared no-call, no-hint, once-only experiment bounds changed')
 require([r['projects'] for r in value['experiments']]==list(backend.DIMENSIONS),'Both original experiment preparations are required')
 ancestors=frozen['common_candidates_frozen_before_any_native_preparation']
 require([{k:r[k] for k in ('id','projects','seed','revenue_jitter_pence')}for r in ancestors]==[
  {'id':'L720-D01','projects':720,'seed':202710720,'revenue_jitter_pence':150000},
  {'id':'L1080-D01','projects':1080,'seed':202711080,'revenue_jitter_pence':150000}],'Both fixed original raw declarations are required')
 for row in value['experiments']:
  prepared,finance=experiment(row['projects']).validate_prepared(Path(row['preparation']['path']).parent)
  require(reference(Path(row['preparation']['path']))==row['preparation'] and prepared['financial_crosscheck']==frozen['finance_handoff'],'Per-profile source binding changed')
  ancestor=next(r for r in ancestors if r['projects']==row['projects'])
  require(ancestor['raw_specification']==finance['specification'] and ancestor['full_model_A']==finance['models']['A'] and ancestor['full_model_B']==finance['models']['B'],'Common raw/full A/B ancestry changed')
 return value,frozen


def main(argv=None):
 parser=argparse.ArgumentParser(__doc__);sub=parser.add_subparsers(dest='command',required=True)
 p=sub.add_parser('prepare');p.add_argument('--finance-terminal',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
 for name in ('validate','run'):
  p=sub.add_parser(name);p.add_argument('--prepared',required=True,type=Path)
  if name=='run':p.add_argument('--projects',required=True,type=int,choices=backend.DIMENSIONS)
 p=sub.add_parser('validate-completed');p.add_argument('--receipt',required=True,type=Path);p.add_argument('--projects',required=True,type=int,choices=backend.DIMENSIONS)
 args=parser.parse_args(argv)
 if args.command=='prepare':answer=prepare(args.finance_terminal,args.output)
 elif args.command=='validate':value,_=validate_prepared(args.prepared);answer={'passed':True,'preparation':reference(args.prepared/'preparation.json')}
 elif args.command=='run':
  value,_=validate_prepared(args.prepared);row=next(r for r in value['experiments'] if r['projects']==args.projects)
  answer=experiment(args.projects).execute_prepared(Path(row['preparation']['path']).parent)
 else:answer=experiment(args.projects).validate_completed(args.receipt)
 print(json.dumps(answer,indent=2))
 return 0

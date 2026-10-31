"""New SCIP representation, portable closure and bounded two-profile lifecycle."""
from copy import deepcopy
import importlib,json,subprocess,sys
from pathlib import Path
from types import ModuleType,SimpleNamespace
import pytest
from sheets_factory.workbook import linear_capital_dimension_scip_backend as backend
from sheets_factory.workbook import linear_capital_dimension_scip_reference as entry
from sheets_factory.workbook.linear_capital_n720_reference import runtime as cp600
from test_linear_capital_optimization_runtime import services


def dump(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value)+'\n');return entry.reference(path)


def matrix(n=720):
 rows=[{'id':f'{family}:{i:04d}','family':family,'scenario_id':None,'year':None,'coefficients':[0]*n,'limit':0}
  for family,count in backend.counts(n).items() for i in range(count)]
 for row in rows:
  if row['family']=='initial_sponsor_equity':row['coefficients'][:2]=[2,1];row['limit']=2
 return {'kind':f'linear_capital_dimension_probe_direct_binary_integer_model_n{n}','version':3,
  'project_ids':[f'P{i:03d}' for i in range(1,n+1)],'objective_pence':[7,4]+[0]*(n-2),
  'rows':sorted(rows,key=lambda r:r['id']),'specification_sha256':'1'*64,'universe_sha256':'2'*64}


@pytest.fixture(autouse=True)
def no_services(monkeypatch,tmp_path):
 def forbidden(*args,**kwargs):raise AssertionError('Tests may not call a native optimizer, subprocess or network')
 monkeypatch.setattr(subprocess,'run',forbidden);monkeypatch.setattr(subprocess,'Popen',forbidden)
 import urllib.request
 monkeypatch.setattr(urllib.request,'urlopen',forbidden)
 historical=dump(tmp_path/'prior_CP600.json',{'explicit_mock_prior_failed_experiment':True})
 monkeypatch.setattr(entry,'PRIOR_CP600',Path(historical['path']));monkeypatch.setattr(entry,'PRIOR_CP600_SHA',historical['sha256'])


def test_private_factories_preserve_old_cp600_and_financial_free_native_surface():
 old=(cp600.PREPARATION_KIND,cp600.BACKENDS,cp600.RUNNER,cp600.profile_reference())
 for n in (720,1080):
  e=entry.experiment(n);m=backend.modules(n)
  assert e.prepare.__globals__ is vars(e) and e.runtime.prepare.__globals__ is vars(e.runtime)
  assert e.runtime.BACKENDS=={'scip':('model_a','solve_scip','native_model.cip')}
  assert e.runtime.ROOT==entry.ROOT==Path(__file__).resolve().parents[1]
  assert e.runtime.VENDOR_SITE_PACKAGES==cp600.VENDOR_SITE_PACKAGES==entry.ROOT/'outputs/tmp/linear-solver-914-py312/lib/python3.12/site-packages'
  assert e.runtime.PROFILE==entry.PROFILE
  assert len(m['spec'].PROJECT_IDS)==n and m['spec'].PRODUCTION_ROW_COUNT==761+n//2
  assert not hasattr(m['model_a'],'build_model') and not hasattr(m['model_b'],'build_model')
  assert not hasattr(m['model_b'],'solve_cp_sat')
 assert (cp600.PREPARATION_KIND,cp600.BACKENDS,cp600.RUNNER,cp600.profile_reference())==old


def test_representation_omits_only_exact_duplicates_and_true_zero_tautologies():
 def row(id,a,b):return {'id':id,'coefficients':a,'limit':b}
 value={'rows':[row('a',[1000001,0],2000002),row('copy',[1000001,0],2000002),
  row('different_bound',[1000001,0],2000001),row('proportional',[2000002,0],4000004),
  row('zero',[0,0],7),row('infeasible_zero',[0,0],-1),row('small',[11,-11],0)]}
 before=deepcopy(value);rows,omitted=backend.solver_rows(value)
 assert value==before and [r['id'] for r in rows]==['a','different_bound','proportional','infeasible_zero','small']
 assert omitted==[{'id':'copy','reason':'exact_duplicate'},{'id':'zero','reason':'zero_tautology'}]
 assert [r['positive_solver_scale'] for r in rows]==[100000,100000,100000,1,1000]
 assert rows[0]['coefficients']==[10.00001,0] and rows[1]['limit']==20.00001


class FakeSCIP:
 def __init__(self,*args):self.params={'numerics/feastol':1e-6};self.values=[];self.freed=False;self.status='optimal';self.bound=7.0;self.primal=7.0;self.gap=0.0;self.row_count=0
 def hideOutput(self,*args):pass
 def getParam(self,name):assert not self.freed;return self.params[name]
 def setParam(self,name,value):self.params[name]=value
 def addVar(self,**kwargs):value=1 if not self.values else 0;self.values.append(value);return value
 def setObjective(self,objective,sense):assert objective==7 and sense=='maximize'
 def addCons(self,*args,**kwargs):self.row_count+=1
 def optimize(self):pass
 def getStatus(self):return self.status
 def getPrimalbound(self):return self.primal
 def getDualbound(self):return self.bound
 def getGap(self):return self.gap
 def getNNodes(self):return 1
 def getSolvingTime(self):return 0.125
 def getNSols(self):return 1
 def getBestSol(self):return object()
 def getSolVal(self,solution,var):return var
 def getSolObjVal(self,*args,**kwargs):return self.primal
 def freeProb(self):self.freed=True


@pytest.mark.parametrize('status,bound,gap,accepted',[('optimal',7.0,0.0,True),('timelimit',7.0,0.0,False),('optimal',7.000000001,0.0,False),('optimal',7.0,1e-12,False)])
def test_mocked_scip_declared_tolerance_raw_objective_and_strict_bound(status,bound,gap,accepted,monkeypatch):
 native=FakeSCIP();native.status=status;native.bound=bound;native.gap=gap
 monkeypatch.setitem(sys.modules,'pyscipopt',SimpleNamespace(Model=lambda *a:native,quicksum=sum,__version__='6.0.0'))
 result=backend.modules(720)['model_a'].solve_scip(matrix(),time_limit_seconds=3600,threads=16)
 assert result['checked_optimal'] is accepted and result['objective_pence']==7
 assert result['parameters']=={'limits/time':3600.0,'limits/gap':0.0,'limits/absgap':0.0,'parallel/maxnthreads':16,'lp/threads':16,'numerics/feastol':1e-9}
 assert result['default_feasibility_tolerance']==1e-6 and result['feasibility_tolerance_changed'] is True
 assert result['declared_feasibility_tolerance']==result['applied_feasibility_tolerance']==1e-9 and native.freed
 assert result['exact_integer_check']['constraints_checked']==1121 and result['exact_integer_check']['feasible']
 assert result['solver_representation']['native_nonzero_distinct_rows']==1 and native.row_count==1
 assert result['native_bound_precision']['dual_bound']['float_hex']==bound.hex()


@pytest.mark.parametrize('damage',['raw_status','nonbinary','dual_fraction','positive_gap','precision'])
def test_cold_optimality_rechecks_native_evidence_not_rounded_display(damage):
 model={'project_ids':['P001','P002']}
 result={'checked_optimal':True,'completed':True,'raw_status':'optimal','objective_pence':7,'plan':{'P001':1,'P002':0},'native_solution_values':[1.0,0.0],
  'native_objective':7.0,'primal_bound':7.0,'dual_bound':7.0,'gap':0.0}
 result['native_bound_precision']=backend.bound_diagnostics(result);entry._strict_scip_evidence(result,model)
 if damage=='raw_status':result['raw_status']='timelimit'
 elif damage=='nonbinary':result['native_solution_values'][0]=0.999999999
 elif damage=='dual_fraction':result['dual_bound']=7.000000001
 elif damage=='positive_gap':result['gap']=1e-12
 else:result['native_bound_precision']['dual_bound']['float_hex']='wrong'
 with pytest.raises(ValueError):entry._strict_scip_evidence(result,model)


def test_profile_integer_boolean_and_parameter_drift_rejected(tmp_path,monkeypatch):
 path=tmp_path/'profile.json';monkeypatch.setattr(entry,'PROFILE',path)
 for key,value in [('version',True),('producer',dict(entry.policy()['producer'],threads=2)),('prior_incumbent_input',True)]:
  changed=entry.policy();changed[key]=value;path.write_text(json.dumps(changed))
  with pytest.raises(ValueError):entry.profile_reference()


@pytest.fixture(params=[720,1080])
def prepared(request,tmp_path,monkeypatch):
 n=request.param;e=entry.experiment(n);r=e.runtime;vendor=tmp_path/'vendor';vendor.mkdir();(vendor/'dummy.py').write_text('# no native modules\n')
 monkeypatch.setattr(r,'VENDOR_SITE_PACKAGES',vendor);monkeypatch.setattr(r,'VENDOR_ROOTS',{'dummy.py'})
 model=dump(tmp_path/'model.json',matrix(n));output=tmp_path/'job'
 preparation=r.prepare(model['path'],output,backend='scip',time_limit_seconds=3600,vendor_site_packages=vendor)
 return n,e,r,output,preparation,model


def test_portable_native_closure_for_each_complete_dimension(prepared):
 n,e,r,output,record,model=prepared;frozen=r.validate_prepared(output)
 assert frozen['resources']=={'cpus':16,'memory_bytes':32*1024**3,'pids_limit':256}
 assert frozen['request']['backend']=='scip' and frozen['request']['time_limit_seconds']==3600 and frozen['request']['exclude_plan'] is None
 assert frozen['operational_timeout_seconds']==3720 and frozen['request']['threads']==16
 assert set(frozen['source_code'])==set(entry.SOURCE_NAMES) and frozen['solver_calls']==frozen['model_calls']==0
 name=f'_portable_scip_dimension_{n}';package=ModuleType(name);package.__path__=[str(output/'job_bundle/portfolio')];sys.modules[name]=package
 try:
  a=importlib.import_module(name+'.model_a');b=importlib.import_module(name+'.model_b');s=importlib.import_module(name+'.spec')
  assert len(s.PROJECT_IDS)==n;a.validate_model(matrix(n));b.validate_model(matrix(n))
  assert not hasattr(a,'build_model') and not hasattr(b,'build_model') and name+'.finance' not in sys.modules
  assert a.solve_scip.__globals__ is vars(a)
 finally:
  for key in list(sys.modules):
   if key==name or key.startswith(name+'.'):del sys.modules[key]


@pytest.mark.parametrize('damage',['wrong_dimension','lost_row','time','backend','source','profile'])
def test_incomplete_or_rebound_preparations_rejected(prepared,damage):
 n,e,r,output,record,model=prepared;frozen=entry.read(record)
 if damage=='wrong_dimension':
  bad=matrix(1080 if n==720 else 720)
  with pytest.raises(ValueError):r.validate_model(bad)
  return
 if damage=='lost_row':
  bad=matrix(n);bad['rows'].pop()
  with pytest.raises(ValueError):r.validate_model(bad)
  return
 if damage=='time':frozen['request']['time_limit_seconds']=600
 elif damage=='backend':frozen['request']['backend']='cp_sat'
 elif damage=='profile':frozen['producer_profile']['sha256']='0'*64
 else:(output/'job_bundle/portfolio/frozen_model_a.py').write_text('# changed\n')
 Path(record['path']).write_text(json.dumps(frozen))
 with pytest.raises(ValueError):r.validate_prepared(output)


@pytest.mark.parametrize('fault',[None,'CPU','tolerance','limited'])
def test_mocked_actual_scip_lifecycle_settings_resources_cleanup_and_full_rows(prepared,monkeypatch,fault):
 n,e,r,output,job,model=prepared;state=services(monkeypatch);frozen=r.validate_prepared(output);bundle=output/'job_bundle';cid='b'*64
 def command(args,*,timeout=30):
  if args[:3]==['docker','image','inspect']:return subprocess.CompletedProcess(args,0,r.IMAGE_ID+'\n','')
  if args[:2]==['docker','create']:
   assert args[args.index('--cpus')+1]=='16';return subprocess.CompletedProcess(args,0,cid+'\n','')
  if args[:2]==['docker','rm']:state['cleaned']=True;return subprocess.CompletedProcess(args,0,cid,'')
  if args[:2]==['docker','inspect']:
   if state.get('cleaned'):return subprocess.CompletedProcess(args,1,'','Error: no such object: '+cid)
   actual={'Id':cid,'Name':f'/sf-dimension-scip3600-n{n}-'+frozen['request']['nonce'],'Image':r.IMAGE_ID,
    'NanoCpus':(2 if fault=='CPU'else 16)*10**9,'Memory':32*1024**3,'PidsLimit':256,'NetworkMode':'none','Privileged':False,
    'CapDrop':['ALL'],'CapAdd':['DAC_OVERRIDE'],'SecurityOpt':['no-new-privileges'],'Mounts':[{'Type':'bind','Source':str(bundle),'Destination':'/app','RW':True}],
    'User':'0','WorkingDir':'/app','Entrypoint':['/usr/bin/python3'],'Cmd':['/app/run.py'],
    'State':{'Status':'exited'if state.get('attached')else'created','Running':False,'ExitCode':0,'OOMKilled':False}}
   return subprocess.CompletedProcess(args,0,json.dumps(actual),'')
  raise AssertionError(args)
 def attach(args,stdout,stderr,timeout):
  assert timeout==3720;state['attached']=True;stdout.write_text('Mock only\n');stderr.write_text('')
  winner={pid:int(i==0)for i,pid in enumerate(matrix(n)['project_ids'])}
  params={'limits/time':3600.0,'limits/gap':0.0,'limits/absgap':0.0,'parallel/maxnthreads':16,'lp/threads':16,'numerics/feastol':1e-9}
  result={'checked_optimal':fault!='limited','completed':True,'raw_status':'timelimit'if fault=='limited'else'optimal','plan':winner,'objective_pence':7,'exclude_plan':None,'model_sha256':frozen['model_canonical_sha256'],
   'specification_sha256':'1'*64,'universe_sha256':'2'*64,'parameters':params,'default_feasibility_tolerance':1e-6,'feasibility_tolerance_changed':True,
   'declared_feasibility_tolerance':1e-9,'applied_feasibility_tolerance':1e-6 if fault=='tolerance' else 1e-9}
  result.update(native_solution_values=list(winner.values()),native_objective=7.0,primal_bound=7.0,dual_bound=7.0,gap=0.0)
  result['native_bound_precision']=backend.bound_diagnostics(result)
  dump(bundle/'solver_result.json',result);dump(bundle/'runtime_result.json',{'completed':True,'backend':'scip','financial_forward_executed':False,'model_canonical_sha256':frozen['model_canonical_sha256'],'threads':16,'gap_requested':0,'distribution_versions':r.DISTRIBUTIONS})
  for name in ('solver.log','native_model.cip'):(bundle/name).write_text('Mock native artifact\n')
  return subprocess.CompletedProcess(args,0)
 monkeypatch.setattr(r,'_command',command);monkeypatch.setattr(r,'_attach',attach)
 if fault in ('CPU','tolerance'):
  with pytest.raises(r.OptimizationRuntimeError)as error:r.execute_prepared(output)
  assert entry.read(error.value.receipt)['status']=='execution_failed'
 else:
  record=r.execute_prepared(output);checked=e.validate_solver_receipt(job,record,model=model,backend='scip')
  assert checked['checked_optimal'] is (fault is None)
  assert checked['matrix_result_check']['exact_matrix_plan_check']['all_integer_rows_checked']==761+n//2
 assert state['cleaned'] and state['released'] and state['stopped'] and state['closed']
 with pytest.raises(ValueError):r.execute_prepared(output)


@pytest.mark.parametrize('n',[720,1080])
@pytest.mark.parametrize('limited,tie',[(False,False),(True,False),(False,True)])
def test_new_scip_best_then_full_winner_runner_once_with_no_density_gate(n,limited,tie,tmp_path,monkeypatch):
 e=entry.experiment(n);r=e.runtime;output=tmp_path/'reference';output.mkdir();ids=[f'P{i:03d}'for i in range(1,n+1)]
 winner={pid:int(i==0)for i,pid in enumerate(ids)};runner={pid:int(i==1)for i,pid in enumerate(ids)}
 boundary=dump(tmp_path/'fake.json',{'mock_boundary':True});finance={'terminal':boundary,'specification':boundary,'raw_preparation':boundary,'universe_A':boundary,'universe_B':boundary,'models':{'A':boundary,'B':boundary},'public':{'project_ids':ids},'A':{},'B':{}}
 frozen={'best_preparation':dump(output/'jobs/best/preparation.json',{'phase':'best'}),'private_density_gate':{'required':False,'public_cardinality_constraint':False},'recipe':{}}
 dump(output/'preparation.json',{'explicit_mock':True});monkeypatch.setattr(e,'validate_prepared',lambda _:(frozen,finance));calls=[]
 def prepare(model,folder,**kwargs):
  assert kwargs['backend']=='scip' and kwargs['time_limit_seconds']==3600 and kwargs['exclude_plan']==winner
  calls.append('prepare_runner');return dump(folder/'preparation.json',{'phase':'runner'})
 def execute(folder):
  phase=entry.read(folder/'preparation.json')['phase'];calls.append(phase);return dump(folder/'terminal.json',{'phase':phase})
 def checked(job,terminal,actual,excluded):
  phase=entry.read(job)['phase'];assert excluded==(None if phase=='best'else winner)
  if limited and phase=='best':raise ValueError('FEASIBLE is preserved; no runner')
  return {'checked_optimal':True,'solver':{'plan':winner if phase=='best'else runner,'objective_pence':100 if phase=='best'or tie else 99}},{}
 monkeypatch.setattr(r,'prepare',prepare);monkeypatch.setattr(r,'execute_prepared',execute);monkeypatch.setattr(e,'_checked_job',checked);monkeypatch.setattr(e,'_financial',lambda *args:{'passed':True});services(monkeypatch)
 result=e.read(e.execute_prepared(output));assert result['passed'] is (not limited and not tie)
 assert calls==(['best']if limited else ['best','prepare_runner','runner'])
 if result['passed']:
  assert result['selected_project_count']==1 and result['selection_density_not_required'] is True
  assert result['model_A']==finance['models']['A'] and result['model_B']==finance['models']['B']
 with pytest.raises(ValueError):e.execute_prepared(output)


def test_both_contracts_and_all_four_matrices_frozen_before_first_job_prepare(tmp_path,monkeypatch):
 source=dump(tmp_path/'source.json',{});raw=[];case_refs=[]
 for n,seed in [(720,202710720),(1080,202711080)]:
  specification=dump(tmp_path/f'spec{n}.json',{'n':n});plans=dump(tmp_path/f'plans{n}.json',{'18':True})
  row={'id':f'L{n}-D01','projects':n,'seed':seed,'revenue_jitter_pence':150000,'specification':specification,'diagnostic_plans':plans};raw.append(row)
  case_refs.append(dump(tmp_path/f'case{n}.json',{'id':row['id'],'passed':True,'raw_specification':specification,'diagnostic_plans':plans,'records':{'model_A':dump(tmp_path/f'A{n}.json',{'A':n}),'model_B':dump(tmp_path/f'B{n}.json',{'B':n})}}))
 corrected=dump(tmp_path/'corrected.json',{'preparation':source,'profile_terminals':case_refs});handoff=dump(tmp_path/'handoff.json',{'corrected_terminal':corrected})
 monkeypatch.setattr(entry.prior_reference,'_probe_entry',lambda:SimpleNamespace(validate_prepared=lambda _:{'profiles':raw}));monkeypatch.setattr(entry,'recipes',lambda:{})
 output=tmp_path/'pair';calls=[]
 def experiment(n):
  def prepare(source,folder):
   frozen=entry.read(output/'prospective.json');assert len(frozen['common_candidates_frozen_before_any_native_preparation'])==2
   assert all(r['full_model_A']!=r['full_model_B']for r in frozen['common_candidates_frozen_before_any_native_preparation'])
   calls.append(n);return dump(folder/'preparation.json',{'mock':True})
  return SimpleNamespace(prepare=prepare)
 monkeypatch.setattr(entry,'experiment',experiment)
 result=entry.read(entry.prepare(handoff['path'],output));assert calls==[720,1080] and result['solver_calls']==0
 with pytest.raises(ValueError):entry.prepare(handoff['path'],output)

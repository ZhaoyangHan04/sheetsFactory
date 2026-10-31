"""N720600 contracts and portable namespace; native/search/UI are mocked."""
from copy import deepcopy
import importlib,importlib.util,json,shutil,subprocess,sys
from pathlib import Path
from types import ModuleType
import pytest
from sheets_factory.workbook.linear_capital_n720_reference import adapter,spec,model_a,model_b,runtime,reference as entry
from sheets_factory.workbook.linear_capital_scaled import model_b as old_model,optimization_runtime as old_runtime
from sheets_factory.workbook import linear_capital_dimension_probe as probe
from test_linear_capital_optimization_runtime import services


def dump(path,value):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value)+'\n');return runtime.reference(path)


def matrix():
 rows=[]
 for family,count in spec.PRODUCTION_COUNTS.items():
  for i in range(count):rows.append({'id':f'{family}:{i:04d}','family':family,'scenario_id':None,'year':None,'coefficients':[0]*720,'limit':0})
 for r in rows:
  if r['family']=='initial_sponsor_equity':r['coefficients'][:2]=[2,1];r['limit']=2
 return {'kind':adapter.MODEL_KIND,'version':3,'project_ids':list(spec.PROJECT_IDS),'objective_pence':[7,4]+[0]*718,
  'rows':sorted(rows,key=lambda r:r['id']),'specification_sha256':'1'*64,'universe_sha256':'2'*64}


@pytest.fixture(autouse=True)
def never_native_or_services(monkeypatch):
 def forbidden(*a,**kw):raise AssertionError('No native optimizer/service call in tests')
 monkeypatch.setattr(subprocess,'run',forbidden);monkeypatch.setattr(subprocess,'Popen',forbidden)
 monkeypatch.setattr(model_b,'_solver',forbidden)


def test_schema_and_solver_algorithm_are_unchanged_except_fixed_dimension():
 public=probe.bundle(720).catalog.build_spec();assert spec.load_spec(public)==public
 assert model_b.solve_cp_sat.__code__.co_code==old_model.solve_cp_sat.__code__.co_code
 assert model_b.solve_cp_sat.__code__.co_consts==old_model.solve_cp_sat.__code__.co_consts
 assert model_b.solve_cp_sat.__globals__ is not old_model.solve_cp_sat.__globals__
 assert not hasattr(model_a,'build_model') and not hasattr(model_b,'build_model')
 assert old_runtime.MODEL_KIND=='linear_capital_scaled_direct_binary_integer_model'
 assert old_runtime.profile_reference()['path'].endswith('linear_capital_reference_producer_v1.json')
 assert json.loads(old_runtime.PROFILE.read_text())['producer']['solver_seconds_per_attempt']==3600
 policy=json.loads(runtime.PROFILE.read_text());assert policy['producer']['solver_seconds_per_attempt']==600
 assert policy['producer']['cpus']==policy['producer']['threads']==16 and policy['producer']['automatic_retries']==0


@pytest.mark.parametrize('change',['old_kind','old_version','old_N360','row_missing','wrong_family','overflow','incomplete_vector'])
def test_full_matrix_guard_rejects_schema_dimension_or_integer_damage(change):
 value=matrix()
 if change=='old_kind':value['kind']=old_runtime.MODEL_KIND
 elif change=='old_version':value['version']=2
 elif change=='old_N360':
  value['project_ids']=value['project_ids'][:360];value['objective_pence']=value['objective_pence'][:360]
  for r in value['rows']:r['coefficients']=r['coefficients'][:360]
 elif change=='row_missing':value['rows'].pop()
 elif change=='wrong_family':value['rows'][0]['family']='resource'
 elif change=='overflow':value['objective_pence'][0]=2**53
 else:value['rows'][-1]['coefficients'].pop()
 with pytest.raises(ValueError):runtime.validate_model(value)


@pytest.fixture
def prepared(tmp_path,monkeypatch):
 vendor=tmp_path/'vendor';vendor.mkdir();(vendor/'dummy.py').write_text('# Explicit no-native fixture\n')
 monkeypatch.setattr(runtime,'VENDOR_SITE_PACKAGES',vendor)
 monkeypatch.setattr(runtime,'VENDOR_ROOTS',{'dummy.py'})
 record=dump(tmp_path/'matrix.json',matrix());output=tmp_path/'job'
 receipt=runtime.prepare(record['path'],output,backend='cp_sat',time_limit_seconds=600,vendor_site_packages=vendor)
 return output,receipt,record


def test_prepare_binds_exact_n720_resource_native_closure_without_execution(prepared):
 output,receipt,record=prepared;frozen=runtime.validate_prepared(output)
 assert frozen['version']==3 and frozen['request']['time_limit_seconds']==600 and frozen['request']['threads']==16
 assert frozen['resources']=={'cpus':16,'memory_bytes':32*1024**3,'pids_limit':256}
 assert frozen['operational_timeout_seconds']==720 and frozen['network']=='none'
 assert frozen['producer_profile']==runtime.profile_reference() and frozen['solver_calls']==frozen['model_calls']==0
 assert set(frozen['source_code'])==set(runtime.SOURCE_NAMES) and len(frozen['source_code'])==10
 assert not (output/'started.json').exists()


def test_complete_portable_native_import_with_only_frozen_bundle(prepared):
 output,_,_=prepared;package=output/'job_bundle/portfolio';name='_portable_n720_fixture'
 module=ModuleType(name);module.__path__=[str(package)];sys.modules[name]=module
 try:
  a=importlib.import_module(name+'.model_a');b=importlib.import_module(name+'.model_b');s=importlib.import_module(name+'.spec')
  assert a.KIND==b.MODEL_KIND==adapter.MODEL_KIND and len(s.PROJECT_IDS)==720
  a.validate_model(matrix());b.validate_model(matrix())
  assert name+'.finance' not in sys.modules and name+'.candidate_a' not in sys.modules and name+'.ledger' not in sys.modules
 finally:
  for key in list(sys.modules):
   if key==name or key.startswith(name+'.'):del sys.modules[key]


@pytest.mark.parametrize('change',['time','threads','resources','profile','native_source'])
def test_prepared_job_drift_cannot_reach_execution(prepared,change):
 output,receipt,_=prepared;value=entry.read(receipt)
 if change=='time':value['request']['time_limit_seconds']=3600
 elif change=='threads':value['request']['threads']=2
 elif change=='resources':value['resources']['cpus']=2
 elif change=='profile':value['producer_profile']['sha256']='0'*64
 else:(output/'job_bundle/portfolio/frozen_scaled_model_b.py').unlink()
 Path(receipt['path']).write_text(json.dumps(value))
 with pytest.raises(ValueError):runtime.validate_prepared(output)


def mocked_native(prepared,monkeypatch,*,limited=False,unknown=False,fault=None):
 output,receipt,model=prepared;state=services(monkeypatch);frozen=runtime.validate_prepared(output);bundle=output/'job_bundle';cid='a'*64
 def command(args,*,timeout=30):
  if args[:3]==['docker','image','inspect']:return subprocess.CompletedProcess(args,0,runtime.IMAGE_ID+'\n','')
  if args[:2]==['docker','create']:
   assert args[args.index('--cpus')+1]=='16' and args[args.index('--memory')+1]==str(32*1024**3)
   return subprocess.CompletedProcess(args,0,cid+'\n','')
  if args[:2]==['docker','rm']:state['cleaned']=True;return subprocess.CompletedProcess(args,0,cid,'')
  if args[:2]==['docker','inspect']:
   if state.get('cleaned'):return subprocess.CompletedProcess(args,1,'','Error: no such object')
   actual={'Id':cid,'Name':'/sf-n720-reference600-'+frozen['request']['nonce'],'Image':runtime.IMAGE_ID,
    'NanoCpus':(2 if fault=='CPU' else 16)*10**9,'Memory':32*1024**3,'PidsLimit':256,'NetworkMode':'none','Privileged':False,
    'CapDrop':['ALL'],'CapAdd':['DAC_OVERRIDE'],'SecurityOpt':['no-new-privileges'],'Mounts':[{'Type':'bind','Source':str(bundle),'Destination':'/app','RW':True}],
    'User':'0','WorkingDir':'/app','Entrypoint':['/usr/bin/python3'],'Cmd':['/app/run.py'],
    'State':{'Status':'exited' if state.get('attached') else 'created','Running':False,'ExitCode':0,'OOMKilled':False}}
   return subprocess.CompletedProcess(args,0,json.dumps(actual),'')
  raise AssertionError(args)
 def attach(args,stdout,stderr,timeout):
  assert timeout==720;state['attached']=True;stdout.write_text('Mock only\n');stderr.write_text('')
  winner={pid:int(i==0 or fault=='row' and i==1) for i,pid in enumerate(spec.PROJECT_IDS)}
  result={'checked_optimal':not (limited or unknown),'status':'UNKNOWN' if unknown else 'FEASIBLE' if limited else 'OPTIMAL','plan':None if unknown else winner,
   'objective_pence':None if unknown else 11 if fault=='row' else 7,'exclude_plan':None,'model_sha256':frozen['model_canonical_sha256'],
   'specification_sha256':'1'*64,'universe_sha256':'2'*64,'gap_parameters':{'relative':0,'absolute':0},'threads':2 if fault=='workers' else 16,'time_limit_seconds':600}
  dump(bundle/'solver_result.json',result)
  dump(bundle/'runtime_result.json',{'completed':True,'backend':'cp_sat','financial_forward_executed':False,'model_canonical_sha256':frozen['model_canonical_sha256'],
   'threads':16,'gap_requested':0,'distribution_versions':runtime.DISTRIBUTIONS})
  for n in ('solver.log','native_model.pbtxt','native_model.pbtxt.parameters.pbtxt'):(bundle/n).write_text('Mock native artifact\n')
  return subprocess.CompletedProcess(args,0)
 monkeypatch.setattr(runtime,'_command',command);monkeypatch.setattr(runtime,'_attach',attach)
 return state


def test_mocked_full_runtime_resource_cleanup_and_exact1121_row_gate(prepared,monkeypatch):
 state=mocked_native(prepared,monkeypatch);output,job,model=prepared;record=runtime.execute_prepared(output)
 checked=entry.validate_solver_receipt(job,record,model=model,backend='cp_sat')
 assert checked['checked_optimal'] and checked['matrix_result_check']['exact_matrix_plan_check']['all_integer_rows_checked']==1121
 assert state['cleaned'] and state['released'] and state['stopped'] and state['closed']
 with pytest.raises(ValueError):runtime.execute_prepared(output)


@pytest.mark.parametrize('fault',['CPU','workers','row'])
def test_mocked_actual_resource_or_primal_damage_is_preserved_failure(prepared,monkeypatch,fault):
 state=mocked_native(prepared,monkeypatch,fault=fault)
 with pytest.raises(runtime.OptimizationRuntimeError) as error:runtime.execute_prepared(prepared[0])
 assert entry.read(error.value.receipt)['status']=='execution_failed' and state['cleaned']


@pytest.mark.parametrize('unknown',[False,True])
def test_feasible_or_unknown_native_status_stays_nonoptimal(prepared,monkeypatch,unknown):
 mocked_native(prepared,monkeypatch,limited=not unknown,unknown=unknown);receipt=runtime.execute_prepared(prepared[0])
 assert entry.read(receipt)['status']=='reference_not_proven_optimal'
 checked=entry.validate_solver_receipt(prepared[1],receipt,model=prepared[2],backend='cp_sat')
 assert checked['checked_optimal'] is False
 assert checked['solver']['status']==('UNKNOWN' if unknown else 'FEASIBLE')


@pytest.mark.parametrize('limited,tie',[(False,False),(True,False),(False,True)])
def test_outer_best_then_complete_excluded_runner_exactly_once(tmp_path,monkeypatch,limited,tie):
 output=tmp_path/'reference';output.mkdir();ids=list(spec.PROJECT_IDS);winner={pid:int(i<300) for i,pid in enumerate(ids)}
 runner=deepcopy(winner);runner['P001']=0;boundary=dump(tmp_path/'fake_finance.json',{'explicit_mock_boundary':True})
 finance={'terminal':boundary,'specification':boundary,'raw_preparation':boundary,'universe_A':boundary,'universe_B':boundary,
  'models':{'A':boundary,'B':boundary},'public':{'project_ids':ids},'A':{},'B':{}}
 frozen={'best_preparation':dump(output/'jobs/best/preparation.json',{'phase':'best'}),
  'private_density_gate':{'minimum':240,'maximum':480,'public_cardinality_constraint':False},'recipe':{}}
 dump(output/'preparation.json',{'explicit_offline_fixture':True});monkeypatch.setattr(entry,'validate_prepared',lambda _:(frozen,finance));calls=[]
 def prepare(model,folder,**kwargs):
  assert kwargs['exclude_plan']==winner and kwargs['time_limit_seconds']==600 and kwargs['backend']=='cp_sat'
  calls.append('prepare_runner');return dump(folder/'preparation.json',{'phase':'runner'})
 def execute(folder):
  phase=entry.read(folder/'preparation.json')['phase'];calls.append(phase);return dump(folder/'terminal.json',{'phase':phase})
 def checked(job,terminal,actual,excluded):
  phase=entry.read(job)['phase'];assert excluded==(None if phase=='best' else winner)
  if phase=='best' and limited:raise ValueError('Preserved FEASIBLE/UNKNOWN/limit mock')
  return {'checked_optimal':True,'solver':{'plan':winner if phase=='best' else runner,'objective_pence':100 if phase=='best' or tie else 99}},{}
 monkeypatch.setattr(runtime,'prepare',prepare);monkeypatch.setattr(runtime,'execute_prepared',execute)
 monkeypatch.setattr(entry,'_checked_job',checked);monkeypatch.setattr(entry,'_financial',lambda *a:{'passed':True});services(monkeypatch)
 result=entry.read(entry.execute_prepared(output));assert result['passed'] is (not limited and not tie)
 assert result['version']==3 and result['qualified'] is False
 assert calls==(['best'] if limited else ['best','prepare_runner','runner'])
 if not limited:assert entry.read(output/'runner_preparation.json')['complete_excluded_plan']==winner
 with pytest.raises(ValueError):entry.execute_prepared(output)


def test_nonprobe_finance_cannot_be_reinterpreted_as_n720_reference(tmp_path):
 fake=dump(tmp_path/'old.json',{'kind':'linear_capital_scaled_full_financial_crosscheck','version':2,'passed':True})
 with pytest.raises(ValueError):entry._checked_finance(fake)

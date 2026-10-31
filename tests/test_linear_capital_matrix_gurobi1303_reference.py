"""Pure matrix/fake-native/fake-Docker boundaries; no native solver or service."""
import ast
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace as NS,ModuleType
import zipfile
import pytest
from sheets_factory.workbook.linear_capital_gurobi_reference import backend as b,runtime as r


def matrix(n=2):
    rows=[{'id':'budget','family':'budget','scenario_id':None,'year':None,'coefficients':[1]*n,'limit':1}]
    if n>=360:
        counts=dict(zip(('initial_sponsor_equity','annual_new_lp','annual_debt_close','resource','region_exposure','sector_exposure','exclusivity','prerequisite'),(1,60,60,360,120,160,n//6,n//3)))
        rows=[{'id':f'{family}-{i:03d}','family':family,'scenario_id':None,'year':None,'coefficients':[0]*n,'limit':0} for family,count in counts.items() for i in range(count)]
        rows.sort(key=lambda x:x['id'])
    return {'kind':'linear_capital_scaled_direct_binary_integer_model' if n<=360 else f'linear_capital_dimension_probe_direct_binary_integer_model_n{n}',
        'version':2 if n<=360 else 3,'project_ids':[f'P{i:03d}' for i in range(1,n+1)],'objective_pence':[100+i for i in range(n)],'rows':rows,'specification_sha256':'a'*64,'universe_sha256':'b'*64}


def exact_result(model=None,plan=None,exclude=None):
    model=matrix() if model is None else model;plan={'P001':0,'P002':1} if plan is None else plan
    rep=b.representation(model);objective=b.check_plan(model,plan)['objective_pence'];params={**b.PARAMETERS,'TimeLimit':10.0}
    return {'backend':'gurobi','model_sha256':b.sha(model),'specification_sha256':model['specification_sha256'],'universe_sha256':model['universe_sha256'],
        'solver_version':'13.0.3','scaling':'none','solver_representation':rep,'plan':plan,'objective_pence':objective,
        'applied_parameters':params,'full_native_parameters':{k:{'value':v} for k,v in params.items()},'time_limit_seconds':10,'threads':16,
        'exclude_plan':exclude,'warm_start':None,'known_feasible_plans':{},'reference_admission':False,'independent_CP_exact_proof_pending':True,
        'checked_optimal':True,'status':'OPTIMAL','completed':True,'gap_parameters':{'relative':0,'absolute':0},
        'native':{'status':2,'sol_count':1,'NumVars':len(model['project_ids']),'NumConstrs':len(model['rows'])+(exclude is not None),
            'X':[plan[k] for k in model['project_ids']],'C':rep['objective_coefficients'],'ObjVal':objective,'ObjBound':objective,'ObjBoundC':objective,'MIPGap':0.0}}


@pytest.mark.parametrize('n,rows',[(360,941),(720,1121),(1080,1301)])
def test_complete_dimensions(n,rows):
    m=matrix(n);assert b.validate_model(m) is m and len(m['rows'])==rows
    m['rows'].pop()
    with pytest.raises(ValueError):b.validate_model(m)


@pytest.mark.parametrize('value',[True,1.0,None])
def test_strict_binary_plan(value):
    with pytest.raises(ValueError):b.check_plan(matrix(),{'P001':value,'P002':0})


def test_all_integer_rows_and_independent_matrix_parity():
    m=matrix();assert not b.check_plan(m,{'P001':1,'P002':1})['feasible']
    other=deepcopy(m);other['universe_sha256']='c'*64;assert b.compare_models(m,other)['passed']
    other['rows'][0]['limit']=2
    with pytest.raises(ValueError):b.compare_models(m,other)
    with pytest.raises(ValueError):b.check_plan(m,{'P001':1})


def test_positive_integer_scaling_preserves_entire_original_matrix():
    m=matrix();m['rows'][0].update(coefficients=[12,-24],limit=36);m['objective_pence']=[20,30]
    rep=b.representation(m,'integer_gcd');assert rep['rows'][0]['coefficients']==[1,-2] and rep['rows'][0]['limit']==3
    assert rep['objective_coefficients']==[2,3] and rep['objective_positive_integer_divisor']==10 and rep['omitted_original_rows']==0
    assert m['rows'][0]['coefficients']==[12,-24]
    with pytest.raises(ValueError):b.representation(m,'float_threshold')


def test_scaled_native_bounds_are_reconciled_to_raw_pence_exactly():
    m=matrix();m['objective_pence']=[20,30];x=exact_result(m);rep=b.representation(m,'integer_gcd')
    x.update(scaling='integer_gcd',solver_representation=rep)
    x['native'].update(C=rep['objective_coefficients'],ObjVal=3.0,ObjBound=3.0,ObjBoundC=3.0)
    assert b.strict_evidence(m,x)['passed']
    x['native']['ObjBoundC']=2.999999999
    assert not b.strict_evidence(m,x)['passed']


def test_native_exact_still_does_not_open_reference_gate():
    e=b.strict_evidence(matrix(),exact_result());assert e['passed'] and not e['reference_admission'] and e['independent_CP_exact_proof_pending']


@pytest.mark.parametrize('change,expected',[
    (lambda x:x['native'].update(X=[0,0.999999999]),'native_X_not_strict_binary'),
    (lambda x:x['native'].update(ObjBound=101.0000001),'native_ObjBound_not_exact_raw_objective'),
    (lambda x:x['native'].update(ObjBoundC=102),'native_ObjBoundC_not_exact_raw_objective'),
    (lambda x:x['native'].update(status=9),'native_not_OPTIMAL'),
    (lambda x:x['native'].update(MIPGap=1e-8),'native_gap_not_zero'),
    (lambda x:x['native'].update(C=[100,102]),'native_C_changed'),
    (lambda x:x['applied_parameters'].update(MIPGap=1e-4),'applied_parameters_changed'),
    (lambda x:x.pop('full_native_parameters'),'full_native_parameters_missing_or_changed'),
    (lambda x:x['native'].update(NumConstrs=2),'native_geometry_changed'),
    (lambda x:x.update(reference_admission=True),'reference_claim_boundary_changed'),
    (lambda x:x.update(exclude_plan={'P001':1,'P002':0}),'complete_exclusion_binding_changed')])
def test_strict_native_rejections(change,expected):
    x=exact_result();change(x);assert expected in b.strict_evidence(matrix(),x)['failures']


def test_false_OPTIMAL_with_higher_exact_feasible_counterexample_is_rejected():
    m=matrix();x=exact_result(m,{'P001':1,'P002':0});known={'predeclared_winner':{'P001':0,'P002':1}}
    e=b.strict_evidence(m,x,known_feasible_plans=known)
    assert not e['passed'] and 'known_feasible_counterexample:predeclared_winner' in e['failures']
    ex={'P001':0,'P002':1};x=exact_result(m,{'P001':1,'P002':0},ex)
    assert b.strict_evidence(m,x,ex,known)['passed']
    with pytest.raises(ValueError):b.strict_evidence(m,x,known_feasible_plans=[])


def test_positive_gap_is_required_but_never_sufficient_for_admission():
    m=matrix();winner=exact_result(m);runner=exact_result(m,{'P001':1,'P002':0},winner['plan'])
    check=b.check_best_runner(m,winner,runner)
    assert check['gap_pence']==1 and not check['reference_admission'] and check['independent_CP_exact_proof_pending']
    equal=matrix();equal['objective_pence']=[101,101]
    with pytest.raises(ValueError):b.check_best_runner(equal,exact_result(equal),exact_result(equal,{'P001':1,'P002':0},{'P001':0,'P002':1}))
    runner['exclude_plan']={'P001':0,'P002':0}
    with pytest.raises(ValueError):b.check_best_runner(m,winner,runner)


@pytest.fixture
def public_wheel(tmp_path,monkeypatch):
    wheel=tmp_path/'public.whl'
    with zipfile.ZipFile(wheel,'w') as z:
        z.writestr('gurobipy/.libs/gurobi.lic','FAKE PUBLIC FIXTURE ONLY')
        z.writestr('gurobipy/_core.cpython-312-x86_64-linux-gnu.so','FAKE NEVER LOADED')
        z.writestr('gurobipy-13.0.3.dist-info/WHEEL','Tag: cp312-cp312-manylinux2014_x86_64\n')
    monkeypatch.setattr(r,'WHEEL_SHA',hashlib.sha256(wheel.read_bytes()).hexdigest());monkeypatch.setattr(r,'WHEEL_BYTES',wheel.stat().st_size)
    return wheel


@pytest.fixture
def prepared(tmp_path,public_wheel,monkeypatch):
    def forbidden(*a,**k):raise AssertionError('No actual process/native service in pure preparation')
    monkeypatch.setattr(subprocess,'run',forbidden);monkeypatch.setattr(subprocess,'Popen',forbidden)
    a=tmp_path/'A.json';other=tmp_path/'B.json';m=matrix();a.write_text(json.dumps(m));m['universe_sha256']='c'*64;other.write_text(json.dumps(m))
    out=tmp_path/'job';r.prepare(a,other,out,time_limit_seconds=10,wheel=public_wheel,known_feasible_plans={'known':{'P001':0,'P002':1}})
    return out


def test_prepare_cold_is_no_services_no_host_vendor_extraction(prepared):
    f=r.validate_prepared(prepared);assert f['request']['threads']==16 and f['resources']['cpus']==16 and f['reference_admission'] is False
    assert set((prepared/'job_bundle').iterdir())=={prepared/'job_bundle'/p for p in ('model.json','independent_model_B.json','vendor.whl','portfolio','run.py','job.json','inventory.json')}
    assert not (prepared/'job_bundle/vendor').exists() and f['request']['known_feasible_plans']
    assert 'gurobipy' not in sys.modules
    with pytest.raises(ValueError):r.prepare(f['model_input']['path'],f['independent_model_B']['path'],prepared,wheel=f['vendor_source'])


def test_preparation_rejects_changed_bytes(prepared):
    with (prepared/'job_bundle/model.json').open('ab') as f:f.write(b' ')
    with pytest.raises(ValueError):r.validate_prepared(prepared)


def test_warm_hint_must_be_feasible_in_both_raw_matrices(tmp_path,public_wheel):
    a=tmp_path/'a';c=tmp_path/'b';m=matrix();a.write_text(json.dumps(m));c.write_text(json.dumps(m))
    with pytest.raises(ValueError):r.prepare(a,c,tmp_path/'bad',wheel=public_wheel,warm_start={'P001':1,'P002':1})
    assert not (tmp_path/'bad').exists()


def test_real_wheel_bytes_metadata_only():
    assert r.check_wheel()['sha256']=='34f0b9528edfbf29e96a74e0b69b8cc832375d43342d6376754fd436c570bb2a'
    assert 'gurobipy' not in sys.modules


def test_counted_resource_adapter_preserves_lifecycle_and_runtime_safety():
    text=ast.unparse(r.adapted_ast());assert "'--cpus', '16'" in text and "'--pids-limit', '256'" in text
    assert "'--network', 'none'" in text and "'--volume', str(bundle) + ':/app:rw'" in text
    assert 'PYTHONNOUSERSITE=1' in text and 'progress.stop()' in text and '_cleanup_owned(owned)' in text
    assert "not (output / 'started.json').exists()" in text
    code=ast.parse(r.RUNNER);imports=[n for n in ast.walk(code) if isinstance(n,(ast.Import,ast.ImportFrom))]
    assert any(isinstance(n,ast.Import) and any(a.name=='gurobipy' for a in n.names) for n in imports)
    assert "dir='/tmp'" in r.RUNNER and "os.environ['GRB_LICENSE_FILE']=str(license_path)" in r.RUNNER
    assert 'pip install' not in r.RUNNER and 'read_text' not in r.RUNNER.split('license_path=')[1].split('sys.path')[0]


class FakeVar:
    def __init__(self,name):self.name=name;self.X=0.0;self.Obj=0.0
class FakeExpr:
    def __init__(self,a,x):self.a=a;self.x=x
    def __le__(self,limit):return self,limit


def test_one_mock_native_call_and_full_artifacts(tmp_path,monkeypatch):
    calls=[];model=matrix();expected=exact_result(model);defaults={**b.PARAMETERS,'TimeLimit':10.0}
    class Env:
        def __init__(self,empty):assert empty
        def setParam(self,k,v):calls.append(('env',k));Path(v).write_text('FAKE NATIVE LOG')
        def start(self):calls.append('env_start')
        def dispose(self):calls.append('env_dispose')
    class Native:
        def __init__(self,*a,**k):self.params=dict(defaults);self.x=[];self.rows=[]
        def setParam(self,k,v):self.params[k]=v
        def getParamInfo(self,k):return k,type(self.params[k]),self.params[k],0,1e100,0
        def addVar(self,vtype,name):v=FakeVar(name);self.x.append(v);return v
        def update(self):pass
        def setObjective(self,e,sense):
            assert sense==1
            for v,c in zip(e.x,e.a):v.Obj=float(c)
        def addConstr(self,e,name):self.rows.append((e,name))
        def write(self,p):Path(p).write_text('FAKE MPS/PARAMETERS')
        def optimize(self):
            calls.append('optimize');self.x[1].X=1.0;self.Status=2;self.SolCount=1;self.NumVars=2;self.NumConstrs=1;self.Runtime=0.0;self.NodeCount=0;self.ObjVal=101.0;self.ObjBound=101.0;self.ObjBoundC=101.0;self.MIPGap=0.0
        def dispose(self):calls.append('model_dispose')
    fake=ModuleType('gurobipy');fake.Env=Env;fake.Model=Native;fake.LinExpr=FakeExpr;fake.gurobi=NS(version=lambda:(13,0,3));fake.GRB=NS(BINARY='B',MAXIMIZE=1,Param=NS(**{k:k for k in defaults}))
    monkeypatch.setitem(sys.modules,'gurobipy',fake)
    result=b.solve_gurobi(model,time_limit_seconds=10,log_path=tmp_path/'solver.log',model_path=tmp_path/'native.mps')
    assert result['checked_optimal'] and not result['reference_admission'] and calls.count('optimize')==1
    assert result['native']['C']==[100.0,101.0] and set(result['full_native_parameters'])==set(defaults)
    assert (tmp_path/'native.mps.parameters.prm').exists() and calls[-2:]==['model_dispose','env_dispose']


def test_full_fake_parameter_inventory_nonfinite_values_are_lossless_JSON_safe():
    import math,struct
    finite={**b.PARAMETERS,'TimeLimit':10.0}
    nan=struct.unpack('>d',bytes.fromhex('fff8000000000042'))[0]
    params=NS(**{k:k for k in finite},NodeLimit='NodeLimit')
    class FakeNative:
        def getParamInfo(self,key):
            return (key,float,finite[key] if key in finite else float('inf'),float('-inf'),float('inf'),nan)
    inventory=b._parameters(FakeNative(),NS(GRB=NS(Param=params)))
    saved=json.loads(b.canonical(inventory))
    for key,value in finite.items():assert saved[key]['value']==value and type(saved[key]['value']) in (int,float)
    for field,classification,hexvalue in [('value','positive_infinity','7ff0000000000000'),('minimum','negative_infinity','fff0000000000000'),('maximum','positive_infinity','7ff0000000000000'),('default','nan','fff8000000000042')]:
        encoded=saved['NodeLimit'][field]
        assert encoded['kind']=='nonfinite_native_parameter_float' and encoded['classification']==classification
        assert encoded['ieee754_binary64_hex']==hexvalue
        original=struct.unpack('>d',bytes.fromhex(hexvalue))[0]
        assert encoded['float_hex']==original.hex()
    assert math.isnan(struct.unpack('>d',bytes.fromhex(saved['NodeLimit']['default']['ieee754_binary64_hex']))[0])
    x=exact_result();x['full_native_parameters']=saved
    assert b.strict_evidence(matrix(),x)['passed']


def fake_inspect(cid,bundle,state):
    return {'Id':cid,'Name':'/sf-gurobi1303-research-'+json.loads((bundle/'job.json').read_text())['nonce'],'Image':r.policy()['image_id'],
        'NanoCpus':16*10**9,'Memory':32*1024**3,'PidsLimit':256,'NetworkMode':'none','Privileged':False,'User':'0',
        'CapDrop':['ALL'],'CapAdd':['DAC_OVERRIDE'],'SecurityOpt':['no-new-privileges'],'WorkingDir':'/app','Entrypoint':['/usr/bin/python3'],'Cmd':['/app/run.py'],
        'Mounts':[{'Type':'bind','Source':str(bundle),'Destination':'/app','RW':True}],
        'State':{'Status':state,'Running':False,'ExitCode':0,'OOMKilled':False}}


@pytest.mark.parametrize('wrong_absence_id',[False,True])
def test_fake_owned_lifecycle_and_complete_cold_validation(prepared,monkeypatch,wrong_absence_id):
    cid='d'*64;bundle=prepared/'job_bundle';events=[];state={'value':'created'}
    class Audit:
        def __init__(self,*a,**k):self.db=NS(close=lambda:events.append('audit_close'));self.snapshot=lambda:{};self.events=lambda:[]
        def update_run(self,**k):pass
        def record(self,*a,**k):return 'node'
        def update_record(self,*a,**k):pass
        def emit(self,*a,**k):pass
        def export(self):pass
    class Dashboard:
        def __init__(self,*a,**k):pass
        def start(self):events.append('dashboard');return 'http://fake-no-listener/'
        def stop(self):events.append('dashboard_stop')
    class Lease:
        def __init__(self,*a):pass
        def acquire(self):events.append('lease');return self
        def release(self):events.append('release')
    class Progress:
        def __init__(self,*a):self.errors=[]
        def start(self):pass
        def stop(self):return True
    for name,attrs in [('sheets_factory.core.audit',{'AuditStore':Audit}),('sheets_factory.dashboard',{'DashboardServer':Dashboard}),('sheets_factory.resume',{'ProducerLease':Lease})]:
        module=ModuleType(name);module.__dict__.update(attrs);monkeypatch.setitem(sys.modules,name,module)
    def command(cmd,**kw):
        events.append(tuple(cmd[:2]))
        if cmd[:3]==['docker','image','inspect']:return NS(returncode=0,stdout=r.policy()['image_id']+'\n',stderr='')
        if cmd[:2]==['docker','create']:return NS(returncode=0,stdout=cid+'\n',stderr='')
        if cmd[:2]==['docker','rm']:assert cmd[-1]==cid;return NS(returncode=0,stdout=cid+'\n',stderr='')
        if cmd[:2]==['docker','inspect']:assert cmd[2]==cid;return NS(returncode=1,stdout='',stderr='error: no such object: '+('e'*64 if wrong_absence_id else cid)+'\n')
        raise AssertionError(cmd)
    def attach(cmd,stdout,stderr,timeout):
        assert events[1]=='dashboard' and cmd==['docker','start','--attach',cid] and timeout==130
        stdout.write_bytes(b'FAKE COMPLETE STDOUT');stderr.write_bytes(b'');state['value']='exited'
        m=json.loads((bundle/'model.json').read_text());result=exact_result(m);result['known_feasible_plans']={'known':{'P001':0,'P002':1}}
        (bundle/'solver_result.json').write_text(json.dumps(result));(bundle/'native_model.mps').write_text('FAKE MPS');(bundle/'native_model.mps.parameters.prm').write_text('FAKE PARAMETERS');(bundle/'solver.log').write_text('FAKE LOG')
        (bundle/'runtime_result.json').write_text(json.dumps({'completed':True,'backend':'gurobi','threads':16,'gap_requested':0,'distribution_versions':{'gurobipy':'13.0.3'},'model_canonical_sha256':b.sha(m),'financial_forward_executed':False,'public_wheel_only':True}))
        return NS(returncode=0)
    monkeypatch.setitem(r._ns,'_command',command);monkeypatch.setitem(r._ns,'_inspect',lambda c:fake_inspect(c,bundle,state['value']));monkeypatch.setitem(r._ns,'_attach',attach);monkeypatch.setitem(r._ns,'_Progress',Progress)
    if wrong_absence_id:
        with pytest.raises(r.OptimizationRuntimeError) as error:r.execute_prepared(prepared)
        t=r._read(error.value.receipt['path']);assert t['status']=='execution_failed' and t['reference_admission'] is False
        assert (bundle/'solver_result.json').is_file() and (prepared/'owned_cleanup.json').is_file()
        with pytest.raises(ValueError):r.execute_prepared(prepared)
        with pytest.raises(ValueError):r.validate_completed(error.value.receipt)
        return
    terminal=r.execute_prepared(prepared);t=r.validate_completed(terminal)
    assert not t['reference_admission'] and t['status']=='native_candidate_consistent_not_reference_admitted' and t['actual_resources_verified']
    assert 'release' in events and ('docker','rm') in events and t['host_resource_evidence']
    with pytest.raises(ValueError):r.execute_prepared(prepared)
    (prepared/'host_after.json').write_text('{}')
    with pytest.raises(ValueError):r.validate_completed(terminal)

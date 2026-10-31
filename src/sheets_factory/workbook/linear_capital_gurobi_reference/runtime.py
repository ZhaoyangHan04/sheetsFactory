"""Opt-in offline wheel transport over the frozen producer resource lifecycle.

Preparation neither imports Gurobi nor contacts Docker. Native execution is an
explicit separate action; it mounts only the private matrix job. No financial
forward, image change, host install, private license, or gold admission occurs.
"""
from __future__ import annotations
import ast
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import stat
import uuid
import zipfile
from . import backend
from ..linear_capital_portfolio import producer_optimization_runtime as producer

ROOT=Path(__file__).resolve().parents[4]
BASE_SHA='fb1031c555fed919830a1f05fdb95bfa8912d2116fd6904801cfaba131a948ea'
PRODUCER_SHA='13958fd26b9b0318a04601fefc8c7b52f8df9fc64bb3f27100158eb26a6d4222'
WHEEL=ROOT/'outputs/research/gurobi1303_cp312_public_wheel_freeze_20261031T223100Z/gurobipy-13.0.3-cp312-cp312-manylinux2014_x86_64.manylinux_2_17_x86_64.whl'
WHEEL_SHA='34f0b9528edfbf29e96a74e0b69b8cc832375d43342d6376754fd436c570bb2a'
WHEEL_BYTES=14865983
PREPARATION_KIND='prepared_gurobi1303_matrix_research_job'
TERMINAL_KIND='completed_gurobi1303_matrix_research_job'
ARTIFACTS={'solver.log','native_model.mps','native_model.mps.parameters.prm','solver_result.json','runtime_result.json'}


def policy():
    return {'kind':'gurobi1303_restricted_matrix_research_policy','version':1,
        'image_id':'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043',
        'cpus':16,'threads':16,'memory_bytes':32*1024**3,'pids_limit':256,'network':'none',
        'maximum_solver_seconds':3600,'operational_extra_seconds':120,'automatic_retries':0,
        'wheel_version':'13.0.3','wheel_sha256':WHEEL_SHA,'wheel_bytes':WHEEL_BYTES,
        'abi':'cp312-cp312-manylinux2014_x86_64','license':'public_wheel_embedded_restricted_only',
        'license_cap_not_yet_runtime_verified':True,'maximum_variables':2000,'maximum_constraints_including_no_good':2000,
        'parameters':backend.PARAMETERS,'native_OPTIMAL_alone_is_reference_proof':False,
        'reference_admission':False,'independent_CP_exact_proof_pending':True,
        'source_quality_difficulty_inherited':False,'research_evaluation_only':True}


def recipes():
    paths=[Path(__file__),Path(backend.__file__),Path(producer.__file__),
        Path(producer.__file__).with_name('optimization_runtime.py'),ROOT/'scripts/run_linear_capital_gurobi_reference.py',
        ROOT/'src/sheets_factory/core/audit.py',ROOT/'src/sheets_factory/dashboard/__init__.py',ROOT/'src/sheets_factory/dashboard/server.py',ROOT/'src/sheets_factory/resume.py']
    return {str(p.relative_to(ROOT)):reference(p) for p in paths}


RUNNER=r'''import sys
sys.dont_write_bytecode=True
from pathlib import Path,PurePosixPath
import hashlib,importlib.metadata,json,os,platform,stat,tempfile,time,traceback,zipfile
root=Path('/app')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def canonical(v):return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
def verify():
 inv=json.loads((root/'inventory.json').read_text())
 for name,r in inv.items():
  p=root/name
  if p.is_symlink() or not p.is_file() or sha(p)!=r['sha256'] or p.stat().st_size!=r['bytes']:raise ValueError('Immutable private input changed')
 return inv
start=time.monotonic()
try:
 if sys.version_info[:2]!=(3,12) or platform.machine()!='x86_64':raise ValueError('Pinned CPython3.12 x86_64 ABI required')
 inv=verify()
 if {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file()}!=set(inv)|{'inventory.json'}:raise ValueError('Unexpected private job file')
 job=json.loads((root/'job.json').read_text());model=json.loads((root/'model.json').read_text())
 if sha(root/'vendor.whl')!=job['wheel_sha256']:raise ValueError('Pinned public wheel changed')
 with tempfile.TemporaryDirectory(prefix='sf-gurobi-public-',dir='/tmp') as temporary:
  vendor=Path(temporary)/'vendor';vendor.mkdir()
  with zipfile.ZipFile(root/'vendor.whl') as archive:
   seen=set()
   for info in archive.infolist():
    name=PurePosixPath(info.filename)
    if name.is_absolute() or '..' in name.parts or '\\' in info.filename or info.filename in seen or stat.S_ISLNK(info.external_attr>>16):raise ValueError('Unsafe wheel member')
    seen.add(info.filename)
    target=vendor/name
    if info.is_dir():target.mkdir(parents=True,exist_ok=True)
    else:target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(archive.read(info))
  # Discard credential environment names without reading/forwarding their values.
  for key in list(os.environ):
   if key.startswith(('GRB_','GUROBI_','WLS')):os.environ.pop(key,None)
  license_path=vendor/'gurobipy/.libs/gurobi.lic'
  if not license_path.is_file():raise ValueError('Public embedded restricted license absent')
  os.environ['GRB_LICENSE_FILE']=str(license_path)
  sys.path.insert(0,str(vendor))
  import gurobipy
  if not Path(gurobipy.__file__).resolve().is_relative_to(vendor.resolve()):raise ValueError('Gurobi did not load from exact public wheel')
  if importlib.metadata.version('gurobipy')!='13.0.3':raise ValueError('Native wheel version changed')
  from portfolio.backend import solve_gurobi
  result=solve_gurobi(model,time_limit_seconds=job['time_limit_seconds'],threads=16,
   exclude_plan=job['exclude_plan'],warm_start=job['warm_start'],known_feasible_plans=job['known_feasible_plans'],
   scaling=job['scaling'],log_path=root/'solver.log',model_path=root/'native_model.mps')
  (root/'solver_result.json').write_bytes(canonical(result))
 verify()
 result={'completed':True,'backend':'gurobi','threads':16,'gap_requested':0,
  'distribution_versions':{'gurobipy':'13.0.3'},'model_canonical_sha256':hashlib.sha256(canonical(model)).hexdigest(),
  'financial_forward_executed':False,'elapsed_seconds':time.monotonic()-start,
  'public_wheel_only':True,'host_install_performed':False,'private_license_mounted':False,
  'reference_admission':False,'independent_CP_exact_proof_pending':True}
 (root/'runtime_result.json').write_bytes(canonical(result));print(json.dumps(result),flush=True)
except BaseException as error:
 (root/'runtime_error.json').write_text(json.dumps({'type':type(error).__name__,'error':str(error),'elapsed_seconds':time.monotonic()-start})+'\n')
 traceback.print_exc();sys.exit(1)
'''


def adapted_ast():
    backend.require(hashlib.sha256(Path(producer.__file__).read_bytes()).hexdigest()==PRODUCER_SHA and hashlib.sha256(Path(producer.__file__).with_name('optimization_runtime.py').read_bytes()).hexdigest()==BASE_SHA,'Frozen producer resource lifecycle changed')
    tree=producer.adapted_ast();hits=Counter()
    class Adapt(ast.NodeTransformer):
        def visit_Assign(self,node):
            names=[getattr(t,'id',None) for t in node.targets]
            replacements={'PREPARATION_KIND':PREPARATION_KIND,'TERMINAL_KIND':TERMINAL_KIND,
                'DISTRIBUTIONS':{'gurobipy':'13.0.3'},'BACKENDS':{'gurobi':('backend','solve_gurobi','native_model.mps')},'RUNNER':RUNNER}
            if len(names)==1 and names[0] in replacements:
                node.value=ast.parse(repr(replacements[names[0]]),mode='eval').body;hits[names[0]]+=1
            return self.generic_visit(node)
        def visit_FunctionDef(self,node):
            if node.name in {'prepare','validate_prepared','validate_model','check_result','_source_files','_copy_vendor'}:
                hits['remove_'+node.name]+=1;return None
            node=self.generic_visit(node)
            if node.name=='execute_prepared':
                for call in ast.walk(node):
                    if isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='_require' and len(call.args)==2 and isinstance(call.args[1],ast.Constant) and call.args[1].value=='The solver result is not bound to the exact matrix and full-plan exclusion':
                        extra=ast.parse("solver.get('warm_start')==frozen['request']['warm_start'] and solver.get('known_feasible_plans')==frozen['request']['known_feasible_plans'] and solver.get('scaling')==frozen['request']['scaling'] and solver.get('time_limit_seconds')==frozen['request']['time_limit_seconds']",mode='eval').body
                        call.args[0]=ast.BoolOp(op=ast.And(),values=[call.args[0],extra]);hits['request_binding']+=1
                for item in ast.walk(node):
                    if isinstance(item,ast.Dict) and any(isinstance(k,ast.Constant) and k.value=='requested_resources' for k in item.keys):
                        for key,value in {'reference_admission':False,'independent_CP_exact_proof_pending':True,'source_quality_difficulty_inherited':False}.items():item.keys.append(ast.Constant(key));item.values.append(ast.Constant(value))
                        hits['terminal_claims']+=1
                    if isinstance(item,ast.List) and any(isinstance(v,ast.Constant) and v.value=='docker' for v in item.elts) and any(isinstance(v,ast.Constant) and v.value=='create' for v in item.elts):
                        item.elts[2:2]=[ast.Constant(v) for v in ('--env','PYTHONDONTWRITEBYTECODE=1','--env','PYTHONNOUSERSITE=1')];hits['create_env']+=1
                for item in ast.walk(node):
                    if isinstance(item,ast.Try):
                        for i,s in enumerate(item.body):
                            if isinstance(s,ast.Expr) and isinstance(s.value,ast.Call) and ast.unparse(s.value.func)=='terminal.update':
                                item.body[i:i]=ast.parse("_require(frozen['recipe']==recipes(),'Frozen Gurobi runtime recipe changed')\nterminal.update(host_resource_evidence={'before':reference(output/'host_before.json'),'after':reference(output/'host_after.json')},create_result=reference(output/'create_result.json'))").body;hits['end_recipe']+=1;break
            return node
        def visit_Compare(self,node):
            if ast.unparse(node)=="frozen['request']['backend'] == 'cp_sat'":node.comparators[0]=ast.Constant('gurobi');hits['parameter_artifact']+=1
            return self.generic_visit(node)
        def visit_Constant(self,node):
            if node.value=='.parameters.pbtxt':node.value='.parameters.prm';hits['parameter_suffix']+=1
            if type(node.value) is str and 'sf-producer16-integer-' in node.value:
                node.value=node.value.replace('sf-producer16-integer-','sf-gurobi1303-research-');hits['owned_name']+=1
            return node
    tree=Adapt().visit(tree)
    expected=Counter({k:1 for k in ('PREPARATION_KIND','TERMINAL_KIND','DISTRIBUTIONS','BACKENDS','RUNNER',
        'remove_prepare','remove_validate_prepared','remove_validate_model','remove_check_result','remove__source_files','remove__copy_vendor',
        'terminal_claims','create_env','end_recipe','request_binding','parameter_artifact','parameter_suffix')});expected['owned_name']=2
    backend.require(hits==expected,'Exact Gurobi transport substitutions changed: '+str(hits))
    return ast.fix_missing_locations(tree)


_ns={'__name__':__name__+'._transport','__package__':__package__,'__file__':__file__}
exec(compile(adapted_ast(),__file__,'exec'),_ns)
for _name in ('reference','_real','_read','_write','_inventory','_now','_canonical','validate_resources','OptimizationRuntimeError'):
    globals()[_name]=_ns[_name]


def check_wheel(path=WHEEL):
    path=_real(path);r=reference(path)
    backend.require(r['sha256']==WHEEL_SHA and r['bytes']==WHEEL_BYTES,'Only the exact public CPython3.12 wheel is permitted')
    with zipfile.ZipFile(path) as z:
        names=set()
        for i in z.infolist():
            p=Path(i.filename)
            backend.require(not p.is_absolute() and '..' not in p.parts and '\\' not in i.filename and i.filename not in names and not stat.S_ISLNK(i.external_attr>>16),'Unsafe wheel member')
            names.add(i.filename)
        backend.require('gurobipy/.libs/gurobi.lic' in names and 'gurobipy/_core.cpython-312-x86_64-linux-gnu.so' in names and 'Tag: cp312-cp312-manylinux2014_x86_64' in z.read('gurobipy-13.0.3.dist-info/WHEEL').decode(),'Pinned ABI/license package structure changed')
    return r


def _source_files():return {'backend.py':Path(backend.__file__)}


def prepare(model_A,model_B,output,*,time_limit_seconds=3600,exclude_plan=None,
            warm_start=None,known_feasible_plans=None,scaling='none',wheel=WHEEL):
    """Freeze both independent matrices and one prospective attempt; zero services."""
    backend.require(type(time_limit_seconds) is int and 1<=time_limit_seconds<=3600,'Use one bounded 1..3600-second private attempt')
    a_ref,b_ref=reference(model_A),reference(model_B);a,b=_read(model_A),_read(model_B)
    parity=backend.compare_models(a,b);backend.representation(a,scaling)
    if exclude_plan is not None:backend.plan_values(a,exclude_plan)
    known_feasible_plans={} if known_feasible_plans is None else known_feasible_plans
    backend.require(type(known_feasible_plans) is dict,'Explicit named known feasible inventory required')
    for name,p in known_feasible_plans.items():
        backend.require(type(name) is str and name and backend.check_plan(a,p)['feasible'] and backend.check_plan(b,p)['feasible'],'Counterexample must satisfy both exact matrices')
    if warm_start is not None:
        backend.require(backend.check_plan(a,warm_start,exclude_plan)['feasible'] and backend.check_plan(b,warm_start,exclude_plan)['feasible'],'Warm start must satisfy both exact matrices and full exclusion')
    wheel_ref=check_wheel(wheel);output=_real(output,exists=False)
    backend.require(not output.exists(),'Preserve every preparation and first attempt');output.mkdir(parents=True)
    try:
        bundle=output/'job_bundle';bundle.mkdir();package=bundle/'portfolio';package.mkdir();(package/'__init__.py').write_bytes(b'')
        shutil.copyfile(backend.__file__,package/'backend.py');shutil.copyfile(wheel,bundle/'vendor.whl')
        (bundle/'model.json').write_bytes(_canonical(a));(bundle/'independent_model_B.json').write_bytes(_canonical(b))
        job={'backend':'gurobi','time_limit_seconds':time_limit_seconds,'threads':16,'exclude_plan':exclude_plan,
            'warm_start':warm_start,'known_feasible_plans':known_feasible_plans,'scaling':scaling,
            'relative_gap':0,'absolute_gap':0,'distribution_versions':{'gurobipy':'13.0.3'},
            'wheel_sha256':WHEEL_SHA,'nonce':uuid.uuid4().hex,'financial_forward_permitted':False}
        (bundle/'job.json').write_bytes(_canonical(job));(bundle/'run.py').write_text(RUNNER)
        initial=_inventory(bundle);_write(bundle/'inventory.json',{k:{'sha256':v['sha256'],'bytes':v['bytes']} for k,v in initial.items()})
        frozen={'kind':PREPARATION_KIND,'version':1,'prepared_at':_now(),'model_input':a_ref,'independent_model_B':b_ref,
            'complete_matrix_comparison':parity,'model_canonical_sha256':backend.sha(a),'request':job,
            'bundle':str(bundle),'bundle_inventory':_inventory(bundle),'source_code':{k:reference(v) for k,v in _source_files().items()},
            'vendor_source':str(Path(wheel).resolve()),'vendor_inventory':{'vendor.whl':wheel_ref},
            'implementation':reference(__file__),'recipe':recipes(),'policy':policy(),'image_id':policy()['image_id'],
            'resources':{'cpus':16,'memory_bytes':32*1024**3,'pids_limit':256},'network':'none',
            'operational_timeout_seconds':time_limit_seconds+120,'agent_tool_budget_changed':False,
            'solver_calls':0,'model_calls':0,'qualified':False,'reference_admission':False}
        backend.require(a_ref==reference(model_A) and b_ref==reference(model_B) and wheel_ref==check_wheel(wheel),'Original input changed during freeze')
        return _write(output/'preparation.json',frozen)
    except BaseException as e:
        _write(output/'preparation_failure.json',{'type':type(e).__name__,'error':str(e),'actual_solver_calls':0,'model_calls':0,'partial_files_preserved':True});raise


def validate_prepared(output,*,completed=False):
    output=_real(output,exists=False);f=_read(output/'preparation.json');request=f['request']
    backend.require(f['kind']==PREPARATION_KIND and type(f['version']) is int and f['version']==1 and f['implementation']==reference(__file__) and f['recipe']==recipes() and f['policy']==policy(),'Frozen Gurobi identity/recipe/policy changed')
    backend.require(f['source_code']=={k:reference(v) for k,v in _source_files().items()} and f['vendor_inventory']=={'vendor.whl':check_wheel(f['vendor_source'])},'Frozen backend/wheel changed')
    backend.require(f['model_input']==reference(f['model_input']['path']) and f['independent_model_B']==reference(f['independent_model_B']['path']),'Original A/B matrix bytes changed')
    a,b=_read(output/'job_bundle/model.json'),_read(output/'job_bundle/independent_model_B.json')
    backend.require(f['complete_matrix_comparison']==backend.compare_models(a,b) and f['model_canonical_sha256']==backend.sha(a) and a==_read(f['model_input']['path']) and b==_read(f['independent_model_B']['path']),'Complete A/B matrix lineage changed')
    backend.require(request==_read(output/'job_bundle/job.json') and set(request)=={'backend','time_limit_seconds','threads','exclude_plan','warm_start','known_feasible_plans','scaling','relative_gap','absolute_gap','distribution_versions','wheel_sha256','nonce','financial_forward_permitted'},'Frozen private request changed')
    backend.require(request['backend']=='gurobi' and type(request['time_limit_seconds']) is int and 1<=request['time_limit_seconds']<=3600 and type(request['threads']) is int and request['threads']==16 and request['relative_gap']==0 and type(request['relative_gap']) is int and request['absolute_gap']==0 and type(request['absolute_gap']) is int and request['distribution_versions']=={'gurobipy':'13.0.3'} and request['wheel_sha256']==WHEEL_SHA and type(request['nonce']) is str and re.fullmatch('[0-9a-f]{32}',request['nonce']) and request['financial_forward_permitted'] is False,'Frozen private settings changed')
    backend.representation(a,request['scaling'])
    if request['exclude_plan'] is not None:backend.plan_values(a,request['exclude_plan'])
    backend.require(type(request['known_feasible_plans']) is dict,'Counterexample inventory changed')
    for name,p in request['known_feasible_plans'].items():backend.require(type(name) is str and name and backend.check_plan(a,p)['feasible'] and backend.check_plan(b,p)['feasible'],'Known plan invalid in A/B')
    if request['warm_start'] is not None:backend.require(backend.check_plan(a,request['warm_start'],request['exclude_plan'])['feasible'] and backend.check_plan(b,request['warm_start'],request['exclude_plan'])['feasible'],'Warm start invalid')
    backend.require(f['resources']=={'cpus':16,'memory_bytes':32*1024**3,'pids_limit':256} and f['network']=='none' and f['image_id']==policy()['image_id'] and f['operational_timeout_seconds']==request['time_limit_seconds']+120 and f['agent_tool_budget_changed'] is False and f['solver_calls']==0 and f['model_calls']==0 and f['qualified'] is False and f['reference_admission'] is False,'Resource/claim boundary changed')
    backend.require(Path(f['bundle'])==output/'job_bundle','Job bundle path changed')
    inv=_inventory(output/'job_bundle');base=f['bundle_inventory']
    backend.require(all(inv.get(k)==r for k,r in base.items()) and (set(inv)==set(base) if not completed else set(inv)-set(base)==ARTIFACTS),'Immutable or complete native artifact inventory changed')
    return f


def check_result(model,result,exclude_plan=None):
    evidence=backend.strict_evidence(model,result,exclude_plan,result.get('known_feasible_plans'))
    backend.require(type(result.get('checked_optimal')) is bool and result['checked_optimal']==evidence['passed'],'Reported checked flag disagrees with independent strict check')
    return {'native_status':result.get('status'),'checked_optimal':evidence['passed'],'exact_matrix_plan_check':evidence,
        'status':'native_candidate_consistent_not_reference_admitted' if evidence['passed'] else 'native_candidate_not_proven',
        'reference_admission':False,'independent_CP_exact_proof_pending':True}


def validate_completed(value):
    ref=value if type(value) is dict else reference(value);backend.require(reference(ref['path'])==ref,'Terminal REF changed')
    terminal=_read(ref['path']);output=Path(ref['path']).parent;f=validate_prepared(output,completed=True)
    backend.require(terminal['kind']==TERMINAL_KIND and terminal['preparation']==reference(output/'preparation.json') and terminal['actual_resources_verified'] is True and terminal['exit_code']==0 and terminal['oom_killed'] is False and terminal['reference_admission'] is False and terminal['qualified'] is False and terminal['model_calls']==0 and terminal['agent_tool_budget_changed'] is False and terminal['financial_forward_executed'] is False and terminal['formal_global_certificate_claimed'] is False and terminal['independent_CP_exact_proof_pending'] is True and terminal['source_quality_difficulty_inherited'] is False,'Native lifecycle did not complete honestly')
    cid=terminal['container_id'];backend.require(re.fullmatch('[0-9a-f]{64}',cid),'Exact owned full ID required')
    for key,name in (('before','host_before.json'),('after','host_after.json')):backend.require(terminal['host_resource_evidence'][key]==reference(output/name),'Bound actual resource evidence changed')
    backend.require(terminal['create_result']==reference(output/'create_result.json'),'Owned create receipt changed')
    created=_read(output/'create_result.json');backend.require(created['returncode']==0 and created['stdout'].strip()==cid,'Owned create ID changed')
    before,after=_read(output/'host_before.json'),_read(output/'host_after.json')
    validate_resources(before,cid,output/'job_bundle');validate_resources(after,cid,output/'job_bundle')
    backend.require(before['Name']=='/sf-gurobi1303-research-'+f['request']['nonce'] and before['State']['Status']=='created' and before['State']['Running'] is False and after['Name']==before['Name'] and after['State']['Status']=='exited' and after['State']['ExitCode']==0 and after['State']['OOMKilled'] is False and after['State']['Running'] is False,'Owned state chain changed')
    cleanup=_read(terminal['cleanup']['path']);backend.require(reference(terminal['cleanup']['path'])==terminal['cleanup'] and cleanup['owned_container_id']==cid and cleanup['removed_and_absent_with_daemon_reachable'] is True and cleanup['returncode']==0 and cleanup['absence_inspect']['returncode']==1 and cleanup['absence_inspect']['stdout']=='' and ('no such object: '+cid) in cleanup['absence_inspect']['stderr'].lower() and cleanup['daemon_image_check']['returncode']==0 and cleanup['daemon_image_check']['stdout'].strip()==policy()['image_id'],'Owned cleanup absence proof incomplete')
    for key in ('solver_result','runtime_result','stdout','stderr'):backend.require(reference(terminal[key]['path'])==terminal[key],'Native result/log artifact changed')
    solver=_read(terminal['solver_result']['path']);runtime=_read(terminal['runtime_result']['path']);model=_read(output/'job_bundle/model.json')
    backend.require(runtime['completed'] is True and runtime['backend']=='gurobi' and runtime['threads']==16 and runtime['gap_requested']==0 and runtime['distribution_versions']=={'gurobipy':'13.0.3'} and runtime['model_canonical_sha256']==f['model_canonical_sha256'] and runtime['financial_forward_executed'] is False and runtime['public_wheel_only'] is True,'Container runtime evidence changed')
    backend.require(solver['model_sha256']==f['model_canonical_sha256'] and solver['exclude_plan']==f['request']['exclude_plan'] and solver['warm_start']==f['request']['warm_start'] and solver['known_feasible_plans']==f['request']['known_feasible_plans'] and solver['scaling']==f['request']['scaling'] and solver['time_limit_seconds']==f['request']['time_limit_seconds'] and solver['threads']==16 and solver['specification_sha256']==model['specification_sha256'] and solver['universe_sha256']==model['universe_sha256'],'Result request/matrix binding changed')
    check=check_result(model,solver,f['request']['exclude_plan']);backend.require(check==terminal['matrix_result_check'] and check['status']==terminal['status'] and terminal['complete_job_inventory']==_inventory(output/'job_bundle'),'Final strict check changed')
    return terminal


def _cleanup_owned(cid):
    result=_base_cleanup_owned(cid)
    absent=result['absence_inspect']
    result['removed_and_absent_with_daemon_reachable']=(result['removed_and_absent_with_daemon_reachable'] and re.fullmatch('[0-9a-f]{64}',cid) is not None and absent['returncode']==1 and absent['stdout']=='' and ('no such object: '+cid) in absent['stderr'].lower())
    return result


_base_cleanup_owned=_ns['_cleanup_owned']
_ns.update(_cleanup_owned=_cleanup_owned,validate_prepared=validate_prepared,validate_model=backend.validate_model,check_result=check_result,
    _source_files=_source_files,recipes=recipes)
execute_prepared=_ns['execute_prepared']

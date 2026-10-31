"""Retain eight genuine CP references; one fixed independent SCIP continuation.

No original attempt is replaced. This revision admits all nine cases only after
both new proofs and all sixteen retained proofs cold-validate. No source, quality
or model performance certification is inherited.
"""
import ast
from collections import Counter
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import re

from . import contract, reference as prior, runtime_scip3600 as runtime, backend_scip

ROOT = Path(__file__).resolve().parents[4]
ENTRY = ROOT/'scripts/run_linear_capital_sensitivity_reference_revision2.py'
ORIGINAL_PREPARATION_SHA = 'e0da2c1d9f93f4ecc9159791c2d7ec10c28f382eef0ca028d10c55b1017167e2'
OBSERVATION_SHA = 'd85b1e410ce302e9cb7eace993337bb72f3f6e536ac9837b62cd9c077a975355'
PRIOR_SHA = 'aceb885373d00edc8aca2d4c6cd612658b8749792a34c6c591e6494448f49150'
FIXED_CASE = 'B110_C110'
PREPARED = 'prepared_fixed_sensitivity9_retained8_SCIP3600_revision2'
KIND = 'complete_fixed_sensitivity9_retained8_SCIP3600_revision2'
CASE_KIND = 'fixed_sensitivity_case_SCIP3600_revision2_best_runner_reference'
TIME_LIMIT = 3600
require = contract.require


def _gate_ast():
    require(prior.reference(prior.__file__)['sha256'] == PRIOR_SHA, 'The retained CP600 producer changed')
    tree = prior.original._gate_ast(); hits=Counter()
    class Adapt(ast.NodeTransformer):
        def visit_Constant(self,node):
            if node.value == '/sf-scaled-producer16-integer-':
                node.value='/sf-sensitivity9-SCIP3600-r2-';hits['name']+=1
            return node
        def visit_Dict(self,node):
            keys=[getattr(k,'value',None) for k in node.keys]
            if keys==['limits/time','limits/gap','limits/absgap','parallel/maxnthreads','lp/threads']:
                for key in ('parallel/maxnthreads','lp/threads'):node.values[keys.index(key)]=ast.Constant(16)
                node.keys.append(ast.Constant('numerics/feastol'));node.values.append(ast.Constant(1e-9));hits['settings']+=1
            return self.generic_visit(node)
        def visit_Compare(self,node):
            if ast.unparse(node)=="solver.get('feasibility_tolerance_changed') is False":
                hits['tolerance']+=1
                return ast.parse("solver.get('declared_feasibility_tolerance')==1e-9 and solver.get('applied_feasibility_tolerance')==1e-9 and solver.get('feasibility_tolerance_changed')==(solver['default_feasibility_tolerance']!=1e-9)",mode='eval').body
            return self.generic_visit(node)
    tree=Adapt().visit(tree)
    require(hits==Counter(dict(name=1,settings=1,tolerance=1)), 'Frozen strict resource receipt gates changed: '+str(hits))
    return ast.fix_missing_locations(tree)


exec(compile(_gate_ast(), __file__, 'exec'), globals())


def recipes():
    from sheets_factory.core import audit
    from sheets_factory import dashboard, resume
    paths=[Path(__file__),Path(runtime.__file__),Path(backend_scip.__file__),runtime.PROFILE,ENTRY,
           Path(audit.__file__),Path(dashboard.__file__),Path(resume.__file__),*runtime._source_files().values()]
    return {**prior.recipes(),**{str(p):reference(p) for p in paths}}


def _checked_case(actual, row, frozen, inputs, *, new=False):
    """Cold proof for the original two-search contract, no aggregate pass flag."""
    module = globals() if new else vars(prior)
    identity=row['case']['id']
    require(actual['kind']==(CASE_KIND if new else prior.CASE_KIND)
        and type(actual['version']) is int and actual['version']==(2 if new else 1)
        and actual['passed'] is True and actual['case']==row['case'] and actual['models']==row['models']
        and type(actual['native_job_invocations'])is int and actual['native_job_invocations']==2
        and actual['qualified'] is False and actual['reference_is_not_source_or_quality_or_difficulty'] is True
        and set(actual['solver_receipts'])==set(actual['validations'])=={'best','runner'}
        and all(type(actual[k])is int and actual[k]==0 for k in ('financial_forwards','LO_calls','model_calls')),
        'A retained or new case must have two genuine complete proofs')
    best=module['_checked_job'](frozen['best_preparations'][identity],actual['solver_receipts']['best'],row,None)
    winner=best['native']['solver']
    runner=module['_checked_job'](actual['runner_preparation'],actual['solver_receipts']['runner'],row,winner['plan'])
    other=runner['native']['solver'];gap=winner['objective_pence']-other['objective_pence']
    require(read(actual['validations']['best'])==best and read(actual['validations']['runner'])==runner
        and actual['winner_plan']==winner['plan'] and actual['runner_plan']==other['plan']
        and actual['winner_objective_pence']==winner['objective_pence']
        and actual['runner_objective_pence']==other['objective_pence']
        and type(gap)is int and gap>=1 and actual['gap_pence']==gap and other['plan']!=winner['plan'],
        'Both actual OPTIMAL proofs and the full excluded-winner positive penny gap are required')
    projection=prior._financial_projection(inputs,row,winner['plan'],other['plan'])
    require(read(actual['financial_projection'])==projection and all(
        projection['comparison']['plans'][i][side]['objective_pence']==solver['objective_pence']
        for i,solver in enumerate((winner,other)) for side in ('A','B')),
        'Both selected financial projections must equal the exact native integer objectives')


def _checked_original(preparation, observation):
    preparation=reference(preparation) if isinstance(preparation,(str,Path)) else preparation
    observation=reference(observation) if isinstance(observation,(str,Path)) else observation
    require(preparation['sha256']==ORIGINAL_PREPARATION_SHA and observation['sha256']==OBSERVATION_SHA,
            'Retain the exact original whole-nine preparation and complete failed observation')
    observed=read(observation);_refs(observed)
    require(observed['original_preparation']==preparation and observed['passed'] is False
        and observed['original_parent_exit_code']==1 and observed['original_parent_outer_terminal_exists'] is False
        and observed['cases_passed']==8 and observed['cases_rejected']==1
        and observed['known_native_job_invocations']==17
        and observed['last_case_FEASIBLE_is_not_optimal_gold'] is True
        and observed['runner_not_started_after_failed_best'] is True,
        'The prior seventeen searches and original orchestration failure cannot be erased')
    output=Path(preparation['path']).parent
    frozen,inputs,inventory=prior.validate_prepared(output)
    require(reference(output/'preparation.json')==preparation,'Original prepared directory differs')
    seen={row['case_id']:row for row in observed['all9case_terminals_retained']}
    require(len(seen)==9 and set(seen)==set(frozen['case_order']), 'The failed observation must retain every fixed case')
    retained={};original_cases={}
    for row in inventory['cases']:
        identity=row['case']['id'];receipt=reference(output/'cases'/identity/'terminal.json')
        require(seen[identity]['terminal']==receipt,'An original case terminal was substituted')
        actual=read(receipt);original_cases[identity]=receipt
        if identity==FIXED_CASE:
            require(actual['passed'] is False and type(actual['native_job_invocations'])is int
                and actual['native_job_invocations']==1 and set(actual['solver_receipts'])=={'best'}
                and 'runner_preparation' not in actual and actual['models']==row['models']
                and actual['case']==row['case'], 'Only the fixed failed ninth best may be continued')
            solver=read(read(actual['solver_receipts']['best'])['solver_result'])
            require(solver['status']=='FEASIBLE' and solver['checked_optimal'] is False,
                    'The preserved failed best is not an optimal winner or warm hint')
        else:
            _checked_case(actual,row,frozen,inputs);retained[identity]=receipt
    require(len(retained)==8 and inventory['case_order'][-1]==FIXED_CASE,
            'Exactly the original eight proofs and fixed last case are required')
    return {'original_preparation':preparation,'observation':observation,'frozen':frozen,
        'inputs':inputs,'inventory':inventory,'retained':retained,'original_cases':original_cases}


def prepare(original_preparation, observation, output):
    output=Path(output).absolute()
    require(output==output.resolve() and output.is_relative_to(ROOT/'outputs') and not output.exists(),
            'Use a fresh isolated revision-two reference directory')
    incoming=_checked_original(original_preparation,observation);before=recipes();runtime.profile_reference()
    output.mkdir(parents=True)
    # The complete fixed nine-case ancestry precedes the sole new native preparation.
    prospective=write(output/'prospective.json',{'kind':PREPARED+'_prospective','version':2,
        'original_preparation':incoming['original_preparation'],'original_complete_failed_observation':incoming['observation'],
        'original_all_nine_models':incoming['frozen']['all_nine_models'],
        'ordered_all_nine_models':incoming['inventory']['cases'],'case_order':incoming['frozen']['case_order'],
        'retained_complete_cases':incoming['retained'],'original_all_nine_case_terminals':incoming['original_cases'],
        'only_new_search_case':FIXED_CASE,'maximum_new_native_searches':2,'maximum_historical_native_searches':19,
        'admitted_proofs_required':18,'new_searches_before_this_inventory':0,'retries':0,'prior_incumbent_input':False,
        'recipe':before,'profile':runtime.profile_reference(),'qualified':False})
    row=incoming['inventory']['cases'][-1]
    job=runtime.prepare(row['models']['A']['path'],output/'cases'/FIXED_CASE/'jobs/best',
                        backend='scip',time_limit_seconds=3600)
    require(recipes()==before,'Implementation changed during zero-service preparation')
    return write(output/'preparation.json',{'kind':PREPARED,'version':2,'prospective':prospective,
        'best_preparations':{FIXED_CASE:job},'recipe':before,'profile':runtime.profile_reference(),
        'financial_forwards':0,'native_solver_calls':0,'LO_calls':0,'model_calls':0,'qualified':False})


def _job_preparation(record,model,excluded):
    value=_checked_preparation(record,model,'scip',excluded)
    require(value['producer_profile']==runtime.profile_reference() and value['operational_timeout_seconds']==3720,
            'The strict new SCIP3600/operational3720 contract changed')
    return value


def validate_prepared(output):
    output=Path(output).absolute();frozen=read(output/'preparation.json');prospective=read(frozen['prospective'])
    require(frozen['kind']==PREPARED and type(frozen['version'])is int and frozen['version']==2
        and frozen['recipe']==recipes() and frozen['profile']==runtime.profile_reference()
        and frozen['qualified'] is False and all(type(frozen[k])is int and frozen[k]==0
            for k in ('financial_forwards','native_solver_calls','LO_calls','model_calls')),
        'The new isolated reference recipe or no-call preparation changed')
    incoming=_checked_original(prospective['original_preparation'],prospective['original_complete_failed_observation'])
    require(prospective=={'kind':PREPARED+'_prospective','version':2,
        'original_preparation':incoming['original_preparation'],'original_complete_failed_observation':incoming['observation'],
        'original_all_nine_models':incoming['frozen']['all_nine_models'],
        'ordered_all_nine_models':incoming['inventory']['cases'],'case_order':incoming['frozen']['case_order'],
        'retained_complete_cases':incoming['retained'],'original_all_nine_case_terminals':incoming['original_cases'],
        'only_new_search_case':FIXED_CASE,'maximum_new_native_searches':2,'maximum_historical_native_searches':19,
        'admitted_proofs_required':18,'new_searches_before_this_inventory':0,'retries':0,'prior_incumbent_input':False,
        'recipe':frozen['recipe'],'profile':frozen['profile'],'qualified':False}
        and set(frozen['best_preparations'])=={FIXED_CASE}, 'The complete original pool or continuation scope changed')
    _job_preparation(frozen['best_preparations'][FIXED_CASE],incoming['inventory']['cases'][-1]['models']['A'],None)
    return frozen,incoming


def _checked_job(job,receipt,row,excluded):
    _job_preparation(job,row['models']['A'],excluded)
    checked=validate_solver_receipt(job,receipt,model=row['models']['A'],backend='scip',exclude_plan=excluded)
    actual=read(receipt)
    require(checked['checked_optimal'] is True and actual['private_reference_time_limit_seconds']==3600
        and actual['operational_timeout_seconds']==3720, 'Limited or approximate native results cannot become gold')
    solver=checked['solver'];independent={}
    for side,module in (('A',contract.model_a),('B',contract.model_b)):
        model=read(row['models'][side]);audit=module.check_plan(model,solver['plan'],exclude_plan=excluded)
        complete=(audit['complete'] is True and audit['feasible'] is True
            and len(audit['rows'])==941+(excluded is not None)) if side=='A' else (
                audit['all_integer_rows_passed'] is True and audit['excluded_plan_distinct'] is True
                and audit['passed'] is True and len(audit['rows'])==941)
        require(len(model['rows'])==941 and complete and audit['plan']==solver['plan']
            and audit['objective_pence']==solver['objective_pence']
            and all(r['passed'] for r in audit['rows'])
            and [r['id'] for r in audit['rows'][:941]]==[r['id'] for r in model['rows']],
            'Every original integer business row and full exclusion must pass independent A/B')
        independent[side]=audit
    return {'native':checked,'independent_integer_checks':independent}


def _case_ast():
    tree=ast.parse(inspect.getsource(prior._case));hits=Counter()
    class Adapt(ast.NodeTransformer):
        def visit_Constant(self,node):
            if node.value=='cp_sat':node.value='scip';hits['backend']+=1
            elif type(node.value)is int and node.value==600:node.value=3600;hits['time']+=1
            return node
        def visit_Dict(self,node):
            keys=[getattr(k,'value',None) for k in node.keys]
            if 'kind'in keys and 'version'in keys:
                require(getattr(node.values[keys.index('kind')],'id',None)=='CASE_KIND','Unexpected case envelope')
                node.values[keys.index('version')]=ast.Constant(2);hits['version']+=1
            return self.generic_visit(node)
        def visit_Subscript(self,node):
            if ast.unparse(node)=="row['models']['B']":node.slice=ast.Constant('A');hits['model_side']+=1
            return self.generic_visit(node)
    tree=Adapt().visit(tree)
    require(hits==Counter(dict(backend=1,time=1,version=1,model_side=1)),'Frozen sole-case control flow changed: '+str(hits))
    return ast.fix_missing_locations(tree)


_case_namespace={**vars(prior),**globals(),'_financial_projection':prior._financial_projection}
exec(compile(_case_ast(),__file__,'exec'),_case_namespace)
_case=_case_namespace['_case']


class _SafeAudit:
    def __init__(self,audit,errors):self.audit,self.errors=audit,errors
    def invoke(self,name,*args,**kwargs):
        try:return getattr(self.audit,name)(*args,**kwargs)
        except Exception as error:
            self.errors.append({'at':datetime.now(timezone.utc).isoformat(),'operation':name,
                'error_type':type(error).__name__,'error':str(error)})
    def emit(self,*args,**kwargs):return self.invoke('emit',*args,**kwargs)
    def export(self):return self.invoke('export')


def execute_prepared(output,*,port=0):
    from sheets_factory.core.audit import AuditStore
    from sheets_factory.dashboard import DashboardServer
    from sheets_factory.resume import ProducerLease
    output=Path(output).absolute();frozen,incoming=validate_prepared(output)
    require(not(output/'started.json').exists(),'This independent revision has no retry or overwrite')
    lease=ProducerLease(output).acquire();audit=server=None;errors=[]
    records=dict(incoming['original_cases']);new_invocations=0
    terminal={'kind':KIND,'version':2,'passed':False,'preparation':reference(output/'preparation.json'),
        'original_complete_failed_observation':incoming['observation'],'all_cases_retained':True,
        'case_order':incoming['frozen']['case_order'],'retained_complete_cases':incoming['retained'],
        'automatic_retries':0,'financial_forwards':0,'LO_calls':0,'model_calls':0,'qualified':False,
        'reference_is_not_source_or_quality_or_difficulty':True}
    try:
        audit=AuditStore(output/'audit',{'id':output.name,'name':'Nine offline references: eight retained, fixed ninth SCIP',
            'status':'running','target_count':9,'producer_active':True,'normal_quality_or_release_counts':False})
        monitor=_SafeAudit(audit,errors)
        server=DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=port);url=server.start()
        write(output/'started.json',{'preparation':terminal['preparation'],'dashboard_url':url})
        monitor.invoke('update_run',dashboard_url=url);monitor.export()
        print(json.dumps({'dashboard_url':url}),flush=True)
        for identity,receipt in incoming['retained'].items():
            monitor.invoke('task',identity,status='passed',reused_genuine_reference=receipt,source_or_quality_certified=False)
        monitor.invoke('task',FIXED_CASE,status='running');monitor.export()
        row=incoming['inventory']['cases'][-1]
        receipt=_case(output,frozen,incoming['inputs'],row,monitor);records[FIXED_CASE]=receipt
        actual=read(receipt);new_invocations=actual['native_job_invocations']
        require(type(new_invocations)is int and 1<=new_invocations<=2,'At most two new searches may execute')
        terminal['passed']=actual['passed'] is True
        monitor.invoke('task',FIXED_CASE,status='passed' if terminal['passed'] else 'rejected',reference=receipt)
        monitor.invoke('update_run',status='passed' if terminal['passed'] else 'rejected',producer_active=False,
                       completed_cases=9);monitor.export()
    except BaseException as error:
        terminal.update(passed=False,error_type=type(error).__name__,error=str(error))
        candidate=output/'cases'/FIXED_CASE/'terminal.json'
        if candidate.exists():
            records[FIXED_CASE]=reference(candidate);new_invocations=read(records[FIXED_CASE]).get('native_job_invocations')
    finally:
        if server:
            try:server.stop()
            except Exception as error:errors.append({'operation':'server.stop','error':str(error)})
        if audit:
            try:audit.db.close()
            except Exception as error:errors.append({'operation':'audit.close','error':str(error)})
        lease.release()
    terminal.update(cases=[records[c] for c in terminal['case_order']],new_native_job_invocations=new_invocations,
        original_native_job_invocations=17,historical_native_job_invocations=17+new_invocations if type(new_invocations)is int else None,
        admitted_proofs=18 if terminal['passed'] else None,dashboard_errors=errors)
    return write(output/'terminal.json',terminal)


def validate_completed(value):
    result=read(value)
    require(result['kind']==KIND and type(result['version'])is int and result['version']==2
        and result['passed'] is True and result['all_cases_retained'] is True and result['qualified'] is False
        and result['reference_is_not_source_or_quality_or_difficulty'] is True
        and type(result['automatic_retries'])is int and result['automatic_retries']==0
        and all(type(result[k])is int and result[k]==v for k,v in
            {'financial_forwards':0,'LO_calls':0,'model_calls':0,'new_native_job_invocations':2,
             'original_native_job_invocations':17,'historical_native_job_invocations':19,'admitted_proofs':18}.items()),
        'Only the complete eighteen admitted proofs with all nineteen historical calls may admit')
    output=Path(result['preparation']['path']).parent;frozen,incoming=validate_prepared(output)
    require(result['preparation']==reference(output/'preparation.json')
        and result['original_complete_failed_observation']==incoming['observation']
        and result['retained_complete_cases']==incoming['retained']
        and result['case_order']==incoming['frozen']['case_order'] and len(result['cases'])==9,
        'The fixed all-nine retained ancestry differs')
    for identity,receipt in zip(result['case_order'],result['cases'],strict=True):
        require(receipt==(reference(output/'cases'/FIXED_CASE/'terminal.json') if identity==FIXED_CASE
                         else incoming['retained'][identity]),'No case may be dropped or substituted')
    _checked_case(read(result['cases'][-1]),incoming['inventory']['cases'][-1],frozen,incoming['inputs'],new=True)
    return result

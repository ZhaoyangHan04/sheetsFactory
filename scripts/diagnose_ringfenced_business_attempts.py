#!/usr/bin/env python3
"""One saved-output calculation per mode, followed by exact ringfenced economics."""
from __future__ import annotations

import argparse
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import importlib.util
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from openpyxl import load_workbook
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard.server import DashboardServer
from sheets_factory.evaluation import business_failure_evidence as files
from sheets_factory.evaluation import ringfenced_resource_harbor as exports
from sheets_factory.evaluation import ringfenced_resource_observer as observer
from sheets_factory.workbook.linear_capital_scaled import model_a, model_b

PROFILE = exports.PROFILE
PILOT = ROOT/'scripts/run_ringfenced_pair_source_pilot.py'
SUPPORT = ROOT/'scripts/resume_ringfenced_pair_task8_remaining_v1.py'
OLD_DIAGNOSIS = ROOT/'scripts/diagnose_associate_bridge_business_attempts.py'
SOURCE_SHA = 'b501a956b3c7b327665609fecbc6790c1164a68c0c7b838cecf3bbd442af5d0c'
CERTIFICATE_SHA = 'a2770c3bf4cccd9491b1f69cf144994d7f775e99c6de79f81a586237a8d4bc46'
SOURCE_KIND = 'completed_two_ringfenced_pair_source_same_process_session_revision3'
MANDATES = ('M01','M02')
PINS = {PILOT:'3be90b1ff63dd11808448263f5d097ea79b73283c14e1d9a6e367a1228a07dc2',
    SUPPORT:'4133d3d5bf01cdd5b60802a9807af510c62455f1055f8b7f70f46da0220b7305',
    OLD_DIAGNOSIS:'6deae634290bbd76d571704d70faa8d1bf1a56f6a2b1e0c72d959ec413eacf5d',
    Path(model_a.__file__):'6bb86d51b39970d151fa4f638d2427c1f04253f87d611f802f5bc0621221354d',
    Path(model_b.__file__):'4fd922ab1f0b60a5412ff873d01ff7c06524005f0eec4ebeb38128b8b4cf806b',
    Path(exports.__file__):'85bf055c9233d0d82193de0f6eb0d9adb6c6b4173bdea5cff60a128d94060733',
    Path(observer.__file__):'922a5c7ab464b0dddbf09f1d8e6ee32236526e29b68d6b512198be8c9c77e390'}
reference, read, require = files.reference, files._read, files._require
validate_trial_observations = observer._namespace['validate_trial_observations']


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x')as stream:json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
    return reference(path)


def recipes():
    exports.load_runtime_profile()
    for path,digest in PINS.items():require(reference(path)['sha256']==digest,'A frozen ringfenced diagnosis provider changed')
    return [reference(__file__),*[reference(p)for p in PINS],reference(PROFILE),
        *[reference(p)for p in dict(model_a.source_files(),**model_b.source_files()).values()]]


def _load(path,name):
    require(reference(path)['sha256']==PINS[path],'The private ringfenced support provider changed')
    definition=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(definition);definition.loader.exec_module(module);return module


def engine_class():
    return _load(PILOT,'_saved_ring_output_engine')._N['engines']().ThreadCappedResourceLibreOfficeEngine


def resource_check(record,source,output,role):
    receipt=read(record)
    require(receipt.get('kind')=='resource_bound_libreoffice_call'and receipt.get('role')==role,
            'The retained native receipt belongs to another role')
    for key,digest in files.ENGINE_PINS.items():
        require(receipt[key]['sha256']==digest and reference(receipt[key]['path'])==receipt[key],
                'The native calculation implementation changed')
    return _load(SUPPORT,'_saved_ring_resource_check').resource_check(record,source=source,output=output)


def owned_absence(receipts):
    return _load(OLD_DIAGNOSIS,'_saved_ring_exact_owned_absence').owned_absence(receipts)


def evaluate_plans(models,plans,certificate):
    """No solver or financial forward: two integer row/objective implementations."""
    require(tuple(models)==tuple(plans)==MANDATES,'Require both complete declared mandates')
    details={};total=0
    for identity in MANDATES:
        A,B=models[identity]['A'],models[identity]['B'];plan=plans[identity]
        require(A['project_ids']==B['project_ids']and len(A['project_ids'])==360
            and len(A['rows'])==len(B['rows'])==941,'Require the unchanged full360-project941-row models')
        require(set(plan)==set(A['project_ids'])and all(type(v)is int and v in(0,1)for v in plan.values()),
                'A complete exact binary choice is required for every project')
        a=model_a.check_plan(A,plan);b=model_b.check_plan(B,plan)
        require(a['rows']==b['rows']and a['objective_pence']==b['objective_pence']
            and a['feasible']==b['passed']and len(a['rows'])==941,
            'The independent exact integer plan checks disagree')
        total+=a['objective_pence'];best=certificate['local'][identity]['winner_objective_pence']
        gap=best-a['objective_pence']
        if a['feasible']:
            require(gap>=0,'A feasible submitted objective exceeds its certified local maximum')
            require((gap==0 and plan==certificate['winner_plan'][identity])or
                gap>=certificate['local'][identity]['gap_pence'],
                'The submitted feasible plan contradicts the certified unique winner or runner gap')
        details[identity]={'plan':dict(plan),'objective_pence':a['objective_pence'],'certified_best_pence':best,
            'objective_difference_from_best_pence':gap,'feasible':a['feasible'],'rows':a['rows'],
            'failed_rows':[r for r in a['rows']if not r['passed']],'A_B_exact_agreement':True}
    feasible=all(r['feasible']for r in details.values());best=certificate['winner_objective_pence']
    require(sum(certificate['local'][i]['winner_objective_pence']for i in MANDATES)==best,
            'The composed objective differs from the two local certified maxima')
    gap=best-total
    if feasible:require(gap==0 or gap>=certificate['gap_pence'],'The global runner gap is contradicted')
    return {'classification':'infeasible'if not feasible else('optimal'if gap==0 else'feasible_suboptimal'),
        'mandates':details,'complete_choice_count':720,'integer_rows_checked':1882,
        'objective_pence':total,'certified_best_pence':best,'certified_runner_gap_pence':certificate['gap_pence'],
        'economic_shortfall_pence':gap if feasible else None,'all_constraints_feasible':feasible,
        'all_financial_fields_certified':False,'new_solver_calls':0,'new_financial_forwards':0}


def extract_choices(path,context):
    """Read the two declared Portfolio schedules; never infer a plan from totals."""
    book=load_workbook(path,read_only=True,data_only=True,keep_links=False)
    plans={};coverage=[];observed={};structure=[]
    try:
        if book.sheetnames!=context['sheetnames']:structure.append('sheet_structure_differs_from_source')
        for identity in MANDATES:
            name=context['portfolio_sheets'][identity];ids=context['models'][identity]['A']['project_ids']
            if name not in book.sheetnames:
                coverage.append({'mandate':identity,'reason':'missing_portfolio_sheet','sheet':name});continue
            values={letter+str(index):cell.value for index,row in enumerate(
                book[name].iter_rows(min_row=3,max_row=370,min_col=1,max_col=2),3)
                for letter,cell in zip(('A','B'),row)}
            plan={}
            for index,pid in enumerate(ids,6):
                label,value=values.get('A'+str(index)),values.get('B'+str(index))
                if label!=pid or type(value)is not int or value not in(0,1):
                    coverage.append({'mandate':identity,'project_id':pid,'point':name+'!B'+str(index),
                        'reason':'project_identity_mismatch'if label!=pid else'missing_or_nonbinary_choice',
                        'actual_type':type(value).__name__})
                else:plan[pid]=value
            plans[identity]=plan
            observed[identity]={'complete':values.get('B3'),'feasible':values.get('B369'),'objective_pence':values.get('B370')}
        group=context['group_sheet']
        if group in book.sheetnames:
            observed['group']={role:book[group][cell].value for role,cell in context['group_points'].items()}
        else:structure.append('missing_group_reporting_sheet')
        return {'plans':plans,'coverage_issues':coverage,'structure_issues':structure,'cached_controls':observed}
    finally:book.close()


def cache_consistency(economics,observed):
    issues=[]
    def same_integer(value,expected):
        try:return type(value)in(int,float)and Decimal(str(value)).is_finite()and Decimal(str(value))==expected
        except InvalidOperation:return False
    for identity,row in economics['mandates'].items():
        controls=observed.get(identity,{})
        for name,expected in [('complete',1),('feasible',int(row['feasible']))]:
            if not same_integer(controls.get(name),expected):issues.append({'mandate':identity,'field':name,'expected':expected,'actual':controls.get(name)})
        expected=row['objective_pence']if row['feasible']else None
        value=controls.get('objective_pence')
        if (expected is not None and not same_integer(value,expected))or(expected is None and value not in(None,'')):
            issues.append({'mandate':identity,'field':'objective_pence','expected':expected,'actual':value})
    group=observed.get('group',{});feasible=economics['all_constraints_feasible']
    if type(group.get('gate'))is not bool or group['gate']!=feasible:issues.append({'field':'group_gate','expected':feasible,'actual':group.get('gate')})
    value=group.get('objective');expected=economics['objective_pence']if feasible else None
    if (expected is not None and not same_integer(value,expected))or(expected is None and value not in(None,'')):
        issues.append({'field':'group_objective','expected':expected,'actual':value})
    return issues


def budget_status(row):
    timing=row['actual_attempt'].get('tool_time')or{};score=row['score']
    valid=timing.get('policy_version')==6 and timing.get('budget_seconds')==1800 and timing.get('strict_less_than')is True
    lower=timing.get('lower_bound_seconds',timing.get('cumulative_tool_seconds'))
    upper=timing.get('upper_bound_seconds',timing.get('cumulative_tool_seconds'))
    numbers=all(type(v)in(int,float)and Decimal(str(v)).is_finite()for v in(lower,upper))
    if valid and numbers and 0<=lower<=upper:
        if timing.get('passed')is False and lower>=1800 and score.get('effective_reward')==0:return 'known_budget_failure'
        if timing.get('passed')is True and upper<1800 and score.get('state')=='complete':return 'within_budget'
    return 'unknown'


def _source(source_ref):
    require(source_ref['sha256']==SOURCE_SHA,'This diagnostic accepts only the original genuine R2-01 source')
    source=read(source_ref)
    require(source['kind']==SOURCE_KIND and source['version']==1 and source['passed']is True
        and source['failure']is None and source['actual_calls_started']==source['actual_calls_completed']==3,
        'The original three-call source proof changed')
    sf=read(source['preparation']);cert_ref=sf['certificate'];require(cert_ref['sha256']==CERTIFICATE_SHA,'The fixed unique optimum certificate changed')
    cert=read(cert_ref);composed=cert['composition'];mapping=read(sf['local_composition']);public=read(sf['public_contract'])
    require(cert['kind']=='cold_composed_two_ringfenced_capital_best_runner_certificate'and cert['pair_id']=='R2-01'
        and cert['contract']==sf['public_contract']and cert['mathematical_composition_certified']is True
        and composed['unique_best']is True and composed['gap_pence']>=1,'The complete original pair certificate changed')
    require([x['id']for x in cert['local_whole_evidence']]==list(MANDATES)
        and [x['id']for x in mapping['donors']]==list(MANDATES)
        and [x['id']for x in public['mandates']]==list(MANDATES),'The two ringfenced mandate identities changed')
    refs=[source_ref,source['preparation'],cert_ref,sf['local_composition'],sf['public_contract']]
    models={};local={}
    for evidence in cert['local_whole_evidence']:
        identity=evidence['id'];reference_record=read(evidence['reference']);models[identity]={}
        for side in('A','B'):
            record=evidence['model_'+side];models[identity][side]=read(record);refs.append(record)
            require(record==reference_record['model_'+side],'The local independent matrix differs from its certified reference')
        a,b=models[identity]['A'],models[identity]['B'];raw=read(evidence['specification']);refs.extend([evidence['reference'],evidence['specification']])
        require(a['project_ids']==b['project_ids']==raw['project_ids']and len(a['project_ids'])==360
            and len(a['rows'])==len(b['rows'])==941 and a['specification_sha256']==b['specification_sha256']==reference_record['specification_sha256'],
            'Require both complete original independently derived360-project941-row matrices')
        winner=composed['winner_plan'][identity]
        require(reference_record['winner_plan']==winner and reference_record['unique_best']is True
            and reference_record['passed']is True and reference_record['gap_pence']==evidence['gap_pence']>=1,
            'A retained local unique-best certificate changed')
        for name in('winner','runner'):
            plan=reference_record[name+'_plan'];aa=model_a.check_plan(a,plan);bb=model_b.check_plan(b,plan)
            require(aa['rows']==bb['rows']and aa['feasible']is bb['passed']is True
                and aa['objective_pence']==bb['objective_pence']==reference_record[name+'_objective_pence'],
                'The certified best/runner does not satisfy both full original integer matrices')
        require(reference_record['winner_plan']!=reference_record['runner_plan']
            and reference_record['winner_objective_pence']-reference_record['runner_objective_pence']==evidence['gap_pence'],
            'The complete winner-excluded local runner gap changed')
        local[identity]={'winner_objective_pence':reference_record['winner_objective_pence'],'gap_pence':evidence['gap_pence']}
    require(sum(x['winner_objective_pence']for x in local.values())==composed['winner_objective_pence']
        and min(x['gap_pence']for x in local.values())==composed['gap_pence']
        and composed['runner_objective_pence']==composed['winner_objective_pence']-composed['gap_pence'],
        'The exact product-set objective/runner composition changed')
    previous=sf['cold_start']
    refs.append(previous)
    for index,call in enumerate(source['actual_calls'],1):
        require(call['index']==index and call['completed']is True and call['input']==previous,
                'The original source calculation chain changed')
        resource_check(call['actual_resource_evidence']['terminal'],previous,call['output'],'source')
        refs.extend([call['output'],call['actual_resource_evidence']['terminal']]);previous=call['output']
    require(source['source']==previous,'The healthy goal differs from the last actual source output')
    report=read(sf['report_plan']);refs.append(sf['report_plan'])
    group_points={('gate'if v['role']=='all_complete_and_feasible'else'objective'):k
        for k,v in report['financial'].items()if v.get('role')in('all_complete_and_feasible','objective')}
    return {'source':source,'goal':source['source'],'source_preparation':source['preparation'],'certificate':cert_ref,
        'models':models,'economics':{**composed,'local':local},'portfolio_sheets':{x['id']:x['sheet_map']['Portfolio']for x in mapping['donors']},
        'sheetnames':[name for x in mapping['donors']for name in x['sheet_map'].values()]+[report['sheet']],
        'group_sheet':report['sheet'],'group_points':group_points,'guard_refs':refs}


def _admit(batch_ref,terminal_ref):
    batch,terminal=read(batch_ref),read(terminal_ref)
    require(batch['kind']=='individually_engineered_business_revision_batch'and batch['version']==1
        and batch['count']==len(batch['tasks'])==2 and {t['mode']for t in batch['tasks']}=={'financial_modeling','debugging'}
        and batch['selected_task_ids']==[t['task_id']for t in batch['tasks']],'Require both original R2 materials')
    require(terminal['kind']=='business_revision_native_frontier_terminal_v1'and terminal['version']==1
        and terminal['phase']=='development'and terminal['outer_retries']==0,'Require the original one-attempt native terminal')
    prepared=read(terminal['prepared']);selection=read(terminal['selection']);resources=read(terminal['resources'])
    require(prepared['kind']=='prepared_business_revision_native_frontier_v1'and prepared['phase']=='development'
        and batch_ref in prepared['batches']and prepared['tasks']==batch['tasks'],'The native preparation belongs to another material')
    require(selection['phase']=='development'and selection['model']=='gpt-6.1-sol'and selection['reasoning_effort']=='xhigh'
        and selection['n_attempts']==1 and selection['tool_time_policy_version']==6
        and selection['infrastructure_retry_policy']['max_retries']==0,'The original v6 native strongest-model protocol changed')
    rows={r['task_id']:r for r in terminal['results']};selected={r['task_id']:r for r in selection['tasks']}
    require(len(rows)==len(terminal['results'])==len(selected)==2 and set(rows)==set(selected)==set(batch['selected_task_ids']),
            'Each material requires its single original attempt')
    context=_source(batch['source'])
    control_ref=batch['actual_control_chain'];control=read(control_ref)
    require(control['kind']=='completed_original_R2_01_four_remaining_controls_revision2'
        and control['passed']is True and control['source']==batch['source']and control['new_LO_calls']==4,
        'The original complete four-control continuation changed')
    context['guard_refs'].append(control_ref)
    for task in batch['tasks']:
        identity=task['task_id'];row=rows[identity];attempt=row['actual_attempt'];directory=Path(task['task_directory'])
        require(task['source_id']==context['goal']['sha256']and row['mode']==task['mode']
            and exports.inspect_resource_export(directory,audit_path=task['worker_cap_audit'])==task['harbor_export_binding']
            and selected[identity]['harbor_export_binding']==task['harbor_export_binding']
            and selected[identity]['task_checksum']==attempt['task_checksum'],'The actual native snapshot changed')
        require(all(reference(directory/'tests/reference.xlsx')[k]==context['goal'][k]for k in('sha256','bytes')),
                'The delivered goal is not the actual source3 output')
        engineering=read(task['individual_engineering'])
        require(engineering['passed']is True and engineering['source']==batch['source']
            and engineering['source_certificate']==context['certificate']
            and engineering['given_literals_unchanged']is engineering['sheet_structure_unchanged']is True
            and engineering['native_two_input_typed_stability']is True
            and engineering['full_source_formula_count']==2494958 and engineering['native_error_count']==0
            and {k:v['reward']for k,v in engineering['actual_programmatic_controls'].items()}
                =={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0},
            'The original complete full-union engineering or five controls changed')
        prefix='FM'if task['mode']=='financial_modeling'else'DBG'
        retained=control['results'][prefix+'_input2']
        require(all(reference(directory/'environment/input.xlsx')[k]==retained[k]for k in('sha256','bytes')),
                'The delivered input differs from its second actual native calculation')
        calls=[c for c in control['inherited_input_calls']if c['role']==prefix+'_input2']
        require(len(calls)==1 and calls[0]['output']==retained,'The actual input2 call lineage is incomplete')
        resource_check(calls[0]['actual_resource_evidence']['terminal'],calls[0]['input'],retained,'source')
        context['guard_refs'].extend([task['individual_engineering'],retained,calls[0]['actual_resource_evidence']['terminal']])
        if attempt.get('result_file'):
            result_ref=reference(attempt['result_file']);actual=read(result_ref)
            require(result_ref['sha256']==attempt['result_sha256']and actual['task_name']=='sheetsfactory/'+identity,
                    'The original saved result identity changed')
            if attempt.get('status')=='scored':
                require(actual.get('exception_info')is None and actual.get('finished_at')
                    and actual['verifier_result']['rewards']['reward']==attempt.get('raw_verifier_reward'),
                    'A scored native result no longer agrees with the retained original reward')
            context['guard_refs'].append(result_ref)
    return batch,terminal,rows,selected,resources,context


def run(batch_path,terminal_path,output,*,port=0):
    output=Path(output).absolute();require(output==output.resolve()and not output.exists(),'Use a fresh real diagnosis directory')
    audit=AuditStore(output,{'id':output.name,'status':'running','stage':'admission','new_model_calls':0,'new_source_calls':0,'verifier_LO_call_limit':2})
    panel=DashboardServer(audit.snapshot,audit.events,port=port);url=panel.start();audit.update_run(dashboard_url=url)
    print(json.dumps({'dashboard_url':url}),flush=True);started=time.monotonic();records=[];receipts=[];calls_started=0;engine=None
    try:
        recipe=recipes();br,tr=reference(batch_path),reference(terminal_path)
        batch,terminal,rows,selected,resources,context=_admit(br,tr)
        prospective=write(output/'prospective.json',{'kind':'saved_R2_01_output_economic_diagnosis','version':1,
            'batch':br,'original_terminal':tr,'source':batch['source'],'certificate':context['certificate'],'recipe':recipe,
            'exact_choices':720,'original_integer_rows':1882,'new_source_model_solver_financial_calls':0,'verifier_LO_call_limit':2,'outer_retries':0})
        for task in batch['tasks']:
            identity=task['task_id'];row=rows[identity];attempt=row['actual_attempt'];budget=budget_status(row)
            audit.task(identity,mode=task['mode'],status='running',stage='saved_output_inspection')
            evidence={'task_id':identity,'mode':task['mode'],'original_attempt':deepcopy(attempt),'original_score':deepcopy(row['score']),
                'budget_status':budget,'classification':'unknown','business_failure_evidence':None,'business_qualified':None,
                'new_verifier_LO_calls':0,'original_primary_score_modified':False,'all_financial_fields_certified':False}
            result_path=attempt.get('result_file');submitted=Path(result_path).parent/'artifacts/app/output.xlsx'if result_path else None
            if budget=='known_budget_failure':
                evidence.update(reason='Original proven tool-budget failure; no economic-suboptimality attribution',business_failure_evidence=False,business_qualified=False)
            elif attempt.get('status')!='scored'or type(attempt.get('raw_verifier_reward'))not in(int,float)or attempt['raw_verifier_reward']not in(0,1):
                evidence['reason']='Original attempt has no scored verifier result'
            elif submitted is None or not submitted.is_file():
                evidence.update(classification='coverage',reason='No retained submitted workbook')
            elif not(row['resources'].get('passed')is row['resources'].get('complete')is True):
                evidence['reason']='Original model resource evidence is incomplete'
            else:
                result_ref=reference(result_path);actual=read(result_ref)
                require(result_ref['sha256']==attempt['result_sha256']and row['resources']['result']==result_ref
                    and actual['task_name']=='sheetsfactory/'+identity and actual.get('exception_info')is None
                    and actual.get('finished_at')and actual['verifier_result']['rewards']['reward']==attempt['raw_verifier_reward'],
                    'The original actual result changed')
                checked=validate_trial_observations(row['resources']['trial_config'],result_ref,
                    receipts=resources['observation_receipts'],expected_task_directory=selected[identity]['task_directory'])
                require(checked['passed']is checked['complete']is True,'Actual original model resources failed verification')
                folder=output/'private'/identity;before=reference(submitted);audit.update_run(stage='one_output_native_recalculation',current_task=identity)
                engine=engine_class()(ROOT,PROFILE,role='verifier',receipt_directory=folder/'native_receipts');calls_started+=1
                native=engine.recalculate(submitted,folder/'output.native.xlsx');after=reference(native)
                require(reference(submitted)==before,'The retained original submission changed')
                metadata=engine.metadata();require(len(metadata['actual_resource_receipts'])==1,'Extra native output calls are forbidden')
                receipt=metadata['actual_resource_receipts'][0];receipts.append(receipt);resource_check(receipt,before,after,'verifier')
                cleanup=owned_absence([receipt]);require(cleanup['all_owned_containers_absent']and cleanup['daemon_reachable'],'Exact owned native cleanup is incomplete')
                extracted=extract_choices(native,context);evidence.update(extracted)
                evidence.update(original_submission=before,recalculated_submission=after,native_receipt=receipt,
                    native_metadata=metadata,owned_cleanup=cleanup,new_verifier_LO_calls=1,original_result=result_ref)
                if extracted['coverage_issues']:
                    evidence.update(classification='coverage',reason='The complete binary financial plan is unavailable')
                else:
                    try:economics=evaluate_plans(context['models'],extracted['plans'],context['economics'])
                    except ValueError as error:
                        evidence.update(classification='unknown',reason='Economic certificate or model contradiction: '+str(error))
                    else:
                        evidence.update(economics,cache_consistency_issues=cache_consistency(economics,extracted['cached_controls']))
                        raw=attempt['raw_verifier_reward'];bad=economics['classification']in('infeasible','feasible_suboptimal')
                        evidence['business_failure_evidence']=bool(bad and raw==0)
                        evidence['business_qualified']=bool(bad and raw==0)if budget=='within_budget'else None
                        if raw==1 and bad:evidence['quality_conflict']='Original success conflicts with recalculated economic plan; original success retained'
            record=write(output/'private'/identity/'economic_evidence.json',evidence)
            records.append({'task_id':identity,'mode':task['mode'],'evidence':record,'classification':evidence['classification'],
                'budget_status':budget,'business_qualified':evidence['business_qualified'],'original_raw_reward':attempt.get('raw_verifier_reward'),
                'original_effective_reward':row['score'].get('effective_reward'),'new_verifier_LO_calls':evidence['new_verifier_LO_calls']})
            audit.task(identity,status='diagnosed',stage=evidence['classification']);audit.export()
        require(recipes()==recipe and reference(batch_path)==br and reference(terminal_path)==tr,'Original code or attempt lineage changed')
        for record in context['guard_refs']:require(reference(record['path'])==record,'An original economic artifact changed during diagnosis')
        result=write(output/'terminal.json',{'kind':'complete_saved_R2_01_output_economic_diagnosis','version':1,'prospective':prospective,
            'records':records,'task_count':2,'business_qualified_count':sum(r['business_qualified']is True for r in records),
            'unknown_count':sum(r['business_qualified']is None for r in records),'actual_verifier_LO_calls':len(receipts),
            'actual_verifier_LO_calls_started':calls_started,'new_source_LO_calls':0,'new_model_calls':0,'new_solver_calls':0,
            'new_financial_forwards':0,'original_scores_modified':False,'outer_retries':0,'duration_seconds':time.monotonic()-started})
        audit.update_run(status='completed',stage='economic_diagnosis_complete');return result
    except BaseException as error:
        cleanup_evidence=None
        try:
            failed_receipts=list(receipts)
            if engine is not None:
                for receipt in engine.metadata()['actual_resource_receipts']:
                    value=read(receipt)
                    if value.get('container_id')and receipt not in failed_receipts:failed_receipts.append(receipt)
            if failed_receipts:
                cleanup_evidence=write(output/'failure_owned_cleanup.json',owned_absence(failed_receipts))
        except Exception as cleanup_error:
            cleanup_evidence=write(output/'failure_cleanup_unknown.json',{'error_type':type(cleanup_error).__name__,
                'reason':str(cleanup_error),'owned_cleanup_confirmed':False})
        write(output/'failure.json',{'error_type':type(error).__name__,'reason':str(error),'completed_records':records,
            'actual_verifier_LO_calls_started':calls_started,'actual_verifier_LO_calls_completed':len(receipts),
            'owned_cleanup_evidence':cleanup_evidence,'original_scores_modified':False,'outer_retries':0,'failure_is_not_model_zero':True})
        audit.update_run(status='failed',stage='economic_diagnosis_failed');raise
    finally:audit.export();panel.stop();audit.db.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for key in('batch','terminal','output'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--port',type=int,default=0);args=parser.parse_args(argv)
    print(json.dumps(run(args.batch,args.terminal,args.output,port=args.port)))


if __name__=='__main__':main()

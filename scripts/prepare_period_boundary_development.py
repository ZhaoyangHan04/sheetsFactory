#!/usr/bin/env python3
"""Freeze both prequality synthetic modes; run each first attempt explicitly."""
from __future__ import annotations
import argparse
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import shlex
import sys

sys.dont_write_bytecode=True
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
import yaml
from sheets_factory.evaluation import native_transport_frontier as runner
from sheets_factory.evaluation.resource_observer import ResourceObserver,validate_observation_receipt
from sheets_factory.evaluation.thread_capped_harbor_export import export_resource_harbor,inspect_resource_export,verify_local_base_image
from sheets_factory.workbook.period_boundary_portfolio.spec import BRIEFS

KIND='prequality_synthetic_period_boundary_development_pair'
MODES=('financial_modeling','debugging')
BUDGET={'version':1,'elapsed_policy':'operational_guard','elapsed_guard_seconds':14400,'tool_budget_seconds':1800}
PROFILE=ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
VALIDATOR=ROOT/'scripts/validate_period_boundary_candidate_v2.py'
VALIDATOR_SHA='0b974c2d7b45ae8f9b844663a06f147c95570094f56e514db15b6b5661b99e48'
HISTORY=ROOT/'scripts/prepare_heterogeneous_native_development.py'
HISTORY_SHA='1331f978f13844a9ceef3f3c3f949a79e7e082859b29303a47fba865130d9896'
_HISTORY=None


def require(ok,message):
    if not ok:raise ValueError(message)


def ref(path):
    p=Path(path).absolute();require(p==p.resolve() and p.is_file(),'Use a real nonsymlink file')
    h=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(4*1024**2),b''):h.update(block)
    return {'path':str(p),'sha256':h.hexdigest(),'bytes':p.stat().st_size}


def checked(value):require(ref(value['path'])==value,'A frozen file changed');return Path(value['path'])


def read(value):return json.loads((checked(value) if isinstance(value,dict) else Path(value)).read_text())


def write(path,value):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as stream:json.dump(value,stream,indent=2,allow_nan=False);stream.write('\n')
    return ref(p)


def load(path,name):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def history_helper():
    global _HISTORY
    require(ref(HISTORY)['sha256']==HISTORY_SHA,'The frozen pure logical/history boundary changed')
    if _HISTORY is None:_HISTORY=load(HISTORY,'_period_frozen_pure_history')
    return _HISTORY


def validation_driver():
    require(ref(VALIDATOR)['sha256']==VALIDATOR_SHA,'The final genuine v2 engineering validator is required')
    return load(VALIDATOR,'_period_actual_v2_engineering')


def canonical(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def recipes():
    from sheets_factory.evaluation import clock_resource_frontier,tool_time_clock_bounds,resource_frontier,frontier,resource_observer,resource_harbor,thread_capped_harbor_export,resource_streaming_verifier
    h=history_helper();driver=validation_driver()
    paths=[Path(__file__),HISTORY,h.SHARED,ROOT/'scripts/prepare_linear_capital_development.py',PROFILE,runner.PROFILE_PATH,
        *[Path(m.__file__) for m in [runner,clock_resource_frontier,tool_time_clock_bounds,resource_frontier,frontier,resource_observer,resource_harbor,thread_capped_harbor_export,resource_streaming_verifier]]]
    return {**driver.recipes(),**{str(p.resolve()):ref(p) for p in paths}}


def content_identity(mode,input,goal,instruction):
    h=history_helper()
    value={'version':1,'mode':mode,'input_definitions':h.workbook_identity(checked(input),formulas=True),
        'input_values':h.workbook_identity(checked(input)),'goal_values':h.workbook_identity(checked(goal)),
        'instruction_sha256':hashlib.sha256(instruction).hexdigest()}
    return {**value,'sha256':canonical(value)}


def _checked_engineering(value):
    driver=validation_driver();actual=driver.validate_completed(value)
    require(actual['kind']=='period_boundary_actual_shared_engineering_validation_v2' and actual['version']==2 and actual['passed'] is True
        and actual['actual_LO_calls_completed']==10 and not actual['qualified'],'Only a genuine new v2 ten-call terminal is admitted')
    prepared=read(actual['preparation']);candidate=read(prepared['candidate_manifest'])
    require(candidate['kind']=='offline_synthetic_period_boundary_candidate' and candidate['synthetic'] is True
        and candidate['formula_count']==657 and candidate['FM_D_count']==657 and candidate['DBG_D_count']==397,
        'This first candidate scope must remain the prospectively fixed 657/397 pair')
    require(set(actual['records']['modes'])==set(MODES),'Both real modes are required')
    return actual,candidate


def _instruction(candidate,mode):
    original=checked(candidate['instructions'][mode]).read_bytes()
    require(original==(BRIEFS[mode]+'\n').encode(),'The ordinary business request changed')
    appendix=b'\n---\nFile paths: read /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'
    return original,original+appendix


def prepare(engineering_terminal,output):
    output=Path(output).absolute();require(output==output.resolve() and not output.exists(),'Use one fresh shared development preparation')
    actual,candidate=_checked_engineering(engineering_terminal);h=history_helper();before=recipes()
    materials={};histories={}
    for mode in MODES:
        material=actual['records']['modes'][mode];original,instruction=_instruction(candidate,mode)
        identity=content_identity(mode,material['input'],material['goal'],instruction)
        histories[mode]=h.selection_history(identity)
        materials[mode]={'input':material['input'],'goal':material['goal'],'original_instruction':candidate['instructions'][mode],
            'original_sha256':hashlib.sha256(original).hexdigest(),'instruction':instruction,'material_task_version':identity,
            'task_id':('fm-' if mode=='financial_modeling' else 'dbg-')+'period-boundary-'+identity['sha256'][:12]}
    output.mkdir(parents=True);records={}
    for mode in MODES:
        m=materials[mode];task=output/'private/materialized'/mode;(task/'public').mkdir(parents=True);(task/'private').mkdir()
        shutil.copyfile(checked(m['input']),task/'public/input.xlsx');shutil.copyfile(checked(m['goal']),task/'private/goal.xlsx')
        (task/'public/instruction.md').write_bytes(m['instruction']);audit=output/'private'/(mode+'_worker_cap.json')
        export=export_resource_harbor(task,output/'SpreadsheetEval'/m['task_id'],{'task_id':m['task_id'],'mode':mode,'source_kind':'synthetic_period_boundary_financial_portfolio',
            'revision':0,'revision_hash':m['material_task_version']['sha256'],'quality_or_difficulty_certified':False,'difficulty_status':'prequality_development_only'},ROOT,runtime_profile=PROFILE,audit_path=audit)
        require((export/'environment/input.xlsx').read_bytes()==checked(m['input']).read_bytes()
            and (export/'tests/reference.xlsx').read_bytes()==checked(m['goal']).read_bytes()
            and (export/'instruction.md').read_bytes()==m['instruction'],'Export cannot alter input, goal or instruction bytes')
        binding=inspect_resource_export(export,audit_path=audit)
        task_record={'task_id':m['task_id'],'mode':mode,'revision':0,'revision_hash':m['material_task_version']['sha256'],
            'source_id':candidate['source_specification']['sha256'],'task_directory':str(export),'harbor_export_binding':binding,'execution_budget':BUDGET}
        source=write(output/(mode+'_source_view.json'),{'kind':'synthetic_period_boundary_prequality_development_source','version':1,
            'source_kind':'synthetic_period_boundary_financial_portfolio','tasks':[task_record],'selected_task_ids':[m['task_id']],
            'material_task_version':m['material_task_version'],'execution_budget':BUDGET,'tool_time_policy_version':3,'tool_time_policy':dict(runner.POLICY_V3),
            'native_transport_profile':runner.transport_profile(),'engineering_terminal':ref(engineering_terminal['path'] if isinstance(engineering_terminal,dict) else engineering_terminal),
            'confirmation_or_publish_authorized':False,'qualified':False})
        records[mode]={'source_view':source,'task_id':m['task_id'],'material_task_version':m['material_task_version'],
            'export_directory':str(export),'export_binding':binding,'worker_cap_audit':ref(audit),'input':m['input'],'goal':m['goal'],
            'original_instruction':m['original_instruction'],'original_instruction_sha256':m['original_sha256'],
            'rendered_instruction':ref(export/'instruction.md'),'IO_appendix_only':True}
    combined={}
    for mode in MODES:
        current=h.selection_history(materials[mode]['material_task_version'])
        require(all(r in current for r in histories[mode]),'History changed during shared preparation')
        for r in current:
            require(r['path'] not in combined or combined[r['path']]==r,'Conflicting history identities');combined[r['path']]=r
    history=[combined[k] for k in sorted(combined)];partition=h.history_partition(history)
    require(recipes()==before,'Preparation code changed')
    for mode in MODES:
        line=[str(ROOT/'.venv312/bin/python'),str(Path(__file__).resolve()),'run-development','--prepared',str(output),'--mode',mode,'--output',str(output/'evaluation'/mode)]
        p=output/('run_'+mode+'.sh');p.write_text('#!/usr/bin/env bash\nset -euo pipefail\ncd '+shlex.quote(str(ROOT))+'\nexec '+' '.join(map(shlex.quote,line))+'\n');p.chmod(0o700)
        records[mode]['runner_script']=ref(p)
    return write(output/'probe_manifest.json',{'kind':KIND,'version':1,'engineering_terminal':ref(engineering_terminal['path'] if isinstance(engineering_terminal,dict) else engineering_terminal),
        'candidate_manifest':read(actual['preparation'])['candidate_manifest'],'mode_order':list(MODES),'modes':records,'recipe':before,
        'selection_history_inventory':history,'prior_model_selection_inventory':partition['model_selections'],'nonmodel_preparation_inventory':partition['nonmodel_preparations'],
        'both_materials_frozen_before_any_model':True,'history_roots':[str(p) for p in h.HISTORY_ROOTS],
        'execution_budget':BUDGET,'model':'gpt-6.1-sol','reasoning_effort':'xhigh','effective_outer_retries':0,
        'model_calls_during_preparation':0,'LO_calls_during_preparation':0,'solver_calls':0,'qualified':False,
        'normal_all12_QA_passed':False,'public_recovery_pending':True,'actual_Harbor_controls_pending':True,'difficulty_claimed':False})


def validate_prepared(prepared):
    p=Path(prepared).absolute();f=read(p/'probe_manifest.json');require(f['kind']==KIND and f['version']==1 and f['recipe']==recipes()
        and f['mode_order']==list(MODES) and set(f['modes'])==set(MODES) and f['both_materials_frozen_before_any_model'] is True and not f['qualified']
        and f['execution_budget']==BUDGET and f['model']=='gpt-6.1-sol' and f['reasoning_effort']=='xhigh' and f['effective_outer_retries']==0,'The complete shared development preparation changed')
    actual,candidate=_checked_engineering(f['engineering_terminal']);h=history_helper()
    partition=h.history_partition(f['selection_history_inventory'])
    require(partition['model_selections']==f['prior_model_selection_inventory'] and partition['nonmodel_preparations']==f['nonmodel_preparation_inventory'],'History partition changed')
    for r in f['selection_history_inventory']:checked(r)
    for mode in MODES:
        m=f['modes'][mode];material=actual['records']['modes'][mode];original,instruction=_instruction(candidate,mode)
        require(m['input']==material['input'] and m['goal']==material['goal'] and m['material_task_version']==content_identity(mode,m['input'],m['goal'],instruction),'Source identity or logical material changed')
        export=Path(m['export_directory']);require(inspect_resource_export(export,audit_path=m['worker_cap_audit'])==m['export_binding'],'Actual export differs')
        require((export/'environment/input.xlsx').read_bytes()==checked(m['input']).read_bytes() and (export/'tests/reference.xlsx').read_bytes()==checked(m['goal']).read_bytes()
            and checked(m['rendered_instruction']).read_bytes()==instruction and instruction.startswith(original),'Public bytes or private goal changed')
        checked(m['runner_script']);source=read(m['source_view'])
        expected_task={'task_id':m['task_id'],'mode':mode,'revision':0,'revision_hash':m['material_task_version']['sha256'],
            'source_id':candidate['source_specification']['sha256'],'task_directory':str(export),'harbor_export_binding':m['export_binding'],'execution_budget':BUDGET}
        require(source['material_task_version']==m['material_task_version'] and source['tasks']==[expected_task]
            and source['selected_task_ids']==[m['task_id']] and source['execution_budget']==BUDGET and source['native_transport_profile']==runner.transport_profile()
            and source['kind']=='synthetic_period_boundary_prequality_development_source'
            and source['engineering_terminal']==f['engineering_terminal'] and not source['confirmation_or_publish_authorized'] and not source['qualified'],
            'A frozen one-case source view changed')
    return f


def reserve(prepared,frozen,mode,destination):
    h=history_helper();m=frozen['modes'][mode];identity=m['material_task_version'];root=Path(h.HISTORY_ROOTS[0]).absolute()
    require(root==root.resolve(),'The history root must be real');directory=root/'.native_development_material_reservations';directory.mkdir(parents=True,exist_ok=True)
    require(directory==directory.resolve(),'The global reservation directory must be real')
    fd=os.open(directory/'launch.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'a') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        current=h.selection_history(identity);require(all(r in current for r in frozen['selection_history_inventory']),'Known historical evidence disappeared')
        partition=h.history_partition(current);core={key:identity[key] for key in ('mode','input_definitions','input_values','goal_values','instruction_sha256')}
        path=directory/(canonical(core)+'.json');require(not path.exists() and not path.is_symlink(),'This logical material already reserved its permanent first attempt; no renamed/repacked retry')
        started=Path(prepared)/(mode+'_development_started.json');require(not started.exists(),'This prepared mode already started')
        r=write(path,{'kind':'period_boundary_permanent_material_first_attempt_reservation','version':1,'material_task_version':identity,
            'content_material_identity':core,'prepared_snapshot':ref(Path(prepared)/'probe_manifest.json'),'evaluation_output':str(destination),'mode':mode,
            'selection_history_inventory':current,'prior_model_selection_inventory':partition['model_selections'],'nonmodel_preparation_inventory':partition['nonmodel_preparations'],
            'model':'gpt-6.1-sol','reasoning_effort':'xhigh','outer_retries':0,'no_resampling_after_success_failure_or_infrastructure':True})
        return write(started,{'reservation':r,'history':current,'prior_model_selections':partition['model_selections'],'mode':mode,'model':'gpt-6.1-sol','reasoning_effort':'xhigh','concurrency':1,'outer_retries':0})


def effective_score(attempt,evaluation,resources):
    raw=attempt.get('raw_verifier_reward',attempt.get('reward'));timing=attempt.get('tool_time',{});valid=resources.get('passed') is True and resources.get('complete') is True
    known_budget=valid and attempt.get('status')=='scored' and attempt.get('failure_kind')=='cumulative_tool_budget_exhausted' and timing.get('passed') is False
    complete=valid and evaluation.get('status')=='completed' and attempt.get('status')=='scored' and not attempt.get('failure_kind') and timing.get('passed') is True and type(raw) in (int,float) and raw in (0,1)
    return {'raw_verifier_reward':raw,'effective_reward':0 if known_budget else raw if complete else None,
        'state':'known_tool_budget_failure' if known_budget else 'complete' if complete else 'unknown','infrastructure_unknown_is_not_model_zero':not known_budget and not complete}


def run_development(prepared,mode,destination,*,port=0):
    require(mode in MODES,'Choose one of the two frozen modes');prepared=Path(prepared).absolute();f=validate_prepared(prepared);m=f['modes'][mode]
    destination=Path(destination).absolute();require(destination==destination.resolve() and not destination.exists(),'Use a fresh evaluation output; no retry/resume')
    started=reserve(prepared,f,mode,destination);observer=None
    try:
        image=verify_local_base_image(PROFILE);write(prepared/(mode+'_actual_base_image.json'),image)
        backend=yaml.safe_load((ROOT/'config/llm.yaml').read_text());backend.update(model='gpt-6.1-sol',reasoning_effort='xhigh',roles={'trace_agent':{'model':'gpt-6.1-sol','reasoning_effort':'xhigh'}})
        async def once(directory,selection,audit,*,concurrency,backend_config):
            require(selection['selected_task_ids']==[m['task_id']] and selection['n_attempts']==1 and selection['phase']=='development'
                and selection['model']=='gpt-6.1-sol' and selection['reasoning_effort']=='xhigh'
                and concurrency==1 and selection['execution_budget']==BUDGET,'Exactly one frozen native attempt is allowed')
            await runner.execute_evaluation(directory,selection,audit,concurrency=1,backend_config=backend_config)
        with ResourceObserver(destination) as observer:
            evaluation=runner.run_evaluation(m['source_view']['path'],destination,phase='development',concurrency=1,project_root=ROOT,backend_config=backend,port=port,
                prior_selections=[r['path'] for r in read(started)['prior_model_selections']],execute=once)
        require(not evaluation.get('infra_history') and not evaluation.get('infrastructure_retries'),'Outer retries are forbidden')
        selection=read(destination/'selection_manifest.json')
        try:resources=validate_observation_receipt(destination,selection,evaluation)
        except Exception as error:
            runner._persist_failure(prepared/(mode+'_resource_failure'),error);resources={'passed':False,'complete':False,'error':ref(prepared/(mode+'_resource_failure/private/evaluation_error.json'))}
        attempts=evaluation.get('attempts',[]);require(len(attempts)<=1,'There cannot be multiple attempts')
        score=effective_score(attempts[0] if attempts else {},evaluation,resources)
        return write(prepared/(mode+'_development_terminal.json'),{'kind':'prequality_period_boundary_native_first_attempt_terminal','version':1,'started':started,
            'evaluation':ref(destination/'evaluation_manifest.json'),'selection':ref(destination/'selection_manifest.json'),'resource_observation':observer.receipt,'resources':resources,
            'score':score,'actual_attempts':attempts,'outer_retries':0,'phase':'development','qualified':False,'normal_all12_QA_passed':False,'difficulty_confirmation_claimed':False})
    except BaseException as error:
        runner._persist_failure(prepared/(mode+'_development_failure'),error)
        write(prepared/(mode+'_development_failure.json'),{'started':started,'error':ref(prepared/(mode+'_development_failure/private/evaluation_error.json')),
            'resource_observation':getattr(observer,'receipt',None),'qualified':False,'retry_authorized':False,'failure_is_not_automatically_model_zero':True})
        raise


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    a=sub.add_parser('prepare');a.add_argument('--validation',type=Path,required=True);a.add_argument('--output',type=Path,required=True)
    a=sub.add_parser('validate');a.add_argument('--prepared',type=Path,required=True)
    a=sub.add_parser('run-development');a.add_argument('--prepared',type=Path,required=True);a.add_argument('--mode',choices=MODES,required=True);a.add_argument('--output',type=Path,required=True);a.add_argument('--port',type=int,default=0)
    a=p.parse_args();r=prepare(a.validation,a.output) if a.command=='prepare' else validate_prepared(a.prepared) if a.command=='validate' else run_development(a.prepared,a.mode,a.output,port=a.port)
    print(json.dumps(r));return 0


if __name__=='__main__':raise SystemExit(main())

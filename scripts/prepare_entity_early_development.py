#!/usr/bin/env python3
"""Opt-in one-task early DEVELOPMENT bytes; unfinished quality never passes here."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sqlite3
import sys
from types import SimpleNamespace

import yaml
from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.evaluation.budget import validate_selection_execution_budget
from sheets_factory.evaluation.resource_frontier import TASK_FILES,MODEL,EFFORT
from sheets_factory.evaluation.resource_harbor import export_resource_harbor,inspect_resource_export,verify_local_base_image
from sheets_factory.evaluation.streaming_delta import compare_workbooks
from sheets_factory.evaluation.streaming_verifier import _sparse_cells
from sheets_factory.evaluation.tool_time_bounds import POLICY_V2
from sheets_factory.nodes.construction import InstructionNode
from sheets_factory.task_adapters.public_workbook_scope import canonical,CLAUSES
from sheets_factory.workbook.resource_engine import load_runtime_profile

TASK='dbg-6b213aa79237'
SOURCE_SHA='6b213aa79237185676a60ca0f6b0099a75cdecc78100589c5a4d4148d48b4e48'
MUTATIONS=60480
D_COUNT=261457
PREPARATION_KIND='prepared_first_fixed_plan_entity_group_G01_debugging_normal_quality'
BUDGET={'version':1,'elapsed_policy':'operational_guard','elapsed_guard_seconds':14400,'tool_budget_seconds':1800}
PENDING=['normal_instruction','joint_repair_certificate','five_local_controls','public_recovery','all_12_quality_checks','normal_export','real_Harbor_controls','fresh_20_task_confirmation']


def require(value,message):
    if not value:raise ValueError(message)


def write_new(path,value):
    with Path(path).open('x') as stream:json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
    return path


class FrozenFiles:
    """One streamed SHA per unchanged inode; never parse financial bindings."""
    def __init__(self):self.files={};self.signatures={}
    @staticmethod
    def signature(path):
        s=path.stat();return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)
    def ref(self,path,*,force=False):
        path=Path(path).absolute()
        require(path==path.resolve() and path.is_file(),'Evidence must be a real nonsymlink file')
        before=self.signature(path);key=str(path)
        if not force and key in self.files and self.signatures[key]==before:return self.files[key]
        h=hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda:stream.read(8*1024**2),b''):h.update(block)
        require(before==self.signature(path),'An early-development artifact changed during hashing')
        ref={'path':key,'sha256':h.hexdigest(),'bytes':before[2]}
        require(key not in self.files or self.files[key]==ref,'A frozen early-development artifact changed')
        self.files[key]=ref;self.signatures[key]=before;return ref
    def expected(self,ref):
        require(isinstance(ref,dict) and set(ref)=={'path','sha256','bytes'} and self.ref(ref['path'])==ref,
                'A declared immutable source artifact differs')
        return ref
    def mapping(self,values):
        require(isinstance(values,dict) and bool(values),'A complete frozen artifact map is required')
        for path,sha in values.items():
            require(type(sha) is str and re.fullmatch('[0-9a-f]{64}',sha) and self.ref(path)['sha256']==sha,
                    'A source or recipe SHA differs')
    def read(self,ref,*,max_bytes=1024**2):
        ref=self.ref(ref) if isinstance(ref,(str,Path)) else self.expected(ref)
        require(ref['bytes']<=max_bytes,'Do not parse financial binding tables in this early path')
        value=json.loads(Path(ref['path']).read_text());require(isinstance(value,dict),'A compact evidence object is required')
        return value
    def finish(self,critical=()):
        for path in tuple(self.files):self.ref(path,force=path in critical)


def read_state(run):
    with sqlite3.connect('file:'+str(Path(run)/'run.sqlite')+'?mode=ro',uri=True) as db:
        return {'run':json.loads(db.execute("select value from state where key='run'").fetchone()[0]),
            'tasks':[json.loads(r[0]) for r in db.execute('select payload from tasks')],
            'nodes':[json.loads(r[0]) for r in db.execute('select payload from nodes')]}


def current_task(state):
    tasks=[t for t in state['tasks'] if t.get('id')==TASK]
    require(len(tasks)==1 and type(tasks[0].get('revision')) is int and tasks[0]['revision']==0
        and tasks[0].get('source_id')==SOURCE_SHA and tasks[0].get('mode')=='debugging'
        and tasks[0].get('status') in ('running','ready','qualified') and state['run'].get('status')=='running',
        'Only the exact original G01 debugging revision zero is allowed')
    latest={n.get('node'):n for n in state['nodes'] if n.get('task_id')==TASK and n.get('revision')==0}
    require(all(latest.get(name,{}).get('status')=='completed' for name in ('normalize','profile','plan')),
        'Normal source normalization, complete profiling and planning must already complete')
    require(latest.get('construct',{}).get('status') in ('running','completed'),
        'The original normal construction must exist and have no recorded terminal failure')
    return tasks[0]


def validate_calculation(graph,reference,profile,source,output):
    value=graph.read(reference);graph.expected(source);graph.expected(output)
    requested=profile['docker_resources']['source']
    require(value.get('kind')=='resource_bound_libreoffice_call' and value.get('status')=='completed'
        and value.get('role')=='source' and value.get('source')==source and value.get('output')==output
        and value.get('destination')==output['path'] and value.get('image_id')==profile['image']['id']
        and type(value.get('container_id')) is str and re.fullmatch('[0-9a-f]{64}',value['container_id'])
        and value.get('actual_resources_verified') is True
        and value.get('actual_resources')=={'cpus_nanoseconds':2*10**9,'memory_bytes':32*1024**3,'pids_limit':requested['pids_limit']}
        and value.get('requested_resources')==requested and value.get('workbook_file_timeout_seconds')==600
        and value.get('solver_tool_budget')==profile['solver_tool_budget'],
        'The actual input/source execution and enforced resource identity differ')
    require(value.get('implementation')==graph.ref(ROOT/'src/sheets_factory/workbook/resource_engine.py')
        and value.get('upstream_engine')==graph.ref(ROOT/'src/sheets_factory/workbook/engine.py'),
        'The actual calculation implementation changed')
    require(value.get('profile_canonical_sha256')==canonical(profile)
        and value.get('profile') in (graph.ref(ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'),{'canonical_sha256':canonical(profile)}),
        'The actual calculation used another prospective profile')
    command=value.get('create_command',[])
    require('--network' in command and command[command.index('--network')+1]=='none'
        and profile['image']['id'] in command,'The actual source execution was not on the pinned isolated image')
    return value


def validate_source_receipts(run,graph):
    pre=graph.read(run/'preflight_manifest.json')
    require(pre.get('kind')==PREPARATION_KIND and pre.get('development_only') is True
        and type(pre.get('count')) is int and pre['count']==1 and pre.get('profile_id')=='G01'
        and pre.get('targets')=={'financial_modeling':0,'debugging':1}
        and pre.get('all_normal_quality_nodes_required') is True,'The trusted original one-source preparation differs')
    graph.mapping(pre['recipe_sha256']);graph.mapping(pre['source_artifacts_sha256'])
    graph.expected(pre['resolved_config']);config=yaml.safe_load(Path(pre['resolved_config']['path']).read_text())
    require(Path(config['run_dir']).absolute()==run and config['construction']['instruction_style']=='business_brief'
        and {key:config['run'].get(key) for key in pre['protected_task_budgets']}==pre['protected_task_budgets'],
        'The original run, public style or quality budgets changed')
    registry_ref=graph.ref(config['pipeline']['node_registry'])
    registry=yaml.safe_load(Path(registry_ref['path']).read_text())
    require(registry['nodes'].get('instruction')=='sheets_factory.nodes.construction:InstructionNode'
        and set(registry['nodes'])=={'normalize','profile','plan','construct','instruction','precheck','independent_recovery','trajectory','diagnose','repair','export'},
        'All ordinary normal quality routes must remain present')
    proof=graph.read(pre['source_admission']);graph.mapping(proof['artifact_sha256'])
    require(proof.get('kind')=='admitted_complete_fixed_plan_entity_group_financial_source'
        and proof.get('financial_seed_verified') is True and proof.get('fixed_plan_provided_and_protected') is True
        and proof.get('optimisation_performed') is False
        and proof.get('admission_implementation')==graph.ref(ROOT/'src/sheets_factory/pipelines/entity_group_admission.py'),
        'The existing complete source admission is required, not a passed flag')
    graph.expected(pre['prepared_seed_manifest']);seeds=json.loads(Path(pre['prepared_seed_manifest']['path']).read_text())['selected']
    require(len(seeds)==1 and seeds[0]['sha256']==SOURCE_SHA and seeds[0].get('modes')==['debugging']
        and seeds[0]['finance_evidence']['audited_source_binding']==proof
        and seeds[0]['source_manifest']==proof['source_manifest']==pre['source_manifest'],
        'The normal seed, exact source admission or current financial source changed')
    manifest=graph.read(proof['source_manifest']);preparation=graph.read(proof['source_preparation'])
    require(manifest.get('kind')=='independently_verified_hypothetical_fixed_plan_entity_group_source'
        and manifest.get('financial_audit_passed') is True and manifest.get('actual_LO_recalculations')==3
        and (manifest.get('entity_count'),manifest.get('month_count'),manifest.get('scenario_count'))==(24,120,3)
        and manifest.get('provided_plan_is_protected') is True and manifest.get('optimisation_performed') is False
        and manifest.get('workbook')==proof['workbook'] and proof['workbook']['sha256']==SOURCE_SHA
        and manifest.get('source_preparation')==proof['source_preparation']
        and manifest.get('bindings')==proof['bindings']
        and manifest.get('financial_audits')==proof['financial_audits']
        and preparation.get('resource_count')==proof['complete_count']==manifest.get('count')
        and manifest.get('source_recipe_sha256')==preparation['recipe_sha256'],
        'Initial actual source audit/preparation identities are incomplete')
    graph.mapping(preparation['recipe_sha256']);graph.expected(proof['bindings'])
    graph.expected(proof['runtime_profile']);profile=load_runtime_profile(proof['runtime_profile']['path'])
    require(profile['id']=='entity_group_large_v2' and profile==proof['runtime_profile_value']
        and proof['runtime_profile']==pre['runtime_profile']==manifest['runtime_profile']
        and config['engine']['image'] in profile['image'].values(),'The exact pinned v2 source/task resources changed')
    count=proof['complete_count'];enc=count['binding_encodings']
    fields=enc['scalar']+enc['exact_integer_pair']+6*enc['queues']
    require(fields==proof['logical_fields_checked']==1030770 and count['physical_formula_count']==1100346
        and count['physical_nonempty_cells']==2222012, 'The complete original G01 source scope differs')
    require(len(manifest['engine_calls'])==len(proof['financial_audits'])==3,'Three actual source passes/audits are required')
    previous=None
    for index,(call,audit_ref) in enumerate(zip(manifest['engine_calls'],proof['financial_audits']),1):
        require(type(call.get('index')) is int and call['index']==index and call.get('completed') is True
            and call.get('network')=='none' and call.get('runtime_profile')==proof['runtime_profile']
            and call.get('image_id')==profile['image']['id'] and call.get('workbook_file_timeout_seconds')==600
            and (previous is None or call['input']==previous),'The actual source execution chain differs')
        require(graph.read(call['terminal_receipt'])=={k:v for k,v in call.items() if k!='terminal_receipt'},
            'The actual source terminal receipt differs')
        started=graph.read(call['started_receipt'])
        require(started.get('completed') is False and started.get('input')==call['input'],'The actual source start receipt differs')
        validate_calculation(graph,call['actual_resource_receipt'],profile,call['input'],call['output'])
        audit=graph.read(audit_ref)
        require(audit.get('workbook')==call['output'] and audit.get('passed') is True
            and audit.get('all_independent_journal_fields_covered') is True and audit.get('all_scenarios_feasible') is True
            and audit.get('provided_fixed_plan_verified') is True and audit.get('optimisation_performed') is False
            and type(audit.get('logical_fields_checked')) is int and audit['logical_fields_checked']==fields
            and audit.get('physical_formulas_checked')==count['physical_formula_count']
            and audit.get('mismatches')==[] and audit.get('control_mismatches')==[],
            'A complete actual independent financial audit receipt failed')
        previous=call['output']
    require(manifest['engine_calls'][0]['output']==proof['workbook'],'The admitted goal is not the original audited first pass')
    stable=graph.read(proof['stability'])
    require(proof['stability']==manifest['stability'] and stable.get('stable') is True
        and all(stable.get(key,{}).get('passed') is True and stable[key].get('sheet_names_equal') is True
            and stable[key].get('mismatches')==[] and stable[key].get('checked_existing_value_cells')==count['physical_nonempty_cells']
            for key in ('first_against_goal','second_against_goal')),
        'Both original complete typed source stability receipts are required')
    return pre,config,proof,profile


def validate_physical_injection(goal,raw,edits):
    """Check every before/after assertion and all other raw cell definitions.

    This is a definition comparison, not an independent financial calculation,
    input stability proof, or individual fault-activity certificate.
    """
    expected={(e['sheet'],e['cell']):e for e in edits};seen=set();books=[]
    try:
        books=[load_workbook(path,read_only=True,data_only=False,keep_links=False) for path in (goal,raw)]
        require(books[0].sheetnames==books[1].sheetnames,'The raw mutation changed the original sheet list')
        for name in books[0].sheetnames:
            streams=[iter(_sparse_cells(book[name])) for book in books]
            try:
                heads=[next(stream,None) for stream in streams]
                while any(head is not None for head in heads):
                    coordinate=min(head[0] for head in heads if head is not None);cells=[]
                    for index,stream in enumerate(streams):
                        cell=None
                        if heads[index] is not None and heads[index][0]==coordinate:
                            cell=heads[index][1];heads[index]=next(stream,None)
                        cells.append(None if cell is None else (cell['data_type'],cell['value']))
                    key=(name,get_column_letter(coordinate[1])+str(coordinate[0]));edit=expected.get(key)
                    if edit is None:
                        require(cells[0]==cells[1],'An unapproved raw cell definition changed')
                    else:
                        require(cells==[('f',edit['before']),('f',edit['after'])],
                                'An asserted before/after formula differs from the actual raw mutation')
                        seen.add(key)
            finally:
                for stream in streams:stream.close()
        require(seen==set(expected),'An asserted mutation coordinate is absent from the actual workbook')
    finally:
        for book in books:book.close()


def selection_history(revision_hash,roots):
    location=ROOT/'scripts/prepare_resource_development_probe.py'
    spec=importlib.util.spec_from_file_location('_strict_early_history_support',location)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module.model_selection_history(revision_hash,TASK,0,roots)


def _freeze(run,output,*,development_only,history_roots):
    require(development_only is True,'Use explicit early development-only opt-in')
    run,output=Path(run).absolute(),Path(output).absolute()
    require(run==run.resolve() and output==output.resolve() and not output.exists()
        and output.is_relative_to(Path('/data')) and not output.is_relative_to(run), 'A fresh real separate /data snapshot is required')
    graph=FrozenFiles();initial=current_task(read_state(run))
    pre,config,proof,profile=validate_source_receipts(run,graph)
    directory=run/'tasks'/TASK/'revisions/000';private=directory/'private';source=directory/'public/input.xlsx';goal=private/'goal.xlsx'
    require(not (private/'diagnosis.json').exists(),
            'A normal diagnosis already exists; use the normal quality-gated snapshot and its findings')
    source_ref,goal_ref,raw_ref=map(graph.ref,(source,goal,private/'mutated_unrecalculated.xlsx'))
    require(goal_ref['sha256']==proof['workbook']['sha256']==SOURCE_SHA,'The current goal differs from its three audited source passes')
    plan=graph.read(private/'plan.json',max_bytes=128*1024**2);edits=plan.get('edits',[])
    policy=graph.read(private/'entity_group_policy_inventory.json');family=plan.get('family_adapter',{})
    require(plan.get('mode')=='debugging' and not plan.get('scenario_inputs') and 'mask_ranges' not in plan
        and family==policy and family.get('id')=='entity_group_fixed_plan_financial_debug_v1'
        and family.get('source_sha256')==SOURCE_SHA and family.get('activity_contract')=='full_workbook_joint_repair'
        and type(family.get('physical_formula_mutation_count')) is int and family['physical_formula_mutation_count']==len(edits)==MUTATIONS
        and family.get('mutations_truncated') is False and family.get('selection_uses_model_outcomes') is False
        and family.get('individual_or_marginal_activity_claimed') is False
        and CLAUSES['debugging'] in plan.get('public_instruction',''), 'The exact current complete policy mutation plan changed')
    physical=[{key:e[key] for key in ('sheet','cell','before','after')} for e in edits]
    require(canonical(physical)==family['physical_edits_sha256'] and len({(e['sheet'],e['cell']) for e in edits})==MUTATIONS
        and all(type(e['before']) is str and e['before'].startswith('=') and type(e['after']) is str
            and e['after'].startswith('=') and e['before']!=e['after'] for e in edits),
        'Physical formula assertions or complete mutation SHA differ')
    edit_validation_ref=graph.ref(private/'edit_validation.json')
    validate_physical_injection(goal,Path(raw_ref['path']),edits)
    guards={filename:graph.read(private/filename,max_bytes=128*1024**2)
        for filename in ('native_risk_guard.json','native_error_probe.json')}
    require(all(value.get('blocking') is False and value.get('state')=='not_applicable'
        and value.get('source_sha256')==SOURCE_SHA for value in guards.values()),
        'An actual current native guard is blocking, unknown or bound to another source')
    saved=graph.read(private/'expected_delta.json',max_bytes=128*1024**2)
    require(type(saved.get('expected_change_count')) is int and saved['expected_change_count']==D_COUNT
        and len(saved.get('expected_changes',[]))==len(set(saved['expected_changes']))==D_COUNT,
        'The complete saved expected delta is missing or truncated')
    error_guard=guards['native_error_probe.json']
    require(error_guard.get('goal_sha256')==goal_ref['sha256'] and error_guard.get('plan_sha256')==canonical(plan)
        and error_guard.get('revision')==0 and type(error_guard.get('revision')) is int
        and error_guard.get('required_delta')==saved['expected_changes']
        and error_guard.get('required_delta_sha256')==canonical(saved['expected_changes']),
        'The actual native-error guard does not cover this exact plan, goal and complete D')
    actual=compare_workbooks(source,goal,goal)
    require(actual==saved and actual.get('reward')==1 and actual.get('structure_ok') is True,
        'The full current cached-value D differs from normal construction')
    calls=[]
    for file in sorted((run/'resource_receipts').glob('*.terminal.json')):
        value=json.loads(file.read_text())
        if value.get('destination')==str(source) and value.get('source')==raw_ref and value.get('output')==source_ref:
            reference=graph.ref(file);validate_calculation(graph,reference,profile,raw_ref,source_ref);calls.append(reference)
    require(calls,'An actual completed first-mutant calculation with exact current input/output SHA is required')
    output.mkdir(parents=True)
    stage=output/'private/ordinary_instruction_replay';(stage/'public').mkdir(parents=True)
    replay=InstructionNode().execute(SimpleNamespace(data={'plan':plan,'input':source},mode='debugging',config=config,revision_dir=stage))
    instruction=stage/'public/instruction.md';instruction_ref=graph.ref(instruction);revision_hash=replay['revision_hash']
    normal_instruction=directory/'public/instruction.md'
    if normal_instruction.exists():require(normal_instruction.read_bytes()==instruction.read_bytes(),'The already saved normal instruction differs')
    require(initial.get('revision_hash') in (None,revision_hash),'The actual current normal revision hash differs')
    history=selection_history(revision_hash,[ROOT/'outputs/difficulty',*history_roots])
    for ref in history:graph.expected(ref)
    for module in (Path(__file__),ROOT/'src/sheets_factory/nodes/construction.py',ROOT/'src/sheets_factory/evaluation/streaming_delta.py',
            ROOT/'src/sheets_factory/evaluation/resource_harbor.py',ROOT/'src/sheets_factory/evaluation/resource_frontier.py',
            ROOT/'src/sheets_factory/evaluation/frontier.py',ROOT/'scripts/prepare_resource_development_probe.py'):
        graph.ref(module)
    base=verify_local_base_image(proof['runtime_profile']['path'])
    write_new(output/'actual_local_base_image.json',base);graph.ref(output/'actual_local_base_image.json')
    staging=output/'private/export_input';(staging/'public').mkdir(parents=True);(staging/'private').mkdir()
    for src,dest in ((source,staging/'public/input.xlsx'),(goal,staging/'private/goal.xlsx'),(instruction,staging/'public/instruction.md')):
        shutil.copyfile(src,dest)
    target=output/'SpreadsheetEval'/TASK
    export_resource_harbor(staging,target,{'task_id':TASK,'mode':'debugging','source_id':SOURCE_SHA,'revision':0,
        'revision_hash':revision_hash,'difficulty_status':'early_development_quality_pending','base_image':profile['image']['tag']},
        ROOT,runtime_profile=proof['runtime_profile']['path'])
    binding=inspect_resource_export(target)
    require(binding.get('task_id')==TASK and type(binding.get('revision')) is int and binding['revision']==0
        and binding.get('revision_hash')==revision_hash,'The early resource export identity differs')
    require((target/'instruction.md').read_bytes()==instruction.read_bytes()
        and graph.ref(target/'environment/input.xlsx')['sha256']==source_ref['sha256']
        and graph.ref(target/'tests/reference.xlsx')['sha256']==goal_ref['sha256'],'The exported current public/private bytes differ')
    inventory={path.relative_to(target).as_posix():graph.ref(path) for path in target.rglob('*') if path.is_file()}
    require(set(inventory)==set(TASK_FILES) and len(inventory)==17,'The full seventeen-file early export is required')
    final_task=current_task(read_state(run))
    require(final_task.get('revision_hash') in (None,revision_hash),'The normal task advanced to another instruction hash')
    require(not (private/'diagnosis.json').exists(),'A normal diagnosis appeared while the early task was frozen')
    graph.finish(critical={str(source),str(goal),str(private/'plan.json'),str(private/'expected_delta.json')})
    if normal_instruction.exists():require(normal_instruction.read_bytes()==instruction.read_bytes(),'The normal instruction advanced to different bytes')
    require(selection_history(revision_hash,[ROOT/'outputs/difficulty',*history_roots])==history,
        'A first selection appeared or history changed while the early task was frozen')
    task={'task_id':TASK,'mode':'debugging','source_id':SOURCE_SHA,'revision':0,'revision_hash':revision_hash,
        'task_directory':str(target),'harbor_export_binding':binding,'source_kind':'early_unqualified_development_probe',
        'execution_budget':dict(BUDGET),'timeout_seconds':14400,'tool_time_policy':dict(POLICY_V2)}
    manifest={'kind':'early_entity_development_probe','schema_version':1,'source_kind':'early_unqualified_development_probe',
        'development_only':True,'count':1,'confirmation_allowed':False,'publication_allowed':False,'qualified':False,'task_count':0,
        'selected_task_ids':[TASK],'tasks':[task],'main_quality_run':str(run),'model':MODEL,'reasoning_effort':EFFORT,
        'execution_budget':dict(BUDGET),'timeout_seconds':14400,'tool_time_policy':dict(POLICY_V2),'tool_time_policy_version':2,
        'source_artifacts_sha256':{path:ref['sha256'] for path,ref in graph.files.items()},'resource_task_inventory':inventory,
        'current_input':source_ref,'audited_goal':goal_ref,'plan':graph.ref(private/'plan.json'),'complete_D':graph.ref(private/'expected_delta.json'),
        'complete_changed_value_count':D_COUNT,'physical_formula_mutations':MUTATIONS,'physical_edits_sha256':family['physical_edits_sha256'],
        'normal_edit_validation':edit_validation_ref,'raw_physical_injection_assertions_checked':True,
        'normal_quality_same_version_required':{'source_sha256':SOURCE_SHA,'input_sha256':source_ref['sha256'],
            'goal_sha256':goal_ref['sha256'],'instruction_sha256':instruction_ref['sha256'],
            'physical_edits_sha256':family['physical_edits_sha256'],'revision_hash':revision_hash,
            'runtime_profile':proof['runtime_profile'],'resource_export_binding':binding,
            'grader_sha256':inventory['tests/verify.py']['sha256'],
            'comparison_sha256':inventory['tests/streaming_core.py']['sha256']},
        'initial_source_audit_receipts':proof['financial_audits'],'actual_current_input_calculations':calls,
        'source_admission':pre['source_admission'],'ordinary_InstructionNode_replay':instruction_ref,
        'ordinary_instruction_node_is_not_claimed_completed':True,'pending_normal_gates':list(PENDING),
        'joint_input_stability_certified':False,'individual_or_marginal_root_activity_claimed':False,
        'five_local_controls_certified':False,'independent_recovery_certified':False,'all_12_QA_certified':False,
        'actual_Harbor_controls_certified':False,'actual_agent_verifier_resources_certified':False,
        'prior_model_selection_inventory':history,'zero_is_provisional_until_same_version_full_normal_quality':True,
        'success_may_reject_candidate_early':True,'no_resampling_authorized':True,
        'new_financial_audits':0,'financial_bindings_table_parsed':False,'new_LO_calls':0,'new_model_calls':0,'new_Harbor_jobs':0,
        'full_source_receipt_graph_rehashed_without_reexecuting_finance':True,
        'resource_limits_and_grader_unchanged':True,'frozen_at':datetime.now(timezone.utc).isoformat()}
    validate_selection_execution_budget(manifest)
    path=write_new(output/'probe_manifest.json',manifest);return graph.ref(path)


def freeze_early_probe(run,output,*,development_only=False,history_roots=()):
    existed=Path(output).exists()
    try:return _freeze(run,output,development_only=development_only,history_roots=history_roots)
    except BaseException as error:
        path=Path(output)
        if not existed and path.is_dir() and not (path/'probe_manifest.json').exists():
            write_new(path/'snapshot_failure.json',{'kind':'early_entity_development_snapshot_failure','error_type':type(error).__name__,
                'error':str(error),'all_partial_artifacts_preserved':True,'qualified':False,'new_models':0,'new_LO_calls':0,'new_Harbor_jobs':0})
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-run',type=Path,required=True);parser.add_argument('--output',type=Path)
    parser.add_argument('--early-development-only',action='store_true');parser.add_argument('--freeze',action='store_true')
    parser.add_argument('--history-root',type=Path,action='append',default=[])
    args=parser.parse_args(argv)
    if args.freeze:
        require(args.output is not None,'A new output is required for explicit early freezing')
        result=freeze_early_probe(args.source_run,args.output,development_only=args.early_development_only,history_roots=args.history_root)
    else:
        require(args.output is None,'Use explicit --freeze to create an early task')
        current_task(read_state(args.source_run));result={'development_only':True,'count':1,'snapshot_created':False,'all_quality_pending':True}
    print(json.dumps(result,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())

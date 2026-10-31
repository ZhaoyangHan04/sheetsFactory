"""Resource snapshot guards with explicit offline service/admission boundaries."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]
_spec=importlib.util.spec_from_file_location('_resource_development_probe_test',ROOT/'scripts/prepare_resource_development_probe.py')
probe=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(probe)


def dump(path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return probe.stream_reference(path)


def nodes(task_id='task',revision=0):
    return [{'task_id':task_id,'revision':revision,'node':name,'status':'completed'} for name in probe.NORMAL_NODES]


@pytest.mark.parametrize('change',['missing','running','new_revision','latest_failed'])
def test_six_actual_current_node_completions_not_file_existence(change):
    records=nodes()
    if change=='missing':records.pop()
    if change=='running':records[-1]['status']='running'
    if change=='new_revision':records[-1]['revision']=1
    if change=='latest_failed':records.append({**records[-1],'status':'failed'})
    with pytest.raises(ValueError,match='has not completed'):probe.require_completed_nodes({'nodes':records},'task',0)


def test_history_all_selections_rejects_hash_and_same_task_revision_without_reading_score(tmp_path):
    first=dump(tmp_path/'a/selection_manifest.json',{'phase':'development','tasks':[{'task_id':'old','revision':0,'revision_hash':'before','reward':1}]})
    second=dump(tmp_path/'b/selection_manifest.json',{'phase':'confirmation','tasks':[{'task_id':'another','revision':1,'revision_hash':'elsewhere','reward':0}]})
    assert probe.model_selection_history('new','task',0,[tmp_path,Path(first['path'])])==[first,second]
    with pytest.raises(ValueError,match='do not resample'):probe.model_selection_history('before','new-id',2,[tmp_path])
    with pytest.raises(ValueError,match='do not resample'):probe.model_selection_history('other','old',0,[tmp_path])
    dump(tmp_path/'bad/selection_manifest.json',{'tasks':'not a selected task list'})
    with pytest.raises(ValueError,match='malformed'):probe.model_selection_history('new','task',0,[tmp_path])


@pytest.fixture
def resource_case(tmp_path):
    profile=probe.reference(ROOT/'config/runtime_profiles/entity_group_large_v2.yaml')
    parsed=probe.load_runtime_profile(profile['path'])
    revision=tmp_path/'tasks/task/revisions/000';revision.mkdir(parents=True)
    raw=revision/'draft.fixture';raw.write_bytes(b'Explicit offline calculation input')
    actual=revision/'actual.fixture';actual.write_bytes(b'Explicit offline calculation result')
    canonical=revision/'controls/canonical.fixture';canonical.parent.mkdir();shutil.copyfile(actual,canonical)
    receipts=tmp_path/'resource_receipts';receipts.mkdir()
    desired=parsed['docker_resources']['source']
    record={'kind':'resource_bound_libreoffice_call','status':'completed','profile':profile,'role':'source',
        'image_id':parsed['image']['id'],'actual_resources_verified':True,'container_id':'a'*64,
        'implementation':probe.reference(ROOT/'src/sheets_factory/workbook/resource_engine.py'),
        'upstream_engine':probe.reference(ROOT/'src/sheets_factory/workbook/engine.py'),
        'actual_resources':{'cpus_nanoseconds':2*10**9,'memory_bytes':32*1024**3,'pids_limit':256},
        'requested_resources':desired,'workbook_file_timeout_seconds':600,
        'source':probe.stream_reference(raw),'output':probe.stream_reference(actual),'destination':str(actual)}
    receipt=dump(receipts/'one.terminal.json',record)
    return SimpleNamespace(run=tmp_path,revision=revision,profile=profile,raw=raw,actual=actual,canonical=canonical,
        receipt=receipt,record=record)


def test_actual_resource_shape_binds_current_bytes_including_canonical_copies(resource_case):
    c=resource_case
    result=probe.resource_receipts(c.run,c.revision,c.profile,[('copied_control',c.raw,c.canonical)])
    assert result[0]['actual_calculation_receipts']==[c.receipt]
    assert result[0]['output']['path']!=c.record['output']['path']
    assert result[0]['output']['sha256']==c.record['output']['sha256']


@pytest.mark.parametrize('change',['unverified','RAM','image','profile','output_bytes','raw_bytes','wrong_revision','missing_container','wrong_implementation'])
def test_actual_resource_evidence_cannot_be_inferred_from_requested_settings(resource_case,change):
    c=resource_case;record=deepcopy(c.record)
    if change=='unverified':record['actual_resources_verified']=False
    if change=='RAM':record['actual_resources']['memory_bytes']=8*1024**3
    if change=='missing_container':record.pop('container_id')
    if change=='wrong_implementation':record['implementation']=record['upstream_engine']
    if change=='image':record['image_id']='sha256:'+'f'*64
    if change=='profile':record['profile']=probe.reference(ROOT/'config/runtime_profiles/entity_group_large_v1.yaml')
    if change=='output_bytes':c.actual.write_bytes(b'changed')
    if change=='raw_bytes':c.raw.write_bytes(b'changed')
    if change=='wrong_revision':record['destination']=str(c.revision.parent/'999/other.fixture')
    dump(Path(c.receipt['path']),record)
    with pytest.raises(ValueError):probe.resource_receipts(c.run,c.revision,c.profile,[('control',c.raw,c.canonical)])


@pytest.fixture(params=['entity','scaled_capital'])
def snapshot(tmp_path,monkeypatch,request):
    family=request.param;run=tmp_path/'run';run.mkdir();task_id='debug-offline' if family=='entity' else 'fm-offline'
    directory=run/'tasks'/task_id/'revisions/000';public=directory/'public';private=directory/'private'
    public.mkdir(parents=True);private.mkdir()
    origin=tmp_path/'original.fixture';origin.write_bytes(b'Explicit mocked source-admission boundary')
    goal=private/'goal.xlsx';shutil.copyfile(origin,goal)
    source=public/'input.xlsx';source.write_bytes(b'Explicit mocked current input boundary')
    mode=probe.FAMILIES[family][1]
    plan={'title':'Offline boundary only','edits':[{'sheet':'Finance','cell':'B1','before':'=1','after':'=2' if family=='entity' else None}],
        'public_instruction':'Repair or complete provided model. '+probe.CLAUSES[mode],'public_rules':['Public fixture.']}
    config={'project_root':str(ROOT),'run_dir':str(run),'construction':{'instruction_style':'business_brief'},
        'engine':{'image':'sheetsfactory-lo:24.2-iterative-openpyxl315-v1'},'family_setting':{
            'runtime_profile':probe.reference(ROOT/'config/runtime_profiles/entity_group_large_v2.yaml')}}
    probe.InstructionNode().execute(SimpleNamespace(data={'plan':plan,'input':source},mode=mode,config=config,revision_dir=directory))
    common={'structure_ok':True,'expected_change_count':2,'actual_change_count':2,
        'expected_changes':['Finance!B1','Arithmetic!B1'],'actual_changes':['Finance!B1','Arithmetic!B1'],
        'missing_changes':[],'extra_changes':[],'wrong_values':[]}
    controls={name:{**deepcopy(common),'reward':reward} for name,reward in probe.CONTROL_REWARDS.items()}
    dump(private/'local_controls.json',controls);dump(private/'expected_delta.json',controls['oracle'])
    dump(private/'plan.json',plan);dump(private/probe.FAMILIES[family][2],{})
    for name in ('edit_validation.json','root_impacts.json'):dump(private/name,{})
    for name in ('native_risk_guard.json','native_error_probe.json'):dump(private/name,{'blocking':False})
    dump(public/'profile.json',{'truncated':False});(private/'mutated_unrecalculated.xlsx').write_bytes(b'Offline raw draft')
    if family=='entity':
        dump(private/'joint_repair_certificate.json',{'engine_calls':[]});dump(private/'joint_control_selection.json',{})
    else:
        dump(private/'scaled_capital_actual_input_scope.json',{'input':probe.stream_reference(source),'goal':probe.stream_reference(goal),
            'actual_normal_draft':probe.stream_reference(private/'mutated_unrecalculated.xlsx'),
            'complete_required_D_count':2,'changed_helper_count':1})
    for name in ('equivalent','missed_root','extra_change'):
        for suffix in ('_raw.xlsx','.xlsx'):
            path=private/'controls'/(name+suffix);path.parent.mkdir(exist_ok=True);path.write_bytes(b'Offline '+name.encode())
    for name in ('preflight_manifest.json','resolved_config.yaml','seed_manifest.json'):(run/name).write_text('{}')
    proof={'workbook':probe.stream_reference(origin),'source_manifest':{'explicit':'mock source admission'}}
    seed={'sha256':proof['workbook']['sha256'],'local_path':str(origin)}
    state={'tasks':[{'id':task_id,'mode':mode,'revision':0,'source_id':seed['sha256']}],
        'nodes':nodes(task_id),'run':{'status':'running'}}
    phase=SimpleNamespace(adapter=SimpleNamespace(SETTING='family_setting'))
    monkeypatch.setattr(probe,'read_run',lambda *args:state)
    monkeypatch.setattr(probe,'validate_preparation',lambda *args:(phase,{'recipe_sha256':{},'source_artifacts_sha256':{}},config,seed,proof))
    monkeypatch.setattr(probe,'validate_family_plan',lambda *args:{'Arithmetic!B1'})
    monkeypatch.setattr(probe,'resource_receipts',lambda *args:[])
    monkeypatch.setattr(probe,'model_selection_history',lambda *args:[])
    events=[]
    def compare(source,goal,candidate):
        name='oracle' if candidate==goal else 'nop' if candidate==source else Path(candidate).stem
        events.append(name);return deepcopy(controls[name])
    monkeypatch.setattr(probe,'compare_workbooks',compare)
    monkeypatch.setattr(probe,'verify_local_base_image',lambda profile:{'explicit_mock_base_tag_boundary':True})
    def export(task,target,metadata,project_root,*,runtime_profile):
        events.append('resource_helper')
        for name in probe.TASK_FILES:
            path=target/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'Explicit export inventory boundary')
        shutil.copyfile(public/'instruction.md',target/'instruction.md')
        shutil.copyfile(source,target/'environment/input.xlsx');shutil.copyfile(goal,target/'tests/reference.xlsx')
    monkeypatch.setattr(probe,'export_resource_harbor',export)
    monkeypatch.setattr(probe,'inspect_resource_export',lambda *args:{'task_id':task_id,'revision':0,
        'revision_hash':__import__('hashlib').sha256(source.read_bytes()+(public/'instruction.md').read_bytes()).hexdigest()})
    return SimpleNamespace(run=run,family=family,task_id=task_id,private=private,state=state,events=events,
        output=tmp_path/'probe',controls=controls)


def test_snapshot_exact_current_instruction_fullD_controls_and_prequality_claims(snapshot):
    c=snapshot
    record=probe.freeze_probe(c.run,c.task_id,0,c.output,family=c.family)
    manifest=probe.read_ref(record)
    assert c.events==list(probe.CONTROL_REWARDS)+['resource_helper']
    assert manifest['family']==c.family and len(manifest['resource_task_inventory'])==17
    assert manifest['normal_InstructionNode_replay_exact'] is True
    assert manifest['normal_ExportNode_called_on_actual_task'] is False
    assert manifest['same_frozen_resource_export_helper_called'] is True
    assert manifest['qualified'] is False and manifest['task_count']==0
    assert manifest['public_recovery_status_at_snapshot']==manifest['diagnosis_status_at_snapshot']=='pending'
    assert manifest['new_LO_calls_during_preparation']==manifest['new_model_calls_during_preparation']==0
    assert probe.validate_selection_execution_budget(manifest)==probe.BUDGET
    assert manifest['model']=='gpt-6.1-sol' and manifest['reasoning_effort']=='xhigh'


@pytest.mark.parametrize('change',['precheck_running','wrong_revision','control_failed','native_blocking','missing_D'])
def test_no_early_or_invalid_snapshot_and_no_export(snapshot,change):
    c=snapshot
    if change=='precheck_running':c.state['nodes'][-1]['status']='running'
    if change=='wrong_revision':c.state['tasks'][0]['revision']=1
    if change=='control_failed':c.controls['nop']['reward']=1
    if change=='native_blocking':dump(c.private/'native_error_probe.json',{'blocking':True})
    if change=='missing_D':
        delta=probe.read(c.private/'expected_delta.json');delta['expected_changes'].pop();dump(c.private/'expected_delta.json',delta)
    with pytest.raises(ValueError):probe.freeze_probe(c.run,c.task_id,0,c.output,family=c.family)
    assert 'resource_helper' not in c.events and not c.output.exists()


def test_nonempty_snapshot_never_overwritten_and_default_cli_is_readonly(snapshot):
    c=snapshot;c.output.mkdir();marker=c.output/'original';marker.write_text('preserve')
    with pytest.raises(ValueError,match='fresh'):probe.freeze_probe(c.run,c.task_id,0,c.output,family=c.family)
    assert marker.read_text()=='preserve'
    assert probe.main(['--family',c.family,'--run',str(c.run),'--task-id',c.task_id])==0
    assert not c.events


def test_completed_nodes_must_still_be_current_at_snapshot_end(snapshot,monkeypatch):
    c=snapshot;calls=[]
    def state(*args):
        calls.append(True)
        result=deepcopy(c.state)
        if len(calls)>1:result['nodes'][-1]['status']='running'
        return result
    monkeypatch.setattr(probe,'read_run',state)
    with pytest.raises(ValueError,match='has not completed'):
        probe.freeze_probe(c.run,c.task_id,0,c.output,family=c.family)
    failure=probe.read(c.output/'snapshot_failure.json')
    assert failure['all_partial_artifacts_preserved'] is True and failure['qualified'] is False
    assert not (c.output/'probe_manifest.json').exists()


def test_exact_instruction_replay_cannot_be_replaced_by_just_scope_phrase(snapshot):
    c=snapshot
    path=c.private.parent/'public/instruction.md';path.write_text(path.read_text()+'Unexpected public rule.\n')
    with pytest.raises(ValueError,match='instruction bytes differ'):
        probe.freeze_probe(c.run,c.task_id,0,c.output,family=c.family)
    assert 'resource_helper' not in c.events
    assert (c.output/'snapshot_failure.json').exists()


def test_actual_control_history_receipts_bind_all_prior_failed_artifacts(tmp_path):
    raw=tmp_path/'old_raw.fixture';raw.write_bytes(b'Failed control input retained')
    leaf=probe.stream_reference(raw)
    older=dump(tmp_path/'old_attempt.json',{'status':'failed','raw':leaf})
    latest=dump(tmp_path/'successful_attempt.json',{'prior_failed_attempts':[older]})
    mapping={};probe.bind_receipt_references(latest,mapping)
    assert mapping[leaf['path']]==leaf['sha256'] and mapping[older['path']]==older['sha256']
    raw.write_bytes(b'Changed old failed control input')
    with pytest.raises(ValueError,match='control-history artifact changed'):
        probe.bind_receipt_references(latest,{})


def test_mismatched_export_identity_preserves_partial_snapshot_without_manifest(snapshot,monkeypatch):
    c=snapshot
    monkeypatch.setattr(probe,'inspect_resource_export',lambda *args:{'task_id':'another','revision':0,'revision_hash':'other'})
    with pytest.raises(ValueError,match='export identity'):
        probe.freeze_probe(c.run,c.task_id,0,c.output,family=c.family)
    assert (c.output/'snapshot_failure.json').exists() and not (c.output/'probe_manifest.json').exists()


@pytest.mark.parametrize('family',['entity','scaled_capital'])
@pytest.mark.parametrize('change',['none','application','reduced','scenario','mask_ranges','public_scope','helper_protected'])
def test_family_plan_scope_revalidated_before_any_export(tmp_path,monkeypatch,family,change):
    """Isolate the adapter compiler; its production dimensions have own tests."""
    directory=tmp_path/'revision';private=directory/'private';private.mkdir(parents=True)
    markdown=tmp_path/'candidate_contract.md';markdown.write_text('Complete public field dictionary.\n')
    plan={'edits':[{'sheet':'S','cell':'B1','before':'=1','after':None},
                   {'sheet':'S','cell':'B2','before':'=2','after':None}],
        'family_adapter':{'complete':'explicit compiler boundary'},'scenario_inputs':[],
        'public_instruction':probe.CLAUSES[probe.FAMILIES[family][1]]+'\n'+markdown.read_text()}
    expected=deepcopy(plan);application=deepcopy(plan['family_adapter'])
    binding=dump(tmp_path/'binding.json',{'arithmetic_bindings':[{'sheet':'Arithmetic','cell':'B1','plan_dependent':True}]})
    proof={'bindings':binding,'public_contract_artifacts':{'candidate_contract_markdown':probe.reference(markdown)}}
    physical=lambda edits:[{key:e[key] for key in ('sheet','cell','before','after')} for e in edits]
    adapter=SimpleNamespace(_physical=physical,propose_from_checked_proof=lambda *a:deepcopy(expected),
        _propose_from_checked_proof=lambda *a:deepcopy(expected),audit_input_helper_caches=lambda *a:None)
    phase=SimpleNamespace(adapter=adapter)
    dump(private/'joint_repair_certificate.json',{'explicit':'joint validator boundary'})
    monkeypatch.setattr(probe,'validate_joint_certificate',lambda *a:{'complete_required_D_count':2})
    scope={'expected_change_count':2,'passed':True,'masked_financial_and_decision_count':25541,
        'provided_helper_formula_count':51972,'plan_dependent_caches_cleared_count':1,
        'cleared_support_coordinates_sha256':probe.canonical(['Arithmetic!B1']),
        'unselected_definitions_and_public_primitives_unchanged':True,'helpers_physically_masked':False,
        'helper_values_protected':False,'no_helper_values_excluded_from_required_D':True}
    if change=='application':application['complete']='different'
    if change=='reduced':plan['edits'].pop()
    if change=='scenario':plan['scenario_inputs']=[{'after':5}]
    if change=='mask_ranges':plan['mask_ranges']=[]
    if change=='public_scope':plan['public_instruction']=markdown.read_text()
    if change=='helper_protected':
        if family=='scaled_capital':scope['helper_values_protected']=True
        else:application['complete']='unsupported helper policy'
    if change=='none':
        result=probe.validate_family_plan(family,phase,plan,application,scope,proof,tmp_path/'goal.fixture',private)
        assert result==({'Arithmetic!B1'} if family=='scaled_capital' else set())
    else:
        with pytest.raises(ValueError):probe.validate_family_plan(family,phase,plan,application,scope,proof,tmp_path/'goal.fixture',private)

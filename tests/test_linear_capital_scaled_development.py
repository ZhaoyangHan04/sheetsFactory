"""N360 first-attempt exports with mocked source, image, model and observer boundaries."""
from copy import deepcopy
import fcntl
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
descriptor = importlib.util.spec_from_file_location('_linear_development_test',
    ROOT/'scripts/prepare_linear_capital_scaled_development.py')
probe = importlib.util.module_from_spec(descriptor); descriptor.loader.exec_module(probe)


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False)+'\n')
    return probe.reference(path)


def workbook(path, value, *, formula=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    book = openpyxl.Workbook(); sheet = book.active; sheet.title = 'Finance'
    sheet['A1'] = 'Supplied business label'; sheet['B1'] = value
    if formula is not None: sheet['C1'] = formula
    book.save(path); book.close(); return probe.reference(path)


@pytest.fixture(params=['financial_modeling', 'debugging'])
def case(tmp_path, monkeypatch, request):
    mode = request.param
    source_book = workbook(tmp_path/'source.xlsx', 12)
    source = dump(tmp_path/'source_manifest.json', {'kind': 'independently_verified_linear_capital_scaled_native_source', 'version': 1,
        'workbook': source_book,
        'runtime_profile': probe.reference(ROOT/'config/runtime_profiles/entity_group_large_v2.yaml')})
    raw_input = workbook(tmp_path/'view/public/input.xlsx', None if mode == 'financial_modeling' else 0)
    raw_goal = workbook(tmp_path/'view/private/goal.xlsx', 12)
    instruction = tmp_path/'view/public/instruction.md'
    instruction.write_text('Complete the existing labelled model. Save it to /app/output.xlsx.\n')
    instruction_ref = probe.reference(instruction)
    family = 'real_policy_fixture'
    edits = [{'sheet': 'Finance', 'cell': 'B1', 'before': '=12', 'after': '=0', 'family': family}]
    plan = dump(tmp_path/'view/private/view_plan.json', {'mode': mode,
        'masked_targets': [{'sheet': 'Finance', 'cell': 'B1'}] if mode == 'financial_modeling' else [],
        'formula_edits': edits if mode == 'debugging' else [], 'choice_edits': [],
        'instruction': instruction.read_text()})
    view = dump(tmp_path/'view/private/view_manifest.json', {'mode': mode, 'source': source_book,
        'kind': 'materialized_unverified_linear_capital_scaled_task_view', 'version': 1,
        'plan': plan, 'specification_sha256': '1'*64, 'input': raw_input, 'goal': raw_goal,
        'instruction': instruction_ref, 'family_inputs': {family: raw_input} if mode == 'debugging' else {}})
    from sheets_factory.evaluation.streaming_delta import compare_workbooks
    delta = dump(tmp_path/'actual/full_D.json', compare_workbooks(raw_input['path'], raw_goal['path'], raw_goal['path']))
    roles = ['goal_reference', 'input_pass1', 'input_pass2', 'input_pass3',
        'control_equivalent', 'control_missed_root', 'control_extra_change']
    if mode == 'debugging':
        roles = ['same_temporary_plan_baseline', 'isolated_fixture_1', 'isolated_fixture_2', 'isolated_fixture_3', *roles]
    actual = dump(tmp_path/'actual/validation.json', {'kind': 'linear_capital_scaled_task_view_actual_validation',
        'version': 2, 'source_provider': 'scaled360', 'passed': True, 'mode': mode, 'source_admission': source, 'materialized_view': view,
        'input': raw_input, 'goal': raw_goal, 'instruction': instruction_ref, 'complete_D': delta,
        'local_controls': deepcopy(probe.CONTROL_REWARDS), 'source_original_unchanged': True,
        'actual_LO_calls': [{'index': index+1, 'role': role, 'completed': True} for index, role in enumerate(roles)],
        'qualified': False})
    calls = []
    def validate_completed(ref):
        calls.append(ref); value = probe.read(ref)
        if value.get('offline_validator_failure'):
            raise ValueError('Explicit mocked actual-stage/source validator rejected missing genuine evidence')
        return value
    fake_driver = SimpleNamespace(validate_completed=validate_completed)
    monkeypatch.setattr(probe, 'validation_driver', lambda: fake_driver)
    monkeypatch.setattr(probe, 'recipes', lambda: {str(Path(probe.__file__)): probe.reference(probe.__file__)['sha256']})
    monkeypatch.setattr(probe, 'HISTORY_ROOTS', (tmp_path/'history/difficulty', tmp_path/'history/research'))
    monkeypatch.setattr(probe, 'verify_local_base_image', lambda path: {
        'kind': 'explicit_offline_mock_image_inspection_boundary', 'actual_local_image_verified': False})
    return SimpleNamespace(root=tmp_path, mode=mode, source=source, view=view, actual=actual,
        output=tmp_path/'snapshot', calls=calls, raw_input=raw_input, raw_goal=raw_goal,
        instruction=instruction_ref, delta=delta)


def prepare(case):
    return probe.prepare(case.source, case.view, case.actual, case.output)


def test_real_seventeen_file_export_with_explicit_fake_actual_admission(case):
    frozen_ref = prepare(case); frozen = probe.read(frozen_ref)
    assert frozen['kind']==probe.KIND and frozen['schema_version']==2
    assert frozen['family']=='linear_capital_scaled' and frozen['source_provider']=='scaled360'
    assert frozen['phase']=='development'
    assert frozen['native_transport_profile']==probe.transport_profile()
    assert len(case.calls) == 1
    assert frozen['actual_validation_LO_calls_retained'] == (7 if case.mode == 'financial_modeling' else 11)
    assert frozen['new_LO_calls'] == frozen['new_model_calls'] == frozen['new_Harbor_jobs'] == 0
    assert frozen['qualified'] is False and frozen['task_count'] == 0
    assert frozen['normal_six_nodes_executed_or_inherited'] is False
    assert frozen['normal_ExportNode_executed'] is False
    assert frozen['local_controls'] == probe.CONTROL_REWARDS
    assert probe.checked(frozen['thread_cap_export_audit'])
    assert frozen['actual_Harbor_controls_status'] == 'pending'
    assert frozen['quality_gates_pending'] == probe.PENDING
    assert frozen['tool_time_policy_version'] == 3 and frozen['tool_time_policy'] == probe.POLICY_V3
    assert set(frozen['resource_task_inventory']) == set(probe.TASK_FILES)
    task = Path(frozen['tasks'][0]['task_directory'])
    assert probe.inspect_resource_export(task,audit_path=frozen['thread_cap_export_audit']) == frozen['tasks'][0]['harbor_export_binding']
    assert (task/'instruction.md').read_bytes() == Path(case.instruction['path']).read_bytes()
    dockerfile = (task/'environment/Dockerfile').read_text()
    assert dockerfile.splitlines()[1]=='ENV MAX_CONCURRENCY=2'
    assert (task/'tests/Dockerfile').read_text().splitlines()[1]=='ENV MAX_CONCURRENCY=2'
    assert 'COPY input.xlsx /app/input.xlsx' in dockerfile
    assert not any(word in dockerfile for word in ('reference.xlsx', 'view_plan', 'specification', 'bindings', 'vendor'))
    assert probe.validate_prepared(case.output) == frozen and len(case.calls) == 2


@pytest.mark.parametrize('change', ['failed_validator', 'source_link', 'view_link', 'mode', 'bool_version',
    'instruction', 'control_reward', 'bool_reward', 'source_changed', 'qualified', 'D_truncated', 'D_duplicate'])
def test_actual_proof_and_scope_fail_closed(case, change):
    actual = probe.read(case.actual)
    if change == 'failed_validator': actual['offline_validator_failure'] = True
    if change == 'source_link': actual['source_admission'] = case.view
    if change == 'view_link': actual['materialized_view'] = case.source
    if change == 'mode': actual['mode'] = 'another_mode'
    if change == 'bool_version': actual['version'] = True
    if change == 'instruction': actual['instruction'] = case.source
    if change == 'control_reward': actual['local_controls']['nop'] = 1
    if change == 'bool_reward': actual['local_controls']['oracle'] = True
    if change == 'source_changed': actual['source_original_unchanged'] = False
    if change == 'qualified': actual['qualified'] = True
    if change in ('D_truncated', 'D_duplicate'):
        delta = probe.read(case.delta)
        if change == 'D_truncated': delta['expected_changes'] = []
        else: delta['expected_changes'] *= 2
        actual['complete_D'] = dump(Path(case.delta['path']), delta)
    actual_ref = dump(Path(case.actual['path']), actual)
    with pytest.raises((ValueError, KeyError)):
        probe.prepare(case.source, case.view, actual_ref, case.output)
    assert not (case.output/'probe_manifest.json').exists()


def test_no_extra_instruction_transport_silently_added(case):
    instruction = Path(case.instruction['path']); instruction.write_text('Complete the model.\n')
    plan_path = Path(probe.read(case.view)['plan']['path']); plan = json.loads(plan_path.read_text())
    plan['instruction'] = instruction.read_text(); new_plan = dump(plan_path, plan)
    view = probe.read(case.view); view['plan'] = new_plan; view['instruction'] = probe.reference(instruction)
    new_view = dump(Path(case.view['path']), view)
    actual = probe.read(case.actual); actual['materialized_view'] = new_view; actual['instruction'] = view['instruction']
    actual_ref = dump(Path(case.actual['path']), actual)
    with pytest.raises(ValueError, match='exported public instruction'):
        probe.prepare(case.source, new_view, actual_ref, case.output)
    failure = probe.read(case.output/'preparation_failure.json')
    assert failure['partial_artifacts_preserved'] is True and failure['new_model_calls'] == 0


def test_logical_identity_ignores_zip_packaging_and_exact_numeric_formula_spelling(tmp_path):
    first = workbook(tmp_path/'first.xlsx', 3, formula='=1000000000000000000+1')
    other = workbook(tmp_path/'other.xlsx', 3, formula='=1E18+1')
    assert probe.workbook_identity(first['path'], formulas=True) == probe.workbook_identity(other['path'], formulas=True)
    third = workbook(tmp_path/'wrong.xlsx', 3, formula='=1000000000000000001+1')
    assert probe.workbook_identity(first['path'], formulas=True) != probe.workbook_identity(third['path'], formulas=True)


def history(case, identity, *, mode=None, source=True, name='old'):
    folder = case.root/'history/research'/name
    source_ref = dump(folder/'probe_manifest.json', {'material_task_version': identity}) if source else None
    selection = {'phase': 'development', 'tasks': [{'task_id': 'renamed-anything',
        'mode': mode or case.mode, 'revision_hash': 'different', 'task_checksum': 'c'*64}]}
    if source_ref is not None: selection['source_manifest'] = source_ref
    return dump(folder/'selection_manifest.json', selection)


def test_same_material_version_rejected_even_with_renamed_id_and_revision(case):
    frozen = probe.read(prepare(case)); history(case, frozen['material_task_version'])
    with pytest.raises(ValueError, match='do not resample or rename'):
        probe.selection_history(frozen['material_task_version'])
    with pytest.raises(ValueError, match='do not resample or rename'):
        probe.validate_prepared(case.output)


def test_same_source_other_mode_or_substantive_revision_not_blocked(case):
    frozen = probe.read(prepare(case)); identity = frozen['material_task_version']
    other = 'debugging' if case.mode == 'financial_modeling' else 'financial_modeling'
    history(case, identity, mode=other)
    assert len(probe.selection_history(identity)) == 1
    changed = deepcopy(identity); changed['instruction_sha256'] = '2'*64
    changed['sha256'] = probe.canonical({k: v for k, v in changed.items() if k != 'sha256'})
    history(case, changed)
    assert len(probe.selection_history(identity)) == 1


def test_legacy_matching_task_without_new_identity_still_rejected(case):
    frozen = probe.read(prepare(case)); task = frozen['tasks'][0]
    dump(case.root/'history/research/legacy/selection_manifest.json', {'phase': 'development',
        'tasks': [{'mode': case.mode, 'task_id': 'legacy-name', 'task_directory': task['task_directory'], 'task_checksum': 'c'*64}]})
    with pytest.raises(ValueError, match='historical selection'):
        probe.selection_history(frozen['material_task_version'])


@pytest.mark.parametrize('change', ['missing_source', 'tampered_source', 'malformed_source_identity', 'malformed_selection'])
def test_history_evidence_missing_or_tampered_is_not_ignored(case, change):
    frozen = probe.read(prepare(case)); record = history(case, frozen['material_task_version'])
    selected = probe.read(record)
    path = Path(selected['source_manifest']['path'])
    if change == 'missing_source': path.unlink()
    if change == 'tampered_source': path.write_text('{}')
    if change == 'malformed_source_identity':
        malformed = deepcopy(frozen['material_task_version']); malformed['sha256'] = '0'*64
        selected['source_manifest'] = dump(path, {'material_task_version': malformed})
        dump(Path(record['path']), selected)
    if change == 'malformed_selection': dump(Path(record['path']), {'tasks': 'invalid'})
    with pytest.raises(ValueError): probe.selection_history(frozen['material_task_version'])


@pytest.mark.parametrize('change', ['export_file', 'extra_file', 'recipe', 'mode', 'revision_bool', 'target_identity', 'control_bool'])
def test_snapshot_revalidation_rejects_drift(case, change):
    ref = prepare(case); frozen = probe.read(ref)
    export = Path(frozen['tasks'][0]['task_directory'])
    if change == 'export_file': (export/'instruction.md').write_text('Changed')
    if change == 'extra_file': (export/'unbound.txt').write_text('Extra')
    if change == 'recipe': frozen['recipe_sha256'] = {}
    if change == 'mode': frozen['tasks'][0]['mode'] = 'different'
    if change == 'revision_bool': frozen['tasks'][0]['revision'] = False
    if change == 'target_identity': frozen['material_task_version']['sha256'] = '0'*64
    if change == 'control_bool': frozen['tasks'][0]['local_controls']['oracle'] = True
    if change not in ('export_file', 'extra_file'): dump(Path(ref['path']), frozen)
    with pytest.raises(ValueError): probe.validate_prepared(case.output)


def test_no_overwrite_and_symlink_output(case):
    prepare(case)
    with pytest.raises(ValueError, match='fresh real'): prepare(case)
    alias = case.root/'alias'; alias.symlink_to(case.root, target_is_directory=True)
    with pytest.raises(ValueError, match='fresh real'):
        probe.prepare(case.source, case.view, case.actual, alias/'fresh')


def test_history_changes_during_export_fail_closed(case, monkeypatch):
    original = probe.export_resource_harbor
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        dump(case.root/'history/research/concurrent/selection_manifest.json', {'tasks': []})
        return result
    monkeypatch.setattr(probe, 'export_resource_harbor', changed)
    with pytest.raises(ValueError, match='history changed'): prepare(case)
    assert (case.output/'preparation_failure.json').is_file()


def test_cli_no_confirmation_resume_or_model_override_routes():
    for arguments in (['confirmation'], ['resume'], ['run-development', '--model', 'other'],
                      ['run-development', '--phase', 'confirmation']):
        with pytest.raises(SystemExit): probe.main(arguments)


def test_runtime_profile_cannot_drift_to_old_eight_gib(case):
    source = probe.read(case.source)
    source['runtime_profile'] = probe.reference(ROOT/'config/runtime_profiles/entity_group_large_v1.yaml')
    new_source = dump(Path(case.source['path']), source)
    actual = probe.read(case.actual); actual['source_admission'] = new_source
    new_actual = dump(Path(case.actual['path']), actual)
    with pytest.raises(ValueError, match='2CPU and 32GiB'):
        probe.prepare(new_source, case.view, new_actual, case.output)


def test_source_changes_during_export_are_retained_and_held(case, monkeypatch):
    original = probe.export_resource_harbor
    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        Path(case.source['path']).write_text('{}')
        return result
    monkeypatch.setattr(probe, 'export_resource_harbor', changed)
    with pytest.raises(ValueError, match='frozen artifact changed'): prepare(case)
    assert (case.output/'preparation_failure.json').is_file()


@pytest.fixture
def model_boundary(case, monkeypatch):
    """A fake model/observer boundary: this never starts a model or container."""
    import sheets_factory.evaluation.native_transport_frontier as frontier
    import sheets_factory.evaluation.resource_observer as observations
    calls = []
    class Observer:
        receipt = None; finalization_error = None
        def __init__(self, directory): self.directory = directory
        def __enter__(self): return self
        def __exit__(self, *error): pass
    def run(source, directory, **kwargs):
        # Exercise the exact historical shape consumed by frontier.freeze_selection:
        # nonmodel preparations must not reach previous['tasks']/task_checksum.
        for location in kwargs['prior_selections']:
            previous=probe.read(location)
            {task['task_checksum'] for task in previous['tasks']}
            assert previous.get('kind')!='composite_preparation_selection'
        calls.append({'source': source, 'directory': directory, **kwargs})
        directory.mkdir()
        dump(directory/'selection_manifest.json', {'tasks': [], 'explicit_fake_model_boundary': True})
        dump(directory/'evaluation_manifest.json', {'status': 'completed', 'explicit_fake_model_boundary': True})
        return {'status': 'completed', 'score': {'explicit_fake_model_boundary': True}}
    monkeypatch.setattr(frontier, 'run_evaluation', run)
    monkeypatch.setattr(observations, 'ResourceObserver', Observer)
    return SimpleNamespace(calls=calls, frontier=frontier)


def test_single_fixed_development_dispatch_and_once_only_receipts(case, model_boundary):
    prepare(case)
    terminal_ref = probe.run_development(case.output, case.root/'evaluation')
    terminal = probe.read(terminal_ref)
    assert terminal['qualified'] is False and terminal['effective_infrastructure_retries'] == 0
    assert (case.output/'development_started.json').is_file()
    assert len(model_boundary.calls) == 1
    call = model_boundary.calls[0]
    assert call['phase'] == 'development' and call['concurrency'] == 1
    assert call['backend_config']['model'] == 'gpt-6.1-sol'
    assert call['backend_config']['reasoning_effort'] == 'xhigh'
    assert set(call['backend_config']['roles']) == {'trace_agent'}
    assert not any(k in call for k in ('task_ids', 'execute', 'max_infrastructure_retries'))
    with pytest.raises(ValueError, match='reserved first attempt'):
        probe.run_development(case.output, case.root/'different_evaluation')
    assert len(model_boundary.calls) == 1


def test_failed_dispatch_preserves_receipt_and_does_not_retry(case, model_boundary, monkeypatch):
    prepare(case)
    def failed(*args, **kwargs):
        model_boundary.calls.append('explicit fake launch failure')
        raise RuntimeError('Explicit offline failure, no model called')
    monkeypatch.setattr(model_boundary.frontier, 'run_evaluation', failed)
    with pytest.raises(RuntimeError): probe.run_development(case.output, case.root/'evaluation')
    failure = probe.read(case.output/'development_failure.json')
    assert failure['failure_is_not_model_zero'] is True and failure['retry_authorized'] is False
    with pytest.raises(ValueError, match='reserved first attempt'):
        probe.run_development(case.output, case.root/'new_evaluation')
    assert len(model_boundary.calls) == 1


def test_concurrent_launcher_lock_precedes_model_boundary(case, model_boundary):
    prepare(case)
    with (case.output/'.development.lock').open('a') as locked:
        fcntl.flock(locked.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='active launcher'):
            probe.run_development(case.output, case.root/'evaluation')
    assert model_boundary.calls == []


def preparation_history(case):
    folder=case.root/'history/research/raw_preparation';rows=[]
    for index in range(2):
        book=workbook(folder/(str(index)+'.xlsx'),index+1)
        source=dump(folder/(str(index)+'.source.json'),{'explicit_offline_source':True,'workbook':book})
        rows.append({'index':index,'profile_id':'old-'+str(index),'source_id':book['sha256'],
            'task_id':('fm-' if case.mode=='financial_modeling' else 'dbg-')+book['sha256'][:12],
            'source_manifest':{k:v for k,v in source.items() if k!='bytes'},
            'workbook':{k:v for k,v in book.items() if k!='bytes'},'verification':{'workbook':book}})
    batch=dump(folder/'source_batch.json',{'explicit_offline_batch':True})
    value={'kind':'composite_preparation_selection','schema_version':1,'frozen_at':'2026-10-30T15:23:06Z',
        'source_batch_manifest':{k:v for k,v in batch.items() if k!='bytes'},
        'source_selected_order':[r['profile_id'] for r in rows],'selected_task_ids':[r['task_id'] for r in rows],
        'sources':rows,'mode':case.mode,'model_results_consulted':False,'qualified':False,'task_count':0,'llm_calls':0,
        'construction':{'root_impact_validation':'strict','composite_activity':True},'selection_policy':'All fixed sources'}
    return dump(folder/'selection_manifest.json',value)


def test_known_nonmodel_preparation_preserves_every_source_and_sha_without_inventing_attempts(case):
    record=preparation_history(case);selection=probe.read(record)
    model,tasks=probe._history_tasks(selection)
    assert model is False and len(tasks)==len(selection['sources'])==2
    assert [t['task_id'] for t in tasks]==selection['selected_task_ids']
    assert all('task_checksum' not in t and 'task_directory' not in t for t in tasks)
    frozen=probe.read(prepare(case))
    assert frozen['selection_history_inventory']==frozen['nonmodel_preparation_inventory']==[record]
    assert frozen['prior_model_selection_inventory']==[]
    assert frozen['source_artifacts_sha256'][record['path']]==record['sha256']
    assert probe.validate_prepared(case.output)==frozen


def test_downstream_frontier_receives_only_original_complete_model_selections(case,model_boundary):
    nonmodel=preparation_history(case)
    identity={'sha256':'x','mode':case.mode,'instruction_sha256':'f'*64}
    identity['sha256']=probe.canonical({k:v for k,v in identity.items() if k!='sha256'})
    model=history(case,identity)
    frozen=probe.read(prepare(case))
    assert set(r['path'] for r in frozen['selection_history_inventory'])=={model['path'],nonmodel['path']}
    probe.run_development(case.output,case.root/'evaluation')
    assert model_boundary.calls[0]['prior_selections']==[model['path']]


@pytest.mark.parametrize('fault',['unknown_kind','bool_version','model_consulted','llm_call','source_order','omitted_source','duplicate_index','wrong_source_sha','extra_tasks','changed_reference'])
def test_unknown_or_corrupt_nonmodel_preparation_is_never_silently_ignored(case,fault):
    record=preparation_history(case);value=probe.read(record)
    if fault=='unknown_kind':value['kind']='unknown_preparation'
    elif fault=='bool_version':value['schema_version']=True
    elif fault=='model_consulted':value['model_results_consulted']=True
    elif fault=='llm_call':value['llm_calls']=1
    elif fault=='source_order':value['source_selected_order'].reverse()
    elif fault=='omitted_source':value['sources'].pop()
    elif fault=='duplicate_index':value['sources'][1]['index']=0
    elif fault=='wrong_source_sha':value['sources'][0]['source_id']='f'*64
    elif fault=='extra_tasks':value['tasks']=[]
    else:value['sources'][0]['workbook']['sha256']='0'*64
    dump(Path(record['path']),value)
    with pytest.raises(ValueError):prepare(case)


@pytest.mark.parametrize('checksum',[None,True,'not-a-checksum'])
def test_actual_model_selection_without_complete_checksum_fails_before_dispatch(case,checksum):
    record=history(case,{'mode':case.mode,'sha256':'x'})
    value=probe.read(record);value.pop('source_manifest')
    value['tasks'][0]['task_checksum']=checksum;dump(Path(record['path']),value)
    with pytest.raises(ValueError,match='model task checksum'):prepare(case)


def test_cold_history_partition_cannot_lose_or_reclassify_preparation_evidence(case):
    preparation_history(case);record=prepare(case);frozen=probe.read(record)
    frozen['nonmodel_preparation_inventory']=[];dump(Path(record['path']),frozen)
    with pytest.raises(ValueError,match='model/nonmodel history'):probe.validate_prepared(case.output)


@pytest.mark.parametrize('fault', ['transport_missing', 'transport_retries', 'phase', 'provider', 'schema_old',
    'schema_bool', 'history_roots'])
def test_new_prospective_contract_is_immutable(case, fault):
    record = prepare(case); frozen = probe.read(record)
    if fault == 'transport_missing': frozen.pop('native_transport_profile')
    elif fault == 'transport_retries': frozen['native_transport_profile']['provider_overrides']['stream_max_retries'] = 9
    elif fault == 'phase': frozen['phase'] = 'confirmation'
    elif fault == 'provider': frozen['source_provider'] = 'producer16'
    elif fault == 'schema_old': frozen['schema_version'] = 1
    elif fault == 'schema_bool': frozen['schema_version'] = True
    else: frozen['history_roots'] = []
    dump(Path(record['path']), frozen)
    with pytest.raises(ValueError): probe.validate_prepared(case.output)


@pytest.mark.parametrize('fault', ['old_source', 'old_view', 'source_version', 'provider'])
def test_old_namespace_cannot_enter_new_development(case, fault):
    source, view, actual = map(probe.read, (case.source, case.view, case.actual))
    if fault == 'old_source': source['kind'] = 'independently_verified_linear_capital_native_source'
    elif fault == 'old_view': view['kind'] = 'materialized_unverified_linear_capital_task_view'
    elif fault == 'source_version': source['version'] = True
    else: actual['source_provider'] = 'standard'
    source_ref = dump(Path(case.source['path']), source)
    view_ref = dump(Path(case.view['path']), view)
    actual.update(source_admission=source_ref, materialized_view=view_ref)
    actual_ref = dump(Path(case.actual['path']), actual)
    with pytest.raises(ValueError, match='fixed N360 source'):
        probe.prepare(source_ref, view_ref, actual_ref, case.output)


@pytest.mark.parametrize('addition', ['same_mode_distinct_material', 'other_mode'])
def test_unrelated_history_append_is_captured_and_passed_without_changing_snapshot(case, model_boundary, addition):
    prior_identity = {'mode': case.mode, 'instruction_sha256': 'a'*64}
    prior_identity['sha256'] = probe.canonical(prior_identity)
    prior = history(case, prior_identity, name='prior')
    nonmodel = preparation_history(case)
    record = prepare(case); frozen = probe.read(record)
    different = deepcopy(frozen['material_task_version'])
    if addition == 'same_mode_distinct_material': different['instruction_sha256'] = 'b'*64
    else: different['mode'] = 'debugging' if case.mode == 'financial_modeling' else 'financial_modeling'
    different['sha256'] = probe.canonical({key: value for key, value in different.items() if key != 'sha256'})
    appended = history(case, different, mode=different['mode'], name='appended')
    assert probe.validate_prepared(case.output) == frozen
    probe.run_development(case.output, case.root/'evaluation')
    started = probe.read(case.output/'development_started.json')
    reservation = probe.read(started['material_reservation'])
    current = probe.selection_history(frozen['material_task_version'])
    expected_models = [row for row in current if row != nonmodel]
    assert set(row['path'] for row in expected_models) == {prior['path'], appended['path']}
    assert model_boundary.calls[0]['prior_selections'] == [row['path'] for row in expected_models]
    for receipt in (started, reservation, reservation['started_value']):
        assert receipt['selection_history_inventory'] == current
        assert receipt['prior_model_selection_inventory'] == expected_models
        assert receipt['nonmodel_preparation_inventory'] == [nonmodel]
    assert probe.checked(record) == record and probe.read(record) == frozen
    assert appended not in frozen['selection_history_inventory']


@pytest.mark.parametrize('fault', ['same_material', 'corrupt_append', 'frozen_changed', 'frozen_missing'])
def test_history_append_does_not_allow_same_material_or_corrupt_old_or_new_records(case, model_boundary, fault):
    previous = {'mode': case.mode, 'instruction_sha256': 'a'*64}
    previous['sha256'] = probe.canonical(previous)
    old_record = history(case, previous, name='prior')
    frozen = probe.read(prepare(case))
    if fault == 'same_material': history(case, frozen['material_task_version'], name='appended')
    elif fault == 'corrupt_append':
        dump(case.root/'history/research/appended/selection_manifest.json', {'tasks': 'invalid'})
    elif fault == 'frozen_changed':
        changed = probe.read(old_record); changed['phase'] = 'changed'
        dump(Path(old_record['path']), changed)
    else: Path(old_record['path']).unlink()
    with pytest.raises(ValueError): probe.run_development(case.output, case.root/'evaluation')
    assert model_boundary.calls == [] and not (case.output/'development_started.json').exists()


def test_two_prepared_copies_share_one_durable_material_reservation(case, model_boundary):
    prepare(case)
    second = case.root/'second_snapshot'
    probe.prepare(case.source, case.view, case.actual, second)
    probe.run_development(case.output, case.root/'evaluation')
    started = probe.read(case.output/'development_started.json')
    reservation = probe.read(started['material_reservation'])
    assert reservation['material_task_version'] == probe.read(case.output/'probe_manifest.json')['material_task_version']
    assert reservation['effective_infrastructure_retries'] == 0 and reservation['qualified'] is False
    assert started['version'] == 2 and started['native_transport_profile'] == probe.transport_profile()
    with pytest.raises(ValueError, match='material already has a reserved first attempt'):
        probe.run_development(second, case.root/'second_evaluation')
    assert len(model_boundary.calls) == 1
    assert not (second/'development_started.json').exists()


def test_concurrent_distinct_snapshots_cannot_double_launch(case, model_boundary):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    prepare(case); second = case.root/'second_snapshot'
    probe.prepare(case.source, case.view, case.actual, second)
    barrier = threading.Barrier(2)
    def run(snapshot, destination):
        barrier.wait()
        try: return probe.run_development(snapshot, destination)
        except ValueError as error: return error
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run, snapshot, case.root/('evaluation'+str(index)))
            for index, snapshot in enumerate((case.output, second))]
        results = [future.result(timeout=30) for future in futures]
    assert len(model_boundary.calls) == 1
    errors = [value for value in results if isinstance(value, ValueError)]
    assert len(errors) == 1 and ('reservation is already in progress' in str(errors[0])
        or 'material already has a reserved first attempt' in str(errors[0]))


def test_failed_first_launch_spends_material_even_in_second_snapshot(case, model_boundary, monkeypatch):
    prepare(case); second = case.root/'second_snapshot'
    probe.prepare(case.source, case.view, case.actual, second)
    def failed(*args, **kwargs):
        model_boundary.calls.append('mock failure'); raise RuntimeError('Explicit mock failure')
    monkeypatch.setattr(model_boundary.frontier, 'run_evaluation', failed)
    with pytest.raises(RuntimeError): probe.run_development(case.output, case.root/'evaluation')
    with pytest.raises(ValueError, match='material already has a reserved first attempt'):
        probe.run_development(second, case.root/'second_evaluation')
    assert len(model_boundary.calls) == 1
    assert probe.read(case.output/'development_failure.json')['retry_authorized'] is False


def test_real_recipe_binds_new_and_frozen_driver_and_transport_files():
    recipe = probe.recipes()
    assert recipe[str(probe.UPSTREAM.resolve())] == probe.UPSTREAM_SHA256
    assert str(ROOT/'scripts/validate_linear_capital_scaled_task_view.py') in recipe
    assert str(ROOT/'src/sheets_factory/evaluation/native_transport_frontier.py') in recipe
    assert str(probe.PROFILE_PATH) in recipe
    assert probe.transport_profile()['provider_overrides'] == {'stream_max_retries': 8}


def test_frozen_upstream_hash_is_rechecked_after_import(tmp_path, monkeypatch):
    changed = tmp_path/'changed_original.py'; changed.write_bytes(probe.UPSTREAM.read_bytes()+b'\n')
    monkeypatch.setattr(probe, 'UPSTREAM', changed)
    with pytest.raises(ValueError, match='frozen complete first-development'):
        probe.adapted_ast()

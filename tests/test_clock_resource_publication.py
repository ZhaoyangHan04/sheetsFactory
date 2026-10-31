"""Offline V3 composition; financial/resource services are explicit fake fixtures.

These tests execute no model, LO, Harbor, Docker or real publication. Real file
inventories, clock parsing, artifact binding and isolated publisher gates remain
active; only expensive source/task/resource witnesses are replaced in fixtures.
"""
import ast
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sheets_factory.evaluation import clock_resource_publication as v3
from sheets_factory.evaluation import resource_publication as legacy
from sheets_factory.evaluation import clock_resource_frontier as runner
from sheets_factory.evaluation.tool_time_bounds import POLICY_V2
from test_resource_publication import offline as legacy_offline

ROOT = Path(__file__).parents[1]


def read(path): return json.loads(Path(path).read_text())
def write(path, value): Path(path).write_text(json.dumps(value, indent=2)+'\n')
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def complete_clock_fixture(result_path):
    actual = read(result_path)
    base = int(datetime.fromisoformat(actual['agent_execution']['started_at'].replace('Z', '+00:00')).timestamp()*1000)
    stamp = lambda offset: datetime.fromtimestamp((base+offset)/1000, timezone.utc).isoformat(timespec='milliseconds')
    native = [
        {'timestamp': stamp(1), 'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'turn', 'root_turn_id': 'turn'}},
        {'timestamp': stamp(10), 'type': 'response_item', 'payload': {'type': 'custom_tool_call', 'name': 'exec', 'call_id': 'wrapper',
            'input': 'text(await tools.exec_command({cmd:"echo fixture"}));'}},
        {'timestamp': stamp(600), 'type': 'event_msg', 'payload': {'type': 'item_completed', 'thread_id': 'thread', 'turn_id': 'turn',
            'started_at_ms': base+20, 'completed_at_ms': base+520, 'item': {'type': 'CommandExecution', 'id': 'native',
                'process_id': '42', 'command': ['/bin/bash', '-lc', 'echo fixture'], 'status': 'completed',
                'exit_code': 0, 'duration': {'secs': 0, 'nanos': 520_000_000}}}},
        {'timestamp': stamp(800), 'type': 'response_item', 'payload': {'type': 'custom_tool_call_output', 'call_id': 'wrapper',
            'output': [{'type': 'input_text', 'text': 'Script completed\n'}]}},
        {'timestamp': stamp(900), 'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'turn', 'root_turn_id': 'turn'}},
    ]
    tool = {'id': 'stream', 'type': 'command_execution', 'command': "/bin/bash -lc 'echo fixture'"}
    stream = [{'type': 'thread.started', 'thread_id': 'thread'}, {'type': 'turn.started'},
              {'type': 'item.started', 'item': deepcopy(tool)},
              {'type': 'item.completed', 'item': {**tool, 'status': 'completed', 'exit_code': 0}},
              {'type': 'turn.completed', 'usage': {}}]
    (result_path.parent/'agent/sessions/fixture.jsonl').write_text('\n'.join(json.dumps(r) for r in native)+'\n')
    (result_path.parent/'agent/codex.txt').write_text('\n'.join(json.dumps(r) for r in stream)+'\n')


@pytest.fixture
def offline(legacy_offline, monkeypatch):
    old = legacy_offline
    monkeypatch.setattr(v3, 'MIN_PER_MODE', 1)
    publish = v3.publisher_namespace()
    monkeypatch.setattr(publish, 'MIN_PER_MODE', 1)
    cohort = read(old.source)
    cohort.update(kind=v3.KIND, tool_time_policy_version=3, publication_recipe=v3.publication_recipe(ROOT))
    write(old.source, cohort)
    backend = v3.ClockResourcePublicationBackend(old.source, project_root=ROOT)
    backend.root = old.root
    monkeypatch.setattr(backend, '_run', old.backend._run)
    def fake_family_gate(run, task, tracked):
        row = backend._mapping(task['id'])
        v3.require(row['source_run'] == str(run) and task['revision_hash'] == row['revision_hash'], 'fixture task changed')
        state = old.backend._run(run, row['family'], tracked)
        backend.tasks[task['id']] = {'source_run': str(run), 'family': row['family'], 'task': deepcopy(task),
            'runtime_profile': v3.reference(ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'),
            'runtime': state['profile'], 'actual_calculation_resource_bindings': 'MOCK only; not actual source admission'}
    monkeypatch.setattr(backend, 'validate_task', fake_family_gate)
    selection = read(old.selection)
    selection.update(tool_time_policy_version=3, tool_time_policy=deepcopy(runner.POLICY_V3),
                     source_manifest={'path': str(old.source), 'sha256': sha(old.source)})
    for entry in selection['tasks']:
        entry['tool_time_policy'] = deepcopy(runner.POLICY_V3)
    write(old.selection, selection)
    evaluation = read(old.evaluation)
    evaluation.update(tool_time_policy_version=3, tool_time_policy=deepcopy(runner.POLICY_V3),
                      selection_manifest={'path': str(old.selection), 'sha256': sha(old.selection)})
    for entry in evaluation['attempts']:
        result = Path(entry['result_file']); actual = read(result)
        actual['config']['agent']['import_path'] = backend.agent_import_path
        write(result, actual)
        complete_clock_fixture(result)
        entry.update(tool_time_policy=deepcopy(runner.POLICY_V3), result_sha256=sha(result),
                     status='scored', reward=0, failure_kind=None)
        runner.apply_tool_time_policy(entry, selection)
        assert entry['status'] == 'scored' and entry['tool_time']['state'] == 'verified_conservative_bound'
    write(old.evaluation, evaluation)
    return SimpleNamespace(**vars(old), new_backend=backend, publish=publish)


def invoke(fixture, **kwargs):
    return fixture.publish.publish_dataset(run_dir=fixture.rows[0]['source_run'],
        selection_manifest=fixture.selection, evaluation_manifest=fixture.evaluation,
        project_root=fixture.root, backend=fixture.new_backend, **kwargs)


def test_full_isolated_composition_uses_real_clock_and_inventory_with_fake_financial_service(offline):
    result = invoke(offline, dry_run=True)
    assert result['status'] == 'validated_dry_run' and result['task_count'] == 2
    confirmation = result['manifest']['confirmation']
    assert confirmation['tool_time_policy'] == runner.POLICY_V3
    assert confirmation['overall_pass_at_1'] == 0
    for row in confirmation['tasks']:
        timing = row['tool_time']
        assert timing['state'] == 'verified_conservative_bound' and timing['passed'] is True
        assert timing['policy_version'] == 3 and timing['exact_state'] == 'unknown'
        assert timing['cumulative_tool_seconds'] is None and timing['cumulative_tool_nanoseconds'] is None
        assert timing['cumulative_exact_ns'] is None and timing['cumulative_upper_bound_ns'] == 1_314_000_000
        assert timing['evidence_sha256']['clock_bound_is_exact'] is False
    assert not (offline.root/'SpreadsheetEval').exists()
    assert all(len(row['payload_files']) == 17 for row in result['manifest']['tasks'])


def test_fixture_only_atomic_staging_uses_same_bound_bytes_and_never_overwrites(offline):
    # This writes only the explicit mocked checkout under pytest's /data temp.
    # It is not a real dataset, actual financial source or qualified cohort.
    result=invoke(offline,dry_run=False)
    assert result['status']=='published'
    for row in offline.rows:
        target=offline.root/'SpreadsheetEval'/row['task_id']
        assert v3.inspect_resource_export(target)==row['harbor_export_binding']
    with pytest.raises(Exception,match='exists|overwrite'):
        invoke(offline,dry_run=False)


def test_new_file_during_fixture_staging_aborts_the_atomic_release(offline,monkeypatch):
    original=offline.publish.release._copy_payload
    def copy_then_change(source,target,**kwargs):
        result=original(source,target,**kwargs)
        (Path(target)/'environment/unmanifested.py').write_text('extra')
        return result
    monkeypatch.setattr(offline.publish.release,'_copy_payload',copy_then_change)
    with pytest.raises(Exception,match='missing|Unexpected|changed'):
        invoke(offline,dry_run=False)
    assert not (offline.root/'SpreadsheetEval').exists()


def test_old_publisher_keeps_rejecting_the_new_policy(offline):
    with pytest.raises(Exception, match='supported strict cumulative'):
        legacy.support(ROOT, 'publish_dataset.py')._frozen_tool_time_policy(read(offline.selection))


def test_policy_cannot_default_or_reinterpret_old_versions():
    publisher = v3.publisher_namespace()
    for version in [None, 1, 2, True, '3']:
        frozen = {'tool_time_policy': deepcopy(runner.POLICY_V3)}
        if version is not None: frozen['tool_time_policy_version'] = version
        with pytest.raises(publisher.PublishError, match='explicit prospective'):
            publisher._frozen_tool_time_policy(frozen)
    with pytest.raises(publisher.PublishError):
        publisher._frozen_tool_time_policy({'tool_time_policy_version': 3, 'tool_time_policy': deepcopy(POLICY_V2)})


def test_backend_adaptation_retains_all_nonmetadata_methods_verbatim():
    before = v3._frozen_ast(ROOT/'src/sheets_factory/evaluation/resource_publication.py', v3.RESOURCE_PUBLICATION_SHA256)
    after = v3.backend_ast()
    old = next(n for n in before.body if isinstance(n, ast.ClassDef) and n.name == 'ResourcePublicationBackend')
    new = next(n for n in after.body if isinstance(n, ast.ClassDef) and n.name == old.name)
    changed = [x.name for x,y in zip(old.body,new.body) if isinstance(x,ast.FunctionDef) and ast.dump(x)!=ast.dump(y)]
    assert changed == ['__init__', 'validate_cohort_shape']
    for name in ['validate_task','validate_control_observations','load_selection','validate_confirmation_source',
                 'prepare_runtime','final_recheck','recheck_payloads','current_tasks']:
        a = next(n for n in old.body if getattr(n,'name',None)==name)
        b = next(n for n in new.body if getattr(n,'name',None)==name)
        assert ast.dump(a) == ast.dump(b)


def test_publisher_ast_only_changes_policy_tracking_and_timing_projection():
    before = v3._frozen_ast(ROOT/'scripts/publish_dataset.py', v3.DATASET_PUBLISHER_SHA256)
    after = v3.publisher_ast()
    originals = {n.name:n for n in before.body if isinstance(n,ast.FunctionDef)}
    adapted = {n.name:n for n in after.body if isinstance(n,ast.FunctionDef)}
    changed = {name for name in originals if name in adapted and ast.dump(originals[name])!=ast.dump(adapted[name])}
    assert changed == {'_frozen_tool_time_policy','_track_tool_time_evidence','_validate_confirmation'}
    assert ast.dump(originals['_track_tool_time_evidence'].args) == ast.dump(adapted['_base_track_tool_time_evidence'].args)
    for name in ['publish_dataset','_validate_confirmation_history','_load_selection',
                 '_rename_new','_execution_budget','_execution_budget_source','_task_contract']:
        assert ast.dump(originals[name]) == ast.dump(adapted[name])


@pytest.mark.parametrize('field,value', [
    ('tool_time_policy_version',2), ('kind',legacy.KIND), ('execution_budget',{}),
])
def test_v3_cohort_metadata_is_not_migrated(offline,field,value):
    cohort=read(offline.source);cohort[field]=value
    with pytest.raises(v3.ResourcePublicationError):
        v3.ResourcePublicationBackend.validate_cohort_shape(cohort)


def test_heterogeneous_family_stays_unadmitted(offline):
    cohort=read(offline.source);cohort['tasks'][0]['family']='heterogeneous_financial_view'
    with pytest.raises(v3.ResourcePublicationError,match='mapping'):
        v3.ResourcePublicationBackend.validate_cohort_shape(cohort)
    assert v3.self_families() == legacy.self_families() == {'entity':'debugging','scaled_capital':'financial_modeling'}


def test_production_quota_remains_ten_per_mode(offline,monkeypatch):
    cohort=read(offline.source)
    monkeypatch.setattr(v3,'MIN_PER_MODE',10)
    with pytest.raises(v3.ResourcePublicationError,match='at least ten'):
        v3.ResourcePublicationBackend.validate_cohort_shape(cohort)


def test_complete_ten_plus_ten_shape_is_preserved_in_declared_order(offline,monkeypatch):
    cohort=read(offline.source);templates=deepcopy(cohort['tasks']);rows=[]
    for template in templates:
        for index in range(10):
            row=deepcopy(template);row['task_id']=template['task_id']+'-'+str(index)
            row['revision_hash']=hashlib.sha256(row['task_id'].encode()).hexdigest()
            rows.append(row)
    cohort.update(tasks=rows,selected_task_ids=[r['task_id'] for r in rows])
    monkeypatch.setattr(v3,'MIN_PER_MODE',10)
    v3.ResourcePublicationBackend.validate_cohort_shape(cohort)
    assert cohort['selected_task_ids']==[row['task_id'] for row in rows]
    cohort['tasks'].pop();cohort['selected_task_ids'].pop()
    with pytest.raises(v3.ResourcePublicationError,match='at least ten'):
        v3.ResourcePublicationBackend.validate_cohort_shape(cohort)


def test_old_exact_branch_uses_the_original_exact_fields(offline):
    evaluation=read(offline.evaluation);selected=read(offline.selection)
    for entry in evaluation['attempts']:
        result=Path(entry['result_file']);session=result.parent/'agent/sessions/fixture.jsonl'
        records=[json.loads(line) for line in session.read_text().splitlines()]
        records[2]['payload']['item']['duration']['nanos']=500_000_000
        session.write_text('\n'.join(json.dumps(r) for r in records)+'\n')
        entry.update(status='scored',reward=0,failure_kind=None)
        runner.apply_tool_time_policy(entry,selected)
        assert entry['tool_time']['state']=='verified'
    write(offline.evaluation,evaluation)
    result=invoke(offline,dry_run=True)
    for row in result['manifest']['confirmation']['tasks']:
        timing=row['tool_time']
        assert timing['measurement_branch']=='unchanged_exact_or_stop_bound'
        assert timing['state']=='verified' and timing['exact_timing_state']=='verified'
        assert timing['cumulative_tool_seconds'] is not None and timing['cumulative_tool_nanoseconds'] is not None


def test_unchanged_stop_bound_projection_remains_a_bound():
    base={'state':'bounded','passed':True,'method':'old','budget_seconds':1800,'strict_less_than':True,
        'cumulative_tool_seconds':None,'model_response_time_included':False,'parallel_executions':'sum',
        'exact_timing_state':'unknown','lower_bound_seconds':1.0,'upper_bound_seconds':2.0,
        'lower_bound_nanoseconds':10**9,'upper_bound_nanoseconds':2*10**9,
        'upper_bound_may_include_idle_cleanup_time':True}
    timing={**base,'policy_version':3,'measurement_branch':'unchanged_exact_or_stop_bound',
        'base_policy_v2_receipt':base}
    projected=v3._project_v3(timing,{'stop_receipt_sha256':'a'*64},v3.require)
    assert projected['cumulative_tool_seconds'] is None and projected['cumulative_tool_nanoseconds'] is None
    assert projected['upper_bound_nanoseconds']==2*10**9 and projected['exact_timing_state']=='unknown'


def test_changed_complete_recipe_cannot_relabel_an_old_cohort(offline):
    cohort=read(offline.source)
    cohort['publication_recipe']=legacy.publication_recipe(ROOT)
    with pytest.raises(v3.ResourcePublicationError,match='complete publication'):
        v3.ResourcePublicationBackend.validate_cohort_shape(cohort)


@pytest.mark.parametrize('change', ['duration','command','status','exit','missing_tail','extra_root','native_id'])
def test_native_timing_changes_never_survive_fresh_recomputation(offline,change):
    evaluation=read(offline.evaluation);result=Path(evaluation['attempts'][0]['result_file'])
    session=result.parent/'agent/sessions/fixture.jsonl'
    native=[json.loads(x) for x in session.read_text().splitlines()]
    item=native[2]['payload']['item']
    if change=='duration':item['duration']['nanos']+=1
    elif change=='command':item['command'][-1]='echo unrelated'
    elif change=='status':item['status']='failed'
    elif change=='exit':item['exit_code']=1
    elif change=='missing_tail':native.pop()
    elif change=='native_id':item['id']='changed'
    else:native.insert(3,deepcopy(native[2]))
    session.write_text('\n'.join(json.dumps(r) for r in native)+'\n')
    with pytest.raises(Exception,match='timing|evidence|native'):
        invoke(offline,dry_run=True)


def test_bound_code_reference_must_equal_the_frozen_approved_recipe(offline):
    evaluation=read(offline.evaluation);entry=evaluation['attempts'][0];result=Path(entry['result_file'])
    timing=deepcopy(entry['tool_time'])
    code=timing['complete_clock_receipt']['implementation']
    arbitrary=result.parent/'arbitrary.py';arbitrary.write_text('not an approved parser')
    code.update(v3.reference(arbitrary))
    with pytest.raises(Exception,match='outside the frozen'):
        offline.publish._track_tool_time_evidence(timing,result,{},backend=offline.new_backend)


@pytest.mark.parametrize('fault',['upper_at_budget','upper_boolean','exact_seconds','missing_artifact','duplicate_artifact'])
def test_bound_tracker_does_not_accept_approximate_or_incomplete_claims(offline,fault):
    entry=read(offline.evaluation)['attempts'][0];result=Path(entry['result_file'])
    timing=deepcopy(entry['tool_time']);clock=timing['complete_clock_receipt']
    if fault=='upper_at_budget':clock['cumulative_upper_bound_ns']=1800*10**9
    elif fault=='upper_boolean':clock['cumulative_upper_bound_ns']=True
    elif fault=='exact_seconds':clock['cumulative_tool_seconds']=1.0
    elif fault=='missing_artifact':clock['artifacts'].pop()
    else:clock['artifacts'].append(deepcopy(clock['artifacts'][0]))
    with pytest.raises(Exception,match='bound|artifact'):
        offline.publish._track_tool_time_evidence(timing,result,{},backend=offline.new_backend)


def test_original_stop_inputs_inspected_by_base_accountant_are_also_bound(offline):
    entry=read(offline.evaluation)['attempts'][0];result=Path(entry['result_file'])
    folder=result.parent/'private/tool_time';folder.mkdir(parents=True)
    config=result.parent/'config.json';write(config,{'fixture_only':True})
    identity=folder/'container_identity.json';write(identity,{'trial_config':v3.reference(config)})
    stop=folder/'stop_receipt.json';write(stop,{'identity_file':v3.reference(identity),'result_file':v3.reference(result)})
    tracked={}
    receipt=offline.publish._track_tool_time_evidence(entry['tool_time'],result,tracked,backend=offline.new_backend)
    assert receipt['clock_bound_is_exact'] is False
    assert {str(config),str(identity),str(stop)}<=set(tracked)


def test_changed_source_run_or_payload_aborts_without_real_publication(offline):
    export=Path(read(offline.selection)['tasks'][0]['task_directory'])
    (export/'environment/extra.py').write_text('unmanifested')
    with pytest.raises(Exception,match='missing|inventory|manifest|payload|changed'):
        invoke(offline,dry_run=True)
    assert not (offline.root/'SpreadsheetEval').exists()


def test_cli_is_a_separate_namespace_and_does_not_run_when_imported(monkeypatch):
    path=ROOT/'scripts/publish_clock_resource_dataset.py'
    spec=importlib.util.spec_from_file_location('_test_clock_publication_cli',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.ResourcePublicationBackend is v3.ResourcePublicationBackend
    assert module.legacy is v3.publisher_namespace()
    assert module.legacy is not legacy.support(ROOT,'publish_dataset.py')
    calls=[]
    monkeypatch.setattr(module,'publish',lambda *args,**kwargs:calls.append(kwargs) or {'offline':True})
    module.main(['publish','--cohort','/fake/cohort','--selection-manifest','/fake/select','--evaluation-manifest','/fake/eval'])
    assert calls==[{'publish_files':False}]


def test_frozen_template_drift_is_rejected(monkeypatch):
    monkeypatch.setattr(v3,'DATASET_PUBLISHER_SHA256','0'*64)
    with pytest.raises(ValueError,match='template changed'):
        v3.publisher_ast()

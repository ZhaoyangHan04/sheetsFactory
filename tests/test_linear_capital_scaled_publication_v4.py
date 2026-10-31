"""Service-free N360 admission, complete-cohort and once-only lifecycle tests."""
import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
from types import SimpleNamespace

import openpyxl
import pytest
import yaml
from test_resource_publication import offline as legacy_offline

from sheets_factory.evaluation import linear_capital_scaled_publication_v4 as pub
from sheets_factory.evaluation import linear_capital_scaled_frontier_v4 as runner
from sheets_factory.evaluation import native_transport_frontier_v4 as old_runner
from sheets_factory.evaluation import clock_resource_publication_v4 as clocks
from sheets_factory.evaluation.streaming_verifier import compare_files

ROOT=Path(__file__).resolve().parents[1]
def script(name):
    spec=importlib.util.spec_from_file_location('_test_'+name,ROOT/'scripts'/(name+'.py'))
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
cli=script('publish_linear_capital_scaled_v4')
development=script('prepare_linear_capital_scaled_development_v4')


@pytest.fixture(autouse=True)
def no_services(monkeypatch):
    def forbidden(*a,**k):raise AssertionError('These fixtures cannot start a service or process')
    monkeypatch.setattr(subprocess,'Popen',forbidden);monkeypatch.setattr(subprocess,'run',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return pub.reference(path)


def book(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    wb=openpyxl.Workbook();wb.active['A1']=value;wb.save(path);wb.close();return pub.reference(path)


def material(tmp_path,mode='financial_modeling'):
    root=tmp_path/'task';book(root/'environment/input.xlsx',1);book(root/'tests/reference.xlsx',2)
    (root/'instruction.md').write_text('Complete the financial model.')
    return root,cli.material_identity(root,mode)


def history(tmp_path,identity,*,phase='development',task_id='old-name',source=True):
    row={'task_id':task_id,'mode':identity['mode'],'revision':0,'revision_hash':'c'*64,'task_checksum':'d'*64}
    if source:
        record=write(tmp_path/'old-source.json',{'tasks':[{'task_id':task_id,'material_task_version':identity}]})
        manifest={'source_manifest':record,'phase':phase,'tasks':[row]}
    else:manifest={'phase':phase,'tasks':[row]}
    return write(tmp_path/'old/selection_manifest.json',manifest)


def row(identity,index=0):
    return {'task_id':'new-'+str(index),'mode':identity['mode'],'revision':0,'revision_hash':hashlib.sha256(str(index).encode()).hexdigest(),
        'material_task_version':identity}


def test_genuine_normal_class_identity_and_exact_view_recipe_stay_distinct():
    assert pub.admission.LinearSourceAdmission is pub.admission.source.LinearSourceAdmission
    assert pub.admission.ReferenceViewAdmission is not pub.admission.source.LinearViewAdmission
    for value in ({'passed':True},SimpleNamespace(guard=lambda:{'passed':True})):
        with pytest.raises(ValueError):pub.admission.require_view_admission(value)
        with pytest.raises(ValueError):pub.admission.require_source_admission(value)
    assert pub.admission.REQUIRED_VIEW_UPSTREAM['sha256']=='24decf5b019f1183ef6c7538c4947e9757cd160d1f11c54d9e3fce36582ae974'
    assert pub.self_families()=={'linear_capital_scaled_FM':'financial_modeling','linear_capital_scaled_DBG':'debugging'}


def test_backend_is_native_n360_v4_and_reference_review_only():
    backend=pub.ResourcePublicationBackend()
    assert backend.runner is runner and backend.agent_import_path.endswith('linear_capital_scaled_frontier_v4:LocalCodex')
    assert backend.release is pub.release_namespace()
    assert backend.publisher is pub.publisher_namespace()
    tree=pub.backend_ast()
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='ResourcePublicationBackend')
    load=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='load_selection')
    calls=[n for n in ast.walk(load) if isinstance(n,ast.Call) and ast.unparse(n.func)=='self.release._validate_task']
    assert len(calls)==1 and [(k.arg,ast.literal_eval(k.value)) for k in calls[0].keywords if k.arg=='reference_policy']==[('reference_policy','reference_review')]
    freeze=cli._freeze_namespace()
    assert freeze.ResourcePublicationBackend is pub.ResourcePublicationBackend
    assert not any('public-solving witness' in c for c in load.name.split())


def test_reference_release_keeps_entire_generic_task_gate_bytecode():
    frozen=pub.support(ROOT,'package_release.py');new=pub.release_namespace()
    assert frozen._validate_task.__code__.co_code==new._validate_task.__code__.co_code
    assert frozen._validate_task.__code__.co_consts==new._validate_task.__code__.co_consts
    assert new._validate_reference_review.__code__.co_code!=frozen._validate_reference_review.__code__.co_code


def test_all_declared_normal_tasks_are_required_even_if_one_failed(tmp_path,monkeypatch):
    run=str(tmp_path/'normal');sources=[{'source_run':run,'task_id':'a'}]
    monkeypatch.setattr(cli,'read_run',lambda _: {'tasks':[{'id':'a','status':'qualified'},{'id':'b','status':'qualified'}]})
    with pytest.raises(ValueError,match='every task'):cli._complete_declaration(sources)
    sources.append({'source_run':run,'task_id':'b'})
    assert cli._complete_declaration(sources)==[run]
    monkeypatch.setattr(cli,'read_run',lambda _: {'tasks':[{'id':'a','status':'qualified'},{'id':'b','status':'rejected'}]})
    with pytest.raises(ValueError,match='do not filter'):cli._complete_declaration(sources)


@pytest.mark.parametrize('private_setting',['actual_config_default','relative','absolute'])
def test_cohort_validation_resolves_optional_private_root_from_actual_normal_config(tmp_path,monkeypatch,private_setting):
    """Exercise the frontdoor with the real config's absent optional key; other gates are explicit mocks."""
    config=yaml.safe_load((ROOT/'config/pipelines/linear_capital_scaled_reference_quality_v1.yaml').read_text())
    assert 'private_evidence_directory' not in config['diagnosis']['execution']
    expected=tmp_path/'outputs/diagnostic_private_evidence'
    if private_setting=='relative':
        config['diagnosis']['execution']['private_evidence_directory']='private/custom-evidence'
        expected=tmp_path/'private/custom-evidence'
    elif private_setting=='absolute':
        expected=tmp_path.parent/'absolute-evidence'
        config['diagnosis']['execution']['private_evidence_directory']=str(expected)
    run=tmp_path/'normal';binding={'complete_export':'fixture'};identity={'sha256':'a'*64}
    task={'task_id':'one','source_run':str(run),'family':'linear_capital_scaled_FM',
        'task_directory':str(tmp_path/'cohort/SpreadsheetEval/one'),'mode':'financial_modeling',
        'harbor_export_binding':binding,'material_task_version':identity}
    cohort={'tasks':[task],'tool_time_policy':runner.POLICY_V4,'native_transport_profile':runner.transport_profile(),
        'reference_evidence_policy':'reference_review','effective_infrastructure_retries':0,'execution_concurrency':4,
        'final20_qualified':False,'declared_normal_directories':[str(run)],
        'confirmation_cohort_identity':cli.canonical([identity['sha256']]),
        'history_roots':[str(tmp_path/'outputs/difficulty')],'prior_selection_inventory':[]}
    calls=[];rechecks=[]
    backend=SimpleNamespace(root=tmp_path,cohort=cohort,_run=lambda *a:{'config':config},
        release=SimpleNamespace(_validate_task=lambda *a,**kw:calls.append(kw)),
        publisher=SimpleNamespace(_credential_values=lambda _:[]),inspect_export=lambda _:binding,
        recheck_tracked=lambda _:rechecks.append('tracked'),recheck_payloads=lambda:rechecks.append('payloads'))
    monkeypatch.setattr(cli.publication,'ResourcePublicationBackend',lambda _:backend)
    monkeypatch.setattr(cli,'read_run',lambda _: {'tasks':[{'id':'one'}]})
    monkeypatch.setattr(cli,'_complete_declaration',lambda _:[str(run)])
    monkeypatch.setattr(cli,'material_identity',lambda *a:identity)
    monkeypatch.setattr(cli,'selection_history',lambda *a:[])
    assert cli.validate_cohort(tmp_path/'cohort.json') is backend
    assert len(calls)==1 and calls[0]['private_evidence_root']==expected
    assert calls[0]['project_root']==tmp_path and calls[0]['reference_policy']=='reference_review'
    assert calls[0]['private_evidence_tracked']=={} and rechecks==['tracked','payloads']


def test_development_history_is_retained_but_does_not_spend_confirmation(tmp_path):
    _,identity=material(tmp_path);record=history(tmp_path,identity)
    assert cli.selection_history([row(identity)],[tmp_path])==[record]


def test_same_material_confirmation_renamed_or_repacked_is_rejected(tmp_path):
    _,identity=material(tmp_path);history(tmp_path,identity,phase='confirmation')
    with pytest.raises(ValueError,match='logical material'):cli.selection_history([row(identity)],[tmp_path])


def test_old_confirmation_without_identity_uses_real_complete_workbooks(tmp_path):
    directory,identity=material(tmp_path);record=history(tmp_path,identity,phase='confirmation',source=False)
    old=pub.read(record['path']);old['tasks'][0]['task_directory']=str(directory);write(record['path'],old)
    with pytest.raises(ValueError,match='unchanged material'):cli.selection_history([row(identity)],[tmp_path])


def test_corrupt_or_missing_history_source_cannot_be_ignored(tmp_path):
    _,identity=material(tmp_path);record=history(tmp_path,identity)
    source=Path(pub.read(record['path'])['source_manifest']['path']);source.write_text('{}')
    with pytest.raises(ValueError,match='changed'):cli.selection_history([row(identity)],[tmp_path])
    source.unlink()
    with pytest.raises(ValueError):cli.selection_history([row(identity)],[tmp_path])


def test_control_path_uses_unique_current_revision_attempt_and_retains_failed_history(tmp_path):
    base=tmp_path/'revision';source=book(base/'public/input.xlsx',1);goal=book(base/'private/goal.xlsx',2)
    write(base/'private/diagnosis.json',{'reference_binding':{'task_revision_hash':'r'}})
    reports={'oracle':compare_files(source['path'],goal['path'],goal['path'])};write(base/'private/local_controls.json',reports)
    write(base/'private/controls/attempt_failed/attempt.json',{'completed':False})
    value={'completed':True,'revision_hash':'r','source':source,'goal':goal,'reports':reports,'actual_LO_calls':[]}
    path=base/'private/controls/attempt_ok/attempt.json';write(path,value);tracked={}
    found=pub.control_path(base,'equivalent',tracked,pub.release_namespace())
    assert found==path.parent/'equivalent.xlsx'
    assert str(base/'private/controls/attempt_failed/attempt.json') in tracked
    write(base/'private/controls/attempt_duplicate/attempt.json',value)
    with pytest.raises(ValueError,match='exactly one'):pub.control_path(base,'equivalent',{},pub.release_namespace())


def reservation_fixture(tmp_path):
    _,identity=material(tmp_path);rows=[row(identity)]
    cohort={'tasks':rows,'confirmation_cohort_identity':cli.canonical([identity['sha256']]),'prior_selection_inventory':[]}
    path=tmp_path/'cohort.json';write(path,cohort)
    validator=lambda _:SimpleNamespace(cohort=deepcopy(cohort))
    return identity,path,cohort,validator


def test_append_only_unrelated_history_is_captured_in_durable_reservation(tmp_path):
    identity,path,cohort,validator=reservation_fixture(tmp_path)
    other={**identity,'instruction_sha256':'9'*64};other['sha256']=cli.canonical({k:v for k,v in other.items() if k!='sha256'})
    prior=history(tmp_path/'history',other)
    receipt,value=cli.reserve_confirmation(path,tmp_path/'eval',validator=validator,history_roots=[tmp_path/'history'])
    assert value['selection_history_inventory']==value['model_selections']==[prior]
    assert value['nonmodel_preparations']==[] and pub.checked(receipt)==value
    assert value['effective_infrastructure_retries']==0
    with pytest.raises(ValueError,match='already reserved'):cli.reserve_confirmation(path,tmp_path/'other',validator=validator,history_roots=[tmp_path/'history'])


@pytest.mark.parametrize('mutation',['changed','missing','same_material'])
def test_reservation_refuses_changed_missing_or_same_material_added_history(tmp_path,mutation):
    identity,path,cohort,validator=reservation_fixture(tmp_path)
    prior=history(tmp_path/'history',identity,phase='development')
    cohort['prior_selection_inventory']=[prior];write(path,cohort)
    if mutation=='changed':Path(prior['path']).write_text('{}')
    elif mutation=='missing':Path(prior['path']).unlink()
    else:history(tmp_path/'history/new',identity,phase='confirmation')
    with pytest.raises((ValueError,KeyError)):cli.reserve_confirmation(path,tmp_path/'eval',validator=validator,history_roots=[tmp_path/'history'])
    assert not list((tmp_path/'history/.linear_scaled_confirmation_reservations').glob('material_*.json'))


def test_two_concurrent_snapshots_spend_exactly_one_confirmation(tmp_path):
    _,path,_,validator=reservation_fixture(tmp_path)
    def attempt(index):
        try:return cli.reserve_confirmation(path,tmp_path/('eval'+str(index)),validator=validator,history_roots=[tmp_path/'history'])[0]
        except ValueError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(attempt,range(2)))
    assert sum(r is not None for r in results)==1
    assert len(list((tmp_path/'history/.linear_scaled_confirmation_reservations').glob('material_*.json')))==1


def test_new_development_entry_keeps_schema_two_and_same_global_reservation():
    assert development.VERSION==2
    text=ast.unparse(development._entry_ast())
    assert "'.scaled_development_reservations'" in text
    assert development.KIND.endswith('_v4')
    assert development._run_once.__globals__['POLICY_V4']==runner.POLICY_V4
    assert development._reserve_first_attempt.__code__.co_code==development._old._reserve_first_attempt.__code__.co_code
    assert not hasattr(development,'resume_infrastructure')


def test_budget_policy_and_zero_retries_frozen_before_attempt():
    tree=runner.adapted_ast();freeze=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='freeze_selection')
    assert "'max_retries': 0" in ast.unparse(freeze)
    assert runner.POLICY_V4['complete_clock_proved_failure']
    for policy in (old_runner.POLICY_V4,{},dict(runner.POLICY_V4,version=3)):
        with pytest.raises(ValueError):pub._policy_n360({'tool_time_policy_version':4,'tool_time_policy':policy},pub.require)


@pytest.mark.parametrize('lower,upper,complete,expected',[
    (1_800_000_000_000,1_801_000_000_000,True,False),
    (1_800_000_000_001,1_801_000_000_000,True,False),
    (1_799_999_999_999,1_800_000_000_000,True,None),
    (1_800_000_000_000,1_801_000_000_000,False,None)])
def test_complete_negative_bound_boundary_and_unknowns(monkeypatch,lower,upper,complete,expected):
    bound={'complete':complete,'cumulative_lower_bound_ns':lower,'cumulative_upper_bound_ns':upper}
    old={'measurement_branch':'complete_proven_owned_overlap','state':'unknown','passed':None,'complete_owned_overlap_receipt':bound}
    monkeypatch.setattr(old_runner,'account_trial_tool_time_v4',lambda *a,**k:deepcopy(old))
    actual=runner.account_trial_tool_time_v4('unused')
    assert actual['passed'] is expected
    if expected is False:
        assert actual['retained_general_v4_receipt']==old
        assert actual['state']=='verified_tool_budget_lower_bound'
    else:assert actual==old


def test_exact_verified_overbudget_raw_one_is_a_legal_scored_zero(monkeypatch,tmp_path):
    old={'state':'verified','passed':False,'policy_version':4,'measurement_branch':'unchanged_v3_exact_or_bound',
        'cumulative_tool_seconds':1826.290321299,'cumulative_tool_nanoseconds':1826290321299,
        'base_policy_v3_receipt':{'state':'verified','passed':False,'policy_version':3}}
    monkeypatch.setitem(runner._namespace,'account_trial_tool_time_v4',lambda *a,**k:deepcopy(old))
    selection={'tool_time_policy':runner.POLICY_V4}
    result=runner.apply_tool_time_policy({'status':'scored','reward':1,'result_file':str(tmp_path/'result.json')},selection)
    assert result['status']=='scored' and result['reward']==0 and result['raw_verifier_reward']==1
    assert result['failure_kind']=='cumulative_tool_budget_exhausted'
    assert result['tool_time']['cumulative_tool_nanoseconds']==1826290321299


def test_proved_lower_bound_failure_is_scored_zero_but_straddle_is_unknown(monkeypatch,tmp_path):
    for state,passed,expected in [('verified_tool_budget_lower_bound',False,'scored'),('unknown',None,'evidence_incomplete')]:
        receipt={'state':state,'passed':passed}
        monkeypatch.setitem(runner._namespace,'account_trial_tool_time_v4',lambda *a,**k:deepcopy(receipt))
        result=runner.apply_tool_time_policy({'status':'scored','reward':1,'result_file':str(tmp_path/'r')},{'tool_time_policy':runner.POLICY_V4})
        assert result['status']==expected
        assert result['reward']==(0 if passed is False else None)


@pytest.mark.parametrize('span_ms,passed',[(1_800_002,False),(1_800_003,False),(1_800_001,None)])
def test_negative_bound_real_native_stream_recalculation_and_publisher(tmp_path,span_ms,passed):
    fixture=script_helper('test_tool_time_clock_bounds.py')
    paths,data=fixture.fixture(tmp_path)
    end=fixture.BASE_MS+20+span_ms
    tool=fixture.tools(data)[0];tool['completed_at_ms']=end
    tool['item']['duration']=fixture.duration((span_ms+20)*1_000_000)
    data['native'][2]['timestamp']=fixture.stamp(end+80)
    data['native'][-2]['timestamp']=fixture.stamp(end+180)
    data['native'][-1]['timestamp']=fixture.stamp(end+280)
    data['result']['agent_execution']['finished_at']=fixture.stamp(end+380)
    data['result']['finished_at']=fixture.stamp(end+480);fixture.save(paths,data)
    receipt=runner.account_trial_tool_time_v4(paths['result'])
    assert receipt['passed'] is passed and receipt['complete']
    assert receipt['cumulative_lower_bound_ns']==(span_ms-2)*1_000_000
    names=('tool_time_clock_bounds_v4.py','tool_time_clock_bounds.py','tool_time.py')
    recipe={'src/sheets_factory/evaluation/'+n:pub.reference(ROOT/'src/sheets_factory/evaluation'/n) for n in names}
    backend=SimpleNamespace(runner=runner,cohort={'publication_recipe':recipe})
    tracked={}
    if passed is False:
        evidence=pub._track_n360(receipt,paths['result'],tracked,backend,lambda *a:{},pub.release_namespace(),pub.require)
        assert len(tracked)==6 and evidence['clock_bound_is_exact'] is False
        projected=pub._project_n360(receipt,evidence,pub.require)
        assert projected['passed'] is False and projected['cumulative_tool_nanoseconds'] is None
        forged=deepcopy(receipt);forged['cumulative_lower_bound_ns']-=1
        with pytest.raises(ValueError,match='does not reproduce'):
            pub._track_n360(forged,paths['result'],{},backend,lambda *a:{},pub.release_namespace(),pub.require)
    else:
        with pytest.raises(ValueError):pub._track_n360(receipt,paths['result'],tracked,backend,lambda *a:{},pub.release_namespace(),pub.require)


def script_helper(filename):
    spec=importlib.util.spec_from_file_location('_N360_fixture_'+filename[:-3],ROOT/'tests'/filename)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value


def test_generic_confirmation_includes_exact_budget_failure_in_denominator(legacy_offline,monkeypatch):
    """Real timing/trial kernel; source and resource admission are explicit mocks."""
    fixture=legacy_offline;publisher=pub.publisher_namespace();monkeypatch.setattr(publisher,'MIN_PER_MODE',1)
    source=pub.read(fixture.source);source.update(tool_time_policy_version=4,tool_time_policy=runner.POLICY_V4,
        native_transport_profile=runner.transport_profile());write(fixture.source,source)
    selection=pub.read(fixture.selection);selection.update(tool_time_policy_version=4,tool_time_policy=runner.POLICY_V4,
        native_transport_profile=runner.transport_profile(),source_manifest={'path':str(fixture.source),'sha256':pub.reference(fixture.source)['sha256']},
        infrastructure_retry_policy={'max_retries':0,'scored_attempts_per_task':1,'never_retry_scored':True})
    for row in selection['tasks']:row['tool_time_policy']=runner.POLICY_V4
    write(fixture.selection,selection)
    evaluation=pub.read(fixture.evaluation);evaluation.update(tool_time_policy_version=4,tool_time_policy=runner.POLICY_V4,
        selection_manifest={'path':str(fixture.selection),'sha256':pub.reference(fixture.selection)['sha256']},
        finished_at='2026-10-29T12:40:00Z',infra_history=[],infrastructure_retries=[])
    persist=script_helper('test_frontier.py').persist_timing
    for index,entry in enumerate(evaluation['attempts']):
        result=Path(entry['result_file']);actual=pub.read(result)
        actual['config']['agent']['import_path']='sheets_factory.evaluation.linear_capital_scaled_frontier_v4:LocalCodex'
        actual['verifier_result']['rewards']['reward']=1 if index==0 else 0
        actual['agent_execution']['finished_at']=actual['finished_at']='2026-10-29T12:35:00Z'
        write(result,actual);persist(result,seconds=1826 if index==0 else 1)
        if index==0:
            path=result.parent/'agent/sessions/fixture.jsonl';records=[json.loads(line) for line in path.read_text().splitlines()]
            item=records[1]['payload'];item['item']['duration']['nanos']=290321299;item['completed_at_ms']+=290
            records[2]['timestamp']='2026-10-29T12:31:27.290Z'
            path.write_text('\n'.join(json.dumps(r) for r in records)+'\n')
        entry.update(result_sha256=pub.reference(result)['sha256'],status='scored',reward=1 if index==0 else 0,tool_time_policy=runner.POLICY_V4)
        runner.apply_tool_time_policy(entry,selection)
        assert entry['status']=='scored' and entry['reward']==0
    write(fixture.evaluation,evaluation)
    backend=SimpleNamespace(runner=runner,agent_import_path='sheets_factory.evaluation.linear_capital_scaled_frontier_v4:LocalCodex',
        cohort={'publication_recipe':pub.publication_recipe(ROOT)},validate_confirmation_source=lambda *a:None,
        export_files=runner.TASK_FILES,inspect_export=pub.inspect_resource_export)
    tracked={str(fixture.selection):pub.reference(fixture.selection)['sha256']}
    result=publisher._validate_confirmation(fixture.evaluation,fixture.selection,selection,fixture.rows,tracked,backend=backend)
    assert result['task_count']==2 and result['passed']==0 and result['overall_pass_at_1']==0
    first=result['tasks'][0]
    assert first['raw_verifier_reward']==1 and first['reward']==0
    assert first['tool_time']['passed'] is False and first['tool_time']['state']=='verified'
    assert first['tool_time']['cumulative_tool_nanoseconds']==1826290321299


def test_full20_shape_is_genuine_distinct_and_cannot_accept_old_namespace(tmp_path,monkeypatch):
    run=tmp_path/'normal';rows=[];tasks=[];sources=[]
    for index in range(20):
        mode='financial_modeling' if index<10 else 'debugging';task_id='task-'+str(index)
        folder=run/'SpreadsheetEval'/task_id
        book(folder/'environment/input.xlsx',index);book(folder/'tests/reference.xlsx',index+100)
        (folder/'instruction.md').write_text('Complete the financial model.')
        revision=hashlib.sha256(task_id.encode()).hexdigest()
        binding={'task_id':task_id,'task_name':task_id,'revision':0,'revision_hash':revision,
            'export_manifest_sha256':'f'*64,'required_controls':{},'resource_runtime':{}}
        family='linear_capital_scaled_FM' if index<10 else 'linear_capital_scaled_DBG'
        rows.append({'task_id':task_id,'source_run':str(run),'family':family,'mode':mode,'revision':0,
            'revision_hash':revision,'source_id':'a'*64,'harbor_export_binding':binding,'audited_harbor_export_binding':binding})
        tasks.append({'id':task_id,'status':'qualified'});sources.append({'task_id':task_id,'source_run':str(run),'family':family})
    monkeypatch.setattr(cli,'read_run',lambda _: {'tasks':tasks})
    cohort={'kind':pub.KIND,'version':4,'status':'frozen_for_fresh_confirmation','tasks':rows,
        'selected_task_ids':[r['task_id'] for r in rows],'frozen_at':'2026-10-31T18:00:00Z',
        'execution_budget':pub.BUDGET,'selection_uses_confirmation_outcomes':False,'publication_recipe':pub.publication_recipe(ROOT)}
    cli._augment_cohort(cohort,sources,tmp_path,history_roots=[tmp_path/'outputs/research'])
    pub.ResourcePublicationBackend.validate_cohort_shape(cohort)
    assert len({r['material_task_version']['sha256'] for r in cohort['tasks']})==20
    for change in ('old_family','subset','repeated_identity','old_policy'):
        bad=deepcopy(cohort)
        if change=='old_family':bad['tasks'][0]['family']='scaled_capital'
        elif change=='subset':bad['tasks'].pop();bad['selected_task_ids'].pop()
        elif change=='repeated_identity':bad['tasks'][1]['material_task_version']=bad['tasks'][0]['material_task_version']
        else:bad['tool_time_policy']=old_runner.POLICY_V4
        with pytest.raises(ValueError):pub.ResourcePublicationBackend.validate_cohort_shape(bad)


def test_publication_rechecks_all_shared_reservations_and_captured_history(tmp_path):
    identity,path,cohort,validator=reservation_fixture(tmp_path)
    history_root=tmp_path/'outputs/difficulty';prior=history(history_root,identity)
    record,value=cli.reserve_confirmation(path,tmp_path/'evaluation',validator=validator,history_roots=[history_root])
    backend=SimpleNamespace(root=tmp_path,cohort=cohort,cohort_path=path)
    backend._bind=lambda value,tracked:pub.ResourcePublicationBackend._bind(backend,value,tracked)
    frozen={'frozen_at':value['started_at'],'prior_selections':[{'path':prior['path'],'sha256':prior['sha256']}]}
    tracked={};pub._bind_confirmation_reservation(backend,tmp_path/'evaluation/selection_manifest.json',frozen,{},tracked)
    assert record['path'] in tracked and prior['path'] in tracked
    with pytest.raises(ValueError,match='dropped model history'):
        pub._bind_confirmation_reservation(backend,tmp_path/'evaluation/selection_manifest.json',{**frozen,'prior_selections':[]},{},{})
    directory=history_root/'.linear_scaled_confirmation_reservations'
    next(directory.glob('material_*.json')).unlink()
    with pytest.raises(ValueError):pub._bind_confirmation_reservation(backend,tmp_path/'evaluation/selection_manifest.json',frozen,{},{})

"""Full official scope with explicit fake model/process boundaries; no services."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def module():
    spec = importlib.util.spec_from_file_location('_external_cohort_tests', ROOT/'scripts/run_external_calibration_cohort.py')
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def dump(m, path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False)+'\n')
    return m.reference(path)


@pytest.fixture
def corpus(module, tmp_path, monkeypatch):
    m = module; cases = []; metadata = {}; raw_metadata = {}
    evaluator = tmp_path/'official_evaluator.py'; evaluator.write_text('# Explicit offline evaluator fixture\n')
    for category, mode, projects, variants in [('Financial_Model', 'financial_modeling', 20, 5), ('Debugging', 'debugging', 10, 10)]:
        rows = []
        for project in range(1, projects+1):
            goal = tmp_path/'books'/category/f'{project:02}_gold.xlsx'
            goal.parent.mkdir(parents=True, exist_ok=True); goal.write_bytes(b'Original golden fixture '+str(project).encode())
            for variant in range(1, variants+1):
                official_id = f'{project:02}_{variant:02}'
                source = goal.with_name(official_id+'_input.xlsx'); source.write_bytes(b'Original public fixture '+official_id.encode())
                record = {'id': official_id, 'instruction': 'Complete the stated model.\nPreserve € units and formatting.',
                    'spreadsheet_path': f'spreadsheet/{official_id}_input.xlsx',
                    'golden_response_path': f'spreadsheet/{project:02}_gold.xlsx', 'answer_position': "'Model'!A1:B2"}
                rows.append(record); key = category+'/'+official_id
                cases.append({'index': len(cases), 'category': category, 'mode': mode, 'official_task_id': official_id,
                    'case_key': key, 'task_id': 'external-sb2-'+('fm-' if category == 'Financial_Model' else 'dbg-')+official_id.replace('_', '-'),
                    'official_record': record, 'input': m.reference(source), 'goal': m.reference(goal),
                    'input_member': 'spreadsheetbench-v2/'+category+'/'+record['spreadsheet_path'],
                    'goal_member': 'spreadsheetbench-v2/'+category+'/'+record['golden_response_path'],
                    'existing_attempt': {} if key in ('Financial_Model/03_04', 'Debugging/04_01') else None,
                    'requires_new_model_attempt': key not in ('Financial_Model/03_04', 'Debugging/04_01')})
        metadata[category] = dump(m, tmp_path/(category+'_dataset.json'), rows)
        raw_metadata[category] = Path(metadata[category]['path']).read_bytes()
    archive = tmp_path/'pinned_fixture.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        for category, raw in raw_metadata.items(): z.writestr('spreadsheetbench-v2/'+category+'/dataset.json', raw)
    monkeypatch.setattr(m, 'ARCHIVE_SHA', m.reference(archive)['sha256'])
    monkeypatch.setattr(m, 'ARCHIVE_BYTES', archive.stat().st_size)
    monkeypatch.setattr(m, 'EVALUATOR_SHA', m.reference(evaluator)['sha256'])
    groups = [[c['case_key'] for c in cases if c['category'] == category] for category in m.MODES]
    value = {'kind': m.INVENTORY_KIND, 'version': 1, 'official_revision': m.HF, 'official_evaluator_revision': m.GITHUB,
        'archive': m.reference(archive), 'official_evaluator': m.reference(evaluator), 'official_metadata': metadata,
        'cases': cases, 'fixed_order': [c['case_key'] for c in cases],
        'prospective_execution_order': [item for pair in zip(*groups) for item in pair]}
    return SimpleNamespace(m=m, root=tmp_path, value=value, ref=dump(m, tmp_path/'inventory.json', value), evaluator=evaluator)


def test_all_200_identities_and_interleaved_order_are_required(corpus):
    _, value = corpus.m.checked_inventory(corpus.ref)
    assert len(value['cases']) == 200
    assert sum(c['requires_new_model_attempt'] for c in value['cases']) == 198
    assert value['prospective_execution_order'][:4] == ['Financial_Model/01_01', 'Debugging/01_01', 'Financial_Model/01_02', 'Debugging/01_02']


@pytest.mark.parametrize('fault', ['subset', 'metadata_order', 'extra_reuse', 'instruction', 'input_bytes', 'archive', 'revision', 'execution_order'])
def test_full_scope_or_bytes_mutation_fails_closed(corpus, fault):
    m=corpus.m; value=deepcopy(corpus.value)
    if fault == 'subset': value['cases'].pop()
    elif fault == 'metadata_order': value['cases'][0], value['cases'][1] = value['cases'][1], value['cases'][0]
    elif fault == 'extra_reuse': value['cases'][0].update(existing_attempt={}, requires_new_model_attempt=False)
    elif fault == 'instruction': value['cases'][0]['official_record']['instruction'] += '\nAn extra target hint.'
    elif fault == 'input_bytes': Path(value['cases'][0]['input']['path']).write_bytes(b'Changed input')
    elif fault == 'archive': value['archive']['sha256'] = '0'*64
    elif fault == 'revision': value['official_revision'] = '0'*40
    else: value['prospective_execution_order'].reverse()
    with pytest.raises(ValueError): m.checked_inventory(dump(m, corpus.root/'mutated.json', value))


@pytest.mark.parametrize('field,value', [('model','other'), ('reasoning_effort','high'), ('outer_retries',1), ('concurrency',5)])
def test_model_effort_retries_and_global_concurrency_are_frozen(module, tmp_path, field, value):
    config = module.policy(); config[field] = value
    with pytest.raises(ValueError): module.policy(dump(module, tmp_path/'policy.json', config)['path'])


def test_export_preserves_raw_input_goal_and_original_instruction_prefix(corpus):
    m=corpus.m; case=corpus.value['cases'][0]; folder=corpus.root/'export_test'
    export, binding, transport = m._export(case, folder)
    original = case['official_record']['instruction'].encode()
    text = (export/'instruction.md').read_bytes()
    assert text.startswith(original) and text[len(original):].startswith(b'\n\n---\nTransport context (file paths only):')
    assert b'01_01_input.xlsx' in text[len(original):] and b'answer_position' not in text[len(original):]
    assert (export/'environment/input.xlsx').read_bytes() == Path(case['input']['path']).read_bytes()
    assert (export/'tests/reference.xlsx').read_bytes() == Path(case['goal']['path']).read_bytes()
    assert len(list(p for p in export.rglob('*') if p.is_file())) == 17
    assert m.read(transport)['original_prefix_byte_identical'] is True
    assert (folder/'private/worker_cap.json').is_file()
    assert (export/'environment/Dockerfile').read_text().splitlines()[1] == 'ENV MAX_CONCURRENCY=2'


class Audit:
    def __init__(self): self.tasks=[]
    def task(self, *args, **kwargs): self.tasks.append((args,kwargs))
    def export(self): pass


@pytest.fixture
def case_boundary(corpus, monkeypatch):
    m=corpus.m; case=deepcopy(corpus.value['cases'][0]); calls=[]
    def forbidden(*a, **k): raise AssertionError('No actual model, compatibility LO or in-process native call is allowed')
    monkeypatch.setattr(m, '_compatibility', forbidden)
    monkeypatch.setattr(m, '_model_core', forbidden)
    monkeypatch.setattr(m.runner, 'run_evaluation', forbidden)
    evaluator=SimpleNamespace(process_single_item=lambda record, root, output, mapping, category: ({'id':record['id'],'accuracy':1.0},False))
    monkeypatch.setattr(m, 'load', lambda *a: evaluator)
    def model(case, folder, export, binding, config, order):
        calls.append(case['task_id']); order.enter(case['case_key'])
        artifact=folder/'evaluation/harbor_jobs/job/trial/artifacts/app/output.xlsx'
        artifact.parent.mkdir(parents=True); artifact.write_bytes(b'One unchanged original submission')
        return {'resources': {'passed':True,'complete':True}, 'value': {'status':'completed','attempts':[
            {'task_id':case['task_id'],'job_name':'job','trial_name':'trial','status':'scored','reward':0,
             'failure_kind':None,'tool_time':{'passed':True}}]}}
    monkeypatch.setattr(m, '_model_subprocess', model)
    return SimpleNamespace(m=m, case=case, output=corpus.root/'cohort', calls=calls, evaluator_ref=m.reference(corpus.evaluator))


def test_default_skips_compatibility_LO_and_official_one_is_separate_from_project_zero(case_boundary):
    c=case_boundary; config=c.m.policy()
    assert config['run_compatibility_controls'] is False
    terminal=c.m.read(c.m._case(c.case,c.output,config,c.evaluator_ref,Audit(),c.m.LaunchOrder([c.case['case_key']])))
    assert c.calls == [c.case['task_id']]
    assert c.m.read(terminal['compatibility'])['status']=='not_run'
    assert c.m.read(terminal['compatibility'])['actual_LO_calls']==0
    assert terminal['official_primary']['result']['accuracy']==1.0
    assert terminal['project_exact_diagnostic']['reward']==0
    assert terminal['native_run_complete'] is True and terminal['official_model_failure'] is False


def test_native_setup_failure_is_retained_and_next_order_slot_is_released(case_boundary, monkeypatch):
    c=case_boundary
    def fail(*args): raise RuntimeError('Explicit offline child failure')
    monkeypatch.setattr(c.m,'_model_subprocess',fail)
    order=c.m.LaunchOrder([c.case['case_key'],'next'])
    terminal=c.m.read(c.m._case(c.case,c.output,c.m.policy(),c.evaluator_ref,Audit(),order))
    assert terminal['disposition']=='infrastructure_or_driver_hold' and terminal['no_retry']
    assert terminal['official_model_failure'] is False
    order.enter('next')


def test_native_launch_is_a_separate_child_and_request_bound(corpus, monkeypatch):
    m=corpus.m; case=corpus.value['cases'][0]; folder=corpus.root/'process'; folder.mkdir()
    export=folder/'export'; export.mkdir(); calls=[]; config=m.policy()
    def popen(command, **kwargs):
        calls.append((command,kwargs)); request_path=Path(command[-1]); request=m.reference(request_path)
        value={'kind':'isolated_official_research_native_attempt','request':request,'passed_transport':True,
            'model':{'value':{'status':'completed'},'resources':{'passed':True,'complete':True}}}
        dump(m,folder/'model_process_terminal.json',value)
        return SimpleNamespace(pid=12345,wait=lambda:0)
    monkeypatch.setattr(m.subprocess,'Popen',popen)
    monkeypatch.setattr(m,'_model_core',lambda *a:pytest.fail('Native execution must be in child only'))
    result=m._model_subprocess(case,folder,export,{'revision_hash':'r'},config,m.LaunchOrder([case['case_key']]))
    assert len(calls)==1 and calls[0][0][2]=='--internal-case-model'
    assert calls[0][0][0]==m.sys.executable
    assert result['value']['status']=='completed' and result['process_terminal']==m.reference(folder/'model_process_terminal.json')
    assert 'credentials_in_arguments' in m.read(folder/'model_process_started.json')
    assert m.read(folder/'model_process_started.json')['credentials_in_arguments'] is False


@pytest.mark.parametrize('failure,timing,effective,state', [
    ('cumulative_tool_budget_exhausted', False, 0, 'known_tool_budget_failure'),
    ('incomplete_tool_timing', None, None, 'unknown'),
])
def test_raw_official_one_never_overrides_budget_or_unknown_timing(module, failure, timing, effective, state):
    result=module.protocol_score({'result':{'accuracy':1.0}},
        {'status':'scored','failure_kind':failure,'tool_time':{'passed':timing}},
        {'value':{'status':'completed'},'resources':{'passed':True,'complete':True}})
    assert result['official_raw_accuracy']==1.0
    assert result['protocol_effective_accuracy'] is effective or result['protocol_effective_accuracy']==effective
    assert result['protocol_state']==state and not result['native_run_complete']


def test_full_inventory_reservations_are_durable_and_UI_precedes_every_dispatch(corpus, monkeypatch):
    m=corpus.m; output=corpus.root/'prepared'; output.mkdir()
    dump(m,output/'preparation.json',{'explicit_offline_fixture':True})
    config=m.policy(); frozen={'policy':config,'inventory':corpus.ref,
        'execution_order':corpus.value['prospective_execution_order']}
    monkeypatch.setattr(m,'validate_prepared',lambda p:(deepcopy(frozen),deepcopy(corpus.value)))
    private_root=corpus.root/'isolated_project';(private_root/'outputs/research').mkdir(parents=True)
    monkeypatch.setattr(m,'ROOT',private_root)
    state={'ui':False,'cases':[]}
    class Lease:
        def __init__(self,*a):pass
        def acquire(self):return self
        def release(self):pass
    class Store:
        def __init__(self,*a):self.db=SimpleNamespace(close=lambda:None)
        def snapshot(self):return {}
        def events(self,*a):return []
        def update_run(self,**kw):pass
        def export(self):pass
    class Server:
        def __init__(self,*a,**kw):pass
        def start(self):state['ui']=True;return 'http://127.0.0.1:12345/'
        def stop(self):pass
    monkeypatch.setattr(m,'ProducerLease',Lease)
    monkeypatch.setattr(m,'AuditStore',Store)
    monkeypatch.setattr(m,'DashboardServer',Server)
    monkeypatch.setattr(m,'verify_local_base_image',lambda *a:{'explicit_offline_image_boundary':True})
    def case_once(case,folder,*args):
        assert state['ui']
        state['cases'].append(case['case_key'])
        return dump(m,folder/'cases'/case['task_id']/'terminal.json',{'case_key':case['case_key'],'offline_only':True})
    monkeypatch.setattr(m,'_case',case_once)
    terminal=m.read(m.execute_prepared(output))
    assert len(state['cases'])==200 and terminal['all_declared_cases_retained']
    registry=private_root/'outputs/research/external_calibration_first_selection_registry'
    assert len(list(registry.glob('*.json')))==198
    with pytest.raises(ValueError):m.execute_prepared(output)
    other=corpus.root/'other_prepared';other.mkdir();dump(m,other/'preparation.json',{'explicit_offline_fixture':True})
    with pytest.raises(FileExistsError):m.execute_prepared(other)
    assert len(state['cases'])==200 and len(list(registry.glob('*.json')))==198

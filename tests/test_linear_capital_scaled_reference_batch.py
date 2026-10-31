"""No-service tests for the N360 fixed-pool reference supervisor adapter."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from test_linear_capital_optimization_runtime import services

ROOT = Path(__file__).resolve().parents[1]
definition = importlib.util.spec_from_file_location('_scaled_reference_batch_test',
    ROOT/'scripts/run_linear_capital_scaled_reference_batch.py')
entry = importlib.util.module_from_spec(definition); definition.loader.exec_module(entry)


@pytest.fixture
def synthetic(monkeypatch):
    original_read,original_ref = entry.read,entry.ref
    records,values = {},{}
    def add(path,value):
        path = str(path); record = {'path':path,'sha256':'a'*64,'bytes':1}
        records[path] = record; values[path] = value; return record
    declaration = add('/explicit_fake_pool/declaration.json',entry.EXPECTED_DECLARATION)
    raw_rows,finance_rows = [],[]
    for pid in entry.ORDER:
        public = add('/explicit_fake_pool/'+pid+'/specification.json',{})
        raw = add('/explicit_fake_pool/'+pid+'/raw.json',{})
        terminal = add('/explicit_fake_finance/'+pid+'/terminal.json',{
            'kind':'linear_capital_scaled_full_financial_crosscheck','version':2,'passed':True,
            'qualified':False,'toy_only':False,'recipe':entry.api.finance_recipes(),
            'raw_preparation':raw,'specification':public,
            'optimizer_calls':0,'LO_calls':0,'model_calls':0,'task_count':0})
        raw_rows.append({'profile_id':pid,'specification':public,'raw_preparation':raw})
        finance_rows.append({'profile_id':pid,'terminal':terminal})
    raw_ref = add('/explicit_fake_pool/catalog_manifest.json',{
        'profile_order':entry.ORDER,'declaration':declaration,'profiles':raw_rows})
    finance_ref = add('/explicit_fake_finance/inventory.json',{'kind':entry.FINANCE_MAP_KIND,'version':2,
        'raw_catalog':raw_ref,'profile_order':entry.ORDER,'profiles':finance_rows})
    def read(value):
        path = value['path'] if isinstance(value,dict) else str(value)
        return deepcopy(values[path]) if path in values else original_read(value)
    def reference(value):
        return records[str(value)] if str(value) in records else original_ref(value)
    monkeypatch.setattr(entry,'read',read); monkeypatch.setattr(entry,'ref',reference)
    monkeypatch.setattr(entry.raw_api,'validate_prepared',lambda _:deepcopy(values[raw_ref['path']]))
    return {'raw':raw_ref,'finance':finance_ref,'values':values,'records':records}


def test_configuration_has_complete_new_pool_identity_and_original_resource_contract(synthetic,monkeypatch):
    monkeypatch.setattr(entry.api.runtime,'_command',lambda *_a,**_k:pytest.fail('No Docker'))
    config = entry.checked_config(entry.DEFAULT_CONFIG)
    inventory,lineage = entry.checked_inventory(synthetic['raw'],synthetic['finance'])
    assert [row['profile_id'] for row in inventory] == entry.ORDER
    assert config['declaration']['profiles'] == [
        {'id':pid,'seed':202701361+i,'revenue_jitter_pence':150000} for i,pid in enumerate(entry.ORDER)]
    assert config['complete_business_rows'] == 941 and config['resources']['cpus'] == 16
    assert config['resources']['seconds_per_phase'] == 3600
    assert lineage == {'raw_catalog':synthetic['raw'],'finance_terminals':synthetic['finance']}


@pytest.mark.parametrize('field,value', [('profile_order',list(reversed(entry.ORDER))),('retries',False),
    ('max_parallel',5),('retries',1),('complete_business_rows',881),('reference_policy','uniqueness_bound'),
    ('reference_api_sha256','0'*64),('declaration',{}),('resources',{'cpus':2})])
def test_configuration_rejects_scope_policy_resource_order_and_retry_changes(tmp_path,field,value):
    config = entry.read(entry.DEFAULT_CONFIG); config[field] = value
    path = tmp_path/'changed.json'; path.write_text(json.dumps(config))
    with pytest.raises(ValueError): entry.checked_config(path)


@pytest.mark.parametrize('fault', ['missing','order','duplicate','wrong_raw_catalog','version',
    'failed','toy','wrong_recipe','wrong_raw_binding','old_terminal','model_calls'])
def test_missing_failed_or_misbound_finance_is_rejected_before_reference_preparation(synthetic,fault):
    values = synthetic['values']; finance = values[synthetic['finance']['path']]
    terminal = values[finance['profiles'][0]['terminal']['path']]
    if fault == 'missing': finance['profiles'].pop()
    elif fault == 'order': finance['profiles'].reverse()
    elif fault == 'duplicate': finance['profiles'][1] = deepcopy(finance['profiles'][0])
    elif fault == 'wrong_raw_catalog': finance['raw_catalog'] = synthetic['finance']
    elif fault == 'version': finance['version'] = 1
    elif fault == 'failed': terminal['passed'] = False
    elif fault == 'toy': terminal['toy_only'] = True
    elif fault == 'wrong_recipe': terminal['recipe'] = {}
    elif fault == 'wrong_raw_binding': terminal['raw_preparation'] = synthetic['raw']
    elif fault == 'old_terminal': terminal['kind'] = 'linear_capital_full_financial_crosscheck'
    elif fault == 'model_calls': terminal['model_calls'] = 1
    with pytest.raises(ValueError): entry.checked_inventory(synthetic['raw'],synthetic['finance'])


def test_all_twenty_are_declared_before_zero_service_preparations_and_freeze(monkeypatch,tmp_path,synthetic):
    monkeypatch.setattr(entry,'ROOT',tmp_path)
    output = tmp_path/'outputs/batch'; prepared,validated = [],[]
    def prepare(terminal,folder):
        declared = entry.read(output/'inventory.json')
        assert [p['profile_id'] for p in declared['profiles']] == entry.ORDER
        assert declared['maximum_native_solver_calls'] == 40 and declared['actual_solver_calls'] == 0
        folder.mkdir(parents=True); prepared.append(folder.name)
        return entry.write(folder/'preparation.json',{'explicit_fake_boundary':True,'finance_terminal':terminal})
    monkeypatch.setattr(entry.api,'prepare',prepare)
    monkeypatch.setattr(entry.api,'validate_prepared',lambda folder:validated.append(folder.name))
    monkeypatch.setattr(entry.api,'execute_prepared',lambda *_a,**_k:pytest.fail('No reference execution'))
    monkeypatch.setattr(entry.api,'_refs',lambda _:None)  # Other inputs are explicit in-memory references.
    record = entry.prepare(entry.DEFAULT_CONFIG,synthetic['raw'],synthetic['finance'],output)
    frozen = entry.read(record)
    assert prepared == validated == entry.ORDER
    assert frozen['version'] == 2 and frozen['profile_order'] == entry.ORDER
    assert frozen['native_solver_calls'] == frozen['model_calls'] == frozen['LO_calls'] == 0
    assert not frozen['qualified'] and frozen['task_count'] == 0
    assert entry.validate(output) == frozen and validated == entry.ORDER+entry.ORDER
    with pytest.raises(ValueError): entry.prepare(entry.DEFAULT_CONFIG,synthetic['raw'],synthetic['finance'],output)


def test_partial_preparation_failure_preserves_inventory_and_artifacts(monkeypatch,tmp_path,synthetic):
    monkeypatch.setattr(entry,'ROOT',tmp_path); output = tmp_path/'outputs/failed'; calls = []
    def prepare(terminal,folder):
        calls.append(folder.name); folder.mkdir(parents=True)
        if folder.name == entry.ORDER[2]: raise ValueError('Explicit mocked compatibility rejection')
        return entry.write(folder/'preparation.json',{'explicit_fake_boundary':True})
    monkeypatch.setattr(entry.api,'prepare',prepare)
    monkeypatch.setattr(entry.api,'validate_prepared',lambda _:None)
    with pytest.raises(ValueError,match='mocked compatibility rejection'):
        entry.prepare(entry.DEFAULT_CONFIG,synthetic['raw'],synthetic['finance'],output)
    assert calls == entry.ORDER[:3] and not (output/'prospective.json').exists()
    assert len(entry.read(output/'inventory.json')['profiles']) == 20
    failure = entry.read(output/'compatibility_failure.json')
    assert failure['all_partial_artifacts_retained'] and list(failure['preparations']) == entry.ORDER[:2]
    assert failure['native_solver_calls'] == 0


def test_worker_retains_nonoptimal_rejection_without_retry_or_cold_pass(monkeypatch,tmp_path):
    output = tmp_path/'run'; pid = entry.ORDER[0]; folder = output/'profiles'/pid; folder.mkdir(parents=True)
    entry.write(output/'prospective.json',{'explicit_fake_boundary':True})
    monkeypatch.setattr(entry,'validate',lambda *_a,**_k:{})
    calls = []
    def execute(actual):
        calls.append(actual)
        return entry.write(folder/'terminal.json',{'passed':False,'error_type':'ValueError','error':'FEASIBLE; OPTIMAL required'})
    monkeypatch.setattr(entry.api,'execute_prepared',execute)
    monkeypatch.setattr(entry.api,'validate_completed',lambda *_a:pytest.fail('No cold pass for rejection'))
    assert entry.worker(output,pid) == 1 and calls == [folder]
    result = entry.read(folder/'worker_terminal.json')
    assert not result['passed'] and not result['retry_authorized'] and result['model_calls'] == 0
    assert result['terminal'] == entry.ref(folder/'terminal.json')
    with pytest.raises(ValueError): entry.worker(output,pid)


def test_worker_pass_requires_cold_complete_validator_and_941_rows(monkeypatch,tmp_path):
    output = tmp_path/'run'; pid = entry.ORDER[0]; folder = output/'profiles'/pid; folder.mkdir(parents=True)
    entry.write(output/'prospective.json',{'explicit_fake_boundary':True})
    monkeypatch.setattr(entry,'validate',lambda *_a,**_k:{})
    monkeypatch.setattr(entry.api,'execute_prepared',lambda _:entry.write(folder/'terminal.json',{'passed':True}))
    seen = []
    def check(receipt):
        seen.append(receipt); return {'gap_pence':1,'selected_project_count':150}
    monkeypatch.setattr(entry.api,'validate_completed',check)
    assert entry.worker(output,pid) == 0 and len(seen) == 1
    cold = entry.read(folder/'cold_completed_validation.json')
    assert cold['version2_best_and_runner_OPTIMAL'] and cold['both_complete_matrix_rows_per_phase'] == 941
    assert cold['additional_financial_forward_calls'] == 0


def test_all_twenty_dispatch_once_at_four_with_rejection_retained(monkeypatch,tmp_path):
    output = tmp_path/'run'; output.mkdir(); dummy = entry.write(output/'prospective.json',{'explicit_fake_boundary':True})
    for pid in entry.ORDER: (output/'profiles'/pid).mkdir(parents=True)
    monkeypatch.setattr(entry,'validate',lambda *_a,**_k:{'lineage':{'finance_terminals':dummy}})
    state = services(monkeypatch); launched,active,peak = [],set(),[]
    class Process:
        def __init__(self,command,**kwargs):
            assert command[2:4] == ['worker','--prepared']
            self.profile = command[-1]; self.pid = 1000+len(launched); self.polls = 0
            assert self.profile not in launched
            launched.append(self.profile); active.add(self.profile); peak.append(len(active))
            entry.write(output/'profiles'/self.profile/'worker_terminal.json',{
                'passed':self.profile != entry.ORDER[2],'explicit_fake_boundary':True,'elapsed_seconds':1})
        def poll(self):
            self.polls += 1
            if self.polls == 1: return None
            active.discard(self.profile); return int(self.profile == entry.ORDER[2])
        def wait(self): return self.poll()
    monkeypatch.setattr(entry.subprocess,'Popen',Process)
    monkeypatch.setattr(entry.time,'sleep',lambda _:None)
    monkeypatch.setattr(entry,'owned_jobs',lambda _folder,**_kwargs:{})
    result = entry.read(entry.execute(output))
    assert launched == entry.ORDER and max(peak) == 4 and not active
    assert result['version'] == 2 and result['profile_order'] == [p['profile_id'] for p in result['profiles']]
    assert result['rejected_profiles'] == [entry.ORDER[2]] and len(result['accepted_profiles']) == 19
    assert not result['passed'] and result['retries'] == 0
    assert result['completed_finance_terminal_inventory'] == dummy
    assert 'finance_accounting_correction' not in result
    assert state['released'] and state['closed'] and state['stopped']
    with pytest.raises(ValueError): entry.execute(output)


def test_exact_owned_job_parser_is_unchanged_and_any_supervisor_drift_fails(monkeypatch,tmp_path):
    before = ast.parse(entry.UPSTREAM.read_bytes()); after = entry.adapted_ast()
    old = next(n for n in before.body if isinstance(n,ast.FunctionDef) and n.name == 'owned_jobs')
    new = next(n for n in after.body if isinstance(n,ast.FunctionDef) and n.name == 'owned_jobs')
    assert ast.dump(old) == ast.dump(new)
    altered = tmp_path/'changed.py'; altered.write_bytes(entry.UPSTREAM.read_bytes()+b'\n')
    monkeypatch.setattr(entry,'UPSTREAM',altered)
    with pytest.raises(ValueError,match='frozen four-worker'): entry.adapted_ast()


def test_prepare_cli_requires_both_completed_lineage_arguments():
    with pytest.raises(SystemExit) as error: entry.main(['prepare','--output','unused'])
    assert error.value.code == 2

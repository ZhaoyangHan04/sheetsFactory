"""Code/fixture tests only: no production enumeration, LO or model calls."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    descriptor=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(descriptor);descriptor.loader.exec_module(result)
    return result


entry=module('_constrained_dual_test_entry',ROOT/'scripts/run_constrained_capital_dual.py')
public_preparer=module('_constrained_dual_test_raw',ROOT/'scripts/prepare_constrained_capital_specs.py')
hand=module('_constrained_dual_hand_cases',ROOT/'tests/test_capital_allocation_ledger.py')


def read(ref):return json.loads(Path(ref['path']).read_text())


def write(path,value):return entry.write(path,value)


@pytest.fixture
def evidence(tmp_path):
    """Raw primitives are real; all historical result claims are unit fixtures."""
    manifest_ref=public_preparer.prepare(tmp_path/'test_raw_public_only')
    manifest=read(manifest_ref);record=manifest['specifications'][0]
    inventory=read(record['engineering_inventory'])
    root=tmp_path/'historical_UNIT_FIXTURES';root.mkdir()
    checks=[]
    for index,declared in enumerate(inventory['plans']):
        ledger_ref=write(root/(str(index)+'.json'),{'UNIT_FIXTURE_NOT_A_FINANCIAL_AUDIT':True})
        checks.append({**declared,'A_B_Decimal_match':True,'ledger':ledger_ref})
    probe_ref=write(root/'probe.json',{'kind':'scaled_capital_explicit_fixed_plan_diagnostics',
        'UNIT_FIXTURE':True,'passed':True,'plan_count':44,'checks':checks})
    old_assessment=write(root/'old_assessment.json',{'UNIT_FIXTURE':True,'all_predeclared_criteria_passed':False})
    diagnostic_ref=write(root/'diagnostic.json',{'kind':'constrained_capital_D02_actual_fixed_plan_diagnostics',
        'UNIT_FIXTURE':True,'status':'completed_with_unmet_engineering_criteria','execution_completed':True,
        'exact_fixed_plan_count':44,'all44_A_B_Decimal_outcomes_match':True,'catalog_manifest':manifest_ref,
        'public_specification':record['spec'],'fixed_plan_probe':probe_ref,'engineering_criteria':old_assessment})
    financing_ref=write(root/'financing_addendum.json',{'kind':'constrained_D02_fixed_inventory_financing_scope_addendum',
        'UNIT_FIXTURE':True,'original_terminal':diagnostic_ref,'original_assessment_preserved':True})
    coverage_ref=write(root/'coverage.json',{'kind':'constrained_D02_complete_fixed_inventory_pairwise_readonly_coverage',
        'UNIT_FIXTURE':True,'original_terminal':diagnostic_ref,'original_probe':probe_ref,
        'original_inventory':record['engineering_inventory'],'fixed_plan_count':44,'total_unordered_pairs':946,
        'original_assessment_preserved':True,'original_predeclared_pair_outcomes':[
            {'predeclared_left':a,'predeclared_right':b,'ordering_reversal':False} for a,b in inventory['comparison_pairs']],
        'existing_ledger_refs':[c['ledger'] for c in checks],
        'all946_pairs':write(root/'pairs.json',{'UNIT_FIXTURE':True}),
        'all_reversals':write(root/'reversals.json',{'UNIT_FIXTURE':True}),
        'all_ordering_reversals_count':122})
    return SimpleNamespace(manifest=manifest_ref,record=record,inventory=inventory,root=root,
        diagnostics=diagnostic_ref,financing=financing_ref,coverage=coverage_ref,
        prepare=lambda output,profile='30-D02':entry.prepare(manifest_ref,profile,output,
            diagnostics_receipt=diagnostic_ref,financing_scope_addendum=financing_ref,coverage_receipt=coverage_ref))


def test_default_preparation_and_validation_start_no_process_or_financial_execution(evidence,tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('Preparation cannot compile, enumerate, calculate finance or start services')
    monkeypatch.setattr(subprocess,'run',forbidden)
    monkeypatch.setattr(entry.ledger,'simulate',forbidden)
    monkeypatch.setattr(entry.search_a,'execute_prepared',forbidden)
    monkeypatch.setattr(entry.search_b,'execute_prepared',forbidden)
    monkeypatch.setattr(entry,'DashboardServer',forbidden)
    prepared=evidence.prepare(tmp_path/'prepared')
    frozen,public,inventory=entry.validate_prepared(prepared)
    assert frozen['kind']==entry.PREPARED_KIND and frozen['profile_id']=='30-D02'
    assert len(public['projects'])==30 and len(inventory['plans'])==44
    assert frozen['count_per_kernel']==1<<30 and frozen['expected_record_bytes_per_kernel']==32*(1<<30)
    assert frozen['compiler_calls']==frozen['kernel_calls']==frozen['Decimal_forward_calls']==0
    assert frozen['LO_calls']==frozen['model_calls']==frozen['source_workbooks']==frozen['task_count']==0
    assert frozen['qualified'] is False and frozen['execution_requires_explicit_run'] is True
    assert frozen['confirmation_profiles_not_executed']==list(entry.catalog.CONFIRMATION_ORDER)
    assert frozen['engineering_provenance_summary']['original_predeclared_three_pair_gate_passed'] is False
    assert frozen['engineering_provenance_summary']['expanded_pairwise_reversal_count']==122
    assert not (tmp_path/'prepared/attempts').exists()


@pytest.mark.parametrize('profile',['30-H01','30-H10','30-D01','26-B01','unknown'])
def test_only_first_prospective_constrained_development_profile_may_be_prepared(evidence,tmp_path,profile):
    with pytest.raises(ValueError,match='first constrained'):evidence.prepare(tmp_path/'rejected',profile)
    assert not (tmp_path/'rejected').exists()


def test_complete_catalog_order_and_original_fixed_inventory_must_remain_intact(evidence,tmp_path):
    manifest=read(evidence.manifest);manifest['profile_order'].reverse()
    changed=write(evidence.root/'bad_manifest.json',manifest)
    with pytest.raises(ValueError,match='complete original'):entry.prepare(changed,'30-D02',tmp_path/'bad',
        diagnostics_receipt=evidence.diagnostics,financing_scope_addendum=evidence.financing,coverage_receipt=evidence.coverage)


def test_expanded_pair_coverage_cannot_rewrite_the_original_failed_three_pairs(evidence,tmp_path):
    coverage=read(evidence.coverage);coverage['original_predeclared_pair_outcomes'][0]['ordering_reversal']=True
    changed=write(evidence.root/'rewritten_gate.json',coverage)
    with pytest.raises(ValueError,match='failed prospective pair'):entry.prepare(evidence.manifest,'30-D02',tmp_path/'bad',
        diagnostics_receipt=evidence.diagnostics,financing_scope_addendum=evidence.financing,coverage_receipt=changed)


def test_expanded_coverage_must_bind_all44_existing_ledger_refs(evidence,tmp_path):
    coverage=read(evidence.coverage);coverage['existing_ledger_refs'].pop()
    changed=write(evidence.root/'missing_ledger.json',coverage)
    with pytest.raises(ValueError,match='same complete'):entry.prepare(evidence.manifest,'30-D02',tmp_path/'bad',
        diagnostics_receipt=evidence.diagnostics,financing_scope_addendum=evidence.financing,coverage_receipt=changed)


@pytest.mark.parametrize('mutation',['recipe','count','guard','fixed_count','source_hash','wire','wire_rebound'])
def test_changed_preparation_is_rejected_before_any_execute(evidence,tmp_path,monkeypatch,mutation):
    prepared=evidence.prepare(tmp_path/'prepared');frozen=read(prepared)
    if mutation=='recipe':frozen['recipe'][str(Path(entry.__file__).resolve())]['sha256']='0'*64
    if mutation=='count':frozen['count_per_kernel']-=1
    if mutation=='guard':frozen['kernel_timeout_seconds']=1800
    if mutation=='fixed_count':frozen['fixed_plan_count']=43
    if mutation=='source_hash':frozen['spec_sha256']='0'*64
    if mutation in ('wire','wire_rebound'):
        wire=Path(frozen['canonical_raw_wires']['A']['path']);wire.write_text(wire.read_text()+'0\n')
        if mutation=='wire_rebound':frozen['canonical_raw_wires']['A']=entry.reference(wire)
    Path(prepared['path']).write_text(json.dumps(frozen))
    monkeypatch.setattr(entry.search_a,'execute_prepared',lambda *a,**k:pytest.fail('Must fail before native execution'))
    with pytest.raises(ValueError):entry.execute_prepared(prepared['path'])
    assert not (tmp_path/'prepared/attempts').exists()


def comparison_fixture(tmp_path):
    public=entry.catalog.build_spec('30-D02')
    binary=b''.join(struct.pack('<IIqqq',mask,7,10+mask,20+mask,30+mask) for mask in range(2))
    refs=[]
    for name in ('A','B'):
        path=tmp_path/(name+'.bin');path.write_bytes(binary);refs.append(entry.reference(path))
    chunk={'start_mask':0,'end_mask_exclusive':2,'record_count':2,'bytes':64,'sha256':hashlib.sha256(binary).hexdigest()}
    common={'UNIT_FIXTURE_NOT_A_PRODUCTION_ENUMERATION':True,'status':'completed','full_enumeration':True,
        'toy_only':False,'plan_count':2,'spec_sha256':entry.spec.canonical_sha(public),'chunks':[chunk],
        'feasible_count':2,'best_count':1,'best_mask':1,'objective_pence':11,'runnerup_mask':0,
        'runnerup_objective_pence':10,'gap_pence':1,'unique_best':True,'best_full_mask':1,
        'best_plan':{p['id']:int(i==0) for i,p in enumerate(public['projects'])}}
    return public,{**deepcopy(common),'records':refs[0]},{**deepcopy(common),'records':refs[1]}


def test_complete_comparison_checks_all_chunks_whole_hash_and_every_rank_field_without_third_scan(tmp_path,monkeypatch):
    public,a,b=comparison_fixture(tmp_path)
    monkeypatch.setattr(entry,'reference',lambda *a:pytest.fail('Do not hash both complete streams a third time'))
    result=entry._compare_results(a,b,public,count=2)
    assert result['records_equal_complete'] is result['rankings_equal'] is True
    assert result['chunk_count_per_kernel']==1 and result['plan_count']==2


@pytest.mark.parametrize('mutation',['count','spec','record_sha','missing_chunk','chunk_gap','chunk_sha','rank','partial_file'])
def test_incomplete_or_disagreeing_independent_streams_fail_closed(tmp_path,mutation):
    public,a,b=comparison_fixture(tmp_path)
    if mutation=='count':b['plan_count']=1
    if mutation=='spec':b['spec_sha256']='0'*64
    if mutation=='record_sha':b['records']['sha256']='0'*64
    if mutation=='missing_chunk':b['chunks']=[]
    if mutation=='chunk_gap':b['chunks'][0]['end_mask_exclusive']=1
    if mutation=='chunk_sha':b['chunks'][0]['sha256']='0'*64
    if mutation=='rank':b['gap_pence']=2
    if mutation=='partial_file':Path(b['records']['path']).write_bytes(b'partial')
    with pytest.raises(ValueError):entry._compare_results(a,b,public,count=2)


def test_forward_checks_retain_best_runnerup_and_every_fixed_plan_even_duplicate_masks(tmp_path):
    public=hand.specification()
    choices=lambda mask:{p['id']:(mask>>i)&1 for i,p in enumerate(public['projects'])}
    binary=bytearray()
    for mask in (0,1):
        forward=entry.ledger.simulate(public,choices(mask))
        values=[forward['scenarios'][sid]['npv_pence'] for sid in entry.spec.SCENARIO_IDS]
        binary.extend(struct.pack('<IIqqq',mask,7,*values))
    path=tmp_path/'two_hand_masks.bin';path.write_bytes(binary)
    inventory={'plans':[{'id':'fixed_'+str(i),'plan':choices(i%2)} for i in range(44)]}
    result=entry._forward_checks(public,inventory,{'best_mask':1,'runnerup_mask':0,'records':entry.reference(path)},tmp_path/'forward')
    assert len(result['checks'])==46
    assert [r['id'] for r in result['checks'][2:]]==[r['id'] for r in inventory['plans']]
    assert all(r['record_matches'] and r['all_journals_balance'] for r in result['checks'])
    assert result['optimisation_performed'] is result['independent_global_optimality_claimed'] is False


def test_kernel_failure_waits_for_other_independent_attempt_and_preserves_both(evidence,tmp_path,monkeypatch):
    prepared=evidence.prepare(tmp_path/'prepared');completed=threading.Event();calls=[]
    def a(*args):calls.append('A');raise RuntimeError('fixture A failure, no native execution')
    def b(*args,**kwargs):
        assert kwargs=={'allow_full':True,'timeout_seconds':14400}
        calls.append('B');time.sleep(.03);completed.set()
        return write(evidence.root/'mock_B_terminal.json',{'UNIT_FIXTURE':True,'status':'completed'})
    monkeypatch.setattr(entry.search_a,'execute_prepared',a)
    monkeypatch.setattr(entry.search_b,'execute_prepared',b)
    monkeypatch.setattr(entry.shutil,'disk_usage',lambda p:SimpleNamespace(free=10**12))
    with pytest.raises(ValueError,match='Independent kernel failure'):entry.execute_prepared(prepared)
    assert completed.is_set() and sorted(calls)==['A','B']
    failures=list((tmp_path/'prepared/attempts').glob('*/failure.json'));assert len(failures)==1
    result=json.loads(failures[0].read_text())
    assert result['phase']=='actual_full_dual_enumeration' and set(result['results'])=={'B'}
    assert 'A' in result['kernel_errors'] and (failures[0].parent/'kernel_A_failure.json').exists()
    assert json.loads((tmp_path/'prepared/producer.lock').read_text())['status']=='released'
    with pytest.raises(ValueError,match='no silent repeat'):entry.execute_prepared(prepared)
    assert sorted(calls)==['A','B']


def test_capacity_guard_writes_started_and_failure_without_compiler_or_kernel(evidence,tmp_path,monkeypatch):
    prepared=evidence.prepare(tmp_path/'prepared')
    monkeypatch.setattr(entry.shutil,'disk_usage',lambda p:SimpleNamespace(free=0))
    monkeypatch.setattr(entry.search_a,'execute_prepared',lambda *a:pytest.fail('No capacity for actual records'))
    monkeypatch.setattr(entry.search_b,'execute_prepared',lambda *a,**k:pytest.fail('No capacity for actual records'))
    with pytest.raises(ValueError,match='capacity'):entry.execute_prepared(prepared)
    failures=list((tmp_path/'prepared/attempts').glob('*/failure.json'));assert len(failures)==1
    assert (failures[0].parent/'started.json').exists()
    assert not (failures[0].parent/'receipt.json').exists()
    assert json.loads(failures[0].read_text())['kernel_errors']=={}


def test_cli_default_is_prepare_and_execution_requires_existing_prepared_only(monkeypatch,capsys):
    calls=[]
    monkeypatch.setattr(entry,'prepare',lambda *a,**k:calls.append(('prepare',a,k)) or {'mock':'prepare'})
    monkeypatch.setattr(entry,'execute_prepared',lambda *a,**k:calls.append(('execute',a,k)) or {'mock':'execute'})
    entry.main(['--catalog-manifest','catalog','--profile','30-D02','--output','out',
        '--diagnostics-receipt','d','--financing-scope-addendum','f','--coverage-receipt','c'])
    assert calls[0][0]=='prepare' and len(calls)==1
    with pytest.raises(ValueError):entry.main(['--run','--prepared','out','--profile','30-H01'])
    entry.main(['--run','--prepared','out'])
    assert calls[-1][0]=='execute' and len(calls)==2


def test_stream_hash_never_materialises_complete_records(tmp_path,monkeypatch):
    path=tmp_path/'small_protocol_fixture.bin';path.write_bytes(b'abc'*1000)
    monkeypatch.setattr(Path,'read_bytes',lambda *a:pytest.fail('Stream complete search files'))
    assert entry.reference(path)['bytes']==3000

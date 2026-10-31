"""Builder UNIT fixtures perform no source emission, engine or model call."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
from uuid import uuid4

import openpyxl
import pytest

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts/build_heterogeneous_source.py'
loader=importlib.util.spec_from_file_location('heterogeneous_source_builder_unit',SCRIPT)
builder=importlib.util.module_from_spec(loader);loader.loader.exec_module(builder)


@pytest.fixture
def output():
    p=ROOT/'outputs/tmp'/('UNIT-heterogeneous-source-'+uuid4().hex)
    yield p
    if p.exists():shutil.rmtree(p)


def prepared(output,monkeypatch):
    # The schema, primitive copy and resource profile are real. A small UNIT
    # recipe avoids concurrent work on the independent Excel author's file.
    monkeypatch.setattr(builder,'recipes',lambda:{str(SCRIPT):builder.reference(SCRIPT)['sha256']})
    return builder.prepare(ROOT/'config/heterogeneous_contracts/prototype_v2.json',output,allow_prototype=True)


def test_prepare_is_zero_finance_workbook_docker_and_model_calls(output,monkeypatch):
    from sheets_factory.workbook.heterogeneous_contracts import ledger
    monkeypatch.setattr(ledger,'simulate',lambda *_:pytest.fail('Preparation executed finance'))
    monkeypatch.setattr(builder,'ResourceLibreOfficeEngine',lambda *_a,**_k:pytest.fail('Preparation instantiated Docker engine'))
    record=prepared(output,monkeypatch)
    f,s=builder.validate_prepared(record['path'])
    assert f['scope']=={'entities':6,'months':24,'scenarios':3}
    assert f['LO_calls']==f['model_calls']==f['task_count']==0
    assert f['source_workbook_materialized'] is f['ledger_execution'] is f['qualified'] is False
    assert not list(output.rglob('*.xlsx')) and not (output/'source_manifest.json').exists()
    assert s['entities'][0]['functional_currency']=='GBP'


def test_prototype_requires_explicit_optin_and_failure_is_preserved(output,monkeypatch):
    with pytest.raises(ValueError,match='allow-prototype'):
        builder.prepare(ROOT/'config/heterogeneous_contracts/prototype_v2.json',output)
    failure=builder.read(output/'preparation_failure.json')
    assert failure['LO_calls']==0 and failure['qualified'] is False
    with pytest.raises(ValueError,match='fresh'):
        builder.prepare(ROOT/'config/heterogeneous_contracts/prototype_v2.json',output,allow_prototype=True)


def test_changed_recipe_and_original_spec_cannot_be_continued(output,monkeypatch):
    prepared(output,monkeypatch)
    monkeypatch.setattr(builder,'recipes',lambda:{'changed':'0'*64})
    with pytest.raises(ValueError,match='recipe changed'):builder.validate_prepared(output)


def test_unsafe_output_and_reference_shape_failclosed(tmp_path):
    with pytest.raises(ValueError,match='/data/outputs'):builder._output(ROOT.parent/'outside-source-output')
    with pytest.raises(ValueError,match='reference'):builder.checked({'path':str(SCRIPT),'sha256':'0'*64,'bytes':True})


def test_reference_and_json_read_reject_changes_or_duplicate_keys(output):
    output.mkdir(parents=True)
    f=output/'value.json';f.write_text('{"x":1}')
    r=builder.reference(f);f.write_text('{"x":2}')
    with pytest.raises(ValueError,match='identity'):builder.checked(r)
    f.write_text('{"x":1,"x":2}')
    with pytest.raises(ValueError,match='Duplicate'):builder.read(f)
    f.write_text('{"x":NaN}')
    with pytest.raises(ValueError,match='Nonfinite'):builder.read(f)


def test_temporary_directory_is_under_data_and_environment_restored(output):
    import os,tempfile
    output.mkdir(parents=True)
    old,cached=os.environ.get('TMPDIR'),tempfile.tempdir
    with builder.data_temporary(output) as d:
        assert d.is_relative_to(ROOT/'outputs') and tempfile.gettempdir()==str(d)
    assert os.environ.get('TMPDIR')==old and tempfile.tempdir==cached


def forward(regimes=None):
    names=builder.REQUIRED_REGIMES if regimes is None else regimes
    return {'feasible':True,'checks':{'all_journals_and_financial_bridges_verified':True},
            'scenarios':{'S01':{'feasible':True,'mechanism_activation':{name:[{'month':'2027-01-01','amount_pence':1}] for name in names}}}}


def test_regime_coverage_does_not_silently_ignore_missing_mechanism():
    r=builder.mechanism_coverage(forward(builder.REQUIRED_REGIMES[:-1]))
    assert not r['all_required_observed'] and r['missing_regimes']==[builder.REQUIRED_REGIMES[-1]]
    assert builder.mechanism_coverage(forward())['all_required_observed']


def test_infeasible_or_unbalanced_journal_cannot_pass_regime_admission():
    for top,scenario,check in [(False,True,True),(True,False,True),(True,True,False)]:
        f=forward();f['feasible']=top;f['scenarios']['S01']['feasible']=scenario
        f['checks']['all_journals_and_financial_bridges_verified']=check
        with pytest.raises(ValueError):builder.mechanism_coverage(f)


def test_complete_geometry_and_no_formula_truncation():
    b=openpyxl.Workbook();s=b.active;s.title='UNIT Forecast';s['A1']='GBP';s['B1']='=1+1'
    bindings={'arithmetic_bindings':[{'sheet':s.title,'cell':'B1','formula':'=1+1'}],
        'formula_count':1,'financial_bindings':[{'sheet':s.title,'cell':'B1'}],
        'complete_scope':{'entities':1,'months':1,'scenarios':1}}
    p=builder.load_runtime_profile(builder.DEFAULT_PROFILE)
    r=builder.geometry(b,bindings,{'values':{(s.title,'A1'):'GBP',(s.title,'B1'):2}},p)
    assert r['physical_formula_count']==1 and r['truncated'] is False
    assert r['dependency_count_is_full_graph_upper_bound'] is True
    s['B2']='=1+1'
    with pytest.raises(ValueError,match='formula definitions'):builder.geometry(b,bindings,{'values':{}},p)
    b.close()


def test_public_prejoined_json_is_rejected_even_when_not_a_formula():
    b=openpyxl.Workbook();s=b.active;s['A1']=json.dumps({'private_contract':['unnecessary']*30});s['B1']='=1'
    bindings={'arithmetic_bindings':[{'sheet':s.title,'cell':'B1','formula':'=1'}],
        'formula_count':1,'financial_bindings':[{}],'complete_scope':{}}
    with pytest.raises(ValueError,match='JSON payload'):
        builder.geometry(b,bindings,{'values':{}},builder.load_runtime_profile(builder.DEFAULT_PROFILE))
    b.close()


def call_fixture(output):
    output.mkdir(parents=True)
    a=output/'UNIT-input.xlsx';b=output/'UNIT-output.xlsx';a.write_bytes(b'UNIT not an actual workbook');b.write_bytes(b'UNIT not an actual workbook result')
    profile_ref,profile=builder.runtime(builder.DEFAULT_PROFILE)
    frozen={'runtime_profile':profile_ref,'runtime_profile_value':profile}
    call={'input':builder.reference(a),'output':builder.reference(b)}
    value={'kind':'resource_bound_libreoffice_call','status':'completed','role':'source','actual_resources_verified':True,
        'call_id':'UNIT-call','source':call['input'],'output':call['output'],'destination':str(b),
        'image_id':builder.IMAGE['id'],'profile':profile_ref,'requested_resources':profile['docker_resources']['source'],
        'implementation':builder.reference(ROOT/'src/sheets_factory/workbook/resource_engine.py'),
        'upstream_engine':builder.reference(ROOT/'src/sheets_factory/workbook/engine.py'),
        'workbook_file_timeout_seconds':600,'actual_resources':{'cpus_nanoseconds':2000000000,'memory_bytes':32*1024**3,'pids_limit':256},
        'container_id':'a'*64,'create_command':['docker','create','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges'],
        'started_at':'2026-10-31T00:00:00+00:00','finished_at':'2026-10-31T00:00:01+00:00'}
    builder.write_new(output/'UNIT-call.started.json',{'call_id':'UNIT-call','source':call['input'],'started_at':value['started_at']})
    terminal=builder.write_new(output/'UNIT-call.terminal.json',value)
    return call,frozen,value,terminal


def test_actual_resource_receipt_binding_checks_are_structural_unit_only(output):
    call,frozen,_,r=call_fixture(output)
    proof=builder.validate_actual_call(call,r,frozen)
    assert proof['actual_resources']['memory_bytes']==32*1024**3
    assert not (output/'source_manifest.json').exists()  # UNIT receipts never create a source.


@pytest.mark.parametrize('field,value',[
    ('status','failed'),('actual_resources_verified',False),('role','agent'),('image_id','sha256:'+'0'*64),
    ('actual_resources',{'cpus_nanoseconds':1000000000,'memory_bytes':32*1024**3,'pids_limit':256}),
    ('source',{'path':'wrong','sha256':'0'*64,'bytes':1}),('create_command',[]),
    ('finished_at','2026-10-30T23:59:00+00:00'),('container_id','not-an-id')])
def test_failed_wrong_resource_or_wrong_chain_receipt_cannot_pass(output,field,value):
    call,frozen,v,_=call_fixture(output);v[field]=value
    r=builder.write_new(output/'UNIT-changed.terminal.json',v)
    with pytest.raises(ValueError):builder.validate_actual_call(call,r,frozen)


def test_failed_execution_preserves_started_terminal_and_never_publishes_source(output,monkeypatch):
    prepared(output,monkeypatch)
    from sheets_factory.workbook.heterogeneous_contracts import ledger
    def fail(_):raise RuntimeError('UNIT deliberate finance failure; no financial execution')
    monkeypatch.setattr(ledger,'simulate',fail)
    monkeypatch.setattr(builder,'ResourceLibreOfficeEngine',lambda *_a,**_k:pytest.fail('Failure instantiated LO'))
    with pytest.raises(RuntimeError,match='UNIT deliberate'):builder.execute_prepared(output)
    assert (output/'execution_started.json').exists() and not (output/'source_manifest.json').exists()
    terminal=list(output.glob('private/attempts/*/terminal.json'))
    assert len(terminal)==1 and builder.read(terminal[0])['status']=='failed'
    assert builder.read(terminal[0])['engine_calls']==[]
    assert builder.read(output/'producer.lock')['status']=='released'
    with pytest.raises(ValueError,match='already started'):builder.execute_prepared(output)


def test_one_command_run_prepares_then_executes_without_additional_confirmation(monkeypatch,output):
    calls=[]
    monkeypatch.setattr(builder,'prepare',lambda *a,**k:calls.append(('prepare',a,k)) or {'prepared':True})
    monkeypatch.setattr(builder,'execute_prepared',lambda *a,**k:calls.append(('execute',a,k)) or {'UNIT_no_actual_execution':True})
    builder.main(['--spec','UNIT.json','--output',str(output),'--allow-prototype','--run'])
    assert [c[0] for c in calls]==['prepare','execute']
    assert calls[0][2]['allow_prototype'] is True


def test_prepared_cli_cannot_override_frozen_source_options(output):
    with pytest.raises(ValueError,match='frozen options'):
        builder.main(['--prepared',str(output),'--spec','different.json'])

"""Offline joint-contract tests; mocked engine records certify no actual run."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import shutil

import openpyxl
import pytest

from sheets_factory.pipelines import joint_repair_activity as joint
from sheets_factory.pipelines import scc_activity_admission as admission
from sheets_factory.task_adapters.public_input_priority import ref
from test_scc_activity_integration import fixture,isolate_financial_gate,dump


def physical_fixture(tmp_path):
    ctx,binding,scope,events=fixture(tmp_path)
    book=openpyxl.load_workbook(ctx.source);book['First']['B1']=True
    book['First']['C1']=datetime(2030,1,2);book.calculation.iterate=True
    book.save(ctx.source);book.close()
    input_file=tmp_path/'input.xlsx';book=openpyxl.load_workbook(ctx.source)
    for edit in ctx.data['plan']['edits']:book[edit['sheet']][edit['cell']]=edit['after']
    book.save(input_file);book.close()
    return ctx,input_file


def test_joint_physical_whitelist_supports_cycles_and_preserves_typed_inputs(tmp_path):
    ctx,input_file=physical_fixture(tmp_path)
    proof=joint.validate_physical_edits(ctx.source,input_file,ctx.data['plan']['edits'])
    assert proof['physical_formula_mutation_count']==2 and proof['all_outside_definitions_and_typed_literals_unchanged']


@pytest.mark.parametrize('defect',['literal_bool_to_number','date_to_number','extra_formula','wrong_after','refMode'])
def test_unapproved_physical_or_typed_input_changes_are_rejected(tmp_path,defect):
    ctx,input_file=physical_fixture(tmp_path);book=openpyxl.load_workbook(input_file)
    if defect=='literal_bool_to_number':book['First']['B1']=1
    elif defect=='date_to_number':book['First']['C1']=0
    elif defect=='extra_formula':book['Second']['B1']='=1+1'
    elif defect=='wrong_after':book['First']['A1']='=777'
    else:book.calculation.refMode='R1C1'
    book.save(input_file);book.close()
    with pytest.raises(ValueError):joint.validate_physical_edits(ctx.source,input_file,ctx.data['plan']['edits'])


def mock_delta(monkeypatch):
    monkeypatch.setattr(joint,'compare_workbooks',lambda *a:{'structure_ok':True,'expected_change_count':2,
        'expected_changes':['First!A1','Downstream!A7']})


def test_masked_physical_edit_is_reported_without_individual_activity_claim(tmp_path,monkeypatch):
    ctx,input_file=physical_fixture(tmp_path);mock_delta(monkeypatch)
    summary=joint.describe_joint_delta(ctx.source,input_file,ctx.data['plan']['edits'],
        {'expected_change_count':2,'expected_changes':['Downstream!A7','First!A1']})
    assert summary['physical_formula_mutation_count']==2 and summary['physical_edits_in_actual_D_count']==1
    assert summary['unobservable_physical_edits']==['Second!A1'] and summary['complete_required_D_count']==2
    assert not summary['individual_or_marginal_activity_claimed'] and not summary['joint_input_global_uniqueness_claimed']


@pytest.mark.parametrize('changes',[['First!A1'],['First!A1','First!A1'],[]])
def test_complete_D_cannot_be_truncated_or_double_counted(tmp_path,monkeypatch,changes):
    ctx,input_file=physical_fixture(tmp_path);mock_delta(monkeypatch)
    with pytest.raises(ValueError):joint.describe_joint_delta(ctx.source,input_file,ctx.data['plan']['edits'],
        {'expected_change_count':len(changes),'expected_changes':changes})


def test_joint_two_pass_proof_claims_no_controls_quality_or_individual_effects(tmp_path,monkeypatch):
    ctx,input_file=physical_fixture(tmp_path);mock_delta(monkeypatch);calls=[]
    def calculate(source,output):calls.append((source,output));shutil.copyfile(source,output);return output
    engine=SimpleNamespace(metadata=lambda:{'backend':'libreoffice_uno_docker','network':'none','image_id':joint.IMAGE_ID},
        recalculate=calculate)
    delta={'expected_change_count':2,'expected_changes':['First!A1','Downstream!A7']}
    certificate=joint.prove_joint_repair(goal=ctx.source,combined_input=input_file,raw_mutation=input_file,
        edits=ctx.data['plan']['edits'],delta=delta,engine=engine,directory=tmp_path/'proof')
    assert certificate['passed'] is True and len(calls)==1  # First ordinary Construct call is an explicit premise.
    assert certificate['actual_joint_workbook_LO_execution_count']==2
    assert not certificate['five_local_controls_claimed'] and not certificate['quality_recovery_difficulty_certified']
    assert joint.validate_joint_certificate(certificate,ctx.source,input_file,ctx.data['plan']['edits'],delta)['unobservable_physical_edit_count']==1
    for key in ('five_local_controls_claimed','quality_recovery_difficulty_certified'):
        changed=deepcopy(certificate);changed[key]=True
        with pytest.raises(ValueError):joint.validate_joint_certificate(changed,ctx.source,input_file,ctx.data['plan']['edits'],delta)


def test_joint_opt_in_does_not_load_or_require_scc_checker(tmp_path,monkeypatch):
    isolate_financial_gate(monkeypatch);ctx,binding,scope,events=fixture(tmp_path)
    old=ctx.config.pop(admission.SETTING)
    old.pop('checker');old['version']=1;old['contract']=joint.METHOD
    old['bindings']=dump(tmp_path/'joint_bindings.json',{'kind':'full_graph_joint_repair_source_bindings',
        'version':1,'sources':{ctx.data['source_id']:binding}})
    ctx.config[joint.SETTING]=old
    monkeypatch.setattr(admission,'load_v8_checker',lambda *a:pytest.fail('Joint contract must not require strict SCC'))
    result=admission.validate_context_binding(ctx)
    assert result['provider'] is None and result['activity_contract']==joint.METHOD


def test_contract_selection_cannot_silently_mix_joint_and_strict(tmp_path,monkeypatch):
    isolate_financial_gate(monkeypatch);ctx,*_=fixture(tmp_path)
    ctx.config[joint.SETTING]={'enabled':True,'version':1,'contract':joint.METHOD}
    with pytest.raises(ValueError,match='Choose one'):admission.validate_context_binding(ctx)

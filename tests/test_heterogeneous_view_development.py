"""Development builder unit tests never execute source finance, LO or models."""
import hashlib
import importlib.util
from pathlib import Path

import openpyxl
import pytest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / 'scripts/prepare_heterogeneous_view_development.py'
definition = importlib.util.spec_from_file_location('unit_heterogeneous_view_development', FILE)
builder = importlib.util.module_from_spec(definition)
definition.loader.exec_module(builder)


def fixture_goal(tmp_path, *, amount='12.34', kind='money_pence'):
    path = tmp_path / 'UNIT-goal.xlsx'
    book = openpyxl.Workbook();sheet=book.active;sheet.title='S01 Statements'
    sheet['A1']='UNIT business forecast';sheet['E4']=float(amount);sheet['F4']=2
    book.create_sheet('UNIT Inputs')['A1']='UNIT fixed assumption'
    book.save(path);book.close()
    plan = {'forecast_targets':[{'sheet':'S01 Statements', 'cell':'E4',
        'reference_value':['number',amount], 'source':{'kind':kind}}]}
    return path,plan


def test_control_variants_change_only_their_declared_cells_and_preserve_goal(tmp_path):
    goal,plan=fixture_goal(tmp_path)
    before=hashlib.sha256(goal.read_bytes()).hexdigest()
    controls,selection=builder.create_control_variants(plan,goal,tmp_path)
    assert set(controls)=={'equivalent','missed_root','extra_change'}
    assert selection['posted_pence']==1234 and selection['missing_control_is_one_forecast_value']
    expected={'equivalent':('=1234/100','UNIT business forecast'),
        'missed_root':(None,'UNIT business forecast'), 'extra_change':(12.34,'UNIT business forecast changed')}
    for name,path in controls.items():
        book=openpyxl.load_workbook(path,data_only=False)
        assert (book['S01 Statements']['E4'].value,book['S01 Statements']['A1'].value)==expected[name]
        assert book['S01 Statements']['F4'].value==2
        assert book['UNIT Inputs']['A1'].value=='UNIT fixed assumption'
        book.close()
    assert hashlib.sha256(goal.read_bytes()).hexdigest()==before


@pytest.mark.parametrize('amount',['0.00','-0.01','98765.43'])
def test_control_formula_handles_zero_and_negative_pence(tmp_path,amount):
    goal,plan=fixture_goal(tmp_path,amount=amount)
    controls,selection=builder.create_control_variants(plan,goal,tmp_path)
    from decimal import Decimal
    assert selection['posted_pence']==int(Decimal(amount)*100)
    book=openpyxl.load_workbook(controls['equivalent'],data_only=False)
    assert book['S01 Statements']['E4'].value=='='+str(selection['posted_pence'])+'/100'
    book.close()


@pytest.mark.parametrize('amount,kind,message',[
    ('1.234','money_pence','exact posted penny'), ('1','integer','monetary forecast')])
def test_missing_or_unposted_monetary_control_is_rejected(tmp_path,amount,kind,message):
    goal,plan=fixture_goal(tmp_path,amount=amount,kind=kind)
    with pytest.raises(ValueError,match=message):builder.create_control_variants(plan,goal,tmp_path)
    assert not list(tmp_path.glob('*.raw.xlsx'))


def test_failed_source_admission_preserves_failure_without_task_or_engine(tmp_path,monkeypatch):
    output=tmp_path/'UNIT-preparation';source=tmp_path/'UNIT-source.json';source.write_text('{}')
    helper=builder.support()
    monkeypatch.setattr(helper,'_output',lambda p,**_:Path(p))
    monkeypatch.setattr(builder,'support',lambda:helper)
    def fail(_):raise ValueError('UNIT no actual source evidence')
    monkeypatch.setattr(builder.view,'validate_source',fail)
    monkeypatch.setattr(builder,'ResourceLibreOfficeEngine',lambda *_a,**_k:pytest.fail('UNIT must not start LO'))
    with pytest.raises(ValueError,match='UNIT no actual'):builder.prepare(source,output)
    failure=helper.read(output/'preparation_failure.json')
    assert failure['new_LO_calls']==failure['model_calls']==failure['task_count']==0
    assert failure['qualified'] is False and not list(output.rglob('*.xlsx'))


def test_prepare_cli_does_not_execute_without_explicit_run(monkeypatch,tmp_path):
    calls=[]
    monkeypatch.setattr(builder,'prepare',lambda *a:calls.append(('prepare',a)) or {'UNIT':True})
    monkeypatch.setattr(builder,'execute_prepared',lambda *a,**k:pytest.fail('No explicit --run'))
    builder.main(['--source-manifest','UNIT.json','--output',str(tmp_path/'UNIT-out')])
    assert len(calls)==1 and calls[0][0]=='prepare'


def test_one_command_run_prepares_then_executes(monkeypatch,tmp_path):
    calls=[]
    monkeypatch.setattr(builder,'prepare',lambda *a:calls.append('prepare') or {'UNIT':True})
    monkeypatch.setattr(builder,'execute_prepared',lambda *a,**k:calls.append('execute') or {'UNIT':True})
    builder.main(['--source-manifest','UNIT.json','--output',str(tmp_path/'UNIT-out'),'--run'])
    assert calls==['prepare','execute']


def test_prepared_cli_cannot_change_source_or_output(tmp_path):
    with pytest.raises(ValueError,match='frozen source'):
        builder.main(['--prepared',str(tmp_path),'--source-manifest','different.json'])


def test_declared_budget_and_pending_gates_do_not_claim_quality():
    assert builder.BUDGET['tool_budget_seconds']==1800
    assert builder.BUDGET['elapsed_guard_seconds']==14400
    assert builder.CONTROL_REWARDS=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}
    assert 'actual_Harbor_oracle_nop' in builder.PENDING
    assert 'all_twelve_quality_checks' in builder.PENDING

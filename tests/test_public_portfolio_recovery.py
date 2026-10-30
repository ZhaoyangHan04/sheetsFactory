"""Public portfolio replay tests with independent assessor-only expectations."""
import ast
from copy import deepcopy
from decimal import Decimal
from datetime import date, datetime
import json
from pathlib import Path
import subprocess
import sys

import openpyxl
import pytest
from test_recovery_witness_history import witness

from test_project_task_templates import build_project, _write_fixture_caches
from test_public_project_recovery import _expected
from sheets_factory.workbook.derived_gold.ledger import simulate
from sheets_factory.workbook.derived_gold.portfolio_public_recovery import compile_public_portfolio_recovery


POLICY = (
    'The subsidiaries are each owned 100%, with no intercompany transactions and no additional parent balances. '
    'Tax attributes cannot be shared. Group monthly amounts sum independently posted entity amounts. '
    'Annual opening balances use January; annual closing balances use December. Cash before allocation '
    'is the December snapshot, cash gap sums months. Owner values sum entity values.'
)


def _portfolio(source, destination, *, changed=True):
    public = openpyxl.load_workbook(source, data_only=True)
    date_row = next(c.row for row in public['Calendar'] for c in row if c.column == 1 and c.value == 'date')
    start_row = next(c.row for row in public['Scenario'] for c in row if c.column == 1 and c.value == 'start_date')
    start = public['Scenario'].cell(start_row, 2).value
    if isinstance(start, str):
        start = datetime.fromisoformat(start)
    dates = [datetime(start.year + (start.month - 1 + month) // 12,
                      (start.month - 1 + month) % 12 + 1, 1) for month in range(36)]
    book = openpyxl.Workbook()
    index = book.active
    index.title = 'Portfolio Index'
    index['A1'] = POLICY
    index.append(['Entity ID', 'Original sheet', 'Portfolio sheet'])
    for entity in ['T01', 'T02']:
        for original in public.sheetnames:
            full = entity + ' ' + original
            target = book.create_sheet(full)
            for row in public[original]:
                for cell in row:
                    if cell.value is not None:
                        target.cell(cell.row, cell.column, cell.value)
            index.append([entity, original, full])
        # The generic cache fixture intentionally omits date-formula caches.
        # Supply this test's public dates explicitly; production rejects absent
        # date caches rather than guessing them.
        for month, value in enumerate(dates, 3):
            book[entity + ' Calendar'].cell(date_row, month, value)
        if changed and entity == 'T02':
            sheet = book[entity + ' Scenario']
            row = next(c.row for cells in sheet for c in cells if c.column == 1 and c.value == 'steady_annual_sales')
            sheet.cell(row, 2, 45000000)
    group = book.create_sheet('Group Statements')
    for column in range(3, 39):
        group.cell(1, column, dates[column - 3])
    for row, label in enumerate(['sales', 'cash close', 'dta close', 'group balance check',
            'group cfo check', 'group operating cash check', 'group total cash check',
            'group reserve check', 'group retained check', 'group income check'], 3):
        group.cell(row, 1, label)
        for column in range(3, 39):
            group.cell(row, column, '=999')
    annual = book.create_sheet('Group Summary')
    for row, label in enumerate(['sales', 'cash open', 'cash close', 'cash before allocation',
            'cash gap', 'nol close', 'equity npv', 'initial owner equity', 'loan a payment'], 21):
        annual.cell(row, 1, label)
        for column in range(3, 6):
            annual.cell(row, column, '=999')
    book.properties.title = 'Public portfolio metadata'
    book.save(destination)
    book.close()
    public.close()
    return destination


def _run(source, folder):
    folder.mkdir()
    public = folder / 'input.xlsx'
    public.write_bytes(source.read_bytes())
    output = folder / 'output.xlsx'
    code = compile_public_portfolio_recovery().replace('"/workspace/input.xlsx"', repr(str(public)))
    code = code.replace('"/workspace/output.xlsx"', repr(str(output)))
    program = folder / 'replay.py'
    program.write_text(code)
    # Only the supplied workbook and files created by this replay may be read.
    # Neither an assessor goal nor a source seed is visible to the subprocess.
    driver = folder / 'driver.py'
    driver.write_text('import pathlib,runpy,sys,json\n'
        + 'root=pathlib.Path(' + repr(str(folder)) + ').resolve()\n'
        + 'allowed={' + repr(str(public)) + '}\nreads=[]\n'
        + "def check(event,args):\n"
        + " if event=='open' and isinstance(args[0],str) and args[0].endswith('.xlsx'):\n"
        + "  path=str(pathlib.Path(args[0]).resolve()); mode=args[1]\n"
        + "  if not isinstance(mode,str): return\n"
        + "  if mode.startswith(('w','a','x')):\n"
        + "   if not pathlib.Path(path).is_relative_to(root): raise RuntimeError('External write')\n"
        + "   allowed.add(path)\n"
        + "  elif mode.startswith('r'):\n"
        + "   if path not in allowed: raise RuntimeError('Private workbook access: '+path)\n"
        + "   reads.append(path)\n"
        + "sys.addaudithook(check)\nrunpy.run_path(" + repr(str(program)) + ",run_name='__main__')\n"
        + 'print(json.dumps(reads))\n')
    result = subprocess.run([sys.executable, '-I', str(driver)], cwd=folder,
                            capture_output=True, text=True, timeout=45)
    return result, output


def test_portfolio_program_has_no_private_imports_answers_or_numerical_defaults():
    program = compile_public_portfolio_recovery()
    tree = ast.parse(program)
    defaults = next(n for n in tree.body if isinstance(n, ast.AnnAssign)
                    and isinstance(n.target, ast.Name) and n.target.id == '_DEFAULTS')
    assert all(isinstance(v, ast.Constant) and v.value is None for v in defaults.value.values)
    assert all('sheets_factory' not in (getattr(n, 'module', '') or '') for n in ast.walk(tree))
    assert 'goal.xlsx' not in program and 'scenario.json' not in program and 'emit_workbook' not in program


def test_public_only_portfolio_recovery_respects_each_entity_and_group_timing(build_project, tmp_path):
    source = build_project('v7')
    spec, _, checks = _expected(source)
    _write_fixture_caches(source, checks)
    path = _portfolio(source, tmp_path / 'portfolio.xlsx')
    original = openpyxl.load_workbook(path)
    protected = {name: {c.coordinate: c.value for row in original[name] for c in row}
                 for name in original.sheetnames if name.endswith((' Scenario', ' Source Inputs', ' Calendar', ' Read Me'))}
    order = original.sheetnames
    original.close()
    result, output = _run(path, tmp_path / 'only_public_workspace')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)
    actual = openpyxl.load_workbook(output, data_only=True)
    other = deepcopy(spec)
    other['parameters']['steady_annual_sales'] = '45000000'
    ledgers = [simulate(spec), simulate(other)]  # Assessor-only, outside replay.
    for month in [0, 11, 12, 35]:
        assert actual['Group Statements'].cell(3, month + 3).value == pytest.approx(float(sum(
            (r['monthly'][month]['sales'] for r in ledgers), Decimal(0))))
        assert actual['Group Statements'].cell(5, month + 3).value == pytest.approx(float(sum(
            (r['monthly'][month]['dta_close'] for r in ledgers), Decimal(0))))
        assert all(actual['Group Statements'].cell(row, month + 3).value == 0 for row in range(6, 13))
    assert actual['Group Summary']['C22'].value == float(sum((r['monthly'][0]['cash_open'] for r in ledgers), Decimal(0)))
    assert actual['Group Summary']['C24'].value == pytest.approx(float(sum(
        (r['monthly'][11]['cash_before_allocation'] for r in ledgers), Decimal(0))))
    assert actual['Group Summary']['C27'].value == pytest.approx(float(sum(
        (r['valuation']['equity_npv'] for r in ledgers), Decimal(0))))
    assert actual['Group Summary']['C29'].value == pytest.approx(float(sum(
        (r['valuation']['loan_a_payment'] for r in ledgers), Decimal(0))))
    assert actual.sheetnames == order and actual.properties.title == 'Public portfolio metadata'
    for name, cells in protected.items():
        assert {c.coordinate: c.value for row in actual[name] for c in row} == cells


@pytest.mark.parametrize('defect', ['missing_assumption', 'missing_group_policy', 'bad_mapping', 'calendar_mismatch'])
def test_missing_public_evidence_fails_closed_without_defaults(build_project, tmp_path, defect):
    source = build_project('v7')
    _, _, checks = _expected(source)
    _write_fixture_caches(source, checks)
    path = _portfolio(source, tmp_path / 'portfolio.xlsx')
    book = openpyxl.load_workbook(path)
    if defect == 'missing_assumption':
        sheet = book['T02 Scenario']
        row = next(c.row for cells in sheet for c in cells if c.column == 1 and c.value == 'steady_annual_sales')
        sheet.cell(row, 2).value = None
    elif defect == 'missing_group_policy':
        book['Portfolio Index']['A1'] = 'No consolidation policy supplied.'
    elif defect == 'bad_mapping':
        book['Portfolio Index']['C3'] = 'T01 Scenario'
    else:
        book['T02 Calendar']['C3'] = None
    book.save(path)
    book.close()
    result, output = _run(path, tmp_path / 'rejected_replay')
    assert result.returncode != 0 and not output.exists()


def test_portfolio_backend_routes_without_a_model_call_and_records_programmatic_usage(witness, monkeypatch):
    from sheets_factory.nodes.quality import RecoveryNode
    from test_recovery_witness_history import PROGRAM
    calls = []
    def compiler():
        calls.append('portfolio')
        return PROGRAM
    monkeypatch.setattr('sheets_factory.workbook.derived_gold.portfolio_public_recovery.compile_public_portfolio_recovery', compiler)
    witness.ctx.config['recovery'] = {'compiler_backend': 'portfolio_journal'}
    witness.ctx.data['finance_evidence'] = {'financial_seed_verified': True}
    result = RecoveryNode().execute(witness.ctx)['recovery']
    assert calls == ['portfolio'] and witness.backend.calls == []
    assert result['verified'] is True and result['compiler_backend'] == 'portfolio_journal'
    assert result['compiler']['implementation'] == 'independent_decimal_portfolio_journals'
    assert result['compiler']['is_llm_attempt'] is False
    assert result['usage_attribution'] == 'not_applicable_programmatic'


def test_portfolio_backend_requires_actual_financial_source_evidence_before_compilation(witness):
    from sheets_factory.nodes.quality import RecoveryNode
    from sheets_factory.core.node import TaskRejected
    witness.ctx.config['recovery'] = {'compiler_backend': 'portfolio_journal'}
    with pytest.raises(TaskRejected, match='verified financial source'):
        RecoveryNode().execute(witness.ctx)
    assert witness.backend.calls == [] and witness.replay.calls == []

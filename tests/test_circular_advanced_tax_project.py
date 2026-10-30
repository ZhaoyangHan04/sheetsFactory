"""Coupled tax-vintage/underwriting proof; offline fixtures are not LO evidence."""
from copy import deepcopy
from decimal import Decimal as D
import json
import openpyxl
import pytest

from test_circular_debt_project import contract as simple_cyclic_contract
from sheets_factory.workbook.derived_gold.spec import resolve_spec
from sheets_factory.workbook.derived_gold.ledger import simulate
from sheets_factory.workbook.derived_gold.excel import emit_workbook
from sheets_factory.workbook.derived_gold.presentation import project_business_brief
from sheets_factory.workbook.derived_gold.validate import audit_workbook,ledger_invariants_pass

TAX={'advanced_tax_enabled':1,'initial_tax_rate_y1':'.50','initial_tax_rate_y2':'.30',
     'initial_tax_rate_y3':'.20','refresh_tax_rate_y1':'.60','refresh_tax_rate_y2':'.30',
     'refresh_tax_rate_y3':'.10','interest_deduction_ebitda_fraction':'.30','nol_carryforward_years':1}

@pytest.fixture
def combined(simple_cyclic_contract,tmp_path):
    _, recipe, path=simple_cyclic_contract
    recipe=deepcopy(recipe);recipe['advanced_tax_parameters']=deepcopy(TAX)
    path.write_text(json.dumps(recipe))
    return resolve_spec(tmp_path,path),path,recipe


def test_combined_finite_grid_has_one_feasible_interior_solution_and_full_vintage_witnesses(combined):
    spec=combined[0];report=simulate(spec);proof=report['cyclic_financing_proof'];sizing=report['debt_sizing']
    assert spec['public_contract_version']==9
    assert proof['grid_points_checked']==14001
    assert proof['fixed_points']==[D('11599000')]
    assert sizing['sized_principal']==D('11599000')
    assert sizing['debt_capacity']==D('11599406.53')
    assert proof['mapping_monotone'] and proof['all_tranches_feasible'] and proof['principal_interior']
    assert all(path[-1]==sizing['sized_principal'] for path in proof['endpoint_paths'])
    assert proof['projection_full_journal_comparisons']==5
    assert proof['projection_tax_vintage_records_compared']==15
    assert proof['adjacent_tranche_year3_cash_tax_response']==D('74.80')
    assert proof['adjacent_tranche_year3_cfads_response']==D('74.80')
    assert ledger_invariants_pass(report['checks'])


def test_book_deferred_tax_is_not_cash_tax_or_financing_capacity(combined):
    report=simulate(combined[0]);annual=report['tax_annual'];sizing=report['debt_sizing']
    assert annual[0]['current_tax']==0 and annual[0]['book_tax']<0
    assert annual[0]['interest_cf_close']>0 and annual[1]['interest_cf_used']>0
    assert annual[1]['interest_cf_close']==0
    assert annual[2]['nol_v1_expired']>0 and annual[2]['nol_v2_used']>0
    assert annual[0]['deferred_tax_expense']<0<annual[2]['deferred_tax_expense']
    assert sizing['year3_cash_tax']==annual[2]['current_tax']==D('732309.34')
    assert sizing['year3_cash_tax']!=annual[2]['book_tax']
    assert sizing['year3_cfads']==sum((row['cfo_direct']+row['interest']-row['capex']
                                      for row in report['monthly'][24:]),D(0))
    assert all(row['cfo_indirect']==row['cfo_direct'] and row['balance_check']==0 for row in report['monthly'])
    for year in report['annual']:
        assert year['tax']==year['current_tax']+year['deferred_tax_expense']


def test_disabling_advanced_tax_preserves_exact_existing_simple_cyclic_report(combined,simple_cyclic_contract):
    spec=deepcopy(combined[0]);spec['advanced_tax_parameters']['advanced_tax_enabled']=0
    assert simulate(spec)==simulate(simple_cyclic_contract[0])


def test_combined_emitter_binds_every_formula_and_exposes_the_existing_public_contracts(combined,tmp_path):
    spec=project_business_brief(combined[0]);path=tmp_path/'combined_unrecalculated.xlsx'
    metadata=emit_workbook(spec,path);report=simulate(spec);audit=audit_workbook(path,spec,report,metadata)
    assert not audit['passed']  # No real LibreOffice has been invoked here.
    assert audit['all_formula_cells_independently_covered']
    assert not audit['uncovered_formulas'] and audit['all_ledger_invariants_passed']
    assert len(spec['public_rules'])==10
    assert len(' '.join(spec['public_rules']).split())<=600
    book=openpyxl.load_workbook(path)
    assert 'Tax Vintages' in book and 'DebtSizing' in book
    assert "'Tax'!AA7:AL7" in book['DebtSizing']['B10'].value
    assert book.calculation.iterate is True
    book.close()


def test_optional_sweep_or_covenant_feedback_is_still_rejected(combined):
    spec=deepcopy(combined[0]);spec['parameters']['cash_sweep_fraction']='.1'
    with pytest.raises(ValueError,match='no covenant/sweep'):
        simulate(spec)

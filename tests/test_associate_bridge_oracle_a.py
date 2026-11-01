from copy import deepcopy
from fractions import Fraction as F
import importlib.util
from pathlib import Path
import pytest
from sheets_factory.workbook.associate_bridge_v1 import spec,oracle_a as a
from sheets_factory.workbook.operating_reports_200 import schema as old
from sheets_factory.workbook.operating_reports_200 import oracle_a as baseline

fixture_spec=importlib.util.spec_from_file_location('_associate_A_raw_fixture',Path(__file__).with_name('test_associate_bridge_spec.py'))
fixture=importlib.util.module_from_spec(fixture_spec);fixture_spec.loader.exec_module(fixture)


def value(result,key):return F(result['economic_exact_values'][key]['value'])


def test_equity_exempt_decode_cash_and_investment_hand_ledger():
    public=spec.build(fixture.toy(),'B01');r=a.solve(public);p='E001/2026Q1/'
    expected={'current_tax':'43/4','core_net_income':'129/4','associate_income':'5','net_income':'149/4',
      'operating_cash_flow':'329/4','closing_cash':'40875/4','closing_investment':'955',
      'closing_retained_earnings':'4295/4','total_assets':'44695/4','total_liabilities_equity':'44695/4'}
    for field,expected_value in expected.items():assert value(r,p+field)==F(expected_value),(field,value(r,p+field))
    assert public['policies']['E001']['share_postings']['2026Q1']=='-5'
    assert r['reconciliation_checks']['passed']


def test_all_three_tax_classes_and_cost_method_hand_values():
    r=a.solve(spec.build(fixture.toy(),'B03'))
    # E001 equity/cash-dividend tax; E002 cost/exempt; E003 equity/recognized tax.
    assert value(r,'E001/2026Q1/current_tax')==F('93/4')
    assert value(r,'E001/2026Q1/net_income')==F('99/4')
    assert value(r,'E002/2026Q1/associate_income')==50
    assert value(r,'E002/2026Q1/net_income')==F('329/4')
    assert value(r,'E002/2026Q1/closing_investment')==1000
    assert value(r,'E003/2026Q1/current_tax')==12
    assert value(r,'E003/2026Q1/net_income')==36
    assert value(r,'E003/2026Q2/current_tax')==F('91/8')  # negative share reduces taxable profit


def test_cost_capital_return_is_cash_not_income_and_reduces_investment():
    p=spec.build(fixture.toy(),'B05');assert p['policies']['E002']['receipt_kind']['2026Q1']=='capital_return'
    r=a.solve(p)
    assert value(r,'E002/2026Q1/associate_income')==0
    assert value(r,'E002/2026Q1/net_income')==F('129/4')
    assert value(r,'E002/2026Q1/operating_cash_flow')==F('329/4')
    assert value(r,'E002/2026Q1/closing_investment')==950


def test_owner_distribution_recalculates_new_annual_profit_and_all_groups():
    base=fixture.toy();prior=baseline.solve(base);r=a.solve(spec.build(base,'B02'))
    assert value(r,'E001/FY2027/dividend')-value(prior,'E001/FY2027/dividend')==F('38.6')
    for period in (*old.QUARTERS,'FY2025','FY2026','FY2027'):
        for field in ('net_income','current_tax','closing_cash','closing_investment','closing_retained_earnings','total_assets'):
            total=sum(value(r,f'E{i:03d}/{period}/{field}')for i in range(1,4))
            assert value(r,f'DIV_ADVISORY/{period}/{field}')==total
            assert value(r,f'PORTFOLIO/{period}/{field}')==total


def test_no_tax_refund_on_negative_taxable_base_and_negative_results():
    base=fixture.toy();
    for e in base['entities']:
        scale=spec.MONEY_SCALES[e['money_unit']]
        e['cash_opex']={q:spec._text(F(100,scale))for q in old.QUARTERS}
    r=a.solve(spec.build(base,'B03'))
    assert value(r,'E003/2026Q1/current_tax')==0
    assert r['reconciliation_checks']['passed']


@pytest.mark.parametrize('case_id',spec.CASE_IDS)
def test_complete_shape_units_reconciliation_and_unchanged_sales_cagr(case_id):
    base=fixture.toy();before=deepcopy(base);public=spec.build(base,case_id);prior=baseline.solve(base);r=a.solve(public)
    assert base==before and r['kind']==spec.RESULT_KIND and r['specification_sha256']==spec.canonical_sha256(public)
    assert set(r)==set(prior)
    for name in ('economic_exact_values','raw_cell_exact_values','typed_2dp_values'):
        assert set(r[name])==set(prior[name])==set(dict(old.points(base)))
        for key in prior[name]:
            if key.split('/')[-1]in('revenue','yoy_percent','qoq_percent','cagr_percent','distribution_eligible'):
                assert r[name][key]==prior[name][key]
    assert r['cagr_proofs']==prior['cagr_proofs'] and r['reconciliation_checks']['passed']
    assert r['typed_2dp_values']['E003/2026Q1/associate_income']['type']=='number'

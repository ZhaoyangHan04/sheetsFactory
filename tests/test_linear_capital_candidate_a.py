"""Hand-audited small forward A fixtures; no B, optimization, LO or models."""
from copy import deepcopy
from fractions import Fraction
import ast
from pathlib import Path

import pytest

from sheets_factory.workbook.linear_capital_portfolio import candidate_a as a
from sheets_factory.workbook.linear_capital_portfolio.spec import (
    ANNUAL_FIELDS, GROUP_FIELDS, EXACT_LIMIT, load_spec)


def toy(*, years=3, projects=1, scenarios=1):
    periods=list(range(1,years+1));keys=list(map(str,periods))
    ids=[f'P{i:03d}' for i in range(1,projects+1)]
    sids=[f'S{i:02d}' for i in range(1,scenarios+1)]
    annual=lambda value:{key:value for key in keys}
    stressed=lambda value:{sid:annual(value) for sid in sids}
    public={'version':1,'kind':'hypothetical_ringfenced_linear_capital_portfolio',
        'dimension_mode':'toy','fiscal_year_start':2027,'years':periods,'project_ids':ids,
        'scenario_ids':sids,'resource_ids':['U01'],'region_ids':['R01'],'sector_ids':['C01'],
        'projects':[],'scenarios':[],'exclusivity_groups':[],'prerequisites':[],
        'shared_limits':{'initial_sponsor_equity_pence':10**12,
            'annual_new_lp_pence':stressed(10**12),'annual_debt_close_pence':stressed(10**12),
            'resource_capacity_units':{'U01':stressed(10**9)},
            'region_exposure_pence':{'R01':annual(10**12)},'sector_exposure_pence':{'C01':annual(10**12)}},
        'provenance':{'hypothetical':True,'description':'Small independent hand-test fixture','ancestor_sha256':[]}}
    for pid in ids:
        public['projects'].append({'id':pid,'name':'Hand fixture '+pid,'region':'R01','sector':'C01',
            'asset_cost_pence':100,'t0_ltv_bp':0,'operating_start_year':1,'depreciation_years':years,
            'base_annual_revenue_pence':0,'base_annual_opex_pence':0,
            'revenue_growth_factor_bp':10000,'opex_growth_factor_bp':10000,
            'bank_rate_bp':0,'debt_policy':'BULLET','debt_maturity_year':years,
            'tax_rate_bp':0,'discount_rate_bp':0,'terminal_sale_proceeds_pence':0,
            'lp_commitment_pence':10000,'resource_usage_units':{'U01':stressed(1)}})
    for sid in sids:
        public['scenarios'].append({'id':sid,'name':'Hand scenario '+sid,
            'revenue_factors_bp':annual(10000),'opex_factors_bp':annual(10000),
            'sale_factors_bp':annual(10000),'interest_spread_bp':annual(0)})
    return load_spec(public)


def forward(public):return a.simulate_project(public,'P001','S01')


def bridges(result):
    assert result['t0']['balance_check']==0
    for row in result['annual']:
        assert set(ANNUAL_FIELDS)<=row.keys()
        assert all(type(row[field]) is int for field in ANNUAL_FIELDS)
        assert all(row[name]==0 for name in ('balance_check','cash_check','asset_check','debt_check','loss_check'))
    assert result['arithmetic_safety']['passed']


@pytest.mark.parametrize('value,expected',[
    (Fraction(1,2),1),(Fraction(-1,2),-1),(Fraction(3,2),2),(Fraction(-3,2),-2),
    (Fraction(4999999999999999,10**16),0),(Fraction(-4999999999999999,10**16),0)])
def test_exact_half_away_rounding(value,expected):assert a._round(value)==expected


def test_t0_and_level_principal_rounding_maturity_and_opening_interest():
    s=toy();p=s['projects'][0]
    p.update(asset_cost_pence=101,t0_ltv_bp=5000,bank_rate_bp=1000,
        debt_policy='LEVEL_PRINCIPAL',debt_maturity_year=2)
    r=forward(s)
    assert r['t0']['bank_draw']==51 and r['t0']['lp_call']==50
    assert [y['debt_open'] for y in r['annual']]==[51,25,0]
    assert [y['principal_repayment'] for y in r['annual']]==[26,25,0]
    assert [y['bank_interest'] for y in r['annual']]==[5,3,0]
    assert [y['lp_call'] for y in r['annual']]==[31,28,0]
    assert r['annual'][-1]['lp_called_cumulative']==109 and r['feasible']
    bridges(r)


def test_bullet_interest_before_maturity_and_scenario_rate_spread():
    s=toy(scenarios=2);s['projects'][0].update(asset_cost_pence=101,t0_ltv_bp=5000,
        bank_rate_bp=1000,debt_maturity_year=2)
    s['scenarios'][1]['interest_spread_bp']={str(y):-500 for y in s['years']}
    first=forward(s);second=a.simulate_project(s,'P001','S02')
    assert [y['bank_interest'] for y in first['annual']]==[5,5,0]
    assert [y['principal_repayment'] for y in first['annual']]==[0,51,0]
    assert [y['bank_interest'] for y in second['annual']]==[3,3,0]
    bridges(first);bridges(second)


def test_growth_is_posted_unshocked_and_shocks_do_not_compound():
    s=toy();s['projects'][0].update(asset_cost_pence=600,base_annual_revenue_pence=101,
        revenue_growth_factor_bp=10500)
    s['scenarios'][0]['revenue_factors_bp']={'1':5000,'2':15000,'3':10000}
    r=forward(s)
    assert [y['revenue_base'] for y in r['annual']]==[101,106,111]
    assert [y['revenue'] for y in r['annual']]==[51,159,111]
    bridges(r)


def test_first_operating_year_controls_revenue_and_depreciation_but_not_debt_interest():
    s=toy();s['projects'][0].update(operating_start_year=2,asset_cost_pence=101,
        depreciation_years=2,base_annual_revenue_pence=20,t0_ltv_bp=5000,bank_rate_bp=1000)
    r=forward(s)
    assert [y['operating_active'] for y in r['annual']]==[0,1,1]
    assert [y['revenue'] for y in r['annual']]==[0,20,20]
    assert [y['depreciation'] for y in r['annual']]==[0,51,50]
    assert r['annual'][0]['bank_interest']==5
    bridges(r)


def test_small_cost_depreciation_cap_prevents_negative_NBV():
    s=toy(years=4);s['projects'][0].update(asset_cost_pence=2,depreciation_years=4)
    r=forward(s)
    assert [y['depreciation'] for y in r['annual']]==[1,1,0,0]
    assert [y['asset_nbv_close'] for y in r['annual']]==[1,0,0,0]
    bridges(r)


def test_terminal_sale_uses_post_depreciation_carrying_and_taxes_disposal_gain():
    s=toy(years=2);s['projects'][0].update(depreciation_years=4,
        terminal_sale_proceeds_pence=150,tax_rate_bp=5000)
    r=forward(s);last=r['annual'][-1]
    assert last['depreciation']==25 and last['sale_carrying']==50 and last['sale_gain']==100
    # FY1 loss25 offsets25 of FY2 profit75: taxable50, tax25.
    assert last['taxable_before_losses']==75 and last['loss_used']==25
    assert last['taxable_after_losses']==50 and last['current_tax']==25
    assert last['lp_distribution']==125 and r['npv_pence']==25
    assert last['asset_nbv_close']==last['debt_close']==last['cash_close']==0
    bridges(r)


def test_three_year_loss_fifo_expiry_before_use_and_no_tax_DTA():
    s=toy(years=5);p=s['projects'][0]
    p.update(depreciation_years=20,base_annual_revenue_pence=100,base_annual_opex_pence=100,
        terminal_sale_proceeds_pence=75,tax_rate_bp=5000)
    s['scenarios'][0]['revenue_factors_bp']={'1':0,'2':0,'3':5000,'4':0,'5':15000}
    s['scenarios'][0]['opex_factors_bp']={'1':10000,'2':0,'3':0,'4':0,'5':0}
    r=forward(s);last=r['annual'][-1]
    assert r['annual'][0]['loss_created']==105 and r['annual'][0]['current_tax']==0
    assert r['annual'][2]['loss_used']==45
    assert last['loss_open']==70 and last['loss_expired']==60 and last['loss_used']==10
    assert last['taxable_after_losses']==135 and last['current_tax']==68
    old=[v for v in r['tax_vintages'] if v['year']==5]
    assert [(v['origin_year'],v['expired'],v['used']) for v in old]==[(1,60,0),(2,0,5),(4,0,5)]
    bridges(r)


def test_finite_total_commitment_keeps_negative_cash_and_persistent_infeasibility():
    s=toy(years=2);s['projects'][0].update(lp_commitment_pence=100,
        base_annual_revenue_pence=100,base_annual_opex_pence=100)
    s['scenarios'][0]['revenue_factors_bp']={'1':0,'2':15000}
    s['scenarios'][0]['opex_factors_bp']={'1':10000,'2':0}
    r=forward(s)
    assert r['t0']['lp_remaining']==0
    assert r['annual'][0]['lp_required']==100 and r['annual'][0]['lp_call']==0
    assert r['annual'][0]['funding_gap']==100 and r['annual'][0]['cash_close']==-100
    assert r['annual'][1]['cash_open']==-100 and r['annual'][1]['lp_distribution']==50
    assert r['annual'][1]['cash_close']==0 and r['annual'][1]['feasible']==0
    assert not r['feasible'] and r['npv_pence'] is None
    bridges(r)


def test_t0_shortfall_does_not_overcall_or_hide_a_candidate():
    s=toy();s['projects'][0]['lp_commitment_pence']=90
    r=forward(s)
    assert r['t0']['lp_required']==100 and r['t0']['lp_call']==90
    assert r['t0']['funding_gap']==10 and r['t0']['cash_close']==-10
    universe=a.simulate_universe(s)
    assert list(universe['projects'])==['P001'] and universe['all_standalone_feasible'] is False
    assert universe['optimization_performed'] is False and universe['source_or_difficulty_certified'] is False
    bridges(r)


def test_NPV_t0_is_inside_single_final_round_and_portfolio_sums_posted_values():
    s=toy(years=1,projects=2)
    for p in s['projects']:p.update(asset_cost_pence=3,terminal_sale_proceeds_pence=3,
        depreciation_years=20,discount_rate_bp=2000)
    r=forward(s)
    assert r['npv_exact']=={'numerator':'-1','denominator':'2'} and r['npv_pence']==-1
    portfolio=a.simulate(s,{'P001':1,'P002':1})
    assert portfolio['feasible'] and portfolio['objective_pence']==-2
    assert portfolio['objective_pence'] != a._round(Fraction(-1,2)+Fraction(-1,2))
    assert all(v['passed'] for v in portfolio['constraints'])


def test_positive_NPV_half_tie_is_rounded_away_from_zero():
    s=toy(years=1);s['projects'][0].update(asset_cost_pence=1,t0_ltv_bp=9000,
        terminal_sale_proceeds_pence=4,discount_rate_bp=2000)
    r=forward(s)
    assert r['t0']['lp_call']==0 and r['npv_exact']=={'numerator':'5','denominator':'2'}
    assert r['npv_pence']==3
    bridges(r)


def test_all_scenarios_are_retained_but_objective_is_only_S01():
    s=toy(years=1,scenarios=3);s['projects'][0].update(base_annual_revenue_pence=100,
        terminal_sale_proceeds_pence=100)
    s['scenarios'][1]['revenue_factors_bp']['1']=5000
    s['scenarios'][2]['revenue_factors_bp']['1']=0
    r=a.simulate(s,{'P001':1})
    scenario_npvs={sid:r['projects']['P001']['scenarios'][sid]['npv_pence'] for sid in s['scenario_ids']}
    assert scenario_npvs=={'S01':100,'S02':50,'S03':0}
    assert r['objective_pence']==100 and r['all_standalone_feasible']
    for sid in s['scenario_ids']:assert set(GROUP_FIELDS)<=r['group']['scenarios'][sid]['annual'][0].keys()


@pytest.mark.parametrize('family',['initial_sponsor_equity','annual_new_lp','annual_debt_close','resource','region_exposure','sector_exposure','exclusivity','prerequisite'])
def test_each_shared_constraint_is_evaluated_without_search(family):
    s=toy(years=2,projects=2);plan={'P001':1,'P002':1}
    if family=='initial_sponsor_equity':s['shared_limits']['initial_sponsor_equity_pence']=199
    elif family=='annual_new_lp':
        s['projects'][0]['base_annual_opex_pence']=5
        s['shared_limits']['annual_new_lp_pence']['S01']['1']=4
    elif family=='annual_debt_close':
        s['projects'][0]['t0_ltv_bp']=5000
        s['shared_limits']['annual_debt_close_pence']['S01']['1']=49
    elif family=='resource':s['shared_limits']['resource_capacity_units']['U01']['S01']['1']=1
    elif family=='region_exposure':s['shared_limits']['region_exposure_pence']['R01']['1']=99
    elif family=='sector_exposure':s['shared_limits']['sector_exposure_pence']['C01']['1']=99
    elif family=='exclusivity':s['exclusivity_groups']=[{'id':'site','description':'Two alternative uses of one site','project_ids':['P001','P002']}]
    else:
        plan={'P001':0,'P002':1}
        s['prerequisites']=[{'id':'dependency','dependent':'P002','prerequisite':'P001','business_reason':'P002 requires the shared access asset P001'}]
    result=a.simulate(s,plan)
    assert not result['feasible'] and result['objective_pence'] is None
    assert any(c['family']==family and not c['passed'] for c in result['constraints'])
    assert all(c['slack']==c['limit']-c['lhs'] and c['passed']==(c['lhs']<=c['limit']) for c in result['constraints'])


@pytest.mark.parametrize('operation',[lambda c:c.integer(EXACT_LIMIT),
    lambda c:c.add(EXACT_LIMIT-1,1,-1),lambda c:c.factor(2**51,4)])
def test_integer_safety_rejects_large_intermediates_even_if_final_value_would_fit(operation):
    with pytest.raises(ValueError,match='exact arithmetic domain'):operation(a._IntegerScope())


def test_raw_and_plan_tampering_rejected_and_inputs_unchanged():
    s=toy();before=deepcopy(s)
    a.simulate(s,{'P001':1})
    assert s==before
    bad=deepcopy(s);bad['projects'][0]['t0_ltv_bp']=True
    with pytest.raises(ValueError):forward(bad)
    for plan in ({'P001':True},{'P001':2},{}, {'P001':1,'P999':0}):
        with pytest.raises(ValueError):a.simulate(s,plan)
    with pytest.raises(ValueError):a.simulate_project(s,'P002','S01')


def test_A_shares_schema_only_and_has_no_B_ledger_or_Decimal_dependency():
    tree=ast.parse(Path(a.__file__).read_text())
    relative=[node for node in ast.walk(tree) if isinstance(node,ast.ImportFrom) and node.level]
    assert len(relative)==1 and relative[0].module=='spec'
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):assert all('decimal' not in name.name.lower() and 'ledger' not in name.name.lower() for name in node.names)
        if isinstance(node,ast.ImportFrom):assert 'decimal' not in (node.module or '').lower() and 'ledger' not in (node.module or '').lower()

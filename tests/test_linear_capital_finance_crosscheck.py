"""Complete small financial comparisons; no production finance, optimizer or LO."""
from copy import deepcopy
from itertools import product

import pytest

from sheets_factory.workbook.linear_capital_portfolio import candidate_a,ledger,finance_crosscheck as check
from test_linear_capital_candidate_a import toy


def universes(s):return candidate_a.simulate_universe(s),ledger.simulate_universe(s)


def test_crosscheck_calls_each_forward_exactly_once_and_reports_stages(monkeypatch):
    s=toy(years=3,projects=2,scenarios=2);calls={'A':0,'B':0};events=[]
    original_a,original_b=candidate_a.simulate_universe,ledger.simulate_universe
    def a(spec):calls['A']+=1;return original_a(spec)
    def b(spec):calls['B']+=1;return original_b(spec)
    monkeypatch.setattr(candidate_a,'simulate_universe',a);monkeypatch.setattr(ledger,'simulate_universe',b)
    plans=[{'id':str(bits),'plan':dict(zip(s['project_ids'],bits))} for bits in product((0,1),repeat=2)]
    report=check.crosscheck(s,plans,progress=lambda name,detail:events.append((name,detail)))
    assert report['passed'] is True and calls=={'A':1,'B':1}
    assert [name for name,_ in events]==['A_started','A_completed','B_started','B_completed','universe_compared','plans_compared']
    assert report['universe_comparison']['counts']['project_scenarios']==4
    assert report['plan_comparison']['plan_count']==4 and report['plan_comparison']['additional_financial_forwards']==0
    assert report['optimization_performed'] is False and report['source_or_difficulty_certified'] is False


@pytest.mark.parametrize('case',['base','growth','loss_fifo','level_debt','terminal','negative_cash'])
def test_common_T0_annual_vintage_NPV_fields_are_complete(case):
    s=toy(years=5,scenarios=2);p=s['projects'][0]
    if case=='growth':p.update(base_annual_revenue_pence=31,revenue_growth_factor_bp=10500)
    elif case=='loss_fifo':
        p.update(base_annual_revenue_pence=100,base_annual_opex_pence=100,depreciation_years=20,
            terminal_sale_proceeds_pence=75,tax_rate_bp=5000)
        for scenario in s['scenarios']:
            scenario['revenue_factors_bp']={'1':0,'2':0,'3':5000,'4':0,'5':15000}
            scenario['opex_factors_bp']={'1':10000,'2':0,'3':0,'4':0,'5':0}
    elif case=='level_debt':p.update(asset_cost_pence=101,t0_ltv_bp=5000,bank_rate_bp=1000,debt_policy='LEVEL_PRINCIPAL',debt_maturity_year=2)
    elif case=='terminal':p.update(depreciation_years=20,terminal_sale_proceeds_pence=150,tax_rate_bp=5000)
    elif case=='negative_cash':p.update(lp_commitment_pence=0,base_annual_opex_pence=10)
    a,b=universes(s);report=check.compare_universes(s,a,b)
    assert report['differences']==[]
    assert report['passed'] is (case!='negative_cash')
    assert report['counts']['vintage_fields']==2*15*5
    assert report['counts']['t0_fields']==2*11
    assert report['counts']['annual_fields']==2*5*(len(check.ANNUAL_FIELDS)+2)
    if case=='negative_cash':assert len(report['infeasible_candidates'])==4
    else:assert report['schema_issues']==[]


def test_unrounded_and_implementation_metadata_are_not_misreported_as_financial_differences():
    s=toy();a,b=universes(s)
    a['financial_implementation']='A metadata is intentionally unlike B'
    b['projects']['P001']['scenarios']['S01']['npv_unrounded_decimal']='different display precision'
    a['projects']['P001']['scenarios']['S01']['npv_exact']={'numerator':'display metadata not compared','denominator':'1'}
    assert check.compare_universes(s,a,b)['passed']


@pytest.mark.parametrize('change',['T0','annual','FIFO','NPV','bool_money','duplicate_annual','duplicate_vintage','missing_project','bounds','terminal'])
def test_any_financial_or_typed_scope_tamper_is_retained_and_fails(change):
    s=toy();s['projects'][0]['base_annual_opex_pence']=5
    a,b=universes(s);r=b['projects']['P001']['scenarios']['S01']
    if change=='T0':r['t0']['lp_call']+=1
    elif change=='annual':r['annual'][0]['revenue']+=1
    elif change=='FIFO':r['tax_vintages'][0]['created']+=1
    elif change=='NPV':r['npv_pence']+=1
    elif change=='bool_money':r['annual'][0]['cash_close']=False
    elif change=='duplicate_annual':r['annual'].append(deepcopy(r['annual'][0]))
    elif change=='duplicate_vintage':r['tax_vintages'].append(deepcopy(r['tax_vintages'][0]))
    elif change=='missing_project':b['projects'].pop('P001')
    elif change=='bounds':r['arithmetic_bounds']['all_postings_products_and_sums_below_2_to_53']=False
    else:
        a['projects']['P001']['scenarios']['S01']['annual'][-1]['asset_nbv_close']=1
        r['annual'][-1]['asset_nbv_close']=1
    report=check.compare_universes(s,a,b)
    assert report['passed'] is False and report['differences_truncated'] is False
    assert report['differences'] or report['schema_issues']


def test_sparse_vintage_order_and_explicit_zero_origin_preserve_complete_grid_semantics():
    s=toy();s['projects'][0]['base_annual_opex_pence']=5
    a,b=universes(s);r=b['projects']['P001']['scenarios']['S01']
    r['tax_vintages'].reverse()
    assert check.compare_universes(s,a,b)['passed']
    # Remove a nonzero origin: the omitted values are compared against zero,
    # not silently removed by intersecting the two sparse record sets.
    r['tax_vintages'].pop()
    report=check.compare_universes(s,a,b)
    assert not report['passed'] and any('/tax_vintages/' in d['path'] for d in report['differences'])


def test_all_differences_retained_without_a_five_example_cap():
    s=toy(years=5,scenarios=2);a,b=universes(s)
    for sid in s['scenario_ids']:
        for row in b['projects']['P001']['scenarios'][sid]['annual']:row['revenue']+=1
    report=check.compare_universes(s,a,b)
    assert len(report['differences'])==10 and not report['passed']


def test_two_plan_aggregation_paths_match_their_own_original_simulate_without_reposting_in_comparison(monkeypatch):
    s=toy(years=3,projects=2,scenarios=2)
    s['projects'][0].update(t0_ltv_bp=5000,bank_rate_bp=1000,base_annual_opex_pence=8)
    s['projects'][1].update(base_annual_revenue_pence=75,terminal_sale_proceeds_pence=100)
    s['exclusivity_groups']=[{'id':'site','description':'Alternative installations','project_ids':['P001','P002']}]
    s['prerequisites']=[{'id':'access','dependent':'P002','prerequisite':'P001','business_reason':'Shared access asset'}]
    a,b=universes(s);plans=[]
    for bits in product((0,1),repeat=2):
        plan=dict(zip(s['project_ids'],bits));plans.append({'id':str(bits),'plan':plan})
        for u,aggregate,original in ((a,check._aggregate_a,candidate_a.simulate),(b,check._aggregate_b,ledger.simulate)):
            summed=aggregate(s,u,plan);full=original(s,plan)
            assert summed['group']==full['group']
            assert summed['objective_pence']==full['objective_pence'] and summed['feasible']==full['feasible']
            assert {r['id']:r for r in summed['constraints']}=={r['id']:r for r in full['constraints']}
    monkeypatch.setattr(candidate_a,'simulate_universe',lambda *_:pytest.fail('Unexpected extra A forward'))
    monkeypatch.setattr(ledger,'simulate_universe',lambda *_:pytest.fail('Unexpected extra B forward'))
    report=check.compare_plans(s,a,b,plans)
    assert report['passed'] and report['plan_count']==4
    assert any(not p['A']['feasible'] for p in report['plans'])
    assert report['third_financial_implementation_claimed'] is False
    required=check.compare_plans(s,a,b,plans,require_feasible=True)
    assert not required['passed'] and required['plan_count']==4


def test_diagnostic_plan_failures_do_not_hide_standalone_source_infeasibility():
    s=toy();s['projects'][0]['lp_commitment_pence']=0;a,b=universes(s)
    report=check.compare_plans(s,a,b,[{'id':'empty','plan':{'P001':0}}])
    assert report['plans'][0]['A']['feasible'] is True
    assert report['plans'][0]['passed'] is True
    assert not report['passed'] and report['financial_universe_check']['infeasible_candidates']


def test_plan_errors_are_complete_and_do_not_stop_later_plan_checks():
    s=toy();a,b=universes(s)
    plans=[{'id':'bad','plan':{'P001':True}},{'id':'bad','plan':{'P001':0}},{'id':'good','plan':{'P001':1}}]
    report=check.compare_plans(s,a,b,plans)
    assert not report['passed'] and len(report['plans'])==3
    assert report['plans'][0]['errors'] and report['plans'][1]['errors'] and report['plans'][2]['passed']
    with pytest.raises(ValueError):check.compare_plans(s,a,b,{},require_feasible=1)

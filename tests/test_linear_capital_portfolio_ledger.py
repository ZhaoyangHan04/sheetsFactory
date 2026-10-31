"""Hand-calculated toy forwards and pure production-shape validation only."""
import ast
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from sheets_factory.workbook.linear_capital_portfolio import spec, ledger


def fixture(*, projects=1, years=3, scenarios=1):
    ys=list(range(1,years+1));ids=list(spec.PROJECT_IDS[:projects]);sc=list(spec.SCENARIO_IDS[:scenarios])
    result={'version':1,'kind':'hypothetical_ringfenced_linear_capital_portfolio','dimension_mode':'toy',
        'fiscal_year_start':2027,'years':ys,'project_ids':ids,'scenario_ids':sc,
        'resource_ids':['U01'],'region_ids':['R01'],'sector_ids':['C01'],
        'projects':[],'scenarios':[],'exclusivity_groups':[],'prerequisites':[],
        'provenance':{'hypothetical':True,'description':'Hand-calculated independent projects, not a production source','ancestor_sha256':[]}}
    for pid in ids:
        result['projects'].append({'id':pid,'name':'Toy project '+pid,'region':'R01','sector':'C01',
            'asset_cost_pence':1000,'t0_ltv_bp':5000,'operating_start_year':1,'depreciation_years':2,
            'base_annual_revenue_pence':300,'base_annual_opex_pence':100,
            'revenue_growth_factor_bp':10000,'opex_growth_factor_bp':10000,'bank_rate_bp':1000,
            'debt_policy':'LEVEL_PRINCIPAL','debt_maturity_year':min(2,years),'tax_rate_bp':2500,
            'discount_rate_bp':0,'terminal_sale_proceeds_pence':1000,'lp_commitment_pence':10000,
            'resource_usage_units':{'U01':{sid:{str(y):7 for y in ys} for sid in sc}}})
    for sid in sc:
        result['scenarios'].append({'id':sid,'name':'Toy scenario '+sid,
            **{key:{str(y):10000 for y in ys} for key in ('revenue_factors_bp','opex_factors_bp','sale_factors_bp')},
            'interest_spread_bp':{str(y):0 for y in ys}})
    result['shared_limits']={'initial_sponsor_equity_pence':10**12,
        **{key:{sid:{str(y):10**12 for y in ys} for sid in sc} for key in ('annual_new_lp_pence','annual_debt_close_pence')},
        'resource_capacity_units':{'U01':{sid:{str(y):10**9 for y in ys} for sid in sc}},
        'region_exposure_pence':{'R01':{str(y):10**12 for y in ys}},
        'sector_exposure_pence':{'C01':{str(y):10**12 for y in ys}}}
    return result


def forward(public):
    return ledger.simulate_project(public,'P001','S01')


def simple(public):
    p=public['projects'][0]
    p.update(asset_cost_pence=100,t0_ltv_bp=0,bank_rate_bp=0,base_annual_revenue_pence=0,
        base_annual_opex_pence=0,tax_rate_bp=0,terminal_sale_proceeds_pence=100,depreciation_years=1)
    return p


def test_hand_calculated_acquisition_interest_losses_tax_distribution_and_equity():
    result=forward(fixture())
    assert result['t0']['bank_draw']==result['t0']['lp_call']==500
    a,b,c=result['annual']
    assert [r['principal_repayment'] for r in [a,b,c]]==[250,250,0]
    assert [r['bank_interest'] for r in [a,b,c]]==[50,25,0]
    assert [r['depreciation'] for r in [a,b,c]]==[500,500,0]
    assert a['taxable_before_losses']==-350 and a['loss_created']==350 and a['lp_call']==100
    assert b['taxable_before_losses']==-325 and b['loss_close']==675 and b['lp_call']==75
    assert c['sale_gain']==1000 and c['taxable_before_losses']==1200
    assert c['loss_used']==675 and c['taxable_after_losses']==525 and c['current_tax']==131
    assert c['lp_distribution']==1069 and c['lp_called_cumulative']==675
    assert result['npv_pence']==394 and result['feasible'] is True
    assert all(row[key]==0 for row in result['annual'] for key in ('balance_check','cash_check','asset_check','debt_check','loss_check'))
    assert c['cash_close']==c['asset_nbv_close']==c['debt_close']==c['book_equity_close']==0


def test_unshocked_growth_then_one_independent_scenario_multiplier():
    public=fixture(years=4);p=simple(public)
    p.update(operating_start_year=2,asset_cost_pence=10,depreciation_years=20,base_annual_revenue_pence=101,
        revenue_growth_factor_bp=10500,terminal_sale_proceeds_pence=0)
    public['scenarios'][0]['revenue_factors_bp'].update({'2':5000,'3':15000,'4':10000})
    rows=forward(public)['annual']
    assert [r['revenue_base'] for r in rows]==[0,101,106,111]
    assert [r['revenue'] for r in rows]==[0,51,159,111]
    assert [r['operating_active'] for r in rows]==[0,1,1,1]


@pytest.mark.parametrize('cost,life,expected',[(10,3,[3,3,4]),(2,3,[1,1,0])])
def test_straight_line_exact_residual_and_early_exhaustion(cost,life,expected):
    public=fixture();p=simple(public);p.update(asset_cost_pence=cost,depreciation_years=life)
    assert [r['depreciation'] for r in forward(public)['annual']]==expected


def test_terminal_sale_derecognises_remaining_nbv_when_operating_start_is_late():
    public=fixture();p=simple(public)
    p.update(asset_cost_pence=100,operating_start_year=3,depreciation_years=20,terminal_sale_proceeds_pence=80)
    result=forward(public);last=result['annual'][-1]
    assert [r['depreciation'] for r in result['annual']]==[0,0,5]
    assert last['sale_carrying']==95 and last['sale_gain']==-15
    assert last['taxable_before_losses']==-20 and last['asset_nbv_close']==0
    assert result['npv_pence']==-20


@pytest.mark.parametrize('policy,principal,interest',[
    ('LEVEL_PRINCIPAL',[17,17,16],[5,3,2]),('BULLET',[0,0,50],[5,5,5])])
def test_opening_debt_interest_and_two_distinct_principal_schedules(policy,principal,interest):
    public=fixture();p=simple(public)
    p.update(asset_cost_pence=100,t0_ltv_bp=5000,bank_rate_bp=1000,debt_policy=policy,debt_maturity_year=3)
    result=forward(public)
    assert [r['principal_repayment'] for r in result['annual']]==principal
    assert [r['bank_interest'] for r in result['annual']]==interest


@pytest.mark.parametrize('use_at_last_valid_year',[False,True])
def test_three_year_fifo_last_valid_year_and_expiry_before_use(use_at_last_valid_year):
    public=fixture(years=5);p=simple(public)
    p.update(asset_cost_pence=1,base_annual_revenue_pence=10,base_annual_opex_pence=10,
        terminal_sale_proceeds_pence=0,tax_rate_bp=5000)
    c=public['scenarios'][0]
    c['opex_factors_bp']={str(y):10000 if y==1 else 0 for y in public['years']}
    c['revenue_factors_bp']={str(y):10000 if y==5 or (y==4 and use_at_last_valid_year) else 0 for y in public['years']}
    result=forward(public);first,fourth,last=result['annual'][0],result['annual'][3],result['annual'][4]
    assert first['loss_created']==11
    assert fourth['loss_used']==(10 if use_at_last_valid_year else 0)
    assert last['loss_expired']==(1 if use_at_last_valid_year else 11)
    assert last['loss_used']==0 and last['taxable_after_losses']==10 and last['current_tax']==5
    event=next(v for v in result['tax_vintages'] if v['year']==5 and v['origin_year']==1)
    assert event['expired']==last['loss_expired'] and event['closing']==0


def test_fifo_uses_oldest_loss_first_and_retains_exhausted_event_rows():
    public=fixture();p=simple(public)
    p.update(asset_cost_pence=1,base_annual_opex_pence=10,base_annual_revenue_pence=10,terminal_sale_proceeds_pence=0)
    c=public['scenarios'][0];c['revenue_factors_bp']={'1':0,'2':0,'3':15000};c['opex_factors_bp']={'1':10000,'2':10000,'3':0}
    result=forward(public)
    events=[v for v in result['tax_vintages'] if v['year']==3]
    assert [(e['origin_year'],e['used'],e['closing']) for e in events]==[(1,11,0),(2,4,6)]


@pytest.mark.parametrize('cost,sale,expected',[(1,3,2),(3,3,-1)])
def test_t0_inside_single_final_positive_and_negative_half_round(cost,sale,expected):
    public=fixture(years=1);p=simple(public)
    p.update(asset_cost_pence=cost,terminal_sale_proceeds_pence=sale,discount_rate_bp=2000)
    result=forward(public)
    assert result['npv_pence']==expected
    assert Decimal(result['npv_unrounded_decimal'])==(Decimal('1.5') if cost==1 else Decimal('-0.5'))


def test_no_annual_npv_rounding():
    public=fixture(years=2);p=simple(public)
    p.update(asset_cost_pence=1,base_annual_revenue_pence=1,terminal_sale_proceeds_pence=0,discount_rate_bp=2000)
    result=forward(public)
    # -1 + 1/1.2 + 1/1.2**2 = 19/36 = .52777..., posted1p.
    assert result['npv_pence']==1
    assert Decimal('0.5277')<Decimal(result['npv_unrounded_decimal'])<Decimal('0.5278')


def test_commitment_shortfall_is_not_a_plug_and_later_cash_does_not_undo_infeasibility():
    public=fixture();p=simple(public);p.update(lp_commitment_pence=10)
    result=forward(public)
    assert result['t0']['lp_required']==100 and result['t0']['lp_call']==10 and result['t0']['funding_gap']==90
    assert result['annual'][0]['cash_open']==-90 and result['annual'][-1]['cash_close']==0
    assert all(r['lp_called_cumulative']==10 for r in result['annual'])
    assert result['feasible'] is False and result['npv_pence'] is None
    assert all(row['balance_check']==row['cash_check']==0 for row in result['annual'])


def test_distributions_never_restore_lifetime_gross_commitment():
    public=fixture();p=simple(public)
    p.update(lp_commitment_pence=100,base_annual_revenue_pence=50,base_annual_opex_pence=20)
    c=public['scenarios'][0];c['revenue_factors_bp']={'1':10000,'2':0,'3':0};c['opex_factors_bp']={'1':0,'2':10000,'3':0}
    result=forward(public)
    assert result['annual'][0]['lp_distribution']==50
    assert result['annual'][1]['lp_required']==20 and result['annual'][1]['lp_call']==0 and result['annual'][1]['funding_gap']==20
    assert result['feasible'] is False


def test_shared_plan_zero_unselected_flows_all_scenarios_and_S01_sum_objective():
    public=fixture(projects=2,scenarios=3);before=deepcopy(public)
    public['scenarios'][1]['revenue_factors_bp']={str(y):5000 for y in public['years']}
    before=deepcopy(public)
    result=ledger.simulate(public,{'P001':1,'P002':0})
    assert public==before and len(result['projects'])==2 and result['all_standalone_feasible']
    assert result['objective_pence']==result['projects']['P001']['scenarios']['S01']['npv_pence']
    assert result['objective_pence']!=result['projects']['P001']['scenarios']['S02']['npv_pence']
    for sid in public['scenario_ids']:
        assert result['group']['scenarios'][sid]['annual'][0]['year_end_debt']==250
    empty=ledger.simulate(public,{'P001':0,'P002':0})
    assert empty['objective_pence']==0 and all(r[field]==0 for s in empty['group']['scenarios'].values() for r in s['annual'] for field in spec.GROUP_FIELDS)


def test_annual_LP_capacity_uses_gross_calls_not_net_distributions():
    public=fixture(projects=2)
    p=public['projects'][1];p.update(base_annual_revenue_pence=3000,base_annual_opex_pence=0)
    public['shared_limits']['annual_new_lp_pence']['S01']['1']=0
    result=ledger.simulate(public,{'P001':1,'P002':1})
    row=next(c for c in result['constraints'] if c['id']=='annual_new_lp:S01:1')
    assert row['lhs']==100 and not row['passed'] and not result['feasible'] and result['objective_pence'] is None
    assert result['group']['scenarios']['S01']['annual'][0]['lp_distributions']>row['lhs']


@pytest.mark.parametrize('family',['initial','debt','resource','region','sector','exclusivity','prerequisite'])
def test_each_shared_business_constraint_can_independently_reject_a_plan(family):
    public=fixture(projects=2);plan={'P001':1,'P002':1};limits=public['shared_limits']
    if family=='initial':limits['initial_sponsor_equity_pence']=999;wanted='initial_sponsor_equity'
    elif family=='debt':limits['annual_debt_close_pence']['S01']['1']=499;wanted='annual_debt_close'
    elif family=='resource':limits['resource_capacity_units']['U01']['S01']['1']=13;wanted='resource'
    elif family=='region':limits['region_exposure_pence']['R01']['1']=999;wanted='region_exposure'
    elif family=='sector':limits['sector_exposure_pence']['C01']['1']=999;wanted='sector_exposure'
    elif family=='exclusivity':
        public['exclusivity_groups']=[{'id':'SITE1','description':'Two alternatives at one site','project_ids':['P001','P002']}];wanted='exclusivity'
    else:
        public['prerequisites']=[{'id':'ACCESS','dependent':'P002','prerequisite':'P001','business_reason':'Operating site requires this separately funded access project'}]
        plan={'P001':0,'P002':1};wanted='prerequisite'
    result=ledger.simulate(public,plan)
    assert not result['feasible'] and result['objective_pence'] is None
    assert {r['family'] for r in result['constraints'] if not r['passed']}=={wanted}


def test_unselected_infeasible_candidate_is_preserved_and_fails_separate_source_gate():
    public=fixture(projects=2);public['projects'][1]['lp_commitment_pence']=0
    result=ledger.simulate(public,{'P001':1,'P002':0})
    assert result['feasible'] and result['all_standalone_feasible'] is False
    assert len(result['projects'])==2 and result['projects']['P002']['scenarios']['S01']['npv_pence'] is None


def test_sparse_rows_complete_fields_and_no_optimization_or_other_financial_imports():
    result=ledger.simulate_universe(fixture())
    row=result['projects']['P001']['scenarios']['S01']
    assert set(row['annual'][0])==set(spec.ANNUAL_FIELDS)|{'year','fiscal_year','operating_active','feasible'}
    assert set(row['tax_vintages'][0])==set(spec.VINTAGE_FIELDS)|{'year','fiscal_year','origin_year'}
    assert result['optimization_performed'] is result['source_or_difficulty_certified'] is False
    tree=ast.parse(Path(ledger.__file__).read_text())
    imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert imports==['__future__','decimal','spec']


def test_actual_arithmetic_guards_reject_unsafe_products_and_sums():
    b=ledger._Bounds()
    assert b.product(1,5000)==1 and b.product(-1,5000)==-1
    with pytest.raises(ValueError,match='times BP'):b.product(2**53//10000+1,10000)
    with pytest.raises(ValueError,match='sum exceeds'):b.sum(2**52,2**52)
    assert forward(fixture())['arithmetic_bounds']['all_postings_products_and_sums_below_2_to_53'] is True


@pytest.mark.parametrize('change',['bool_money','float_factor','bool_year','missing_year','extra_field','negative_rate','cycle','incomplete_plan'])
def test_raw_contract_and_plan_type_fail_closed(change):
    public=fixture(projects=2)
    if change=='bool_money':public['projects'][0]['asset_cost_pence']=True
    elif change=='float_factor':public['scenarios'][0]['revenue_factors_bp']['1']=10000.0
    elif change=='bool_year':public['years'][0]=True
    elif change=='missing_year':del public['shared_limits']['annual_new_lp_pence']['S01']['1']
    elif change=='extra_field':public['projects'][0]['ready_NPV']=123
    elif change=='negative_rate':public['scenarios'][0]['interest_spread_bp']['1']=-1001
    elif change=='cycle':public['prerequisites']=[{'id':'A','dependent':'P001','prerequisite':'P002','business_reason':'Dependency A'},
        {'id':'B','dependent':'P002','prerequisite':'P001','business_reason':'Dependency B'}]
    else:
        with pytest.raises(ValueError):ledger.simulate(public,{'P001':1})
        return
    with pytest.raises(ValueError):spec.load_spec(public)


def production_shape():
    """Construct typed raw primitives only; never execute the production ledger."""
    public=fixture(years=20,scenarios=3);template=public['projects'][0]
    public.update(dimension_mode='production',project_ids=list(spec.PROJECT_IDS),resource_ids=list(spec.RESOURCE_IDS),
        region_ids=list(spec.REGION_IDS),sector_ids=list(spec.SECTOR_IDS))
    public['projects']=[]
    for i,pid in enumerate(spec.PROJECT_IDS):
        p=deepcopy(template);p.update(id=pid,name='Hypothetical project '+pid,region=spec.REGION_IDS[i%6],sector=spec.SECTOR_IDS[i%8])
        p['resource_usage_units']={u:deepcopy(template['resource_usage_units']['U01']) for u in spec.RESOURCE_IDS}
        public['projects'].append(p)
    limits=public['shared_limits']
    limits['resource_capacity_units']={u:deepcopy(limits['resource_capacity_units']['U01']) for u in spec.RESOURCE_IDS}
    limits['region_exposure_pence']={r:deepcopy(limits['region_exposure_pence']['R01']) for r in spec.REGION_IDS}
    limits['sector_exposure_pence']={r:deepcopy(limits['sector_exposure_pence']['C01']) for r in spec.SECTOR_IDS}
    public['exclusivity_groups']=[{'id':f'SITE{i}','description':'Provided site alternatives',
        'project_ids':list(spec.PROJECT_IDS[3*i:3*i+3])} for i in range(40)]
    public['prerequisites']=[{'id':f'ACCESS{i}','prerequisite':spec.PROJECT_IDS[i],
        'dependent':spec.PROJECT_IDS[120+i],'business_reason':'The dependent site requires this separately funded connection'} for i in range(80)]
    return public


def test_full_240_scope_is_typed_without_any_production_financial_forward(monkeypatch):
    monkeypatch.setattr(ledger,'_project',lambda *_:pytest.fail('Production forward not authorized'))
    public=production_shape();loaded=spec.load_spec(public)
    assert len(loaded['projects'])==240 and loaded['project_ids'][-1]=='P240'
    assert len(loaded['scenarios'])==3 and len(loaded['years'])==20
    assert len(loaded['exclusivity_groups'])==40 and len(loaded['prerequisites'])==80
    assert len(loaded['resource_ids'])==6 and len(loaded['region_ids'])==6 and len(loaded['sector_ids'])==8
    del public['projects'][-1]
    with pytest.raises(ValueError,match='Every project'):spec.load_spec(public)


def test_public_rules_have_business_policies_without_evaluation_pipeline_tutorial():
    text=' '.join(spec.RULES).lower()
    assert not any(term in text for term in ('model difficulty','oracle','harbor','workbook audit','optimization status'))

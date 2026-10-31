"""N40 certificates with two active bits, safe prunes, and counted forwards.

Only four predeclared plans are journalled by the main fixture. No optimiser,
40-bit enumeration, workbook, LibreOffice, model or production run occurs.
"""
from copy import deepcopy
from fractions import Fraction
import json

import pytest

from sheets_factory.workbook.capital_allocation_sparse import bounds,certificate,ledger,spec

LIMITS={'max_regions':100,'max_leaves':16,'max_region_bytes':10000,'max_total_bytes':1000000,'max_elapsed_seconds':120}


def annual(value):return {str(year):value for year in spec.YEARS}


def public():
    projects=[]
    for index,pid in enumerate(spec.project_ids(40)):
        projects.append({'id':pid,'commission_year':2024,'sale_year':2026,
            'acquisition_cost_pence':1000 if index<2 else 1000000,'depreciation_years':1,
            'annual_revenue_pence':{**annual(0),'2025':3000 if index==0 else 2000 if index==1 else 0},
            'annual_opex_pence':annual(0),'sale_proceeds_pence':0})
    return {'schema_version':1,'currency':'GBP','monetary_unit':'pence','years':list(spec.YEARS),
        'opening_cash_pence':5000,'minimum_cash_pence':0,'lp_commitment_pence':0,'facility_limit_pence':0,
        'advance_rate_p12':0,'tax_rate_p12':0,'tax_loss_carry_years':3,'discount_factors_p12':annual(spec.SCALE),
        'projects':projects,'scenarios':[{'id':sid,'revenue_factors_p12':annual(spec.SCALE),
            'opex_factors_p12':annual(spec.SCALE),'nav_factors_p12':annual(spec.SCALE),
            'sale_factors_p12':annual(spec.SCALE),'bank_rates_p12':annual(0),'haircuts_p12':annual(0)}
            for sid in spec.SCENARIO_IDS],
        'provenance':{'kind':'synthetic_capital_allocation_extension','raw_ancestors':deepcopy(spec.RAW_ANCESTORS)}}


def leaf_claim(value,mask):
    plan=spec.plan_from_mask_hex(value,'0x'+format(mask,'016x'));actual=ledger.simulate(value,plan)
    return {'mask_hex':spec.mask_hex(value,plan),'feasible':actual['feasible'],
        'objective_pence':None if actual['objective_pence'] is None else str(actual['objective_pence']),
        'scenario_npvs_pence':{sid:None if row['npv_pence'] is None else str(row['npv_pence'])
            for sid,row in actual['scenarios'].items()},
        'first_violations':{sid:None if row['first_violation'] is None else {
            'year':str(row['first_violation']['year']),'kind':row['first_violation']['kind'],
            'amount_pence':str(row['first_violation']['amount_pence'])}
            for sid,row in actual['scenarios'].items()}}


def rank(claim):return {key:claim[key] for key in ('mask_hex','scenario_npvs_pence','objective_pence')}


@pytest.fixture
def case():
    value=public();order=[*spec.project_ids(40)[2:],'P01','P02']
    # Four fixed plans in branch ordinal order; thirty-eight other decisions
    # are provably unaffordable. No plan is selected through an optimiser.
    claims=[leaf_claim(value,mask) for mask in (0,2,1,3)]
    regions=[{'prefix':'0'*38+bits,'kind':'leaf','evidence':claim}
        for bits,claim in zip(('00','01','10','11'),claims)]
    regions.extend({'prefix':'0'*zeros+'1','kind':'infeasible',
        'evidence':{'method':'farkas','cut_multipliers':{'S01.2024.facility':bounds.encode_rational(1)}}}
        for zeros in range(37,-1,-1))
    header={'kind':certificate.KIND,'version':1,'binding':certificate.certificate_binding(value,branch_order=order,limits=LIMITS),
        'best':rank(claims[3]),'runnerup':rank(claims[2]),'gap_pence':'1000'}
    return value,header,regions


def verify(case,**kwargs):
    value,header,regions=case
    return certificate.verify_certificate(value,header,iter(regions),limits=kwargs.get('limits',LIMITS))


def test_complete_semantic_partition_proves_unique_best_and_actual_runner_with_exact_four_forwards(case,monkeypatch):
    real=ledger.simulate;calls=[]
    def counted(value,plan):calls.append(dict(plan));return real(value,plan)
    monkeypatch.setattr(ledger,'simulate',counted)
    result=verify(case)
    assert len(calls)==4 and result['actual_forward_calls']==result['actual_leaf_count']=='4'
    assert result['actual_region_count']=='42' and result['actual_Farkas_regions']=='38'
    assert result['complete_plan_count']==str(1<<40)
    assert result['best']['objective_pence']=='3000' and result['runnerup']['objective_pence']=='2000'
    assert result['gap_pence']=='1000' and result['unique_optimum_and_actual_runnerup_proven'] is True
    assert result['complete'] is True and result['passed'] is True
    assert result['two_independent_searches_certified'] is False
    assert result['independent_financial_forward_implementations']=='1'
    assert result['source_financial_workbook_audited'] is False and result['source_quality_or_difficulty_certified'] is False
    assert result['optimiser_or_search_executed'] is False and int(result['elapsed_nanoseconds'])>0
    assert result['verification_limits']==LIMITS


@pytest.mark.parametrize('method',['additive','fractional_knapsack','dual'])
def test_safe_exact_bound_regions_can_replace_non_rank_leaves_without_extra_forward(case,method,monkeypatch):
    value,header,regions=deepcopy(case);fixed=spec.plan_from_mask_hex(value,regions[0]['evidence']['mask_hex'])
    model=bounds.prepare_bounds(value)
    if method=='additive':upper=bounds.additive_upper_bound(model,fixed)
    elif method=='fractional_knapsack':upper=bounds.fractional_knapsack_upper_bound(model,fixed)
    else:upper=bounds.dual_upper_bound(model,{'S01':1,'S02':0,'S03':0},{},fixed)
    evidence={'method':method,'claimed_upper':bounds.encode_rational(upper)}
    if method=='dual':evidence.update(scenario_weights={sid:bounds.encode_rational(int(sid=='S01')) for sid in spec.SCENARIO_IDS},cut_multipliers={})
    regions[0]={'prefix':regions[0]['prefix'],'kind':'bound','evidence':evidence}
    result=verify((value,header,regions))
    assert result['actual_forward_calls']=='3' and result['actual_bound_regions']=='1'


def test_negative_fractional_upper_uses_floor_and_may_equal_integer_runner():
    value=public();value['discount_factors_p12']=annual(spec.SCALE//2)
    value['projects'][1]['annual_revenue_pence']['2025']=2801
    order=[*spec.project_ids(40)[2:],'P01','P02'];claims=[leaf_claim(value,mask) for mask in (0,2,1,3)]
    regions=[{'prefix':'0'*38+bits,'kind':'leaf','evidence':claim} for bits,claim in zip(('00','01','10','11'),claims)]
    model=bounds.prepare_bounds(value)
    upper=bounds.additive_upper_bound(model,spec.plan_from_mask_hex(value,claims[1]['mask_hex']))
    assert upper==Fraction(-2999,2) and upper.numerator//upper.denominator==-1500
    regions[1]={'prefix':regions[1]['prefix'],'kind':'bound','evidence':{'method':'additive','claimed_upper':bounds.encode_rational(upper)}}
    regions.extend({'prefix':'0'*zeros+'1','kind':'infeasible','evidence':{'method':'farkas',
        'cut_multipliers':{'S01.2024.facility':bounds.encode_rational(1)}}} for zeros in range(37,-1,-1))
    header={'kind':certificate.KIND,'version':1,'binding':certificate.certificate_binding(value,branch_order=order,limits=LIMITS),
        'best':rank(claims[3]),'runnerup':rank(claims[2]),'gap_pence':'900'}
    result=verify((value,header,regions))
    assert result['runnerup']['objective_pence']=='-1500' and result['actual_forward_calls']=='3'


def test_header_is_snapshotted_before_streamed_producer_can_mutate_rank_or_recipe(case):
    value,header,regions=deepcopy(case);original=deepcopy(header)
    def streamed():
        header['binding']['public_spec_sha256']='0'*64
        header['best']['objective_pence']='999999'
        yield from regions
    result=certificate.verify_certificate(value,header,streamed(),limits=LIMITS)
    assert result['binding']==original['binding'] and result['best']==original['best']


def test_runnerup_economic_ties_are_allowed_but_best_ties_are_not():
    value=public();value['projects'][1]['annual_revenue_pence']['2025']=3000
    order=[*spec.project_ids(40)[2:],'P01','P02'];claims=[leaf_claim(value,mask) for mask in (0,2,1,3)]
    regions=[{'prefix':'0'*38+bits,'kind':'leaf','evidence':claim} for bits,claim in zip(('00','01','10','11'),claims)]
    regions.extend({'prefix':'0'*zeros+'1','kind':'infeasible','evidence':{'method':'farkas',
        'cut_multipliers':{'S01.2024.facility':bounds.encode_rational(1)}}} for zeros in range(37,-1,-1))
    header={'kind':certificate.KIND,'version':1,'binding':certificate.certificate_binding(value,branch_order=order,limits=LIMITS),
        'best':rank(claims[3]),'runnerup':rank(claims[2]),'gap_pence':'2000'}
    assert verify((value,header,regions))['unique_optimum_and_actual_runnerup_proven'] is True
    # Make P02 exactly zero profit, giving P01 and the joint plan equal best.
    value['projects'][1]['annual_revenue_pence']['2025']=1000
    claims=[leaf_claim(value,mask) for mask in (0,2,1,3)]
    for record,claim in zip(regions,claims):record['evidence']=claim
    header.update(binding=certificate.certificate_binding(value,branch_order=order,limits=LIMITS),best=rank(claims[3]),runnerup=rank(claims[0]),gap_pence='2000')
    with pytest.raises(certificate.CertificateVerificationError,match='exceeds the claimed runner'):
        verify((value,header,regions))


@pytest.mark.parametrize('change',['public','candidate','recipe','order','count','limits','high_mask','same_rank','gap','rank_npv','float','missing_key'])
def test_public_branch_recipe_counts_and_rank_claims_cannot_be_trusted(case,change):
    value,header,regions=deepcopy(case)
    if change=='public':value['opening_cash_pence']+=1
    if change=='candidate':header['binding']['public_candidate_flows_sha256']='0'*64
    if change=='recipe':header['binding']['verification_recipe_sha256'][next(iter(header['binding']['verification_recipe_sha256']))]='0'*64
    if change=='order':header['binding']['branch_project_order'][-1]='P01'
    if change=='count':header['binding']['complete_plan_count']=str((1<<40)-1)
    if change=='limits':header['binding']['verification_limits']['max_leaves']+=1
    if change=='high_mask':header['best']['mask_hex']='0x8000000000000003'
    if change=='same_rank':header['runnerup']=deepcopy(header['best'])
    if change=='gap':header['gap_pence']='0'
    if change=='rank_npv':header['best']['scenario_npvs_pence']['S02']='3001'
    if change=='float':header['best']['objective_pence']=3000.0
    if change=='missing_key':header.pop('runnerup')
    with pytest.raises(certificate.CertificateVerificationError) as failed:verify((value,header,regions))
    assert failed.value.partial['passed'] is False and failed.value.partial['complete'] is False
    assert failed.value.partial['unique_optimum_and_actual_runnerup_proven'] is False


@pytest.mark.parametrize('change',['best_absent','runner_absent','other_above_runner','wrong_leaf_mask','wrong_leaf_npv','wrong_leaf_feasible','wrong_violation','bad_Farkas','fake_flag','wrong_upper','understated_upper'])
def test_every_leaf_and_prune_is_semantic_and_both_rank_leaves_must_be_present(case,change):
    value,header,regions=deepcopy(case)
    if change=='best_absent':
        header['runnerup']=deepcopy(header['best']);header['best']={'mask_hex':'0x0000000000000004','scenario_npvs_pence':{sid:'4000' for sid in spec.SCENARIO_IDS},'objective_pence':'4000'}
        header['gap_pence']='1000'
    if change=='runner_absent':
        header['runnerup']={'mask_hex':'0x0000000000000004','scenario_npvs_pence':{sid:'2500' for sid in spec.SCENARIO_IDS},'objective_pence':'2500'};header['gap_pence']='500'
    if change=='other_above_runner':header.update(runnerup=rank(regions[0]['evidence']),gap_pence='3000')
    if change=='wrong_leaf_mask':regions[0]['evidence']['mask_hex']=regions[1]['evidence']['mask_hex']
    if change=='wrong_leaf_npv':regions[0]['evidence']['scenario_npvs_pence']['S01']='1'
    if change=='wrong_leaf_feasible':regions[0]['evidence']['feasible']=1
    if change=='wrong_violation':regions[0]['evidence']['first_violations']['S01']={'year':'2024','kind':'unfunded_cash_deficiency','amount_pence':'1'}
    if change=='bad_Farkas':regions[-1]['evidence']['cut_multipliers']={}
    if change=='fake_flag':regions[-1]['evidence']['passed']=True
    if change in ('wrong_upper','understated_upper'):
        # A bound covering the real best can never replace its required leaf.
        regions[3]={'prefix':regions[3]['prefix'],'kind':'bound','evidence':{'method':'additive',
            'claimed_upper':bounds.encode_rational(3100 if change=='wrong_upper' else 1999)}}
    with pytest.raises(certificate.CertificateVerificationError):verify((value,header,regions))


def test_infeasible_full_depth_leaves_replay_actual_first_violation(case,monkeypatch):
    value,header,regions=deepcopy(case);region=regions[4]
    # Expand just the smallest four-plan impossible sibling, not the N40 cube.
    leaves=[]
    for bits,mask in zip(('00','01','10','11'),(1<<39,(1<<39)|2,(1<<39)|1,(1<<39)|3)):
        leaves.append({'prefix':region['prefix']+bits,'kind':'leaf','evidence':leaf_claim(value,mask)})
    regions[4:5]=leaves
    result=verify((value,header,regions))
    assert result['actual_forward_calls']=='8' and result['actual_Farkas_regions']=='37'
    regions[4]['evidence']['first_violations']['S01']['amount_pence']='1'
    with pytest.raises(certificate.CertificateVerificationError,match='first violation'):verify((value,header,regions))


@pytest.mark.parametrize('change',['truncated','overlap','reorder','interrupted'])
def test_complete_ordered_partition_is_required_not_just_a_reported_total(case,change):
    value,header,regions=deepcopy(case)
    if change=='truncated':regions.pop()
    if change=='overlap':regions.insert(1,deepcopy(regions[0]))
    if change=='reorder':regions[0],regions[1]=regions[1],regions[0]
    if change=='interrupted':
        def interrupted():
            yield regions[0]
            raise OSError('Explicit interrupted certificate stream')
        stream=interrupted()
    else:stream=iter(regions)
    with pytest.raises(certificate.CertificateVerificationError) as failed:
        certificate.verify_certificate(value,header,stream,limits=LIMITS)
    assert failed.value.partial['complete'] is False


@pytest.mark.parametrize('field',['max_regions','max_leaves','max_region_bytes','max_total_bytes','max_elapsed_seconds'])
def test_independent_budgets_fail_incomplete_without_claiming_an_optimum(case,monkeypatch,field):
    value,header,regions=deepcopy(case);limits=deepcopy(LIMITS);limits[field]=1
    header['binding']=certificate.certificate_binding(value,branch_order=header['binding']['branch_project_order'],limits=limits)
    if field=='max_elapsed_seconds':
        clock=iter((0,0,2*10**9,2*10**9));monkeypatch.setattr(certificate.time,'monotonic_ns',lambda:next(clock))
    with pytest.raises(certificate.CertificateVerificationError,match='budget exhausted') as failed:
        verify((value,header,regions),limits=limits)
    assert failed.value.partial['complete'] is False and failed.value.partial['unique_optimum_and_actual_runnerup_proven'] is False


@pytest.mark.parametrize('value',[True,0,-1,0.5,'100'])
def test_resource_limits_require_literal_positive_integers(value):
    limits=deepcopy(LIMITS);limits['max_leaves']=value
    with pytest.raises(ValueError):certificate.certificate_binding(public(),limits=limits)


def test_exact_rational_witnesses_reject_float_noncanonical_and_negative_multipliers(case):
    for invalid in (0.5,{'numerator':'2','denominator':'2'},{'numerator':'-1','denominator':'1'}):
        value,header,regions=deepcopy(case)
        regions[-1]['evidence']['cut_multipliers']['S01.2024.facility']=invalid
        with pytest.raises(certificate.CertificateVerificationError):verify((value,header,regions))

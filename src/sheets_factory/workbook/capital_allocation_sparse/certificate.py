"""Baseline exact semantic verification of one sparse financial partition.

No search is performed. Every supplied leaf is evaluated once by the frozen
Decimal journal. Every prune is recomputed from public primitives and exact
rationals. This deliberately slow baseline has explicit independent budgets;
an interrupted or over-budget verification never proves an optimum.
"""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import re
import time

from . import bounds,coverage,ledger,spec

KIND='sparse_capital_semantic_certificate'
LIMIT_FIELDS=frozenset(('max_regions','max_leaves','max_region_bytes','max_total_bytes','max_elapsed_seconds'))


class CertificateVerificationError(ValueError):
    """No verified optimum exists; ``partial`` preserves bounded progress."""
    def __init__(self,message,partial):
        super().__init__(message);self.partial=partial


def _require(condition,message):
    if not condition:raise ValueError(message)


def _integer(value):
    _require(type(value) is str and re.fullmatch(r'0|-?[1-9][0-9]*',value) is not None,
             'Financial claims require canonical signed integer strings')
    return int(value)


def _limits(value):
    _require(isinstance(value,dict) and set(value)==LIMIT_FIELDS
        and all(type(x) is int and 0<x<=coverage.MAX_SAFE_JSON_INTEGER for x in value.values()),
        'Independent verification limits must be complete positive literal integers')
    return dict(value)


def _bytes(value):
    coverage._json_value(value)
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def _recipe():
    ledger.validate_upstream()
    modules=(Path(__file__),Path(bounds.__file__),Path(coverage.__file__),Path(ledger.__file__),Path(spec.__file__),
             Path(ledger.original.__file__),Path(ledger.original_spec.__file__))
    return {str(path.resolve()):hashlib.sha256(path.read_bytes()).hexdigest() for path in modules}


def _binding(public,model,branch_order,limits):
    coverage.describe_prefix(len(model.project_ids),'',branch_order=branch_order)
    order=list(model.project_ids if branch_order is None else branch_order)
    candidates=[[[asdict(row) for row in project] for project in scenario] for scenario in model.candidates]
    return {'version':1,'public_spec_sha256':spec.canonical_sha(public),
        'project_count':len(model.project_ids),'project_order':list(model.project_ids),
        'branch_project_order':order,'complete_plan_count':str(1<<len(model.project_ids)),
        'bound_model':model.binding(),'public_candidate_flows_sha256':spec.canonical_sha(candidates),
        'verification_recipe_sha256':_recipe(),'verification_limits':limits}


def certificate_binding(public,*,branch_order=None,limits):
    """Prepare public bounds and recipe bindings only; no plan forward/search."""
    public=spec.load_spec(public);limits=_limits(limits);model=bounds.prepare_bounds(public)
    return _binding(public,model,branch_order,limits)


def _rank(public,value):
    _require(isinstance(value,dict) and set(value)=={'mask_hex','scenario_npvs_pence','objective_pence'},
             'A complete best or runner-up rank claim is required')
    spec.plan_from_mask_hex(public,value['mask_hex'])
    objective=_integer(value['objective_pence']);scenarios=value['scenario_npvs_pence']
    _require(isinstance(scenarios,dict) and set(scenarios)==set(spec.SCENARIO_IDS),
             'Every rank must claim all three scenario NPVs')
    _require(min(_integer(scenarios[sid]) for sid in spec.SCENARIO_IDS)==objective,
             'The claimed rank objective is not the scenario minimum')
    return objective


def _rational(value):
    _require(isinstance(value,dict),'Certificate rational values must use reduced numerator/denominator strings')
    return bounds.rational(value)


def _multipliers(value):
    _require(isinstance(value,dict),'An explicit cut multiplier map is required')
    for amount in value.values():_rational(amount)
    return value


def _leaf_summary(result,mask):
    _require(type(result.get('feasible')) is bool and set(result.get('scenarios',{}))==set(spec.SCENARIO_IDS),
             'The independent journal returned an incomplete scenario set')
    violations={};npvs={}
    for sid in spec.SCENARIO_IDS:
        row=result['scenarios'][sid]
        _require(row.get('all_journals_balance') is True and len(row.get('annual',[]))==20
            and [year['year'] for year in row['annual']]==list(spec.YEARS),
            'Every independent scenario needs all twenty balanced financial periods')
        amount=row.get('npv_pence');_require(amount is None or type(amount) is int,'The independent journal NPV is not exact integer pence')
        npvs[sid]=None if amount is None else str(amount)
        first=row.get('first_violation')
        violations[sid]=None if first is None else {'year':str(first['year']),'kind':first['kind'],'amount_pence':str(first['amount_pence'])}
    objective=result.get('objective_pence')
    _require(objective is None or type(objective) is int,'The independent objective is not exact integer pence')
    return {'mask_hex':mask,'feasible':result['feasible'],'scenario_npvs_pence':npvs,
        'objective_pence':None if objective is None else str(objective),'first_violations':violations}


def _validate_leaf_claim(public,value):
    _require(isinstance(value,dict) and set(value)=={'mask_hex','feasible','scenario_npvs_pence','objective_pence','first_violations'}
        and type(value['feasible']) is bool,'A complete typed leaf claim is required')
    spec.plan_from_mask_hex(public,value['mask_hex'])
    if value['objective_pence'] is not None:_integer(value['objective_pence'])
    for name in ('scenario_npvs_pence','first_violations'):
        _require(isinstance(value[name],dict) and set(value[name])==set(spec.SCENARIO_IDS),'All three leaf scenario claims are required')
    for amount in value['scenario_npvs_pence'].values():
        if amount is not None:_integer(amount)
    for violation in value['first_violations'].values():
        if violation is None:continue
        _require(isinstance(violation,dict) and set(violation)=={'year','kind','amount_pence'}
            and type(violation['kind']) is str,'A first actual violation claim is incomplete')
        _integer(violation['year']);_integer(violation['amount_pence'])


def verify_certificate(public,header,regions,*,limits):
    """Verify one complete streamed certificate, or raise with incomplete data.

    Limits come from an independently frozen caller configuration, never from
    the header alone. Header rank claims require their actual full-depth leaves
    to occur in the partition. A bound's rational floor may equal runner-up;
    runner-up ties are permitted, best ties are not. Returned evidence proves
    one semantic partition using one Decimal journal, not two global searches.
    """
    started=time.monotonic_ns();counts={'regions':0,'leaves':0,'bound':0,'infeasible':0,'forward_calls':0,'bytes':0}
    claimed={};actual_ranks={};leaf_digest=hashlib.sha256();active_limits=None

    def elapsed():return time.monotonic_ns()-started

    def partial(reason):
        return {'kind':'incomplete_sparse_capital_semantic_verification','version':1,'passed':False,'complete':False,
            'reason':reason,'actual_region_count':str(counts['regions']),'actual_leaf_count':str(counts['leaves']),
            'actual_forward_calls':str(counts['forward_calls']),'canonical_region_bytes_checked':str(counts['bytes']),
            'elapsed_nanoseconds':str(elapsed()),'verification_limits':active_limits,
            'unique_optimum_and_actual_runnerup_proven':False,'source_quality_or_difficulty_certified':False}

    def budget():
        _require(elapsed()<=active_limits['max_elapsed_seconds']*10**9,'Verification elapsed budget exhausted; proof incomplete')

    try:
        active_limits=_limits(limits);budget();public=spec.load_spec(public)
        _require(isinstance(header,dict) and set(header)=={'kind','version','binding','best','runnerup','gap_pence'}
            and header['kind']==KIND and type(header['version']) is int and header['version']==1,
            'The semantic certificate header schema differs')
        # A streamed producer must not mutate its original header between
        # records after the public/recipe/rank checks have completed.
        header=json.loads(_bytes(header))
        _require(isinstance(header['binding'],dict),'The complete public/recipe/branch binding is required')
        order=header['binding'].get('branch_project_order');model=bounds.prepare_bounds(public);budget()
        _require(header['binding']==_binding(public,model,order,active_limits),
                 'Public primitives, candidate flows, branch order, bounds recipe or limits changed')
        best=_rank(public,header['best']);runner=_rank(public,header['runnerup'])
        _require(header['best']['mask_hex']!=header['runnerup']['mask_hex'] and best>runner
            and _integer(header['gap_pence'])==best-runner>=1,'Best and runner-up must be distinct with a genuine positive pence gap')
        claimed={header[key]['mask_hex']:key for key in ('best','runnerup')};cursor=0

        def checked_regions():
            nonlocal cursor
            for original in regions:
                budget();_require(counts['regions']<active_limits['max_regions'],'Verification region budget exhausted; proof incomplete')
                encoded=_bytes(original)+b'\n'
                _require(len(encoded)<=active_limits['max_region_bytes'],'Verification per-region byte budget exhausted; proof incomplete')
                _require(counts['bytes']+len(encoded)<=active_limits['max_total_bytes'],'Verification stream byte budget exhausted; proof incomplete')
                record=json.loads(encoded);counts['bytes']+=len(encoded)
                _require(isinstance(record,dict) and set(record)=={'prefix','kind','evidence'}
                    and record['kind'] in coverage.KINDS and isinstance(record['evidence'],dict),'A complete typed region record is required')
                region=coverage.describe_prefix(len(model.project_ids),record['prefix'],branch_order=order)
                _require(int(region['ordinal_start'])==cursor,'A semantic partition has a gap, overlap or out-of-order region')
                fixed=region['fixed_decisions'];evidence=record['evidence'];kind=record['kind']
                if kind=='leaf':
                    _require(region['depth']==len(model.project_ids),'A financial leaf must specify every decision')
                    _require(counts['leaves']<active_limits['max_leaves'],'Verification leaf budget exhausted; proof incomplete')
                    _validate_leaf_claim(public,evidence)
                    _require(evidence['mask_hex']==region['value_mask_hex'],'The financial leaf mask differs from its exact prefix')
                    counts['forward_calls']+=1
                    result=ledger.simulate(public,fixed);budget()
                    actual=_leaf_summary(result,region['value_mask_hex'])
                    _require(evidence==actual,'A financial leaf differs from the independent Decimal forward or first violation')
                    leaf_digest.update(_bytes({'prefix':record['prefix'],'actual':actual})+b'\n');counts['leaves']+=1
                    if result['feasible']:
                        name=claimed.get(actual['mask_hex'])
                        if name:
                            rank={key:actual[key] for key in ('mask_hex','scenario_npvs_pence','objective_pence')}
                            _require(rank==header[name],'The actual best/runner-up leaf differs from its complete rank claim')
                            _require(name not in actual_ranks,'A rank leaf appeared twice');actual_ranks[name]=rank
                        else:_require(result['objective_pence']<=runner,'Another feasible leaf exceeds the claimed runner-up')
                elif kind=='bound':
                    method=evidence.get('method');keys={'method','claimed_upper'}
                    if method=='dual':keys|={'scenario_weights','cut_multipliers'}
                    _require(set(evidence)==keys,'A bound witness has missing or unexpected fields')
                    upper=_rational(evidence['claimed_upper'])
                    if method=='additive':actual=bounds.additive_upper_bound(model,fixed)
                    elif method=='fractional_knapsack':actual=bounds.fractional_knapsack_upper_bound(model,fixed)
                    elif method=='dual':
                        weights=evidence['scenario_weights']
                        _require(isinstance(weights,dict),'All exact scenario weights are required')
                        for weight in weights.values():_rational(weight)
                        actual=bounds.dual_upper_bound(model,weights,_multipliers(evidence['cut_multipliers']),fixed)
                    else:raise ValueError('Unknown exact bound method')
                    _require(actual is not None and upper==actual and actual.numerator//actual.denominator<=runner,
                             'A prune upper is incorrect or exceeds the actual runner-up')
                    counts['bound']+=1
                else:
                    _require(set(evidence)=={'method','cut_multipliers'} and evidence['method']=='farkas',
                             'An infeasible region requires an explicit exact Farkas witness')
                    result=bounds.verify_infeasibility_witness(model,_multipliers(evidence['cut_multipliers']),fixed)
                    _require(result['passed'] is True,'The exact necessary-cut Farkas contradiction is not strict')
                    counts['infeasible']+=1
                budget();cursor=int(region['ordinal_end_exclusive']);counts['regions']+=1
                yield record

        structural=coverage.verify_partition(len(model.project_ids),checked_regions(),branch_order=order,max_regions=active_limits['max_regions'])
        budget();_require(set(actual_ranks)=={'best','runnerup'},'Both claimed feasible rank leaves must actually occur in the complete partition')
        _require(structural['region_count']==counts['regions'] and structural['covered_plan_count']==str(1<<len(model.project_ids)),
                 'The independently checked complete coverage count differs')
        return {'kind':'checked_sparse_capital_semantic_certificate','version':1,'passed':True,'complete':True,
            'header_sha256':hashlib.sha256(_bytes(header)).hexdigest(),'binding':header['binding'],
            'complete_plan_count':structural['complete_plan_count'],'actual_region_count':str(counts['regions']),
            'actual_leaf_count':str(counts['leaves']),'actual_forward_calls':str(counts['forward_calls']),
            'actual_bound_regions':str(counts['bound']),'actual_Farkas_regions':str(counts['infeasible']),
            'canonical_region_bytes_checked':str(counts['bytes']),'elapsed_nanoseconds':str(elapsed()),
            'verification_limits':active_limits,'canonical_region_stream_sha256':structural['canonical_region_stream_sha256'],
            'independent_leaf_observations_sha256':leaf_digest.hexdigest(),**actual_ranks,'gap_pence':str(best-runner),
            'complete_disjoint_structural_coverage':True,'every_supplied_leaf_independently_replayed':True,
            'every_prune_semantically_checked':True,'unique_optimum_and_actual_runnerup_proven':True,
            'semantic_certificates_checked':'1','independent_financial_forward_implementations':'1',
            'two_independent_searches_certified':False,'optimiser_or_search_executed':False,
            'source_financial_workbook_audited':False,'source_quality_or_difficulty_certified':False}
    except Exception as error:
        if isinstance(error,CertificateVerificationError):raise
        raise CertificateVerificationError(str(error),partial(str(error))) from error

"""Pure primitive, public-contract and immutable-inventory tests; no finance calls."""
import ast
from copy import deepcopy
from decimal import localcontext
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
import random

import pytest

from sheets_factory.workbook.capital_allocation_scaled import constrained_catalog as catalog
from sheets_factory.workbook.capital_allocation_scaled import spec
from sheets_factory.workbook.capital_allocation.spec import ANNUAL_FIELDS, PROJECT_FIELDS, VINTAGE_FIELDS

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/prepare_constrained_capital_specs.py'


def entry():
    module = importlib.util.spec_from_file_location('_constrained_capital_entry', SCRIPT)
    result = importlib.util.module_from_spec(module); module.loader.exec_module(result)
    return result


@pytest.fixture(scope='module')
def rows():
    return catalog.generate_specs()


def test_fixed_first_development_and_ten_fresh_confirmation_candidates(rows):
    value = catalog.load_catalog()
    assert len(rows) == 11 and [r['profile_id'] for r in rows] == list(catalog.PROFILE_ORDER)
    assert value['prospective_first_strong_profile'] == '30-D02'
    assert value['confirmation_profile_order'] == [f'30-H{i:02d}' for i in range(1, 11)]
    assert not set(value['profile_order']) & set(catalog.original.PROFILE_ORDER)
    assert len({p['seed'] for p in value['profiles']}) == 11
    assert value['selection_uses_model_outcomes'] is False
    assert value['optimal_project_count_is_acceptance_criterion'] is False


def test_every_source_has_all_public_GBP_pence_P12_primitives_without_answers(rows):
    for row in rows:
        public = spec.load_spec(row['spec'])
        assert public['currency'] == 'GBP' and public['monetary_unit'] == 'pence'
        assert len(public['projects']) == 30 and [p['id'] for p in public['projects']] == list(spec.project_ids(30))
        assert len(public['scenarios']) == 3 and public['years'] == list(spec.YEARS)
        assert public['provenance']['raw_ancestors'] == spec.RAW_ANCESTORS
        assert not {'best_plan','winner','objective_pence','plan','unique_best'} & public.keys()
        assert all(p['annual_revenue_pence'][str(p['commission_year'])] == 0 and p['sale_year'] <= 2043 for p in public['projects'])
        assert all(type(n) is int for s in public['scenarios'] for k in s if k != 'id' for n in s[k].values())


def test_generation_is_deterministic_independent_of_global_decimal_and_random(rows):
    value = catalog.load_catalog(); original = deepcopy(value)
    random.seed(12345)
    with localcontext() as context:
        context.prec = 7
        assert catalog.generate_specs(value) == rows
    assert value == original
    assert len({spec.canonical_sha(r['spec']) for r in rows}) == 11


def test_economic_families_are_not_uniform_scalings_and_equal_capex_pairs_are_declared(rows):
    all_shapes = []
    for row in rows:
        public = row['spec']; summary = catalog.describe_profile(row['profile_id']); metadata = summary['candidate_cohorts']
        assert [sum(p['cohort'] == c for p in metadata) for c in catalog.COHORTS] == [5]*6
        by_id = {p['id']: p for p in public['projects']}
        paired = {c: sorted([m for m in metadata if m['cohort'] == c], key=lambda m:m['cohort_ordinal'])
                  for c in ('contracted_long_life','merchant_cycle')}
        for left, right in zip(*paired.values()):
            assert by_id[left['id']]['acquisition_cost_pence'] == by_id[right['id']]['acquisition_cost_pence']
        shapes = [(p['commission_year'],p['sale_year'],p['depreciation_years'],
            tuple(Fraction(v,p['acquisition_cost_pence']) for v in p['annual_revenue_pence'].values()),
            tuple(Fraction(v,p['acquisition_cost_pence']) for v in p['annual_opex_pence'].values())) for p in public['projects']]
        assert len(set(shapes)) == 30
        all_shapes.append(tuple(shapes))
    assert len(set(all_shapes)) == 11


def test_raw_first_wave_exceeds_funding_upper_bound_without_a_ledger(rows):
    # An algebraic public-primitive bound, not an actual forward/journal claim:
    # no operation/sale/prior-NAV precedes the first commissioning year.
    for row in rows:
        p = row['spec']; first = min(a['commission_year'] for a in p['projects'])
        capex = sum(a['acquisition_cost_pence'] for a in p['projects'] if a['commission_year']==first)
        upper = p['opening_cash_pence'] + p['lp_commitment_pence'] - p['minimum_cash_pence']
        assert capex > upper
        assert all(all(v==0 for y,v in a['annual_revenue_pence'].items() if int(y)<=first) for a in p['projects'])
    p = rows[0]['spec']
    assert (p['opening_cash_pence'],p['minimum_cash_pence'],p['lp_commitment_pence'],p['facility_limit_pence']) == (300000000,90000000,1800000000,1400000000)


def test_stresses_are_dated_and_fifo_expiry_candidate_has_genuine_delayed_recovery(rows):
    config = catalog.load_catalog()
    for row, profile in zip(rows,config['profiles']):
        p=row['spec']; s2,s3=p['scenarios'][1:]
        assert s2['revenue_factors_p12'][str(profile['early_stress_start'])] < s3['revenue_factors_p12'][str(profile['early_stress_start'])]
        assert s3['revenue_factors_p12'][str(profile['late_stress_start'])] < s2['revenue_factors_p12'][str(profile['late_stress_start'])]
        assert s2['haircuts_p12'][str(profile['early_stress_start'])] > s3['haircuts_p12'][str(profile['early_stress_start'])]
        summary=catalog.describe_profile(row['profile_id'])
        identity=next(m['id'] for m in summary['candidate_cohorts'] if m['cohort']=='early_loss_rebuild' and m['cohort_ordinal']==4)
        project=next(a for a in p['projects'] if a['id']==identity)
        assert all(project['annual_revenue_pence'][str(project['commission_year']+age)]
            < project['annual_opex_pence'][str(project['commission_year']+age)] for age in range(1,6))
        assert project['annual_revenue_pence'][str(project['commission_year']+6)] > project['annual_opex_pence'][str(project['commission_year']+6)]
        assert p['tax_loss_carry_years'] <= 4


def test_fixed_inventory_matches_independent_forward_protocol_but_does_not_claim_execution(rows):
    for row in rows:
        identity=row['profile_id']; plans=catalog.fixed_diagnostic_plans(identity); inventory=catalog.engineering_inventory(identity)
        assert len(plans)==44 and len({v['id'] for v in plans})==44
        assert all(set(v)=={'id','plan'} and list(v['plan'])==list(spec.project_ids(30))
            and all(type(n) is int and n in (0,1) for n in v['plan'].values()) for v in plans)
        assert inventory['plans']==plans and inventory['public_spec_sha256']==spec.canonical_sha(row['spec'])
        assert inventory['engineering_criteria_status']=='predeclared_not_evaluated'
        assert inventory['all_mechanisms_or_feasibility_guaranteed'] is False
        assert inventory['source_financial_audit_or_global_optimum_proven'] is False
        assert inventory['plan_enumeration_or_ranking_performed'] is False
        assert inventory['minimum_optimal_project_count_rule'] is None
        assert [c['id'] for c in inventory['engineering_criteria']]==list(catalog.CRITERIA_IDS)
        assert all(n==0 for k,n in inventory.items() if k.endswith('_calls'))
        assert all(a in {v['id'] for v in plans} and b in {v['id'] for v in plans} for a,b in inventory['comparison_pairs'])


def test_full_public_contract_retains_all_field_meanings_and_original_math():
    contract=catalog.public_contract('30-D02')
    assert contract['profile_id']=='30-D02'
    assert set(contract['annual_fields'])==set(ANNUAL_FIELDS)
    assert set(contract['project_fields'])==set(PROJECT_FIELDS)
    assert set(contract['vintage_fields'])==set(VINTAGE_FIELDS)
    assert catalog.contract_markdown(contract)==catalog.original.contract_markdown(catalog.original.public_contract('30-D01'))
    assert 'including candidates with choice 0' in contract['candidate_schedule_policy']
    assert 'time-zero' in contract['opening_cashflow_policy']


@pytest.mark.parametrize('change',['missing','reordered','old_id','repeated_seed','currency','unit','boolmoney','boolrate','extra_answer','zero_cohort','bad_calendar','reverse_range','no_expiry_case','missing_criteria','posthoc','claimed_pass','force_cardinality','bad_ancestor','incomplete_stress'])
def test_ambiguous_or_incomplete_catalog_is_rejected(change):
    c=catalog.load_catalog()
    if change=='missing':c['profiles'].pop()
    elif change=='reordered':c['profiles'].reverse()
    elif change=='old_id':c['prospective_first_strong_profile']='30-D01'
    elif change=='repeated_seed':c['profiles'][1]['seed']=c['profiles'][0]['seed']
    elif change=='currency':c['currency']='CNY'
    elif change=='unit':c['monetary_unit']='pounds'
    elif change=='boolmoney':c['profiles'][0]['opening_cash_pence']=True
    elif change=='boolrate':c['profiles'][0]['tax_rate_bp']=True
    elif change=='extra_answer':c['profiles'][0]['best_plan']={}
    elif change=='zero_cohort':c['cohorts'][0]['count']=0
    elif change=='bad_calendar':c['profiles'][0]['calendar_shift_years']=3
    elif change=='reverse_range':c['cohorts'][0]['cost_range_pence']=[500000000,100000000]
    elif change=='no_expiry_case':c['early_loss_recovery_delays_by_ordinal']=[2]*5
    elif change=='missing_criteria':c['engineering_criteria'].pop()
    elif change=='posthoc':c['selection_uses_model_outcomes']=True
    elif change=='claimed_pass':c['engineering_criteria_status']='passed'
    elif change=='force_cardinality':c['optimal_project_count_is_acceptance_criterion']=True
    elif change=='bad_ancestor':c['raw_ancestors']['NYU']='0'*64
    else:c['scenario_stress_policy']['early'].pop('nav_bp')
    with pytest.raises(ValueError):catalog.load_catalog(c)


def test_duplicate_json_catalog_fields_are_rejected(tmp_path):
    path=tmp_path/'duplicate.json';path.write_text('{"currency":"GBP","currency":"GBP"}')
    with pytest.raises(ValueError,match='Duplicate'):catalog.load_catalog(path)


def test_prepare_writes_all_eleven_raw_profiles_and_zero_execution_claims(tmp_path,monkeypatch):
    module=entry()
    def forbidden(*a,**k):pytest.fail('No financial engine or optional forward diagnostics may run')
    monkeypatch.setattr(catalog.original,'diagnose_fixed_plans',forbidden)
    frozen_before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in
        [Path(catalog.original.__file__),catalog.original.DEFAULT_CATALOG,Path(spec.__file__)]}
    ref=module.prepare(tmp_path/'raw');manifest=json.loads(Path(ref['path']).read_text())
    assert manifest['generated_count']==11 and manifest['failures']==[] and manifest['status']=='completed_public_primitives_only'
    assert manifest['profile_order']==list(catalog.PROFILE_ORDER) and manifest['qualified'] is False
    assert all(manifest[k]==0 for k in ('ledger_calls','optimizer_calls','LO_calls','model_calls','source_workbooks','task_count'))
    assert manifest['engineering_criteria_status']=='predeclared_not_evaluated' and manifest['criteria_guaranteed_to_pass'] is False
    assert not list((tmp_path/'raw').rglob('*.xlsx')) and not list((tmp_path/'raw').rglob('*.bin'))
    for record in manifest['specifications']:
        assert set(record)=={'profile_id','spec','public_summary','candidate_contract','engineering_inventory','candidate_contract_markdown'}
        for value in record.values():
            if isinstance(value,dict):assert module.reference(value['path'])==value
    assert frozen_before=={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in frozen_before}
    with pytest.raises(ValueError,match='fresh'):module.prepare(tmp_path/'raw')


def test_failed_profile_stays_in_complete_inventory_while_other_profiles_are_preserved(tmp_path,monkeypatch):
    module=entry();normal=catalog.build_spec
    def fail(identity,*a,**k):
        if identity=='30-H02':raise ValueError('explicit unit primitive-preparation failure')
        return normal(identity,*a,**k)
    monkeypatch.setattr(catalog,'build_spec',fail)
    with pytest.raises(ValueError,match='failures are retained'):module.prepare(tmp_path/'failed')
    manifest=json.loads((tmp_path/'failed/catalog_manifest.json').read_text());inventory=json.loads(Path(manifest['prospective_inventory']['path']).read_text())
    assert [x['profile_id'] for x in inventory['profiles']]==list(catalog.PROFILE_ORDER)
    assert manifest['generated_count']==10 and manifest['failures'][0]['profile_id']=='30-H02'
    assert (tmp_path/'failed/30-H02/failure.json').is_file()
    assert (tmp_path/'failed/30-H10/public_spec.json').is_file()
    assert manifest['status']=='failed_public_preparation' and manifest['qualified'] is False


def test_no_financial_imports_or_execution_CLI_are_available(tmp_path):
    module=entry()
    for path in (SCRIPT,Path(catalog.__file__)):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                names=[node.module or ''] if isinstance(node,ast.ImportFrom) else [a.name for a in node.names]
                assert not any(any(part in name.split('.') for part in ('ledger','search_a','search_b','engine','openpyxl')) for name in names)
    with pytest.raises(SystemExit):module.main(['--output',str(tmp_path/'never'),'--run'])
    with pytest.raises(SystemExit):module.main(['--output',str(tmp_path/'never'),'--diagnostics'])
    assert not (tmp_path/'never').exists()


def test_symlink_preparation_root_is_rejected(tmp_path):
    target=tmp_path/'actual';target.mkdir();link=tmp_path/'link';link.symlink_to(target,target_is_directory=True)
    with pytest.raises(ValueError,match='real directory'):entry().prepare(link/'escape')

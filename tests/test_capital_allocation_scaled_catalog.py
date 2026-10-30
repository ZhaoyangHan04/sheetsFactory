from copy import deepcopy
from decimal import localcontext
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import random
import subprocess
import sys

import pytest

from sheets_factory.workbook.capital_allocation.spec import ANNUAL_FIELDS, PROJECT_FIELDS, VINTAGE_FIELDS
from sheets_factory.workbook.capital_allocation_scaled import catalog
from sheets_factory.workbook.capital_allocation_scaled.spec import RAW_ANCESTORS, YEARS, canonical_sha, load_spec

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / 'config/capital_allocation_scaled_catalog_v1.json'
SCRIPT = ROOT / 'scripts/prepare_capital_allocation_scaled_specs.py'


def _driver():
    module_spec = importlib.util.spec_from_file_location('scaled_catalog_preparation', SCRIPT)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def generated():
    return catalog.generate_specs()


def test_prospective_roles_reserve_development_and_ten_confirmation_profiles(generated):
    checked = catalog.load_catalog()
    assert len(generated) == 13
    assert [r['profile_id'] for r in generated] == list(catalog.PROFILE_ORDER)
    assert checked['benchmark_profile_order'] == ['26-B01', '28-B01', '30-D01']
    assert checked['prospective_first_strong_profile'] == '30-D01'
    assert checked['confirmation_profile_order'] == [f'30-G{i:02d}' for i in range(1, 11)]
    assert '30-D01' not in checked['confirmation_profile_order']
    assert checked['benchmark_only_no_rollout'] == ['26-B01', '28-B01']


def test_complete_bounded_public_primitives_with_two_ancestors_and_no_plan(generated):
    for row in generated:
        public = load_spec(row['spec'])
        count = int(row['profile_id'].split('-')[0])
        assert len(public['projects']) == count
        assert [p['id'] for p in public['projects']] == [f'P{i:02d}' for i in range(1, count + 1)]
        assert public['provenance']['raw_ancestors'] == RAW_ANCESTORS
        assert len(public['scenarios']) == 3 and public['years'] == list(YEARS)
        assert not {'plan', 'best_plan', 'objective_pence', 'unique_best', 'winner'} & public.keys()
        assert all(p['annual_revenue_pence'][str(p['commission_year'])] == 0
                   and p['sale_year'] <= 2043 for p in public['projects'])
        assert any(p['annual_revenue_pence'][str(p['commission_year'] + 1)]
                   < p['annual_opex_pence'][str(p['commission_year'] + 1)] for p in public['projects'])


def test_generation_is_independent_of_global_random_and_decimal_context(generated):
    before = catalog.load_catalog()
    random.seed(9001)
    with localcontext() as context:
        context.prec = 8
        again = catalog.generate_specs(before)
    assert again == generated
    assert before == catalog.load_catalog()
    assert len({canonical_sha(row['spec']) for row in generated}) == 13


def test_project_families_have_nonproportional_timing_and_operating_shapes(generated):
    normalised_profiles = set()
    for row in generated:
        summary = catalog.describe_profile(row['profile_id'])
        public = row['spec']
        roles = summary['candidate_cohorts']
        assert set(p['cohort'] for p in roles) == set(catalog.COHORTS)
        declared = next(p for p in catalog.load_catalog()['profiles'] if p['id'] == row['profile_id'])
        assert [sum(p['cohort'] == cohort for p in roles) for cohort in catalog.COHORTS] == declared['cohort_counts']
        shapes = []
        for p in public['projects']:
            cost = p['acquisition_cost_pence']
            shapes.append((p['commission_year'], p['sale_year'], p['depreciation_years'],
                tuple(Fraction(p['annual_revenue_pence'][str(y)], cost) for y in YEARS),
                tuple(Fraction(p['annual_opex_pence'][str(y)], cost) for y in YEARS)))
        assert len(set(shapes)) == len(public['projects'])
        normalised_profiles.add(tuple(shapes))
        assert len({p['commission_year'] for p in public['projects']}) >= 5
        assert len({p['sale_year'] for p in public['projects']}) >= 6
    # Uniform money rescaling would leave these normalised shapes unchanged.
    assert len(normalised_profiles) == 13


def test_scenarios_have_distinct_dated_demands_costs_and_collateral_haircuts(generated):
    for row in generated:
        scenarios = row['spec']['scenarios']
        for field in ('revenue_factors_p12', 'opex_factors_p12', 'nav_factors_p12',
                      'sale_factors_p12', 'bank_rates_p12', 'haircuts_p12'):
            assert len({tuple(s[field].values()) for s in scenarios}) == 3
            assert all(len(set(s[field].values())) >= 2 for s in scenarios)
        assert len({canonical_sha(s) for s in scenarios}) == 3


@pytest.mark.parametrize('change', [
    'missing_profile', 'reordered', 'repeat_seed', 'wrong_count', 'drop_cohort',
    'bad_sum', 'hidden_best', 'bool_rate', 'bad_timing', 'raw_ancestor',
    'first_development', 'confirmation_includes_development',
])
def test_catalog_rejects_incomplete_or_posthoc_role_and_input_changes(change):
    config = catalog.load_catalog()
    if change == 'missing_profile': config['profiles'].pop()
    elif change == 'reordered': config['profiles'].reverse()
    elif change == 'repeat_seed': config['profiles'][1]['seed'] = config['profiles'][0]['seed']
    elif change == 'wrong_count': config['profiles'][0]['project_count'] = 30
    elif change == 'drop_cohort': config['profiles'][2]['cohort_counts'] = [0, 10, 5, 5, 5, 5]
    elif change == 'bad_sum': config['profiles'][2]['cohort_counts'][0] += 1
    elif change == 'hidden_best': config['profiles'][0]['best_plan'] = [1] * 26
    elif change == 'bool_rate': config['profiles'][0]['tax_rate_bp'] = True
    elif change == 'bad_timing': config['profiles'][0]['early_stress_start'] = 2040
    elif change == 'raw_ancestor': config['raw_ancestors']['NYU'] = '0' * 64
    elif change == 'first_development': config['prospective_first_strong_profile'] = '30-G01'
    elif change == 'confirmation_includes_development': config['confirmation_profile_order'][0] = '30-D01'
    with pytest.raises(ValueError): catalog.load_catalog(config)


def test_complete_candidate_annual_vintage_and_summary_contract_resolves_public_semantics():
    contract = catalog.public_contract('30-D01')
    assert set(contract['annual_fields']) == set(ANNUAL_FIELDS)
    assert set(contract['project_fields']) == set(PROJECT_FIELDS)
    assert set(contract['vintage_fields']) == set(VINTAGE_FIELDS)
    assert set(contract['summary_fields']) == {'feasible', 'npv_pence', 'diagnostic_npv_pence',
                                              'overall_feasible', 'objective_pence'}
    assert 'including candidates with choice 0' in contract['candidate_schedule_policy']
    assert 'only when aggregating' in contract['candidate_schedule_policy']
    assert 'negative' in contract['diagnostic_continuation_policy']
    assert 'time-zero' in contract['opening_cashflow_policy']
    assert 'not subtract initial capital twice' in contract['opening_cashflow_policy']
    assert 'blank' in contract['blank_policy']
    assert 'before this FY expiry' in contract['annual_fields']['loss_open']
    assert 'before all financing' in contract['annual_fields']['cash_before_financing']
    assert 'before applying' in contract['annual_fields']['lp_required']
    assert 'never' in contract['summary_fields']['diagnostic_npv_pence']
    assert '30 binary investment choices' in contract['rules'][0]
    assert 'eighteen' not in json.dumps(contract)
    markdown = catalog.contract_markdown(contract)
    for field in (*ANNUAL_FIELDS, *PROJECT_FIELDS, *VINTAGE_FIELDS):
        assert f'`{field}`' in markdown
    assert not any(term in contract for term in ('best_plan', 'winner', 'optimal_npv_pence'))


def test_fixed_diagnostic_plans_are_declared_not_an_optimised_subset():
    public = catalog.build_spec('30-D01')
    plans = catalog.fixed_plans('30-D01')
    assert list(plans) == ['empty', 'all', 'first8', *('cohort_' + c for c in catalog.COHORTS)]
    assert all(set(plan) == {p['id'] for p in public['projects']} for plan in plans.values())
    assert sum(plans['empty'].values()) == 0 and sum(plans['all'].values()) == 30
    assert sum(plans['first8'].values()) == 8
    assert all(sum(plans['cohort_' + c].values()) == 5 for c in catalog.COHORTS)
    report = catalog.diagnose_fixed_plans('30-D01')
    assert len(report['results']) == 9 and report['optimisation_performed'] is False
    assert report['unique_optimum_claimed'] is False and report['source_admission_claimed'] is False
    empty = report['results'][0]
    assert empty['name'] == 'empty' and empty['feasible'] is True
    assert empty['objective_pence'] < 0  # No investment still bears the dated cash holding cost.
    assert not {'best_plan', 'winner', 'selected_plan'} & report.keys()


def test_cli_default_only_describes_no_artifacts_or_process_calculations(tmp_path):
    result = subprocess.run([sys.executable, str(SCRIPT)], cwd=tmp_path,
                            capture_output=True, text=True, check=True)
    plan = json.loads(result.stdout)
    assert plan['requested_profiles'] == list(catalog.PROFILE_ORDER)
    assert plan['planned_raw_specifications'] == 13
    assert plan['source_original_ancestors'] == 2 and plan['derived_workbook_count'] == 0
    assert plan['LO_calls'] == plan['model_calls'] == plan['actual_enumerated_plans'] == 0
    assert plan['task_count'] == 0 and plan['qualified'] is False
    assert list(tmp_path.iterdir()) == []


def test_explicit_test_fixture_preparation_preserves_full_prospective_inventory(tmp_path):
    driver = _driver()
    directory = tmp_path / 'fixture_only'
    reference = driver.prepare(CATALOG_PATH, directory, profiles=['30-D01'])
    manifest = json.loads(Path(reference['path']).read_text())
    assert manifest['status'] == 'completed_public_primitives_only' and manifest['generated_count'] == 1
    assert manifest['confirmation_profile_order'] == list(catalog.CONFIRMATION_ORDER)
    assert manifest['financial_or_unique_optimum_claimed'] is False
    assert manifest['source_original_ancestors'] == 2 and manifest['source_workbooks'] == 0
    inventory = json.loads(Path(manifest['prospective_inventory']['path']).read_text())
    assert len(inventory['profiles']) == 13
    assert sum(r['requested'] for r in inventory['profiles']) == 1
    assert inventory['profiles'][2]['profile_id'] == '30-D01'
    public = json.loads((directory / '30-D01/public_spec.json').read_text())
    assert canonical_sha(public) == inventory['profiles'][2]['spec_sha256']
    assert not list(directory.rglob('*.xlsx'))
    assert not list(directory.rglob('*diagnostics*'))
    for record in manifest['specifications']:
        for key in ('spec', 'public_summary', 'candidate_contract', 'candidate_contract_markdown'):
            assert driver.reference(record[key]['path']) == record[key]
    with pytest.raises(ValueError, match='fresh immutable'):
        driver.prepare(CATALOG_PATH, directory)


@pytest.mark.parametrize('profiles', [[], ['30-G01', '30-D01'], ['30-D01', '30-D01'], ['30-G11']])
def test_operational_subset_must_retain_declared_order(profiles):
    with pytest.raises(ValueError, match='prospective'):
        _driver().describe(CATALOG_PATH, profiles)


def test_failure_is_retained_and_never_replaced_with_a_passing_subset(tmp_path, monkeypatch):
    driver = _driver()
    original = driver.generation.describe_profile

    def fail_second(profile_id, config):
        if profile_id == '28-B01':
            raise ArithmeticError('fixture publication error')
        return original(profile_id, config)

    monkeypatch.setattr(driver.generation, 'describe_profile', fail_second)
    output = tmp_path / 'failed_fixture'
    with pytest.raises(ValueError, match='failure manifest retained'):
        driver.prepare(CATALOG_PATH, output, profiles=['26-B01', '28-B01'])
    failure = json.loads((output / 'catalog_manifest.json').read_text())
    assert failure['status'] == 'failed' and failure['generated_count'] == 1
    assert failure['requested_profiles'] == ['26-B01', '28-B01']
    assert failure['failure']['type'] == 'ArithmeticError'
    assert len(json.loads((output / 'prospective_inventory.json').read_text())['profiles']) == 13
    assert failure['qualified'] is False and failure['task_count'] == 0


def test_optional_diagnostics_are_physically_separate_from_public_artifacts(tmp_path, monkeypatch):
    driver = _driver()
    # Test isolation and recipe binding without additional financial evaluation.
    monkeypatch.setattr(driver.generation, 'diagnose_fixed_plans',
                        lambda *args: {'kind': 'fixture', 'optimisation_performed': False})
    reference = driver.prepare(CATALOG_PATH, tmp_path / 'diagnostic_fixture',
                               profiles=['30-D01'], include_diagnostics=True)
    manifest = json.loads(Path(reference['path']).read_text())
    record = manifest['specifications'][0]
    private = Path(record['private_fixed_plan_diagnostics']['path'])
    assert private.parts[-3:] == ('private', 'fixed_plan_diagnostics', '30-D01.json')
    assert not list((tmp_path / 'diagnostic_fixture/30-D01').glob('*diagnostic*'))

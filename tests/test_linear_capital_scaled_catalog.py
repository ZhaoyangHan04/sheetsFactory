"""Fresh N360 raw assumptions only; no financial, optimizer or service calls."""
import ast
from copy import deepcopy
import importlib.util
from pathlib import Path
import random
import socket
import subprocess

import pytest

from sheets_factory.workbook.linear_capital_portfolio import spec as original_spec
from sheets_factory.workbook.linear_capital_scaled import catalog, spec


@pytest.fixture(scope='module')
def public():
    return catalog.build_spec()


def without_revenue(public):
    result = deepcopy(public)
    result.pop('provenance')
    for project in result['projects']:
        project.pop('base_annual_revenue_pence')
        project.pop('base_annual_opex_pence')
    return result


def test_fresh_full_universe_has_exact_dimensions_and_globally_coupled_relationships(public):
    assert spec.load_spec(public) == public
    assert public['project_ids'] == [f'P{i:03d}' for i in range(1, 361)]
    assert spec.expected_constraint_count(public) == 941
    assert len(public['exclusivity_groups']) == 60 and len(public['prerequisites']) == 120
    grouped = [pid for group in public['exclusivity_groups'] for pid in group['project_ids']]
    assert grouped == public['project_ids'][180:] and len(set(grouped)) == 180
    for group in public['exclusivity_groups']:
        members = [public['projects'][public['project_ids'].index(pid)] for pid in group['project_ids']]
        assert len({p['region'] for p in members}) == 1
    hubs = set(public['project_ids'][:60])
    assert all(edge['prerequisite'] in hubs and edge['dependent'] not in hubs
        for edge in public['prerequisites'])
    assert len({edge['dependent'] for edge in public['prerequisites']}) == 120
    assert any(int(edge['dependent'][1:]) > 240 for edge in public['prerequisites'])
    # No repeating project block is present: each complete raw physical record
    # is distinct, including across the former 240-project prefix boundary.
    fingerprints = [spec.canonical_sha256(p['resource_usage_units']) for p in public['projects']]
    assert len(set(fingerprints)) == 360
    assert public['provenance']['ancestor_sha256'] == []
    assert 'All source correctness and difficulty checks remain pending' in public['provenance']['description']


def test_correlated_contracts_match_explicit_independent_revenue_draws(public):
    rng = random.Random(catalog.SEED)
    for project in public['projects']:
        cost = project['asset_cost_pence']
        wanted = cost*3000//spec.BP+rng.randint(-catalog.REVENUE_JITTER_PENCE, catalog.REVENUE_JITTER_PENCE)
        assert project['base_annual_revenue_pence'] == wanted
        assert project['base_annual_opex_pence'] == wanted*6500//spec.BP
        assert (project['t0_ltv_bp'],project['operating_start_year'],project['depreciation_years'],
            project['bank_rate_bp'],project['debt_policy'],project['debt_maturity_year'],
            project['tax_rate_bp'],project['discount_rate_bp']) == (6000,1,15,500,'LEVEL_PRINCIPAL',10,2500,700)
        assert project['revenue_growth_factor_bp'] == project['opex_growth_factor_bp'] == 10000
        assert project['terminal_sale_proceeds_pence'] == cost*3000//spec.BP
        assert project['lp_commitment_pence'] == cost*100


def test_spread_is_independent_of_all_other_raw_contracts_capacities_and_relationships(public):
    narrower = catalog.build_competitive_spec(catalog.SEED, 100000)
    assert without_revenue(narrower) == without_revenue(public)
    assert narrower['provenance'] != public['provenance']
    assert any(a['base_annual_revenue_pence'] != b['base_annual_revenue_pence']
        for a,b in zip(narrower['projects'],public['projects']))
    rng = random.Random(catalog.SEED)
    assert [p['base_annual_revenue_pence'] for p in narrower['projects']] == [
        p['asset_cost_pence']*3000//spec.BP+rng.randint(-100000,100000) for p in narrower['projects']]
    assert public == catalog.build_competitive_spec(catalog.SEED, catalog.REVENUE_JITTER_PENCE)


@pytest.mark.parametrize('spread', [0,6_000_000])
def test_complete_raw_specs_validate_at_both_allowed_revenue_spread_endpoints(spread):
    public = catalog.build_competitive_spec(catalog.SEED, spread)
    assert spec.load_spec(public) == public
    assert all(p['base_annual_revenue_pence'] >= 0 for p in public['projects'])
    if spread == 0:
        assert all(p['base_annual_revenue_pence'] == p['asset_cost_pence']*3000//spec.BP
            for p in public['projects'])


def test_capacities_use_all_360_raw_contracts_and_no_financial_forecast(public):
    projects, limits = public['projects'], public['shared_limits']
    total_cost = sum(p['asset_cost_pence'] for p in projects)
    raw_equity = sum(p['asset_cost_pence']*4000//spec.BP for p in projects)
    assert limits['initial_sponsor_equity_pence'] == raw_equity*4500//spec.BP
    assert limits['initial_sponsor_equity_pence'] > sum(
        p['asset_cost_pence']*4000//spec.BP for p in projects[:240])*4500//spec.BP
    for sid in public['scenario_ids']:
        for year in public['years']:
            assert limits['annual_new_lp_pence'][sid][str(year)] == total_cost*500//spec.BP
            assert limits['annual_debt_close_pence'][sid][str(year)] == (
                total_cost*6000*(10-year)*4600//(spec.BP**2*10) if year < 10 else 0)
    for resource in public['resource_ids']:
        for sid in public['scenario_ids']:
            for year in public['years']:
                usage = [p['resource_usage_units'][resource][sid][str(year)] for p in projects]
                assert all(p['asset_cost_pence']//1000 <= observed <= p['asset_cost_pence']//1000+5000
                    for p,observed in zip(projects,usage))
                cap = limits['resource_capacity_units'][resource][sid][str(year)]
                assert sum(usage)*4400//spec.BP <= cap <= sum(usage)*4500//spec.BP
                assert cap > sum(usage[:240])*4500//spec.BP
    for attribute, field in [('region','region_exposure_pence'),('sector','sector_exposure_pence')]:
        for identity in public[attribute+'_ids']:
            cost = sum(p['asset_cost_pence'] for p in projects if p[attribute] == identity)
            assert limits[field][identity] == {
                str(y): cost*4600*max(0,15-y)//(spec.BP*15) for y in public['years']}
    policy = catalog.generation_policy()
    assert not policy['financial_forwards_or_NPV_or_optimized_plan_used']
    assert not policy['previous_project_blocks_copied_or_tiled']
    policy['physical_resource_capacity_bp_of_complete_provided_usage'].append(9999)
    assert catalog.generation_policy()['physical_resource_capacity_bp_of_complete_provided_usage'] == [4400,4500]


def test_determinism_new_seed_and_original_namespace_remain_separate(public):
    original_ids = original_spec.PROJECT_IDS
    assert public == catalog.build_spec(catalog.SEED)
    changed = catalog.build_spec(catalog.SEED+1)
    assert public['projects'][0]['asset_cost_pence'] != changed['projects'][0]['asset_cost_pence']
    assert public['shared_limits'] != changed['shared_limits']
    assert original_spec.PROJECT_IDS is original_ids and len(original_ids) == 240
    with pytest.raises(ValueError, match='Unknown portfolio'): original_spec.load_spec(public)


def test_catalog_has_only_pure_contract_imports_and_uses_no_file_network_or_process_calls(monkeypatch):
    tree = ast.parse(Path(catalog.__file__).read_text())
    imported = {(n.module, n.level) for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imported == {('__future__',0),('copy',0),(None,1)}
    assert [alias.name for n in ast.walk(tree) if isinstance(n, ast.Import) for alias in n.names] == ['random']
    def forbidden(*args, **kwargs):
        raise AssertionError('A raw unit fixture must not call files, processes or network')
    monkeypatch.setattr(subprocess, 'Popen', forbidden)
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(Path, 'read_bytes', forbidden)
    monkeypatch.setattr(Path, 'write_bytes', forbidden)
    assert len(catalog.build_spec()['projects']) == 360


def test_complete_prospective_diagnostics_do_not_mutate_public_inputs(public):
    before = spec.canonical_sha256(public)
    plans = catalog.diagnostic_plans(public)
    assert len(plans) == len({p['id'] for p in plans}) == 18
    assert plans == catalog.diagnostic_plans(public)
    assert plans[0]['plan'] == {pid:0 for pid in public['project_ids']}
    assert plans[1]['plan'] == {pid:1 for pid in public['project_ids']}
    for record in plans:
        assert spec.validate_plan(public, record['plan']) == record['plan']
    assert spec.canonical_sha256(public) == before


def test_toy_diagnostics_are_complete_and_remain_explicit_toy():
    path = Path(__file__).with_name('test_linear_capital_scaled_spec.py')
    definition = importlib.util.spec_from_file_location('_scaled_raw_toy_inputs', path)
    inputs = importlib.util.module_from_spec(definition); definition.loader.exec_module(inputs)
    public = inputs.fixture()
    plans = catalog.diagnostic_plans(public)
    assert [r['id'] for r in plans] == ['empty','all']
    assert [sum(r['plan'].values()) for r in plans] == [0,3]
    assert spec.expected_constraint_count(public) == 33 and public['dimension_mode'] == 'toy'


@pytest.mark.parametrize('seed', [True,-1,2**32,1.5,'202701360'])
def test_invalid_seed_is_rejected_before_any_raw_draw(seed):
    with pytest.raises(ValueError, match='seed'): catalog.build_spec(seed)


@pytest.mark.parametrize('spread', [True,-1,6_000_001,0.5,'150000'])
def test_spread_domain_preserves_nonnegative_public_money_for_every_raw_draw(spread):
    with pytest.raises(ValueError, match='spread'): catalog.build_competitive_spec(catalog.SEED, spread)

"""Raw assumptions only; no finance, solver, workbook, service or model runs."""
import ast
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import random

import pytest

from sheets_factory.workbook.linear_capital_portfolio import catalog, catalog_candidates as candidates, catalog_correlated, spec

ROOT = Path(__file__).resolve().parents[1]
definition = importlib.util.spec_from_file_location('_candidate_raw_prepare', ROOT/'scripts/prepare_linear_capital_candidates.py')
entry = importlib.util.module_from_spec(definition); definition.loader.exec_module(entry)


def test_exact_twenty_profiles_are_read_from_the_fixed_config():
    configuration = candidates.load_catalog()
    assert candidates.profile_order() == tuple(f'P{i:02d}' for i in range(1, 21))
    assert [p['seed'] for p in configuration['profiles']] == list(range(20261201, 20261221))
    assert [p['revenue_jitter_pence'] for p in configuration['profiles']] == [150000]*10+[100000]*10
    assert configuration['reference_policy']['private_solver_seconds_per_job'] == 3600
    assert configuration['reference_policy']['retries'] == 0
    assert configuration['reference_policy']['independent_integer_matrices_required'] == 2
    assert configuration['selection_density_admission'] == candidates.DENSITY_GATE
    assert configuration['candidate_scope']['candidate_pool_is_not_release_set'] is True
    assert configuration['candidate_scope']['model_outcome_based_membership_selection_permitted'] is False


@pytest.mark.parametrize('attack', ['order', 'omit', 'seed', 'spread', 'bool_seed', 'bool_version', 'density', 'retry', 'runner', 'release'])
def test_catalog_cannot_silently_change_any_frozen_membership_or_gate(attack):
    value = candidates.load_catalog()
    if attack == 'order': value['profiles'].reverse()
    elif attack == 'omit': value['profile_order'].pop()
    elif attack == 'seed': value['profiles'][0]['seed'] += 1
    elif attack == 'spread': value['profiles'][10]['revenue_jitter_pence'] = 150000
    elif attack == 'bool_seed': value['profiles'][0]['seed'] = True
    elif attack == 'bool_version': value['version'] = True
    elif attack == 'density': value['selection_density_admission']['minimum'] = 79
    elif attack == 'retry': value['reference_policy']['retries'] = True
    elif attack == 'runner': value['reference_policy']['runner_excludes_complete_winner_plan'] = False
    else: value['candidate_scope']['confirmation_or_publication_authorized'] = True
    with pytest.raises(ValueError, match='complete prospectively fixed'):
        candidates.load_catalog(value)


@pytest.mark.parametrize('pid', ['P01', 'P10', 'P11', 'P20'])
def test_raw_jitter_is_independent_and_all_other_contracts_capacities_unchanged(pid):
    policy = candidates.profile_policy(pid)
    actual = candidates.build_spec(pid); base = catalog_correlated.build_spec(policy['seed'])
    rng = random.Random(policy['seed']); spread = policy['revenue_jitter_pence']
    changed = {'base_annual_revenue_pence', 'base_annual_opex_pence'}
    for before, after in zip(base['projects'], actual['projects']):
        revenue = before['asset_cost_pence']*3000//spec.BP + rng.randint(-spread, spread)
        assert after['base_annual_revenue_pence'] == revenue
        assert after['base_annual_opex_pence'] == revenue*6500//spec.BP
        assert {k:v for k,v in before.items() if k not in changed} == {k:v for k,v in after.items() if k not in changed}
    assert {k:v for k,v in actual.items() if k not in ('projects','provenance')} == {
        k:v for k,v in base.items() if k not in ('projects','provenance')}
    plans = candidates.diagnostic_plans(pid, public=actual)
    assert plans == catalog.diagnostic_plans(actual, seed=policy['seed'])
    assert len(plans) == len({p['id'] for p in plans}) == 18
    assert all(spec.validate_plan(actual, row['plan']) == row['plan'] for row in plans)


@pytest.mark.parametrize('bad', [None, True, {}, 'P00', 'P21', 'M02', 20261201])
def test_no_profile_or_seed_override(bad):
    with pytest.raises(ValueError): candidates.build_spec(bad)


def test_raw_modules_do_not_import_finance_solver_engine_or_model_backends():
    allowed = {'catalog', 'catalog_correlated', 'catalog_candidates', 'spec'}
    for path in (Path(candidates.__file__), Path(entry.__file__)):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module is None or 'sheets_factory' in node.module):
                assert {item.name for item in node.names} <= allowed
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {'simulate','simulate_universe','solve_cp_sat','solve_scip',
                    'solve_gurobi','load_workbook','recalculate','normalize','Popen'}
    assert not hasattr(entry, 'execute_prepared') and not hasattr(entry, 'run_development')


@pytest.fixture(scope='module')
def prepared(tmp_path_factory):
    output = tmp_path_factory.mktemp('raw-candidates')/'pool'
    receipt = entry.prepare(output)
    return output, receipt


def test_all_twenty_specs_and_diagnostic_inventories_precede_future_finance(prepared):
    output, receipt = prepared; value = entry.validate_prepared(output)
    assert entry.reference(receipt['path']) == receipt
    assert value['profile_order'] == list(candidates.PROFILE_ORDER) and len(value['profiles']) == 20
    assert value['all_specifications_frozen_before_financial_execution'] is True
    assert value['candidate_scope'] == candidates.CANDIDATE_SCOPE
    assert all(type(value[key]) is int and value[key] == 0 for key in entry.ZERO_FIELDS)
    all_specs = {row['profile_id']:row['specification'] for row in value['profiles']}
    for row in value['profiles']:
        raw = entry.read(row['raw_preparation'])
        assert raw['kind'] == 'prepared_linear_240_project_raw_assumptions'
        assert raw['all_specifications_frozen_before_finance'] == all_specs
        assert raw['reference_policy'] == candidates.REFERENCE_POLICY and raw['qualified'] is False
        assert len(raw['diagnostic_plans']) == 18
        assert str(candidates.DEFAULT_CATALOG) in raw['recipe_sha256']
    assert (output/'frozen_catalog.json').read_bytes() == candidates.DEFAULT_CATALOG.read_bytes()
    with pytest.raises(ValueError, match='fresh'):
        entry.prepare(output)


@pytest.mark.parametrize('attack', ['order', 'omit', 'bool_zero', 'weaken_gate', 'diagnostic', 'raw_specification'])
def test_cold_validation_rejects_rebound_raw_bytes_and_claims(prepared, attack):
    output, _ = prepared; manifest_path = output/'catalog_manifest.json'
    originals = {manifest_path:manifest_path.read_bytes()}
    try:
        value = json.loads(originals[manifest_path]); row = value['profiles'][0]
        if attack == 'order': value['profiles'].reverse()
        elif attack == 'omit': value['profiles'].pop()
        elif attack == 'bool_zero': value['optimizer_calls'] = False
        else:
            path = Path(row['specification' if attack == 'raw_specification' else 'raw_preparation']['path'])
            originals[path] = path.read_bytes(); changed = json.loads(originals[path])
            if attack == 'weaken_gate': changed['reference_policy']['retries'] = 1
            elif attack == 'diagnostic': changed['diagnostic_plans'].pop()
            else: changed['projects'][0]['base_annual_revenue_pence'] += 1
            path.write_text(json.dumps(changed))
            row['specification' if attack == 'raw_specification' else 'raw_preparation'] = entry.reference(path)
        manifest_path.write_text(json.dumps(value))
        with pytest.raises(ValueError): entry.validate_prepared(output)
    finally:
        for path, raw in originals.items(): path.write_bytes(raw)


def test_generation_reads_no_result_artifact_inputs_or_runtime_arguments():
    configuration = candidates.load_catalog()
    assert set(configuration) == {'kind','version','catalog_id','generation_policy','profile_order',
        'profiles','selection_density_admission','reference_policy','candidate_scope'}
    assert all(set(row) == {'profile_id','seed','revenue_jitter_pence'} for row in configuration['profiles'])
    # There is no CLI source of candidate lists, seeds, spreads or result paths.
    cli = ast.parse(Path(entry.__file__).read_text())
    flags = [node.args[0].value for node in ast.walk(cli) if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute) and node.func.attr == 'add_argument']
    assert flags == ['--output', '--validate-only']

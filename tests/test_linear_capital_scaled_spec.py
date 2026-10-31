"""Version-two identity, full N360 dimensions and unchanged financial contract."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
from pathlib import Path

import pytest

from sheets_factory.workbook.linear_capital_portfolio import spec as original
from sheets_factory.workbook.linear_capital_scaled import spec


def fixture(*, production=False):
    """Complete raw test inputs only; no ledger, optimizer or external service."""
    ids = list(spec.PROJECT_IDS) if production else ['P001', 'P002', 'P003']
    years = list(spec.YEARS) if production else [1, 2, 3]
    scenarios = list(spec.SCENARIO_IDS) if production else ['S01', 'S02']
    resources = list(spec.RESOURCE_IDS) if production else ['U01', 'U02']
    regions = list(spec.REGION_IDS) if production else ['R01']
    sectors = list(spec.SECTOR_IDS) if production else ['C01']
    annual = lambda value: {str(year): value for year in years}
    stressed = lambda value: {sid: annual(value) for sid in scenarios}
    projects = []
    for index, pid in enumerate(ids):
        projects.append({'id': pid, 'name': 'Dimension test '+pid,
            'region': regions[index % len(regions)], 'sector': sectors[index % len(sectors)],
            'asset_cost_pence': 100+index, 't0_ltv_bp': 5000, 'operating_start_year': 1,
            'depreciation_years': 3, 'base_annual_revenue_pence': 50,
            'base_annual_opex_pence': 10, 'revenue_growth_factor_bp': 10000,
            'opex_growth_factor_bp': 10000, 'bank_rate_bp': 500,
            'debt_policy': 'LEVEL_PRINCIPAL', 'debt_maturity_year': len(years),
            'tax_rate_bp': 2500, 'discount_rate_bp': 700,
            'terminal_sale_proceeds_pence': 20, 'lp_commitment_pence': 10000,
            'resource_usage_units': {resource: stressed(1+index) for resource in resources}})
    groups = ([{'id': f'SITE{i+1:02d}', 'description': 'Three alternative test assets',
        'project_ids': ids[180+3*i:183+3*i]} for i in range(60)] if production else
        [{'id': 'SITE', 'description': 'Two alternative test assets', 'project_ids': ids[1:]}])
    edges = ([{'id': f'LINK{i+1:03d}', 'dependent': ids[60+i],
        'prerequisite': ids[i % 60], 'business_reason': 'Test asset needs a separate connection'}
        for i in range(120)] if production else
        [{'id': 'LINK', 'dependent': ids[1], 'prerequisite': ids[0],
            'business_reason': 'Test asset needs a separate connection'}])
    return {'kind': spec.SPEC_KIND, 'version': spec.SPEC_VERSION,
        'dimension_mode': 'production' if production else 'toy', 'fiscal_year_start': 2027,
        'project_ids': ids, 'years': years, 'scenario_ids': scenarios,
        'resource_ids': resources, 'region_ids': regions, 'sector_ids': sectors,
        'projects': projects, 'scenarios': [{'id': sid, 'name': 'Test '+sid,
            'revenue_factors_bp': annual(10000), 'opex_factors_bp': annual(10000),
            'sale_factors_bp': annual(10000), 'interest_spread_bp': annual(0)} for sid in scenarios],
        'shared_limits': {'initial_sponsor_equity_pence': 100000,
            'annual_new_lp_pence': stressed(100000), 'annual_debt_close_pence': stressed(100000),
            'resource_capacity_units': {resource: stressed(100000) for resource in resources},
            'region_exposure_pence': {region: annual(100000) for region in regions},
            'sector_exposure_pence': {sector: annual(100000) for sector in sectors}},
        'exclusivity_groups': groups, 'prerequisites': edges,
        'provenance': {'hypothetical': True, 'ancestor_sha256': [],
            'description': 'Raw in-memory dimension consistency test; never a source candidate'}}


def test_only_five_identity_and_dimension_expressions_differ_from_original_contract():
    raw = spec.upstream_path().read_bytes()
    assert hashlib.sha256(raw).hexdigest() == spec.UPSTREAM_SHA256
    before = ast.parse(raw)
    after = spec.adapted_ast()
    changes = {
        "tuple((f'P{i:03d}' for i in range(1, 361)))":
            "tuple((f'P{i:03d}' for i in range(1, 241)))",
        "s['version'] == 2": "s['version'] == 1",
        "s['kind'] == 'hypothetical_ringfenced_linear_capital_portfolio_scaled'":
            "s['kind'] == 'hypothetical_ringfenced_linear_capital_portfolio'",
        'len(groups) == 60': 'len(groups) == 40',
        'len(edges) == 120': 'len(edges) == 80',
    }
    # Match normalized ASTs rather than depending on Python's source formatter.
    changes = {ast.dump(ast.parse(k, mode='eval').body): ast.parse(v, mode='eval').body
        for k, v in changes.items()}
    replaced = []
    class Restore(ast.NodeTransformer):
        def generic_visit(self, node):
            key = ast.dump(node)
            if key in changes:
                replaced.append(key)
                return deepcopy(changes[key])
            return super().generic_visit(node)
    restored = Restore().visit(after)
    assert len(replaced) == 5 and len(set(replaced)) == 5
    assert ast.dump(restored) == ast.dump(before)
    for name in ('BP', 'EXACT_LIMIT', 'PROJECT_MONEY_LIMIT', 'PORTFOLIO_MONEY_LIMIT',
        'T0_FIELDS', 'ANNUAL_FIELDS', 'VINTAGE_FIELDS', 'GROUP_FIELDS', 'RULES'):
        assert getattr(spec, name) == getattr(original, name)
    assert len(original.PROJECT_IDS) == 240 and len(spec.PROJECT_IDS) == 360


@pytest.mark.parametrize('production,expected', [(False, 33), (True, 941)])
def test_complete_dimension_tables_validate_and_row_census_is_exact(production, expected):
    raw = fixture(production=production); public = spec.load_spec(raw)
    assert spec.expected_constraint_count(public) == expected
    assert public == raw and public is not raw
    if production:
        assert spec.DIMENSIONS == {'projects':360,'scenarios':3,'years':20,'resources':6,
            'regions':6,'sectors':8,'exclusivity_groups':60,'prerequisites':120}
        assert spec.PRODUCTION_ROW_COUNT == sum(spec.PRODUCTION_COUNTS.values()) == expected
    else:
        assert spec.validate_plan(public, {'P003':0,'P001':1,'P002':0}) == {
            'P001':1,'P002':0,'P003':0}
    public['projects'][0]['asset_cost_pence'] += 1
    assert public != raw


@pytest.mark.parametrize('attack', ['old_version','old_kind','missing_project','missing_group',
    'missing_edge','missing_resource_date','missing_capacity_date','overlap','cycle','boolean_money'])
def test_production_identity_completeness_relationship_and_numeric_gates_remain_strict(attack):
    value = fixture(production=True)
    if attack == 'old_version': value['version'] = 1
    elif attack == 'old_kind': value['kind'] = 'hypothetical_ringfenced_linear_capital_portfolio'
    elif attack == 'missing_project': value['project_ids'].pop(); value['projects'].pop()
    elif attack == 'missing_group': value['exclusivity_groups'].pop()
    elif attack == 'missing_edge': value['prerequisites'].pop()
    elif attack == 'missing_resource_date': del value['projects'][-1]['resource_usage_units']['U06']['S03']['20']
    elif attack == 'missing_capacity_date': del value['shared_limits']['resource_capacity_units']['U06']['S03']['20']
    elif attack == 'overlap': value['exclusivity_groups'][1]['project_ids'][0] = value['exclusivity_groups'][0]['project_ids'][0]
    elif attack == 'cycle':
        edge = value['prerequisites'][0]
        value['prerequisites'][1].update(dependent=edge['prerequisite'], prerequisite=edge['dependent'])
    elif attack == 'boolean_money': value['projects'][-1]['asset_cost_pence'] = True
    with pytest.raises(ValueError): spec.load_spec(value)


@pytest.mark.parametrize('plan', [{'P001':1}, {'P001':True,'P002':0,'P003':0},
    {'P001':1,'P002':0,'P003':2}, {'P001':1,'P002':0,'P003':0,'P004':0}])
def test_complete_binary_plan_gate_is_unchanged(plan):
    with pytest.raises(ValueError, match='complete integer binary'): spec.validate_plan(fixture(), plan)


def test_old_and_new_versions_cannot_enter_each_others_contracts():
    new = fixture(); old = deepcopy(new)
    old.update(version=1, kind='hypothetical_ringfenced_linear_capital_portfolio')
    assert original.load_spec(old) == old
    assert spec.load_spec(new) == new
    with pytest.raises(ValueError, match='Unknown portfolio'): original.load_spec(new)
    with pytest.raises(ValueError, match='Unknown portfolio'): spec.load_spec(old)


def test_native_bundle_can_use_exact_vendored_source_and_rejects_any_drift(tmp_path):
    adapter = tmp_path/'spec.py'; upstream = tmp_path/'frozen_spec.py'
    adapter.write_bytes(Path(spec.__file__).read_bytes())
    upstream.write_bytes(spec.upstream_path().read_bytes())
    def load(name):
        definition = importlib.util.spec_from_file_location(name, adapter)
        result = importlib.util.module_from_spec(definition)
        definition.loader.exec_module(result)
        return result
    bundled = load('_n360_bundled_spec')
    assert bundled.upstream_path() == upstream
    assert bundled.load_spec(fixture(production=True))['project_ids'][-1] == 'P360'
    upstream.write_bytes(upstream.read_bytes()+b'\n')
    with pytest.raises(ValueError, match='differs'): load('_n360_drifted_spec')

"""A Decimal journal produces toy CSVs for the separate integer interpreter."""
import ast
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import struct

import pytest

from sheets_factory.workbook.capital_allocation import verify
from sheets_factory.workbook.capital_allocation.ledger import simulate
from sheets_factory.workbook.capital_allocation.spec import (
    ANNUAL_FIELDS, PROJECT_IDS, RAW_ANCESTORS, SCALE, SCENARIO_IDS, YEARS,
)


def annual(value):
    return {str(year): value for year in YEARS}


def public_spec():
    projects = []
    for index, identifier in enumerate(PROJECT_IDS):
        commission, sale = 2024 + index % 3, 2028 + index % 4
        projects.append({'id': identifier, 'commission_year': commission, 'sale_year': sale,
            'acquisition_cost_pence': 120 + 25 * index, 'depreciation_years': 3 + index % 3,
            'annual_revenue_pence': {str(y): 40 + 3 * index if commission < y <= sale else 0 for y in YEARS},
            'annual_opex_pence': {str(y): 20 + index if commission < y <= sale else 0 for y in YEARS},
            'sale_proceeds_pence': 90 + index * 3})
    scenarios = []
    for index, identifier in enumerate(SCENARIO_IDS):
        scenarios.append({'id': identifier,
            'revenue_factors_p12': annual(SCALE if index != 1 else SCALE * 7 // 10),
            'opex_factors_p12': annual(SCALE if index != 2 else SCALE * 13 // 10),
            'nav_factors_p12': annual(SCALE if index != 1 else SCALE * 8 // 10),
            'sale_factors_p12': annual(SCALE if index != 1 else SCALE * 7 // 10),
            'bank_rates_p12': annual(SCALE // 10),
            'haircuts_p12': {**annual(0), '2026': SCALE * 9 // 10}})
    return {'schema_version': 1, 'currency': 'GBP', 'monetary_unit': 'pence', 'years': list(YEARS),
        'opening_cash_pence': 300, 'minimum_cash_pence': 10, 'lp_commitment_pence': 600,
        'facility_limit_pence': 500, 'advance_rate_p12': SCALE * 3 // 4,
        'tax_rate_p12': SCALE // 4, 'tax_loss_carry_years': 2,
        'discount_factors_p12': {str(y): SCALE - 25_000_000_000 * (y - 2023) for y in YEARS},
        'projects': projects, 'scenarios': scenarios,
        'provenance': {'kind': 'synthetic_capital_allocation_extension', 'raw_ancestors': deepcopy(RAW_ANCESTORS)}}


def decimal_record(spec, mask, active):
    full_mask = sum(1 << PROJECT_IDS.index(identifier) for bit, identifier in enumerate(active) if mask & (1 << bit))
    plan = {identifier: int(bool(full_mask & (1 << bit))) for bit, identifier in enumerate(PROJECT_IDS)}
    result = simulate(spec, plan)
    row = {'mask': str(mask), 'full_mask': str(full_mask)}
    for identifier in SCENARIO_IDS:
        scenario = result['scenarios'][identifier]
        loss = {(item['year'], item['vintage']): item['closing'] for item in scenario['tax_vintages']}
        digest = hashlib.sha256()
        for frame in scenario['annual']:
            values = (frame['year'], *(frame[field] for field in ANNUAL_FIELDS),
                      *(loss[frame['year'], vintage] for vintage in YEARS))
            digest.update(struct.pack('<' + 'q' * len(values), *values))
        flags = 0
        for failure in scenario['violations']:
            flags |= {'unfunded_cash_deficiency': 1, 'terminal_bank_debt': 2,
                      'terminal_project_assets': 4, 'terminal_cash': 8}[failure['kind']]
        prefix = identifier + '_'
        row.update({prefix + 'feasible': str(int(scenario['feasible'])),
            prefix + 'npv_pence': '' if scenario['npv_pence'] is None else str(scenario['npv_pence']),
            prefix + 'path_sha256': digest.hexdigest(),
            prefix + 'first_violation_year': '' if not scenario['violations'] else str(scenario['violations'][0]['year']),
            prefix + 'violation_mask': str(flags)})
    row.update(feasible=str(int(result['feasible'])),
        objective_pence='' if result['objective_pence'] is None else str(result['objective_pence']))
    return row


def make_decimal_csv(path, spec, active):
    rows = [decimal_record(spec, mask, active) for mask in range(1 << len(active))]
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=verify.CSV_FIELDS, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    return rows


def read_receipt(reference):
    return json.loads(Path(reference['path']).read_text())


@pytest.mark.parametrize('mask', [0, 1, 5, 341, 4095, 2**18 - 1])
def test_independent_integer_all_annual_fields_and_loss_vintages_match_decimal(mask):
    spec = public_spec()
    integer = verify.evaluate_plan(spec, mask, details=True)
    decimal = simulate(spec, {identifier: int(bool(mask & (1 << bit))) for bit, identifier in enumerate(PROJECT_IDS)})
    assert integer['feasible'] == decimal['feasible']
    assert integer['objective_pence'] == decimal['objective_pence']
    for actual in integer['scenarios']:
        expected = decimal['scenarios'][actual['id']]
        assert actual['npv_pence'] == expected['npv_pence']
        assert actual['net_npv_numerator'] == expected['net_npv_numerator']
        losses = {(r['year'], r['vintage']): r['closing'] for r in expected['tax_vintages']}
        for row, reference in zip(actual['annual'], expected['annual']):
            assert {key: value for key, value in row.items() if key != 'closing_loss_vintages'} == reference
            assert row['closing_loss_vintages'] == [losses[row['year'], vintage] for vintage in YEARS]


def test_full_toy_csv_is_byte_identical_and_cannot_admit_eighteen_bit_source(tmp_path):
    spec = public_spec()
    active = ['P01', 'P03', 'P07']
    source = tmp_path / 'decimal_plans.csv'
    rows = make_decimal_csv(source, spec, active)
    receipt = read_receipt(verify.verify_search(spec, source, tmp_path / 'verified', active_project_ids=active))
    assert receipt['passed'] is True
    assert receipt['full_enumeration'] is False and receipt['toy_only'] is True
    assert receipt['plan_count'] == 8 and receipt['scenario_year_evaluations'] == 480
    assert receipt['source_admissible_unique_optimum'] is False
    assert Path(receipt['python_plans']['path']).read_bytes() == source.read_bytes()
    assert receipt['python_plans']['sha256'] == receipt['cpp_plans']['sha256']
    feasible = [(int(row['objective_pence']), int(row['mask'])) for row in rows if row['feasible'] == '1']
    feasible.sort(key=lambda pair: (-pair[0], pair[1]))
    assert receipt['feasible_count'] == len(feasible)
    if feasible:
        assert receipt['objective_pence'] == feasible[0][0]
        assert receipt['best_mask'] == feasible[0][1]
    if len(feasible) > 1:
        assert receipt['runnerup_objective_pence'] == feasible[1][0]
        assert receipt['runnerup_mask'] == feasible[1][1]
        assert receipt['gap_pence'] == feasible[0][0] - feasible[1][0]


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'reordered', 'objective', 'path', 'flags', 'extra', 'header'])
def test_every_mask_and_its_complete_financial_path_is_required(tmp_path, fault):
    spec, active = public_spec(), ['P01', 'P02']
    source = tmp_path / 'plans.csv'
    rows = make_decimal_csv(source, spec, active)
    fields = list(verify.CSV_FIELDS)
    if fault == 'missing': rows.pop()
    elif fault == 'duplicate': rows[2] = deepcopy(rows[1])
    elif fault == 'reordered': rows[1], rows[2] = rows[2], rows[1]
    elif fault == 'objective': rows[1]['objective_pence'] = '987654321'
    elif fault == 'path': rows[1]['S02_path_sha256'] = '0' * 64
    elif fault == 'flags': rows[1]['S01_violation_mask'] = '8'
    elif fault == 'extra': rows.append(deepcopy(rows[0]))
    else: fields.reverse()
    with source.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)
    output = tmp_path / 'failed'
    with pytest.raises(ValueError, match='verification failed'):
        verify.verify_search(spec, source, output, active_project_ids=active)
    receipt = json.loads((output / 'verification_receipt.json').read_text())
    assert receipt['passed'] is False and receipt['full_enumeration'] is False
    assert receipt['unique_best'] is False
    assert receipt['source_admissible_unique_optimum'] is False
    assert source.exists() and (output / 'python_plans.csv').exists()


def test_equal_objective_has_no_hidden_mask_tie_break_or_unique_claim(tmp_path):
    spec = public_spec()
    # P01 returns its acquisition cost at the same fiscal end via proceeds,
    # and has no operating cash flows; zero discount preserves a genuine tie.
    project = spec['projects'][0]
    project.update(annual_revenue_pence=annual(0), annual_opex_pence=annual(0),
                   sale_proceeds_pence=project['acquisition_cost_pence'])
    spec['tax_rate_p12'] = 0
    spec['discount_factors_p12'] = annual(SCALE)
    for scenario in spec['scenarios']:
        scenario['sale_factors_p12'] = annual(SCALE)
        scenario['bank_rates_p12'] = annual(0)
    source = tmp_path / 'ties.csv'
    make_decimal_csv(source, spec, ['P01'])
    receipt = read_receipt(verify.verify_search(spec, source, tmp_path / 'ties', active_project_ids=['P01']))
    assert receipt['passed']
    assert receipt['best_count'] == 2 and receipt['gap_pence'] == 0
    assert receipt['unique_best'] is False and receipt['best_plan'] is None


@pytest.mark.parametrize('annual_total,factor,expected', [(2, SCALE // 4, -1), (3, SCALE // 2, 1)])
def test_independent_signed_net_npv_round_includes_time_zero(annual_total, factor, expected):
    spec = public_spec()
    spec.update(opening_cash_pence=1, minimum_cash_pence=0)
    spec['tax_rate_p12'] = 0
    spec['discount_factors_p12'] = annual(factor)
    project = spec['projects'][0]
    project.update(commission_year=2024, sale_year=2026, acquisition_cost_pence=1,
        depreciation_years=1, sale_proceeds_pence=0,
        annual_revenue_pence={**annual(0), '2025': 1, '2026': annual_total - 1}, annual_opex_pence=annual(0))
    for scenario in spec['scenarios']:
        scenario['revenue_factors_p12'] = annual(SCALE)
        scenario['opex_factors_p12'] = annual(SCALE)
    assert verify.evaluate_plan(spec, 1)['objective_pence'] == expected


def test_interpreter_imports_no_decimal_journal_search_or_precompiled_cache():
    tree = ast.parse(Path(verify.__file__).read_text())
    names = [node.module or '' for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    names += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
    assert not any('ledger' in name or 'search' in name or 'decimal' in name for name in names)


def test_existing_verification_directory_is_not_overwritten(tmp_path):
    spec = public_spec()
    source = tmp_path / 'plans.csv'
    make_decimal_csv(source, spec, [])
    output = tmp_path / 'verified'
    verify.verify_search(spec, source, output, active_project_ids=[])
    before = (output / 'verification_receipt.json').read_bytes()
    with pytest.raises(ValueError, match='fresh'):
        verify.verify_search(spec, source, output, active_project_ids=[])
    assert (output / 'verification_receipt.json').read_bytes() == before

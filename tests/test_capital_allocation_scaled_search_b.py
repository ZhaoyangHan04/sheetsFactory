"""Independent B kernel toy calibration. Never execute a full18+ choice run."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess

import pytest

from sheets_factory.workbook.capital_allocation_scaled import search_b as kernel
from sheets_factory.workbook.capital_allocation_scaled import spec as schema
from sheets_factory.workbook.capital_allocation.ledger import simulate

ROOT = Path(__file__).resolve().parents[1]
_module = importlib.util.spec_from_file_location('_independent_decimal_calibration', ROOT / 'tests/test_capital_allocation_verify.py')
hand = importlib.util.module_from_spec(_module); _module.loader.exec_module(hand)


def read(record): return json.loads(Path(record['path']).read_text())


def run(spec, output, active):
    prepared = kernel.prepare(spec, output, active_project_ids=active)
    result = read(kernel.execute_prepared(prepared, timeout_seconds=60))
    assert result['status'] == 'completed' and result['toy_only'] is True
    assert result['full_enumeration'] is False and result['plan_count'] <= 256
    return result


def decimal_records(spec, active):
    result = bytearray()
    for mask in range(1 << len(active)):
        plan = {project['id']: int(project['id'] in active and bool(mask & (1 << active.index(project['id'])))) for project in spec['projects']}
        journal = simulate(spec, plan); values, flags = [], 0
        for index, scenario in enumerate(schema.SCENARIO_IDS):
            state = journal['scenarios'][scenario]
            if state['feasible']: flags |= 1 << index
            values.append(state['npv_pence'] if state['feasible'] else schema.NULL_NPV)
        result.extend(struct.pack('<IIqqq', mask, flags, *values))
    return bytes(result)


def test_prepare_and_full_run_guard_execute_no_compiler_or_financial_calculation(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs): raise AssertionError('Preparation must not execute a process')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    ref = kernel.prepare(hand.public_spec(), tmp_path / 'prepared')
    frozen, public = kernel.validate_prepared(ref)
    assert frozen['expected_plan_count'] == 262144 and frozen['full_enumeration'] is True
    assert frozen['compiler_calls'] == frozen['kernel_calls'] == 0
    assert frozen['spec_sha256'] == schema.canonical_sha(public)
    with pytest.raises(ValueError, match='allow_full'): kernel.execute_prepared(ref)
    assert not (tmp_path / 'prepared/execution').exists()


def test_two_half_256_plan_records_match_separate_Decimal_journal_exactly(tmp_path):
    public = hand.public_spec(); active = list(schema.project_ids(18)[:8])
    result = run(public, tmp_path / 'B', active)
    records = Path(result['records']['path']).read_bytes()
    expected = decimal_records(public, active)
    assert records == expected
    assert result['records'] == result['plans_binary']
    assert result['records']['sha256'] == hashlib.sha256(expected).hexdigest()
    assert result['record_format'] == '<IIqqq' and result['record_bytes'] == 32
    assert result['kernel_statistics']['method'] == 'independent_two_half_ordinal_subset_tables'
    assert result['kernel_statistics']['scenario_evaluations'] == 256 * 3
    assert 256 * 3 <= result['kernel_statistics']['scenario_year_evaluations'] <= 256 * 60
    assert result['kernel_statistics']['subset_table_bytes'] == 2 * (1 << 4) * 3 * 20 * 8 * 8
    assert result['chunks'] == [{'start_mask': 0, 'end_mask_exclusive': 256,
        'record_count': 256, 'bytes': 8192, 'sha256': hashlib.sha256(records).hexdigest()}]


def test_nonprefix_active_ids_map_ordinal_records_to_the_correct_full_projects(tmp_path):
    public = hand.public_spec(); active = ['P02', 'P04', 'P08']
    result = run(public, tmp_path / 'B', active)
    assert Path(result['records']['path']).read_bytes() == decimal_records(public, active)
    if result['unique_best']:
        full = sum(1 << (int(identifier[1:]) - 1) for bit, identifier in enumerate(active) if result['best_mask'] & (1 << bit))
        assert result['best_full_mask'] == full
        assert {name for name, choice in result['best_plan'].items() if choice} <= set(active)


@pytest.mark.parametrize('opening,contribution,df', [(1, 1, schema.SCALE // 2), (0, 1, schema.SCALE // 2), (2, 1, schema.SCALE // 2 + 1)])
def test_net_NPV_final_half_ties_and_t0_inside_rounding(tmp_path, opening, contribution, df):
    public = hand.public_spec(); public['opening_cash_pence'] = opening; public['minimum_cash_pence'] = 0
    public['lp_commitment_pence'] = contribution; public['facility_limit_pence'] = 0
    public['discount_factors_p12'] = dict.fromkeys(map(str, schema.YEARS), df)
    public['tax_rate_p12'] = 0
    project = public['projects'][0]
    project.update(commission_year=2024, sale_year=2025, acquisition_cost_pence=1,
        depreciation_years=4, sale_proceeds_pence=1,
        annual_revenue_pence=dict.fromkeys(map(str, schema.YEARS), 0), annual_opex_pence=dict.fromkeys(map(str, schema.YEARS), 0))
    result = run(public, tmp_path / 'B', ['P01'])
    assert Path(result['records']['path']).read_bytes() == decimal_records(public, ['P01'])


def test_tax_FIFO_expiry_depreciation_residual_and_three_factor_base_round_only_once(tmp_path):
    public = hand.public_spec()
    public['tax_loss_carry_years'] = 1; public['advance_rate_p12'] = schema.SCALE // 2 + 1
    public['opening_cash_pence'] = 30; public['minimum_cash_pence'] = 2; public['lp_commitment_pence'] = 1000
    project = public['projects'][0]
    project.update(acquisition_cost_pence=2, depreciation_years=4,
        annual_revenue_pence={str(y): (40 if y == 2028 else 0) for y in schema.YEARS},
        annual_opex_pence={str(y): (3 if y in (2025, 2026) else 0) for y in schema.YEARS}, sale_proceeds_pence=3)
    for scenario in public['scenarios']:
        scenario['haircuts_p12']['2026'] = schema.SCALE // 2 - 1
    result = run(public, tmp_path / 'B', ['P01', 'P02'])
    assert Path(result['records']['path']).read_bytes() == decimal_records(public, ['P01', 'P02'])


def test_infeasible_plans_have_explicit_nulls_without_claiming_future_year_execution(tmp_path):
    public = hand.public_spec(); public.update(opening_cash_pence=0, minimum_cash_pence=0,
        lp_commitment_pence=0, facility_limit_pence=0)
    result = run(public, tmp_path / 'B', ['P01', 'P02'])
    rows = list(struct.iter_unpack('<IIqqq', Path(result['records']['path']).read_bytes()))
    assert rows[0] == (0, 7, 0, 0, 0)
    assert all(row[1:] == (0, schema.NULL_NPV, schema.NULL_NPV, schema.NULL_NPV) for row in rows[1:])
    # P01 fails in FY2024, P02 commissions and first fails in FY2025;
    # selecting both fails at the earlier FY2024 cash call.
    assert result['kernel_statistics']['scenario_year_evaluations'] == 60 + 3 + 6 + 3
    assert result['feasible_count'] == 1 and result['gap_pence'] is None


def test_ties_return_no_selected_plan_and_no_implicit_mask_tie_break(tmp_path):
    public = hand.public_spec(); public['discount_factors_p12'] = dict.fromkeys(map(str, schema.YEARS), schema.SCALE)
    public['tax_rate_p12'] = 0; public['opening_cash_pence'] = 1000; public['lp_commitment_pence'] = 1000
    for scenario in public['scenarios']:
        scenario['bank_rates_p12'] = dict.fromkeys(map(str, schema.YEARS), 0)
        scenario['sale_factors_p12'] = dict.fromkeys(map(str, schema.YEARS), schema.SCALE)
    for project in public['projects']:
        project['annual_revenue_pence'] = dict.fromkeys(map(str, schema.YEARS), 0)
        project['annual_opex_pence'] = dict.fromkeys(map(str, schema.YEARS), 0)
        project['sale_proceeds_pence'] = project['acquisition_cost_pence']
    result = run(public, tmp_path / 'B', ['P01', 'P02'])
    assert result['best_count'] == 4 and result['unique_best'] is False and result['gap_pence'] == 0
    assert result['best_plan'] is result['best_full_mask'] is None
    assert result['nonunique_best_mask_is_diagnostic_not_a_selected_plan'] is True


@pytest.mark.parametrize('count', [26, 28, 30])
def test_larger_public_dimensions_are_prepared_but_only_one_active_bit_is_executed(tmp_path, count):
    public = hand.public_spec()
    for index in range(18, count): public['projects'].append({**deepcopy(public['projects'][0]), 'id': f'P{index + 1:02d}'})
    result = run(public, tmp_path / 'B', [f'P{count:02d}'])
    reference = hand.public_spec(); reference['projects'][0] = deepcopy(public['projects'][-1]); reference['projects'][0]['id'] = 'P01'
    assert Path(result['records']['path']).read_bytes() == decimal_records(reference, ['P01'])
    assert result['plan_count'] == 2 and result['project_count'] == count


@pytest.mark.parametrize('fault', ['truncated', 'extra', 'wrong_mask', 'unknown_flag', 'null_disagrees', 'false_feasible'])
def test_complete_record_scan_rejects_partial_or_falsely_typed_coverage(tmp_path, fault):
    public = hand.public_spec(); records = bytearray(struct.pack('<IIqqq', 0, 7, 0, 0, 0) + struct.pack('<IIqqq', 1, 0, *([schema.NULL_NPV] * 3)))
    if fault == 'truncated': records.pop()
    if fault == 'extra': records.extend(bytes(32))
    if fault == 'wrong_mask': records[32:36] = struct.pack('<I', 0)
    if fault == 'unknown_flag': records[4:8] = struct.pack('<I', 15)
    if fault == 'null_disagrees': records[8:16] = struct.pack('<q', schema.NULL_NPV)
    if fault == 'false_feasible': records[36:40] = struct.pack('<I', 1)
    path = tmp_path / 'records.bin'; path.write_bytes(records)
    with pytest.raises(ValueError): kernel.scan_records(path, public, ['P01'])


def test_maximum_primitive_amounts_use_wide_integer_products(tmp_path):
    public = hand.public_spec(); public.update(opening_cash_pence=10**11, minimum_cash_pence=10**11,
        lp_commitment_pence=10**11, facility_limit_pence=10**11, advance_rate_p12=schema.SCALE - 1)
    project = public['projects'][0]; project.update(acquisition_cost_pence=10**9, sale_proceeds_pence=10**9)
    for scenario in public['scenarios']:
        for field in ('revenue_factors_p12', 'opex_factors_p12', 'nav_factors_p12', 'sale_factors_p12'):
            scenario[field] = dict.fromkeys(map(str, schema.YEARS), 3 * schema.SCALE)
        scenario['bank_rates_p12'] = dict.fromkeys(map(str, schema.YEARS), schema.SCALE - 1)
    result = run(public, tmp_path / 'B', ['P01'])
    assert Path(result['records']['path']).read_bytes() == decimal_records(public, ['P01'])


def test_B_implementation_has_no_A_or_old_financial_helper_dependency():
    tree = ast.parse(Path(kernel.__file__).read_text())
    imports = [(node.module or '') for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert imports == ['__future__', 'datetime', 'pathlib', '']
    assert all(word not in Path(kernel.__file__).read_text() for word in ('import search_a', 'capital_allocation.ledger', 'capital_allocation.verify'))
    cpp = kernel.KERNEL.read_text()
    assert 'half_table' in cpp and '__int128_t' in cpp
    assert 'Gray' in cpp  # the comment identifies why its ordinal DP is independent
    assert not any('#include "' + name in cpp for name in ('search_a', 'ledger', 'verify'))


def test_preparation_raw_wire_tampering_is_rejected_before_execution(tmp_path):
    ref = kernel.prepare(hand.public_spec(), tmp_path / 'B', active_project_ids=['P01'])
    frozen = read(ref); Path(frozen['raw_wire']['path']).write_text('not the public contract')
    with pytest.raises(ValueError, match='wire'): kernel.validate_prepared(ref)

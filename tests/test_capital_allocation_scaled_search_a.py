"""Small active-subset enumeration only; never a full18/26/28/30 run."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import random
import struct

import pytest

from sheets_factory.workbook.capital_allocation_scaled import spec, search_a
from sheets_factory.workbook.capital_allocation.ledger import simulate

ROOT = Path(__file__).resolve().parents[1]
fixture_spec = importlib.util.spec_from_file_location('scaled_A_hand_fixture', ROOT / 'tests/test_capital_allocation_ledger.py')
hand = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(hand)


@pytest.fixture(scope='module')
def compiled(tmp_path_factory):
    return search_a.compile_kernel(tmp_path_factory.mktemp('scaled_A') / 'compile')


def run(public, tmp_path, compiled, ids=('P01',)):
    reference = search_a.enumerate_plans(public, tmp_path / 'enumeration', active_project_ids=ids, compilation=compiled)
    receipt = json.loads(Path(reference['path']).read_text())
    rows = list(search_a.read_records(receipt['records']['path']))
    return receipt, rows


def compare_decimal(public, rows, ids):
    for mask, flags, *values in rows:
        plan = {p['id']: int(p['id'] in ids and bool(mask & (1 << ids.index(p['id'])))) for p in public['projects']}
        independent = simulate(public, plan)
        expected_flags = 0
        for si, sid in enumerate(spec.SCENARIO_IDS):
            s = independent['scenarios'][sid]
            if s['feasible']:
                expected_flags |= 1 << si
                assert values[si] == s['npv_pence']
            else:
                assert values[si] == spec.NULL_NPV
        assert flags == expected_flags


def test_hand_pence_tax_and_complete_active_toy_records(tmp_path, compiled):
    public = hand.specification()
    public['tax_rate_p12'] = spec.SCALE // 4
    receipt, rows = run(public, tmp_path, compiled, ('P01', 'P18'))
    assert rows == [(0, 7, 0, 0, 0), (1, 7, 30, 30, 30), (2, 7, 30, 30, 30), (3, 7, 60, 60, 60)]
    assert receipt['best_mask'] == 3 and receipt['best_full_mask'] == (1 | (1 << 17))
    assert receipt['objective_pence'] == 60 and receipt['runnerup_mask'] == 1 and receipt['gap_pence'] == 30
    assert receipt['best_plan']['P18'] == receipt['best_plan']['P01'] == 1
    assert receipt['toy_only'] is True and receipt['full_enumeration'] is False
    assert receipt['independent_comparison_completed'] is False and receipt['source_admission_certified'] is False
    assert receipt['records']['bytes'] == 4 * 32
    compare_decimal(public, rows, ('P01', 'P18'))


@pytest.mark.parametrize('opening,second,factor,expected', [(1, 1, spec.SCALE // 4, -1),
    (1, 2, spec.SCALE // 2, 1), (1, 1, spec.SCALE // 2, 0)])
def test_negative_half_t0_is_inside_sole_rounding(tmp_path, compiled, opening, second, factor, expected):
    public = hand.specification()
    public['opening_cash_pence'] = opening
    public['discount_factors_p12'] = hand.annual(factor)
    public['projects'][0].update(acquisition_cost_pence=1, depreciation_years=1,
        annual_revenue_pence={**hand.annual(0), '2025': 1, '2026': second}, annual_opex_pence=hand.annual(0))
    _, rows = run(public, tmp_path, compiled)
    assert rows[1][2:] == (expected,) * 3
    compare_decimal(public, rows, ('P01',))


def test_real_margin_gap_null_encoding_and_all_scenarios_evaluated(tmp_path, compiled):
    public = hand.financed_spec()
    public['lp_commitment_pence'] = 100
    public['scenarios'][0]['haircuts_p12'] = hand.annual(0)
    _, rows = run(public, tmp_path, compiled)
    assert rows[1][1] == 1  # S01 feasible; S02/S03 fail their actual margin calls.
    assert rows[1][3:] == (spec.NULL_NPV,) * 2
    compare_decimal(public, rows, ('P01',))


def test_fifo_expiry_round_once_collateral_and_clamped_depreciation(tmp_path, compiled):
    public = hand.specification()
    public['facility_limit_pence'] = 0
    public['tax_rate_p12'] = spec.SCALE // 2
    public['projects'][0].update(acquisition_cost_pence=1, depreciation_years=1, sale_year=2029,
        annual_revenue_pence={**hand.annual(0), '2027': 15, '2029': 20},
        annual_opex_pence={**hand.annual(0), '2025': 9, '2026': 20})
    public['projects'][1].update(acquisition_cost_pence=2, depreciation_years=4, sale_year=2029,
        annual_revenue_pence=hand.annual(0), annual_opex_pence=hand.annual(0))
    _, rows = run(public, tmp_path, compiled, ('P01', 'P02'))
    assert rows[1][2] == -5
    compare_decimal(public, rows, ('P01', 'P02'))


def test_collateral_product_has_one_posting_not_two(tmp_path, compiled):
    public = hand.specification()
    public['advance_rate_p12'] = spec.SCALE // 2
    public['projects'][0].update(acquisition_cost_pence=1, depreciation_years=20,
        annual_revenue_pence=hand.annual(0), annual_opex_pence={**hand.annual(0), '2025': 1})
    for scenario in public['scenarios']:
        scenario['haircuts_p12'] = hand.annual(spec.SCALE // 2)
    _, rows = run(public, tmp_path, compiled)
    compare_decimal(public, rows, ('P01',))


@pytest.mark.parametrize('seed', [23, 42, 20261030])
def test_varied_raw_primitive_toy_all_masks_match_independent_Decimal(tmp_path, compiled, seed):
    rng = random.Random(seed)
    public = hand.specification()
    public.update(opening_cash_pence=300, minimum_cash_pence=25, lp_commitment_pence=1200,
        facility_limit_pence=2000, advance_rate_p12=7 * spec.SCALE // 10,
        tax_rate_p12=28 * spec.SCALE // 100, tax_loss_carry_years=3,
        discount_factors_p12={str(y): spec.SCALE - (y - 2024) * spec.SCALE // 40 for y in spec.YEARS})
    for project in public['projects']:
        commission = rng.randrange(2024, 2035)
        sale = rng.randrange(commission + 1, 2044)
        project.update(commission_year=commission, sale_year=sale,
            acquisition_cost_pence=rng.randrange(1, 800), depreciation_years=rng.randrange(1, 21),
            sale_proceeds_pence=rng.randrange(0, 1000),
            annual_revenue_pence={str(y): rng.randrange(0, 250) if commission < y <= sale else 0 for y in spec.YEARS},
            annual_opex_pence={str(y): rng.randrange(0, 200) if commission < y <= sale else 0 for y in spec.YEARS})
    for scenario in public['scenarios']:
        for field in ('revenue_factors_p12', 'opex_factors_p12', 'nav_factors_p12', 'sale_factors_p12'):
            scenario[field] = {str(y): rng.randrange(0, 3 * spec.SCALE + 1) for y in spec.YEARS}
        for field in ('bank_rates_p12', 'haircuts_p12'):
            scenario[field] = {str(y): rng.randrange(0, spec.SCALE + 1) for y in spec.YEARS}
    _, rows = run(public, tmp_path, compiled, ('P01', 'P03', 'P18'))
    compare_decimal(public, rows, ('P01', 'P03', 'P18'))


def test_declared_maximums_use_wide_products_without_overflow(tmp_path, compiled):
    public = hand.specification()
    public.update(opening_cash_pence=10**11, minimum_cash_pence=10**6, lp_commitment_pence=10**11,
        facility_limit_pence=10**11, advance_rate_p12=spec.SCALE-17, tax_rate_p12=spec.SCALE//3)
    for p in public['projects']:
        p.update(acquisition_cost_pence=10**9, sale_proceeds_pence=10**9, depreciation_years=20, sale_year=2043,
            annual_revenue_pence={str(y): 10**9 if y>2024 else 0 for y in spec.YEARS},
            annual_opex_pence={str(y): 10**9 if y>2024 else 0 for y in spec.YEARS})
    for s in public['scenarios']:
        for field in ('revenue_factors_p12','opex_factors_p12','nav_factors_p12','sale_factors_p12'):
            s[field]=hand.annual(3*spec.SCALE)
        s['bank_rates_p12']=hand.annual(spec.SCALE//10);s['haircuts_p12']=hand.annual(spec.SCALE//7)
    _, rows = run(public, tmp_path, compiled, ('P01', 'P18'))
    compare_decimal(public, rows, ('P01', 'P18'))


def test_ties_have_no_hidden_winner(tmp_path, compiled):
    public = hand.specification()
    for p in public['projects']:
        p.update(annual_revenue_pence=hand.annual(0), annual_opex_pence=hand.annual(0), sale_proceeds_pence=100)
    receipt, rows = run(public, tmp_path, compiled, ('P01', 'P02'))
    assert receipt['best_count'] == 4 and receipt['unique_best'] is False
    assert receipt['best_plan'] is receipt['best_full_mask'] is None and receipt['gap_pence'] == 0
    assert receipt['best_mask'] == 0 and receipt['runnerup_mask'] == 1  # Diagnostic order only.


@pytest.mark.parametrize('count', [18,26,28,30])
def test_supported_prospective_dimensions_only_small_active_subset(tmp_path, compiled, count):
    public = hand.specification()
    for i in range(18,count):
        p=deepcopy(public['projects'][0]);p['id']=f'P{i+1:02d}';public['projects'].append(p)
    assert spec.load_spec(public)==public
    receipt, rows=run(public,tmp_path,compiled,('P01',f'P{count:02d}'))
    assert [row[2] for row in rows]==[0,40,40,80]
    assert receipt['plan_count']==4 and receipt['project_count']==count
    assert receipt['best_plan'][f'P{count:02d}']==1


def test_eight_bit_toy_is_bounded256_not_full18(tmp_path, compiled):
    public=hand.specification()
    receipt,rows=run(public,tmp_path,compiled,tuple(f'P{i:02d}' for i in range(1,9)))
    assert len(rows)==256 and [r[0] for r in rows]==list(range(256))
    assert receipt['best_mask']==255 and receipt['objective_pence']==320
    assert receipt['gap_pence']==40 and receipt['runnerup_mask']==127


@pytest.mark.parametrize('change', [lambda p:p['projects'].pop(),lambda p:p.update(opening_cash_pence=True),
    lambda p:p['projects'][0].update(commission_year=2024.0),lambda p:p['scenarios'].reverse(),
    lambda p:p['projects'][0]['annual_revenue_pence'].update({'2024':1})])
def test_bad_public_contracts_reject(change):
    public=hand.specification();change(public)
    with pytest.raises(ValueError):spec.load_spec(public)


def test_prepare_is_zero_execution_and_full_requires_explicit_run(tmp_path,monkeypatch):
    public=hand.specification()
    with pytest.raises(ValueError,match='explicit'):
        search_a.enumerate_plans(public,tmp_path/'forbidden')
    assert not (tmp_path/'forbidden').exists()
    monkeypatch.setattr(search_a,'compile_kernel',lambda *a,**k:pytest.fail('Prepare cannot compile or execute'))
    reference=search_a.prepare(public,tmp_path/'prepared')
    prepared=json.loads(Path(reference['path']).read_text())
    assert prepared['enumeration_performed'] is False
    assert not list((tmp_path/'prepared').rglob('*.bin'))
    p=tmp_path/'prepared'/'public_spec.json';p.write_text('{}')
    with pytest.raises(ValueError,match='changed'):
        search_a.execute_prepared(tmp_path/'prepared')


@pytest.mark.parametrize('record', [(1,7,0,0,0),(0,8,0,0,0),(0,0,0,spec.NULL_NPV,spec.NULL_NPV)])
def test_binary_coverage_flags_and_null_integrity(tmp_path,record):
    p=tmp_path/'bad.bin';p.write_bytes(struct.pack(spec.RECORD_FORMAT,*record))
    with pytest.raises(ValueError):search_a.inspect_records(p,1)


def test_chunk_boundary_hashes_without_financial_enumeration(tmp_path):
    p=tmp_path/'synthetic_protocol_records.bin'
    with p.open('wb') as stream:
        for mask in range(spec.CHUNK_RECORDS+1):stream.write(struct.pack(spec.RECORD_FORMAT,mask,7,0,0,0))
    reference,chunks=search_a.inspect_records(p,spec.CHUNK_RECORDS+1)
    assert reference==search_a.reference(p)
    assert [c['record_count'] for c in chunks]==[65536,1]
    assert chunks[1]['start_mask']==65536 and chunks[1]['end_mask_exclusive']==65537


def test_no_shared_financial_calculation_imports_or_old_CPP_call():
    text=Path(search_a.__file__).read_text()
    cpp=search_a.SOURCE.read_text()
    assert 'capital_allocation.ledger' not in text and 'capital_allocation.search' not in text
    assert '#include "' not in cpp and 'search.cpp' not in cpp

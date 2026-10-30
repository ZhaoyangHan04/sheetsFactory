"""Toy exhaustive tests only.  No eighteen-bit run, workbook engine or model."""
from copy import deepcopy
import csv
import hashlib
import importlib
import json
from pathlib import Path
import random
import struct

import pytest

from sheets_factory.workbook.capital_allocation import search
from sheets_factory.workbook.capital_allocation.spec import (
    ANNUAL_FIELDS, PROJECT_IDS, RAW_ANCESTORS, SCALE, SCENARIO_IDS, YEARS,
)


def annual(value):
    return {str(year): value for year in YEARS}


def specification():
    return {
        'schema_version': 1, 'currency': 'GBP', 'monetary_unit': 'pence', 'years': list(YEARS),
        'opening_cash_pence': 1000, 'minimum_cash_pence': 0, 'lp_commitment_pence': 1000,
        'facility_limit_pence': 1000, 'advance_rate_p12': SCALE, 'tax_rate_p12': 0,
        'tax_loss_carry_years': 2, 'discount_factors_p12': annual(SCALE),
        'projects': [{
            'id': project, 'commission_year': 2024, 'sale_year': 2026,
            'acquisition_cost_pence': 100, 'depreciation_years': 2,
            'annual_revenue_pence': {**annual(0), '2025': 80, '2026': 80},
            'annual_opex_pence': {**annual(0), '2025': 10, '2026': 10},
            'sale_proceeds_pence': 0,
        } for project in PROJECT_IDS],
        'scenarios': [{
            'id': scenario, 'revenue_factors_p12': annual(SCALE),
            'opex_factors_p12': annual(SCALE), 'nav_factors_p12': annual(SCALE),
            'sale_factors_p12': annual(SCALE), 'bank_rates_p12': annual(0),
            'haircuts_p12': annual(0),
        } for scenario in SCENARIO_IDS],
        'provenance': {'kind': 'synthetic_capital_allocation_extension',
                       'raw_ancestors': deepcopy(RAW_ANCESTORS)},
    }


@pytest.fixture(scope='module')
def compilation(tmp_path_factory):
    directory = tmp_path_factory.mktemp('capital_cpp_parent') / 'compilation'
    return search.compile_search(directory)


def cpp(spec, directory, compilation, active=('P01',)):
    ref = search.enumerate_cpp(spec, directory, active_project_ids=active, compilation=compilation)
    receipt = json.loads(Path(ref['path']).read_text())
    with Path(receipt['plans_csv']['path']).open(newline='') as stream:
        records = list(csv.DictReader(stream))
    return ref, receipt, records


def check_independent(spec, receipt, directory):
    from sheets_factory.workbook.capital_allocation.verify import verify_search
    ref = verify_search(spec, receipt['plans_csv']['path'], directory,
                        active_project_ids=receipt['active_project_ids'])
    checked = json.loads(Path(ref['path']).read_text())
    assert checked['passed'] is True
    assert checked['cpp_plans']['sha256'] == checked['python_plans']['sha256']
    assert checked['scenario_year_evaluations'] == receipt['plan_count'] * 60
    assert checked['toy_only'] is True and checked['full_enumeration'] is False
    for field in search.RANK_FIELDS:
        assert checked[field] == receipt[field]
    return checked


def manual_hash(rows):
    result = hashlib.sha256()
    for year, fields in zip(YEARS, rows):
        row = dict.fromkeys(ANNUAL_FIELDS, 0)
        row['lp_remaining'] = 1000
        row.update(fields)
        values = (year, *(row[field] for field in ANNUAL_FIELDS), *([0] * 20))
        result.update(struct.pack('<' + 'q' * len(values), *values))
    return result.hexdigest()


def test_manual_full_annual_path_tax_capital_return_and_cash_profit(tmp_path, compilation):
    spec = specification()
    spec['tax_rate_p12'] = SCALE // 4
    _, receipt, records = cpp(spec, tmp_path / 'cpp', compilation)
    # Hand calculation: 100 cost, 2*(80-10), tax 2*5 => total LP profit 30.
    assert [row['objective_pence'] for row in records] == ['0', '30']
    expected = manual_hash([
        dict(cash_open=1000, capital_open=1000, capex=100,
             cash_before_financing=900, cash_after_margin=900, cash_after_optional=900,
             cash_before_distribution=900, equity_before_distribution=1000,
             distribution=900, return_of_capital=900, net_lp_cashflow=900,
             capital_close=100, project_book_value=100, certified_nav=100,
             total_assets=100, total_equity=100),
        dict(capital_open=100, prior_certified_nav=100, revenue=80, opex=10,
             depreciation=50, taxable_before_losses=20, taxable_after_losses=20,
             current_tax=5, net_income=15, borrowing_base=100,
             cash_before_financing=65, cash_after_margin=65, cash_after_optional=65,
             cash_before_distribution=65, equity_before_distribution=115,
             distribution=65, return_of_capital=65, net_lp_cashflow=65,
             capital_close=35, retained_close=15, project_book_value=50,
             certified_nav=50, total_assets=50, total_equity=50),
        dict(capital_open=35, retained_open=15, prior_certified_nav=50, revenue=80,
             opex=10, depreciation=50, taxable_before_losses=20,
             taxable_after_losses=20, current_tax=5, net_income=15, borrowing_base=50,
             cash_before_financing=65, cash_after_margin=65, cash_after_optional=65,
             cash_before_distribution=65, equity_before_distribution=65,
             distribution=65, return_of_capital=35, profit_distribution=30, net_lp_cashflow=65),
        *[{} for _ in range(17)],
    ])
    assert records[1]['S01_path_sha256'] == expected
    assert all(records[1][scenario + '_path_sha256'] == expected for scenario in SCENARIO_IDS)
    check_independent(spec, receipt, tmp_path / 'independent')


def test_complete_toy_masks_and_worst_scenario_not_project_npv_sum(tmp_path, compilation):
    spec = specification()
    spec['scenarios'][1]['revenue_factors_p12'] = annual(SCALE // 2)
    _, receipt, records = cpp(spec, tmp_path / 'cpp', compilation, active=('P01', 'P18'))
    assert [(row['mask'], row['full_mask']) for row in records] == [
        ('0', '0'), ('1', '1'), ('2', str(1 << 17)), ('3', str((1 << 17) + 1))]
    assert [row['objective_pence'] for row in records] == ['0', '-40', '-40', '-80']
    assert records[3]['S01_npv_pence'] == records[3]['S03_npv_pence'] == '80'
    assert receipt['best_plan'] == dict.fromkeys(PROJECT_IDS, 0)
    assert receipt['runnerup_mask'] == 1 and receipt['gap_pence'] == 40
    assert receipt['scenario_year_evaluations'] == 4 * 3 * 20
    check_independent(spec, receipt, tmp_path / 'independent')


@pytest.mark.parametrize('second,factor,expected', [
    (1, SCALE // 4, -1), (2, SCALE // 2, 1), (1, SCALE // 2, 0),
])
def test_t0_inside_sole_signed_rounding_before_crossing_zero(
        tmp_path, compilation, second, factor, expected):
    spec = specification()
    spec['opening_cash_pence'] = 1
    spec['discount_factors_p12'] = annual(factor)
    spec['projects'][0].update(acquisition_cost_pence=1, depreciation_years=1,
        annual_revenue_pence={**annual(0), '2025': 1, '2026': second}, annual_opex_pence=annual(0))
    _, receipt, records = cpp(spec, tmp_path / 'cpp', compilation)
    assert int(records[1]['objective_pence']) == expected
    check_independent(spec, receipt, tmp_path / 'independent')


def test_fifo_expiry_full_path_uses_prior_vintage_before_current_tax(tmp_path, compilation):
    spec = specification()
    spec['facility_limit_pence'] = 0
    spec['tax_rate_p12'] = SCALE // 2
    spec['projects'][0].update(acquisition_cost_pence=1, depreciation_years=1, sale_year=2029,
        annual_revenue_pence={**annual(0), '2027': 15, '2029': 20},
        annual_opex_pence={**annual(0), '2025': 9, '2026': 20})
    _, receipt, records = cpp(spec, tmp_path / 'cpp', compilation)
    assert records[1]['objective_pence'] == '-5'
    check_independent(spec, receipt, tmp_path / 'independent')
    from sheets_factory.workbook.capital_allocation.verify import evaluate_plan
    annuals = evaluate_plan(spec, 1, details=True)['scenarios'][0]['annual']
    assert annuals[1]['loss_created'] == 10 and annuals[2]['loss_created'] == 20
    assert annuals[3]['closing_loss_vintages'][1:3] == [0, 15]
    assert annuals[5]['loss_expired'] == 15 and annuals[5]['current_tax'] == 10


@pytest.mark.parametrize('commitment,feasible,first,gap', [(200, '1', '', 0), (100, '0', '2026', 33)])
def test_margin_prior_nav_interest_and_funding_gap_all_twenty_years_retained(
        tmp_path, compilation, commitment, feasible, first, gap):
    spec = specification()
    spec.update(opening_cash_pence=100, minimum_cash_pence=10, lp_commitment_pence=commitment)
    spec['projects'][0].update(acquisition_cost_pence=180, depreciation_years=3,
        sale_year=2027, annual_revenue_pence=annual(0),
        annual_opex_pence={**annual(0), '2025': 50}, sale_proceeds_pence=150)
    for scenario in spec['scenarios']:
        scenario['bank_rates_p12'] = annual(SCALE // 10)
        scenario['haircuts_p12']['2026'] = SCALE * 9 // 10
    _, receipt, records = cpp(spec, tmp_path / 'cpp', compilation)
    assert records[1]['feasible'] == feasible
    assert records[1]['S01_first_violation_year'] == first
    if feasible == '0':
        assert records[1]['objective_pence'] == records[1]['S01_npv_pence'] == ''
    check_independent(spec, receipt, tmp_path / 'independent')
    from sheets_factory.workbook.capital_allocation.verify import evaluate_plan
    rows = evaluate_plan(spec, 1, details=True)['scenarios'][0]['annual']
    assert len(rows) == 20
    assert rows[0]['borrowing_base'] == 0 and rows[0]['lp_call'] == 90
    assert rows[1]['borrowing_base'] == 180 and rows[1]['bank_draw'] == 50
    assert rows[2]['bank_interest'] == 5 and rows[2]['borrowing_base'] == 12
    assert rows[2]['mandatory_margin'] == 38 and rows[2]['funding_gap'] == gap


def test_triple_factor_rounds_once_and_clamped_depreciation(tmp_path, compilation):
    spec = specification()
    spec['advance_rate_p12'] = SCALE // 2
    spec['projects'][0].update(acquisition_cost_pence=1, depreciation_years=20,
        annual_revenue_pence=annual(0), annual_opex_pence={**annual(0), '2025': 1})
    spec['projects'][1].update(acquisition_cost_pence=2, depreciation_years=4, sale_year=2029,
        annual_revenue_pence=annual(0), annual_opex_pence=annual(0))
    for scenario in spec['scenarios']:
        scenario['haircuts_p12'] = annual(SCALE // 2)
    _, receipt, _ = cpp(spec, tmp_path / 'cpp', compilation, active=('P01', 'P02'))
    check_independent(spec, receipt, tmp_path / 'independent')
    from sheets_factory.workbook.capital_allocation.verify import evaluate_plan
    rows = evaluate_plan(spec, 1, details=True)['scenarios'][0]['annual']
    assert rows[1]['prior_certified_nav'] == 1 and rows[1]['borrowing_base'] == 0
    rows = evaluate_plan(spec, 2, details=True)['scenarios'][0]['annual']
    assert [row['depreciation'] for row in rows[:6]] == [0, 1, 1, 0, 0, 0]


def test_declared_maximum_amounts_need_128_bit_products(tmp_path, compilation):
    spec = specification()
    spec.update(opening_cash_pence=10**11, minimum_cash_pence=10**6,
        lp_commitment_pence=10**11, facility_limit_pence=10**11,
        advance_rate_p12=SCALE - 17, tax_rate_p12=SCALE // 3)
    for project in spec['projects']:
        project.update(acquisition_cost_pence=10**9, sale_proceeds_pence=10**9,
            depreciation_years=20, sale_year=2043,
            annual_revenue_pence={str(y): 10**9 if y > 2024 else 0 for y in YEARS},
            annual_opex_pence={str(y): 10**9 if y > 2024 else 0 for y in YEARS})
    for scenario in spec['scenarios']:
        scenario.update(revenue_factors_p12=annual(3 * SCALE), opex_factors_p12=annual(3 * SCALE),
            nav_factors_p12=annual(3 * SCALE), sale_factors_p12=annual(3 * SCALE),
            bank_rates_p12=annual(SCALE // 10), haircuts_p12=annual(SCALE // 7))
    _, receipt, _ = cpp(spec, tmp_path / 'cpp', compilation, active=('P01', 'P18'))
    check_independent(spec, receipt, tmp_path / 'independent')


def test_eight_bit_toy_all_256_plans_and_15360_year_states(tmp_path, compilation):
    spec = specification()
    _, receipt, records = cpp(spec, tmp_path / 'cpp', compilation, active=PROJECT_IDS[:8])
    assert len(records) == 256 and receipt['scenario_year_evaluations'] == 15360
    assert receipt['best_mask'] == 255 and receipt['objective_pence'] == 320
    assert receipt['runnerup_mask'] == 127 and receipt['gap_pence'] == 40
    check_independent(spec, receipt, tmp_path / 'independent')


@pytest.mark.parametrize('seed', [17, 42, 20261030])
def test_varied_raw_primitives_full_toy_paths_independently_agree(tmp_path, compilation, seed):
    rng = random.Random(seed)
    spec = specification()
    spec.update(opening_cash_pence=300, minimum_cash_pence=25, lp_commitment_pence=1200,
        facility_limit_pence=2000, advance_rate_p12=7 * SCALE // 10,
        tax_rate_p12=28 * SCALE // 100, tax_loss_carry_years=3,
        discount_factors_p12={str(y): SCALE - (y - 2024) * SCALE // 40 for y in YEARS})
    for project in spec['projects']:
        commission = rng.randrange(2024, 2035)
        sale = rng.randrange(commission + 1, 2044)
        project.update(commission_year=commission, sale_year=sale,
            acquisition_cost_pence=rng.randrange(1, 800), depreciation_years=rng.randrange(1, 21),
            sale_proceeds_pence=rng.randrange(1, 1000),
            annual_revenue_pence={str(y): rng.randrange(0, 250) if commission < y <= sale else 0 for y in YEARS},
            annual_opex_pence={str(y): rng.randrange(0, 200) if commission < y <= sale else 0 for y in YEARS})
    for scenario in spec['scenarios']:
        for factor in ('revenue_factors_p12', 'opex_factors_p12', 'nav_factors_p12', 'sale_factors_p12'):
            scenario[factor] = {str(y): rng.randrange(0, 3 * SCALE + 1) for y in YEARS}
        for factor in ('bank_rates_p12', 'haircuts_p12'):
            scenario[factor] = {str(y): rng.randrange(0, SCALE + 1) for y in YEARS}
    _, receipt, records = cpp(spec, tmp_path / 'cpp', compilation, active=('P01', 'P03', 'P18'))
    assert len(records) == 8
    check_independent(spec, receipt, tmp_path / 'independent')


def test_all_ties_are_recorded_without_a_hidden_winner(tmp_path, compilation):
    spec = specification()
    for project in spec['projects']:
        project.update(annual_revenue_pence=annual(0), annual_opex_pence=annual(0), sale_proceeds_pence=100)
    _, receipt, records = cpp(spec, tmp_path / 'cpp', compilation, active=('P01', 'P02'))
    assert [row['objective_pence'] for row in records] == ['0', '0', '0', '0']
    assert receipt['unique_best'] is False and receipt['best_count'] == 4
    assert receipt['best_plan'] is None and receipt['gap_pence'] == 0
    assert receipt['runnerup_mask'] == 1
    check_independent(spec, receipt, tmp_path / 'independent')


@pytest.mark.parametrize('active', [[], ['P02', 'P01'], ['P01', 'P01'], ['P19'], [True]])
def test_bad_active_selection_is_rejected_before_compilation(tmp_path, active):
    with pytest.raises(ValueError, match='Active project'):
        search.enumerate_cpp(specification(), tmp_path / 'bad', active_project_ids=active)
    assert not (tmp_path / 'bad').exists()


def test_import_is_inert_and_compilation_uses_data_temp(compilation, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Import must not compile or enumerate')
    monkeypatch.setattr(search.subprocess, 'run', forbidden)
    importlib.reload(search)
    data = json.loads(Path(compilation['path']).read_text())
    assert Path(data['temporary_directory']).is_relative_to('/data')
    assert data['external_financial_calls'] == 0
    assert Path(data['snapshot']['path']).read_bytes() == search.CPP.read_bytes()
    assert 'ledger' not in search._wire.__code__.co_names


@pytest.fixture
def unique_cpp(tmp_path, compilation):
    _, receipt, records = cpp(specification(), tmp_path / 'cpp', compilation, active=('P01', 'P02'))
    return receipt, records


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'order', 'objective', 'worst', 'hash',
                                  'unknown_npv', 'false_feasibility', 'extra', 'newline'])
def test_complete_csv_validation_rejects_partial_or_false_proofs(tmp_path, unique_cpp, fault):
    receipt, records = unique_cpp
    if fault == 'missing':
        records.pop()
    elif fault == 'duplicate':
        records[1] = records[0].copy()
    elif fault == 'order':
        records[1], records[2] = records[2], records[1]
    elif fault == 'objective':
        records[1]['objective_pence'] = '41'
    elif fault == 'worst':
        records[1]['S02_npv_pence'] = '-5'
    elif fault == 'hash':
        records[1]['S01_path_sha256'] = ''
    elif fault == 'unknown_npv':
        records[1]['S01_npv_pence'] = ''
    elif fault == 'false_feasibility':
        records[1]['feasible'] = '0'
    elif fault == 'extra':
        records.append(records[-1])
    target = tmp_path / 'bad.csv'
    with target.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=search.HEADER, lineterminator='\n')
        writer.writeheader(); writer.writerows(records)
    if fault == 'newline':
        target.write_bytes(target.read_bytes().rstrip(b'\n'))
    with pytest.raises(ValueError):
        search.inspect_plans(target, active_project_ids=['P01', 'P02'])


@pytest.fixture(scope='module')
def toy_certificate(tmp_path_factory):
    parent = tmp_path_factory.mktemp('capital_certificate')
    spec = specification()
    ref = search.enumerate_capital_plans(spec, parent / 'enumeration', active_project_ids=['P01', 'P02'])
    return spec, ref


def test_two_implementation_certificate_is_read_only_and_toy_never_production(toy_certificate, monkeypatch):
    spec, ref = toy_certificate
    monkeypatch.setattr(search.subprocess, 'run', lambda *a, **k: pytest.fail('Admission must be read-only'))
    data = search.validate_certificate(ref, spec, require_full=False)
    assert data['best_plan']['P01'] == data['best_plan']['P02'] == 1
    assert sum(data['best_plan'].values()) == 2
    assert data['objective_pence'] == 80 and data['gap_pence'] == 40
    assert data['admissible'] is False and data['toy_only'] is True
    with pytest.raises(ValueError, match='toy subset'):
        search.validate_certificate(ref, spec)
    other = deepcopy(spec)
    other['projects'][0]['sale_proceeds_pence'] += 1
    with pytest.raises(ValueError, match='different public primitives'):
        search.validate_certificate(ref, other, require_full=False)


@pytest.mark.parametrize('fault', ['method', 'false_full', 'ranking', 'bool_count', 'missing_verifier',
                                  'quality', 'wrong_cpp', 'wrong_verifier', 'gap', 'bool_plan'])
def test_certificate_rejects_changed_claims_and_evidence(tmp_path, toy_certificate, fault):
    spec, ref = toy_certificate
    data = json.loads(Path(ref['path']).read_text())
    if fault == 'method':
        data['methods'][0] = 'winner_only'
    elif fault == 'false_full':
        data['full_enumeration'] = True
    elif fault == 'ranking':
        data['objective_pence'] += 1
    elif fault == 'bool_count':
        data['best_count'] = True
    elif fault == 'missing_verifier':
        data['verification']['sha256'] = '0' * 64
    elif fault == 'quality':
        data['quality_or_difficulty_certified'] = True
    elif fault == 'wrong_cpp':
        data['cpp_implementation']['sha256'] = '0' * 64
    elif fault == 'wrong_verifier':
        data['verifier_implementation']['sha256'] = '0' * 64
    elif fault == 'gap':
        data['gap_pence'] = 0
    elif fault == 'bool_plan':
        data['best_plan']['P01'] = True
    changed = tmp_path / 'changed.json'
    changed.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        search.validate_certificate(changed, spec, require_full=False)


def test_fresh_directory_and_artifact_hash_guards(tmp_path, compilation):
    existing = tmp_path / 'existing'
    existing.mkdir()
    with pytest.raises(ValueError, match='fresh'):
        search.enumerate_cpp(specification(), existing, active_project_ids=['P01'], compilation=compilation)
    target = tmp_path / 'target'
    target.mkdir()
    link = tmp_path / 'symlink'
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match='symbolic link'):
        search.enumerate_cpp(specification(), link / 'child', active_project_ids=['P01'], compilation=compilation)
    broken = deepcopy(compilation)
    broken['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='Artifact content differs'):
        search.enumerate_cpp(specification(), tmp_path / 'broken', active_project_ids=['P01'], compilation=broken)


def test_terminal_sale_matures_facility_and_calls_do_not_replenish_commitment(tmp_path, compilation):
    spec = specification()
    spec.update(opening_cash_pence=200, minimum_cash_pence=20)
    spec['projects'][0].update(sale_year=2043, acquisition_cost_pence=180, depreciation_years=20,
        annual_revenue_pence=annual(0), annual_opex_pence={**annual(0), '2025': 20},
        sale_proceeds_pence=200)
    _, receipt, records = cpp(spec, tmp_path / 'cpp', compilation)
    check_independent(spec, receipt, tmp_path / 'independent')
    assert records[1]['objective_pence'] == '0'
    from sheets_factory.workbook.capital_allocation.verify import evaluate_plan
    rows = evaluate_plan(spec, 1, details=True)['scenarios'][0]['annual']
    assert rows[-1]['borrowing_base'] == 0 and rows[-1]['mandatory_margin'] == 20
    assert rows[-1]['cash_close'] == rows[-1]['bank_close'] == rows[-1]['project_book_value'] == 0


def test_no_feasible_alternative_and_ties_cannot_pass_admission(tmp_path):
    tied = specification()
    tied['projects'][1].update(annual_revenue_pence=annual(0), annual_opex_pence=annual(0),
                               sale_proceeds_pence=100)
    tie_ref = search.enumerate_capital_plans(tied, tmp_path / 'tied', active_project_ids=['P01', 'P02'])
    tie = json.loads(Path(tie_ref['path']).read_text())
    assert tie['unique_best'] is False and tie['best_plan'] is None and tie['gap_pence'] == 0
    with pytest.raises(ValueError, match='unique best'):
        search.validate_certificate(tie_ref, tied, require_full=False)
    scarce = specification()
    scarce['lp_commitment_pence'] = 0
    scarce['projects'][0]['acquisition_cost_pence'] = 2000
    scarce_ref = search.enumerate_capital_plans(scarce, tmp_path / 'scarce', active_project_ids=['P01'])
    value = json.loads(Path(scarce_ref['path']).read_text())
    assert value['feasible_count'] == 1 and value['unique_best'] is True
    assert value['gap_pence'] is None and value['runnerup_mask'] is None
    with pytest.raises(ValueError, match='finite gap'):
        search.validate_certificate(scarce_ref, scarce, require_full=False)


def test_input_cannot_change_during_enumeration(tmp_path, compilation, monkeypatch):
    spec_path = tmp_path / 'public.json'
    spec_path.write_text(json.dumps(specification()))
    actual = search.subprocess.run
    def change_after_run(*args, **kwargs):
        result = actual(*args, **kwargs)
        spec = json.loads(spec_path.read_text())
        spec['projects'][0]['sale_proceeds_pence'] += 1
        spec_path.write_text(json.dumps(spec))
        return result
    monkeypatch.setattr(search.subprocess, 'run', change_after_run)
    with pytest.raises(ValueError, match='Artifact content differs'):
        search.enumerate_cpp(spec_path, tmp_path / 'changed', active_project_ids=['P01'], compilation=compilation)
    assert (tmp_path / 'changed' / 'execution.json').is_file()
    assert not (tmp_path / 'changed' / 'cpp_enumeration.json').exists()


def test_cpp_failure_preserves_exit_and_partial_output_instead_of_a_certificate(
        tmp_path, compilation, monkeypatch):
    def fail(command, **kwargs):
        Path(command[2]).write_text(','.join(search.HEADER) + '\n')
        return search.subprocess.CompletedProcess(command, 1, stdout=b'', stderr=b'forced test failure')
    monkeypatch.setattr(search.subprocess, 'run', fail)
    with pytest.raises(ValueError, match='enumeration failed'):
        search.enumerate_cpp(specification(), tmp_path / 'failed', active_project_ids=['P01'], compilation=compilation)
    failed = json.loads((tmp_path / 'failed' / 'execution.json').read_text())
    assert failed['returncode'] == 1 and failed['complete_enumeration_claimed'] is False
    assert Path(failed['stderr']['path']).read_bytes() == b'forced test failure'
    assert (tmp_path / 'failed' / 'all_plans.csv').is_file()
    assert not (tmp_path / 'failed' / 'certificate.json').exists()

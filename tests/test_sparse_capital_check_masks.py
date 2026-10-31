"""Small supplied-mask tests only: never search the 40/48/56-bit space."""
from copy import deepcopy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import time

import pytest

from sheets_factory.workbook.capital_allocation_sparse import check_masks as check, ledger, spec


def public(n=40):
    annual = lambda value: {str(year): value for year in spec.YEARS}
    projects = []
    for index, pid in enumerate(spec.project_ids(n)):
        revenue = annual(0)
        if index < 2:
            revenue['2025'] = (350, 240)[index]
        projects.append({'id': pid, 'commission_year': 2024, 'sale_year': 2025,
            'acquisition_cost_pence': (100, 80)[index] if index < 2 else 10**9,
            'depreciation_years': 1, 'annual_revenue_pence': revenue,
            'annual_opex_pence': annual(0), 'sale_proceeds_pence': 0})
    return {'schema_version': 1, 'currency': 'GBP', 'monetary_unit': 'pence', 'years': list(spec.YEARS),
        'opening_cash_pence': 1000, 'minimum_cash_pence': 0, 'lp_commitment_pence': 0,
        'facility_limit_pence': 0, 'advance_rate_p12': 0, 'tax_rate_p12': 0,
        'tax_loss_carry_years': 3, 'discount_factors_p12': annual(spec.SCALE), 'projects': projects,
        'scenarios': [{'id': sid, **{key: annual(spec.SCALE) for key in (
            'revenue_factors_p12', 'opex_factors_p12', 'nav_factors_p12', 'sale_factors_p12')},
            'bank_rates_p12': annual(0), 'haircuts_p12': annual(0)} for sid in spec.SCENARIO_IDS],
        'provenance': {'kind': 'synthetic_capital_allocation_extension', 'raw_ancestors': deepcopy(spec.RAW_ANCESTORS)}}


def mask_file(path, masks):
    path.write_bytes(b''.join(check.MASK.pack(mask) for mask in masks))
    return path


def prepare(tmp_path, core, value=None, masks=(0, 1, 3, 2, 1, 4), max_masks=256, max_ms=60000):
    path = mask_file(tmp_path / 'supplied.u64le', masks)
    return check.prepare_inputs(public() if value is None else value, path, tmp_path / 'prepared',
                                core=core, max_masks=max_masks, max_ms=max_ms)


@pytest.fixture(scope='module', params=['A', 'B'])
def native(request, tmp_path_factory):
    folder = tmp_path_factory.mktemp('supplied-' + request.param)
    frozen = prepare(folder, request.param, masks=(0,))
    binary = folder / 'native'
    done = subprocess.run(['g++', '-O3', '-std=c++17', '-static', '-DCHECK_FINANCIAL_' + request.param,
        '-I', str(Path(frozen['public_reader']['path']).parent), str(check.KERNEL), '-o', str(binary)],
        capture_output=True, text=True, timeout=60, env=dict(os.environ, TMPDIR=str(folder)))
    assert done.returncode == 0, done.stderr
    return request.param, binary


def run_native(native, tmp_path, value=None, masks=(0, 1, 3, 2, 1, 4), *, expected=None, cap=256, ms=60000, raw=None):
    core, binary = native
    frozen = prepare(tmp_path, core, value=value, masks=masks)
    mask_path = Path(frozen['masks']['path'])
    if raw is not None:
        mask_path.write_bytes(raw)
    output, summary = tmp_path / 'outcomes.bin', tmp_path / 'summary.json'
    command = [str(binary), frozen['raw_public']['path'], str(mask_path), str(output), str(summary),
               str(len(masks) if expected is None else expected), str(cap), str(ms)]
    done = subprocess.run(command, capture_output=True, text=True, timeout=15)
    return done, frozen, output, json.loads(summary.read_text())


def assert_decimal(value, masks, output):
    rows = list(check.RECORD.iter_unpack(output.read_bytes()))
    assert len(rows) == len(masks)
    for mask, row in zip(masks, rows, strict=True):
        plan = {pid: int(bool(mask & (1 << index))) for index, pid in enumerate(spec.project_ids(len(value['projects'])))}
        actual = ledger.simulate(value, plan)
        npvs = [actual['scenarios'][sid]['npv_pence'] for sid in spec.SCENARIO_IDS]
        flags = sum((1 << index) for index, npv in enumerate(npvs) if npv is not None)
        assert row == (mask, flags, *(check.NULL_NPV if npv is None else npv for npv in npvs))


@pytest.mark.parametrize('n', [40, 48, 56])
def test_actual_opposite_financial_forwards_preserve_duplicates_order_and_nulls(native, tmp_path, n):
    value = public(n); masks = (0, 1, 3, 2, 1, 4)
    done, frozen, output, summary = run_native(native, tmp_path, value, masks)
    assert done.returncode == 0, done.stderr
    assert summary['complete'] and summary['row_count'] == summary['financial_forward_calls'] == '6'
    assert summary['scenario_forward_calls'] == '18' and summary['optimizer_runs'] == 0
    assert not summary['optimum_certified'] and not summary['source_quality_or_difficulty_certified']
    assert_decimal(value, masks, output)
    chunks = check.validate_output(output, frozen['masks'], project_count=n, expected_count=len(masks))
    assert chunks == [{'start_row': '0', 'end_row_exclusive': '6', 'record_count': '6',
                       'bytes': 240, 'sha256': check.reference(output)['sha256']}]
    assert summary['actual_scenario_year_states'] is None if native[0] == 'A' else int(summary['actual_scenario_year_states']) > 0


def test_bit55_never_uses_float_or_json_numeric_masks(native, tmp_path):
    value = public(56)
    value['projects'][-1] = dict(deepcopy(value['projects'][1]), id='P56')
    value['projects'][1] = dict(deepcopy(public(56)['projects'][-1]), id='P02')
    masks = (0, 1 << 55, (1 << 55) | 1, 1, 1 << 55)
    done, _, output, summary = run_native(native, tmp_path, value, masks)
    assert done.returncode == 0 and summary['complete']
    assert_decimal(value, masks, output)
    assert list(check.RECORD.iter_unpack(output.read_bytes()))[2][2:] == (410, 410, 410)


def test_financing_fifo_tax_and_signed_rounding_match_independent_decimal(native, tmp_path):
    helper_spec = importlib.util.spec_from_file_location('private_bound_test_fixture', Path(__file__).with_name('test_sparse_capital_bounds.py'))
    helper = importlib.util.module_from_spec(helper_spec); helper_spec.loader.exec_module(helper)
    value = helper.public(40, stress=True)
    # Only the sixteen explicitly supplied plans are calculated, not 2**40.
    masks = tuple(range(16)) + (15, 0)
    done, _, output, summary = run_native(native, tmp_path, value, masks)
    assert done.returncode == 0 and summary['financial_forward_calls'] == str(len(masks))
    assert_decimal(value, masks, output)


@pytest.mark.parametrize('raw,expected,reason', [
    (struct.pack('<Q', 0) + b'x', 2, 'truncated_masks'),
    (struct.pack('<Q', 0) + b'x', 1, 'trailing_masks'),
    (struct.pack('<Q', 1 << 40), 1, 'mask_outside_dimension')])
def test_native_rejects_truncated_trailing_and_high_masks_without_completion(native, tmp_path, raw, expected, reason):
    done, _, _, summary = run_native(native, tmp_path, masks=(0,), raw=raw, expected=expected)
    assert done.returncode == 2 and not summary['complete'] and summary['status'] == 'incomplete'
    assert summary['stop_reason'] == reason and not summary['optimum_certified']


def test_native_explicit_cap_is_not_a_partial_success(native, tmp_path):
    done, _, output, summary = run_native(native, tmp_path, masks=(0, 1), cap=1)
    assert done.returncode == 2 and summary['stop_reason'] == 'mask_limit'
    assert summary['row_count'] == summary['financial_forward_calls'] == '0' and output.stat().st_size == 0


def test_native_large_explicit_deadline_does_not_overflow_nanosecond_conversion(native, tmp_path):
    done, _, _, summary = run_native(native, tmp_path, masks=(0,), ms=999999999999999999)
    assert done.returncode == 0 and summary['complete'] and summary['row_count'] == '1'


def test_actual_backpressured_close_exceeding_deadline_is_incomplete(native, tmp_path):
    core, binary = native; frozen = prepare(tmp_path, core, masks=(0,))
    fifo = tmp_path / 'owned.fifo'; os.mkfifo(fifo)
    fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
    child = None
    try:
        fcntl.fcntl(fd, fcntl.F_SETPIPE_SZ, 4096); os.write(fd, b'x' * 4096)
        summary = tmp_path / 'summary.json'
        child = subprocess.Popen([str(binary), frozen['raw_public']['path'], frozen['masks']['path'], str(fifo),
            str(summary), '1', '1', '200'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.4)
        assert child.poll() is None, 'The owned FIFO must actually backpressure the final flush'
        assert os.read(fd, 4096) == b'x' * 4096
        _, stderr = child.communicate(timeout=10)
        result = json.loads(summary.read_text())
        assert child.returncode == 2, stderr
        assert result['status'] == 'incomplete' and result['stop_reason'] == 'elapsed_limit'
        assert not result['complete'] and not result['optimum_certified']
    finally:
        if child is not None and child.poll() is None:
            child.kill(); child.wait()
        os.close(fd)


def test_backpressured_summary_finalization_is_also_inside_native_deadline(native, tmp_path):
    core, binary = native; frozen = prepare(tmp_path, core, masks=(0,))
    fifo = tmp_path / 'owned-summary.fifo'; os.mkfifo(fifo)
    fd = os.open(fifo, os.O_RDWR | os.O_NONBLOCK)
    child = None
    try:
        fcntl.fcntl(fd, fcntl.F_SETPIPE_SZ, 4096); os.write(fd, b'x' * 4096)
        child = subprocess.Popen([str(binary), frozen['raw_public']['path'], frozen['masks']['path'],
            str(tmp_path / 'output.bin'), str(fifo), '1', '1', '200'],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.4)
        assert child.poll() is None, 'The owned summary FIFO must actually block metadata finalization'
        assert os.read(fd, 4096) == b'x' * 4096
        _, stderr = child.communicate(timeout=10)
        assert child.returncode == 2, stderr
        summaries = [json.loads(line) for line in os.read(fd, 4096).splitlines()]
        assert summaries[-1]['complete'] is False and summaries[-1]['stop_reason'] == 'elapsed_limit'
        assert int(summaries[-1]['elapsed_nanoseconds']) >= 200000000
    finally:
        if child is not None and child.poll() is None:
            child.kill(); child.wait()
        os.close(fd)


@pytest.mark.parametrize('core', ['A', 'B'])
def test_preparation_is_zero_execution_and_exact_extracted_reader_only(tmp_path, monkeypatch, core):
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('Preparation cannot compile or execute'))
    frozen = prepare(tmp_path, core)
    actual, value = check.validate_prepared(tmp_path / 'prepared')
    assert actual == frozen and spec.canonical_sha(value) == frozen['public_spec_sha256']
    assert frozen['compiler_runs'] == frozen['optimizer_runs'] == frozen['model_calls'] == frozen['LO_calls'] == 0
    assert frozen['checks_partition_backend'] != core and frozen['record_format'] == '<QQqqq'
    reader = Path(frozen['public_reader']['path']).read_text()
    assert 'int main(' not in reader and 'SparseSearch' not in reader and 'BSearch' not in reader
    assert 'CAPITAL_SPARSE_' + core + '_RAW_V1' in reader
    with pytest.raises(ValueError, match='fresh'):
        check.prepare_inputs(value, frozen['masks'], tmp_path / 'prepared', core=core, max_masks=256, max_ms=60000)


@pytest.mark.parametrize('masks,cap', [(b'', 10), (b'x', 10), (struct.pack('<Q', 1 << 40), 10), (struct.pack('<QQ', 0, 1), 1)])
def test_bad_mask_inputs_fail_before_execution_or_output_creation(tmp_path, masks, cap):
    source = tmp_path / 'masks'; source.write_bytes(masks)
    with pytest.raises(ValueError):
        check.prepare_inputs(public(), source, tmp_path / 'prepared', core='B', max_masks=cap, max_ms=1000)
    assert not (tmp_path / 'prepared').exists()


@pytest.mark.parametrize('limit', [0, -1, True, 1.0, 10**18])
def test_limits_require_bounded_literal_integers(tmp_path, limit):
    source = mask_file(tmp_path / 'masks', (0,))
    with pytest.raises(ValueError):
        check.prepare_inputs(public(), source, tmp_path / 'prepared', core='A', max_masks=limit, max_ms=1000)


def test_symlink_and_recipe_tampering_rejected(tmp_path, monkeypatch):
    source = mask_file(tmp_path / 'masks', (0,)); alias = tmp_path / 'alias'; alias.symlink_to(source)
    with pytest.raises(ValueError, match='nonsymlink'):
        check.prepare_inputs(public(), alias, tmp_path / 'bad', core='B', max_masks=1, max_ms=1000)
    frozen = check.prepare_inputs(public(), source, tmp_path / 'prepared', core='B', max_masks=1, max_ms=1000)
    fake = tmp_path / 'changed.cpp'; fake.write_text('changed checker')
    monkeypatch.setattr(check, 'KERNEL', fake)
    with pytest.raises(ValueError, match='recipe changed'):
        check.validate_prepared(tmp_path / 'prepared')
    assert frozen['masks']['sha256'] == check.reference(source)['sha256']


@pytest.mark.parametrize('core', ['A', 'B'])
def test_real_explicit_execution_complete_immutable_receipts_and_negative_bindings(tmp_path, core):
    frozen = prepare(tmp_path, core, masks=(0, 1, 3, 4, 1))
    receipt = check.execute_prepared(tmp_path / 'prepared')
    actual = check.validate_execution(receipt, expected_core=core, expected_public_sha=spec.canonical_sha(public()),
                                      expected_masks=frozen['masks'])
    assert actual['complete'] is True and actual['passed'] is True and actual['row_count'] == '5'
    assert actual['financial_forward_calls'] == '5' and actual['scenario_forward_calls'] == '15'
    assert actual['optimizer_runs'] == 0 and not actual['complete_partition_coverage_certified']
    assert actual['compilation']['command'][3] == '-static' and Path(actual['started']['path']).exists()
    assert_decimal(public(), (0, 1, 3, 4, 1), Path(actual['outcomes']['path']))
    for kwargs in ({'expected_core': 'B' if core == 'A' else 'A'}, {'expected_public_sha': '0' * 64}):
        with pytest.raises(ValueError):
            check.validate_execution(receipt, **kwargs)
    other = mask_file(tmp_path / 'different_masks', (0, 1, 3, 1, 4))
    with pytest.raises(ValueError, match='projection'):
        check.validate_execution(receipt, expected_masks=other)
    modified = deepcopy(actual); modified['optimum_certified'] = True
    target = tmp_path / 'fake_receipt.json'; target.write_text(json.dumps(modified))
    with pytest.raises(ValueError, match='unsupported claims'):
        check.validate_execution(target)
    modified = deepcopy(actual); modified['native_command'][-1] = '999999'
    target.write_text(json.dumps(modified))
    with pytest.raises(ValueError, match='command differs'):
        check.validate_execution(target)
    modified = deepcopy(actual); modified['output_chunks'][0]['sha256'] = '0' * 64
    target.write_text(json.dumps(modified))
    with pytest.raises(ValueError, match='chunk hashes'):
        check.validate_execution(target)


def test_failed_compilation_preserves_started_and_terminal_without_complete_claim(tmp_path, monkeypatch):
    fake = tmp_path / 'invalid.cpp'; fake.write_text('this is not C++')
    monkeypatch.setattr(check, 'KERNEL', fake)
    prepare(tmp_path, 'B', masks=(0,))
    receipt = check.execute_prepared(tmp_path / 'prepared')
    value = json.loads(Path(receipt['path']).read_text())
    assert value['complete'] is False and value['passed'] is False and value['status'] == 'incomplete'
    assert value['compilation']['exit_code'] != 0 and Path(value['started']['path']).exists()
    assert Path(value['compilation']['stderr']['path']).stat().st_size > 0
    with pytest.raises(ValueError, match='Incomplete'):
        check.validate_execution(receipt)


@pytest.mark.parametrize('mutation', ['wrong_mask', 'flags', 'null', 'truncated', 'trailing'])
def test_output_validator_never_accepts_other_masks_flags_nulls_or_lengths(tmp_path, mutation):
    source = mask_file(tmp_path / 'masks', (0,))
    row = [0, 7, 0, 0, 0]
    if mutation == 'wrong_mask': row[0] = 1
    if mutation == 'flags': row[1] = 8
    if mutation == 'null': row[2] = check.NULL_NPV
    raw = check.RECORD.pack(*row)
    if mutation == 'truncated': raw = raw[:-1]
    if mutation == 'trailing': raw += b'x'
    output = tmp_path / 'output'; output.write_bytes(raw)
    with pytest.raises(ValueError):
        check.validate_output(output, source, project_count=40, expected_count=1)


def test_only_financial_functions_are_invoked_not_search_or_rank():
    text = check.KERNEL.read_text()
    assert '#include "../capital_allocation_scaled/search_a.cpp"' in text
    assert '#include "../capital_allocation_scaled/search_b.cpp"' in text
    assert 'close_scenario(p,current,s)' in text and 'close(p,s,current,zero,years)' in text
    assert all(term not in text for term in ('half_table(', '.optimise(', '.walk(', '.seed(', 'best_mask', 'runnerup'))
    assert check.MASK.size == 8 and check.RECORD.size == 40

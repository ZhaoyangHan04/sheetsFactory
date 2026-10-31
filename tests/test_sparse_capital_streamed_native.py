"""Native integer proof checks on four fixed leaves; no production search."""
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

import pytest

import test_sparse_capital_certificate as finance
from sheets_factory.workbook.capital_allocation_sparse import streamed_native as native, streamed_certificate as baseline, spec, check_masks

LIMITS = {'max_regions': 100, 'max_leaves': 16, 'max_line_bytes': 512,
          'max_partition_bytes': 100000, 'max_elapsed_seconds': 120}


def make_case(tmp_path, n=40):
    public = finance.public()
    for j in range(40, n):
        public['projects'].append(dict(deepcopy(public['projects'][-1]), id=f'P{j+1:02d}'))
    # Move the second profitable project to the highest bit, including bit55.
    public['projects'][-1], public['projects'][1] = (dict(deepcopy(public['projects'][1]), id=f'P{n:02d}'),
        dict(deepcopy(public['projects'][-1]), id='P02'))
    ids = spec.project_ids(n)
    order = [*ids[1:-1], 'P01', ids[-1]]
    masks = (0, 1 << (n-1), 1, (1 << (n-1)) | 1)
    claims = [finance.leaf_claim(public, mask) for mask in masks]
    rows = ['L\t' + '0'*(n-2) + bits + '\t' + claim['mask_hex'] + '\t7\t' +
        '\t'.join(claim['scenario_npvs_pence'][sid] for sid in spec.SCENARIO_IDS) + '\n'
        for bits, claim in zip(('00', '01', '10', '11'), claims, strict=True)]
    rows.extend('I\t' + '0'*zeros + '1\tS01.2024.facility\n' for zeros in range(n-3, -1, -1))
    partition = tmp_path / 'partition.tsv'; partition.write_text(''.join(rows))
    return public, order, finance.rank(claims[3]), finance.rank(claims[2]), partition


def prepare(case, directory, limits=LIMITS):
    value, order, best, runner, _ = case
    return native.prepare_inputs(value, directory, branch_order=order, best=best, runnerup=runner, limits=limits)


@pytest.fixture(scope='module')
def binary(tmp_path_factory):
    directory = tmp_path_factory.mktemp('native-prefix'); path = directory / 'verify'
    done = subprocess.run(['g++', '-O3', '-std=c++17', '-static', str(native.KERNEL), '-o', str(path)],
        capture_output=True, text=True, timeout=60, env=dict(os.environ, TMPDIR=str(directory)))
    assert done.returncode == 0, done.stderr
    return path


def run(binary, case, directory, *, caps=None, outputs=None):
    frozen = prepare(case, directory)
    caps = {**LIMITS, **(caps or {})}
    masks, claims, summary = outputs or (directory/'masks', directory/'claims', directory/'summary')
    command = [str(binary), frozen['bound_wire']['path'], str(case[-1]), str(masks), str(claims), str(summary),
        *[str(caps[key]) for key in ('max_regions', 'max_leaves', 'max_line_bytes', 'max_partition_bytes')],
        str(caps.get('max_ms', caps['max_elapsed_seconds']*1000))]
    done = subprocess.run(command, capture_output=True, text=True, timeout=15)
    return frozen, done, json.loads(summary.read_text()), masks, claims


@pytest.mark.parametrize('n', [40, 48, 56])
def test_native_exact_geometry_prunes_high_masks_and_every_leaf_equal_python(binary, tmp_path, n):
    case = make_case(tmp_path, n)
    frozen, done, observed, masks, outcomes = run(binary, case, tmp_path/'prepared')
    assert done.returncode == 0, done.stderr
    assert observed['complete'] and observed['covered_plan_count'] == str(1 << n)
    assert observed['regions'] == str(n+2) and observed['leaves'] == '4' and observed['infeasible'] == str(n-2)
    assert observed['best_leaf_present'] and observed['runnerup_leaf_present']
    result = baseline.project_partition(case[0], case[-1], tmp_path/'python', branch_order=case[1], best=case[2], runnerup=case[3], limits=LIMITS)
    assert masks.read_bytes() == Path(result['masks']['path']).read_bytes()
    assert outcomes.read_bytes() == Path(result['claimed_outcomes']['path']).read_bytes()
    assert list(check_masks.MASK.iter_unpack(masks.read_bytes()))[1][0] == 1 << (n-1)
    assert observed['financial_forward_calls'] == observed['optimizer_runs'] == 0
    assert not observed['unique_optimum_certified'] and not frozen['source_quality_or_difficulty_certified']


def test_safe_ceil_objective_prune_matches_exact_baseline(binary, tmp_path):
    case = make_case(tmp_path)
    lines = case[-1].read_text().splitlines(keepends=True)
    lines[0] = 'B\t' + '0'*40 + '\t100\n'; case[-1].write_text(''.join(lines))
    _, done, summary, masks, _ = run(binary, case, tmp_path/'prepared')
    assert done.returncode == 0 and summary['bound'] == '1' and summary['leaves'] == '3'
    assert list(check_masks.MASK.iter_unpack(masks.read_bytes()))[0][0] == 1 << 39


def test_bounded_lines_cross_real_one_megabyte_reader_boundary(binary, tmp_path):
    case = make_case(tmp_path)
    rows = case[-1].read_text().splitlines(keepends=True)
    # Split one already-infeasible subcube into ordered subcubes. No extra
    # financial leaves or search are executed; the same four ranks remain.
    assert rows[-1] == 'I\t1\tS01.2024.facility\n'
    rows[-1:] = ['I\t1' + format(j, '015b') + '\tS01.2024.facility\n' for j in range(1 << 15)]
    case[-1].write_text(''.join(rows))
    assert case[-1].stat().st_size > 1 << 20
    limits = {**LIMITS, 'max_regions': 40000, 'max_partition_bytes': 2000000}
    frozen = prepare(case, tmp_path/'prepared', limits)
    directory = tmp_path/'prepared'
    command = [str(binary), frozen['bound_wire']['path'], str(case[-1]), str(directory/'masks'), str(directory/'claims'), str(directory/'summary'),
        '40000', '16', '512', '2000000', '60000']
    done = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert done.returncode == 0, done.stderr
    summary = json.loads((directory/'summary').read_text())
    assert summary['complete'] and summary['leaves'] == '4' and summary['regions'] == str(41 + (1 << 15))
    assert summary['financial_forward_calls'] == 0


@pytest.mark.parametrize('change', ['gap', 'overlap', 'reorder', 'truncated', 'long_line', 'mask', 'mask_case',
    'npv_plus', 'negative_zero', 'flags', 'cut', 'unproved_cut', 'bound', 'insufficient_bound',
    'rank_value', 'high_leaf', 'missing_rank', 'trailing', 'feasible_null', 'infeasible_number'])
def test_malformed_or_unproved_partitions_remain_incomplete(binary, tmp_path, change):
    case = make_case(tmp_path); rows = case[-1].read_text().splitlines(keepends=True)
    if change == 'gap': rows.pop(0)
    if change == 'overlap': rows.insert(0, rows[0])
    if change == 'reorder': rows[0], rows[1] = rows[1], rows[0]
    if change == 'truncated': rows[-1] = rows[-1][:-1]
    if change == 'long_line': rows[0] = 'x'*513 + '\n'
    if change == 'mask': rows[0] = rows[0].replace('0x0000000000000000', '0x0000000000000001')
    if change == 'mask_case': rows[0] = rows[0].replace('0x', '0X')
    if change == 'npv_plus': rows[0] = rows[0].replace('\t7\t0', '\t7\t+0', 1)
    if change == 'negative_zero': rows[0] = rows[0].replace('\t7\t0', '\t7\t-0', 1)
    if change == 'flags': rows[0] = rows[0].replace('\t7\t', '\t8\t')
    if change == 'cut': rows[-1] = rows[-1].replace('facility', 'unknown')
    if change == 'unproved_cut': rows[0] = 'I\t'+'0'*40+'\tS01.2024.facility\n'
    if change == 'bound': rows[0] = 'B\t'+'0'*40+'\t0\n'
    if change in ('insufficient_bound', 'missing_rank'): rows[3] = 'B\t'+'0'*38+'11\t3100\n'
    if change == 'rank_value': rows[3] = rows[3].replace('3000', '2999')
    if change == 'high_leaf': rows[1] = rows[1].replace('1000', '4000')
    if change == 'trailing': rows.append('ignored\n')
    if change == 'feasible_null': rows[0] = rows[0].replace('\t7\t0', '\t7\tnull', 1)
    if change == 'infeasible_number': rows[0] = rows[0].replace('\t7\t', '\t0\t')
    case[-1].write_text(''.join(rows))
    _, done, summary, _, _ = run(binary, case, tmp_path/'prepared')
    assert done.returncode == 2 and not summary['complete'] and not summary['unique_optimum_certified']


@pytest.mark.parametrize('caps', [{'max_regions': 1}, {'max_leaves': 1}, {'max_line_bytes': 8}, {'max_partition_bytes': 1}])
def test_native_caps_cannot_certify_partial_evidence(binary, tmp_path, caps):
    case = make_case(tmp_path)
    _, done, summary, _, _ = run(binary, case, tmp_path/'prepared', caps=caps)
    assert done.returncode == 2 and not summary['complete'] and summary['stop_reason']


@pytest.mark.parametrize('blocked', ['masks', 'summary'])
def test_actual_output_or_metadata_backpressure_cannot_escape_time_cap(binary, tmp_path, blocked):
    case = make_case(tmp_path); frozen = prepare(case, tmp_path/'prepared')
    fifo = tmp_path/'owned.fifo'; os.mkfifo(fifo); fd = os.open(fifo, os.O_RDWR|os.O_NONBLOCK)
    masks, claims, summary = tmp_path/'masks', tmp_path/'claims', tmp_path/'summary'
    if blocked == 'masks': masks = fifo
    else: summary = fifo
    child = None
    try:
        fcntl.fcntl(fd, fcntl.F_SETPIPE_SZ, 4096); os.write(fd, b'x'*4096)
        child = subprocess.Popen([str(binary), frozen['bound_wire']['path'], str(case[-1]), str(masks), str(claims), str(summary),
            '100', '16', '512', '100000', '200'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(0.4); assert child.poll() is None
        assert os.read(fd, 4096) == b'x'*4096
        _, stderr = child.communicate(timeout=10); assert child.returncode == 2, stderr
        result = json.loads(summary.read_text()) if blocked == 'masks' else json.loads(os.read(fd,4096).splitlines()[-1])
        assert result['complete'] is False and result['stop_reason'] == 'elapsed_limit'
    finally:
        if child is not None and child.poll() is None: child.kill(); child.wait()
        os.close(fd)


def test_zero_execution_preparation_and_recipe_drift_hold(tmp_path, monkeypatch):
    case = make_case(tmp_path)
    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: pytest.fail('Preparation cannot execute'))
    frozen = prepare(case, tmp_path/'prepared')
    actual, _, _ = native.validate_prepared(tmp_path/'prepared')
    assert actual == frozen and frozen['compiler_runs'] == frozen['financial_forward_calls'] == frozen['optimizer_runs'] == 0
    source = native.KERNEL
    assert 'search_a.cpp' not in source.read_text() and 'search_b.cpp' not in source.read_text()
    fake = tmp_path/'fake.cpp'; fake.write_text('changed'); monkeypatch.setattr(native, 'KERNEL', fake)
    with pytest.raises(ValueError, match='recipe differs'): native.validate_prepared(tmp_path/'prepared')


@pytest.mark.parametrize('limits', [{**LIMITS, 'max_line_bytes':513}, {**LIMITS, 'max_leaves':True},
                                   {**LIMITS, 'max_regions':0}, {**LIMITS, 'max_elapsed_seconds':2**63}])
def test_invalid_independent_limits_fail_before_preparation(tmp_path, limits):
    case = make_case(tmp_path)
    with pytest.raises(ValueError): prepare(case, tmp_path/'prepared', limits)
    assert not (tmp_path/'prepared').exists()


def test_real_wrapper_and_opposite_core_every_leaf_identity(tmp_path):
    case = make_case(tmp_path); prepare(case, tmp_path/'prepared')
    projection = native.execute_prepared(tmp_path/'prepared', case[-1])
    value = native.validate_execution(projection)
    assert value['complete'] is True and value['passed'] is True and value['counts']['leaves'] == '4'
    assert not value['all_financial_leaves_independently_checked'] and not value['unique_optimum_certified']
    check_masks.prepare_inputs(case[0], value['masks'], tmp_path/'opposite', core='B', max_masks=16, max_ms=60000)
    crosscheck = check_masks.execute_prepared(tmp_path/'opposite')
    checked = check_masks.validate_execution(crosscheck, expected_core='B', expected_public_sha=value['public_spec_sha256'], expected_masks=value['masks'])
    assert checked['outcomes']['sha256'] == value['claimed_outcomes']['sha256']
    assert checked['outcomes']['bytes'] == value['claimed_outcomes']['bytes'] == 160
    assert checked['row_count'] == value['counts']['leaves']
    altered = deepcopy(value); altered['counts']['leaves'] = '3'
    bad = tmp_path/'altered.json'; bad.write_text(json.dumps(altered))
    with pytest.raises(ValueError): native.validate_execution(bad)


def test_false_leaf_claim_can_never_be_called_financial_verification(binary, tmp_path):
    case = make_case(tmp_path)
    case[-1].write_text(case[-1].read_text().replace('\t7\t1000\t1000\t1000', '\t7\t999\t999\t999'))
    _, done, summary, _, _ = run(binary, case, tmp_path/'prepared')
    assert done.returncode == 0 and summary['complete']
    assert summary['all_financial_leaves_independently_checked'] is False and summary['unique_optimum_certified'] is False


def test_wrapper_final_receipt_io_after_cap_is_retained_incomplete(tmp_path, monkeypatch):
    case = make_case(tmp_path); prepare(case, tmp_path/'prepared')
    clock = [0]; original = native._write
    monkeypatch.setattr(native.time, 'monotonic_ns', lambda: clock[0])
    def write(path, value):
        original(path, value)
        if path.name == 'receipt.pending.json': clock[0] = 121*10**9
    monkeypatch.setattr(native, '_write', write)
    receipt = native.execute_prepared(tmp_path/'prepared', case[-1])
    observed = json.loads(Path(receipt['path']).read_text())
    assert observed['complete'] is False and observed['status'] == 'incomplete'
    assert (Path(receipt['path']).parent/'receipt.incomplete_candidate.json').exists()
    with pytest.raises(ValueError): native.validate_execution(receipt)

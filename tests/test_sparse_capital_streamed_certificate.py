"""Stream geometry/prunes, four fixed Decimal leaves, and malformed evidence."""
from copy import deepcopy
import hashlib
import json
import struct

import pytest

import test_sparse_capital_certificate as baseline
from sheets_factory.workbook.capital_allocation_sparse import streamed_certificate as streamed, spec

LIMITS = {'max_regions': 100, 'max_leaves': 16, 'max_line_bytes': 256,
          'max_partition_bytes': 100000, 'max_elapsed_seconds': 120}


@pytest.fixture
def case(tmp_path):
    value = baseline.public()
    claims = [baseline.leaf_claim(value, mask) for mask in (0, 2, 1, 3)]
    order = [*spec.project_ids(40)[2:], 'P01', 'P02']
    rows = ['L\t' + '0'*38 + bits + '\t' + claim['mask_hex'] + '\t7\t' +
            '\t'.join(claim['scenario_npvs_pence'][sid] for sid in spec.SCENARIO_IDS) + '\n'
            for bits, claim in zip(('00', '01', '10', '11'), claims)]
    rows.extend('I\t'+'0'*zeros+'1\tS01.2024.facility\n' for zeros in range(37, -1, -1))
    path = tmp_path / 'partition.tsv'
    path.write_text(''.join(rows))
    return value, order, baseline.rank(claims[3]), baseline.rank(claims[2]), path


def project(case, tmp_path, limits=LIMITS):
    value, order, best, runnerup, path = case
    return streamed.project_partition(value, path, tmp_path/'projection', branch_order=order,
                                      best=best, runnerup=runnerup, limits=limits)


def rewrite(case, transform):
    path = case[-1]
    path.write_text(transform(path.read_text()))


def test_projects_every_actual_leaf_in_order_without_claiming_financial_verification(case, tmp_path, monkeypatch):
    monkeypatch.setattr(baseline.ledger, 'simulate', lambda *a, **k: pytest.fail('Projection must not run a financial forward'))
    result = project(case, tmp_path)
    assert result['complete'] and result['every_integer_prune_checked'] and result['complete_disjoint_prefix_coverage']
    assert result['counts'] == {'regions': 42, 'leaves': 4, 'bound': 0, 'infeasible': 38,
                                'bytes': case[-1].stat().st_size}
    assert result['covered_plan_count'] == str(1 << 40)
    masks = (tmp_path/'projection/masks.u64le').read_bytes()
    outcomes = (tmp_path/'projection/claimed_outcomes.bin').read_bytes()
    assert list(struct.iter_unpack('<Q', masks)) == [(0,), (2,), (1,), (3,)]
    assert list(streamed.OUTCOME.iter_unpack(outcomes)) == [
        (0, 7, 0, 0, 0), (2, 7, 1000, 1000, 1000), (1, 7, 2000, 2000, 2000), (3, 7, 3000, 3000, 3000)]
    for field, data in (('partition', case[-1].read_bytes()), ('masks', masks), ('claimed_outcomes', outcomes)):
        assert result[field]['sha256'] == hashlib.sha256(data).hexdigest()
        assert result[field]['bytes'] == len(data)
    assert not result['all_financial_leaves_independently_checked']
    assert not result['unique_optimum_certified'] and not result['source_quality_or_difficulty_certified']


def test_integer_bound_is_independently_recomputed_and_may_equal_runner(case, tmp_path):
    rewrite(case, lambda text: 'B\t'+'0'*40+'\t100\n'+'\n'.join(text.splitlines()[1:])+'\n')
    result = project(case, tmp_path)
    assert result['counts']['bound'] == 1 and result['counts']['leaves'] == 3


@pytest.mark.parametrize('change', ['gap', 'overlap', 'reorder', 'truncate', 'missing_rank',
    'wrong_mask', 'noncanonical_mask', 'bad_npv', 'bad_flags', 'bad_cut', 'unproved_cut',
    'bad_bound', 'insufficient_bound', 'high_rank', 'rank_value', 'tie', 'bad_order', 'trailing'])
def test_malformed_or_unproved_regions_fail_without_complete_projection(case, tmp_path, change):
    value, order, best, runner, path = case
    rows = path.read_text().splitlines(keepends=True)
    if change == 'gap': rows.pop(0)
    if change == 'overlap': rows.insert(0, rows[0])
    if change == 'reorder': rows[0], rows[1] = rows[1], rows[0]
    if change == 'truncate': rows[-1] = rows[-1].rstrip('\n')
    if change == 'missing_rank': rows[3] = 'B\t'+'0'*38+'11\t3100\n'
    if change == 'wrong_mask': rows[0] = rows[0].replace('0x0000000000000000', '0x0000000000000002')
    if change == 'noncanonical_mask': rows[0] = rows[0].replace('0x0000000000000000', '0x0')
    if change == 'bad_npv': rows[0] = rows[0].replace('\t7\t0', '\t7\t+0', 1)
    if change == 'bad_flags': rows[0] = rows[0].replace('\t7\t', '\t0\t')
    if change == 'bad_cut': rows[-1] = rows[-1].replace('facility', 'unknown')
    if change == 'unproved_cut': rows[0] = 'I\t'+'0'*40+'\tS01.2024.facility\n'
    if change == 'bad_bound': rows[0] = 'B\t'+'0'*40+'\t0\n'
    if change == 'insufficient_bound': rows[3] = 'B\t'+'0'*38+'11\t3100\n'
    if change == 'high_rank': rows[1] = rows[1].replace('1000', '4000')
    if change == 'rank_value': rows[3] = rows[3].replace('3000', '2999')
    if change == 'tie': best['objective_pence'] = runner['objective_pence']; best['scenario_npvs_pence'] = deepcopy(runner['scenario_npvs_pence'])
    if change == 'bad_order': order[0] = order[-1]
    if change == 'trailing': rows.append('ignored\n')
    path.write_text(''.join(rows))
    with pytest.raises(streamed.StreamVerificationError) as error:
        project(case, tmp_path)
    assert not error.value.partial['complete'] and not error.value.partial['unique_optimum_certified']
    assert not (tmp_path/'projection/projection.json').exists()


@pytest.mark.parametrize('field,amount', [('max_regions', 1), ('max_leaves', 1), ('max_line_bytes', 8),
                                       ('max_partition_bytes', 1)])
def test_independent_caps_fail_closed_with_partial_artifacts(case, tmp_path, field, amount):
    limits = {**LIMITS, field: amount}
    with pytest.raises(streamed.StreamVerificationError) as error:
        project(case, tmp_path, limits)
    assert not error.value.partial['complete']
    assert not (tmp_path/'projection/projection.json').exists()


def test_expired_deadline_and_bad_limits_do_not_infer_complete_evidence(case, tmp_path, monkeypatch):
    calls = iter([0, 121*10**9, 122*10**9])
    monkeypatch.setattr(streamed.time, 'monotonic_ns', lambda: next(calls))
    with pytest.raises(streamed.StreamVerificationError, match='time limit'):
        project(case, tmp_path)
    assert not (tmp_path/'projection').exists()


def test_existing_output_is_preserved_without_writing_failure_receipt(case, tmp_path):
    directory = tmp_path/'projection'
    directory.mkdir()
    (directory/'original').write_bytes(b'frozen')
    with pytest.raises(streamed.StreamVerificationError, match='fresh'):
        project(case, tmp_path)
    assert sorted(path.name for path in directory.iterdir()) == ['original']


def test_false_non_rank_financial_value_is_only_a_claim_pending_opposite_core(case, tmp_path):
    # The projection can verify prunes and geometry without trusting its NPV.
    # The later complete opposite-core stream must expose this altered leaf.
    rewrite(case, lambda text: text.replace('\t7\t1000\t1000\t1000', '\t7\t999\t999\t999'))
    result = project(case, tmp_path)
    assert result['complete'] and not result['all_financial_leaves_independently_checked']
    assert not result['unique_optimum_certified']

"""Finite structural examples only; no financial search or certificates."""
import hashlib
import json

import pytest

from sheets_factory.workbook.capital_allocation_sparse.coverage import (
    describe_prefix, verify_partition)


def record(prefix, kind='bound', evidence=None):
    return {'prefix': prefix, 'kind': kind, 'evidence': {} if evidence is None else evidence}


@pytest.mark.parametrize('count', [40, 48, 56])
def test_one_root_region_is_structurally_complete_but_proves_no_mathematics(count):
    result = verify_partition(count, iter([record('', evidence={'unverified_upper': '-999'})]))
    assert result['complete_plan_count'] == str(1 << count)
    assert result['covered_plan_count'] == str(1 << count)
    assert result['complete_disjoint_structural_coverage'] is True
    assert result['financial_leaf_values_checked'] is False
    assert result['pruning_witnesses_checked'] is False
    assert result['unique_optimum_or_runnerup_proven'] is False
    assert result['source_quality_or_difficulty_certified'] is False


def test_nonuniform_prefixes_cover_the_complete_cube_and_bind_all_payload_bytes():
    regions = [record('0'), record('10', 'infeasible'), record('110'), record('111')]
    result = verify_partition(40, iter(regions))
    expected = hashlib.sha256(b''.join(json.dumps(row, sort_keys=True, separators=(',', ':')).encode()
                                      + b'\n' for row in regions)).hexdigest()
    assert result['canonical_region_stream_sha256'] == expected
    assert result['region_kinds'] == {'bound': 3, 'infeasible': 1}
    changed = [*regions[:-1], record('111', evidence={'proof_ref': 'a different witness'})]
    assert verify_partition(40, iter(changed))['canonical_region_stream_sha256'] != expected


def test_a_56_bit_complete_partition_can_include_a_leaf_without_numeric_count_loss():
    # One leftmost leaf followed by every right sibling on the path to root.
    regions = [record('0' * 56, 'leaf', {'npv_pence': 123})]
    regions.extend(record('0' * zeros + '1') for zeros in range(55, -1, -1))
    result = verify_partition(56, iter(regions))
    assert result['region_count'] == 57
    assert result['complete_plan_count'] == '72057594037927936'
    assert result['region_kinds']['leaf'] == 1


def test_prefix_ordinals_and_project_masks_have_explicit_different_significance():
    result = describe_prefix(40, '10')
    assert result['ordinal_start'] == str(1 << 39)
    assert result['ordinal_end_exclusive'] == str((1 << 39) + (1 << 38))
    assert result['known_mask_hex'] == '0x0000000000000003'
    assert result['value_mask_hex'] == '0x0000000000000001'
    assert result['fixed_decisions'] == {'P01': 1, 'P02': 0}
    order = [f'P{i:02d}' for i in range(40, 0, -1)]
    reverse = describe_prefix(40, '1', branch_order=order)
    assert reverse['value_mask_hex'] == '0x0000008000000000'
    assert reverse['fixed_decisions'] == {'P40': 1}
    assert verify_partition(40, iter([record('0'), record('1')]), branch_order=order)['branch_project_order'] == order


@pytest.mark.parametrize('regions', [
    [], [record('0')], [record('00'), record('1')],
    [record('0'), record('0'), record('1')],
    [record('1'), record('0')], [record(''), record('')],
    [record('0', 'leaf'), record('1')],
])
def test_missing_overlapping_reordered_or_invalid_leaf_regions_fail(regions):
    with pytest.raises(ValueError):
        verify_partition(40, iter(regions))


@pytest.mark.parametrize('prefix', [None, 0, False, '2', '01 ', '0' * 41])
def test_invalid_prefixes_fail(prefix):
    with pytest.raises(ValueError):
        describe_prefix(40, prefix)


@pytest.mark.parametrize('count', [True, 0, 30, 39, 64, '40'])
def test_only_declared_integer_dimensions_are_supported(count):
    with pytest.raises(ValueError):
        verify_partition(count, iter([record('')]))


@pytest.mark.parametrize('change', ['duplicate', 'missing', 'extra', 'not_text'])
def test_branch_order_must_be_a_complete_exact_project_permutation(change):
    order = [f'P{i:02d}' for i in range(1, 41)]
    if change == 'duplicate': order[-1] = order[0]
    if change == 'missing': order.pop()
    if change == 'extra': order.append('P41')
    if change == 'not_text': order[-1] = 40
    with pytest.raises(ValueError):
        describe_prefix(40, '', branch_order=order)


@pytest.mark.parametrize('evidence', [{'float': 0.5}, {'large': 1 << 56}, {'set': {1}}, {1: 'key'}])
def test_witness_payloads_cannot_silently_lose_json_precision(evidence):
    with pytest.raises(ValueError):
        verify_partition(56, iter([record('', evidence=evidence)]))


def test_large_witness_quantities_can_be_bound_as_strings():
    result = verify_partition(56, iter([record('', evidence={'numerator': str(1 << 80), 'denominator': '2'})]))
    assert result['region_count'] == 1


def test_region_limit_and_interrupted_stream_never_return_a_complete_proof():
    with pytest.raises(ValueError, match='region limit'):
        verify_partition(40, iter([record('0'), record('1')]), max_regions=1)
    with pytest.raises(ValueError):
        verify_partition(40, iter([record('')]), max_regions=True)
    def interrupted():
        yield record('0')
        raise OSError('fixture stream interruption')
    with pytest.raises(OSError):
        verify_partition(40, interrupted())


@pytest.mark.parametrize('bad', [
    {'prefix': '', 'kind': 'bound'},
    {'prefix': '', 'kind': 'unknown', 'evidence': {}},
    {'prefix': '', 'kind': 'bound', 'evidence': [], 'ignored': True},
])
def test_incomplete_or_unknown_record_schema_is_rejected(bad):
    with pytest.raises(ValueError):
        verify_partition(40, iter([bad]))

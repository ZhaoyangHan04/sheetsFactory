"""Check a streamed binary-prefix partition, without claiming optimality.

Every prefix denotes a complete decision subcube in one fixed branch order.
Contiguous, disjoint ordinal intervals prove structural coverage. A financial
certificate must separately verify every leaf and every pruning witness.
"""
from collections import Counter
import hashlib
import json

from .spec import project_ids, require

MAX_SAFE_JSON_INTEGER = (1 << 53) - 1
KINDS = frozenset(('leaf', 'bound', 'infeasible'))


def _order(count, order):
    ids = project_ids(count)
    if order is None:
        return ids
    require(isinstance(order, (list, tuple)) and len(order) == count
            and all(type(item) is str for item in order)
            and len(set(order)) == count and set(order) == set(ids),
            'The branch order must contain every public project exactly once')
    return tuple(order)


def describe_prefix(count, prefix, *, branch_order=None):
    """Return exact string intervals and canonical uint64 decision masks.

    The first path character selects the first branch variable. Its ordinal
    significance differs from the canonical mask, where P01 is bit zero.
    """
    order = _order(count, branch_order)
    require(type(prefix) is str and len(prefix) <= count
            and all(bit in '01' for bit in prefix), 'A bounded binary prefix is required')
    depth = len(prefix)
    width = 1 << (count - depth)
    start = (int(prefix, 2) if prefix else 0) * width
    indices = {name: index for index, name in enumerate(project_ids(count))}
    known = sum(1 << indices[name] for name in order[:depth])
    chosen = sum((int(bit) << indices[name]) for name, bit in zip(order, prefix))
    return {'prefix': prefix, 'depth': depth,
            'ordinal_start': str(start), 'ordinal_end_exclusive': str(start + width),
            'plan_count': str(width), 'known_mask_hex': '0x' + format(known, '016x'),
            'value_mask_hex': '0x' + format(chosen, '016x'),
            'fixed_decisions': {name: int(bit) for name, bit in zip(order, prefix)}}


def _json_value(value, depth=0):
    require(depth <= 64, 'A partition evidence object is too deeply nested')
    if value is None or type(value) in (str, bool):
        return
    if type(value) is int:
        require(abs(value) <= MAX_SAFE_JSON_INTEGER,
                'Large evidence integers must use canonical strings')
        return
    if isinstance(value, list):
        for child in value:
            _json_value(child, depth + 1)
        return
    if isinstance(value, dict):
        require(all(type(key) is str for key in value), 'Evidence keys must be strings')
        for child in value.values():
            _json_value(child, depth + 1)
        return
    raise ValueError('Partition evidence must use exact JSON values without floats')


def verify_partition(count, regions, *, branch_order=None, max_regions=10_000_000):
    """Verify complete ordered prefix coverage using bounded working memory.

    Records contain exactly prefix/kind/evidence. Evidence is bound by a digest
    but its financial meaning is intentionally not verified by this function.
    Truncation, gaps, overlaps, reordering and invalid leaf depths fail closed.
    """
    order = _order(count, branch_order)
    require(type(max_regions) is int and max_regions > 0, 'A positive region limit is required')
    cursor = 0
    total = 1 << count
    observed = 0
    kinds = Counter()
    digest = hashlib.sha256()
    for record in regions:
        require(observed < max_regions, 'The sparse partition exceeds its explicit region limit')
        require(isinstance(record, dict) and set(record) == {'prefix', 'kind', 'evidence'}
                and type(record['kind']) is str and record['kind'] in KINDS
                and isinstance(record['evidence'], dict), 'A complete typed region record is required')
        prefix = describe_prefix(count, record['prefix'], branch_order=order)
        require(record['kind'] != 'leaf' or prefix['depth'] == count,
                'A financial leaf must specify every decision')
        require(int(prefix['ordinal_start']) == cursor,
                'A sparse partition has a gap, overlap or out-of-order region')
        _json_value(record['evidence'])
        digest.update(json.dumps(record, sort_keys=True, separators=(',', ':'),
                                 ensure_ascii=False, allow_nan=False).encode() + b'\n')
        cursor = int(prefix['ordinal_end_exclusive'])
        observed += 1
        kinds[record['kind']] += 1
    require(observed > 0 and cursor == total, 'The sparse partition is truncated or incomplete')
    return {'kind': 'checked_sparse_binary_prefix_partition', 'version': 1,
            'project_count': count, 'branch_project_order': list(order),
            'region_count': observed, 'region_kinds': dict(kinds),
            'complete_plan_count': str(total), 'covered_plan_count': str(cursor),
            'canonical_region_stream_sha256': digest.hexdigest(),
            'complete_disjoint_structural_coverage': True,
            'financial_leaf_values_checked': False, 'pruning_witnesses_checked': False,
            'unique_optimum_or_runnerup_proven': False,
            'source_quality_or_difficulty_certified': False}

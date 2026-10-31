"""Bounded integer checks for native sparse partitions.

This stage proves prefix coverage and every conservative integer prune. It
projects every leaf, in order, for a separate financial implementation. It
does not run a search, accept a subset of leaves, or certify financial values.
The slow Fraction/Decimal certificate remains the independent baseline.
"""
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import struct
import time

from . import bounds, coverage, spec

OUTCOME = struct.Struct('<QQqqq')
MASK = struct.Struct('<Q')
ABSENT = -(1 << 63)
LIMIT_FIELDS = frozenset(('max_regions', 'max_leaves', 'max_line_bytes',
                          'max_partition_bytes', 'max_elapsed_seconds'))


class StreamVerificationError(ValueError):
    def __init__(self, message, partial):
        super().__init__(message)
        self.partial = partial


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _integer(text):
    _require(type(text) is str and re.fullmatch(r'0|-?[1-9][0-9]*', text) is not None,
             'A canonical signed integer is required')
    return int(text)


def _ref(path):
    path = Path(path).resolve(strict=True)
    _require(path.is_file(), 'A real evidence file is required')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def _write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write('\n')
    return _ref(path)


def _ceil(value):
    value = Fraction(value)
    return -((-value.numerator) // value.denominator)


def _floor(value):
    value = Fraction(value)
    return value.numerator // value.denominator


def _rank(public, value):
    _require(isinstance(value, dict) and set(value) ==
             {'mask_hex', 'objective_pence', 'scenario_npvs_pence'}, 'A complete rank claim is required')
    spec.plan_from_mask_hex(public, value['mask_hex'])
    scenarios = value['scenario_npvs_pence']
    _require(isinstance(scenarios, dict) and set(scenarios) == set(spec.SCENARIO_IDS),
             'A rank must contain all three scenarios')
    npvs = tuple(_integer(scenarios[key]) for key in spec.SCENARIO_IDS)
    objective = _integer(value['objective_pence'])
    _require(all(ABSENT < amount < 1 << 63 for amount in npvs)
             and objective == min(npvs), 'The rank objective or signed64 outcomes differ')
    return int(value['mask_hex'], 16), objective, npvs


def project_partition(public, partition_path, directory, *, branch_order, best, runnerup, limits):
    """Check one entire wire and create ALL masks/outcome claims for cross-check.

    ``limits`` are independently supplied by the caller. Partial files remain
    auditable after any failure; only a terminal complete projection may enter
    the separate opposite-core financial check. Best/runner values here are
    claims, not independently evaluated financial results.
    """
    started = time.monotonic_ns()
    counts = Counter(regions=0, leaves=0, bound=0, infeasible=0, bytes=0)
    active_limits = None
    directory = Path(directory).absolute()
    owns_directory = False

    def budget():
        _require(time.monotonic_ns() - started < active_limits['max_elapsed_seconds'] * 10**9,
                 'The independent verification time limit expired')

    def progress(reason):
        return {'kind': 'incomplete_sparse_integer_partition_projection', 'version': 1,
                'complete': False, 'reason': reason, 'counts': dict(counts),
                'elapsed_nanoseconds': str(time.monotonic_ns() - started),
                'all_financial_leaves_independently_checked': False,
                'unique_optimum_certified': False, 'source_quality_or_difficulty_certified': False}

    try:
        _require(isinstance(limits, dict) and set(limits) == LIMIT_FIELDS
                 and all(type(x) is int and x > 0 for x in limits.values()),
                 'Complete positive independent stream limits are required')
        active_limits = dict(limits)
        budget()
        public = spec.load_spec(public)
        model = bounds.prepare_bounds(public)
        n = len(model.project_ids)
        coverage.describe_prefix(n, '', branch_order=branch_order)
        branch_order = tuple(branch_order)
        indices = {name: i for i, name in enumerate(model.project_ids)}
        order = tuple(indices[name] for name in branch_order)
        best_mask, best_objective, best_npvs = _rank(public, best)
        runner_mask, runner_objective, runner_npvs = _rank(public, runnerup)
        _require(best_mask != runner_mask and best_objective > runner_objective,
                 'A distinct unique best and a strictly lower runner are required')
        expected_ranks = {best_mask: (best_objective, best_npvs), runner_mask: (runner_objective, runner_npvs)}
        constants = tuple(_ceil(x) for x in model.constants)
        coeff = tuple(tuple(_ceil(x) for x in row) for row in model.coefficients)
        objective_base = tuple(c + sum(max(0, x) for x in row) for c, row in zip(constants, coeff))
        cuts = {cut.id: (tuple(_floor(x) for x in cut.weights), _ceil(cut.capacity)) for cut in model.cuts}
        cut_base = {key: sum(min(0, x) for x in weights) for key, (weights, _) in cuts.items()}
        partition_path = Path(partition_path).resolve(strict=True)
        _require(partition_path.is_file() and partition_path.stat().st_size <= active_limits['max_partition_bytes'],
                 'The partition exceeds its independently fixed byte limit')
        _require(not directory.exists(), 'A fresh output directory is required')
        directory.mkdir(parents=True)
        owns_directory = True
        cursor = 0
        ranks_seen = set()
        wire_hash = hashlib.sha256()
        mask_hash = hashlib.sha256()
        outcome_hash = hashlib.sha256()
        with partition_path.open('rb') as stream, (directory / 'masks.u64le').open('xb') as masks, \
                (directory / 'claimed_outcomes.bin').open('xb') as outcomes:
            while True:
                budget()
                line = stream.readline(active_limits['max_line_bytes'] + 1)
                if not line:
                    break
                _require(len(line) <= active_limits['max_line_bytes'] and line.endswith(b'\n'),
                         'A partition row is too long or truncated')
                counts['bytes'] += len(line)
                _require(counts['bytes'] <= active_limits['max_partition_bytes']
                         and counts['regions'] < active_limits['max_regions'], 'A partition resource limit was exceeded')
                fields = line[:-1].decode('ascii').split('\t')
                kind = fields[0]
                _require(kind in ('B', 'I', 'L') and len(fields) == (7 if kind == 'L' else 3),
                         'A complete typed native partition row is required')
                prefix = '' if fields[1] == '-' else fields[1]
                _require(len(prefix) <= n and all(bit in '01' for bit in prefix), 'An invalid binary prefix was supplied')
                width = 1 << (n - len(prefix))
                start = (int(prefix, 2) if prefix else 0) * width
                _require(start == cursor, 'The partition has a gap, overlap, or out-of-order region')
                fixed = tuple((order[i], int(bit)) for i, bit in enumerate(prefix))
                if kind == 'B':
                    actual = min(base + sum(bit * row[j] - max(0, row[j]) for j, bit in fixed)
                                 for base, row in zip(objective_base, coeff))
                    _require(_integer(fields[2]) == actual and actual <= runner_objective,
                             'An objective prune has an incorrect or insufficient conservative bound')
                    counts['bound'] += 1
                elif kind == 'I':
                    _require(fields[2] in cuts, 'An infeasible region names an unknown necessary cut')
                    weights, capacity = cuts[fields[2]]
                    actual = cut_base[fields[2]] + sum(bit * weights[j] - min(0, weights[j]) for j, bit in fixed)
                    _require(actual > capacity, 'A claimed necessary-cut contradiction does not hold')
                    counts['infeasible'] += 1
                else:
                    _require(len(prefix) == n and counts['leaves'] < active_limits['max_leaves'],
                             'A leaf is incomplete or exceeds the leaf limit')
                    _require(re.fullmatch(r'0x[0-9a-f]{16}', fields[2]) is not None,
                             'A canonical uint64 mask string is required')
                    mask = int(fields[2], 16)
                    _require(mask == sum(bit << j for j, bit in fixed), 'A leaf mask differs from its complete prefix')
                    _require(fields[3] in tuple(str(x) for x in range(8)), 'Invalid scenario feasibility bits')
                    flags = int(fields[3])
                    values = []
                    for s, text in enumerate(fields[4:]):
                        feasible = bool(flags & (1 << s))
                        _require((text != 'null') == feasible, 'A scenario NPV differs from its feasibility flag')
                        amount = _integer(text) if feasible else ABSENT
                        _require(amount == ABSENT or ABSENT < amount < 1 << 63, 'A financial outcome exceeds signed64')
                        _require(not feasible or amount != ABSENT, 'The null sentinel is not a feasible NPV')
                        values.append(amount)
                    if mask in expected_ranks:
                        _require(mask not in ranks_seen and flags == 7 and tuple(values) == expected_ranks[mask][1],
                                 'A best/runner claim does not match its actual supplied leaf')
                        ranks_seen.add(mask)
                    elif flags == 7:
                        _require(min(values) <= runner_objective, 'A supplied leaf outranks the claimed runner')
                    mask_bytes = MASK.pack(mask)
                    outcome_bytes = OUTCOME.pack(mask, flags, *values)
                    masks.write(mask_bytes)
                    outcomes.write(outcome_bytes)
                    mask_hash.update(mask_bytes)
                    outcome_hash.update(outcome_bytes)
                    counts['leaves'] += 1
                cursor += width
                wire_hash.update(line)
                counts['regions'] += 1
            budget()
        _require(counts['regions'] > 0 and cursor == 1 << n and ranks_seen == set(expected_ranks),
                 'Complete coverage and actual best/runner leaves are required')
        budget()
        result = {'kind': 'checked_sparse_integer_partition_projection', 'version': 1, 'complete': True,
                  'public_spec_sha256': spec.canonical_sha(public), 'bound_model': model.binding(),
                  'project_count': n, 'branch_project_order': list(branch_order),
                  'best': best, 'runnerup': runnerup, 'gap_pence': str(best_objective - runner_objective),
                  'counts': dict(counts), 'covered_plan_count': str(cursor), 'complete_plan_count': str(1 << n),
                  'partition': {'path': str(partition_path), 'sha256': wire_hash.hexdigest(), 'bytes': counts['bytes']},
                  'masks': {'path': str((directory / 'masks.u64le').resolve()), 'sha256': mask_hash.hexdigest(),
                            'bytes': MASK.size * counts['leaves']},
                  'claimed_outcomes': {'path': str((directory / 'claimed_outcomes.bin').resolve()),
                                       'sha256': outcome_hash.hexdigest(), 'bytes': OUTCOME.size * counts['leaves']},
                  'implementation': _ref(__file__), 'limits': active_limits,
                  'elapsed_nanoseconds': str(time.monotonic_ns() - started),
                  'complete_disjoint_prefix_coverage': True, 'every_integer_prune_checked': True,
                  'all_financial_leaves_independently_checked': False, 'unique_optimum_certified': False,
                  'source_quality_or_difficulty_certified': False}
        budget()
        _write(directory / 'projection.json', result)
        return result
    except Exception as error:
        partial = progress(str(error))
        if owns_directory and not (directory / 'failure.json').exists():
            _write(directory / 'failure.json', partial)
        raise StreamVerificationError(str(error), partial) from error

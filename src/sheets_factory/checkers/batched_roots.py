"""Actual batch recalculations plus static proofs of each root's effects.

Each batch must contain mutually independent roots. Batches may interact with
one another. Individual witnesses start at the original goal; marginal
witnesses restore a batch from the actual full mutation and reverse edits.
No individual-root execution or complete per-root delta is claimed.
"""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import time

import openpyxl

from .separated_roots import (
    certify_separated_roots, _digest, _json_digest, _unchanged_definitions,
)


def validate_root_impact_batches(batches, root_count, max_batches=256):
    """Require an explicit exact partition; booleans are not root indices."""
    if type(root_count) is not int or root_count < 1:
        raise ValueError('positive root count required')
    if type(max_batches) is not int or not 1 <= max_batches <= 2048:
        raise ValueError('invalid max_root_impact_batches')
    if not isinstance(batches, list) or not 1 <= len(batches) <= max_batches:
        raise ValueError('explicit nonempty root_impact_batches within bound required')
    seen = set()
    for batch in batches:
        if not isinstance(batch, list) or not batch:
            raise ValueError('root impact batches cannot be empty')
        for index in batch:
            if type(index) is not int or not 0 <= index < root_count:
                raise ValueError('root impact batch index is outside the edit list')
            if index in seen:
                raise ValueError('root impact batch index is repeated')
            seen.add(index)
    if seen != set(range(root_count)):
        raise ValueError('root impact batches must cover every root exactly once')
    return deepcopy(batches)


def _save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def _batch_copy(source, destination, edits, *, reverse):
    book = openpyxl.load_workbook(source, keep_links=False)
    try:
        for edit in edits:
            book[edit['sheet']][edit['cell']] = edit['before' if reverse else 'after']
        book.save(destination)
    finally:
        book.close()


def prove_batched_root_impacts(*, goal, combined_input, edits, batches, engine,
                              directory, max_batches=256,
                              max_dependency_cells=20000,
                              per_formula_reference_cells=5000):
    """Recalculate twice per batch and reject any missing or uncertain proof."""
    directory, goal, combined_input = Path(directory), Path(goal), Path(combined_input)
    started = time.monotonic()
    receipt = {'version': 1, 'passed': False, 'blocking': True, 'state': 'rejected',
        'proof_method': 'batched_separated_roots_with_actual_LO_values',
        'business_correctness_certificate': False, 'root_impacts': [], 'batches': [],
        'actual_batch_LO_execution_count': 0, 'individual_root_LO_executions': 0,
        'individual_marginal_LO_executions': 0, 'counts_are_lower_bounds': True,
        'complete_per_root_changed_sets_claimed': False}
    executing_engine = False
    try:
        if not isinstance(edits, list) or not edits:
            raise ValueError('nonempty edits list required')
        partition = validate_root_impact_batches(batches, len(edits), max_batches)
        receipt.update(root_count=len(edits), batch_count=len(partition),
            root_impact_batches=partition, edits_sha256=_json_digest(edits),
            root_impact_batches_sha256=_json_digest(partition),
            goal_sha256=_digest(goal), combined_input_sha256=_digest(combined_input))
        roots = [(edit['sheet'], edit['cell']) for edit in edits]
        if len(set(roots)) != len(roots):
            raise ValueError('duplicate edit roots')
        original = openpyxl.load_workbook(goal, keep_links=False)
        try:
            combined = openpyxl.load_workbook(combined_input, keep_links=False)
            try:
                receipt['unchanged_non_root_definition_count'] = _unchanged_definitions(original, combined, set(roots))
            finally:
                combined.close()
        finally:
            original.close()
        directory.mkdir(parents=True, exist_ok=True)
        if any(directory.iterdir()):
            raise ValueError('batch proof directory must be fresh')
        proven = {}
        for batch_index, indices in enumerate(partition):
            selected = [edits[index] for index in indices]
            record = {'batch_index': batch_index, 'root_indices': indices,
                'roots': [edit['sheet'] + '!' + edit['cell'] for edit in selected],
                'state': 'checking', 'actual_LO_execution_count': 0}
            receipt['batches'].append(record)
            pairs = {}
            for kind, base, reverse in [('individual', goal, False),
                                        ('combined_marginal', combined_input, True)]:
                raw = directory / f'batch_{batch_index:03d}_{kind}_raw.xlsx'
                calculated = directory / f'batch_{batch_index:03d}_{kind}.xlsx'
                _batch_copy(base, raw, selected, reverse=reverse)
                engine_started = time.monotonic()
                executing_engine = True
                engine.recalculate(raw, calculated)
                executing_engine = False
                receipt['actual_batch_LO_execution_count'] += 1
                record['actual_LO_execution_count'] += 1
                assertions = ([{**edit, 'before': edit['after'], 'after': edit['before']}
                               for edit in selected] if reverse else selected)
                certificate = certify_separated_roots(goal=base, combined_input=calculated,
                    edits=assertions, max_dependency_cells=max_dependency_cells,
                    per_formula_reference_cells=per_formula_reference_cells)
                certificate_path = directory / f'batch_{batch_index:03d}_{kind}_certificate.json'
                _save_json(certificate_path, certificate)
                record[kind] = {'proof_method': certificate['proof_method'],
                    'base': 'full_combined_mutation' if reverse else 'original_goal',
                    'edits_reversed': reverse, 'actual_batch_LO_execution': True,
                    'actual_individual_root_LO_execution': False,
                    'raw_path': str(raw.resolve()), 'raw_sha256': _digest(raw),
                    'calculated_path': str(calculated.resolve()), 'calculated_sha256': _digest(calculated),
                    'certificate_path': str(certificate_path.resolve()),
                    'certificate_sha256': _digest(certificate_path),
                    'duration_ms': round((time.monotonic() - engine_started) * 1000),
                    'passed': certificate['passed'], 'blocking': certificate['blocking']}
                if certificate.get('passed') is not True or certificate.get('blocking') is not False:
                    raise ValueError(f'batch {batch_index} {kind} separation/value proof failed: ' + certificate.get('reason', 'incomplete proof'))
                values = {impact['evidence']['root']: impact for impact in certificate['root_impacts']}
                if set(values) != set(record['roots']) or len(values) != len(indices):
                    raise ValueError('batch certificate does not cover every declared root')
                pairs[kind] = values
            for index, edit in zip(indices, selected):
                label = edit['sheet'] + '!' + edit['cell']
                individual = pairs['individual'][label]
                marginal = pairs['combined_marginal'][label]
                # The marginal certificate's "goal" is the full broken input:
                # its direction is restoration, not another original mutation.
                lower_bound = {'expected_change_count': 1, 'expected_changes': [label],
                    'counts_are_lower_bounds': True, 'actual_individual_LO_execution': False,
                    'actual_batch_LO_execution': True,
                    'proof_method': 'batched_separation_and_actual_LO_values',
                    'batch_index': batch_index}
                proven[index] = {**lower_bound, 'root_index': index,
                    'evidence': individual['evidence'],
                    'individual_batch_certificate_sha256': record['individual']['certificate_sha256'],
                    'combined_marginal': {**lower_bound, 'edits_reversed': True,
                        'base': 'full_combined_mutation', 'evidence': marginal['evidence'],
                        'batch_certificate_sha256': record['combined_marginal']['certificate_sha256']}}
            record['state'] = 'proven'
        if set(proven) != set(range(len(edits))):
            raise ValueError('not every root has both individual and full-context marginal evidence')
        if _digest(goal) != receipt['goal_sha256'] or _digest(combined_input) != receipt['combined_input_sha256']:
            raise ValueError('source workbook changed during batch proof')
        if _json_digest(edits) != receipt['edits_sha256'] or _json_digest(batches) != receipt['root_impact_batches_sha256']:
            raise ValueError('batch edit plan changed during proof')
        receipt.update(passed=True, blocking=False, state='proven',
            root_impacts=[proven[index] for index in range(len(edits))],
            guarantee='Every root changes its own normalized value under an original-baseline mutation alone and a full-context restoration alone; each actual batch pair separately certifies no intra-batch interference in both graphs.')
    except Exception as error:
        receipt.update(passed=False, blocking=True, state='execution_error' if executing_engine else 'rejected',
            reason=str(error), error_type=type(error).__name__, root_impacts=[])
    receipt['duration_ms'] = round((time.monotonic() - started) * 1000)
    return receipt

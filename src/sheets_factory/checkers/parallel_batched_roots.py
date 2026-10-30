"""Bounded parallel execution of independent batch witnesses.

Each batch still receives two real calculations and two separation proofs.
The scheduler stops admitting new batches after a failure, waits for all
started work, and reports every actual successful calculation.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path
import time

import openpyxl

from .batched_roots import _batch_copy, _save_json, validate_root_impact_batches
from .separated_roots import certify_separated_roots, _digest, _json_digest, _unchanged_definitions


def _check_batch(record, *, edits, goal, combined_input, engine, directory,
                 max_dependency_cells, per_formula_reference_cells):
    selected = [edits[index] for index in record['root_indices']]
    pairs = {}
    executing_engine = False
    try:
        for kind, base, reverse in [('individual', goal, False),
                                    ('combined_marginal', combined_input, True)]:
            stem = f'batch_{record["batch_index"]:03d}_{kind}'
            raw, calculated = directory / (stem + '_raw.xlsx'), directory / (stem + '.xlsx')
            _batch_copy(base, raw, selected, reverse=reverse)
            started = time.monotonic()
            executing_engine = True
            record['actual_LO_started_count'] += 1
            engine.recalculate(raw, calculated)
            record['actual_LO_execution_count'] += 1
            executing_engine = False
            assertions = ([{**edit, 'before': edit['after'], 'after': edit['before']}
                           for edit in selected] if reverse else selected)
            certificate = certify_separated_roots(goal=base, combined_input=calculated,
                edits=assertions, max_dependency_cells=max_dependency_cells,
                per_formula_reference_cells=per_formula_reference_cells)
            certificate_path = directory / (stem + '_certificate.json')
            _save_json(certificate_path, certificate)
            record[kind] = {'proof_method': certificate['proof_method'],
                'base': 'full_combined_mutation' if reverse else 'original_goal',
                'edits_reversed': reverse, 'actual_batch_LO_execution': True,
                'actual_individual_root_LO_execution': False,
                'raw_path': str(raw.resolve()), 'raw_sha256': _digest(raw),
                'calculated_path': str(calculated.resolve()), 'calculated_sha256': _digest(calculated),
                'certificate_path': str(certificate_path.resolve()),
                'certificate_sha256': _digest(certificate_path),
                'duration_ms': round((time.monotonic() - started) * 1000),
                'passed': certificate['passed'], 'blocking': certificate['blocking']}
            if certificate.get('passed') is not True or certificate.get('blocking') is not False:
                raise ValueError(f'batch {record["batch_index"]} {kind} separation/value proof failed: '
                                 + certificate.get('reason', 'incomplete proof'))
            values = {item['evidence']['root']: item for item in certificate['root_impacts']}
            if set(values) != set(record['roots']) or len(values) != len(selected):
                raise ValueError('batch certificate does not cover every declared root')
            pairs[kind] = values
        proven = {}
        for index, edit in zip(record['root_indices'], selected):
            label = edit['sheet'] + '!' + edit['cell']
            lower_bound = {'expected_change_count': 1, 'expected_changes': [label],
                'counts_are_lower_bounds': True, 'actual_individual_LO_execution': False,
                'actual_batch_LO_execution': True,
                'proof_method': 'batched_separation_and_actual_LO_values',
                'batch_index': record['batch_index']}
            proven[index] = {**lower_bound, 'root_index': index,
                'evidence': pairs['individual'][label]['evidence'],
                'individual_batch_certificate_sha256': record['individual']['certificate_sha256'],
                'combined_marginal': {**lower_bound, 'edits_reversed': True,
                    'base': 'full_combined_mutation', 'evidence': pairs['combined_marginal'][label]['evidence'],
                    'batch_certificate_sha256': record['combined_marginal']['certificate_sha256']}}
        record['state'] = 'proven'
        return proven
    except Exception as error:
        record.update(state='execution_error' if executing_engine else 'rejected',
                      reason=str(error), error_type=type(error).__name__)
        return {}


def prove_parallel_batched_root_impacts(*, goal, combined_input, edits, batches, engine,
        directory, concurrency=2, max_batches=256, max_dependency_cells=20000,
        per_formula_reference_cells=5000):
    """Return a complete certificate or retain all started work in a rejection."""
    started = time.monotonic()
    goal, combined_input, directory = Path(goal), Path(combined_input), Path(directory)
    receipt = {'version': 1, 'passed': False, 'blocking': True, 'state': 'rejected',
        'proof_method': 'batched_separated_roots_with_actual_LO_values',
        'business_correctness_certificate': False, 'root_impacts': [], 'batches': [],
        'actual_batch_LO_execution_count': 0, 'actual_batch_LO_started_count': 0,
        'individual_root_LO_executions': 0, 'individual_marginal_LO_executions': 0,
        'counts_are_lower_bounds': True, 'complete_per_root_changed_sets_claimed': False,
        'batch_execution_concurrency': concurrency}
    try:
        if type(concurrency) is not int or not 1 <= concurrency <= 4:
            raise ValueError('root impact concurrency must be an integer from one to four')
        if not isinstance(edits, list) or not edits:
            raise ValueError('nonempty edits list required')
        partition = validate_root_impact_batches(batches, len(edits), max_batches)
        roots = [(edit['sheet'], edit['cell']) for edit in edits]
        if len(set(roots)) != len(roots):
            raise ValueError('duplicate edit roots')
        receipt.update(root_count=len(edits), batch_count=len(partition),
            root_impact_batches=partition, edits_sha256=_json_digest(edits),
            root_impact_batches_sha256=_json_digest(partition),
            goal_sha256=_digest(goal), combined_input_sha256=_digest(combined_input))
        original, combined = openpyxl.load_workbook(goal, keep_links=False), None
        try:
            combined = openpyxl.load_workbook(combined_input, keep_links=False)
            receipt['unchanged_non_root_definition_count'] = _unchanged_definitions(original, combined, set(roots))
        finally:
            original.close()
            if combined is not None:
                combined.close()
        directory.mkdir(parents=True, exist_ok=True)
        if any(directory.iterdir()):
            raise ValueError('batch proof directory must be fresh')
        records = [{'batch_index': number, 'root_indices': indices,
            'roots': [edits[i]['sheet'] + '!' + edits[i]['cell'] for i in indices],
            'state': 'not_started', 'actual_LO_execution_count': 0, 'actual_LO_started_count': 0}
            for number, indices in enumerate(partition)]
        receipt['batches'] = records
        proven, cursor, failed = {}, 0, False
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            running = {}
            while running or (cursor < len(records) and not failed):
                while len(running) < concurrency and cursor < len(records) and not failed:
                    record = records[cursor]
                    record['state'] = 'checking'
                    future = pool.submit(_check_batch, record, edits=edits, goal=goal,
                        combined_input=combined_input, engine=engine, directory=directory,
                        max_dependency_cells=max_dependency_cells,
                        per_formula_reference_cells=per_formula_reference_cells)
                    running[future] = record
                    cursor += 1
                done, _ = wait(running, return_when=FIRST_COMPLETED)
                for future in done:
                    record = running.pop(future)
                    proven.update(future.result())
                    failed = failed or record['state'] != 'proven'
                _save_json(directory / 'progress.json', {'completed_batches': [r for r in records
                    if r['state'] in {'proven', 'execution_error', 'rejected'}],
                    'running_batch_indices': [r['batch_index'] for r in running.values()],
                    'finished_root_count': len(proven), 'stopped_admitting_batches': failed})
        for record in records[cursor:]:
            record['state'] = 'not_started_after_failure'
        receipt['actual_batch_LO_execution_count'] = sum(r['actual_LO_execution_count'] for r in records)
        receipt['actual_batch_LO_started_count'] = sum(r['actual_LO_started_count'] for r in records)
        if failed:
            errors = [r for r in records if r['state'] in {'execution_error', 'rejected'}]
            receipt['state'] = 'execution_error' if any(r['state'] == 'execution_error' for r in errors) else 'rejected'
            raise ValueError('; '.join(r['reason'] for r in errors))
        if set(proven) != set(range(len(edits))):
            raise ValueError('not every root has individual and full-context marginal evidence')
        if (_digest(goal) != receipt['goal_sha256'] or _digest(combined_input) != receipt['combined_input_sha256']
                or _json_digest(edits) != receipt['edits_sha256']
                or _json_digest(batches) != receipt['root_impact_batches_sha256']):
            raise ValueError('source workbook or edit plan changed during batch proof')
        receipt.update(passed=True, blocking=False, state='proven',
            root_impacts=[proven[index] for index in range(len(edits))],
            guarantee='Every root changes its own normalized value under an original-baseline mutation alone and a full-context restoration alone; each actual batch pair separately certifies no intra-batch interference in both graphs.')
    except Exception as error:
        receipt.update(passed=False, blocking=True, reason=str(error), error_type=type(error).__name__, root_impacts=[])
    receipt['duration_ms'] = round((time.monotonic() - started) * 1000)
    return receipt

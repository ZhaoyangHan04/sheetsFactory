#!/usr/bin/env python3
"""Recalculate saved submissions once and retain auxiliary economic witnesses."""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard.server import DashboardServer
from sheets_factory.evaluation import business_failure_evidence as business
from sheets_factory.evaluation.resource_observer import validate_trial_observations
from sheets_factory.workbook.thread_capped_resource_engine import ThreadCappedResourceLibreOfficeEngine

PROFILE = ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
ABSENCE = ROOT/'scripts/validate_period_boundary_candidate_v2.py'
PINS = {Path(business.__file__): 'eeb67c32873930857bc713c1cd3892b9c1da7ea2b70964b91ad13a212f18c54b',
    PROFILE: '4ecc79fe954b9e2965a15d2f0c8965a39394f621ae9808f02fcf88965f446b9b',
    ABSENCE: '0b974c2d7b45ae8f9b844663a06f147c95570094f56e514db15b6b5661b99e48'}
SCALES = {'GBP': 1, 'GBP_thousands': 1000, 'GBP_millions': 1000000}
reference = business.reference
read = business._read


def require(value, message):
    if not value: raise ValueError(message)


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write('\n')
    return reference(path)


def recipes():
    for path, digest in PINS.items(): require(reference(path)['sha256'] == digest, 'A frozen diagnosis dependency changed')
    return [reference(__file__), *[reference(path) for path in PINS]]


def owned_absence(receipts):
    """Reuse only the reviewed exact-owned-ID absence parser, not period admission."""
    require(reference(ABSENCE)['sha256'] == PINS[ABSENCE], 'The owned absence helper changed')
    tree = ast.parse(ABSENCE.read_text()); functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'owned_absence']
    require(len(functions) == 1, 'The pure owned absence seam changed')
    namespace = {'re': re, 'subprocess': subprocess}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(ABSENCE), 'exec'), namespace)
    return namespace['owned_absence']([{'actual_resource_evidence': read(r)} for r in receipts])


def _maps(receipt_ref, published, folder):
    receipt = read(receipt_ref); output = receipt['output']
    require(reference(published)['sha256'] == output['sha256']
        and reference(published)['bytes'] == output['bytes'], 'Published workbook differs from its actual native output')
    require(reference(output['path']) == output, 'The retained native workbook changed')
    maps = business.extract_native_maps(output['path'])
    return maps, {'map_scope': 'complete_sparse_workbook', 'original_workbook': receipt['source'],
        'recalculated_workbook': output, 'native_receipt': receipt_ref,
        'typed_map': write(folder/'typed.json', maps['typed']),
        'raw_numeric_map': write(folder/'raw_numeric.json', maps['raw_numeric'])}


def _admit(batch_ref, terminal_ref):
    batch, terminal = read(batch_ref), read(terminal_ref)
    require(batch.get('kind') == 'individually_engineered_business_revision_batch' and batch.get('version') == 1
        and batch['count'] == len(batch['tasks']) == 2
        and batch['selected_task_ids'] == [t['task_id'] for t in batch['tasks']]
        and {t['mode'] for t in batch['tasks']} == {'financial_modeling', 'debugging'},
        'Require the complete fixed two-mode engineering batch')
    require(terminal.get('kind') == 'business_revision_native_frontier_terminal_v1'
        and terminal.get('version') == 1 and terminal.get('phase') == 'development' and terminal.get('outer_retries') == 0,
        'Require the actual one-attempt business development terminal')
    prepared = read(terminal['prepared'])
    require(prepared.get('kind') == 'prepared_business_revision_native_frontier_v1'
        and prepared.get('phase') == 'development'
        and batch_ref in prepared['batches'] and prepared['tasks'] == batch['tasks'],
        'The terminal belongs to another batch or material')
    resources = read(terminal['resources'])
    require(resources['passed'] is resources['complete'] is True, 'Actual native model resources are incomplete')
    rows = {r['task_id']: r for r in terminal['results']}
    selection = read(terminal['selection'])
    require(selection.get('phase') == 'development' and selection.get('model') == 'gpt-6.1-sol'
        and selection.get('reasoning_effort') == 'xhigh' and selection.get('n_attempts') == 1
        and selection.get('tool_time_policy_version') == 6
        and selection.get('infrastructure_retry_policy', {}).get('max_retries') == 0,
        'Retain the actual single native strongest-model selection and original v6 policy')
    selected = {r['task_id']: r for r in selection['tasks']}
    require(len(rows) == len(terminal['results']) == 2 and set(rows) == set(batch['selected_task_ids']),
        'Each declared material needs its one original attempt')
    source = read(batch['source'])
    require(source.get('kind') == 'independently_verified_associate_bridge_business_source_v1'
        and source.get('passed') is True and source.get('actual_LO_calls_completed') == 3
        and [r['index'] for r in source['actual_LO_calls']] == [1, 2, 3]
        and source.get('complete_AB_financial_fields') == 93510,
        'Require the original complete independently checked associate source')
    for record in source['recipe']: require(reference(record['path']) == record, 'An actual source recipe changed')
    independent = source['independent_records']
    for record in independent.values(): require(reference(record['path']) == record, 'An independent source ledger changed')
    comparison = read(independent['independent_comparison'])
    require(comparison.get('full_financial_fields') == 93510
        and comparison.get('complete_economic_raw_and_primary_values_equal') is True,
        'The retained independent source comparison is incomplete')
    for call in source['actual_LO_calls']:
        audit = read(call['audit'])
        require(audit.get('passed') is True and audit.get('all_financial_fields_checked') == 93510
            and audit.get('unresolved_mismatches') == audit.get('native_errors') == [],
            'A complete retained native source audit is missing')
        receipt = read(call['native_metadata']['actual_resource_receipts'][-1])
        require(receipt.get('status') == 'completed' and receipt.get('output') == call['workbook']
            and reference(call['workbook']['path']) == call['workbook'],
            'A retained native source calculation is missing or changed')
    for task in batch['tasks']:
        row = rows[task['task_id']]; attempt = row['actual_attempt']; r = row['resources']
        result_ref = reference(attempt['result_file']); actual = read(result_ref)
        require(attempt['status'] == 'scored' and type(attempt.get('raw_verifier_reward')) in (int, float)
            and attempt['raw_verifier_reward'] in (0, 1) and result_ref['sha256'] == attempt['result_sha256']
            and actual.get('task_name') == 'sheetsfactory/' + task['task_id']
            and actual.get('exception_info') is None and actual.get('finished_at')
            and actual['verifier_result']['rewards']['reward'] == attempt['raw_verifier_reward']
            and task['source_id'] == source['goal']['sha256'] and row['mode'] == task['mode']
            and r.get('passed') is r.get('complete') is True and r['result'] == result_ref,
            'An unscored, changed or resource-incomplete attempt cannot supply business evidence')
        require(selected[task['task_id']]['task_checksum'] == attempt['task_checksum']
            and selected[task['task_id']]['harbor_export_binding'] == task['harbor_export_binding'],
            'The original native snapshot belongs to another material')
        validated = validate_trial_observations(r['trial_config'], r['result'], receipts=resources['observation_receipts'],
            expected_task_directory=selected[task['task_id']]['task_directory'])
        require(validated['passed'] is validated['complete'] is True, 'Original native actual-role resource proof failed')
    return batch, terminal, rows, source


def run(batch_path, terminal_path, output, *, port=0):
    output = Path(output).absolute()
    require(output == output.resolve() and not output.exists(), 'Use a fresh real diagnosis directory')
    audit = AuditStore(output, {'id': output.name, 'status': 'running', 'stage': 'admission',
        'model_calls': 0, 'source_LO_calls': 0, 'verifier_LO_call_limit': 2})
    server = DashboardServer(audit.snapshot, audit.events, port=port); url = server.start()
    audit.update_run(dashboard_url=url); write(output/'dashboard.json', {'url': url})
    print(json.dumps({'dashboard_url': url}), flush=True)
    started = time.monotonic(); records = []; calls = []; calls_started = 0; current_task = None
    try:
        recipe = recipes(); batch_ref, terminal_ref = reference(batch_path), reference(terminal_path)
        batch, terminal, rows, source = _admit(batch_ref, terminal_ref)
        prospective = write(output/'prospective.json', {'kind': 'fixed_associate_bridge_saved_submission_diagnosis',
            'version': 1, 'batch': batch_ref, 'original_terminal': terminal_ref, 'source': batch['source'],
            'selected_task_ids': batch['selected_task_ids'], 'recipe': recipe,
            'source_calls_reused': 5, 'new_source_calls': 0, 'new_model_calls': 0,
            'new_financial_forwards': 0, 'verifier_LO_call_limit': 2, 'outer_retries': 0})
        public = read(source['specification']); bindings = read(source['bindings'])
        require(public['kind'] == 'associate_bridge_business_spec_v1' and public['case_id'] == source['case_id'],
            'The public business specification differs from the actual source')
        scales = {e['id']: SCALES[e['money_unit']] for e in public['base']['entities']}
        require(len(scales) == len(public['base']['entities']), 'Entity identities must be unique')
        scale_ref = write(output/'private/entity_money_scales.json', scales)
        goal_receipt = source['actual_LO_calls'][-1]['native_metadata']['actual_resource_receipts'][-1]
        audit.update_run(stage='reuse_native_goal')
        goal, goal_proof = _maps(goal_receipt, source['goal']['path'], output/'private/reference')
        for task in batch['tasks']:
            current_task = task['task_id']; row = rows[current_task]; attempt = row['actual_attempt']
            audit.task(current_task, mode=task['mode'], status='running', stage='saved_output_inspection')
            folder = output/'private'/current_task; engineering = read(task['individual_engineering'])
            require(engineering['source'] == batch['source'], 'The input audit belongs to another source')
            published = Path(task['task_directory'])
            published_goal = reference(published/'tests/reference.xlsx')
            require(all(published_goal[k] == source['goal'][k] for k in ('sha256', 'bytes')),
                    'The delivered goal changed after native source validation')
            input_receipt = engineering['native_call_metadata']['actual_resource_receipts'][-1]
            original, input_proof = _maps(input_receipt, published/'environment/input.xlsx', folder/'input')
            result_ref = reference(attempt['result_file'])
            submitted = Path(attempt['result_file']).parent/'artifacts/app/output.xlsx'
            base = {'task_id': current_task, 'mode': task['mode'], 'variant_id': task['variant_id'],
                'original_result': result_ref, 'original_raw_reward': attempt['raw_verifier_reward'],
                'original_effective_score': deepcopy(row['score']), 'source': batch['source'],
                'input_native_receipt': input_receipt, 'goal_native_receipt': goal_receipt,
                'primary_reward_modified': False}
            if not submitted.is_file():
                evidence = {**base, 'state': 'coverage_unknown', 'reason': 'No retained submitted output workbook',
                    'business_failure_evidence': None, 'business_qualified': None, 'new_verifier_LO_calls': 0}
            else:
                require(not submitted.is_symlink() and submitted.resolve() == submitted, 'Use the exact real retained submitted workbook')
                before = reference(submitted); audit.task(current_task, stage='one_output_recalculation')
                audit.update_run(stage='one_output_recalculation', current_task=current_task)
                engine = ThreadCappedResourceLibreOfficeEngine(ROOT, PROFILE, role='verifier', receipt_directory=folder/'native_receipts')
                calls_started += 1
                native = engine.recalculate(submitted, folder/'output.native.xlsx')
                metadata = engine.metadata(); receipt = metadata['actual_resource_receipts'][-1]; calls.append(receipt)
                require(reference(submitted) == before, 'The original submitted workbook changed during recalculation')
                actual, output_proof = _maps(receipt, native, folder/'output')
                provenance = {'kind': 'three_complete_native_recalculated_value_maps', 'version': 1,
                    'roles': {'input': input_proof, 'reference': goal_proof, 'output': output_proof},
                    'bindings': source['bindings'], 'entity_money_scales': scale_ref}
                audit.update_run(stage='economic_evidence_analysis', current_task=current_task)
                trace_root = Path(attempt['result_file']).parent/'agent'
                trace_refs = [reference(p) for p in [trace_root/'codex.txt', *sorted((trace_root/'sessions').rglob('*.jsonl'))] if p.is_file()]
                evidence = business.analyze(original['typed'], goal['typed'], actual['typed'], bindings=bindings,
                    entity_money_scales=scales, provenance=provenance, original_reward=attempt['raw_verifier_reward'],
                    raw_reference=goal['raw_numeric'], raw_output=actual['raw_numeric'], trace_refs=trace_refs)
                cleanup = owned_absence([receipt])
                require(cleanup['all_owned_containers_absent'] and cleanup['daemon_reachable'], 'The exact owned output-recalculation container cleanup is incomplete')
                evidence.update(base, original_submission=before, recalculated_submission=reference(native),
                    output_native_metadata=metadata, owned_cleanup=cleanup, new_verifier_LO_calls=1)
            record = write(folder/'business_evidence.json', evidence); records.append({'task_id': current_task,
                'mode': task['mode'], 'evidence': record, 'state': evidence['state'],
                'business_failure_evidence': evidence['business_failure_evidence'],
                'business_qualified': evidence['business_qualified'],
                'original_raw_reward': attempt['raw_verifier_reward'],
                'original_effective_reward': row['score']['effective_reward'],
                'primary_wrong_count': evidence.get('primary_wrong_count'),
                'core_witnesses': len(evidence.get('economic_witnesses', [])),
                'categories': evidence.get('category_counts', {})})
            audit.task(current_task, status='diagnosed', stage=evidence['state'], business_qualified=evidence['business_qualified'])
            audit.export()
        require(recipes() == recipe and reference(batch_path) == batch_ref and reference(terminal_path) == terminal_ref,
                'The original batch, terminal or diagnosis code changed')
        result = write(output/'terminal.json', {'kind': 'complete_associate_bridge_auxiliary_business_diagnosis',
            'version': 1, 'prospective': prospective, 'records': records, 'task_count': len(records),
            'business_qualified_count': sum(r['business_qualified'] is True for r in records),
            'unknown_count': sum(r['business_qualified'] is None for r in records), 'actual_verifier_LO_calls': len(calls),
            'actual_verifier_LO_calls_started': calls_started,
            'new_source_LO_calls': 0, 'new_model_calls': 0, 'new_financial_forwards': 0,
            'primary_rewards_modified': False, 'outer_retries': 0, 'duration_seconds': time.monotonic()-started})
        audit.update_run(status='completed', stage='diagnosis_complete'); return result
    except BaseException as error:
        write(output/'failure.json', {'error_type': type(error).__name__, 'reason': str(error),
            'task_id': current_task, 'completed_records': records, 'actual_verifier_LO_calls_completed': len(calls),
            'actual_verifier_LO_calls_started': calls_started,
            'new_source_LO_calls': 0, 'new_model_calls': 0, 'primary_rewards_modified': False, 'outer_retries': 0})
        audit.update_run(status='failed', stage='diagnosis_failed', error_type=type(error).__name__); raise
    finally:
        audit.export(); server.stop(); audit.db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('batch', 'terminal', 'output'): parser.add_argument('--'+key, type=Path, required=True)
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.batch, args.terminal, args.output, port=args.port)))


if __name__ == '__main__': main()

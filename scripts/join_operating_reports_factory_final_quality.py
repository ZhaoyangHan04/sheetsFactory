#!/usr/bin/env python3
"""Join completed shared reviews and twenty actual task checks, without execution."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from sheets_factory.evaluation.resource_harbor import inspect_resource_export
from sheets_factory.evaluation.resource_observer import validate_trial_observations
from sheets_factory.workbook.resource_engine import load_runtime_profile

CHECKS = tuple(f'Q{i:02d}' for i in range(1, 13))
SEMANTIC = ('Q01', 'Q02', 'Q03', 'Q04', 'Q07')
GOAL = '5f38a984cf7fc689e030602aab0f0bc95a51b05d54711d4a79207f04445936ef'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reference(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file() and not path.is_symlink(), 'Missing real evidence file: '+str(path))
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def read(record):
    require(isinstance(record, dict) and set(record) == {'path', 'sha256', 'bytes'}
        and reference(record['path']) == record, 'An evidence reference is missing or changed')
    return json.loads(Path(record['path']).read_text())


def assessment(state, reason, *evidence):
    return {'state': state, 'reason': reason, 'evidence': list(evidence)}


def _shared(path, mode):
    record = reference(path); joined = read(record)
    require(joined['candidate_count'] == 20 and joined['business_semantic_passed'] is True,
        'The mode lacks its completed shared semantic review')
    original = read(joined['retained_original_model_review'])
    require(original['failures'] == {} and set(original['assessments']) == set(CHECKS)
        and original['usage']['llm_calls'] == 2 and original['usage']['unknown_usage_calls'] == 0,
        'Two completed ordinary reviews must cover every enabled check')
    require(all(original['assessments'][k]['state'] == 'clear' for k in SEMANTIC)
        and original['assessments']['Q08']['state'] == 'not_applicable', 'A shared semantic finding remains unresolved')
    for review_ref in original['review_results'].values():
        review = read(review_ref)
        require(not any(issue.get('severity') == 'blocker' and issue.get('attribution') in
            ('task_defect', 'reference_defect', 'environment_failure') for issue in review['issues']),
            'The original shared review contains an unresolved blocker')
    dispatch = read(original['dispatch'])
    source_ref = dispatch['workspace_inventories']['reference']['source_manifest.private.json']
    source = read(source_ref)
    require(source['passed'] is True and source['actual_LO_calls_started'] == source['actual_LO_calls_completed'] == 3
        and [row['role'] for row in source['actual_calls']] == ['source1', 'source2', 'source3']
        and all(row['completed'] is True for row in source['actual_calls'])
        and source['source']['sha256'] == GOAL, 'The shared genuine healthy-source proof is missing or belongs to another goal')
    cases = {row['task_id']: row for row in joined['cases']}
    require(len(cases) == len(joined['cases']) == 20, 'Shared native cases must have unique identities')
    return {'record': record, 'joined': joined, 'original': original, 'cases': cases,
        'source': source_ref, 'mode': mode}


def _resources(row, receipts, task_directory=None):
    require(row.get('passed') is True and row.get('complete') is True
        and set(row.get('roles_observed', [])) == {'agent', 'verifier'}, 'Both actual resource roles must be complete')
    checked = validate_trial_observations(row['trial_config'], row['result'], receipts=receipts,
        expected_task_directory=task_directory)
    require(checked['passed'] is True and checked['complete'] is True,
        'Actual CPU/RAM/image observations do not support both roles')
    return checked


def _controls(control_ref, manifest_ref, dataset, task_ids):
    terminal = read(control_ref)
    require(terminal['kind'] == 'complete_exact_twenty_root_controls' and terminal['passed'] is True
        and terminal['dataset_manifest'] == manifest_ref and terminal['oracle_all20_reward'] == 1
        and terminal['nop_all20_reward'] == 0 and terminal['actual_role_resources_checked'] is True,
        'Exact whole-root actual controls are missing, incomplete or belong to another dataset')
    answer = {task_id: {} for task_id in task_ids}
    require(set(terminal['command_receipts']) == {'oracle', 'nop'}, 'Both actual root commands are required')
    for role, command_ref in terminal['command_receipts'].items():
        command = read(command_ref)
        require(command['argv'] == ['harbor', 'run', '-p', 'SpreadsheetEval', '-a', role]
            and command['returncode'] == 0 and command['dataset_manifest'] == manifest_ref,
            'The executed command must target the exact complete root')
        whole = read(command['whole_job_audit']); resources = read(command['actual_resources'])
        require(whole['status'] == 'passed' and whole['agent'] == role
            and whole['dataset_manifest_sha256'] == manifest_ref['sha256']
            and whole['counts'] == {'dataset_tasks': 20, 'trial_results': 20, 'matched_rewards': 20,
                'exceptions': 0, 'missing': 0, 'unknown': 0, 'duplicates': 0}
            and len(whole['trials']) == 20 and resources['passed'] is True,
            'Every actual control trial and its resource proof must pass')
        by_result = {v['result']['sha256']: v for v in resources['validations']}
        require(len(by_result) == len(resources['validations']) == 20, 'Control resource trials must be unique')
        seen = set()
        for trial in whole['trials']:
            task_id = trial['task_id']; result_ref = reference(trial['result_file']); result = read(result_ref)
            actual_task = Path(result['config']['task']['path'])
            if not actual_task.is_absolute():
                actual_task = Path(command['cwd'])/actual_task
            require(task_id in answer and task_id not in seen and result_ref['sha256'] == trial['result_sha256']
                and trial['reward'] == (1 if role == 'oracle' else 0) and trial['exception_info'] is None
                and result.get('exception_info') is None and result.get('finished_at')
                and result['verifier_result']['rewards']['reward'] == trial['reward']
                and result['config']['agent']['name'] == role and result['agent_info']['name'] == role
                and actual_task.resolve() == dataset/task_id
                and Path(trial['resolved_task_path']) == dataset/task_id,
                'A raw actual control is missing, duplicated, changed or has the wrong reward')
            resource = by_result.get(result_ref['sha256'], {})
            _resources(resource, command['resource_observation_receipts'], dataset/task_id)
            answer[task_id][role] = {'command': command_ref, 'result': result_ref,
                'whole_job_audit': command['whole_job_audit'], 'actual_resources': command['actual_resources']}
            seen.add(task_id)
        require(seen == set(task_ids), 'The control job omitted a selected task')
    return answer


def _confirmation(terminal_ref, task_ids):
    terminal = read(terminal_ref)
    require(terminal['kind'] == 'operating_reports_factory_frontier_terminal_v6'
        and terminal['phase'] == 'confirmation' and terminal['outer_retries'] == 0,
        'Fresh confirmation resource evidence must retain its native protocol')
    resources = read(terminal['resources'])
    require(resources['passed'] is True and resources['complete'] is True,
        'Fresh confirmation resources are incomplete')
    rows = {r['task_id']: r for r in terminal['results']}
    require(len(rows) == len(terminal['results']) == 20 and set(rows) == set(task_ids),
        'Confirmation must cover the same fixed twenty tasks once')
    for row in rows.values():
        require(row['actual_attempt'] and row['score']['state'] in ('complete', 'known_tool_budget_failure')
            and row['score']['effective_reward'] in (0, 1), 'An infrastructure or timing unknown cannot complete quality coverage')
        _resources(row['resources'], resources['observation_receipts'])
    return terminal['resources'], rows


def _individual(case, task, dataset):
    engineering = read(case['individual_engineering']); plan = read(case['private_plan'])
    if task['mode'] == 'financial_modeling':
        expected = set(plan['mask_points'])
    else:
        expected = {row['sheet']+'!'+row['cell'] for row in plan['DBG_faults'].values()}
    actual = engineering['complete_primary_difference']
    require(engineering['passed'] is True and engineering['native_error_count'] == 0
        and engineering['given_literals_unchanged'] is True and engineering['sheet_structure_unchanged'] is True
        and engineering['programmatic_oracle_reward'] == 1 and engineering['programmatic_nop_reward'] == 0
        and len(actual) == len(set(actual)) == engineering['complete_primary_difference_count'] >= 100
        and set(actual) == expected, 'Actual native effects must match this material and preserve its given data')
    task_dir = dataset/task['task_id']
    for name, key in [('environment/input.xlsx', 'input'), ('tests/reference.xlsx', 'goal'), ('instruction.md', 'instruction')]:
        current = reference(task_dir/name); prior = case[key]
        require((current['sha256'], current['bytes']) == (prior['sha256'], prior['bytes']),
            'The final task differs from its reviewed and individually checked material')
    require(case['goal']['sha256'] == GOAL, 'The common actual healthy reference changed')
    source_receipts = engineering['native_call_metadata']['actual_resource_receipts']
    require(bool(source_receipts), 'The individual actual source-role calculation is missing')
    for record in source_receipts:
        source = read(record)
        require(source['role'] == 'source' and source['status'] == 'completed'
            and source['actual_resources_verified'] is True and source['thread_cap_verified'] is True,
            'The actual individual source calculation lacks its complete resource evidence')
        require(reference(source['profile']['path']) == source['profile'], 'The actual source profile binding changed')
        profile = load_runtime_profile(source['profile']['path'])
        require(profile == engineering['native_call_metadata']['runtime_profile'], 'The individual source metadata uses another resource profile')
        capacity = profile['docker_resources']['source']; actual_capacity = source['actual_resources']
        require(source['requested_resources'] == capacity
            and actual_capacity['cpus_nanoseconds'] == int(capacity['cpus']*1_000_000_000)
            and actual_capacity['memory_bytes'] == capacity['memory_bytes']
            and actual_capacity['pids_limit'] == capacity['pids_limit']
            and source['image_id'] == profile['image']['id'], 'Actual source CPU/RAM/PID/image capacity differs from the fixed profile')
        output = source['output']; require(reference(output['path']) == output
            and output['sha256'] == case['input']['sha256'], 'The actual native output is not this delivered input')
    return source_receipts


def build(cohort, fm_join, debug_join, root_controls, confirmation, dataset_root):
    cohort_ref = reference(cohort); frozen = read(cohort_ref); dataset = Path(dataset_root).absolute()
    tasks = frozen['tasks']; ids = [t['task_id'] for t in tasks]
    require(frozen['count'] == len(ids) == len(set(ids)) == 20 and
        Counter(t['mode'] for t in tasks) == Counter({'financial_modeling': 10, 'debugging': 10})
        and frozen['selection_uses_confirmation_results'] is False, 'Require the original fixed 10+10 cohort')
    result = {'kind': 'operating_report_factory_final_quality_join', 'version': 1,
        'created_at': datetime.now(timezone.utc).isoformat(), 'passed': False, 'task_count': 20,
        'enabled_check_ids': list(CHECKS), 'tasks': [{'task_id': t['task_id'], 'mode': t['mode'],
            'assessments': {k: assessment('unknown', 'Required final evidence not yet joined') for k in CHECKS},
            'passed': False} for t in tasks], 'shared_semantic_reviews': [], 'individual_engineering': [],
        'actual_root_controls': reference(root_controls), 'confirmation_resources': None,
        'confirmation_terminal': reference(confirmation), 'cohort': cohort_ref,
        'quality_is_not_difficulty_confirmation': True, 'new_model_LO_Harbor_calls': 0, 'old_artifacts_modified': False}
    try:
        manifest_ref = reference(dataset/'dataset_manifest.json'); manifest = read(manifest_ref)
        require(manifest['cohort_freeze'] == cohort_ref and manifest['task_count'] == 20
            and len(manifest['selected_task_ids']) == 20 and set(manifest['selected_task_ids']) == set(ids)
            and {p.name for p in dataset.iterdir()} == set(ids)|{'dataset_manifest.json'},
            'The actual root is not the exact frozen selected cohort')
        payloads = {t['task_id']: t for t in manifest['tasks']}
        require(len(payloads) == len(manifest['tasks']) == 20 and set(payloads) == set(ids), 'Dataset task entries must be complete and unique')
        shared = {'financial_modeling': _shared(fm_join, 'financial_modeling'), 'debugging': _shared(debug_join, 'debugging')}
        result['shared_semantic_reviews'] = [s['joined']['retained_original_model_review'] for s in shared.values()]
        result['shared_append_only_native_joins'] = [s['record'] for s in shared.values()]
        controls = _controls(result['actual_root_controls'], manifest_ref, dataset, ids)
        confirmation_ref, confirmations = _confirmation(result['confirmation_terminal'], ids)
        result['confirmation_resources'] = confirmation_ref
        for target, task in zip(result['tasks'], tasks):
            task_id = task['task_id']; family = shared[task['mode']]; case = family['cases'][task_id]
            root_task = dataset/task_id
            require(inspect_resource_export(root_task) == task['harbor_export_binding'] == payloads[task_id]['harbor_export_binding'],
                'The actual delivered export binding changed')
            inventory = {str(p.relative_to(root_task)): reference(p)['sha256'] for p in root_task.rglob('*') if p.is_file()}
            require(len(inventory) == 17 and inventory == payloads[task_id]['payload_files'], 'The complete final task payload changed')
            source_receipts = _individual(case, task, dataset)
            require(confirmations[task_id]['mode'] == task['mode'], 'Confirmation task category differs')
            states = target['assessments']
            for check in SEMANTIC:
                states[check] = assessment('clear', family['original']['assessments'][check]['reason'],
                    family['joined']['retained_original_model_review'], family['record'], case['individual_engineering'])
            states['Q05'] = assessment('clear', 'Shared original five controls, individual native I/G1/0 and actual whole-root oracle1/nop0 agree.',
                family['record'], case['individual_engineering'], controls[task_id]['oracle'], controls[task_id]['nop'])
            states['Q06'] = assessment('clear', 'Actual complete primaryD equals the frozen mask or bug-root set; facts and structure remain intact.',
                case['private_plan'], case['individual_engineering'])
            states['Q08'] = assessment('not_applicable', 'Candidate shortcut review is complete; this quality join makes no difficulty claim.',
                family['joined']['retained_original_model_review'])
            states['Q09'] = assessment('clear', 'The individually calculated input has zero native errors and the unchanged goal retains its shared complete source proof.',
                case['individual_engineering'], family['record'])
            states['Q10'] = assessment('clear', 'Shared genuine healthy-source stability and this individual actual input calculation are bound.',
                family['source'], family['record'], case['individual_engineering'], *source_receipts)
            states['Q11'] = assessment('clear', 'Actual source resources and both actual control/confirmation roles satisfy the fixed profile.',
                *source_receipts, controls[task_id]['oracle']['actual_resources'], controls[task_id]['nop']['actual_resources'], confirmation_ref)
            states['Q12'] = assessment('clear', 'All twelve enabled checks have current shared or individual evidence for this exact delivered material.',
                cohort_ref, family['record'], case['individual_engineering'], result['actual_root_controls'], confirmation_ref)
            target['passed'] = all(v['state'] in ('clear', 'not_applicable') and v['evidence'] for v in states.values())
            result['individual_engineering'].append(case['individual_engineering'])
        result['passed'] = all(t['passed'] for t in result['tasks'])
        require(reference(cohort) == cohort_ref and reference(dataset/'dataset_manifest.json') == manifest_ref,
            'The selected cohort or delivered dataset changed during joining')
    except (ValueError, KeyError, OSError, TypeError) as error:
        result['passed'] = False
        result['failure'] = {'error_type': type(error).__name__, 'reason': str(error)}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cohort', 'fm-join', 'debug-join', 'root-controls', 'confirmation', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--dataset-root', type=Path, default=ROOT/'SpreadsheetEval')
    args = parser.parse_args(argv)
    require(not args.output.exists() and args.output.absolute() == args.output.absolute().resolve(), 'Use a fresh real output path')
    report = build(args.cohort, args.fm_join, args.debug_join, args.root_controls, args.confirmation, args.dataset_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2); stream.write('\n')
    print(json.dumps({'report': reference(args.output), 'passed': report['passed'], 'task_count': report['task_count']}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())

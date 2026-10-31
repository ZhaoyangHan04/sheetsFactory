#!/usr/bin/env python3
"""Run every frozen official research case once; never create production seeds."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
import yaml
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.evaluation import native_transport_frontier as runner
from sheets_factory.evaluation.resource_observer import ResourceObserver, validate_observation_receipt
from sheets_factory.evaluation.streaming_verifier import compare_files
from sheets_factory.evaluation.thread_capped_harbor_export import export_resource_harbor, inspect_resource_export, verify_local_base_image
from sheets_factory.workbook.thread_capped_resource_engine import ThreadCappedResourceLibreOfficeEngine

CONFIG = ROOT/'config/pipelines/external_calibration_cohort_v1.json'
PROFILE = ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
CONTROL_HELPER = ROOT/'outputs/research/spreadsheetbench2_external_controls_20261031T020734Z/prepare_and_run_controls.py'
CONTROL_SHA = 'd06e1da485db0b1a80ebf257fbe0e577c70f24c9586584a39eeb1ac26ce5760c'
OLD_RUNNER = ROOT/'outputs/research/spreadsheetbench2_external_model_runner_20261031T021756Z/run_external_calibration.py'
OLD_RUNNER_SHA = '8ba2ec4084e1f189595e2f0b2e6caabe5fec2ca759f5b3e20d55f3bfa767bcc0'
KIND = 'prepared_external_official_calibration_cohort'
INVENTORY_KIND = 'prepared_full_official_SpreadsheetBench2_FM_DBG_research_inventory'
MODES = {'Financial_Model': 'financial_modeling', 'Debugging': 'debugging'}
HF = '5a2215ed4121945ab09d8723df2995602090b042'
GITHUB = 'a7bdc2d358e052d35a94768e1f487c0d9e9c0011'
ARCHIVE_SHA = '52699c974c30aced7125f3d12cdaabbbcbba8db804373d7397a5d3bdf68e5b3e'
ARCHIVE_BYTES = 134232213
EVALUATOR_SHA = '5e31ba8f9cbdd8007eebfb441f9783cfaff280e90225b37ff61702863cb0f8b9'


def require(ok, message):
    if not ok:
        raise ValueError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def reference(path):
    p = Path(path).absolute()
    require(p == p.resolve() and p.is_file() and not p.is_symlink(), 'Use a real immutable file')
    before = p.stat(); h = hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024**2), b''):
            h.update(block)
    after = p.stat()
    require((before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
        (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'A file changed while hashing')
    return {'path': str(p), 'sha256': h.hexdigest(), 'bytes': after.st_size}


def checked(value):
    require(type(value) is dict and set(value) == {'path', 'sha256', 'bytes'}
        and reference(value['path']) == value, 'A complete frozen reference changed')
    return Path(value['path'])


def read(value):
    return json.loads((checked(value) if isinstance(value, dict) else Path(value)).read_text())


def write(path, value):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write('\n')
    return reference(p)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def policy(path=CONFIG):
    value = read(path)
    fixed = {'research_only': True, 'model': 'gpt-6.1-sol', 'reasoning_effort': 'xhigh',
        'attempts_per_case_version': 1, 'outer_retries': 0,
        'official_original_evaluator_is_primary': True, 'project_exact_is_diagnostic_only': True,
        'compatibility_is_not_a_selection_filter': True, 'run_compatibility_controls': False, 'worker_cap': 'MAX_CONCURRENCY=2',
        'production_seed_or_release_eligible': False,
        'execution_budget': {'version': 1, 'elapsed_policy': 'operational_guard',
            'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}}
    require(value.get('kind') == 'external_official_calibration_cohort_policy' and value.get('version') == 1
        and all(value.get(k) == v for k, v in fixed.items())
        and type(value.get('concurrency')) is int and 1 <= value['concurrency'] <= 4
        and value.get('maximum_cases') == 200
        and value.get('runtime_profile') == str(PROFILE.relative_to(ROOT)), 'The bounded research policy changed')
    return value


def identity(case):
    value = {'HF_revision': HF, 'case': case['task_id'], 'original_input_sha256': case['input']['sha256'],
        'original_instruction_sha256': hashlib.sha256(case['official_record']['instruction'].encode()).hexdigest(),
        'model': 'gpt-6.1-sol', 'reasoning_effort': 'xhigh'}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def checked_inventory(value):
    record = value if isinstance(value, dict) else reference(value)
    inventory = read(record)
    require(inventory.get('kind') == INVENTORY_KIND and inventory.get('version') == 1
        and inventory.get('official_revision') == HF and inventory.get('official_evaluator_revision') == GITHUB,
        'Use the complete pinned official research inventory')
    checked(inventory['archive']); checked(inventory['official_evaluator'])
    require(inventory['archive']['sha256'] == ARCHIVE_SHA
        and inventory['archive']['bytes'] == ARCHIVE_BYTES
        and inventory['official_evaluator']['sha256'] == EVALUATOR_SHA,
        'Use the exact full official archive and original evaluator')
    cases = inventory['cases']; require(type(cases) is list and len(cases) == 200, 'The full 200-case inventory is required')
    expected = []
    for category in MODES:
        rows = read(inventory['official_metadata'][category])
        require(type(rows) is list and rows, 'The complete official category metadata is required')
        expected.extend((category, row) for row in rows)
    require(len(cases) == len(expected), 'Never select a subset of the official metadata')
    for case, (category, original) in zip(cases, expected, strict=True):
        require(case['category'] == category and case['mode'] == MODES[category]
            and case['official_task_id'] == original['id'] and case['official_record'] == original
            and type(original['instruction']) is str, 'The full official case identity or original instruction changed')
        checked(case['input']); checked(case['goal'])
        alias = 'external-sb2-'+('fm-' if category == 'Financial_Model' else 'dbg-')+original['id'].replace('_', '-')
        require(case['task_id'] == alias and Path(alias).name == alias, 'The immutable Harbor case alias changed')
        require(type(case['requires_new_model_attempt']) is bool
            and (case['existing_attempt'] is None) == case['requires_new_model_attempt'], 'Reuse and new attempts must be explicit')
    require(all(sum(c['category'] == category for c in cases) == 100 for category in MODES)
        and sum(c['requires_new_model_attempt'] for c in cases) == 198
        and {c['case_key'] for c in cases if not c['requires_new_model_attempt']} ==
            {'Financial_Model/03_04', 'Debugging/04_01'}, 'Retain all 200 cases and only the two original attempts')
    keys = [c['case_key'] for c in cases]; ids = [c['task_id'] for c in cases]
    require(len(set(keys)) == len(keys) and len(set(ids)) == len(ids)
        and inventory['fixed_order'] == keys, 'The complete raw metadata order changed')
    by_mode = [[c['case_key'] for c in cases if c['category'] == category] for category in MODES]
    interleaved = [items[i] for i in range(max(map(len, by_mode))) for items in by_mode if i < len(items)]
    require(inventory['prospective_execution_order'] == interleaved, 'Freeze the complete interleaved execution order before calls')
    return record, inventory


def recipes():
    from sheets_factory.evaluation import clock_resource_frontier, tool_time_clock_bounds, resource_frontier, frontier
    from sheets_factory.evaluation import resource_observer, resource_harbor, thread_capped_harbor_export
    from sheets_factory.evaluation import streaming_verifier, resource_streaming_verifier, tool_time, tool_time_bounds, budget
    from sheets_factory.workbook import thread_capped_resource_engine, resource_engine, engine
    require(reference(CONTROL_HELPER)['sha256'] == CONTROL_SHA and reference(OLD_RUNNER)['sha256'] == OLD_RUNNER_SHA,
        'The frozen two-case control or research boundary changed')
    modules = (runner, clock_resource_frontier, tool_time_clock_bounds, resource_frontier, frontier,
        resource_observer, resource_harbor, thread_capped_harbor_export,
        streaming_verifier, resource_streaming_verifier, tool_time, tool_time_bounds, budget,
        thread_capped_resource_engine, resource_engine, engine)
    paths = [Path(__file__), CONFIG, PROFILE, CONTROL_HELPER, OLD_RUNNER, runner.PROFILE_PATH,
        *[Path(m.__file__) for m in modules]]
    return {str(p.resolve()): reference(p) for p in paths}


def reused_result(case):
    refs = case['existing_attempt']; terminal = read(refs['model_terminal']); post = read(refs['official_postscore'])
    require(terminal.get('resource_validation', {}).get('passed') is True
        and terminal['resource_validation'].get('complete') is True
        and terminal.get('actual_no_retry_history') is True and post.get('status') == 'completed',
        'A reused case needs its genuine completed original attempt and official postscore')
    matches = [r for r in post['results'] if r['category'] == case['category']
        and r['original_metadata_id'] == case['official_task_id']]
    require(len(matches) == 1, 'The original official postscore does not identify this case')
    row = matches[0]; score = row['official_scores']['original_official']
    for key, current in (('input', case['input']), ('reference', case['goal'])):
        old = score[key]; checked(old)
        require((old['sha256'], old['bytes']) == (current['sha256'], current['bytes']), 'The reused official material differs')
    checked(row['submitted_artifact']); checked(row['actual_result'])
    require(sum(a['task_id'] == row['task_id'] for a in terminal['actual_attempts']) == 1,
        'A reused case must be one original attempt, not a selected retry')
    return {'case_key': case['case_key'], 'task_id': case['task_id'], 'disposition': 'reused_original_completed_attempt',
        'new_model_calls': 0, 'original_model_terminal': refs['model_terminal'], 'original_postscore': refs['official_postscore'],
        'original_result': row['actual_result'], 'submitted_artifact': row['submitted_artifact'],
        'official_primary': score, 'project_exact_diagnostic': row['our_exact_reward'],
        'original_timing_metadata_preserved': True, 'research_only': True}


def prepare(inventory, output, *, configuration=CONFIG):
    p = Path(output).absolute(); require(p == p.resolve() and not p.exists(), 'Use one fresh research cohort directory')
    config = policy(configuration); inventory_ref, source = checked_inventory(inventory)
    reused = [reused_result(c) for c in source['cases'] if not c['requires_new_model_attempt']]
    p.mkdir(parents=True)
    return write(p/'preparation.json', {'kind': KIND, 'version': 1, 'inventory': inventory_ref,
        'policy': config, 'configuration': reference(configuration), 'recipe': recipes(),
        'fixed_raw_order': source['fixed_order'], 'execution_order': source['prospective_execution_order'],
        'case_identities': {c['case_key']: identity(c) for c in source['cases']}, 'reused': reused,
        'actual_LO_calls': 0, 'actual_model_calls': 0, 'actual_Harbor_jobs': 0,
        'qualified': False, 'production_seed_or_release_eligible': False})


def validate_prepared(output):
    p = Path(output).absolute(); frozen = read(p/'preparation.json')
    require(frozen.get('kind') == KIND and frozen.get('version') == 1
        and frozen['policy'] == policy(checked(frozen['configuration']))
        and frozen['recipe'] == recipes() and frozen['qualified'] is False, 'The complete prospective research freeze changed')
    _, inventory = checked_inventory(frozen['inventory'])
    require(frozen['case_identities'] == {c['case_key']: identity(c) for c in inventory['cases']}
        and frozen['execution_order'] == inventory['prospective_execution_order'], 'The case membership or order changed')
    require(frozen['reused'] == [reused_result(c) for c in inventory['cases'] if not c['requires_new_model_attempt']], 'Original results must remain unchanged')
    return frozen, inventory


def _official(evaluator, evaluator_ref, case, source, goal, output):
    original = case['official_record']; mapped = dict(original)
    mapped.update(spreadsheet_path=str(source), golden_response_path=str(goal))
    require(all((term in original['spreadsheet_path']) == (term in mapped['spreadsheet_path'])
        for term in ('Color', 'Embedded')), 'Relocation must preserve official evaluator path modes')
    value, missing = evaluator.process_single_item(mapped, '/', str(output.parent), {}, case['category'])
    return {'result': value, 'missing_output': missing, 'mapped_record': mapped, 'evaluator': evaluator_ref,
        'input': reference(source), 'reference': reference(goal), 'output': reference(output) if output.is_file() else None}


def _compatibility(case, folder, evaluator, evaluator_ref, audit):
    helper = load(CONTROL_HELPER, '_frozen_external_controls')
    engine = ThreadCappedResourceLibreOfficeEngine(ROOT, PROFILE, role='source', receipt_directory=folder/'resources')
    calls = []; rows = {}; failure = None
    # Preserve evaluator switches from the official public filename, without changing public bytes.
    switches = ''.join(t for t in ('Color', 'Embedded') if t in case['official_record']['spreadsheet_path']) or 'ordinary'
    norm = folder/'private'/switches; norm.mkdir(parents=True, exist_ok=True)
    try:
        baseline = helper.calculate(engine, checked(case['input']), norm/'input.xlsx', folder, 'normalize_input', audit, calls)
        goal = helper.calculate(engine, checked(case['goal']), norm/'reference.xlsx', folder, 'normalize_reference', audit, calls)
        for name, source, expected in (('oracle', goal, 1), ('nop', baseline, 0)):
            directory = norm/name; directory.mkdir()
            actual = helper.calculate(engine, source, directory/(case['official_task_id']+'_output.xlsx'), folder,
                name+'_actual_output_recalculation', audit, calls)
            official = _official(evaluator, evaluator_ref, case, baseline, goal, actual)
            original = _official(evaluator, evaluator_ref, case, checked(case['input']), checked(case['goal']), actual)
            exact = compare_files(baseline, goal, actual)
            rows[name] = {'official_normalized_diagnostic': official, 'official_original_cache_diagnostic': original,
                'project_exact_diagnostic': exact, 'expected_control': expected,
                'compatible': official['result'].get('accuracy') == expected and exact['reward'] == expected}
    except Exception as error:
        failure = {'type': type(error).__name__, 'message': str(error)}
    return write(folder/'compatibility.json', {'research_only': True, 'calls': calls, 'controls': rows, 'error': failure,
        'compatible': failure is None and len(rows) == 2 and all(r['compatible'] for r in rows.values()),
        'never_a_case_selection_filter': True, 'model_failure_inferred': False})


def _export(case, folder):
    task = folder/'task'; (task/'public').mkdir(parents=True); (task/'private').mkdir()
    shutil.copyfile(checked(case['input']), task/'public/input.xlsx')
    shutil.copyfile(checked(case['goal']), task/'private/goal.xlsx')
    original = case['official_record']['instruction'].encode()
    appendix = ('\n\n---\nTransport context (file paths only):\nOriginal public input filename: '
        +Path(case['official_record']['spreadsheet_path']).name+'\nInput workbook: /app/input.xlsx\n'
        'Save the edited workbook to /app/output.xlsx.\n').encode()
    (task/'public/instruction.md').write_bytes(original+appendix)
    transport = write(folder/'instruction_transport.json', {'original_instruction_sha256': hashlib.sha256(original).hexdigest(),
        'rendered_instruction_sha256': hashlib.sha256(original+appendix).hexdigest(),
        'appended_bytes_utf8': appendix.decode(), 'original_prefix_byte_identical': True, 'business_or_target_hint_added': False})
    audit = folder/'private/worker_cap.json'
    export = export_resource_harbor(task, folder/'export', {'task_id': case['task_id'], 'mode': case['mode'],
        'source_kind': 'external_research', 'revision': 0, 'revision_hash': identity(case),
        'quality_or_difficulty_certified': False, 'difficulty_status': 'external_research_only',
        'original_instruction_sha256': hashlib.sha256(original).hexdigest(),
        'rendered_instruction_sha256': hashlib.sha256(original+appendix).hexdigest()}, ROOT, runtime_profile=PROFILE, audit_path=audit)
    require((export/'instruction.md').read_bytes() == original+appendix, 'The original instruction plus IO-only appendix changed')
    return export, inspect_resource_export(export, audit_path=audit), transport


class LaunchOrder:
    def __init__(self, keys):
        self.keys = list(keys); self.position = 0; self.condition = threading.Condition(); self.skipped = set()
    def _advance(self):
        while self.position < len(self.keys) and self.keys[self.position] in self.skipped:
            self.position += 1
    def launch(self, key, callback):
        with self.condition:
            require(key in self.keys[self.position:], 'A case launch cannot be repeated')
            while self.position < len(self.keys) and self.keys[self.position] != key:
                self.condition.wait(.2)
            require(self.position < len(self.keys), 'A case launch cannot be repeated')
            result = callback()
            self.position += 1; self._advance(); self.condition.notify_all()
            return result
    def enter(self, key):
        return self.launch(key, lambda: None)
    def skip(self, key):
        with self.condition:
            self.skipped.add(key); self._advance(); self.condition.notify_all()


def _model_core(case, folder, export, binding, config):
    task = {'task_id': case['task_id'], 'mode': case['mode'], 'revision': 0, 'revision_hash': binding['revision_hash'],
        'source_id': case['input']['sha256'], 'task_directory': str(export), 'harbor_export_binding': binding,
        'execution_budget': config['execution_budget']}
    source = write(folder/'source_view.json', {'source_kind': 'external_research', 'research_only': True,
        'selected_task_ids': [case['task_id']], 'tasks': [task], 'execution_budget': config['execution_budget'],
        'tool_time_policy_version': 3, 'tool_time_policy': dict(runner.POLICY_V3),
        'native_transport_profile': runner.transport_profile(), 'confirmation_or_publish_authorized': False})
    backend = yaml.safe_load((ROOT/'config/llm.yaml').read_text())
    backend.update(model=config['model'], reasoning_effort=config['reasoning_effort'],
        roles={'trace_agent': {'model': config['model'], 'reasoning_effort': config['reasoning_effort']}})
    directory = folder/'evaluation'
    async def once(directory, selection, audit, *, concurrency, backend_config):
        require(selection['selected_task_ids'] == [case['task_id']] and selection['n_attempts'] == 1
            and selection['phase'] == 'development' and concurrency == 1
            and selection['execution_budget'] == config['execution_budget'], 'Only one frozen original case attempt is allowed')
        await runner.execute_evaluation(directory, selection, audit, concurrency=1, backend_config=backend_config)
    with ResourceObserver(directory) as observer:
        runner.run_evaluation(source['path'], directory, phase='development', concurrency=1,
            project_root=ROOT, backend_config=backend, execute=once)
    selection = read(directory/'selection_manifest.json'); evaluation = read(directory/'evaluation_manifest.json')
    require(not evaluation.get('infrastructure_retries') and not evaluation.get('infra_history'), 'Research outer retries are forbidden')
    try:
        resources = validate_observation_receipt(directory, selection, evaluation)
    except Exception as error:
        runner._persist_failure(folder/'resource_failure', error)
        resources = {'passed': False, 'complete': False, 'error_type': type(error).__name__,
            'error_receipt': reference(folder/'resource_failure/private/evaluation_error.json')}
    return {'selection': reference(directory/'selection_manifest.json'), 'evaluation': reference(directory/'evaluation_manifest.json'),
        'resource_observation': observer.receipt, 'resources': resources, 'value': evaluation}


def _internal_case_model(request_path):
    request = read(request_path)
    require(request['implementation'] == reference(__file__) and request['runtime_profile'] == reference(PROFILE),
        'The isolated model process code or profile changed')
    case = request['case']; checked(case['input']); checked(case['goal'])
    folder = Path(request['folder']); export = Path(request['export'])
    require(inspect_resource_export(export, audit_path=folder/'private/worker_cap.json') == request['binding'],
        'The isolated model export changed')
    try:
        value = _model_core(case, folder, export, request['binding'], request['policy'])
        terminal = {'kind': 'isolated_official_research_native_attempt', 'passed_transport': True,
            'request': reference(request_path), 'pid': os.getpid(), 'model': value}
    except BaseException as error:
        runner._persist_failure(folder/'model_process_failure', error)
        retained = {label: reference(folder/'evaluation'/name) for label,name in
            (('selection','selection_manifest.json'), ('evaluation','evaluation_manifest.json'))
            if (folder/'evaluation'/name).is_file()}
        terminal = {'kind': 'isolated_official_research_native_attempt', 'passed_transport': False,
            'request': reference(request_path), 'pid': os.getpid(), 'retained_records': retained,
            'error': reference(folder/'model_process_failure/private/evaluation_error.json')}
    return write(folder/'model_process_terminal.json', terminal)


def _model_subprocess(case, folder, export, binding, config, order):
    request = write(folder/'model_process_request.json', {'case': case, 'folder': str(folder),
        'export': str(export), 'binding': binding, 'policy': config,
        'implementation': reference(__file__), 'runtime_profile': reference(PROFILE)})
    command = [sys.executable, str(Path(__file__).resolve()), '--internal-case-model', request['path']]
    with (folder/'model_process_stdout.log').open('xb') as log:
        process = order.launch(case['case_key'], lambda: subprocess.Popen(command, cwd=ROOT,
            stdout=log, stderr=subprocess.STDOUT, env=dict(os.environ)))
        write(folder/'model_process_started.json', {'at': now(), 'pid': process.pid, 'request': request,
            'isolation': 'separate_process_environment', 'credentials_in_arguments': False})
        code = process.wait()
    terminal_path = folder/'model_process_terminal.json'
    require(terminal_path.is_file(), 'The isolated model process ended without its retained terminal')
    terminal = read(terminal_path)
    require(terminal['request'] == request, 'The child result does not bind the original request')
    if not terminal['passed_transport']:
        raise RuntimeError('Isolated native setup failed; inspect model_process_terminal.json and redacted failure')
    require(code == 0, 'The isolated model process did not exit normally')
    value = terminal['model']; value['process_terminal'] = reference(terminal_path)
    return value


def protocol_score(official, attempt, model):
    """Keep official artifact accuracy separate from resource/timing eligibility."""
    raw = official.get('result', {}).get('accuracy') if isinstance(official.get('result'), dict) else None
    resources = model.get('resources', {})
    timing = attempt.get('tool_time', {})
    supported = resources.get('passed') is True and resources.get('complete') is True
    budget_failed = (supported and attempt.get('status') == 'scored'
        and attempt.get('failure_kind') == 'cumulative_tool_budget_exhausted'
        and timing.get('passed') is False)
    normal = (supported and model['value'].get('status') == 'completed'
        and attempt.get('status') == 'scored' and not attempt.get('failure_kind')
        and timing.get('passed') is True)
    return {'official_raw_accuracy': raw, 'protocol_effective_accuracy': 0 if budget_failed else raw if normal else None,
        'protocol_state': 'known_tool_budget_failure' if budget_failed else 'complete' if normal else 'unknown',
        'native_run_complete': normal, 'infrastructure_or_timing_unknown_is_not_model_zero': not normal and not budget_failed}


def _case(case, output, config, evaluator_ref, audit, order):
    folder = output/'cases'/case['task_id']; folder.mkdir(parents=True)
    start = time.monotonic(); result = None; records = {}
    try:
        if not case['requires_new_model_attempt']:
            order.enter(case['case_key']); result = reused_result(case)
        else:
            evaluator = load(checked(evaluator_ref), '_official_'+case['task_id'].replace('-', '_'))
            compatibility = write(folder/'compatibility.json', {'status': 'not_run',
                'reason': 'Optional project compatibility controls are not prerequisites for official research attempts',
                'actual_LO_calls': 0, 'never_a_case_selection_filter': True})
            records['compatibility'] = compatibility
            export, binding, transport = _export(case, folder)
            records['instruction_transport'] = transport
            audit.task(case['task_id'], mode=case['mode'], case_key=case['case_key'],
                status='model_running', node='single_native_attempt')
            model = _model_subprocess(case, folder, export, binding, config, order)
            records['model'] = {k:v for k,v in model.items() if k != 'value'}
            attempts = model['value'].get('attempts', [])
            require(len(attempts) == 1 and attempts[0]['task_id'] == case['task_id'], 'Retain exactly one original native attempt')
            attempt = attempts[0]; trial = folder/'evaluation/harbor_jobs'/attempt['job_name']/attempt['trial_name']
            submitted = trial/'artifacts/app/output.xlsx'; alias_dir = folder/'private/official_submission'; alias_dir.mkdir(parents=True)
            alias = alias_dir/(case['official_task_id']+'_output.xlsx')
            if submitted.is_file():
                before = reference(submitted); shutil.copyfile(submitted, alias)
                require(reference(alias)['sha256'] == before['sha256'], 'The identical submitted artifact is required')
            official = _official(evaluator, evaluator_ref, case, checked(case['input']), checked(case['goal']), alias)
            if submitted.is_file(): require(reference(submitted) == before, 'Official postscore cannot modify the submission')
            scoring = protocol_score(official, attempt, model); normal = scoring['native_run_complete']
            result = {'case_key': case['case_key'], 'task_id': case['task_id'], 'disposition': 'new_first_attempt',
                'new_model_calls': 1, 'compatibility': compatibility, 'instruction_transport': transport,
                'model': {k:v for k,v in model.items() if k != 'value'}, 'official_primary': official,
                'project_exact_diagnostic': {'reward': attempt.get('reward'), 'tool_time': attempt.get('tool_time')},
                **scoring,
                'official_primary_accuracy': official['result'].get('accuracy') if isinstance(official['result'], dict) else None,
                'official_score_is_raw_artifact_score': True,
                'official_model_failure': normal and isinstance(official['result'], dict) and official['result'].get('accuracy') == 0,
                'research_only': True, 'qualified': False}
    except Exception as error:
        # Advance a failed preparation's fixed slot, so other official cases are not filtered away.
        order.skip(case['case_key'])
        runner._persist_failure(folder, error)
        records['redacted_error'] = reference(folder/'private/evaluation_error.json')
        for name in ('model_process_terminal.json', 'model_process_started.json'):
            if (folder/name).is_file(): records[name] = reference(folder/name)
        result = {'case_key': case['case_key'], 'task_id': case['task_id'], 'disposition': 'infrastructure_or_driver_hold',
            'error_type': type(error).__name__, 'error_details': 'Inspect retained upstream receipts; no private backend values copied.',
            'retained_records': records, 'official_model_failure': False,
            'no_retry': True, 'all_partial_artifacts_preserved': True, 'qualified': False}
    result['elapsed_seconds'] = time.monotonic()-start
    receipt = write(folder/'terminal.json', result)
    audit.task(case['task_id'], mode=case['mode'], case_key=case['case_key'], status=result['disposition'], terminal=receipt)
    audit.export(); return receipt


def execute_prepared(output):
    output = Path(output).absolute(); frozen, inventory = validate_prepared(output)
    require(not (output/'started.json').exists(), 'Preserve the first complete cohort attempt')
    lease = ProducerLease(output).acquire(); audit = server = thread = None
    start = time.monotonic(); receipts = {}; stop = threading.Event()
    old_tmp = os.environ.get('TMPDIR'); old_cache = tempfile.tempdir
    temporary = output/'temporary'; temporary.mkdir(); os.environ['TMPDIR'] = str(temporary); tempfile.tempdir = str(temporary)
    try:
        registry = ROOT/'outputs/research/external_calibration_first_selection_registry'; registry.mkdir(exist_ok=True)
        reservations = []
        for case in inventory['cases']:
            if case['requires_new_model_attempt']:
                reservations.append(write(registry/(identity(case)+'.json'), {'kind': 'external_research_first_attempt_reservation',
                    'case_id': case['task_id'], 'case_identity': identity(case), 'cohort': reference(output/'preparation.json'),
                    'model': frozen['policy']['model'], 'effective_infrastructure_retries': 0, 'at': now()}))
        write(output/'started.json', {'at': now(), 'preparation': reference(output/'preparation.json'),
            'reservations': reservations, 'complete_execution_order': frozen['execution_order'], 'outer_retries': 0})
        audit = AuditStore(output/'audit', {'id': output.name, 'name': 'All fixed official FM and Debugging research cases',
            'target_count': 0, 'official_case_count': len(inventory['cases']), 'status': 'running', 'producer_pid': os.getpid(),
            'research_only': True, 'qualified': False})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=0); url = server.start()
        audit.update_run(dashboard_url=url, producer_active=True)
        print(json.dumps({'dashboard_url': url, 'pid': os.getpid(), 'case_count': len(inventory['cases'])}), flush=True)
        def heartbeat():
            while not stop.wait(15):
                audit.update_run(elapsed_seconds=time.monotonic()-start, completed_cases=len(receipts))
                audit.export()
        thread = threading.Thread(target=heartbeat, daemon=True); thread.start()
        write(output/'actual_base_image.json', verify_local_base_image(PROFILE))
        cases = {c['case_key']: c for c in inventory['cases']}; order = LaunchOrder(frozen['execution_order'])
        with ThreadPoolExecutor(max_workers=frozen['policy']['concurrency']) as pool:
            pending = {pool.submit(_case, cases[key], output, frozen['policy'], inventory['official_evaluator'], audit, order): key
                for key in frozen['execution_order']}
            for future in as_completed(pending):
                key = pending[future]; receipts[key] = future.result()
                audit.update_run(completed_cases=len(receipts), elapsed_seconds=time.monotonic()-start); audit.export()
                print(json.dumps({'completed_case': key, 'terminal': receipts[key]}), flush=True)
        return write(output/'terminal.json', {'kind': 'complete_external_official_calibration_cohort', 'version': 1,
            'inventory': frozen['inventory'], 'preparation': reference(output/'preparation.json'),
            'case_order': frozen['execution_order'], 'cases': [{'case_key': key, 'terminal': receipts[key]} for key in frozen['execution_order']],
            'all_declared_cases_retained': True, 'automatic_retries': 0, 'official_original_evaluator_is_primary': True,
            'project_exact_is_diagnostic_only': True, 'qualified': False, 'production_seed_or_release_eligible': False,
            'elapsed_seconds': time.monotonic()-start})
    except BaseException as error:
        runner._persist_failure(output, error)
        write(output/'cohort_failure.json', {'at': now(), 'preparation': reference(output/'preparation.json'),
            'error': reference(output/'private/evaluation_error.json'), 'completed_cases': receipts,
            'no_retry': True, 'qualified': False})
        raise
    finally:
        stop.set()
        if thread: thread.join(timeout=1)
        if audit:
            audit.update_run(status='completed' if len(receipts) == len(inventory['cases']) else 'infrastructure_hold', producer_active=False)
            audit.export()
        if server: server.stop()
        if audit: audit.db.close()
        lease.release()
        if old_tmp is None: os.environ.pop('TMPDIR', None)
        else: os.environ['TMPDIR'] = old_tmp
        tempfile.tempdir = old_cache


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--internal-case-model', type=Path, help=argparse.SUPPRESS)
    parser.add_argument('--inventory', type=Path); parser.add_argument('--output', type=Path)
    parser.add_argument('--config', type=Path, default=CONFIG); parser.add_argument('--prepared', type=Path)
    parser.add_argument('--run', action='store_true'); args = parser.parse_args()
    if args.internal_case_model:
        require(not args.run and args.prepared is None and args.inventory is None and args.output is None,
            'Internal process accepts only its frozen request')
        print(json.dumps(_internal_case_model(args.internal_case_model))); return 0
    if args.prepared:
        require(args.inventory is None and args.output is None and args.config == CONFIG, 'Do not replace a frozen cohort')
        result = execute_prepared(args.prepared) if args.run else validate_prepared(args.prepared)[0]
    else:
        require(args.inventory is not None and args.output is not None, 'Supply the complete inventory and a fresh output')
        result = prepare(args.inventory, args.output, configuration=args.config)
        if args.run: result = execute_prepared(args.output)
    print(json.dumps(result)); return 0


if __name__ == '__main__':
    raise SystemExit(main())

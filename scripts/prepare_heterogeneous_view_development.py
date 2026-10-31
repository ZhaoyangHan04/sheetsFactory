#!/usr/bin/env python3
"""Build one independently bound business-view development task.

The source must already have three actual calculation passes. This script then
normalizes both projected books twice, checks five actual local controls, and
exports a frozen development snapshot. It performs no model call and grants no
quality, Harbor-control, difficulty or release qualification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.task_adapters import heterogeneous_financial_view as view
from sheets_factory.workbook.heterogeneous_contracts.validate import compare_typed_caches
from sheets_factory.workbook.resource_engine import ResourceLibreOfficeEngine, load_runtime_profile
from sheets_factory.evaluation.streaming_verifier import compare_files
from sheets_factory.evaluation.streaming_delta import compare_workbooks
from sheets_factory.evaluation.resource_harbor import (
    export_resource_harbor, inspect_resource_export, verify_local_base_image)
from sheets_factory.evaluation.budget import validate_execution_budget

PROFILE = ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'
CONTROL_REWARDS = {'oracle':1, 'nop':0, 'equivalent':1, 'missed_root':0, 'extra_change':0}
BUDGET = {'version':1, 'elapsed_policy':'operational_guard',
    'elapsed_guard_seconds':14400, 'tool_budget_seconds':1800}
PENDING = ['public_only_recovery', 'all_twelve_quality_checks', 'actual_Harbor_oracle_nop',
    'strongest_model_development', 'frozen_cohort_confirmation', 'final_full_directory_oracle']


def support():
    path = ROOT / 'scripts/build_heterogeneous_source.py'
    definition = importlib.util.spec_from_file_location('_heterogeneous_view_development_support', path)
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


def recipes():
    paths = [Path(__file__), Path(view.__file__), view.DEFAULT_POLICY, PROFILE,
        ROOT / 'scripts/build_heterogeneous_source.py',
        ROOT / 'src/sheets_factory/workbook/heterogeneous_contracts/validate.py',
        ROOT / 'src/sheets_factory/evaluation/streaming_verifier.py',
        ROOT / 'src/sheets_factory/evaluation/streaming_delta.py',
        ROOT / 'src/sheets_factory/evaluation/resource_harbor.py',
        ROOT / 'src/sheets_factory/evaluation/resource_streaming_verifier.py',
        ROOT / 'src/sheets_factory/workbook/resource_engine.py',
        ROOT / 'src/sheets_factory/workbook/engine.py',
        ROOT / 'src/sheets_factory/workbook/uno_recalculate.py']
    return {str(p.resolve()):view.reference(p)['sha256'] for p in paths}


def check_preparation(output):
    helper = support()
    frozen = helper.read(Path(output) / 'preparation.json')
    view.require(frozen.get('kind') == 'prepared_heterogeneous_business_view_development'
        and frozen['recipe'] == recipes(), 'The frozen development recipe changed')
    helper.checked(frozen['source_manifest'])
    view.require(view.validate_source(frozen['source_manifest']) == frozen['source_admission'],
        'The complete actual source admission changed')
    return frozen


def prepare(source_manifest, output):
    helper = support()
    output = helper._output(output, fresh=True)
    output.mkdir(parents=True)
    try:
        source = view.reference(source_manifest)
        proof = view.validate_source(source)
        return helper.write_new(output / 'preparation.json', {
            'kind':'prepared_heterogeneous_business_view_development', 'version':1,
            'prepared_at':utcnow(), 'source_manifest':source, 'source_admission':proof,
            'recipe':recipes(), 'model_calls':0, 'new_LO_calls':0, 'task_count':0,
            'qualified':False, 'pending':PENDING})
    except BaseException as error:
        helper.write_new(output / 'preparation_failure.json', {'status':'failed',
            'error_type':type(error).__name__, 'error':str(error), 'model_calls':0,
            'new_LO_calls':0, 'task_count':0, 'qualified':False})
        raise


def create_control_variants(plan, normalized_goal, output):
    """Make actual variants of the same complete goal; never synthesize scores."""
    output = Path(output)
    candidates = [r for r in plan['forecast_targets'] if r['reference_value'][0] == 'number'
        and r['source']['kind'] == 'money_pence']
    view.require(bool(candidates), 'An observable monetary forecast control is required')
    selected = candidates[0]
    unit_value = Decimal(selected['reference_value'][1])
    pence = unit_value * 100
    view.require(pence == pence.to_integral_value(), 'The control amount must be an exact posted penny')
    raw = {}
    for name in ('equivalent', 'missed_root', 'extra_change'):
        book = openpyxl.load_workbook(normalized_goal, keep_links=False)
        try:
            if name == 'equivalent':
                book[selected['sheet']][selected['cell']] = '=' + str(int(pence)) + '/100'
            elif name == 'missed_root':
                book[selected['sheet']][selected['cell']] = None
            else:
                # A visible, fixed template title is outside every target.
                sheet = book[selected['sheet']]
                view.require(isinstance(sheet['A1'].value, str), 'The protected public title is absent')
                sheet['A1'] = sheet['A1'].value + ' changed'
            path = output / (name + '.raw.xlsx')
            book.save(path);raw[name] = path
        finally:
            book.close()
    return raw, {'sheet':selected['sheet'], 'cell':selected['cell'],
        'posted_pence':int(pence), 'missing_control_is_one_forecast_value':True,
        'extra_control_coordinate':selected['sheet']+'!A1'}


def freeze_snapshot(output, task, plan, frozen, controls, delta, calls, profile):
    """Export immutable development bytes, without pretending normal QA ran."""
    helper = support()
    source_id = frozen['source_admission']['workbook']['sha256']
    revision_hash = hashlib.sha256((task / 'public/input.xlsx').read_bytes()
        + (task / 'public/instruction.md').read_bytes()).hexdigest()
    task_id = 'fm-heterogeneous-H01-' + revision_hash[:12]
    history = []
    for path in sorted((ROOT / 'outputs/difficulty').rglob('selection_manifest.json')):
        previous = helper.read(path)
        for row in previous.get('tasks', []):
            view.require(row.get('revision_hash') != revision_hash and row.get('task_id') != task_id,
                'This exact task already has a model selection; do not resample it')
        history.append(view.reference(path))
    base = helper.write_new(output / 'actual_base_image.json', verify_local_base_image(PROFILE))
    export = output / 'SpreadsheetEval' / task_id
    export_resource_harbor(task, export, {'task_id':task_id, 'mode':'financial_modeling',
        'source_id':source_id, 'source_file':'heterogeneous-native-business-source.xlsx',
        'revision':0, 'revision_hash':revision_hash, 'difficulty_status':'prequality_development_probe',
        'base_image':profile['image']['id']}, ROOT, runtime_profile=PROFILE)
    binding = inspect_resource_export(export)
    inventory = {p.relative_to(export).as_posix():view.reference(p)
        for p in export.rglob('*') if p.is_file()}
    from sheets_factory.evaluation.resource_frontier import TASK_FILES
    view.require(set(inventory) == set(TASK_FILES), 'The full resource task inventory differs')
    budget = validate_execution_budget(BUDGET)
    item = {'task_id':task_id, 'mode':'financial_modeling', 'revision':0,
        'revision_hash':revision_hash, 'source_id':source_id,
        'task_directory':str(export), 'harbor_export_binding':binding,
        'execution_budget':budget, 'timeout_seconds':14400, 'local_controls':CONTROL_REWARDS}
    manifest = {'kind':'prequality_heterogeneous_business_view_development', 'version':1,
        'frozen_at':utcnow(), 'selected_task_ids':[task_id], 'tasks':[item],
        'execution_budget':budget, 'timeout_seconds':14400, 'tool_time_policy_version':3,
        'source_manifest':frozen['source_manifest'], 'source_admission':frozen['source_admission'],
        'complete_changed_value_set_count':delta['expected_change_count'],
        'declared_business_slots':plan['declared_slot_count'], 'plan_sha256':plan['plan_sha256'],
        'local_controls':controls, 'actual_engine_calls':calls, 'actual_local_base_image':base,
        'resource_task_inventory':inventory, 'prior_model_selection_inventory':history,
        'recipe':recipes(), 'normal_Factory_nodes_executed':False,
        'public_only_recovery_executed':False, 'all_quality_checks_executed':False,
        'actual_Harbor_control_jobs_executed':False, 'strongest_model_executed':False,
        'pending':PENDING, 'model_calls':0, 'qualified':False, 'task_count':0}
    return helper.write_new(output / 'probe_manifest.json', manifest)


def execute_prepared(output, *, port=0):
    helper = support();output = helper._output(output)
    frozen = check_preparation(output)
    view.require(not (output / 'started.json').exists(), 'Preserve the first attempt; use a fresh output')
    lease = ProducerLease(output).acquire()
    audit = server = None;calls = [];started = time.monotonic();status = 'failed'
    try:
        audit = AuditStore(output / 'audit', {'id':output.name, 'name':'Heterogeneous business view development',
            'status':'starting', 'target_count':0, 'qualified':0, 'producer_active':True,
            'producer_pid':os.getpid(), 'development_only':True})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port)
        url = server.start()
        helper.write_new(output / 'started.json', {'started_at':utcnow(), 'dashboard_url':url,
            'preparation':view.reference(output / 'preparation.json'), 'producer_pid':os.getpid(),
            'model_calls':0, 'task_count':0, 'qualified':False})
        audit.update_run(status='running', dashboard_url=url)
        print(json.dumps({'dashboard_url':url, 'output':str(output)}), flush=True)
        with helper.data_temporary(output):
            with helper.stage(audit, 'plan_and_materialize_fully_masked_business_view'):
                plan = view.build_view_plan(frozen['source_manifest'], enabled=True)
                helper.write_new(output / 'private_plan.json', plan)
                projection = view.materialize_view(plan, output / 'projection', enabled=True)
                helper.write_new(output / 'projection.json', projection)
            profile = load_runtime_profile(PROFILE)
            runtime = {'runtime_profile':view.reference(PROFILE), 'runtime_profile_value':profile}
            engine = ResourceLibreOfficeEngine(ROOT, PROFILE, role='source', receipt_directory=output / 'engine_resources')
            engine.ensure_image()
            def recalc(source, target, label):
                record = {'index':len(calls)+1, 'label':label, 'input':view.reference(source),
                    'destination':str(target), 'started_at':utcnow(), 'completed':False}
                calls.append(record)
                helper.write_new(output / ('LO'+str(record['index'])+'_started.json'), dict(record))
                with helper.stage(audit, label):
                    try:
                        clock = time.monotonic();actual = engine.recalculate(source, target)
                        record.update(completed=True, output=view.reference(actual), elapsed_seconds=time.monotonic()-clock)
                        receipt = engine.metadata()['actual_resource_receipts'][-1]
                        record['actual_resource_evidence'] = helper.validate_actual_call(record, receipt, runtime)
                    finally:
                        record['finished_at'] = utcnow()
                        helper.write_new(output / ('LO'+str(record['index'])+'_terminal.json'), dict(record))
                return actual
            task = output / 'task';(task / 'public').mkdir(parents=True);(task / 'private').mkdir()
            shutil.copyfile(projection['instruction']['path'], task / 'public/instruction.md')
            normalized = {}
            for role, relative in (('input','public/input.xlsx'), ('goal','private/goal.xlsx')):
                normalized[role] = recalc(Path(projection[role]['path']), task / relative, 'normalize_'+role)
                repeat = recalc(normalized[role], output / (role+'_stable.xlsx'), 'repeat_'+role)
                comparison = compare_typed_caches(normalized[role], repeat)
                helper.write_new(output / (role+'_typed_stability.json'), comparison)
                view.require(comparison['passed'] is True, 'Projected business values are not stable')
                preservation = compare_typed_caches(projection[role]['path'], normalized[role])
                helper.write_new(output / (role+'_actual_value_preservation.json'), preservation)
                view.require(preservation['passed'] is True, 'Actual projection normalization changed business values')
            with helper.stage(audit, 'full_projection_D_and_control_variants'):
                delta = compare_workbooks(normalized['input'], normalized['goal'], normalized['goal'])
                view.require(delta['reward']==1 and delta['expected_change_count']>0, 'The complete expected change set is empty or invalid')
                count = sum(r['reference_value'][0]!='empty' for r in plan['forecast_targets'])
                view.require(delta['expected_change_count']==count, 'The actual modified set differs from all applicable business targets')
                helper.write_new(output / 'complete_delta.json', delta)
                variants, selected = create_control_variants(plan, normalized['goal'], output)
                helper.write_new(output / 'control_selection.json', selected)
            reports = {}
            control_files = {'oracle':normalized['goal'], 'nop':normalized['input']}
            for name, raw in variants.items():
                control_files[name] = recalc(raw, output / (name+'.xlsx'), 'actual_control_'+name)
            with helper.stage(audit, 'score_all_five_actual_local_controls'):
                for name, path in control_files.items():
                    report = compare_files(normalized['input'], normalized['goal'], path)
                    reports[name] = helper.write_new(output / (name+'_comparison.json'), report)
                    view.require(report['reward']==CONTROL_REWARDS[name], 'An actual local control failed: '+name)
                controls = {'rewards':CONTROL_REWARDS, 'reports':reports,
                    'workbooks':{name:view.reference(p) for name,p in control_files.items()},
                    'actual_LO_calls':len(calls), 'actual_Harbor_jobs':0}
                helper.write_new(output / 'local_controls.json', controls)
            with helper.stage(audit, 'freeze_separate_development_export'):
                view.require(check_preparation(output)==frozen, 'Source or recipe changed during construction')
                manifest = freeze_snapshot(output, task, plan, frozen, controls, delta, calls, profile)
            status = 'development_snapshot_verified_quality_pending'
            helper.write_new(output / 'terminal.json', {'status':status, 'finished_at':utcnow(),
                'manifest':manifest, 'elapsed_seconds':time.monotonic()-started,
                'engine_calls':calls, 'model_calls':0, 'task_count':0, 'qualified':False})
            return manifest
    except BaseException as error:
        helper.write_new(output / 'failure.json', {'status':'failed', 'finished_at':utcnow(),
            'error_type':type(error).__name__, 'error':str(error), 'traceback':traceback.format_exc(),
            'engine_calls':calls, 'elapsed_seconds':time.monotonic()-started, 'model_calls':0,
            'task_count':0, 'qualified':False, 'all_partial_artifacts_preserved':True})
        raise
    finally:
        try:
            if audit:
                audit.update_run(status=status, producer_active=False, finished_at=utcnow())
                audit.export()
        finally:
            if server:server.stop()
            if audit:audit.db.close()
            lease.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.prepared:
        view.require(args.source_manifest is None and args.output is None, 'Prepared execution retains its frozen source and output')
        output = args.prepared
    else:
        view.require(args.source_manifest is not None and args.output is not None, 'Specify the verified source and a fresh output')
        output = args.output;print(json.dumps(prepare(args.source_manifest, output)), flush=True)
    if args.run:print(json.dumps(execute_prepared(output, port=args.port)), flush=True)


if __name__ == '__main__':
    main()

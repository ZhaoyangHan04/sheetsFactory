#!/usr/bin/env python3
"""Construct one policy-fault development task from a newly verified source.

Preparation only freezes the source and compiler recipe. Explicit execution
checks four separate family effects, three joint calculation passes, complete
typed stability, full D and five local controls. No model or quality is implied.
"""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time
import traceback

import openpyxl
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.resume import ProducerLease
from sheets_factory.task_adapters import heterogeneous_financial_view as view
from sheets_factory.task_adapters import heterogeneous_specialized_source as admission
from sheets_factory.task_adapters import heterogeneous_specialized_debugging as faults
from sheets_factory.workbook.heterogeneous_contracts.validate import compare_typed_caches
from sheets_factory.workbook.resource_engine import ResourceLibreOfficeEngine, load_runtime_profile
from sheets_factory.evaluation.streaming_verifier import compare_files
from sheets_factory.evaluation.streaming_delta import compare_workbooks
from sheets_factory.evaluation.resource_harbor import export_resource_harbor, inspect_resource_export, verify_local_base_image
from sheets_factory.evaluation.budget import validate_execution_budget

PROFILE = ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'
CONTROL_REWARDS = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard', 'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}
PENDING = ['public_only_recovery', 'all_twelve_quality_checks', 'actual_Harbor_oracle_nop',
    'strongest_model_development', 'frozen_cohort_confirmation', 'final_full_directory_oracle']
TEMPLATE = ROOT / 'scripts/prepare_heterogeneous_view_development.py'
TEMPLATE_SHA = '2dde40a6b1f99e3b140a01e0a99b18c72213069d271da352498a3742d8ab2ef3'


def support():
    path = ROOT / 'scripts/build_heterogeneous_source.py'
    definition = importlib.util.spec_from_file_location('_specialized_debug_build_support', path)
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


def recipes():
    paths = [Path(__file__), Path(admission.__file__), Path(faults.__file__), TEMPLATE,
        ROOT / 'scripts/build_specialized_heterogeneous_source.py',
        ROOT / 'src/sheets_factory/task_adapters/heterogeneous_localized_debugging.py',
        ROOT / 'src/sheets_factory/task_adapters/heterogeneous_formula_identity.py',
        ROOT / 'src/sheets_factory/workbook/heterogeneous_contracts/policy_specialization.py']
    helper_definition = importlib.util.spec_from_file_location('_specialized_debug_recipe_template', TEMPLATE)
    module = importlib.util.module_from_spec(helper_definition)
    module.__file__ = str(TEMPLATE)
    helper_definition.loader.exec_module(module)
    original = module.recipes()
    original.update({str(p.resolve()): view.reference(p)['sha256'] for p in paths})
    return original


def frozen_export_ast():
    raw = TEMPLATE.read_bytes()
    view.require(hashlib.sha256(raw).hexdigest() == TEMPLATE_SHA, 'The complete development export template changed')
    tree = ast.parse(raw)
    definitions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'freeze_snapshot']
    view.require(len(definitions) == 1, 'The frozen export function is absent or duplicated')
    function = definitions[0]
    replacements = {'fm-heterogeneous-H01-': 'dbg-heterogeneous-specialized-H01-',
        'financial_modeling': 'debugging', 'heterogeneous-native-business-source.xlsx': 'heterogeneous-specialized-source.xlsx',
        'prequality_heterogeneous_business_view_development': 'prequality_specialized_heterogeneous_debugging_development'}
    counts = {key: 0 for key in replacements}
    class Replace(ast.NodeTransformer):
        def visit_Constant(self, node):
            if isinstance(node.value, str) and node.value in replacements:
                old = node.value; node.value = replacements[old]; counts[old] += 1
            return node
    function = Replace().visit(function)
    view.require(counts == {'fm-heterogeneous-H01-': 1, 'financial_modeling': 2,
        'heterogeneous-native-business-source.xlsx': 1, 'prequality_heterogeneous_business_view_development': 1},
        'The bounded debugging export identity substitutions changed')
    return ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[]))


exec(compile(frozen_export_ast(), str(TEMPLATE), 'exec'), globals())


def public_brief():
    return ('Review the supplied monthly forecast and correct its formula errors so that the financial statements, '
        'debt, tax and covenant schedules follow the supplied assumptions and Contract Notes across all entities '
        'and scenarios. Preserve provided assumptions, dates, labels, formatting, worksheet names and order; '
        'retain unrelated formulas and policy-defined blanks. Correct results may recalculate throughout the '
        'workbook. Do not add worksheets or helper cells. Read /app/input.xlsx and save /app/output.xlsx. '
        'Values are checked after LibreOffice recalculation.')


def prepare(source_manifest, output):
    helper = support(); output = helper._output(output, fresh=True); output.mkdir(parents=True)
    try:
        proof = admission.validate_source(source_manifest)
        return helper.write_new(output / 'preparation.json', {'kind': 'prepared_specialized_debugging_development',
            'version': 1, 'prepared_at': utcnow(), 'source_manifest': view.reference(source_manifest),
            'source_admission': proof, 'recipe': recipes(), 'setting': faults.setting(enabled=True),
            'instruction_sha256': hashlib.sha256(public_brief().encode()).hexdigest(),
            'new_LO_calls': 0, 'model_calls': 0, 'qualified': False})
    except BaseException as error:
        helper.write_new(output / 'preparation_failure.json', {'status': 'failed',
            'error_type': type(error).__name__, 'error': str(error), 'model_calls': 0, 'qualified': False})
        raise


def _mutant(source, path, edits):
    book = openpyxl.load_workbook(source, keep_links=False)
    try:
        # Source LO may legally remove redundant worksheet quotes. Formula
        # identity is checked separately by the complete canonical signatures.
        from sheets_factory.task_adapters.heterogeneous_formula_identity import formula_signature
        for edit in edits:
            cell = book[edit['sheet']][edit['cell']]
            view.require(cell.data_type == 'f' and formula_signature(cell.value) == formula_signature(edit['before_formula']),
                'An actual source formula differs from its complete bound definition')
            cell.value = edit['after_formula']
        book.save(path)
    finally:
        book.close()


def execute_prepared(output, *, port=0):
    helper = support(); output = helper._output(output)
    frozen = helper.read(output / 'preparation.json')
    view.require(frozen['kind'] == 'prepared_specialized_debugging_development'
        and frozen['recipe'] == recipes() and frozen['setting'] == faults.setting(enabled=True), 'The frozen debugging recipe changed')
    view.require(not (output / 'started.json').exists(), 'Preserve the first attempt and choose a fresh output')
    lease = ProducerLease(output).acquire(); audit = server = None; calls = []; clock = time.monotonic(); status = 'failed'
    try:
        audit = AuditStore(output / 'audit', {'id': output.name, 'name': 'Specialized policy debugging development',
            'status': 'running', 'qualified': 0, 'producer_active': True, 'producer_pid': __import__('os').getpid()})
        server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port); url = server.start()
        helper.write_new(output / 'started.json', {'started_at': utcnow(), 'preparation': view.reference(output / 'preparation.json'),
            'dashboard_url': url, 'model_calls': 0, 'qualified': False})
        audit.update_run(dashboard_url=url)
        print(json.dumps({'dashboard_url': url, 'output': str(output)}), flush=True)
        with helper.data_temporary(output):
            with helper.stage(audit, 'cold_source_admission_and_complete_policy_fault_compilation'):
                proof, public, bindings, _, _ = admission.load_source(frozen['source_manifest'])
                view.require(proof == frozen['source_admission'], 'The source admission changed')
                plan = faults.compile_policy_mutations(public, bindings, enabled=True)
                plan['source_admission'] = proof
                helper.write_new(output / 'mutation_proposal.json', plan)
                source = Path(proof['workbook']['path'])
            engine = ResourceLibreOfficeEngine(ROOT, PROFILE, role='source', receipt_directory=output / 'engine_resources')
            engine.ensure_image(); profile = load_runtime_profile(PROFILE)
            runtime = {'runtime_profile': view.reference(PROFILE), 'runtime_profile_value': profile}
            def recalc(path, destination, label):
                record = {'index': len(calls)+1, 'label': label, 'input': view.reference(path),
                    'destination': str(destination), 'started_at': utcnow(), 'completed': False}; calls.append(record)
                helper.write_new(output / ('LO'+str(record['index'])+'_started.json'), dict(record))
                with helper.stage(audit, label):
                    try:
                        t = time.monotonic(); result = engine.recalculate(path, destination)
                        record.update(completed=True, output=view.reference(result), elapsed_seconds=time.monotonic()-t)
                        record['actual_resource_evidence'] = helper.validate_actual_call(record,
                            engine.metadata()['actual_resource_receipts'][-1], runtime)
                    finally:
                        record['finished_at'] = utcnow()
                        helper.write_new(output / ('LO'+str(record['index'])+'_terminal.json'), dict(record))
                return result
            effects = {}
            for family in faults.FAMILIES:
                with helper.stage(audit, 'materialize_individual_'+family):
                    raw = output / (family+'.raw.xlsx')
                    _mutant(source, raw, [e for e in plan['mutations'] if e['family'] == family])
                actual = recalc(raw, output / (family+'.xlsx'), 'actual_individual_'+family)
                delta = compare_workbooks(actual, source, source)
                view.require(delta['reward'] == 1 and delta['expected_change_count'] > 0,
                    'A policy family has no actual observable effect: '+family)
                effects[family] = helper.write_new(output / (family+'_complete_effect.json'), delta)
            task = output / 'task'; (task / 'public').mkdir(parents=True); (task / 'private').mkdir()
            with helper.stage(audit, 'materialize_joint_faults'):
                raw = output / 'joint.raw.xlsx'; _mutant(source, raw, plan['mutations'])
                shutil.copyfile(source, task / 'private/goal.xlsx')
                (task / 'public/instruction.md').write_text(public_brief())
            actual = recalc(raw, task / 'public/input.xlsx', 'actual_joint_pass1')
            for index in (2, 3):
                repeat = recalc(actual, output / ('joint_pass'+str(index)+'.xlsx'), 'actual_joint_pass'+str(index))
                comparison = compare_typed_caches(task / 'public/input.xlsx', repeat)
                helper.write_new(output / ('joint_typed_stability_'+str(index)+'.json'), comparison)
                view.require(comparison['passed'], 'The complete joint mutant has unstable typed values'); actual = repeat
            delta = compare_workbooks(task / 'public/input.xlsx', task / 'private/goal.xlsx', task / 'private/goal.xlsx')
            view.require(delta['reward'] == 1 and delta['expected_change_count'] > 0, 'The complete joint D is empty or invalid')
            helper.write_new(output / 'complete_delta.json', delta)
            from sheets_factory.evaluation.streaming_verifier import _sparse_cells
            book = openpyxl.load_workbook(source, read_only=True, data_only=True)
            try:
                changed = set(delta['expected_changes'])
                candidates = {(e['sheet'], e['cell']): e for e in plan['mutations']
                    if e['sheet']+'!'+e['cell'] in changed}
                first = next((s.title, get_column_letter(key[1])+str(key[0]), c['value'])
                    for s in book for key, c in _sparse_cells(s)
                    if (s.title, get_column_letter(key[1])+str(key[0])) in candidates
                    and type(c['value']) in (int, float))
            finally:
                book.close()
            reports = {}; control_files = {'oracle': task/'private/goal.xlsx', 'nop': task/'public/input.xlsx'}
            for name in ('equivalent', 'missed_root', 'extra_change'):
                book = openpyxl.load_workbook(source, keep_links=False)
                try:
                    if name == 'equivalent': book[first[0]][first[1]] = '=' + str(first[2]) + '+0'
                    elif name == 'missed_root':
                        # A known observable changed root, rather than an edit
                        # that may be dormant at the first chronological date.
                        book[first[0]][first[1]] = None
                    else:
                        sheet = book.worksheets[0]; view.require(isinstance(sheet['A1'].value, str), 'The protected source title is missing')
                        sheet['A1'] = sheet['A1'].value + ' changed'
                    path = output / (name+'.raw.xlsx'); book.save(path)
                finally:
                    book.close()
                control_files[name] = recalc(path, output/(name+'.xlsx'), 'actual_control_'+name)
            for name, path in control_files.items():
                report = compare_files(task/'public/input.xlsx', task/'private/goal.xlsx', path)
                reports[name] = helper.write_new(output/(name+'_comparison.json'), report)
                view.require(report['reward'] == CONTROL_REWARDS[name], 'A local control failed: '+name)
            controls = {'rewards': CONTROL_REWARDS, 'reports': reports,
                'workbooks': {name: view.reference(p) for name, p in control_files.items()},
                'actual_LO_calls': len(calls), 'actual_Harbor_jobs': 0}
            helper.write_new(output/'local_controls.json', controls)
            view.require(recipes() == frozen['recipe'] and admission.validate_source(frozen['source_manifest']) == proof,
                'The complete source or development recipe changed during construction')
            plan['declared_slot_count'] = delta['expected_change_count']; plan['plan_sha256'] = view.canonical(plan)
            helper.write_new(output/'private_plan.json', plan)
            helper.write_new(output/'individual_family_effects.json', effects)
            manifest = freeze_snapshot(output, task, plan, frozen, controls, delta, calls, profile)
            status = 'development_snapshot_verified_quality_pending'
            helper.write_new(output/'terminal.json', {'status': status, 'finished_at': utcnow(), 'manifest': manifest,
                'elapsed_seconds': time.monotonic()-clock, 'model_calls': 0, 'qualified': False})
            return manifest
    except BaseException as error:
        helper.write_new(output/'failure.json', {'status': 'failed', 'finished_at': utcnow(),
            'error_type': type(error).__name__, 'error': str(error), 'traceback': traceback.format_exc(),
            'engine_calls': calls, 'model_calls': 0, 'qualified': False, 'all_partial_artifacts_preserved': True})
        raise
    finally:
        try:
            if audit:
                audit.update_run(status=status, producer_active=False, finished_at=utcnow()); audit.export()
        finally:
            if server: server.stop()
            if audit: audit.db.close()
            lease.release()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', type=Path); parser.add_argument('--output', type=Path)
    parser.add_argument('--prepared', type=Path); parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0); args = parser.parse_args(argv)
    if args.prepared:
        view.require(args.source_manifest is None and args.output is None, 'Prepared execution retains its original options')
        output = args.prepared
    else:
        view.require(args.source_manifest is not None and args.output is not None, 'A verified source and fresh output are required')
        output = args.output; print(json.dumps(prepare(args.source_manifest, output)), flush=True)
    if args.run: print(json.dumps(execute_prepared(output, port=args.port)), flush=True)


if __name__ == '__main__':
    main()

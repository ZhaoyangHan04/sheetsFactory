#!/usr/bin/env python3
"""Complete four unspent R2-01 controls in an append-only namespace."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter
from openpyxl.worksheet._reader import WorkSheetParser
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard.server import DashboardServer
from sheets_factory.evaluation import streaming_verifier as grader
from sheets_factory.evaluation.thread_capped_harbor_export import export_resource_harbor, inspect_resource_export
from sheets_factory.workbook.linear_capital_portfolio.formula_identity import formula_signature
from sheets_factory.workbook.thread_capped_resource_engine import ThreadCappedResourceLibreOfficeEngine

PROFILE = ROOT / 'config/runtime_profiles/ringfenced_pair_source_v1.yaml'
PROFILE_SHA = '20fc02fec3aaf4918ece50d18ef9e315ffee9fccce088863f044ebac301a026a'
SOURCE_SHA = 'b501a956b3c7b327665609fecbc6790c1164a68c0c7b838cecf3bbd442af5d0c'
PREPARATION_SHA = '2b3aff6d2d76da0fa3b144242beed8943c8d4690b1de0adbd2fa55a9810c2401'
CERTIFICATE_SHA = 'a2770c3bf4cccd9491b1f69cf144994d7f775e99c6de79f81a586237a8d4bc46'
ORIGINAL = ROOT / 'outputs/research/ringfenced_pair_R2_01_task8_revision2_conditional_20261101T030000Z/prepared'
SPENT = ('FM_input1', 'FM_input2', 'DBG_input1', 'DBG_input2')
REMAINING = ('equivalent', 'FM_missed_root', 'DBG_missed_root', 'extra_change')
MODES = ('financial_modeling', 'debugging')
BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard', 'tool_budget_seconds': 1800, 'elapsed_guard_seconds': 14400}
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def ref(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file(), 'Use a real nonsymlink evidence file')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            digest.update(block)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def read(value):
    if not isinstance(value, dict):
        value = ref(value)
    require(ref(value['path']) == value, 'An immutable evidence reference changed')
    return json.loads(Path(value['path']).read_text())


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write('\n')
    return ref(path)


def resource_check(record, *, source=None, output=None):
    """Check actual receipts, rather than resource requests alone."""
    actual = read(record)
    require(actual.get('status') == 'completed' and actual.get('actual_resources_verified') is True
            and actual.get('thread_cap_verified') is True, 'The native call lacks completed actual resource evidence')
    require(actual['requested_resources'] == {'cpus': 2, 'memory_bytes': 34359738368, 'pids_limit': 256}
            and actual['actual_resources'] == {'cpus_nanoseconds': 2000000000, 'memory_bytes': 34359738368, 'pids_limit': 256},
            'Actual native resources differ from the original contract')
    cid = actual['container_id']; require(re.fullmatch('[0-9a-f]{64}', cid), 'Require a complete owned container ID')
    require(actual['profile'] == ref(PROFILE) and actual['image_id'] == read_profile_image(), 'Native profile or image changed')
    command = actual['create_command']
    require(command[:2] == ['docker', 'create'] and command.count(actual['image_id']) == 1
            and '--env' in command and command[command.index('--env') + 1] == 'MAX_CONCURRENCY=2', 'Native creation is not bound to the capped image')
    require(datetime.fromisoformat(actual['started_at']) <= datetime.fromisoformat(actual['thread_cap_before']['inspected_at'])
            <= datetime.fromisoformat(actual['thread_cap_after']['inspected_at']) <= datetime.fromisoformat(actual['finished_at']),
            'Actual resource observations have inconsistent times')
    for phase in ('before', 'after'):
        event = actual['thread_cap_' + phase]
        require(event['container_id'] == cid and event['variable'] == 'MAX_CONCURRENCY'
                and event['values'] == ['MAX_CONCURRENCY=2'], 'A native worker-cap observation changed')
    require(actual['thread_cap_after']['exit_code_observed'] == '0', 'The native calculation did not exit normally')
    if source is not None:
        require(actual['source'] == source, 'A native call belongs to another input')
    if output is not None:
        require(actual['output'] == output, 'A native call belongs to another output')
    return {'receipt': record, 'container_id': cid, 'passed': True}


def read_profile_image():
    import yaml
    require(ref(PROFILE)['sha256'] == PROFILE_SHA, 'The original R2-01 resource profile changed')
    return yaml.safe_load(PROFILE.read_text())['image']['id']


def preflight(original=ORIGINAL):
    """Read the original frozen lineage; never rerun source or its four inputs."""
    original = Path(original).absolute()
    require(original == ORIGINAL and ref(original/'preparation.json')['sha256'] == PREPARATION_SHA,
            'This finite continuation accepts only the original R2-01 preparation')
    f = read(original/'preparation.json'); started = read(original/'started.json')
    require(not Path('/proc') .joinpath(str(started['pid'])).exists(), 'The original owner is still alive')
    require(not any((original/(role + '_started.json')).exists() for role in REMAINING)
            and not (original/'terminal.json').exists(), 'An unspent remaining stage or terminal already exists')
    require(f['stage_order'] == list(SPENT + REMAINING) and f['required_actual_LO_calls'] == 8
            and f['financial_target_count'] == 3044678 and f['source_formula_count'] == 2494958
            and f['provisional_choice_count'] == 720 and f['pair_id'] == 'R2-01', 'The original complete task scope changed')
    require(f['runtime_profile'] == ref(PROFILE), 'Use the actual original large-pair profile')
    for value in f['recipe'].values():
        if isinstance(value, dict):
            read_ref = ref(value['path']); require(read_ref == value, 'A frozen implementation recipe changed')
    for key in ('source_manifest', 'source_preparation', 'genuine_goal', 'whole_views_contract', 'definition', 'expected'):
        require(ref(f[key]['path']) == f[key], 'A frozen source or task binding changed: ' + key)
    source = read(f['source_manifest']); sf = read(f['source_preparation']); certificate = read(sf['certificate'])
    require(f['source_manifest']['sha256'] == SOURCE_SHA and sf['certificate']['sha256'] == CERTIFICATE_SHA
            and source['passed'] is True and source['failure'] is None and source['source'] == f['genuine_goal']
            and source['actual_calls_started'] == source['actual_calls_completed'] == 3
            and certificate['mathematical_composition_certified'] is True
            and certificate['cold_local_reference_count'] == certificate['cold_original_source_count'] == 2,
            'The already completed source or isolated-mandate optimum certificate changed')
    for donor in certificate['donors']:
        local = read(donor['reference'])
        require(local['passed'] is True and local['unique_best'] is True and local['gap_pence'] > 0,
                'A local best/runner reference is no longer available')
    for record in (sf['public_contract'], sf['certificate']):
        require(ref(record['path']) == record, 'The source business contract changed')
    calls = []; results = {}; observations = []
    for index, role in enumerate(SPENT, 1):
        terminal = ref(original/(role + '_terminal.json')); call = read(terminal)
        wanted = results[role[:-1] + '1'] if role.endswith('2') else f['planned_inputs'][role[:-1]]
        require(call['index'] == index and call['role'] == role and call['completed'] is True
                and call['input'] == wanted and ref(call['output']['path']) == call['output'], 'A spent actual input call changed')
        observations.append(resource_check(call['actual_resource_evidence']['terminal'], source=wanted, output=call['output']))
        calls.append({**call, 'terminal_receipt': terminal, 'inherited_completed_call': True}); results[role] = call['output']
    for role in REMAINING:
        require(ref(f['planned_inputs'][role]['path']) == f['planned_inputs'][role], 'A predeclared remaining control changed')
    for record in f['instruction_bytes'].values():
        require(ref(record['path']) == record, 'An original task instruction changed')
    return f, calls, results, {'source': f['source_manifest'], 'certificate': sf['certificate'],
        'public_contract': sf['public_contract'], 'original_preparation': ref(original/'preparation.json'),
        'original_started': ref(original/'started.json'), 'inherited_resource_observations': observations,
        'remaining_roles': list(REMAINING), 'additional_LO_calls_authorized': 4,
        'new_source_or_solver_or_model_calls': 0, 'source_cold_validation_repeated': False}


class DualParser(WorkSheetParser):
    """Decode formula definitions and native cached values in one XML pass."""
    def parse_cell(self, element):
        cell = super().parse_cell(element)
        formula = element.find(NS + 'f')
        cell['formula'] = None if formula is None else self.parse_formula(element)
        return cell


def sheet_cells(sheet):
    result = {}
    with sheet._get_source() as stream:
        parser = DualParser(stream, sheet._shared_strings, data_only=True, epoch=sheet.parent.epoch,
                            date_formats=sheet.parent._date_formats, timedelta_formats=sheet.parent._timedelta_formats)
        previous = (0, 0)
        for _, row in parser.parse():
            cells = {(c['row'], c['column']): c for c in row}
            for coordinate, cell in sorted(cells.items()):
                require(coordinate > previous, 'Native XML is not in canonical cell order'); previous = coordinate
                if cell['value'] is not None or cell['formula'] is not None:
                    result[coordinate] = cell
        merges = sorted((v.min_row, v.min_col, v.max_row, v.max_col) for v in parser.merged_cells.mergeCell) if parser.merged_cells else []
    for bounds in merges:
        top, left, bottom, right = bounds
        for point in list(result):
            if top <= point[0] <= bottom and left <= point[1] <= right and point != (top, left):
                del result[point]
    return result, merges


def same_formula(left, right):
    return left == right or (isinstance(left, str) and isinstance(right, str) and formula_signature(left) == formula_signature(right))


def check_definition(before, after, edit):
    if edit is not None:
        kind, value = edit
        if kind == 'blank':
            require(after is None, 'A required FM field retained a value or formula')
        elif kind == 'formula':
            require(after is not None and same_formula(after['formula'], value), 'A predeclared debugging fault changed')
        else:
            require(after is not None and after['formula'] is None and type(after['value']) is int and after['value'] == value,
                    'A predeclared provisional choice changed')
    elif before is not None and before['formula'] is not None:
        require(after is not None and same_formula(before['formula'], after['formula']), 'A healthy formula changed outside the declared edits')
    else:
        primitive = lambda x: None if x is None else (x['data_type'], x['value'])
        require(primitive(before) == primitive(after), 'A supplied fact, policy, label or context changed')


def compare_values(baseline, expected, actual):
    needed, changed = baseline != expected, baseline != actual
    return needed, changed, needed and not changed, changed and not needed, needed and actual != expected


def audit_complete(f, results, output, audit):
    """Read each native workbook once; compare the full physical union."""
    plan = read(f['definition'])
    fm_mask = {name: set(values) for name, values in plan['FM_mask'].items()}
    dbg_edits = {}
    for kind, rows in (('formula', plan['DBG_faults']), ('number', plan['DBG_choices'])):
        for row in rows:
            dbg_edits.setdefault(row['sheet'], {})[row['cell']] = (kind, row['after'])
    paths = {'goal': f['genuine_goal'], **results}
    paths = {key: value for key, value in paths.items() if key in ('goal',) + SPENT + REMAINING}
    differences = {mode: [] for mode in MODES}; counts = {mode: {role: [0, 0, 0, 0, 0] for role in ('oracle', 'nop', 'equivalent', 'missed_root', 'extra_change')} for mode in MODES}
    unions = 0; formulas = 0; protected = 0; errors = 0
    with ExitStack() as stack:
        books = {key: load_workbook(value['path'], read_only=True, data_only=True, keep_links=False) for key, value in paths.items()}
        for book in books.values():
            stack.callback(book.close)
        names = plan['sheetnames']; goal = books['goal']
        require(all(book.sheetnames == names and book.epoch == goal.epoch and book.calculation.iterate is not True for book in books.values()),
                'The workbook structure, epoch or noncircular policy changed')
        indexes = {key: {sheet.title: sheet for sheet in book.worksheets} for key, book in books.items()}
        for index, name in enumerate(names, 1):
            current = {}; merges = {}
            for key in books:
                current[key], merges[key] = sheet_cells(indexes[key][name])
            require(all(value == merges['goal'] for value in merges.values()), 'The worksheet merged layout changed')
            union = set().union(*(set(value) for value in current.values()))
            for point in sorted(union):
                address = get_column_letter(point[1]) + str(point[0]); label = name + '!' + address
                healthy = current['goal'].get(point)
                reference = healthy if healthy is not None else current['FM_input2'].get(point)
                reference_value = reference['value'] if reference else None
                normalized = {key: grader._normalized_cell(value.get(point), reference_value, books[key].epoch) for key, value in current.items()}
                errors += sum(cell is not None and cell['data_type'] == 'e' for cell in (value.get(point) for value in current.values()))
                require(errors == 0, 'A native input or control contains an error')
                formulas += int(healthy is not None and healthy['formula'] is not None)
                fm_edit = ('blank', None) if address in fm_mask.get(name, set()) else None
                dbg_edit = dbg_edits.get(name, {}).get(address)
                for key in ('FM_input1', 'FM_input2'):
                    check_definition(healthy, current[key].get(point), fm_edit)
                for key in ('DBG_input1', 'DBG_input2'):
                    check_definition(healthy, current[key].get(point), dbg_edit)
                protected += int(healthy is not None and healthy['formula'] is None and fm_edit is dbg_edit is None)
                require(normalized['FM_input1'] == normalized['FM_input2'] and normalized['DBG_input1'] == normalized['DBG_input2'],
                        'The two actual native inputs do not have stable typed values')
                for mode, prefix in zip(MODES, ('FM', 'DBG')):
                    baseline, expected = normalized[prefix + '_input2'], normalized['goal']
                    if baseline != expected:
                        differences[mode].append(label)
                    outputs = {'oracle': expected, 'nop': baseline, 'equivalent': normalized['equivalent'],
                               'missed_root': normalized[prefix + '_missed_root'], 'extra_change': normalized['extra_change']}
                    for role, actual in outputs.items():
                        state = compare_values(baseline, expected, actual)
                        counts[mode][role] = [left + int(right) for left, right in zip(counts[mode][role], state)]
            unions += len(union)
            if index % 20 == 0 or index == len(names):
                audit.update_run(stage='full_union_audit', sheets_checked=index, physical_union_cells_checked=unions); audit.export()
    require(formulas == f['source_formula_count'], 'The complete healthy formula inventory changed')
    require(len(differences['financial_modeling']) == f['financial_target_count'], 'FM does not cover every declared financial target')
    modes = {}
    for mode in MODES:
        controls = {}
        for role, row in counts[mode].items():
            e, a, missing, extra, wrong = row
            controls[role] = {'reward': int(not (missing or extra or wrong)), 'expected_change_count': e, 'actual_change_count': a,
                              'missing_change_count': missing, 'extra_change_count': extra, 'wrong_value_count': wrong}
        require({key: value['reward'] for key, value in controls.items()} == {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0},
                'The actual full-value five-control pattern failed')
        modes[mode] = {'passed': True, 'native_error_count': errors, 'given_literals_unchanged': True, 'sheet_structure_unchanged': True,
            'complete_primary_difference_count': len(differences[mode]), 'complete_primary_difference': differences[mode],
            'actual_programmatic_controls': controls, 'native_two_input_typed_stability': True,
            'full_source_formula_count': formulas, 'full_physical_union_count': unions, 'protected_literal_count': protected,
            'source': f['source_manifest'], 'actual_Harbor_controls_pending': True}
    return modes


def owned_cleanup(observations):
    daemon = subprocess.run(['docker', 'info', '--format', '{{.ID}}'], capture_output=True, text=True, check=True).stdout.strip()
    values = []
    for item in observations:
        cid = item['container_id']
        probe = subprocess.run(['docker', 'inspect', cid, '--format', '{{.Id}}'], capture_output=True, text=True)
        absent = probe.returncode != 0 and ('no such object' in probe.stderr.lower() or 'no such container' in probe.stderr.lower())
        values.append({'container_id': cid, 'absent': absent, 'receipt': item['receipt'], 'probe_returncode': probe.returncode})
    require(daemon and all(value['absent'] for value in values), 'Owned native cleanup is incomplete or unknown')
    return {'passed': True, 'daemon_id': daemon, 'all_owned_containers_absent': True, 'owned': values}


def run(output, *, original=ORIGINAL, port=0):
    output = Path(output).absolute(); require(output == output.resolve() and not output.exists(), 'Use a fresh append-only continuation directory')
    output.mkdir(parents=True)
    audit = AuditStore(output/'audit', {'id': output.name, 'name': 'Complete four unspent ringfenced controls', 'status': 'running', 'target_count': 2})
    server = DashboardServer(audit.snapshot, audit.events, port=port); url = server.start(); started = time.monotonic()
    print(json.dumps({'dashboard_url': url, 'pid': __import__('os').getpid()}), flush=True)
    audit.update_run(dashboard_url=url)
    engine = None; observations = []; result = None
    try:
        f, inherited, results, admission = preflight(original)
        daemon_before = subprocess.run(['docker', 'info', '--format', '{{.ID}}'], capture_output=True, text=True, check=True).stdout.strip()
        require(bool(daemon_before), 'The actual Docker daemon identity is unavailable')
        freeze = write(output/'prospective.json', {'kind': 'append_only_R2_01_remaining_four_native_controls_v1', 'version': 1,
            'created_at': datetime.now(timezone.utc).isoformat(), 'admission': admission, 'implementation': ref(__file__),
            'remaining_roles': list(REMAINING), 'old_records_or_calls_modified': False, 'source_or_inputs_repeated': False,
            'new_native_calls_maximum': 4, 'new_model_solver_source_calls': 0, 'retry': 0, 'daemon_before_id': daemon_before})
        observations = list(admission['inherited_resource_observations'])
        engine = ThreadCappedResourceLibreOfficeEngine(ROOT, PROFILE, role='source', receipt_directory=output/'native_receipts')
        new_calls = []
        for index, role in enumerate(REMAINING, 5):
            audit.update_run(stage='actual_' + role, actual_LO_calls_completed=len(new_calls)); audit.export()
            before = f['planned_inputs'][role]; tick = time.monotonic()
            actual = engine.recalculate(before['path'], output/(role + '.xlsx')); after = ref(actual)
            receipt = engine.metadata()['actual_resource_receipts'][-1]
            observations.append(resource_check(receipt, source=before, output=after))
            call = {'index': index, 'role': role, 'input': before, 'output': after, 'completed': True,
                    'elapsed_seconds': time.monotonic()-tick, 'native_resource_receipt': receipt}
            write(output/(role + '_completed.json'), call); new_calls.append(call); results[role] = after
            print(json.dumps({'actual_call_completed': role, 'new_completed_calls': len(new_calls)}), flush=True)
        audit.update_run(stage='full_union_audit'); audit.export()
        modes = audit_complete(f, results, output, audit)
        plan = read(f['definition'])
        plan_freeze = write(output/'plans_frozen.json', {'kind': 'original_ringfenced_pair_material_plan_rebound', 'version': 1,
            'original_preparation': admission['original_preparation'], 'prospective': freeze, 'source': f['source_manifest'],
            'execution_budget': BUDGET, 'runtime_profile': ref(PROFILE),
            'plans': [{'mode': mode, 'plan': {'variant_id': 'R2-01-' + ('FM' if mode == MODES[0] else 'DBG')}} for mode in MODES]})
        tasks = []
        for mode, prefix in zip(MODES, ('FM', 'DBG')):
            folder = output/'private'/('R2-01-' + prefix); material = folder/'materialized'
            (material/'public').mkdir(parents=True); (material/'private').mkdir()
            native = results[prefix + '_input2']; goal = f['genuine_goal']; instruction = f['instruction_bytes'][mode]
            for source, destination in ((native, material/'public/input.xlsx'), (goal, material/'private/goal.xlsx'),
                                        (instruction, material/'public/instruction.md')):
                shutil.copyfile(source['path'], destination)
            signature = hashlib.sha256(json.dumps({'mode': mode, 'input': native['sha256'], 'goal': goal['sha256'],
                'instruction': instruction['sha256']}, sort_keys=True).encode()).hexdigest()
            task_id = ('fm-' if mode == MODES[0] else 'dbg-') + 'ringfenced-r2-01-' + signature[:20]
            engineering = write(folder/'individual_engineering.json', {**modes[mode], 'prospective': freeze,
                'inherited_actual_inputs': [call['terminal_receipt'] for call in inherited if call['role'].startswith(prefix)],
                'inherited_complete_source': admission['source'], 'unique_optimum_certificate': admission['certificate'],
                'new_native_control_calls': [ref(output/(role + '_completed.json')) for role in REMAINING]})
            cap = folder/'worker_cap.json'
            directory = export_resource_harbor(material, output/'SpreadsheetEval'/task_id,
                {'task_id': task_id, 'mode': mode, 'revision': 0, 'revision_hash': signature,
                 'source_kind': 'unchanged_ringfenced_pair_finite_task8_continuation', 'variant_id': 'R2-01-' + prefix,
                 'difficulty_status': 'development_pending'}, ROOT, runtime_profile=PROFILE, audit_path=cap)
            task = {'task_id': task_id, 'mode': mode, 'revision': 0, 'revision_hash': signature, 'source_id': goal['sha256'],
                'task_directory': str(directory), 'variant_id': 'R2-01-' + prefix, 'execution_budget': BUDGET,
                'harbor_export_binding': inspect_resource_export(directory, audit_path=cap), 'worker_cap_audit': ref(cap),
                'individual_engineering': engineering, 'plan_freeze': plan_freeze}
            tasks.append(task); write(folder/'task_record.json', task)
        cleanup_value = owned_cleanup(observations)
        require(cleanup_value['daemon_id'] == daemon_before, 'The cleanup observation belongs to another Docker daemon')
        cleanup = write(output/'owned_resources_absent.json', {**cleanup_value, 'same_daemon_before_after': True})
        f2, calls2, _, _ = preflight(original)
        require(f2 == f and inherited == calls2, 'The original source, preparation or spent inputs changed')
        result = write(output/'engineered_batch.json', {'kind': 'individually_engineered_business_revision_batch', 'version': 1,
            'count': len(tasks), 'tasks': tasks, 'selected_task_ids': [task['task_id'] for task in tasks], 'source': f['source_manifest'],
            'source_count': 1, 'qualified': False, 'business_difficulty_evidence_pending': True,
            'actual_LO_calls_completed': 4, 'inherited_source_calls': 3, 'inherited_input_calls': 4,
            'remaining_calls_completed': new_calls, 'prospective': freeze, 'owned_resource_cleanup': cleanup,
            'old_records_or_scores_modified': False, 'new_model_solver_Harbor_calls': 0, 'duration_seconds': time.monotonic()-started})
        audit.update_run(status='completed', stage='engineering_complete', actual_LO_calls_completed=4)
        return result
    except BaseException as error:
        write(output/'failure.json', {'type': type(error).__name__, 'reason': str(error), 'qualified': False, 'failure_is_not_model_zero': True})
        audit.update_run(status='failed', stage='engineering_failed', error_type=type(error).__name__)
        raise
    finally:
        if result is None and observations:
            try:
                if engine is not None:
                    known = {row['receipt']['path'] for row in observations}
                    observations += [resource_check(value) for value in engine.metadata()['actual_resource_receipts'] if value['path'] not in known]
                write(output/'failure_owned_resources_absent.json', owned_cleanup(observations))
            except Exception as error:
                write(output/'failure_cleanup_unknown.json', {'type': type(error).__name__, 'reason': str(error)})
        audit.export(); server.stop(); audit.db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--original-prepared', type=Path, default=ORIGINAL)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.run:
        require(args.output is not None, 'A fresh continuation output is required')
        print(json.dumps(run(args.output, original=args.original_prepared, port=args.port)))
    else:
        _, _, _, value = preflight(args.original_prepared)
        if args.output:
            print(json.dumps(write(args.output, value)))
        else:
            print(json.dumps(value))


if __name__ == '__main__':
    main()

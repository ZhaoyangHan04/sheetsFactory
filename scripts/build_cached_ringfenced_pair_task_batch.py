#!/usr/bin/env python3
"""Create the two fixed whole-pair tasks with one real input call per mode."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter
from sheets_factory.evaluation import ringfenced_resource_harbor as export
from sheets_factory.workbook.linear_capital_ringfenced_pairs import task_views

SOURCE_BUILDER = ROOT/'scripts/build_cached_ringfenced_pair_source.py'
SOURCE_BUILDER_SHA = '13b9ba6663a611bb866e98351a118e314658f2d6eec7db4d6a628e9367653958'
SUPPORT = ROOT/'scripts/resume_ringfenced_pair_task8_remaining_revision2.py'
SUPPORT_SHA = '8a5c88d53f80dfdbff9936f50c40257cbec71759d2747871cf1e852943c6f145'
FIRST_FIVE = ROOT/'outputs/research/ringfenced_first5_retained10_design_20261101T074000Z/freeze.json'
FIRST_FIVE_SHA = 'fa8ec5498c45d561570e4c1ba41f3fa9687b969386af74b5cfb1fe3a45326312'
ORIGINAL_PREPARATION = ROOT/'outputs/research/ringfenced_pair_R2_01_task8_revision2_conditional_20261101T030000Z/prepared/preparation.json'
ORIGINAL_PREPARATION_SHA = '2b3aff6d2d76da0fa3b144242beed8943c8d4690b1de0adbd2fa55a9810c2401'
PAIRS = ('R2-02', 'R2-03', 'R2-04', 'R2-05')
MODES = task_views.MODES
COUNTS = dict(task_views.COUNTS)
ref, read, require = task_views.c.reference, task_views.c.read, task_views.c.require


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    return task_views.c.write(path, value)


def load(path, digest, name):
    require(ref(path)['sha256'] == digest, 'A frozen task builder dependency changed')
    loader = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(loader); loader.loader.exec_module(value)
    return value


helpers = load(SUPPORT, SUPPORT_SHA, '_cached_pair_task_helpers')
dual = helpers.v1
PROFILE = dual.PROFILE
BUDGET = dual.BUDGET


def source_provider():
    return load(SOURCE_BUILDER, SOURCE_BUILDER_SHA, '_cached_pair_genuine_completed_source')


def recipes():
    provider = source_provider()
    export.load_runtime_profile(PROFILE)
    return {'builder': ref(__file__), 'source_builder': ref(SOURCE_BUILDER), 'helpers': ref(SUPPORT),
        'original_helpers': ref(dual.__file__), 'source_recipe': provider.recipes(),
        'task_view_recipe': task_views.recipes(), 'export_recipe': export.recipes(), 'profile': ref(PROFILE)}


def _reference_guard(record):
    require(ref(record['path']) == record, 'An immutable material or proof changed')


def admit(source):
    """Consume the complete cached source proof once, without finance replays."""
    require(ref(FIRST_FIVE)['sha256'] == FIRST_FIVE_SHA and ref(ORIGINAL_PREPARATION)['sha256'] == ORIGINAL_PREPARATION_SHA,
        'The predeclared cohort or original whole-view contract changed')
    design = read(FIRST_FIVE); original = read(ORIGINAL_PREPARATION)
    provider = source_provider(); terminal = provider.validate_completed(source)
    require(terminal['kind'] == 'completed_cached_ringfenced_pair_source_v1' and terminal['version'] == 1
        and terminal['pair_id'] in PAIRS and terminal['passed'] is True and terminal['failure'] is None
        and terminal['actual_calls_started'] == terminal['actual_calls_completed'] == terminal['LO_calls'] == 3,
        'Require the complete genuine three-call cached source for a new fixed pair')
    sf = read(terminal['preparation']); certificate = read(sf['certificate'])
    pool_ref = original['whole_views_contract']; pool = read(pool_ref)
    require(pool['kind'] == task_views.POOL_KIND and pool['version'] == 1 and pool['counts'] == COUNTS
        and pool['mode_order'] == list(MODES) and pool['prospective'] == design['original_whole_pair_pool']
        and certificate['prospective'] == pool['prospective'] and certificate['pair_id'] == terminal['pair_id']
        and sf['geometry'] == {key: COUNTS[key] for key in ('formulas', 'nonempty', 'targets')},
        'The source, fixed full task scope and predeclared whole pool disagree')
    selected = next(row for row in design['new_pairs'] if row['id'] == terminal['pair_id'])
    public = read(sf['public_contract'])
    require([row['local_profile_id'] for row in public['mandates']] == selected['profiles']
        and certificate['contract'] == sf['public_contract'], 'The selected two original mandates changed')
    lookup = {row['profile_id']: row for row in pool['donors']}; rows = []; leaves = []
    for identity in selected['profiles']:
        bound = lookup[identity]; row = {'control_primary': bound['control_primary']}
        for mode in MODES:
            record = bound['views'][mode]['plan']; row[mode] = read(record); leaves.append(record)
            require(row[mode]['mode'] == mode, 'A retained donor plan has the wrong mode')
        control = read(bound['control_evidence']); leaves.append(bound['control_evidence'])
        require(control['rewards'] == {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
            and control['observable_primary'] == bound['control_primary'], 'The retained deterministic control witness changed')
        rows.append(row)
    composition = read(sf['local_composition']); report = read(sf['report_plan'])
    require([r['id'] for r in composition['donors']] == ['M01', 'M02']
        and [r['workbook'] for r in composition['donors']] == [r['workbook'] for r in certificate['donors']],
        'The complete local donor maps changed')
    compiled = task_views.compile_views(rows, composition, report)
    plan = {'kind': task_views.PLAN_KIND, 'version': 1, 'pair_id': terminal['pair_id'], **compiled,
        'whole_views_contract': pool_ref, 'source_manifest': source, 'source_preparation': terminal['preparation'],
        'genuine_goal': terminal['source'], 'source_formula_count': COUNTS['formulas'],
        'provided_cells_and_all_context_preserved': True, 'all_formula_caches_must_be_absent': True,
        'mode_order': list(MODES), 'qualified': False, 'task_qualification_inherited': False}
    instructions = original['instruction_bytes']
    for mode, expected in zip(MODES, (task_views.FM_BRIEF, task_views.DBG_BRIEF)):
        _reference_guard(instructions[mode])
        require(Path(instructions[mode]['path']).read_bytes() == expected.encode(), 'An original business brief changed')
    guards = [source, ref(FIRST_FIVE), ref(ORIGINAL_PREPARATION), terminal['preparation'], sf['certificate'],
        pool_ref, sf['local_composition'], sf['report_plan'], sf['public_contract'], terminal['source'], *leaves,
        *instructions.values(), *sf['recipe']]
    guards += list(terminal['records'].values())
    for call in terminal['actual_calls']:
        guards += [call['input'], call['output'], call['actual_resource_evidence']['terminal']]
    # These artifacts are consumed as evidence, not as a recursive inventory of
    # active historical Python providers. The completed source validator checks
    # its actual native/audit chain and original A/B reference proof.
    return terminal, sf, plan, instructions, guards


def _sheet_styles(book, cell):
    if cell is None:
        return None
    style = book._cell_styles[cell.get('style_id', 0)]
    values = list(style)
    values[3] = book._number_formats[style.numFmtId-164] if style.numFmtId >= 164 else style.numFmtId
    return values


def audit_inputs(plan, actual, audit):
    """One full union pass over goal and the two actual native inputs."""
    masks = {name: set(points) for name, points in plan['FM_mask'].items()}
    edits = task_views.actions(plan, 'debugging')
    differences = {mode: [] for mode in MODES}; seen = {mode: set() for mode in MODES}
    formulas = union_count = protected = 0
    paths = {'goal': plan['genuine_goal'], **actual}
    with ExitStack() as stack:
        books = {key: load_workbook(record['path'], read_only=True, data_only=True, keep_links=False) for key, record in paths.items()}
        for book in books.values(): stack.callback(book.close)
        goal = books['goal']; names = plan['sheetnames']
        require(all(book.sheetnames == names and book.epoch == goal.epoch and book.calculation.iterate is not True
            for book in books.values()), 'Workbook structure, epoch or noncircular policy changed')
        indexes = {key: {sheet.title: sheet for sheet in book.worksheets} for key, book in books.items()}
        for index, name in enumerate(names, 1):
            current = {}; merges = {}
            for key in books: current[key], merges[key] = dual.sheet_cells(indexes[key][name])
            require(all(value == merges['goal'] for value in merges.values()), 'The merged report layout changed')
            for point in sorted(set().union(*(set(value) for value in current.values()))):
                union_count += 1; address = get_column_letter(point[1])+str(point[0]); label = name+'!'+address
                healthy = current['goal'].get(point); wanted = healthy['value'] if healthy else None
                formulas += int(healthy is not None and healthy['formula'] is not None)
                fm_edit = ('blank', None) if address in masks.get(name, set()) else None
                dbg_edit = edits.get(name, {}).get(address)
                require(all(cell is None or cell['data_type'] != 'e' for cell in
                    (values.get(point) for values in current.values())), 'An actual native input or goal contains an error')
                for mode, edit in zip(MODES, (fm_edit, dbg_edit)):
                    after = current[mode].get(point)
                    dual.check_definition(healthy, after, edit)
                    if edit is not None: seen[mode].add((name, address))
                    require(after is None or healthy is None or _sheet_styles(goal, healthy) == _sheet_styles(books[mode], after),
                        'A supplied or financial cell style changed')
                    before_typed = dual.grader._normalized_cell(healthy, wanted, goal.epoch)
                    after_typed = dual.grader._normalized_cell(after, wanted, books[mode].epoch)
                    if before_typed != after_typed:
                        require(address in masks.get(name, set()), 'A primary difference lies outside the complete financial targets')
                        differences[mode].append(label)
                protected += int(healthy is not None and healthy['formula'] is None and fm_edit is dbg_edit is None)
            audit.update_run(stage='full_union_audit', worksheets_completed=index, worksheets_total=len(names),
                full_union_cells_checked=union_count, formulas_checked=formulas); audit.export()
    require(formulas == COUNTS['formulas'] and union_count == COUNTS['nonempty'], 'The full source cell or formula census changed')
    require(len(seen[MODES[0]]) == plan['FM_target_count'] and len(seen[MODES[1]]) == plan['DBG_formula_root_count']+plan['DBG_choice_count'],
        'A declared full mask or fault/choice edit was not checked')
    require(len(differences[MODES[0]]) == COUNTS['targets'] and differences[MODES[1]], 'The actual complete FM mask or nonempty DBG difference failed')
    return {mode: {'passed': True, 'native_error_count': 0, 'given_literals_unchanged': True,
        'sheet_structure_unchanged': True, 'cell_styles_unchanged': True, 'complete_primary_difference_count': len(points),
        'complete_primary_difference': points, 'full_source_formula_count': formulas, 'full_physical_union_count': union_count,
        'protected_literal_count': protected, 'full_D_subset_complete_financial_targets': True,
        'actual_Harbor_controls_pending': True, 'normal_all12_pending': True,
        'synthetic_controls_reexecuted': False, 'native_two_input_typed_stability': None}
        for mode, points in differences.items()}


def run(source, output, *, port=0):
    output = Path(output).absolute()
    require(output == output.resolve() and not output.exists(), 'Use a fresh complete fixed-pair task batch directory')
    output.mkdir(parents=True)
    audit = dual.AuditStore(output/'audit', {'id': output.name, 'name': 'Two whole ringfenced tasks', 'status': 'running', 'target_count': 2})
    server = dual.DashboardServer(audit.snapshot, audit.events, port=port); url = server.start(); tick = time.monotonic()
    print(json.dumps({'dashboard_url': url}), flush=True); audit.update_run(dashboard_url=url, stage='genuine_source_admission')
    calls = []; observations = []; engine = None; stop = threading.Event(); started_calls = 0
    def pulse():
        while not stop.wait(10): audit.update_run(duration_ms=int((time.monotonic()-tick)*1000), actual_LO_calls_completed=len(calls)); audit.export()
    thread = threading.Thread(target=pulse, daemon=True); thread.start()
    try:
        recipe = recipes(); source = ref(source) if not isinstance(source, dict) else source
        terminal, sf, plan, instructions, guards = admit(source); pair = terminal['pair_id']
        reservation = ROOT/'outputs/research/.cached_ringfenced_pair_task_batch_reservations_v1'/(pair+'.json')
        write(reservation, {'pair_id': pair, 'source': source, 'output': str(output), 'retry': 0, 'recipe': recipe})
        plan_ref = write(output/'whole_view_plan.private.json', plan)
        prospective = write(output/'plans_frozen.json', {'kind': 'predeclared_cached_ringfenced_pair_two_input_task_batch_v1', 'version': 1,
            'created_at': datetime.now(timezone.utc).isoformat(), 'source': source, 'source_preparation': terminal['preparation'],
            'first_five_design': ref(FIRST_FIVE), 'whole_views_contract': plan['whole_views_contract'], 'definition': plan_ref,
            'runtime_profile': ref(PROFILE), 'recipe': recipe, 'execution_budget': BUDGET,
            'stage_order': list(MODES), 'actual_new_input_LO_limit': 2, 'new_synthetic_control_calls': 0,
            'source_financial_forward_solver_model_Harbor_calls': 0, 'retry': 0,
            'plans': [{'mode': mode, 'plan': {'variant_id': pair+('-FM' if mode == MODES[0] else '-DBG')}} for mode in MODES]})
        planned = {}
        for mode in MODES:
            folder = output/'private'/mode; folder.mkdir(parents=True)
            changes = task_views.actions(plan, mode)
            transformed = task_views.transform(plan['genuine_goal']['path'], folder/'cold_input.xlsx', changes)
            require(transformed['edited_cells'] == (plan['FM_target_count'] if mode == MODES[0]
                else plan['DBG_formula_root_count']+plan['DBG_choice_count']), 'The complete declared input edit count changed')
            planned[mode] = transformed['output']; write(folder/'cold_transform.json', transformed)
        engine = helpers.engine_class()(ROOT, PROFILE, role='source', receipt_directory=output/'native_receipts')
        actual = {}
        for index, mode in enumerate(MODES, 1):
            audit.task(pair+'-'+mode, mode=mode, status='engineering', node='one_native_input'); audit.update_run(stage='native_'+mode)
            before = planned[mode]; started_calls += 1; call_tick = time.monotonic()
            result = ref(engine.recalculate(before['path'], output/'private'/mode/'input.native.xlsx'))
            metadata = engine.metadata(); require(len(metadata['actual_resource_receipts']) == index, 'Unexpected additional native input calls')
            receipt = metadata['actual_resource_receipts'][-1]
            observations.append(dual.resource_check(receipt, source=before, output=result))
            call = {'index': index, 'role': mode+'_input', 'input': before, 'output': result,
                'completed': True, 'elapsed_seconds': time.monotonic()-call_tick, 'native_resource_receipt': receipt}
            write(output/'private'/mode/'native_call.json', call); calls.append(call); actual[mode] = result
        modes = audit_inputs(plan, actual, audit)
        cleanup = write(output/'owned_resources_absent.json', dual.owned_cleanup(observations))
        tasks = []
        for mode, suffix in zip(MODES, ('FM', 'DBG')):
            variant = pair+'-'+suffix; folder = output/'private'/variant; material = folder/'materialized'
            (material/'public').mkdir(parents=True); (material/'private').mkdir()
            for original, destination in ((actual[mode], material/'public/input.xlsx'), (plan['genuine_goal'], material/'private/goal.xlsx'),
                (instructions[mode], material/'public/instruction.md')):
                shutil.copyfile(original['path'], destination)
                copied = ref(destination); require((copied['sha256'], copied['bytes']) == (original['sha256'], original['bytes']), 'A published material copy changed bytes')
            signature = hashlib.sha256(json.dumps({'mode': mode, 'input': actual[mode]['sha256'],
                'goal': plan['genuine_goal']['sha256'], 'instruction': instructions[mode]['sha256']}, sort_keys=True).encode()).hexdigest()
            identity = ('fm-' if mode == MODES[0] else 'dbg-')+'ringfenced-'+pair.lower()+'-'+signature[:20]
            individual = write(folder/'individual_engineering.json', {**modes[mode], 'source': source, 'source_certificate': sf['certificate'],
                'prospective': prospective, 'definition': plan_ref, 'native_call': calls[MODES.index(mode)],
                'native_call_metadata': {'actual_resource_receipts': [calls[MODES.index(mode)]['native_resource_receipt']]},
                'owned_cleanup': cleanup, 'actual_programmatic_controls': None,
                'retained_local_controls_are_design_witnesses_only': True})
            cap = folder/'worker_cap.json'
            directory = export.export_resource_harbor(material, output/'SpreadsheetEval'/identity,
                {'task_id': identity, 'mode': mode, 'revision': 0, 'revision_hash': signature, 'variant_id': variant,
                'source_kind': 'completed_cached_ringfenced_pair_source_v1', 'difficulty_status': 'development_pending'},
                ROOT, runtime_profile=PROFILE, audit_path=cap)
            task = {'task_id': identity, 'mode': mode, 'revision': 0, 'revision_hash': signature, 'source_id': plan['genuine_goal']['sha256'],
                'task_directory': str(directory), 'variant_id': variant, 'execution_budget': BUDGET,
                'harbor_export_binding': export.inspect_resource_export(directory, audit_path=cap),
                'worker_cap_audit': ref(cap), 'individual_engineering': individual, 'plan_freeze': prospective}
            tasks.append(task); write(folder/'task_record.json', task)
            audit.task(pair+'-'+mode, status='engineering_passed', node='export_complete')
        require(recipes() == recipe and len(calls) == started_calls == 2, 'The exact two-call task recipe changed')
        for record in guards+list(planned.values())+list(actual.values()): _reference_guard(record)
        result = write(output/'engineered_batch.json', {'kind': 'individually_engineered_business_revision_batch', 'version': 1,
            'count': 2, 'tasks': tasks, 'selected_task_ids': [r['task_id'] for r in tasks], 'source': source, 'source_count': 1,
            'pair_id': pair, 'qualified': False, 'business_difficulty_evidence_pending': True,
            'actual_LO_calls_completed': 2, 'inherited_source_calls': 3, 'source_recalculated': False,
            'actual_native_input_calls': calls, 'owned_resource_cleanup': cleanup, 'plan_freeze': prospective,
            'actual_Harbor_controls_pending': True, 'normal_all12_pending': True, 'synthetic_control_calls': 0,
            'new_model_solver_financial_forward_Harbor_calls': 0, 'outer_retries': 0, 'duration_seconds': time.monotonic()-tick})
        audit.update_run(status='completed', stage='engineering_complete'); return result
    except BaseException as error:
        cleanup = None
        try:
            if engine is not None:
                known = {item['receipt']['path'] for item in observations}
                for record in engine.metadata()['actual_resource_receipts']:
                    if record['path'] not in known: observations.append(dual.resource_check(record))
            if observations: cleanup = write(output/'failure_owned_cleanup.json', dual.owned_cleanup(observations))
        except Exception as cleanup_error:
            cleanup = write(output/'failure_cleanup_unknown.json', {'type': type(cleanup_error).__name__, 'reason': str(cleanup_error)})
        write(output/'failure.json', {'type': type(error).__name__, 'reason': str(error), 'completed_calls': calls,
            'actual_LO_calls_started': started_calls, 'owned_cleanup': cleanup, 'outer_retries': 0,
            'qualified': False, 'failure_is_not_model_zero': True})
        audit.update_run(status='failed', stage='engineering_failed'); raise
    finally:
        stop.set(); thread.join(timeout=1); audit.export(); server.stop(); audit.db.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True); parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=0); parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv); require(args.run, 'Actual two-input engineering requires explicit --run after recipe review')
    print(json.dumps(run(args.source, args.output, port=args.port)))


if __name__ == '__main__': main()

#!/usr/bin/env python3
"""Join one complete timing supplement without changing the original attempt."""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import FunctionType

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
QUALITY = ROOT / 'scripts/join_operating_reports_factory_final_quality.py'
FINALIZER = ROOT / 'scripts/finalize_operating_reports_factory_release.py'
SUPPLEMENT = ROOT / 'scripts/supplement_operating_reports_F11_tool_time.py'
FRONTIER = ROOT / 'src/sheets_factory/evaluation/frontier.py'
PINS = {
    QUALITY: 'b87f30af319ed3b460e3c1e0a113c104c20f5b21857ca962ef6db331b18d82b8',
    FINALIZER: '98c0bf07b56c14314b158e5c3db126cec54727bf5194fdeeeb40cc4626ec4b00',
    SUPPLEMENT: 'c5523f284e679d934fb2f736b246ae82dad2ca8f1ed9d54b6d961f8229dd1d9e',
    FRONTIER: 'f507f738726347f61c27c3cf866d701e722690a87951b38d349b7d046d34df36',
}
TASK = 'fm-f11-f7a3b39b327a92e5ed0b'
ORIGINAL_CONFIRMATION_SHA = 'd3bb3e70eb71029abbd4022a6d53f20033033239cd7ba0c7bdfbd66b01460174'
RESULT_SHA = 'c1231f067ee6721fa60a9c5706a046d8245bab7b748a549f667bb65ef0458e40'
EVALUATION_SHA = '5c372400c38b18acdeff35273b5044e5656d2c6dc272d535b4b5448d7b6a45ca'
DISPLAY_SHA = '1816a80f40cdd6f1b9fe455aa16e623eac9d09a9298927f3ec2df57572ce90b1'
INTERPRETATION = 'append_only_F11_complete_timing_supplement_v1'


def require(value, message):
    if not value:
        raise ValueError(message)


def reference(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file() and not path.is_symlink(), 'Use a real evidence file')
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def read(record):
    require(isinstance(record, dict) and set(record) == {'path', 'sha256', 'bytes'}
            and reference(record['path']) == record, 'A retained evidence reference changed')
    return json.loads(Path(record['path']).read_text())


def write(path, value):
    path = Path(path).absolute()
    require(path == path.resolve() and not path.exists() and not path.is_symlink(), 'Use a fresh real output')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write('\n')
    return reference(path)


def _load(path, *, annotate_release=None):
    require(reference(path)['sha256'] == PINS[path], 'A frozen evidence consumer changed')
    name = '_append_only_' + path.stem
    if annotate_release is None:
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    # Add provenance before the unchanged finalizer writes its fresh result.
    # The original source file and every original module namespace stay intact.
    tree = ast.parse(path.read_text(), filename=str(path))
    edits = 0
    for function in tree.body:
        if isinstance(function, ast.FunctionDef) and function.name == 'finalize':
            body = []
            for node in function.body:
                body.append(node)
                if (isinstance(node, ast.Assign) and len(node.targets) == 1
                        and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'result'
                        and isinstance(node.value, ast.Dict)):
                    body.append(ast.Expr(ast.Call(ast.Name('_annotate_release', ast.Load()),
                                                 [ast.Name('result', ast.Load())], [])))
                    edits += 1
            function.body = body
    require(edits == 1, 'The frozen finalizer provenance seam changed')
    namespace = {'__name__': name, '__file__': str(path), '_annotate_release': annotate_release}
    exec(compile(ast.fix_missing_locations(tree), str(path), 'exec'), namespace)
    return namespace


def _projection(original, original_ref, supplement):
    """Resolve one timing-only status in memory after complete evidence replay."""
    require(original_ref['sha256'] == ORIGINAL_CONFIRMATION_SHA
            and supplement.get('kind') == 'readonly_F11_supplemental_complete_tool_time_evidence'
            and supplement.get('version') == 1 and supplement.get('task_id') == TASK
            and supplement.get('original_confirmation') == original_ref,
            'The supplement must bind the exact original F11 confirmation')
    require(original.get('kind') == 'operating_reports_factory_frontier_terminal_v6'
            and original.get('phase') == 'confirmation' and original.get('outer_retries') == 0
            and len(original.get('results', [])) == 20
            and len({r['task_id'] for r in original['results']}) == 20,
            'Keep the entire original one-attempt confirmation cohort')
    unknowns = [r for r in original['results'] if r['score'].get('state') == 'unknown']
    require(len(unknowns) == 1 and unknowns[0]['task_id'] == TASK,
            'Only the single declared F11 timing unknown may be supplemented')
    row = unknowns[0]; attempt = row['actual_attempt']; prior = attempt['tool_time']
    require(attempt.get('status') == 'evidence_incomplete'
            and attempt.get('failure_kind') == 'native_tool_timing_incomplete'
            and attempt.get('raw_verifier_reward') == 0
            and row['score'].get('effective_reward') is None
            and prior.get('passed') is None and prior.get('state') == 'unknown'
            and prior.get('policy_version') == 6
            and prior.get('problems') == ['Unsupported local result use or callback'],
            'An unrelated execution, business or infrastructure failure cannot be repaired here')
    result_ref = reference(attempt['result_file'])
    require(result_ref['sha256'] == RESULT_SHA == attempt['result_sha256']
            and supplement.get('result') == result_ref
            and supplement.get('material_identity') == row['material_identity']
            and supplement.get('retained_trial_resources') == row['resources']
            and supplement.get('original_v6_tool_time') == prior
            and row['resources'].get('passed') is row['resources'].get('complete') is True,
            'The original result, material, resource or timing binding changed')
    native = read(result_ref)
    require(native.get('task_name') == 'sheetsfactory/' + TASK
            and 'exception_info' in native and native['exception_info'] is None and native.get('finished_at')
            and type(native.get('verifier_result', {}).get('rewards', {}).get('reward')) in (int, float)
            and native['verifier_result']['rewards']['reward'] == 0,
            'Retain the original normal completed native result and raw reward')
    comparison = supplement['wrapper_comparison']; clock = supplement['supplemental_clock']
    wrappers = comparison['wrappers']; added = [w for w in wrappers if w['new_display_only']]
    require((comparison['wrapper_count'], comparison['v6_already_recognized'], comparison['new_display_wrappers']) == (22, 21, 1)
            and len(wrappers) == 22 and len(added) == 1
            and len({w['call_id'] for w in wrappers}) == 22
            and added[0]['code_sha256'] == DISPLAY_SHA and added[0]['primitive_count'] == 2
            and all(w['unchanged_primitive_dispatches'] is True for w in wrappers if not w['new_display_only']),
            'Only the exact terminal array-value display extension is allowed')
    coverage = clock['coverage']; tools = clock['tools']; bounds = (clock['cumulative_lower_bound_ns'], clock['cumulative_upper_bound_ns'])
    require(all(type(v) is int for v in bounds) and 0 <= bounds[0] <= bounds[1] < 1_800_000_000_000
            and clock.get('passed') is clock.get('complete') is True
            and clock.get('budget_seconds') == 1800 and clock.get('strict_less_than') is True
            and clock.get('parallel_executions') == 'sum' and clock.get('model_response_time_included') is False
            and not clock.get('problems') and clock.get('result_file') == result_ref
            and coverage['native_tool_count'] == coverage['stream_tool_count'] == len(tools) == 24
            and coverage['static_launch_count'] == 24 and coverage['unknown_dispatch_count'] == 0
            and coverage['all_primitives_uniquely_owned'] is True
            and coverage['wrapper_call_count'] == coverage['wrapper_output_count'] == len(clock['wrappers']) == 22
            and all(coverage.get(k) is True for k in (
                'native_stream_ordered_signatures_status_and_exits_equal', 'all_intervals_in_agent_window',
                'all_parallel_primitive_uppers_summed', 'all_uncovered_wrapper_time_retained',
                'disagreeing_clock_items_never_credit_overlap')),
            'Complete native/stream ownership and strict SUM bounds are required')
    require(supplement.get('original_v6_unknown_preserved') is True
            and supplement.get('original_scores_modified') is False
            and supplement.get('new_native_calls') == supplement.get('new_model_calls') == 0,
            'The supplement must preserve the original unknown and execute no new attempt')
    for record in [*supplement['recipes'], *comparison['sessions'], *clock['artifacts']]:
        require(reference(record['path']) == record, 'A supplemental source, session or stream changed')
    projected = deepcopy(original)
    target = next(r for r in projected['results'] if r['task_id'] == TASK)
    target['actual_attempt'].update(status='scored', failure_kind=None, reward=0, tool_time=deepcopy(clock))
    target['score'].update(effective_reward=0, state='complete')
    return projected


def _summarize(selection, attempts):
    require(reference(FRONTIER)['sha256'] == PINS[FRONTIER], 'The original score aggregator changed')
    tree = ast.parse(FRONTIER.read_text(), filename=str(FRONTIER))
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'summarize']
    require(len(functions) == 1, 'The original score aggregator seam changed')
    namespace = {'MODES': ('financial_modeling', 'debugging')}
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(FRONTIER), 'exec'), namespace)
    return namespace['summarize'](selection, attempts)


def _evaluation_projection(original, projected):
    record = original['evaluation']; evaluation = read(record)
    selection_ref = original['selection']; selection = read(selection_ref)
    require(record['sha256'] == EVALUATION_SHA
            and evaluation.get('phase') == 'confirmation' and evaluation.get('status') == 'infrastructure_failed'
            and evaluation.get('finished_at') and evaluation.get('failure_kind') is None
            and evaluation.get('infra_history') == [] and evaluation.get('infrastructure_retries') == []
            and evaluation.get('n_attempts') == 1 and evaluation.get('gate_passed') is False
            and evaluation.get('selection_manifest') == {k: selection_ref[k] for k in ('path', 'sha256')},
            'Only the exact aggregate failure caused by F11 timing can be supplemented')
    attempts = evaluation['attempts']; by_id = {a['task_id']: a for a in attempts}
    require(len(by_id) == len(attempts) == 20
            and by_id == {r['task_id']: r['actual_attempt'] for r in original['results']},
            'The complete original evaluation attempts must equal the original confirmation')
    old_score, old_gate = _summarize(selection, attempts)
    require(evaluation['score'] == old_score and old_gate is False
            and old_score['scored_tasks'] == 19 and old_score['total_tasks'] == 20
            and old_score['infrastructure_errors'] == 0 and old_score['incomplete_timing_evidence'] == 1,
            'An unrelated original aggregate failure cannot be changed')
    interpreted = deepcopy(evaluation)
    new_by_id = {r['task_id']: r['actual_attempt'] for r in projected['results']}
    interpreted['attempts'] = [deepcopy(new_by_id[a['task_id']]) for a in attempts]
    interpreted['score'], interpreted['gate_passed'] = _summarize(selection, interpreted['attempts'])
    require(interpreted['score']['scored_tasks'] == 20
            and interpreted['score']['incomplete_timing_evidence'] == interpreted['score']['infrastructure_errors'] == 0,
            'The supplemented evidence must complete every original attempt')
    interpreted['status'] = 'completed'
    return record, evaluation, interpreted


def finalize(cohort, fm_join, debug_join, root_controls, confirmation, supplement, output, *, quality_output):
    original_ref = reference(confirmation); supplement_ref = reference(supplement)
    original = read(original_ref)
    checker = _load(SUPPLEMENT)
    verified = checker.validate_supplement(supplement_ref)
    projected = _projection(original, original_ref, verified)
    evaluation_ref, evaluation, interpreted_evaluation = _evaluation_projection(original, projected)
    guarded = [original_ref, supplement_ref, evaluation_ref, original['selection'], verified['result'],
        reference(__file__), *[reference(p) for p in PINS], *verified['recipes'],
        *verified['wrapper_comparison']['sessions'], *verified['supplemental_clock']['artifacts']]
    def guard():
        require(all(reference(r['path']) == r for r in guarded), 'Retained evidence changed during interpretation')
    provenance = {'interpretation': INTERPRETATION, 'original_confirmation': original_ref,
        'timing_supplement': supplement_ref, 'original_v6_unknown_preserved': True,
        'original_evaluation': evaluation_ref, 'original_evaluation_status_preserved': evaluation['status'],
        'original_artifacts_modified': False, 'new_model_LO_Harbor_calls': 0,
        'supplemented_task_id': TASK, 'supplemented_result': verified['result'],
        'interpretation_recipe': [reference(__file__), *[reference(p) for p in PINS]]}
    def annotate(result):
        guard()
        result.update(version=2, timing_interpretation=deepcopy(provenance))
    quality = _load(QUALITY)
    original_read = quality.read
    def projected_read(record):
        if record == original_ref:
            require(read(original_ref) == original, 'Original confirmation changed during joining')
            return deepcopy(projected)
        return original_read(record)
    private = dict(quality._confirmation.__globals__, read=projected_read)
    quality._confirmation = FunctionType(quality._confirmation.__code__, private,
        quality._confirmation.__name__, quality._confirmation.__defaults__, quality._confirmation.__closure__)
    report = quality.build(cohort, fm_join, debug_join, root_controls, confirmation,
        ROOT / 'SpreadsheetEval')
    annotate(report)
    quality_ref = write(quality_output, report)
    require(report.get('passed') is True, 'All original quality/resource checks must pass; retain the new report')
    finalizer = _load(FINALIZER, annotate_release=annotate)
    old_scores = finalizer['confirmation_scores']
    def scores(terminal, selected):
        require(terminal == original and read(original_ref) == original,
                'Final scoring must consume the exact original confirmation')
        return old_scores(deepcopy(projected), selected)
    finalizer['confirmation_scores'] = scores
    original_read_ref = finalizer['read_ref']
    def interpreted_read_ref(record):
        if record == evaluation_ref:
            guard()
            return deepcopy(interpreted_evaluation)
        return original_read_ref(record)
    finalizer['read_ref'] = interpreted_read_ref
    result = finalizer['finalize'](cohort, confirmation, quality_ref['path'], root_controls, output)
    guard()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('cohort', 'fm-join', 'debug-join', 'root-controls', 'confirmation', 'supplement', 'quality-output', 'output'):
        parser.add_argument('--' + key, type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(finalize(args.cohort, args.fm_join, args.debug_join, args.root_controls,
        args.confirmation, args.supplement, args.output, quality_output=args.quality_output)))


if __name__ == '__main__':
    main()

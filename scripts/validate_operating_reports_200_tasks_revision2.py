#!/usr/bin/env python3
"""Fresh task8 proof with an explicit revised DBG design; reuse healthy source3."""
from __future__ import annotations

import argparse
import ast
from contextvars import ContextVar
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.workbook.operating_reports_200 import debug_design_revision2 as design

UPSTREAM = ROOT / 'scripts/validate_operating_reports_200_tasks.py'
UPSTREAM_SHA256 = 'b4d8376ec90df5d145f9f10889cfbaac393a12d0c94ac8bbccd1a19d8a72cae5'
DESIGN_PATH = ROOT / 'src/sheets_factory/workbook/operating_reports_200/debug_design_revision2.py'
DESIGN_SHA256 = '524a11be7e6e7e266af448f559f2a547588c01bd1ab46362d3bd2208c98625b8'
KIND = 'prepared_fixed_operating_reports_200_task_engineering_revision2'
TERMINAL_KIND = 'complete_fixed_operating_reports_200_task_engineering_revision2'
LINEAGE_KIND = 'fixed_operating_reports_200_task_fault_lineage_revision2'
_DESIGN_CONTEXT = ContextVar('fixed200_task8_revision2_design', default=None)


def _task_fault_plan(candidate):
    """Replay the new design against the entire original genuine candidate."""
    record = _DESIGN_CONTEXT.get()
    require(record is not None, 'A pre-frozen explicit task fault design is required')
    require(reference(DESIGN_PATH)['sha256'] == DESIGN_SHA256, 'The revised fault-design implementation changed')
    plans = design.validate_revision(record, candidate=candidate)
    frozen = read(record)
    require(read(frozen['view_plans']) == plans, 'The replayed design must be the exact retained plan')
    return frozen['view_plans']


def _lineage_value(design_ref, candidate_ref, source_ref, goal_ref, source_preparation):
    frozen = read(design_ref); candidate = read(candidate_ref); ancestry = frozen['ancestry']
    require(ancestry['original_candidate'] == candidate_ref
            and ancestry['unchanged_source_manifest'] == source_ref
            and ancestry['unchanged_genuine_goal'] == goal_ref,
            'Reuse the exact healthy source, goal and candidate from the retained failed attempt')
    require(candidate['view_plans'] == frozen['original_view_plans']
            and candidate['bindings'] == frozen['bindings']
            and candidate['specification'] == frozen['specification']
            and candidate['retained_A'] == frozen['retained_A'] and candidate['retained_B'] == frozen['retained_B'],
            'The new task design cannot replace source artifacts or financial bindings')
    failed = read(ancestry['failed_task8']); old = read(ancestry['failed_preparation'])
    require(failed['preparation'] == ancestry['failed_preparation']
            and old['source_preparation'] == source_preparation
            and old['source_manifest'] == source_ref and old['genuine_goal'] == goal_ref,
            'The unchanged source must bind the original failed task preparation')
    return {
        'kind': LINEAGE_KIND, 'version': 2, 'fault_design': design_ref,
        'revised_view_plans': frozen['view_plans'], 'pure_design_proof': frozen['proof'],
        'failed_task8': ancestry['failed_task8'], 'failed_preparation': ancestry['failed_preparation'],
        'original_candidate': candidate_ref, 'original_view_plans': candidate['view_plans'],
        'unchanged_source_manifest': source_ref, 'unchanged_source_preparation': source_preparation,
        'unchanged_genuine_goal': goal_ref, 'unchanged_bindings': candidate['bindings'],
        'unchanged_public_specification': candidate['specification'],
        'healthy_renderer': ancestry['healthy_renderer'], 'recipe': recipes(),
        'source_certification_reused_without_change': True, 'new_source_calls': 0,
        'new_financial_forwards': 0, 'actual_task_validation_inherited': False,
        'qualified': False, 'normal_all12_QA_passed': False,
    }


def _freeze_task_lineage(candidate, actual, source_preparation, output):
    design_ref = _DESIGN_CONTEXT.get()
    require(design_ref is not None, 'The task design must precede preparation')
    candidate_ref = source_preparation['candidate_manifest']
    require(read(candidate_ref) == candidate, 'Use the genuine original source candidate')
    frozen = read(design_ref)
    value = _lineage_value(design_ref, candidate_ref, frozen['ancestry']['unchanged_source_manifest'],
                           actual['source'], actual['preparation'])
    return write(Path(output) / 'task_fault_lineage.json', value)


def _namespace():
    raw = UPSTREAM.read_bytes()
    if hashlib.sha256(raw).hexdigest() != UPSTREAM_SHA256:
        raise ValueError('The frozen original fixed200 task8 lifecycle changed')
    counts = {'plan_reads': 0, 'prepared_lineage': 0, 'kind': 0, 'terminal_kind': 0}

    class Revision(ast.NodeTransformer):
        def visit_Assign(self, node):
            node = self.generic_visit(node)
            if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and node.targets[0].id == 'plans':
                wanted = ast.parse("read(candidate['view_plans'])", mode='eval').body
                if ast.dump(node.value) != ast.dump(wanted):
                    raise ValueError('An original task fault-plan read changed shape')
                node.value = ast.parse('read(_task_fault_plan(candidate))', mode='eval').body
                counts['plan_reads'] += 1
            return node

        def visit_Constant(self, node):
            if node.value == 'prepared_fixed_operating_reports_200_task_engineering':
                node.value = KIND; counts['kind'] += 1
            elif node.value == 'complete_fixed_operating_reports_200_task_engineering':
                node.value = TERMINAL_KIND; counts['terminal_kind'] += 1
            return node

        def visit_Dict(self, node):
            node = self.generic_visit(node)
            keys = {key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
            if {'source_manifest', 'planned_inputs', 'all_formula_cache_clearances', 'recipe'} <= keys:
                node.keys.append(ast.Constant('task_fault_lineage'))
                node.values.append(ast.parse('_freeze_task_lineage(candidate, actual, sf, output)', mode='eval').body)
                counts['prepared_lineage'] += 1
            return node

    tree = Revision().visit(ast.parse(raw))
    if counts != {'plan_reads': 2, 'prepared_lineage': 1, 'kind': 1, 'terminal_kind': 1}:
        raise ValueError('The counted task8 revision seam changed: ' + str(counts))
    private = {'__name__': '_isolated_fixed200_task8_revision2', '__file__': __file__,
               '_task_fault_plan': _task_fault_plan, '_freeze_task_lineage': _freeze_task_lineage}
    exec(compile(ast.fix_missing_locations(tree), str(UPSTREAM), 'exec'), private)
    return private, counts


_private, ADAPTATION_COUNTS = _namespace()
_runtime = _private['_ns']
reference, checked, read, write, require = (_private[key] for key in ('reference', 'checked', 'read', 'write', 'require'))
source, STAGES = _private['source'], _private['STAGES']
_base_recipes, _base_prepare, _base_validate = (_private[key] for key in ('recipes', 'prepare', 'validate_prepared'))
_base_completed = _private['validate_completed']


def recipes():
    require(reference(UPSTREAM)['sha256'] == UPSTREAM_SHA256, 'The frozen task8 ancestor changed')
    require(reference(DESIGN_PATH)['sha256'] == DESIGN_SHA256, 'The revised task design changed')
    # The design proof also checks the frozen renderer and all retained A/B refs.
    return {**_base_recipes(), str(UPSTREAM): reference(UPSTREAM),
            str(DESIGN_PATH): reference(DESIGN_PATH), str(Path(__file__).resolve()): reference(__file__)}


def prepare(source_manifest, output, *, fault_design):
    design_ref = fault_design if isinstance(fault_design, dict) else reference(fault_design)
    checked(design_ref)
    token = _DESIGN_CONTEXT.set(design_ref)
    try:
        return _base_prepare(source_manifest, output)
    finally:
        _DESIGN_CONTEXT.reset(token)


def validate_prepared(output):
    frozen = read(Path(output) / 'preparation.json')
    lineage = read(frozen['task_fault_lineage'])
    token = _DESIGN_CONTEXT.set(lineage['fault_design'])
    try:
        require(lineage == _lineage_value(lineage['fault_design'], frozen['candidate_preparation'],
                frozen['source_manifest'], frozen['genuine_goal'], frozen['source_preparation']),
                'The task fault-design lineage changed')
        return _base_validate(output)
    finally:
        _DESIGN_CONTEXT.reset(token)


def _terminal_namespace():
    """Retain the exact actual-call lifecycle, adding its bound task-stage lineage."""
    ancestor = _private['UPSTREAM']
    require(reference(ancestor)['sha256'] == _private['UPSTREAM_SHA'], 'The original eight-call lifecycle changed')
    tree = ast.parse(ancestor.read_bytes())
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'execute_prepared')
    count = 0

    class TerminalLineage(ast.NodeTransformer):
        def visit_Dict(self, node):
            nonlocal count
            node = self.generic_visit(node)
            keys = {key.value for key in node.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)}
            if {'actual_calls', 'source_LO_calls_reused', 'normal_all12_QA_passed', 'difficulty_claimed'} <= keys:
                node.keys.append(ast.Constant('task_fault_lineage'))
                node.values.append(ast.parse("f['task_fault_lineage']", mode='eval').body); count += 1
            return node

    function = TerminalLineage().visit(function)
    require(count == 1, 'The exact terminal provenance seam changed')
    # The original domain adaptation supplies definition-aware cache checks.
    cache_count = title_count = 0
    class CacheArgument(ast.NodeTransformer):
        def visit_Constant(self, node):
            nonlocal title_count
            if node.value == 'Equity-income FM/DBG engineering':
                node.value = 'Fixed200 revised DBG task engineering'; title_count += 1
            return node

        def visit_Call(self, node):
            nonlocal cache_count
            node = self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id == 'verify_input_caches':
                node.keywords.append(ast.keyword(arg='definition', value=ast.Name('definition', ast.Load())))
                cache_count += 1
            return node
    function = CacheArgument().visit(function)
    require(cache_count == 2 and title_count == 1, 'The original execute domain seams changed')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), str(ancestor), 'exec'), _runtime)
    return _runtime['execute_prepared'], {'terminal_lineage': count, 'execute_cache_arguments': cache_count,
                                         'dashboard_title': title_count}


def validate_completed(value):
    terminal = read(value)
    frozen = validate_prepared(checked(terminal['preparation']).parent)
    require(terminal['task_fault_lineage'] == frozen['task_fault_lineage'], 'The actual terminal lost its task-design lineage')
    return _base_completed(value)


_private.update(recipes=recipes, prepare=prepare, validate_prepared=validate_prepared)
_runtime.update(recipes=recipes, prepare=prepare, validate_prepared=validate_prepared, validate_completed=validate_completed)
execute_prepared, TERMINAL_ADAPTATION_COUNTS = _terminal_namespace()
_private['execute_prepared'] = execute_prepared


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', type=Path); parser.add_argument('--fault-design', type=Path)
    parser.add_argument('--output', type=Path); parser.add_argument('--prepared', type=Path)
    parser.add_argument('--run', action='store_true'); args = parser.parse_args(argv)
    if args.prepared:
        require(args.source_manifest is None and args.fault_design is None and args.output is None,
                'Use the exact frozen revision2 preparation')
        result = execute_prepared(args.prepared) if args.run else validate_prepared(args.prepared)
    else:
        require(args.source_manifest is not None and args.fault_design is not None and args.output is not None,
                'Supply the unchanged genuine source, pre-frozen fault design and fresh output')
        result = prepare(args.source_manifest, args.output, fault_design=args.fault_design)
        if args.run: result = execute_prepared(args.output)
    print(json.dumps(result)); return 0


if __name__ == '__main__':
    raise SystemExit(main())

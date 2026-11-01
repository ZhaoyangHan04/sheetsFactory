#!/usr/bin/env python3
"""Append a complete official-region evidence census; never recalculate or rescore runs."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, time, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.evaluation import spreadsheet_failure_analysis as evidence

INVENTORY_SHA = '654e7ab5c78ceba2293f046456cd8eaef57114725a994a44bdb03a900aadd684'
EVALUATOR_SHA = '5e31ba8f9cbdd8007eebfb441f9783cfaff280e90225b37ff61702863cb0f8b9'
CASE_KIND = 'complete_official_comparison_region_case_census'
BATCH_KIND = 'complete_official_comparison_region_census_batch'
ANCESTOR = ROOT / 'outputs/research/SB2_FM03_03_first_failure_forensics_20261031T173300Z/census.py'
reference, checked, read, write_new = evidence.reference, evidence.checked, evidence.read, evidence.write_new


def require(value, message):
    if not value:
        raise ValueError(message)


def load_evaluator(ref):
    path = checked(ref)
    require(reference(path)['sha256'] == EVALUATOR_SHA, 'Unknown official evaluator bytes')
    spec = importlib.util.spec_from_file_location('_original_official_region_census', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    checked(ref)
    return module


def recipes():
    paths = [Path(__file__), ROOT / 'tests/test_official_spreadsheet_region_census.py',
             Path(evidence.__file__), ANCESTOR]
    return {str(p.relative_to(ROOT)): reference(p) for p in paths}


def comparison_mode(case):
    path = case['official_record']['spreadsheet_path']
    debug = 'Debugging' in case['category']
    return {'with_font_color': debug and 'Color' in path,
            'with_formula': debug and 'Embedded' in path}


def _value(value):
    if hasattr(value, 'text'):
        return {'array_formula_text': value.text}
    if isinstance(value, (datetime, date, time)):
        return {'python_type': type(value).__name__, 'iso': value.isoformat()}
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    return {'python_type': type(value).__name__, 'repr': str(value)}


def _cell(cell):
    if cell is None:
        return None
    color = cell.font.color
    return {'value': _value(cell.value), 'data_type': cell.data_type,
            'font_color': None if color is None else {
                'type': color.type, 'value': _value(color.value), 'tint': color.tint}}


def _point(wb, sheet, cell, evaluator):
    ws = evaluator._find_sheet(wb, sheet) if wb else None
    return ws[cell] if ws is not None else None


def _match(evaluator, left, right, left_formula, right_formula, mode):
    if left is None or right is None:
        return False, 'missing_sheet'
    fallback = (not mode['with_formula'] and left_formula is not None and right_formula is not None
                and (evaluator._has_excel_error(left) or evaluator._has_excel_error(right)))
    if fallback:
        return evaluator.compare_cell_formula(left_formula, right_formula), 'excel_error_formula_fallback'
    return evaluator._compare_cells(left, right, **mode), (
        'formula' if mode['with_formula'] else 'value_and_font_color' if mode['with_font_color'] else 'value')


def compare_regions(source, goal, output, answer_position, mode, evaluator):
    """Use original pure helpers, then enumerate every classified point and miss."""
    paths = {'source': checked(source), 'reference': checked(goal), 'output': checked(output)}
    before = {key: reference(path) for key, path in paths.items()}
    books, formulas = {}, {}
    try:
        for key, path in paths.items():
            books[key] = openpyxl.load_workbook(path, data_only=not mode['with_formula'])
            formulas[key] = None if mode['with_formula'] else openpyxl.load_workbook(path, data_only=False)
        stats = dict(regression_correct=0, regression_total=0, modification_correct=0, modification_total=0)
        regions, misses, holds = [], [], []
        declared_count = 0
        for ordinal, text in enumerate(evaluator.parse_answer_position(answer_position)):
            if '!' in text:
                sheet, cell_range = text.split('!')  # Preserve the pinned evaluator's parsing.
            else:
                sheet, cell_range = books['reference'].sheetnames[0], text
            sheet, cell_range = sheet.strip("'").strip(), cell_range.strip("'").strip()
            declared = evaluator.generate_cell_names(cell_range)
            declared_count += len(declared)
            reg, mod = evaluator.classify_cells_by_modification(
                books['source'], books['reference'], sheet, cell_range, **mode,
                wb_input_formula=formulas['source'], wb_answer_formula=formulas['reference'])
            rc, rt, mc, mt, _ = evaluator.cell_level_compare_with_classification(
                books['reference'], books['output'], sheet, reg, mod, **mode,
                wb_answer_formula=formulas['reference'], wb_output_formula=formulas['output'])
            for key, value in zip(stats, (rc, rt, mc, mt)):
                stats[key] += value
            found = 0
            for label, cells in (('regression', reg), ('modification', mod)):
                for name in cells:
                    values = {key: _point(wb, sheet, name, evaluator) for key, wb in books.items()}
                    definitions = {key: _point(wb or books[key], sheet, name, evaluator)
                                   for key, wb in formulas.items()}
                    matched, rule = _match(evaluator, values['reference'], values['output'],
                                          definitions['reference'], definitions['output'], mode)
                    if not matched:
                        found += 1
                        misses.append({'region_index': ordinal, 'sheet': sheet, 'cell': name,
                                       'class': label, 'comparison_rule': rule,
                                       'source': _cell(values['source']), 'reference': _cell(values['reference']),
                                       'output': _cell(values['output']),
                                       'source_definition': _cell(definitions['source']),
                                       'reference_definition': _cell(definitions['reference']),
                                       'output_definition': _cell(definitions['output'])})
            require(found == rt + mt - rc - mc, 'Complete miss enumeration disagrees with original evaluator')
            missing_sheets = [key for key, wb in books.items() if evaluator._find_sheet(wb, sheet) is None]
            if missing_sheets:
                holds.append({'reason': 'declared_sheet_missing', 'region_index': ordinal, 'roles': missing_sheets})
            require(missing_sheets or rt + mt == len(declared), 'Original evaluator did not classify complete rectangle')
            regions.append({'region_index': ordinal, 'declaration': text, 'sheet': sheet, 'range': cell_range,
                            'declared_position_count': len(declared), 'regression_cells': reg,
                            'modification_cells': mod, 'regression_correct': rc, 'regression_total': rt,
                            'modification_correct': mc, 'modification_total': mt, 'miss_count': found})
        require(regions, 'Empty official comparison region')
        reg_ratio = round(stats['regression_correct'] / stats['regression_total'], 4) if stats['regression_total'] else 0.0
        mod_ratio = round(stats['modification_correct'] / stats['modification_total'], 4) if stats['modification_total'] else 0.0
        if reg_ratio >= .998:
            reg_ratio = 1.0
        metrics = {'regression_accuracy': reg_ratio, 'modification_accuracy': mod_ratio,
                   'accuracy': float(reg_ratio == mod_ratio == 1.0)}
        return {'stats': stats, 'reproduced_metrics': metrics, 'regions': regions, 'all_misses': misses,
                'holds': holds, 'summary': {'region_position_count': declared_count,
                    'classified_position_count': stats['regression_total'] + stats['modification_total'],
                    'miss_count': len(misses), 'region_count': len(regions),
                    'misses_by_class': dict(Counter(row['class'] for row in misses)),
                    'misses_by_rule': dict(Counter(row['comparison_rule'] for row in misses))},
                'overlapping_regions_counted_as_original': True,
                'all_declared_positions_enumerated': stats['regression_total'] + stats['modification_total'] == declared_count}
    finally:
        for wb in list(books.values()) + [v for v in formulas.values() if v is not None]:
            wb.close()
        for key, path in paths.items():
            require(reference(path) == before[key], 'Workbook changed during offline comparison')


def _same_content(left, right):
    checked(left); checked(right)
    return (left['sha256'], left['bytes']) == (right['sha256'], right['bytes'])


def resolve_case(case, cohort, evaluator_ref):
    """Bind the same canonical artifact paths as the frozen offline extractor."""
    folder = Path(cohort) / 'cases' / case['task_id']
    terminal_path = folder / 'terminal.json'
    bound = {'source': case['input'], 'reference': case['goal'], 'official_evaluator': evaluator_ref}
    if not terminal_path.is_file():
        return {'case': case, 'evidence': bound, 'holds': ['case_terminal_pending'], 'pending': True}
    bound['case_terminal'] = reference(terminal_path)
    terminal = read(bound['case_terminal'])
    require(terminal.get('task_id') == case['task_id'] and terminal.get('case_key') == case['case_key'], 'Foreign case terminal')
    trials = sorted(folder.glob('evaluation/harbor_jobs/*/*/result.json'))
    require(len(trials) <= 1, 'Multiple trials require explicit manual attribution')
    previous = case.get('existing_attempt') or {}
    result = trials[0] if trials else checked(previous['result']) if previous.get('result') else None
    holds = []
    if result is not None:
        bound['result'] = reference(result)
        for key, path in [('output', result.parent / 'artifacts/app/output.xlsx'),
                          ('trajectory', result.parent / 'agent/trajectory.json')]:
            if path.is_file():
                bound[key] = reference(path)
            else:
                holds.append(key + '_unavailable')
    else:
        holds.append('native_result_unavailable')
    official = terminal.get('official_primary') or {}
    scoring = {key: official[key] for key in ('input', 'reference', 'output', 'same_submitted_alias') if official.get(key)}
    for key, canonical in [('input', 'source'), ('reference', 'reference')]:
        if key in scoring:
            require(_same_content(scoring[key], bound[canonical]), 'Official scoring input identity mismatch')
        else:
            holds.append('official_scoring_' + key + '_unavailable')
    alias = scoring.get('output') or scoring.get('same_submitted_alias')
    if bound.get('output') and alias:
        require(_same_content(alias, bound['output']), 'Official score refers to another submission')
    else:
        holds.append('official_scoring_output_unavailable')
    mapped = official.get('mapped_record') or {}
    if mapped:
        for key in ('id', 'instruction', 'answer_position'):
            require(mapped.get(key) == case['official_record'].get(key), 'Official metadata transport changed')
    else:
        holds.append('official_mapped_record_unavailable')
    scorer = official.get('evaluator')
    postscore_ref = None
    if scorer is None and previous.get('official_postscore'):
        postscore_ref = previous['official_postscore']
        scorer = read(postscore_ref).get('pinned_evaluator')
    if scorer:
        require(_same_content(scorer, evaluator_ref), 'Official scorer evaluator identity mismatch')
        scoring['evaluator'] = scorer
    else:
        holds.append('original_official_evaluator_evidence_unavailable')
    score = official.get('result')
    if not isinstance(score, dict) or not all(key in score for key in ('accuracy', 'regression_accuracy', 'modification_accuracy')):
        holds.append('official_score_unavailable')
    for ref in bound.values():
        checked(ref)
    return {'case': case, 'evidence': bound, 'official_scoring_artifacts': scoring,
            'retained_official_postscore': postscore_ref,
            'original_official_score': score, 'terminal_layers': {key: terminal.get(key) for key in (
                'disposition', 'official_raw_accuracy', 'protocol_effective_accuracy', 'protocol_state',
                'native_run_complete', 'official_model_failure')}, 'holds': holds, 'pending': False}


def census_case(plan, evaluator):
    case = plan['case']
    report = {'kind': CASE_KIND, 'version': 1, 'case_key': case['case_key'], 'case_id': case['case_key'],
              'task_id': case['task_id'], 'evidence': plan['evidence'], 'holds': list(plan['holds']),
              'official_scoring_artifacts': plan.get('official_scoring_artifacts', {}),
              'retained_official_postscore': plan.get('retained_official_postscore'),
              'original_official_score': plan.get('original_official_score'),
              'terminal_layers': plan.get('terminal_layers', {}), 'comparison_mode': comparison_mode(case),
              'summary': {'region_position_count': None, 'miss_count': None},
              'official_score_consistency': None, 'all_misses': [], 'regions': [],
              'new_model_LO_solver_network_calls': 0, 'official_score_changed': False,
              'financial_root_cause_attribution_completed': False, 'qualified': False}
    if plan['evidence'].get('output'):
        comparison = compare_regions(plan['evidence']['source'], plan['evidence']['reference'],
            plan['evidence']['output'], case['official_record']['answer_position'], report['comparison_mode'], evaluator)
        report['holds'].extend(comparison.pop('holds'))
        report.update(comparison)
        score = plan.get('original_official_score')
        if score and all(key in score for key in comparison['reproduced_metrics']):
            report['official_score_consistency'] = all(score[key] == value for key, value in comparison['reproduced_metrics'].items())
            if not report['official_score_consistency']:
                report['holds'].append('reproduced_metrics_differ_from_original_official_score')
    for ref in list(plan['evidence'].values()) + list(plan.get('official_scoring_artifacts', {}).values()):
        checked(ref)
    if plan.get('retained_official_postscore'):
        checked(plan['retained_official_postscore'])
    report['status'] = 'pending' if plan['pending'] else 'hold' if report['holds'] else 'complete'
    return report


def run_batch(inventory, cohort, output):
    inventory_ref = reference(checked(inventory))
    require(inventory_ref['sha256'] == INVENTORY_SHA, 'Unknown official all200 inventory')
    data = read(inventory_ref)
    cases = data['cases']
    require(len(cases) == 200 and len({c['case_key'] for c in cases}) == 200, 'Incomplete or duplicate official inventory')
    require([c['case_key'] for c in cases] == data['fixed_order'], 'Frozen inventory order changed')
    require(Counter(c['category'] for c in cases) == {'Financial_Model': 100, 'Debugging': 100}, 'Official mode inventory changed')
    evaluator = load_evaluator(data['official_evaluator'])
    recipe = recipes()
    out = Path(output)
    out.mkdir(parents=True, exist_ok=False)
    plans = []
    for case in cases:
        try:
            plans.append(resolve_case(case, cohort, data['official_evaluator']))
        except Exception as error:
            path = Path(cohort) / 'cases' / case['task_id'] / 'terminal.json'
            bound = {'source': case['input'], 'reference': case['goal'], 'official_evaluator': data['official_evaluator']}
            if path.is_file():
                bound['case_terminal'] = reference(path)
            plans.append({'case': case, 'evidence': bound, 'holds': [
                {'reason': 'evidence_binding_exception', 'exception': type(error).__name__, 'message': str(error)}], 'pending': False})
    prospective = write_new(out / 'prospective.json', {
        'kind': 'prospective_complete_official_comparison_region_census', 'version': 1,
        'inventory': inventory_ref, 'cohort_directory': str(Path(cohort).resolve()), 'recipe': recipe,
        'created_at': datetime.now(timezone.utc).isoformat(), 'case_plans': plans,
        'new_model_LO_solver_network_calls': 0, 'original_scores_authoritative': True})
    index = []
    for plan in plans:
        try:
            report = census_case(plan, evaluator)
        except Exception as error:
            report = {'kind': CASE_KIND, 'version': 1, 'case_key': plan['case']['case_key'],
                'case_id': plan['case']['case_key'], 'task_id': plan['case']['task_id'],
                'status': 'hold', 'evidence': plan['evidence'], 'original_official_score': plan.get('original_official_score'),
                'summary': {'region_position_count': None, 'miss_count': None}, 'official_score_consistency': None,
                'holds': [{'reason': 'offline_comparison_exception', 'exception': type(error).__name__, 'message': str(error)}],
                'financial_root_cause_attribution_completed': False, 'official_score_changed': False,
                'new_model_LO_solver_network_calls': 0}
        report.update(inventory=inventory_ref, prospective=prospective, recipe=recipe)
        ref = write_new(out / 'cases' / plan['case']['task_id'] / 'census.json', report)
        index.append({'case_key': report['case_key'], 'task_id': report['task_id'], 'status': report['status'],
                      'case_terminal': report['evidence'].get('case_terminal'), 'report': ref,
                      'summary': {**report['summary'], 'official_score_consistent': report['official_score_consistency']},
                      'holds': report['holds']})
        print(json.dumps({'completed': len(index), 'case_key': report['case_key'], 'status': report['status']}), flush=True)
    checked(inventory_ref)
    for ref in recipe.values():
        checked(ref)
    for plan in plans:
        for ref in plan['evidence'].values():
            checked(ref)
    return write_new(out / 'index.json', {'kind': BATCH_KIND, 'version': 1, 'inventory': inventory_ref,
        'prospective': prospective, 'recipe': recipe, 'cohort_directory': str(Path(cohort).resolve()),
        'case_order': [c['case_key'] for c in cases], 'cases': index,
        'counts': dict(Counter(row['status'] for row in index)), 'new_model_LO_solver_network_calls': 0,
        'original_scores_authoritative': True, 'financial_root_cause_attribution_completed': False})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--evaluation', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='Fresh append-only evidence directory')
    args = parser.parse_args(argv)
    print(json.dumps({'index': run_batch(args.inventory, args.evaluation, args.output),
                      'new_model_LO_solver_network_calls': 0}), flush=True)


if __name__ == '__main__':
    main()

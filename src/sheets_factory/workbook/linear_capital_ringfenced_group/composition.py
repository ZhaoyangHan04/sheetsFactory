"""Exact product-set best/runner proof over four genuinely cold local proofs.

This module creates a mathematical certificate only. It emits no workbook and
does not admit a new source, task, quality result or model development attempt.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import gc
import importlib.util
from pathlib import Path
import time
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from . import contract as c

KIND = 'cold_composed_four_ringfenced_capital_best_runner_certificate'
REFERENCE_PATH = c.ROOT / 'src/sheets_factory/workbook/linear_capital_scaled/reference.py'
REFERENCE_SHA256 = '6b38f264f3dc3c3e06213768eaa50c5944ab3bac5ab643150d1d5260b115a44c'
SOURCE_PATH = c.ROOT / 'scripts/build_linear_capital_scaled_source.py'
SOURCE_SHA256 = '743c49ff2af634d4c0a4c42989d74068c96be3689f6818d25f486262f5a18f72'
EXACT_INTEGER_LIMIT = 2 ** 53
LOCAL_GEOMETRY = {'sheets': 370, 'physical_formulas': 1247328, 'nonempty_cells': 1773566,
                  'profile_targets_including_360_choices': 1522187,
                  'financial_bindings_without_choices': 1521827}


def _integer(value):
    c.require(type(value) is int and abs(value) < EXACT_INTEGER_LIMIT,
              'All posted amounts and their sums must be exact integers below2^53')
    return value


def _providers():
    c.require(c.reference(REFERENCE_PATH)['sha256'] == REFERENCE_SHA256
              and c.reference(SOURCE_PATH)['sha256'] == SOURCE_SHA256, 'A frozen genuine local validator changed')
    from sheets_factory.workbook.linear_capital_scaled import reference
    descriptor = importlib.util.spec_from_file_location('_ringfenced_genuine_scaled_source', SOURCE_PATH)
    source = importlib.util.module_from_spec(descriptor); descriptor.loader.exec_module(source)
    c.require(Path(reference.__file__).resolve() == REFERENCE_PATH, 'Unexpected local reference provider')
    return reference, source


def _report(value):
    scenarios = value['group']['scenarios']
    c.require(set(scenarios) == set(c.SCENARIOS) and value['feasible'] is True
              and value['selected_standalone_feasible'] is True, 'Every local plan must retain its genuine feasible financial report')
    for scenario in c.SCENARIOS:
        rows = scenarios[scenario]['annual']
        c.require(len(rows) == 20, 'Each complete scenario has20 unchanged fiscal years')
        for year, row in zip(c.YEARS, rows, strict=True):
            c.require(set(row) == {'year', 'fiscal_year', *c.GROUP_FIELDS}
                      and row['year'] == year and row['fiscal_year'] == 2026 + year,
                      'Local reporting periods or fields changed')
            for field in c.GROUP_FIELDS: _integer(row[field])
    c.require(len(value['constraints']) == 941 and all(row['passed'] is True for row in value['constraints']),
              'Retain every one of the941 local constraints for each plan')
    return scenarios


def _hydrate(context, reference_provider, source_provider):
    # FIRST consume the complete strict reference validator, never a JSON flag.
    started = time.monotonic()
    result = reference_provider.validate_completed(context['reference'])
    c.require(result == c.read(context['reference']) and result['specification'] == context['specification'],
              'The genuine local reference belongs to another fixed context')
    source = source_provider.validate_source(context['source_manifest'])
    c.require(source == c.read(context['source_manifest']) and source['independent_reference'] == context['reference']
              and source['public_specification']['sha256'] == context['specification']['sha256']
              and source['public_specification']['bytes'] == context['specification']['bytes']
              and source['winner_plan_private'] == result['winner_plan']
              and source['winner_objective_pence_private'] == result['winner_objective_pence'],
              'The entire actual local source must bind the exact certified reference and winner')
    public = c.read(context['specification'])
    c.require(public['fiscal_year_start'] == 2027 and public['years'] == list(c.YEARS)
              and public['scenario_ids'] == list(c.SCENARIOS) and len(public['project_ids']) == 360,
              'All four whole local public contexts must use the same reporting periods and scenarios')
    for side in ('A', 'B'):
        model = c.read(result['model_' + side])
        c.require(model['project_ids'] == public['project_ids'] and len(model['rows']) == 941
                  and model['specification_sha256'] == result['specification_sha256'],
                  'The whole independently checked local integer matrix changed')
    financial = c.read(result['reference_validation'])
    c.require(financial['passed'] is True and financial['require_group_feasible'] is True
              and [row['id'] for row in financial['plans']] == ['winner', 'runner'],
              'Use the complete original two-plan independent financial proof')
    selected = {}
    for label, row in zip(('best', 'runner'), financial['plans'], strict=True):
        plan_key = 'winner_plan' if label == 'best' else 'runner_plan'
        objective_key = 'winner_objective_pence' if label == 'best' else 'runner_objective_pence'
        c.require(row['plan'] == result[plan_key] and set(row['plan']) == set(public['project_ids'])
                  and all(type(bit) is int and bit in (0, 1) for bit in row['plan'].values())
                  and row['passed'] is True and row['A'] == row['B'], 'Full local A/B plan evidence changed')
        _report(row['A']); _report(row['B'])
        c.require(row['A']['objective_pence'] == result[objective_key], 'A local posted-pence objective changed')
        selected[label] = {'plan': row['plan'], 'objective_pence': _integer(result[objective_key]),
                           'report_A': row['A']['group']['scenarios'], 'report_B': row['B']['group']['scenarios']}
    gap = _integer(result['gap_pence'])
    c.require(gap == selected['best']['objective_pence'] - selected['runner']['objective_pence'] >= 1
              and result['unique_best'] is True and selected['best']['plan'] != selected['runner']['plan'],
              'Every local complete winner-excluded runner must have a positive exact gap')
    geometry = c.read(source['geometry']); counts = geometry['resource_limits']['counts']
    with ZipFile(c.checked(source['workbook'])) as book:
        sheets = len(ET.fromstring(book.read('xl/workbook.xml')).find('{*}sheets'))
    observed_geometry = {'sheets': sheets, 'physical_formulas': geometry['physical_formula_count'],
        'nonempty_cells': geometry['nonempty_cells'],
        'profile_targets_including_360_choices': counts['full_target_cells'],
        'financial_bindings_without_choices': geometry['complete_business_field_coverage']['physical_financial_bindings']}
    c.require(observed_geometry == LOCAL_GEOMETRY, 'The known complete local geometry changed')
    return {'id': context['id'], 'profile_id': context['profile_id'], **selected, 'gap_pence': gap,
        'geometry': observed_geometry, 'source_manifest': context['source_manifest'], 'workbook': source['workbook'],
        'reference': context['reference'], 'specification': context['specification'],
        'model_A': result['model_A'], 'model_B': result['model_B'],
        'best_solver_receipt': result['solver_receipts']['best'], 'excluded_runner_solver_receipt': result['solver_receipts']['runner'],
        'best_solver_validation': result['solver_validations']['best'], 'runner_solver_validation': result['solver_validations']['runner'],
        'whole_financial_validation': result['reference_validation'],
        'cold_validation_seconds': time.monotonic() - started}


def compose_values_a(locals_):
    """Plain product-set arithmetic, not an admission API or a solver."""
    c.require(len(locals_) == 4 and [v['id'] for v in locals_] == list(c.MANDATE_ORDER), 'Keep all four fixed mandates')
    best = 0; minimum = None; tied = []
    for local in locals_:
        W = _integer(local['best']['objective_pence']); R = _integer(local['runner']['objective_pence'])
        gap = _integer(W - R)
        c.require(gap == _integer(local['gap_pence']) and gap >= 1 and local['best']['plan'] != local['runner']['plan'],
                  'Every local best must have a distinct complete runner and positive gap')
        best = _integer(best + W)
        if minimum is None or gap < minimum: minimum, tied = gap, [local['id']]
        elif gap == minimum: tied.append(local['id'])
    def report(replaced):
        result = {}
        for scenario in c.SCENARIOS:
            annual = []
            for i, year in enumerate(c.YEARS):
                row = {'year': year, 'fiscal_year': 2026 + year}
                for field in c.GROUP_FIELDS:
                    total = 0
                    for local in locals_:
                        side = 'runner' if local['id'] == replaced else 'best'
                        total = _integer(total + _integer(local[side]['report_A'][scenario]['annual'][i][field]))
                    row[field] = total
                annual.append(row)
            result[scenario] = {'annual': annual}
        return result
    return {'winner_objective_pence': best, 'runner_objective_pence': _integer(best - minimum),
        'gap_pence': minimum, 'unique_best': True, 'minimum_gap_mandates': tied,
        'winner_plan': {local['id']: deepcopy(local['best']['plan']) for local in locals_},
        'canonical_runner_plan': {local['id']: deepcopy(local['runner' if local['id'] == tied[0] else 'best']['plan']) for local in locals_},
        'winner_report': report(None), 'canonical_runner_report': report(tied[0])}


def compose_values_b(locals_):
    """Independent column sums from retained B, with runner objective by swap."""
    c.require(tuple(x['id'] for x in locals_) == c.MANDATE_ORDER, 'The complete four-mandate order is required')
    differences = [_integer(_integer(x['best']['objective_pence']) - _integer(x['runner']['objective_pence'])) for x in locals_]
    c.require(all(g > 0 and g == _integer(x['gap_pence']) and x['best']['plan'] != x['runner']['plan']
                  for g, x in zip(differences, locals_, strict=True)), 'B requires each exact positive local runner gap')
    index = min(range(4), key=lambda i: differences[i]); indices = [i for i in range(4) if differences[i] == differences[index]]
    selections = [locals_[i]['runner' if i == index else 'best'] for i in range(4)]
    def columns(selections):
        scenarios = {}
        for scenario in c.SCENARIOS:
            rows = []
            for i in range(20):
                values = {field: _integer(sum(_integer(p['report_B'][scenario]['annual'][i][field]) for p in selections))
                          for field in c.GROUP_FIELDS}
                rows.append({'year': i + 1, 'fiscal_year': 2027 + i, **values})
            scenarios[scenario] = {'annual': rows}
        return scenarios
    return {'winner_objective_pence': _integer(sum(x['best']['objective_pence'] for x in locals_)),
        'runner_objective_pence': _integer(sum(x['objective_pence'] for x in selections)),
        'gap_pence': differences[index], 'unique_best': True, 'minimum_gap_mandates': [locals_[i]['id'] for i in indices],
        'winner_plan': {x['id']: deepcopy(x['best']['plan']) for x in locals_},
        'canonical_runner_plan': {x['id']: deepcopy(p['plan']) for x, p in zip(locals_, selections, strict=True)},
        'winner_report': columns([x['best'] for x in locals_]), 'canonical_runner_report': columns(selections)}


def _compose(frozen):
    reference_provider, source_provider = _providers()
    locals_ = []
    for context in frozen['contexts']:
        print('Cold validating ' + context['profile_id'] + ' reference and original source', flush=True)
        locals_.append(_hydrate(context, reference_provider, source_provider)); gc.collect()
    A, B = compose_values_a(locals_), compose_values_b(locals_)
    c.require(A == B, 'The independent group arithmetic and runner swap disagree')
    mandates = c.read(frozen['contract'])['mandates']
    evidence = [{key: row[key] for key in ('id', 'profile_id', 'reference', 'source_manifest', 'workbook', 'specification',
        'model_A', 'model_B', 'best_solver_receipt', 'excluded_runner_solver_receipt', 'best_solver_validation',
        'runner_solver_validation', 'whole_financial_validation', 'gap_pence', 'geometry')} for row in locals_]
    geometry = {key: sum(row['geometry'][key] for row in locals_) for key in LOCAL_GEOMETRY}
    return {'kind': KIND, 'version': 1, 'contract': frozen['contract'], 'composition': A,
        'local_whole_evidence': evidence,
        'donors': [{'id': row['id'], 'display_name': mandate['display_name'], 'prefix': mandate['sheet_prefix'],
                   'workbook': row['workbook'], 'source_manifest': row['source_manifest'], 'reference': row['reference']}
                  for row, mandate in zip(locals_, mandates, strict=True)],
        'geometry_before_global_header_and_reports': geometry,
        'FM_mask_projection_including_four_completion_gates': geometry['profile_targets_including_360_choices'] + 4,
        'proof': {'feasible_set': 'Cartesian product of four unchanged local feasible sets',
            'upper_bound': 'Every local objective is at most its certified local W; sum is at most sum(W).',
            'attainment': 'The tuple of all local winners attains that bound.',
            'uniqueness': 'Every changed mandate loses at least its strictly positive certified local gap.',
            'runner_bound': 'Any different complete plan loses at least min(local gaps).',
            'runner_attainment': 'Replace exactly one minimum-gap mandate by its whole certified local excluded-winner runner.',
            'ties': 'Each listed minimum-gap mandate gives one valid runner witness; further local runner ties are allowed.',
            'all_possible_global_runner_vectors_enumerated': False},
        'mathematical_composition_certified': True, 'cold_local_reference_count': 4, 'cold_original_source_count': 4,
        'independent_group_arithmetic_implementations': 2, 'original_local_proof_searches_reused': 8,
        'new_financial_universe_forwards': 0, 'new_solver_calls': 0, 'LO_calls': 0, 'model_calls': 0,
        'workbooks_written': 0, 'new_group_source_admitted': False, 'source_classification_pending': True,
        'qualified': False, 'normal_task_quality_passed': False, 'difficulty_qualified': False,
        'local_quality_or_development_inherited': False, 'coupled_1440_project_MIP_claimed': False,
        'local_reference_recipe': reference_provider.recipes(), 'local_source_recipe': source_provider.recipes(),
        'recipe': c.recipes()}


def build_certificate(prospective, output):
    frozen = c.validate_prospective(prospective)
    output = Path(output).absolute()
    c.require(output == output.resolve() and output.is_relative_to(c.ROOT / 'outputs') and not output.exists(),
              'Use a fresh certificate output; preserve all previous histories')
    # No output or alleged composition certificate exists before all eight cold gates.
    value = _compose(frozen)
    output.mkdir(parents=True)
    value.update(prospective=prospective if isinstance(prospective, dict) else c.reference(prospective),
                 created_at=datetime.now(timezone.utc).isoformat())
    return c.write(output / 'certificate.json', value)


def validate_certificate(record):
    retained = c.read(record); frozen = c.validate_prospective(retained['prospective'])
    expected = _compose(frozen)
    c.require({k: v for k, v in retained.items() if k not in ('prospective', 'created_at')} == expected,
              'The full mathematical certificate or exact local evidence changed')
    return retained

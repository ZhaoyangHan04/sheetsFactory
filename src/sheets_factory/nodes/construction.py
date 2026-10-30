from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path
import re
import shutil
import sys

import openpyxl
from openpyxl.utils.cell import range_boundaries, coordinate_to_tuple, get_column_letter

from ..core.node import BaseNode, TaskRejected
from ..workbook import profile_workbook, compare_workbooks, formula_references
from ..workbook.static_references import expand_static_formula, static_formula_text, StaticReferenceError
from ..checkers.unsafe_regions import evaluate_native_risk_guard
from ..checkers.native_error_probe import probe_native_errors
from ..checkers.native_error_dependencies import validate_static_reference_syntax


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prompt(ctx, name):
    filename = ctx.config.get('prompt_overrides', {}).get(name, name)
    return (Path(ctx.config['project_root']) / 'prompts' / filename).read_text()


def construction_contract(mode=None, config=None):
    """Machine-readable executor limits, distinct from authoring preferences."""
    modes = {
        'financial_modeling': {'edit_count': {'min': 6, 'max': 80}, 'after_must_be_null': True,
                              'every_masked_target_must_change_normalized_value': True},
        'debugging': {'edit_count': {'min': 2, 'max': 80}, 'after_must_be_different_excel_formula': True,
                      'each_root_requires_individual_and_combined_marginal_impact': True},
    }
    if mode is not None and mode not in modes:
        raise ValueError('Unsupported construction mode: ' + str(mode))
    settings = (config or {}).get('construction', {})
    root_impact_method = settings.get('root_impact_validation', 'strict')
    if root_impact_method not in {'strict', 'separated_roots', 'batched_separated_roots'}:
        raise ValueError('Invalid construction.root_impact_validation')
    max_root_impact_batches = settings.get('max_root_impact_batches', 256)
    if type(max_root_impact_batches) is not int or not 1 <= max_root_impact_batches <= 2048:
        raise ValueError('Invalid construction.max_root_impact_batches')
    root_impact_concurrency = settings.get('root_impact_concurrency', 1)
    if type(root_impact_concurrency) is not int or not 1 <= root_impact_concurrency <= 4:
        raise ValueError('Invalid construction.root_impact_concurrency')
    for name, maximum in settings.get('max_edit_count', {}).items():
        if name not in modes or type(maximum) is not int or not modes[name]['edit_count']['min'] <= maximum <= 200000:
            raise ValueError('Invalid configured construction edit limit')
        modes[name]['edit_count']['max'] = maximum
    analysis = {'max_dependency_closure_cells': 20000, 'max_profile_cells': 200000,
                'per_formula_reference_cells': 5000, 'max_mask_ranges': 64}
    supported = {'max_dependency_closure_cells': 500000, 'max_profile_cells': 500000,
                 'per_formula_reference_cells': 50000, 'max_mask_ranges': 1024}
    configured = settings.get('analysis_limits', {})
    if not isinstance(configured, dict):
        raise ValueError('construction.analysis_limits must be a dictionary')
    for name, maximum in configured.items():
        if name not in analysis or type(maximum) is not int or not 1 <= maximum <= supported[name]:
            raise ValueError('Invalid configured construction analysis limit: ' + str(name))
        analysis[name] = maximum
    preferences = {'financial_modeling_edit_count': [6, 20], 'debugging_edit_count': [2, 4]}
    preferences.update(settings.get('planning_preferences_only', {}))
    return {'version': 2, 'active_mode': mode, 'modes': modes,
        'root_impact_validation': root_impact_method,
        'max_root_impact_batches': max_root_impact_batches,
        'root_impact_concurrency': root_impact_concurrency,
        'planning_preferences_only': preferences,
        'range_authoring': {'financial_modeling_only': True, 'field': 'mask_ranges',
            'item_fields': ['sheet', 'range', 'reason', 'business_rule'],
            'existing_formula_cells_only': True, 'nonformula_cells_preserved': True,
            'before_assertions_compiled_from_immutable_baseline': True,
            'overlapping_targets_rejected': True, 'max_ranges': analysis['max_mask_ranges']},
        'scenario_inputs': {'max_count': 40, 'allowed_original_cells': ['numeric', 'blank'],
            'original_must_not_be_formula': True, 'before_must_match_original_exactly': True,
            'after_must_be_finite_numeric_and_not_boolean': True,
            'cannot_overwrite_labels_dates_or_text': True,
            'must_be_explicit_public_hypothetical_inputs': True},
        'target_requirements': {'original_must_be_existing_formula': True,
            'before_must_equal_original_formula_exactly': True, 'unique_existing_coordinates': True,
            'required_nonempty_fields': ['public_instruction', 'public_rules', 'reference_evidence'],
            'at_least_one_finite_numeric_target_with_absolute_value_above': 0.005},
        'dependency_requirements': {'true_cross_sheet_formula_edge_in_target_closure': True,
            'independent_local_targets_on_two_sheets_do_not_suffice': True,
            'max_dependency_closure_cells': analysis['max_dependency_closure_cells'],
            'per_formula_reference_cells': analysis['per_formula_reference_cells'],
            'no_native_calculation_errors_in_required_D': True,
            'ancestor_cached_errors_require_narrow_path_certificates_and_actual_LO_probes': True,
            'unchanged_finite_sentinels_alone_cannot_clear_errors': True,
            'all_formula_references_must_be_supported': True,
            'forbidden_volatile_functions': ['NOW', 'TODAY', 'RAND', 'RANDBETWEEN']},
        'source_requirements': {'min_nonempty_sheets': 4, 'min_formula_count': 6,
                                'max_profile_cells': analysis['max_profile_cells']},
        'reference_scope': {'complete_recalculated_changed_value_set': True,
            'baseline_formula_correction_supported': False, 'immutable_source_and_baseline': True,
            'verbal_scope_exclusions_cannot_remove_affected_cells': True,
            'missing_source_evidence_requires_unrepairable_not_invented_data': True}}


def compile_mask_ranges(plan, baseline, mode, config=None):
    """Expand declarative masks to asserted edits, without changing a workbook.

    Range proposals save authors from transcribing hundreds of source formulas.
    Every resulting edit still passes the normal per-cell business, impact and
    full-closure quality gates. No reference correctness follows from expansion.
    """
    if 'mask_ranges' not in plan:
        return plan
    ranges = plan['mask_ranges']
    contract = construction_contract(mode, config)
    max_ranges = contract['range_authoring']['max_ranges']
    if mode != 'financial_modeling' or not isinstance(ranges, list) or not 1 <= len(ranges) <= max_ranges:
        raise TaskRejected(f'Q06: mask_ranges requires 1 through {max_ranges} financial-modeling ranges')
    result = deepcopy(plan)
    edits = result.setdefault('edits', [])
    if not isinstance(edits, list) or any(not isinstance(e, dict) or not e.get('sheet') or not e.get('cell') for e in edits):
        raise TaskRejected('Q06: explicit mask edits are malformed')
    seen = {(e['sheet'], e['cell']) for e in edits}
    if len(seen) != len(edits):
        raise TaskRejected('Q06: duplicate explicit mask targets')
    maximum = contract['modes'][mode]['edit_count']['max']
    coverage = contract['source_requirements']['max_profile_cells']
    book = openpyxl.load_workbook(baseline, keep_links=False)
    receipts = []
    try:
        for group in ranges:
            if not isinstance(group, dict) or any(not isinstance(group.get(k), str) or not group[k].strip()
                    for k in ('sheet', 'range', 'reason', 'business_rule')):
                raise TaskRejected('Q06: a mask range lacks its coordinates or business evidence')
            if group['sheet'] not in book.sheetnames or not re.fullmatch(
                    r'\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6}(?::\$?[A-Z]{1,3}\$?[1-9][0-9]{0,6})?', group['range']):
                raise TaskRejected('Q06: invalid mask range or nonexistent sheet')
            left, top, right, bottom = range_boundaries(group['range'])
            if left > right or top > bottom or right > 16384 or bottom > 1048576 or (right-left+1)*(bottom-top+1) > coverage:
                raise TaskRejected('Q06: mask range exceeds supported profile coverage')
            added = []
            for row in book[group['sheet']].iter_rows(min_row=top, max_row=bottom, min_col=left, max_col=right):
                for cell in row:
                    if cell.data_type != 'f':
                        continue
                    key = (group['sheet'], cell.coordinate)
                    if key in seen:
                        raise TaskRejected('Q06: mask ranges overlap another target')
                    if not isinstance(cell.value, str):
                        raise TaskRejected('Q10: range contains unsupported array or shared formula objects')
                    seen.add(key)
                    edits.append({'sheet': group['sheet'], 'cell': cell.coordinate,
                        'before': cell.value, 'after': None, 'reason': group['reason'], 'business_rule': group['business_rule']})
                    added.append(cell.coordinate)
                    if len(edits) > maximum:
                        raise TaskRejected(f'Q06: expanded mask exceeds configured maximum={maximum}')
            if not added:
                raise TaskRejected('Q06: mask range contains no existing formulas')
            receipts.append({'proposal': deepcopy(group), 'expanded_formula_cells': added})
    finally:
        book.close()
    result.pop('mask_ranges')
    result['range_authoring_receipt'] = {'baseline_sha256': digest(baseline), 'groups': receipts,
        'expanded_edit_count': len(edits), 'source_workbook_modified': False}
    return result


def authoring_source_context(ctx):
    """Give authors exact immutable artifacts; absent fixture paths stay absent."""
    baseline = ctx.data.get('baseline')
    cache = ctx.data.get('source_cache')
    profile = Path(cache) / 'profile.json' if cache else None
    registry = Path(ctx.config.get('native_risks', {}).get('registry_path') or 'data/manifests/native_risks.json')
    if not registry.is_absolute():
        registry = Path(ctx.config['project_root']) / registry
    candidate = Path(ctx.config['project_root']) / '.venv312/bin/python'
    executable = candidate.absolute() if candidate.is_file() else Path(sys.executable).absolute()
    return {'source_file': ctx.source.name, 'source_path': str(ctx.source.resolve()),
            'source_sha256': digest(ctx.source) if ctx.source.is_file() else None,
            'native_risk_registry_path': str(registry.resolve()),
            'native_risk_registry_available': registry.is_file(),
            'baseline_path': str(Path(baseline).resolve()) if baseline else None,
            'baseline_is_immutable': True,
            'full_profile_path': str(profile.resolve()) if profile else None,
            'full_profile_available': bool(profile and profile.is_file()),
            'python_executable': str(executable)}


def compact_profile(profile, formula_limit=45, literal_limit=55):
    result = {k: profile[k] for k in ['sheet_count', 'nonempty_sheet_count', 'formula_count', 'errors', 'external_references']}
    result['sheets'] = []
    for sheet in profile['sheets']:
        formulas, literals, groups = [], [], {}
        for cell in sheet['cells']:
            if cell.get('formula'):
                key = re.sub(r'\$?[A-Z]{1,3}\$?\d+', '@', cell['formula'])
                count = groups.get(key, 0)
                groups[key] = count + 1
                if count < 2:
                    formulas.append({k: cell[k] for k in ['cell', 'formula', 'cached_value', 'row_labels', 'column_labels']})
            elif cell.get('value') is not None and len(literals) < literal_limit:
                literals.append({'cell': cell['cell'], 'value': cell['value']})
        result['sheets'].append({'name': sheet['name'], 'state': sheet['state'],
            'nonempty_cells': sheet['nonempty_cells'], 'formula_count': sheet['formula_count'],
            'formulas': formulas[:formula_limit], 'literals': literals})
    return result


class NormalizeNode(BaseNode):
    node_id = 'normalize'

    def execute(self, ctx):
        source_id = digest(ctx.source)
        cache = Path(ctx.config['run_dir']) / 'sources' / source_id[:12]
        cache.mkdir(parents=True, exist_ok=True)
        baseline = cache / 'baseline.xlsx'
        survey = ctx.data.get('survey', {})
        if not baseline.exists():
            cached = Path(survey.get('normalized_path', '/nonexistent'))
            if cached.is_file():
                shutil.copy2(cached, baseline)
            else:
                ctx.engine.normalize(ctx.source, baseline)
        stable_file = cache / 'stability.json'
        if stable_file.exists():
            stable = json.loads(stable_file.read_text())
        else:
            stable = ctx.engine.check_stable(baseline, cache / 'stability')
            stable_file.write_text(json.dumps(stable, indent=2))
        if not stable['stable']:
            raise TaskRejected('Q10: source values are not stable under repeated full recalculation')
        return {'source_id': source_id, 'baseline': baseline, 'source_cache': cache,
                'engine_report': {'normalization_ok': True, 'recalculation_ok': True, 'stable': True,
                                  'normalization_artifact': str(baseline), 'stability_artifact': str(stable_file),
                                  'engine': ctx.engine.metadata()}}


class ProfileNode(BaseNode):
    node_id = 'profile'

    def execute(self, ctx):
        path = ctx.data['source_cache'] / 'profile.json'
        contract = construction_contract(ctx.mode, ctx.config)
        limits = {'max_profile_cells': contract['source_requirements']['max_profile_cells'],
                  'per_formula_reference_cells': contract['dependency_requirements']['per_formula_reference_cells']}
        profile = json.loads(path.read_text()) if path.exists() else None
        legacy_limits = {'max_profile_cells': 200000, 'per_formula_reference_cells': 5000}
        if profile is None or profile.get('analysis_limits', legacy_limits) != limits:
            profile = profile_workbook(ctx.data['baseline'], max_cells=limits['max_profile_cells'],
                                       per_formula_reference_cells=limits['per_formula_reference_cells'])
            path.write_text(json.dumps(profile, ensure_ascii=False, indent=2))
        if profile['nonempty_sheet_count'] < 4 or profile['formula_count'] < 6:
            raise TaskRejected('Source lacks four nonempty sheets or a usable formula model')
        if profile['truncated']:
            raise TaskRejected('Full profile exceeds the configured coverage limit')
        if not any(any(ref['sheet'] != sheet['name'] for ref in cell.get('dependencies', {}).get('references', []))
                   for sheet in profile['sheets'] for cell in sheet['cells'] if cell.get('formula')):
            raise TaskRejected('Source contains no genuine cross-sheet formula dependency')
        return {'profile': profile}


class PlanNode(BaseNode):
    node_id = 'plan'

    def execute(self, ctx):
        variant = ctx.data.get('variant', 0)
        backend = ctx.config.get('construction', {}).get('authoring_backend', 'llm')
        templates = {'project_template', 'portfolio_template', 'composite_template'}
        if backend not in {'llm', *templates}:
            raise ValueError('Unsupported construction.authoring_backend')
        if backend in templates and (
                ctx.data.get('finance_evidence', {}).get('financial_seed_verified') is not True or variant != 0):
            raise TaskRejected('Financial template requires a verified financial source and a new source identity')
        scope = ctx.config.get('construction', {}).get('planning_scope', 'both_modes')
        if scope not in {'both_modes', 'per_mode'}:
            raise ValueError('construction.planning_scope must be both_modes or per_mode')
        requested = [ctx.mode] if scope == 'per_mode' else ['financial_modeling', 'debugging']
        suffix = '_' + ctx.mode if scope == 'per_mode' else ''
        backend_suffix = '_' + backend if backend != 'llm' else ''
        path = ctx.data['source_cache'] / f'task_plans_v{variant}{suffix}{backend_suffix}.json'
        if path.exists():
            plans = json.loads(path.read_text())
        elif backend in templates:
            evidence = ctx.data.get('finance_evidence', {})
            if backend == 'project_template':
                from ..workbook.derived_gold.task_templates import propose_project_task as propose
            elif backend == 'portfolio_template':
                from ..workbook.derived_gold.portfolio_tasks import propose_portfolio_task as propose
            else:
                from ..workbook.composite_finance.tasks import propose_task as propose
            plans = {'source_assessment': {'financial_evidence': evidence,
                                          'authoring_backend': backend, 'known_risks': []},
                     'financial_modeling': None, 'debugging': None}
            for requested_mode in requested:
                plans[requested_mode] = propose(Path(ctx.data['baseline']), requested_mode)
            path.write_text(json.dumps(plans, ensure_ascii=False, indent=2))
            ctx.audit.emit('planning.template', task_id=ctx.task_id, mode=ctx.mode,
                           backend=backend, baseline_sha256=digest(ctx.data['baseline']),
                           plan_sha256=digest(path), llm_calls=0)
        else:
            previous = []
            for item in ctx.data['source_cache'].glob('task_plans_v*.json'):
                if item == path:
                    continue
                prior = json.loads(item.read_text())
                previous.extend({'mode': mode, 'title': task.get('title'),
                                 'mask_ranges': task.get('mask_ranges', []),
                                 'cells': [(e['sheet'], e['cell']) for e in task.get('edits', [])]}
                                for mode, task in prior.items() if mode in ['financial_modeling', 'debugging'] and task)
            payload = {**authoring_source_context(ctx),
                       'requested_modes': requested,
                       'construction_contract': construction_contract(
                           ctx.mode if scope == 'per_mode' else None, ctx.config),
                       'variant': variant, 'previous_target_groups': previous,
                       'generation_feedback': ctx.config.get('generation_feedback', {}),
                       'known_source_business_issues': ctx.data.get('source_business_issues', []),
                       'finance_module_evidence': ctx.data.get('finance_evidence', {}),
                       'profile': compact_profile(ctx.data['profile'])}
            plans = ctx.llm.complete(prompt(ctx, 'planning.md') + '\nINPUT JSON:\n' + json.dumps(payload, ensure_ascii=False),
                                     role='planner', task_id=ctx.task_id, stage=self.node_id,
                                     timeout=ctx.config['agents']['timeout_seconds'])
            path.write_text(json.dumps(plans, ensure_ascii=False, indent=2))
        plan = plans.get(ctx.mode)
        if not plan:
            raise TaskRejected('Planner rejected source for this mode: ' + str(plans.get('source_assessment'))[:600])
        if backend == 'composite_template' and ctx.mode == 'debugging':
            from uuid import uuid4
            from ..workbook.composite_finance import activity as activity_module
            from ..workbook.composite_finance.debugging import suggest_root_impact_batches

            settings = ctx.config.get('construction', {}).get('composite_activity', {})
            if not isinstance(settings, dict) or set(settings) - {
                    'enabled', 'max_authoring_attempts', 'execute_fallback'}:
                raise ValueError('Invalid construction.composite_activity settings')
            enabled = settings.get('enabled', True)
            if type(enabled) is not bool:
                raise ValueError('construction.composite_activity.enabled must be boolean')
            limits = construction_contract(ctx.mode, ctx.config)['dependency_requirements']
            bounds = {'max_dependency_cells': limits['max_dependency_closure_cells'],
                      'per_formula_reference_cells': limits['per_formula_reference_cells']}
            plan = deepcopy(plan)
            if enabled:
                maximum = settings.get('max_authoring_attempts', 3)
                fallback = settings.get('execute_fallback', False)
                if type(maximum) is not int or not 1 <= maximum <= 3 or type(fallback) is not bool:
                    raise ValueError('Invalid cumulative composite activity attempt/fallback setting')
                canonical = lambda value: hashlib.sha256(json.dumps(value, sort_keys=True,
                    separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
                image = ctx.engine.metadata()
                binding = {'baseline_sha256': digest(ctx.data['baseline']),
                    'proposal_sha256': canonical(plan),
                    'implementation_sha256': digest(activity_module.__file__),
                    'settings_sha256': canonical({'max_authoring_attempts': maximum,
                        'execute_fallback': fallback, **bounds}), 'image_id': image.get('image_id')}
                cache_name = 'composite_activity_' + canonical(binding)[:32] + '.json'
                activity_cache = ctx.data['source_cache'] / cache_name
                cache_hit = activity_cache.is_file()
                if cache_hit:
                    cached_activity = json.loads(activity_cache.read_text())
                    if cached_activity.get('binding') != binding:
                        raise TaskRejected('Q06: composite activity cache binding differs')
                    for artifact in cached_activity.get('files', {}).values():
                        if (not Path(artifact['path']).is_file()
                                or digest(artifact['path']) != artifact['sha256']):
                            raise TaskRejected('Q06: composite activity cache artifact changed')
                    files = cached_activity.get('files', {})
                    if not {'receipt', 'activity_plan', 'grouped_plan', 'batch_planning'}.issubset(files):
                        raise TaskRejected('Q06: composite activity cache is incomplete')
                    receipt = json.loads(Path(files['receipt']['path']).read_text())
                    activity_plan = json.loads(Path(files['activity_plan']['path']).read_text())
                    if (receipt.get('before_plan_sha256') != binding['proposal_sha256']
                            or receipt.get('baseline_sha256') != binding['baseline_sha256']
                            or receipt.get('implementation_sha256') != binding['implementation_sha256']
                            or receipt.get('after_plan_sha256') != canonical(activity_plan)
                            or receipt.get('engine', {}).get('image_id') != binding['image_id']):
                        raise TaskRejected('Q06: composite activity receipt does not bind this proposal')
                    for call in receipt.get('engine_calls', []):
                        for name in ('raw', 'output'):
                            if (not call.get(name + '_path') or
                                    not Path(call[name + '_path']).is_file() or
                                    digest(call[name + '_path']) != call[name + '_sha256']):
                                raise TaskRejected('Q06: composite activity executed workbook changed')
                    plan = json.loads(Path(files['grouped_plan']['path']).read_text())
                    if plan.get('edits') != activity_plan.get('edits'):
                        raise TaskRejected('Q06: grouped activity edits differ from screened edits')
                else:
                    directory = ctx.revision_dir / 'private' / 'composite_activity' / uuid4().hex
                    result = activity_module.screen_composite_activity(Path(ctx.data['baseline']), plan,
                        engine=ctx.engine, directory=directory,
                        max_authoring_attempts=maximum, execute_fallback=fallback, **bounds)
                    receipt, activity_plan = result['receipt'], result['plan']
                    ctx.save('composite_activity_result.json', receipt)
                    if receipt.get('passed') is not True or receipt.get('blocking') is not False:
                        raise TaskRejected('Q06: composite joint activity rejected: ' +
                                           str(receipt.get('reason', receipt.get('state'))))
                    plan = deepcopy(activity_plan)
                    groups = suggest_root_impact_batches(Path(ctx.data['baseline']), plan['edits'], **bounds)
                    plan['root_impact_batches'] = groups['root_impact_batches']
                    plan['root_impact_batch_planning'] = groups
                    grouped = directory / 'grouped_plan.json'
                    batch_file = directory / 'root_batch_planning.json'
                    grouped.write_text(json.dumps(plan, ensure_ascii=False, indent=2))
                    batch_file.write_text(json.dumps(groups, ensure_ascii=False, indent=2))
                    paths = {'receipt': Path(result['receipt_path']),
                             'activity_plan': directory / 'screened_plan.json',
                             'grouped_plan': grouped, 'batch_planning': batch_file}
                    cached_activity = {'binding': binding, 'files': {
                        key: {'path': str(value.resolve()), 'sha256': digest(value)}
                        for key, value in paths.items()}}
                    activity_cache.write_text(json.dumps(cached_activity, ensure_ascii=False, indent=2))
                if receipt.get('passed') is not True or receipt.get('blocking') is not False:
                    raise TaskRejected('Q06: cached composite activity evidence is not passing')
                ctx.audit.emit('planning.composite_activity', task_id=ctx.task_id,
                    mode=ctx.mode, cache_hit=cache_hit,
                    baseline_sha256=binding['baseline_sha256'],
                    proposal_sha256=binding['proposal_sha256'],
                    retained_roots=len(plan['edits']),
                    authoring_attempts_used=receipt.get('authoring_attempts_used'),
                    actual_LO_calls_this_invocation=0 if cache_hit else receipt.get('actual_LO_execution_count'),
                    actual_LO_calls_in_evidence=receipt.get('actual_LO_execution_count'), llm_calls=0)
            else:
                groups = suggest_root_impact_batches(Path(ctx.data['baseline']), plan['edits'], **bounds)
                plan['root_impact_batches'] = groups['root_impact_batches']
                plan['root_impact_batch_planning'] = groups
                ctx.audit.emit('planning.composite_activity', task_id=ctx.task_id,
                    mode=ctx.mode, enabled=False, screening_certified=False, llm_calls=0,
                    required_next_step='Actual Construct individual/full-context marginal proof remains mandatory')
        # The revision controller expands range proposals before claiming their
        # exact cells; duplicate checks there use the complete compiled set.
        if plan.get('mask_ranges'):
            return {'plan': plan, 'source_assessment': plans.get('source_assessment', {})}
        selected = {(e['sheet'], e['cell']) for e in plan.get('edits', [])}
        for item in ctx.data['source_cache'].glob('task_plans_v*.json'):
            if item == path:
                continue
            prior = json.loads(item.read_text()).get(ctx.mode)
            if prior:
                previous = {(e['sheet'], e['cell']) for e in prior.get('edits', [])}
                if selected == previous or (selected and previous and len(selected & previous) / len(selected | previous) > .8):
                    raise TaskRejected('New variant repeats an existing target module')
        return {'plan': plan, 'source_assessment': plans.get('source_assessment', {})}


def validate_plan(plan, baseline, mode, config=None):
    edits = plan.get('edits', [])
    contract = construction_contract(mode, config)
    bounds = contract['modes'][mode]['edit_count']
    if len(edits) < bounds['min'] or len(edits) > bounds['max']:
        raise TaskRejected('Q06: target group size outside supported construction contract '
                           f'(mode={mode}, actual={len(edits)}, min={bounds["min"]}, max={bounds["max"]})')
    if not plan.get('public_instruction') or not plan.get('public_rules') or not plan.get('reference_evidence'):
        raise TaskRejected('Q01/Q04: missing public derivation rules or reference evidence')
    book = openpyxl.load_workbook(baseline, data_only=False, keep_links=False)
    values = openpyxl.load_workbook(baseline, data_only=True, keep_links=False)
    seen, involved, visited, cross_edges = set(), set(), set(), set()
    native_errors = {}
    meaningful_targets = 0
    reference_cache = {}
    expansion = contract['dependency_requirements']['per_formula_reference_cells']

    def resolved_dependencies(sheet_name, address, source_cell):
        try:
            formula_text = static_formula_text(source_cell)
        except StaticReferenceError as exc:
            raise TaskRejected(f'Q10: unresolved dependency at {sheet_name}!{address}: {exc}') from exc
        if re.search(r'\b(?:NOW|TODAY|RAND|RANDBETWEEN)\s*\(', formula_text, re.I):
            raise TaskRejected('Q10: unsupported or volatile formula in target dependency closure')
        dependencies = formula_references(formula_text, sheet_name, max_expansion=expansion,
            workbook=book, cache=reference_cache, include_resolved_formula=True)
        if (not dependencies['fully_supported']
                or validate_static_reference_syntax(dependencies['resolved_formula'])):
            raise TaskRejected(f'Q10: unresolved target dependency closure at {sheet_name}!{address}')
        return dependencies

    def inspect_dependencies(sheet_name, address):
        pending = [(sheet_name, address)]
        while pending:
            key = pending.pop()
            if key in visited:
                continue
            visited.add(key)
            if len(visited) > contract['dependency_requirements']['max_dependency_closure_cells']:
                raise TaskRejected('Target dependency closure exceeds supported analysis scope')
            current_sheet, current_address = key
            if current_sheet not in book.sheetnames:
                raise TaskRejected('Q10: target dependency references a missing sheet')
            source_cell = book[current_sheet][current_address]
            if values[current_sheet][current_address].data_type == 'e':
                native_errors[key] = {'sheet': current_sheet, 'cell': current_address,
                    'cached_error': values[current_sheet][current_address].value,
                    'formula': source_cell.value if source_cell.data_type == 'f' else None}
            if source_cell.data_type != 'f':
                continue
            dependencies = resolved_dependencies(current_sheet, current_address, source_cell)
            for reference in dependencies['references']:
                involved.add(reference['sheet'])
                if reference['sheet'] != current_sheet:
                    cross_edges.add((current_sheet, current_address, reference['sheet'], reference['cell']))
                target = (reference['sheet'], reference['cell'])
                if target not in visited:
                    pending.append(target)
    try:
        for edit in edits:
            key = (edit['sheet'], edit['cell'])
            if key in seen or key[0] not in book.sheetnames:
                raise TaskRejected('Q06: duplicate or nonexistent edit')
            seen.add(key)
            cell = book[key[0]][key[1]]
            if cell.data_type != 'f' or not isinstance(cell.value, str) or cell.value != edit['before']:
                raise TaskRejected('Q06: before assertion does not match actual original formula at ' + str(key))
            refs = resolved_dependencies(key[0], key[1], cell)
            value = values[key[0]][key[1]]
            if value.data_type == 'e' or value.value is None:
                raise TaskRejected('Q04: target has no valid recalculated reference value')
            if isinstance(value.value, float) and not math.isfinite(value.value):
                raise TaskRejected('Q04: nonfinite target value')
            if isinstance(value.value, (int, float)) and not isinstance(value.value, bool) and abs(value.value) > .005:
                meaningful_targets += 1
            inspect_dependencies(key[0], key[1])
            involved.add(key[0])
            for ref in refs['references']:
                involved.add(ref['sheet'])
                if ref['sheet'] not in values.sheetnames:
                    raise TaskRejected('Q10: direct input references a missing sheet')
            if mode == 'financial_modeling' and edit.get('after') is not None:
                raise TaskRejected('Modeling mask may only clear approved formulas')
            if mode == 'debugging' and (not isinstance(edit.get('after'), str) or not edit['after'].startswith('=') or edit['after'] == edit['before']):
                raise TaskRejected('Debugging requires an actual formula mutation')
        if len(involved) < 2 or not cross_edges:
            raise TaskRejected('Task does not involve a real cross-sheet calculation')
        if not meaningful_targets:
            raise TaskRejected('All targets are zero or nonnumeric; an explicit populated scenario is required')
    finally:
        book.close(); values.close()
    return {'edit_count': len(edits), 'dependency_sheets': sorted(involved), 'before_assertions_passed': True,
            'dependency_closure_cells': len(visited), 'cross_sheet_edges': sorted(cross_edges),
            'meaningful_nonzero_targets': meaningful_targets,
            'native_error_candidates': [native_errors[key] for key in sorted(native_errors)],
            'native_error_candidates_provisional': bool(native_errors),
            'native_error_policy': 'all paths require narrow certificates; actual full-D LO sensitivity probes are additional evidence, not business correctness'}


class ConstructNode(BaseNode):
    node_id = 'construct'

    def execute(self, ctx):
        public, private = ctx.revision_dir / 'public', ctx.revision_dir / 'private'
        public.mkdir(parents=True, exist_ok=True); private.mkdir(parents=True, exist_ok=True)
        goal = private / 'goal.xlsx'
        scenario = ctx.data['plan'].get('scenario_inputs', [])
        if scenario:
            scenario_limit = construction_contract(ctx.mode, ctx.config)['scenario_inputs']['max_count']
            if len(scenario) > scenario_limit:
                raise TaskRejected(f'Scenario input set exceeds supported scope (actual={len(scenario)}, max={scenario_limit})')
            base = openpyxl.load_workbook(ctx.data['baseline'], keep_links=False)
            for item in scenario:
                cell = base[item['sheet']][item['cell']]
                after = item['after']
                if cell.data_type == 'f' or cell.value != item.get('before') or isinstance(after, bool) or not isinstance(after, (int, float)) or not math.isfinite(after):
                    base.close()
                    raise TaskRejected('Scenario inputs must match numeric/blank public source inputs')
                if cell.value is not None and (isinstance(cell.value, bool) or not isinstance(cell.value, (int, float))):
                    base.close(); raise TaskRejected('Scenario cannot overwrite labels, dates or text')
                cell.value = after
            raw_baseline = private / 'scenario_baseline_raw.xlsx'; base.save(raw_baseline); base.close()
            ctx.engine.recalculate(raw_baseline, goal)
            ctx.save('scenario_inputs.json', scenario)
        else:
            shutil.copy2(ctx.data['baseline'], goal)
        validation = validate_plan(ctx.data['plan'], goal, ctx.mode, ctx.config)
        book = openpyxl.load_workbook(goal, keep_links=False)
        edits = ctx.data['plan']['edits']
        for edit in edits:
            book[edit['sheet']][edit['cell']] = edit['after']
        draft = private / 'mutated_unrecalculated.xlsx'
        book.save(draft); book.close()
        input_file = ctx.engine.recalculate(draft, public / 'input.xlsx')
        delta = compare_workbooks(input_file, goal, goal)
        if not delta.get('expected_change_count'):
            raise TaskRejected('Q06: mutation has no observable normalized value impact')
        if ctx.mode == 'financial_modeling' and any(
                e['sheet'] + '!' + e['cell'] not in delta['expected_changes'] for e in edits):
            raise TaskRejected('Q06: at least one masked target has no observable value change')
        native_guard = evaluate_native_risk_guard(delta['expected_changes'], ctx.data.get('source_id'),
            project_root=ctx.config['project_root'], sheet_names=delta.get('goal_sheets', []),
            registry_path=ctx.config.get('native_risks', {}).get('registry_path'),
            legacy_risks=ctx.data.get('source_business_issues', []))
        # Persist before rejection so the repair planner receives the actual D
        # intersection, including downstream cells outside physical edits.
        ctx.save('plan.json', ctx.data['plan']); ctx.save('expected_delta.json', delta)
        ctx.save('native_risk_guard.json', native_guard)
        ctx.data['native_risk_guard'] = native_guard
        ctx.audit.emit('native_risk_guard.result', task_id=ctx.task_id, revision=ctx.revision,
                       state=native_guard['state'], blocking=native_guard['blocking'],
                       risk_ids=[issue['risk_id'] for issue in native_guard['issues']])
        if native_guard['blocking']:
            affected = sorted({cell for issue in native_guard['issues'] if issue['certainty'] == 'confirmed'
                               for cell in issue['affected_cells']})
            raise TaskRejected('Q09: confirmed native unsafe region intersects complete changed-value set: '
                               + ', '.join(affected[:16]) + '; see private/native_risk_guard.json')
        # Cached errors in an expanded lookup range are provisional, never
        # automatically cleared. Recheck the complete actual D, not roots only.
        error_probe = probe_native_errors(goal=goal, required_delta=delta['expected_changes'],
            candidates=validation['native_error_candidates'], engine=ctx.engine,
            directory=private / 'native_error_probes', source_sha256=ctx.data.get('source_id') or digest(ctx.source),
            plan=ctx.data['plan'], revision=ctx.revision,
            immutable_files={'source': ctx.source, 'baseline': ctx.data['baseline']},
            engine_metadata=ctx.data.get('engine_report', {}).get('engine'),
            max_dependency_cells=construction_contract(ctx.mode, ctx.config)['dependency_requirements']['max_dependency_closure_cells'],
            per_formula_reference_cells=construction_contract(ctx.mode, ctx.config)['dependency_requirements']['per_formula_reference_cells'])
        validation['native_error_probe'] = error_probe
        validation['native_error_candidates'] = error_probe.get('candidates', validation['native_error_candidates'])
        validation['native_error_candidates_provisional'] = bool(validation['native_error_candidates'])
        ctx.save('native_error_probe.json', error_probe)
        ctx.save('edit_validation.json', validation)
        ctx.data['construction_validation'] = validation
        ctx.audit.emit('native_error_probe.result', task_id=ctx.task_id, revision=ctx.revision,
                       state=error_probe['state'], blocking=error_probe['blocking'],
                       candidates=len(error_probe['candidates']), probes=len(error_probe['probes']),
                       duration_ms=error_probe['duration_ms'])
        if error_probe['blocking']:
            raise TaskRejected(error_probe['problem_id'] + ': ' + error_probe.get('reason', 'native-error evidence incomplete')
                               + '; see private/native_error_probe.json')
        # Every root must have an effect by itself, not merely a syntactic edit.
        root_impacts = []
        root_method = construction_contract(ctx.mode, ctx.config)['root_impact_validation']
        if ctx.mode == 'debugging' and root_method == 'separated_roots':
            from ..checkers.separated_roots import certify_separated_roots
            limits = construction_contract(ctx.mode, ctx.config)['dependency_requirements']
            certificate = certify_separated_roots(goal=goal, combined_input=input_file, edits=edits,
                max_dependency_cells=limits['max_dependency_closure_cells'],
                per_formula_reference_cells=limits['per_formula_reference_cells'])
            ctx.save('separated_roots_certificate.json', certificate)
            ctx.audit.emit('root_impact_validation.result', task_id=ctx.task_id, revision=ctx.revision,
                method=root_method, state=certificate.get('state'), passed=certificate.get('passed'),
                root_count=len(edits))
            if certificate.get('passed') is not True or certificate.get('blocking') is not False:
                raise TaskRejected('Q06: separated-root proof rejected: ' + str(certificate.get('reason', 'incomplete proof')))
            root_impacts = certificate.get('root_impacts', [])
            expected_roots = {edit['sheet'] + '!' + edit['cell'] for edit in edits}
            proven_roots = {next(iter(impact.get('expected_changes', [])), None) for impact in root_impacts
                            if impact.get('proof_method') == 'separated_dependency_graph_and_actual_combined_value_change'
                            and impact.get('expected_change_count', 0) >= 1
                            and impact.get('combined_marginal', {}).get('expected_change_count', 0) >= 1}
            if len(root_impacts) != len(edits) or proven_roots != expected_roots:
                raise TaskRejected('Q06: separated-root certificate does not prove every declared root')
            validation['root_impact_validation'] = {'method': root_method,
                'proof_method': certificate.get('proof_method'), 'root_count': len(root_impacts),
                'individual_LO_executions': False, 'marginal_LO_executions': False}
        elif ctx.mode == 'debugging' and root_method == 'batched_separated_roots':
            from ..checkers.batched_roots import prove_batched_root_impacts
            from uuid import uuid4
            limits = construction_contract(ctx.mode, ctx.config)
            batch_options = {}
            if limits['root_impact_concurrency'] > 1:
                from ..checkers.parallel_batched_roots import prove_parallel_batched_root_impacts
                prove_batched_root_impacts = prove_parallel_batched_root_impacts
                batch_options['concurrency'] = limits['root_impact_concurrency']
            certificate = prove_batched_root_impacts(goal=goal, combined_input=input_file,
                edits=edits, batches=ctx.data['plan'].get('root_impact_batches'), engine=ctx.engine,
                directory=private / 'batched_root_impact_probes' / uuid4().hex,
                max_batches=limits['max_root_impact_batches'],
                max_dependency_cells=limits['dependency_requirements']['max_dependency_closure_cells'],
                per_formula_reference_cells=limits['dependency_requirements']['per_formula_reference_cells'],
                **batch_options)
            ctx.save('batched_roots_certificate.json', certificate)
            ctx.audit.emit('root_impact_validation.result', task_id=ctx.task_id, revision=ctx.revision,
                method=root_method, state=certificate.get('state'), passed=certificate.get('passed'),
                root_count=len(edits), batch_count=certificate.get('batch_count'),
                actual_batch_LO_executions=certificate.get('actual_batch_LO_execution_count'),
                duration_ms=certificate.get('duration_ms'))
            if certificate.get('state') == 'execution_error':
                raise RuntimeError('Batch root-impact recalculation failed: ' + str(certificate.get('reason')))
            if certificate.get('passed') is not True or certificate.get('blocking') is not False:
                raise TaskRejected('Q06: batched root-impact proof rejected: ' + str(certificate.get('reason', 'incomplete proof')))
            root_impacts = certificate.get('root_impacts', [])
            expected_roots = {edit['sheet'] + '!' + edit['cell'] for edit in edits}
            proven_roots = {next(iter(impact.get('expected_changes', [])), None) for impact in root_impacts
                if impact.get('proof_method') == 'batched_separation_and_actual_LO_values'
                and impact.get('expected_change_count', 0) >= 1
                and impact.get('combined_marginal', {}).get('expected_change_count', 0) >= 1
                and impact.get('combined_marginal', {}).get('edits_reversed') is True
                and impact.get('combined_marginal', {}).get('base') == 'full_combined_mutation'}
            if len(root_impacts) != len(edits) or proven_roots != expected_roots:
                raise TaskRejected('Q06: batch certificate does not prove every declared root')
            validation['root_impact_validation'] = {'method': root_method,
                'proof_method': certificate['proof_method'], 'root_count': len(root_impacts),
                'batch_count': certificate['batch_count'],
                'actual_batch_LO_execution_count': certificate['actual_batch_LO_execution_count'],
                'individual_LO_executions': False, 'marginal_LO_executions': False,
                'counts_are_lower_bounds': True}
        elif ctx.mode == 'debugging':
            for index, edit in enumerate(edits):
                one = openpyxl.load_workbook(goal, keep_links=False)
                one[edit['sheet']][edit['cell']] = edit['after']
                raw = private / f'root_{index}_raw.xlsx'; one.save(raw); one.close()
                calc = ctx.engine.recalculate(raw, private / f'root_{index}.xlsx')
                impact = compare_workbooks(calc, goal, goal)
                root_impacts.append(impact)
                if not impact.get('expected_change_count'):
                    raise TaskRejected('Q06: an injected root is inactive or erased by rounding')
                combined = openpyxl.load_workbook(input_file, keep_links=False)
                combined[edit['sheet']][edit['cell']] = edit['before']
                partial_raw = private / f'marginal_{index}_raw.xlsx'; combined.save(partial_raw); combined.close()
                partial = ctx.engine.recalculate(partial_raw, private / f'marginal_{index}.xlsx')
                marginal = compare_workbooks(input_file, partial, partial)
                root_impacts[-1]['combined_marginal'] = marginal
                if not marginal.get('expected_change_count'):
                    raise TaskRejected('Q06: a root is inactive in the combined mutation')
        analysis = construction_contract(ctx.mode, ctx.config)
        public_profile = profile_workbook(input_file,
            max_cells=analysis['source_requirements']['max_profile_cells'],
            per_formula_reference_cells=analysis['dependency_requirements']['per_formula_reference_cells'])
        ctx.save('plan.json', ctx.data['plan']); ctx.save('edit_validation.json', validation)
        ctx.save('expected_delta.json', delta); ctx.save('root_impacts.json', root_impacts)
        ctx.save('profile.json', public_profile, private=False)
        return {'input': input_file, 'goal': goal, 'public_profile': public_profile,
                'delta': delta, 'construction_validation': validation, 'root_impacts': root_impacts,
                'native_risk_guard': native_guard}


def compact_target_regions(edits):
    """Cover the exact selected cells with rectangles; never include a hole."""
    sheets = {}
    for edit in edits:
        row, column = coordinate_to_tuple(edit['cell'])
        sheets.setdefault(edit['sheet'], {}).setdefault(row, set()).add(column)
    labels = []
    for sheet, rows in sheets.items():
        active, rectangles = {}, []
        for row in sorted(rows):
            intervals = []
            for column in sorted(rows[row]):
                if intervals and intervals[-1][1] + 1 == column:
                    intervals[-1] = (intervals[-1][0], column)
                else:
                    intervals.append((column, column))
            following = {}
            for interval in intervals:
                previous = active.pop(interval, None)
                if previous and previous[1] == row - 1:
                    following[interval] = (previous[0], row)
                else:
                    if previous:
                        rectangles.append((*interval, *previous))
                    following[interval] = (row, row)
            rectangles.extend((*interval, *span) for interval, span in active.items())
            active = following
        rectangles.extend((*interval, *span) for interval, span in active.items())
        quoted = "'" + sheet.replace("'", "''") + "'!"
        for left, right, top, bottom in sorted(rectangles, key=lambda item: (item[2], item[0])):
            first, last = get_column_letter(left) + str(top), get_column_letter(right) + str(bottom)
            labels.append(quoted + first + (':' + last if first != last else ''))
    return '; '.join(labels)


class InstructionNode(BaseNode):
    node_id = 'instruction'

    def execute(self, ctx):
        text = ctx.data['plan']['public_instruction'].strip()
        rules = ctx.data['plan']['public_rules']
        style = ctx.config.get('construction', {}).get('instruction_style', 'full')
        if style not in {'full', 'business_brief'}:
            raise ValueError('Unsupported construction.instruction_style')
        heading = 'Model context:' if style == 'business_brief' else 'Public calculation rules and input evidence:'
        text += '\n\n' + heading + '\n' + '\n'.join(
            '- ' + (rule if isinstance(rule, str) else json.dumps(rule, ensure_ascii=False))
            for rule in rules) + '\n'
        scenario = ctx.data['plan'].get('scenario_inputs', [])
        if scenario:
            text += '\nHypothetical planning scenario already entered in the input workbook (not historical source facts):\n'
            text += '\n'.join(f"- '{s['sheet']}'!{s['cell']}: {s['after']} {s.get('unit', '')}; {s.get('meaning', '')}" for s in scenario) + '\n'
        if ctx.mode == 'financial_modeling':
            edits = ctx.data['plan']['edits']
            locations = (compact_target_regions(edits) if len(edits) > 80 else
                '; '.join(f"'{e['sheet']}'!{e['cell']}" for e in edits))
            text += '\n\nMissing formula cells to complete: ' + locations + '.\n'
        if style == 'business_brief':
            text += ('\n\nPreserve inputs, existing structure and unrelated formulas; allow dependent results '
                     'to recalculate. Read /app/input.xlsx and save /app/output.xlsx. '
                     'Values will be checked after LibreOffice recalculation.\n')
        else:
            text += ('\n\nWork only within the stated financial-model scope. Preserve unrelated inputs, existing '
                     'worksheets and unaffected values. Read /app/input.xlsx and save /app/output.xlsx. '
                     'The file will be fully recalculated in LibreOffice before values are checked.\n')
        path = ctx.revision_dir / 'public/instruction.md'; path.write_text(text)
        return {'instruction': text, 'instruction_path': path,
                'revision_hash': hashlib.sha256(ctx.data['input'].read_bytes() + text.encode()).hexdigest()}


class ControlsNode(BaseNode):
    node_id = 'precheck'

    def execute(self, ctx):
        source, goal = ctx.data['input'], ctx.data['goal']
        controls = {'oracle': compare_workbooks(source, goal, goal), 'nop': compare_workbooks(source, goal, source)}
        folder = ctx.revision_dir / 'private/controls'; folder.mkdir(parents=True, exist_ok=True)
        first = ctx.data['plan']['edits'][0]
        for name in ['equivalent', 'missed_root', 'extra_change']:
            book = openpyxl.load_workbook(goal, keep_links=False)
            if name == 'equivalent':
                original = first['before']
                # SUM coerces text and booleans and is not generally an
                # equivalent expression. IF preserves the selected value/type.
                book[first['sheet']][first['cell']] = '=IF(TRUE(),' + original[1:] + ',"")'
            elif name == 'missed_root':
                book[first['sheet']][first['cell']] = first['after']
            else:
                book[book.sheetnames[0]]['XFD100'] = 'unexpected extra value'
            raw = folder / (name + '_raw.xlsx'); book.save(raw); book.close()
            recalculated = ctx.engine.recalculate(raw, folder / (name + '.xlsx'))
            controls[name] = compare_workbooks(source, goal, recalculated)
        ctx.save('local_controls.json', controls)
        if any(controls[name].get('reward') != expected for name, expected in
               [('oracle', 1), ('nop', 0), ('equivalent', 1), ('missed_root', 0), ('extra_change', 0)]):
            raise TaskRejected('Q05/Q06: positive/negative verifier controls did not match')
        return {'controls': controls}

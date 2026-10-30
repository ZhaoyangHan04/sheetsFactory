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
from openpyxl.utils.cell import range_boundaries

from ..core.node import BaseNode, TaskRejected
from ..workbook import profile_workbook, compare_workbooks, formula_references
from ..checkers.unsafe_regions import evaluate_native_risk_guard


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
    for name, maximum in settings.get('max_edit_count', {}).items():
        if name not in modes or type(maximum) is not int or not modes[name]['edit_count']['min'] <= maximum <= 4096:
            raise ValueError('Invalid configured construction edit limit')
        modes[name]['edit_count']['max'] = maximum
    preferences = {'financial_modeling_edit_count': [6, 20], 'debugging_edit_count': [2, 4]}
    preferences.update(settings.get('planning_preferences_only', {}))
    return {'version': 2, 'active_mode': mode, 'modes': modes,
        'planning_preferences_only': preferences,
        'range_authoring': {'financial_modeling_only': True, 'field': 'mask_ranges',
            'item_fields': ['sheet', 'range', 'reason', 'business_rule'],
            'existing_formula_cells_only': True, 'nonformula_cells_preserved': True,
            'before_assertions_compiled_from_immutable_baseline': True,
            'overlapping_targets_rejected': True, 'max_ranges': 64},
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
            'max_dependency_closure_cells': 20000, 'no_native_calculation_errors': True,
            'all_formula_references_must_be_supported': True,
            'forbidden_volatile_functions': ['NOW', 'TODAY', 'RAND', 'RANDBETWEEN']},
        'source_requirements': {'min_nonempty_sheets': 4, 'min_formula_count': 6,
                                'max_profile_cells': 200000},
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
    if mode != 'financial_modeling' or not isinstance(ranges, list) or not 1 <= len(ranges) <= 64:
        raise TaskRejected('Q06: mask_ranges requires 1 through 64 financial-modeling ranges')
    result = deepcopy(plan)
    edits = result.setdefault('edits', [])
    if not isinstance(edits, list) or any(not isinstance(e, dict) or not e.get('sheet') or not e.get('cell') for e in edits):
        raise TaskRejected('Q06: explicit mask edits are malformed')
    seen = {(e['sheet'], e['cell']) for e in edits}
    if len(seen) != len(edits):
        raise TaskRejected('Q06: duplicate explicit mask targets')
    maximum = construction_contract(mode, config)['modes'][mode]['edit_count']['max']
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
            if left > right or top > bottom or right > 16384 or bottom > 1048576 or (right-left+1)*(bottom-top+1) > 200000:
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
        if path.exists():
            profile = json.loads(path.read_text())
        else:
            profile = profile_workbook(ctx.data['baseline'], max_cells=200000)
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
        path = ctx.data['source_cache'] / f'task_plans_v{variant}.json'
        if path.exists():
            plans = json.loads(path.read_text())
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
            payload = {**authoring_source_context(ctx), 'construction_contract': construction_contract(config=ctx.config),
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
    meaningful_targets = 0

    def inspect_dependencies(sheet_name, address):
        key = (sheet_name, address)
        if key in visited:
            return
        visited.add(key)
        if len(visited) > contract['dependency_requirements']['max_dependency_closure_cells']:
            raise TaskRejected('Target dependency closure exceeds supported analysis scope')
        if sheet_name not in book.sheetnames:
            raise TaskRejected('Q10: target dependency references a missing sheet')
        source_cell = book[sheet_name][address]
        if values[sheet_name][address].data_type == 'e':
            raise TaskRejected('Q09: native calculation error in target dependency closure')
        if source_cell.data_type != 'f':
            return
        if not isinstance(source_cell.value, str) or re.search(r'\b(?:NOW|TODAY|RAND|RANDBETWEEN)\s*\(', source_cell.value, re.I):
            raise TaskRejected('Q10: unsupported or volatile formula in target dependency closure')
        dependencies = formula_references(source_cell.value, sheet_name)
        if not dependencies['fully_supported']:
            raise TaskRejected('Q10: unresolved target dependency closure')
        for reference in dependencies['references']:
            involved.add(reference['sheet'])
            if reference['sheet'] != sheet_name:
                cross_edges.add((sheet_name, address, reference['sheet'], reference['cell']))
            inspect_dependencies(reference['sheet'], reference['cell'])
    try:
        for edit in edits:
            key = (edit['sheet'], edit['cell'])
            if key in seen or key[0] not in book.sheetnames:
                raise TaskRejected('Q06: duplicate or nonexistent edit')
            seen.add(key)
            cell = book[key[0]][key[1]]
            if cell.data_type != 'f' or not isinstance(cell.value, str) or cell.value != edit['before']:
                raise TaskRejected('Q06: before assertion does not match actual original formula at ' + str(key))
            refs = formula_references(cell.value, key[0])
            if not refs['fully_supported']:
                raise TaskRejected('Q10: unresolved references at target ' + str(key))
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
                if ref['sheet'] not in values.sheetnames or values[ref['sheet']][ref['cell']].data_type == 'e':
                    raise TaskRejected('Q09: direct input error contaminates target')
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
            'meaningful_nonzero_targets': meaningful_targets}


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
        # Every root must have an effect by itself, not merely a syntactic edit.
        root_impacts = []
        if ctx.mode == 'debugging':
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
        public_profile = profile_workbook(input_file, max_cells=200000)
        ctx.save('plan.json', ctx.data['plan']); ctx.save('edit_validation.json', validation)
        ctx.save('expected_delta.json', delta); ctx.save('root_impacts.json', root_impacts)
        ctx.save('profile.json', public_profile, private=False)
        return {'input': input_file, 'goal': goal, 'public_profile': public_profile,
                'delta': delta, 'construction_validation': validation, 'root_impacts': root_impacts,
                'native_risk_guard': native_guard}


class InstructionNode(BaseNode):
    node_id = 'instruction'

    def execute(self, ctx):
        text = ctx.data['plan']['public_instruction'].strip()
        rules = ctx.data['plan']['public_rules']
        text += '\n\nPublic calculation rules and input evidence:\n' + '\n'.join(
            '- ' + (rule if isinstance(rule, str) else json.dumps(rule, ensure_ascii=False))
            for rule in rules) + '\n'
        scenario = ctx.data['plan'].get('scenario_inputs', [])
        if scenario:
            text += '\nHypothetical planning scenario already entered in the input workbook (not historical source facts):\n'
            text += '\n'.join(f"- '{s['sheet']}'!{s['cell']}: {s['after']} {s.get('unit', '')}; {s.get('meaning', '')}" for s in scenario) + '\n'
        if ctx.mode == 'financial_modeling':
            locations = '; '.join(f"'{e['sheet']}'!{e['cell']}" for e in ctx.data['plan']['edits'])
            text += '\n\nMissing formula cells to complete: ' + locations + '.\n'
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

#!/usr/bin/env python3
"""Eight real task/control calculations after fixed200 source3 admission."""
from __future__ import annotations

import ast
from collections import Counter
from copy import deepcopy
import hashlib
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'scripts/validate_equity_income_group_tasks.py'
UPSTREAM_SHA = 'bcc07848ed5b868c9cb943e3058aa10980b9399d4d53a8d17220d60748a85f0c'
SOURCE_SHA = 'e0ed07a1954c40cfe3db67a5ef709e40708bd9244a6cf755b77ccc5a9031dfe7'
KIND = 'prepared_fixed_operating_reports_200_task_engineering'
TERMINAL_KIND = 'complete_fixed_operating_reports_200_task_engineering'


def _source_facade(native):
    return SimpleNamespace(**{**native._ns, **vars(native)})


def _namespace():
    data = UPSTREAM.read_bytes()
    if hashlib.sha256(data).hexdigest() != UPSTREAM_SHA:
        raise ValueError('The frozen task8 lifecycle changed')
    counts = {'source': 0, 'sha': 0, 'loader': 0, 'facade': 0, 'kind': 0, 'terminal': 0, 'title': 0, 'cache': 0}
    replacements = {
        'scripts/build_equity_income_group_source.py': ('scripts/build_operating_reports_200_source_revision2.py', 'source'),
        '1b6e3374a98e39a5708543af4e796026262d9d782a461d6ec29ad10d11ac3690': (SOURCE_SHA, 'sha'),
        '_equity_income_source_for_tasks': ('_fixed200_source_for_tasks', 'loader'),
        'prepared_equity_income_group_task_engineering': (KIND, 'kind'),
        'complete_equity_income_group_task_engineering': (TERMINAL_KIND, 'terminal'),
        'Equity-income FM/DBG engineering': ('Fixed heterogeneous report task engineering', 'title'),
    }

    class Domain(ast.NodeTransformer):
        def visit_Constant(self, node):
            if type(node.value) is str and node.value in replacements:
                node.value, key = replacements[node.value]; counts[key] += 1
            return node

        def visit_Expr(self, node):
            node = self.generic_visit(node)
            if ast.unparse(node) == '_spec.loader.exec_module(source)':
                counts['facade'] += 1
                return [node, *ast.parse('source = _new_source_facade(source)').body]
            return node

        def visit_Call(self, node):
            node = self.generic_visit(node)
            if isinstance(node.func, ast.Name) and node.func.id == 'verify_input_caches':
                node.keywords.append(ast.keyword(arg='definition', value=ast.Name('definition', ast.Load())))
                counts['cache'] += 1
            return node

    tree = Domain().visit(ast.parse(data))
    if counts != {'source': 1, 'sha': 1, 'loader': 1, 'facade': 1, 'kind': 1, 'terminal': 1, 'title': 1, 'cache': 4}:
        raise ValueError('The bounded task8 domain adaptation changed: ' + str(counts))
    namespace = {'__name__': '_isolated_fixed200_task8', '__file__': __file__, '_new_source_facade': _source_facade}
    exec(compile(ast.fix_missing_locations(tree), __file__, 'exec'), namespace)
    return namespace


_ns = _namespace(); source, STAGES = _ns['source'], _ns['STAGES']
reference, checked, read, write, require = (_ns[name] for name in ('reference', 'checked', 'read', 'write', 'require'))
transform, snapshot, compare_complete = (_ns[name] for name in ('transform', 'snapshot', 'compare_complete'))
_base_recipes = _ns['recipes']


def recipes():
    require(reference(UPSTREAM)['sha256'] == UPSTREAM_SHA, 'The frozen task8 ancestor changed')
    return {**_base_recipes(), str(UPSTREAM): reference(UPSTREAM)}


def forecast_keys(public):
    return {key for key, kind in source.schema.points(public)
            if kind != 'text' and key.split('/')[1].startswith(('2026', '2027', 'FY2026', 'FY2027'))}


def verify_definitions(path, definition, *, blank=False):
    book = source._book(path)
    try:
        require(book.sheetnames == definition['sheetnames'] and book.calculation.iterate is not True,
                'Task sheets or calculation policy changed')
        mask = set(definition['FM_mask_points'])
        wanted = {point: formula for point, formula in definition['formulas'].items() if not blank or point not in mask}
        formulas = {s.title + '!' + c.coordinate: c.value for s in book for c in s._cells.values() if c.data_type == 'f'}
        require(set(formulas) == set(wanted) and all(source.formula_signature(formulas[p]) == source.formula_signature(wanted[p])
                for p in wanted), 'Full task formula scope or definitions changed')
        literals = {s.title + '!' + c.coordinate: source.typed(c.value)
                    for s in book for c in s._cells.values() if c.value is not None and c.data_type != 'f'}
        require(literals == definition['literals'], 'Provided task facts, labels or nonapplicable values changed')
    finally:
        book.close()


def verify_input_caches(path, expected, *, blank, definition):
    observed = snapshot(path, expected)['values']; mask = set(definition['FM_mask_points'])
    require(not any(value['type'] == 'error' for value in observed.values()), 'The task input has a native error')
    for point, target in expected.items():
        if blank and point in mask:
            require(point not in observed, 'A forecast target must be absent from FM input')
        elif blank:
            require(observed.get(point) == target, 'Unmasked historical/report NA value changed')
        else:
            require(observed.get(point, {}).get('type') == target['type'], 'DBG report value type changed')
    if not blank:
        require(all(observed.get(point) != expected[point] for point in definition['DBG_root_points']),
                'Every declared entity root must have a real primary2dp value impact')


def prepare(source_manifest, output):
    output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT / 'outputs') and not output.exists(),
            'Use a fresh private task-engineering directory')
    actual = source.validate_source(source_manifest)
    require(actual['kind'] == source.SOURCE_KIND and actual['passed'] is True, 'A genuine complete fixed200 source3 is required')
    sf = source.validate_prepared(checked(actual['preparation']).parent)
    candidate, bindings, original, expected = (read(sf[key]) for key in ('candidate_manifest', 'bindings', 'definition', 'expected'))
    public = read(sf['specification']); plans = read(candidate['view_plans'])
    require(actual['source'] == actual['actual_calls'][-1]['output'] and len(expected) == 93510,
            'Use the complete genuine source3 goal')
    require(set(plans['FM_mask']) == forecast_keys(public) and len(plans['FM_mask']) == 62322,
            'Mask exactly the full applicable forecast business inventory')
    mask = [bindings['financial'][key]['sheet'] + '!' + bindings['financial'][key]['cell'] for key in plans['FM_mask']]
    faults = plans['DBG_faults']; roots = []
    require(len(faults) == 200 and {key.split('/')[0] for key in faults} == {e['id'] for e in public['entities']}
            and Counter(row['family'] for row in faults.values()) == {
                'associate_sign': 50, 'ratio_as_change': 50, 'money_scale': 50, 'wrong_reference_quarter': 50},
            'Keep all fixed200 entity roots and four predeclared families')
    for key, row in faults.items():
        point = row['sheet'] + '!' + row['cell']; binding = bindings['financial'][key]
        require(point in mask and (row['sheet'], row['cell']) == (binding['sheet'], binding['cell'])
                and source.formula_signature(original['formulas'][point]) == source.formula_signature(row['healthy_formula'])
                and source.formula_signature(row['healthy_formula']) != source.formula_signature(row['faulty_formula']),
                'A declared root must match its genuine healthy formula and forecast binding')
        roots.append({'key': key, 'sheet': row['sheet'], 'cell': row['cell'], 'before': row['healthy_formula'], 'after': row['faulty_formula']})
    require(len(set(mask)) == 62322 and set(mask) <= set(original['formulas']), 'Duplicate or non-formula forecast mask')
    root = roots[0]; root_point = (root['sheet'], root['cell']); point = '!'.join(root_point)
    definition = deepcopy(original); definition['FM_mask_points'] = sorted(mask)
    definition['DBG_root_points'] = sorted(row['sheet'] + '!' + row['cell'] for row in roots)
    require('ReadMe!A1' not in expected, 'The extra-change control must be outside all report targets')
    changes = {
        'FM_input': {tuple(p.rsplit('!', 1)): ('blank', None) for p in mask},
        'DBG_input': {(r['sheet'], r['cell']): ('formula', r['after']) for r in roots},
        'equivalent': {root_point: ('formula', '=0+(' + definition['formulas'][point].lstrip('=') + ')')},
        'FM_missed_root': {root_point: ('blank', None)},
        'DBG_missed_root': {root_point: ('formula', root['after'])},
        'extra_change': {('ReadMe', 'A1'): ('text', definition['literals']['ReadMe!A1']['value'] + ' [control]')},
    }
    output.mkdir(parents=True); planned = output / 'planned'; planned.mkdir(); goal = actual['source']
    inputs, edits, clearances, instructions = {}, {}, {}, {}
    for name, actions in changes.items():
        intermediate = planned / (name + '.edited.xlsx'); edits[name] = transform(checked(goal), intermediate, actions)
        target = planned / (name + '.xlsx'); clearances[name] = source.clear_all_formula_caches(intermediate, target)
        inputs[name] = reference(target)
    for mode in ('financial_modeling', 'debugging'):
        target = planned / (mode + '_instruction.md')
        source.shutil.copyfile(checked(candidate['views'][mode]['instruction']), target); instructions[mode] = reference(target)
    dbg = deepcopy(definition)
    for row in roots: dbg['formulas'][row['sheet'] + '!' + row['cell']] = row['after']
    verify_definitions(checked(inputs['FM_input']), definition, blank=True)
    verify_definitions(checked(inputs['DBG_input']), dbg)
    return write(output / 'preparation.json', {
        'kind': KIND, 'version': 1, 'source_manifest': reference(source_manifest['path'] if isinstance(source_manifest, dict) else source_manifest),
        'genuine_goal': goal, 'source_preparation': actual['preparation'], 'candidate_preparation': sf['candidate_manifest'],
        'specification': sf['specification'], 'source_definition': sf['definition'],
        'definition': write(output / 'definition.private.json', definition), 'expected': sf['expected'], 'bindings': sf['bindings'],
        'DBG_definition': write(output / 'DBG_definition.private.json', dbg), 'planned_inputs': inputs,
        'instruction_bytes': instructions, 'exact_edits': edits, 'all_formula_cache_clearances': clearances,
        'stage_order': list(STAGES), 'mode_order': ['financial_modeling', 'debugging'], 'required_actual_LO_calls': 8,
        'all_modes_and_controls_frozen_before_first_actual_call': True, 'reuse_genuine_source3_goal_and_two_stabilities': True,
        'independent_business_field_count': 93510, 'financial_target_count': 62322, 'DBG_formula_root_count': 200,
        'complete_D_counts_pending_actual_input_calculation': True,
        'runtime_profile': sf['runtime_profile'], 'runtime_profile_value': sf['runtime_profile_value'], 'recipe': recipes(),
        'actual_LO_calls': 0, 'model_calls': 0, 'qualified': False, 'normal_all12_QA_passed': False})


def validate_prepared(output):
    f = read(Path(output) / 'preparation.json')
    require(f['kind'] == KIND and f['version'] == 1 and f['recipe'] == recipes()
            and f['stage_order'] == list(STAGES) and f['required_actual_LO_calls'] == 8
            and f['all_modes_and_controls_frozen_before_first_actual_call'] is True
            and f['actual_LO_calls'] == f['model_calls'] == 0 and f['qualified'] is False
            and f['normal_all12_QA_passed'] is False, 'The fixed task8 scope or recipe changed')
    for key in ('source_manifest', 'genuine_goal', 'source_preparation', 'candidate_preparation', 'specification',
                'source_definition', 'definition', 'expected', 'bindings', 'DBG_definition', 'runtime_profile'):
        checked(f[key])
    for refs in (f['planned_inputs'], f['instruction_bytes']):
        for record in refs.values(): checked(record)
    actual, sf, candidate = (read(f[key]) for key in ('source_manifest', 'source_preparation', 'candidate_preparation'))
    require(actual['kind'] == source.SOURCE_KIND and actual['passed'] is True and actual['source'] == f['genuine_goal']
            and actual['preparation'] == f['source_preparation'] and sf['candidate_manifest'] == f['candidate_preparation']
            and sf['specification'] == f['specification'] and sf['definition'] == f['source_definition']
            and sf['bindings'] == f['bindings'] and sf['expected'] == f['expected']
            and sf['runtime_profile'] == f['runtime_profile'] and sf['runtime_profile_value'] == f['runtime_profile_value'],
            'Task artifacts must bind the genuine fixed200 source3 originals')
    public = read(f['specification']); plans = read(candidate['view_plans']); bindings = read(f['bindings'])
    require(source.schema.canonical_sha256(public) == source.SPECIFICATION_SHA256,
            'The approved fixed200 source specification changed')
    mask = sorted(bindings['financial'][key]['sheet'] + '!' + bindings['financial'][key]['cell'] for key in plans['FM_mask'])
    roots = sorted(row['sheet'] + '!' + row['cell'] for row in plans['DBG_faults'].values())
    require(set(plans['FM_mask']) == forecast_keys(public) and len(mask) == len(set(mask)) == 62322
            and len(roots) == len(set(roots)) == 200 and len(read(f['expected'])) == 93510
            and f['financial_target_count'] == 62322 and f['independent_business_field_count'] == 93510
            and f['DBG_formula_root_count'] == 200, 'Full forecast/business/root scope changed')
    definition = read(f['definition']); original = read(f['source_definition'])
    require(definition == {**original, 'FM_mask_points': mask, 'DBG_root_points': roots},
            'Task masks and primary roots must extend the original source definition only')
    dbg = deepcopy(definition)
    for row in plans['DBG_faults'].values(): dbg['formulas'][row['sheet'] + '!' + row['cell']] = row['faulty_formula']
    require(read(f['DBG_definition']) == dbg, 'DBG formula definitions differ from the frozen entity fault plan')
    verify_definitions(checked(f['planned_inputs']['FM_input']), definition, blank=True)
    verify_definitions(checked(f['planned_inputs']['DBG_input']), dbg)
    for mode, record in f['instruction_bytes'].items():
        original_brief = candidate['views'][mode]['instruction']
        require(record['sha256'] == original_brief['sha256'] and record['bytes'] == original_brief['bytes'],
                'Keep the original business brief')
    require(source.runtime(checked(f['runtime_profile'])) == (f['runtime_profile'], f['runtime_profile_value']),
            'The source/task resource contract changed')
    for name, record in f['planned_inputs'].items():
        clearance = f['all_formula_cache_clearances'][name]; edit = f['exact_edits'][name]
        require(clearance['output'] == record and clearance['source'] == edit['output'] and edit['source'] == f['genuine_goal']
                and source._formula_cache_count(checked(record)) == 0,
                'Every actual first/control input must bind its original cache-clear transformation')
    return f


_ns.update(recipes=recipes, verify_definitions=verify_definitions, verify_input_caches=verify_input_caches,
           prepare=prepare, validate_prepared=validate_prepared)
execute_prepared = _ns['execute_prepared']
validate_completed = _ns['validate_completed']
main = _ns['main']


if __name__ == '__main__': raise SystemExit(main())

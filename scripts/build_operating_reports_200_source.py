#!/usr/bin/env python3
"""Cold three-calculation admission for the fixed heterogeneous reports."""
from __future__ import annotations

import argparse
import ast
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.workbook.operating_reports_200 import schema, raw, oracle_a, oracle_b, excel, audit as business

UPSTREAM = ROOT / 'scripts/build_equity_income_group_source.py'
UPSTREAM_SHA = '1b6e3374a98e39a5708543af4e796026262d9d782a461d6ec29ad10d11ac3690'
KIND = 'prepared_fixed_operating_reports_200_cold_source'
SOURCE_KIND = 'independently_checked_fixed_operating_reports_200_source'
SPECIFICATION_SHA256 = '4eaf468d8d7c0764f1cb70cbba7aa60a05c512bb00d0e9cad6137503f080ee40'
BRIEFS = {
    'financial_modeling': 'Complete the FY2026 and FY2027 reports for all listed businesses, their management divisions and the master portfolio. Use the supplied FY2025 actuals, opening balances and business assumptions. The report labels and Read Me state the reporting conventions. Preserve supplied facts, historical reports and nonapplicable fields, and make the forecast reports consistent. The businesses are hypothetical.\n',
    'debugging': 'Audit and repair the FY2026 and FY2027 reports for all listed businesses, their management divisions and the master portfolio. Use the supplied FY2025 actuals, opening balances and business assumptions. The report labels and Read Me state the reporting conventions. Preserve supplied facts, historical reports and nonapplicable fields, and make the forecast reports consistent. The businesses are hypothetical.\n',
}


def _lifecycle_namespace():
    data = UPSTREAM.read_bytes()
    if hashlib.sha256(data).hexdigest() != UPSTREAM_SHA:
        raise ValueError('The frozen source3 lifecycle changed')
    counts = {'import': 0, 'validate': 0, 'title': 0, 'events': 0}

    class Domain(ast.NodeTransformer):
        def visit_ImportFrom(self, node):
            if node.module == 'sheets_factory.workbook.equity_income_group':
                node.module = 'sheets_factory.workbook.operating_reports_200'
                node.names = [ast.alias(name='schema', asname='spec'), ast.alias(name='oracle_a', asname='decimal_oracle'),
                              ast.alias(name='oracle_b', asname='fraction_oracle'), ast.alias(name='excel')]
                counts['import'] += 1
            return node

        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == 'spec' and node.attr == 'validate':
                node.attr = 'validate_spec'; counts['validate'] += 1
            return self.generic_visit(node)

        def visit_Constant(self, node):
            if node.value == 'Equity-income cold-start source':
                node.value = 'Heterogeneous operating reports cold-start source'; counts['title'] += 1
            elif node.value in ('equity_source.stage_started', 'equity_source.stage_terminal'):
                node.value = node.value.replace('equity_source.', 'operating_reports_200_source.'); counts['events'] += 1
            return node

    tree = Domain().visit(ast.parse(data))
    if counts != {'import': 1, 'validate': 3, 'title': 1, 'events': 2}:
        raise ValueError('The source3 lifecycle boundaries changed: ' + str(counts))
    namespace = {'__name__': '_isolated_operating_reports_200_source', '__file__': __file__}
    exec(compile(ast.fix_missing_locations(tree), __file__, 'exec'), namespace)
    namespace.update(KIND=KIND, SOURCE_KIND=SOURCE_KIND)
    return namespace


_ns = _lifecycle_namespace()
reference, checked, read, write, require, typed = (_ns[name] for name in ('reference', 'checked', 'read', 'write', 'require', 'typed'))
PROFILE, STAGES, runtime = (_ns[name] for name in ('PROFILE', 'STAGES', 'runtime'))
_base_recipes = _ns['recipes']


def recipes():
    require(reference(UPSTREAM)['sha256'] == UPSTREAM_SHA, 'The frozen source3 ancestor changed')
    paths = [UPSTREAM, Path(business.__file__), Path(raw.__file__), raw.DESIGN,
             ROOT / 'config/operating_reports_200_public_spec_schema_v1.json',
             ROOT / 'config/operating_reports_200_oracle_result_schema_v1.json']
    return {**_base_recipes(), **{str(p.resolve()): reference(p) for p in paths}}


def target(value):
    if value['type'] != 'number':
        return value
    number = Decimal(value['value'])
    return {'type': 'number', 'value': '0' if not number else format(number.normalize(), 'f')}


def crosscheck(public, bindings):
    schema.validate_spec(public)
    left, right = oracle_a.solve(public), oracle_b.solve(public)
    comparison = business.compare(public, left, right)
    require(comparison['passed'] and not comparison['differences'], 'Full independent business values disagree')
    declared = dict(schema.points(public)); rows = bindings['financial']
    require(set(rows) == set(declared), 'Complete financial binding keys required')
    expected = {}
    for key, row in rows.items():
        point = row['sheet'] + '!' + row['cell']
        require(point not in expected and row['role'] == ('given_NA' if declared[key] == 'text' else 'report'),
                'Duplicate report position or incorrect NA role')
        expected[point] = target(right['typed_2dp_values'][key])
    return expected, comparison


def provided_facts(public):
    """Reconstruct only the declared input inventory, without report arithmetic."""
    result = {}
    for entity in public['entities']:
        prefix = entity['id'] + '/'
        result.update({prefix + 'opening_' + key: value for key, value in entity['opening'].items()})
        result.update({prefix + key: entity[key] for key in ('direct_cost_rate', 'annual_interest_rate', 'parent_tax_rate')})
        for period in schema.QUARTERS:
            result[prefix + 'actual_sales/' + period] = entity['actual_sales'].get(period, schema.FORECAST_ACTUAL_NA)
            result[prefix + 'forecast_sales/' + period] = entity['forecast_sales'].get(period, schema.ACTUAL_DRIVER_NA)
            for key in ('cash_opex', 'associate_results'):
                result[prefix + key + '/' + period] = entity[key][period]
    return result


def source_definition(path, bindings, public):
    import openpyxl
    book = openpyxl.load_workbook(path, data_only=False)
    formulas, literals = {}, {}
    try:
        require(book.calculation.iterate is not True and all(s.sheet_state == 'visible' for s in book),
                'Reports must remain visible and non-circular')
        paragraphs = public['public_policy'].strip().split('\n\n')
        require([book['ReadMe'].cell(i + 3, 1).value for i in range(len(paragraphs))] == paragraphs,
                'All public business policies must be present unchanged')
        for sheet in book:
            for cell in sheet._cells.values():
                point = sheet.title + '!' + cell.coordinate
                if cell.data_type == 'f': formulas[point] = cell.value
                elif cell.value is not None: literals[point] = typed(cell.value)
        rows = bindings['financial']; scope = {v['sheet'] + '!' + v['cell'] for v in rows.values()}
        expected_formulas = {v['sheet'] + '!' + v['cell'] for v in rows.values() if v['role'] == 'report'}
        require(set(formulas) == expected_formulas and all(len(value) <= 8192 for value in formulas.values()),
                'Full bounded source formula inventory changed')
        kinds = dict(schema.points(public))
        require(set(rows) == set(kinds) and len(scope) == len(rows), 'Every business field needs a unique cell')
        given = bindings['provided_facts']; facts = provided_facts(public)
        require(set(given) == set(facts), 'All original local input facts must be bound')
        provided = {}
        for key, fact in given.items():
            point = fact['sheet'] + '!' + fact['cell']; value = facts[key]
            require(fact['value'] == value and point not in provided and point in literals,
                    'Provided input binding changed or duplicates another fact')
            actual = literals[point]
            wanted = {'type': 'text', 'value': value} if value.startswith('n/a') else {'type': 'number', 'value': value}
            require(actual == wanted if wanted['type'] == 'text' else
                    actual['type'] == 'number' and Fraction(actual['value']) == Fraction(value),
                    'The worksheet input differs from its exact public decimal')
            provided[point] = actual
        context = bindings['provided_context']
        require(set(context) == set(literals) - scope, 'Every provided context cell must be bound')
        for point, row in context.items():
            sheet, cell = point.rsplit('!', 1); actual = book[sheet][cell]
            require(row['sheet'] == sheet and row['cell'] == cell and row['cell_type'] == actual.data_type
                    and row['number_format'] == actual.number_format
                    and row['hyperlink'] == (actual.hyperlink.target if actual.hyperlink else None),
                    'Public context identity, format or hyperlink changed')
            if point not in provided:
                require(typed(row['value']) == literals[point], 'Public label or context value changed')
        return {'sheetnames': book.sheetnames, 'formulas': formulas, 'literals': literals,
                'provided_financial_inputs': provided, 'financial_scope': sorted(scope),
                'non_circular': True, 'specification_sha256': schema.canonical_sha256(public)}
    finally:
        book.close()


def _formula_cache_count(path):
    with ZipFile(path) as archive:
        return sum(cell.find('{*}f') is not None and cell.find('{*}v') is not None
                   for name in archive.namelist() if name.startswith('xl/worksheets/sheet') and name.endswith('.xml')
                   for cell in ET.fromstring(archive.read(name)).findall('{*}sheetData/{*}row/{*}c'))


def audit_workbook(path, definition, expected, *, empty_caches=False):
    import openpyxl
    book = openpyxl.load_workbook(path, data_only=False)
    values = openpyxl.load_workbook(path, data_only=True)
    formulas, observed, errors, mismatches = {}, {}, [], []
    try:
        require(book.sheetnames == values.sheetnames == definition['sheetnames'] and book.calculation.iterate is not True,
                'Source worksheet or calculation policy changed')
        for sheet in book:
            for cell in sheet._cells.values():
                if cell.data_type == 'f': formulas[sheet.title + '!' + cell.coordinate] = cell.value
        require(set(formulas) == set(definition['formulas']) and all(
            _ns['formula_signature'](value) == _ns['formula_signature'](definition['formulas'][point])
            for point, value in formulas.items()), 'Full formula definitions changed')
        for sheet in values:
            for cell in sheet._cells.values():
                point = sheet.title + '!' + cell.coordinate
                if cell.data_type == 'e': errors.append({'point': point, 'error': cell.value})
                if cell.value is not None: observed[point] = typed(cell.value, financial=point in expected)
        for point, wanted in expected.items():
            actual = observed.get(point, {'type': 'empty', 'value': ''})
            desired = {'type': 'empty', 'value': ''} if empty_caches and point in formulas else wanted
            if actual != desired: mismatches.append({'point': point, 'expected': desired, 'actual': actual})
        for point, wanted in definition['literals'].items():
            if observed.get(point) != wanted: mismatches.append({'point': point, 'claim': 'Supplied context changed'})
        require(set(observed) == set(definition['literals']) | (set() if empty_caches else set(expected)),
                'Unexpected missing or extra populated positions')
        if empty_caches: require(_formula_cache_count(path) == 0, 'Formula caches must be absent before source1')
        return {'kind': 'full_fixed_operating_reports_200_native_audit', 'passed': not mismatches and not errors,
                'workbook': reference(path), 'all_financial_fields_checked': len(expected),
                'all_derived_values_checked': len(expected), 'physical_formulas_checked': len(formulas),
                'provided_financial_input_fields_checked': len(definition['provided_financial_inputs']),
                'protected_public_literals_checked': len(definition['literals']),
                'mismatches': mismatches, 'native_errors': errors, 'all_formula_caches_empty': empty_caches,
                'normalization': 'Financial numerics2dp; supplied construction context exact; booleans distinct',
                'qualified': False}
    finally:
        book.close(); values.close()


def _inputs(specification, emission, left, right):
    specification, emission, left, right = map(lambda p: Path(p).absolute(), (specification, emission, left, right))
    public = schema.validate_spec(read(specification))
    require(public['dimension_mode'] == 'production' and len(public['entities']) == 200,
            'Actual source admission requires the fixed200 production inputs')
    require(schema.canonical_sha256(public) == SPECIFICATION_SHA256,
            'The original fixed200 raw contract changed')
    generated = read(specification.parent / 'receipt.json')
    require(generated['kind'] == 'fixed_operating_reports_200_input_generation'
            and generated['specification'] == reference(specification)
            and generated['canonical_specification_sha256'] == schema.canonical_sha256(public)
            and generated['financial_forwards'] == generated['workbooks'] == generated['services'] == 0,
            'Bind the original pre-financial raw generation receipt')
    emitted = read(emission / 'receipt.json'); census = business.census(public, emission)
    require(emitted['kind'] == 'pure_operating_reports_200_emission'
            and emitted['specification_sha256'] == schema.canonical_sha256(public)
            and emitted['report_positions'] == 93510 and emitted['formulas'] == 88676
            and emitted['sheets'] == 211 and emitted['nonempty'] == 148176
            and emitted['native_calculations'] == 0 and emitted['source_caches_seeded'] is False
            and census['passed'] is True and census['report_positions'] == 93510
            and census['FM_mask'] == 62322 and census['DBG_roots'] == 200,
            'Use the complete unverified fixed200 emission, not a partial or cached specimen')
    a, b = read(left), read(right); comparison = business.compare(public, a, b)
    require(comparison['passed'] and not comparison['differences'], 'Retained full independent A/B proof failed')
    return public, read(emission / 'private_bindings.json'), a, b, comparison, census


def prepare(specification, emission, left, right, output, *, profile=PROFILE):
    output = Path(output).absolute()
    require(output == output.resolve() and output.is_relative_to(ROOT / 'outputs') and not output.exists(),
            'Use a fresh private source directory')
    public, bindings, a, b, retained, census = _inputs(specification, emission, left, right)
    expected, comparison = crosscheck(public, bindings)
    require(comparison == retained and all(target(b['typed_2dp_values'][key]) == expected[row['sheet'] + '!' + row['cell']]
            for key, row in bindings['financial'].items()), 'Cold independent results differ from retained original results')
    source_path = Path(emission).absolute() / 'source_uncalculated.xlsx'
    definition = source_definition(source_path, bindings, public)
    require(len(expected) == 93510 and len(definition['formulas']) == 88676
            and len(definition['provided_financial_inputs']) == 11200, 'Incomplete complete source scope')
    profile_ref, profile_value = runtime(profile); before = recipes()
    output.mkdir(parents=True); cold = output / 'cold_start.xlsx'
    clearance = _ns['clear_all_formula_caches'](source_path, cold)
    require(clearance['all_formula_caches_cleared'] == 88676, 'Clear every derived formula cache')
    report = audit_workbook(cold, definition, expected, empty_caches=True)
    require(report['passed'], 'The cold source must preserve all inputs and NA report fields')
    instructions = {}
    for mode, text in BRIEFS.items():
        p = output / (mode + '_instruction.md'); p.write_text(text)
        instructions[mode] = {'instruction': reference(p)}
    refs = {name: reference(Path(emission).absolute() / filename) for name, filename in {
        'source': 'source_uncalculated.xlsx', 'FM_input': 'financial_modeling_input.xlsx',
        'DBG_input': 'debugging_input.xlsx', 'bindings': 'private_bindings.json',
        'view_plans': 'view_plans.json', 'emission_receipt': 'receipt.json'}.items()}
    candidate = write(output / 'candidate.private.json', {
        'kind': 'prepared_unverified_fixed_operating_reports_200_pair', 'version': 1,
        'specification': reference(specification), 'raw_generation': reference(Path(specification).parent / 'receipt.json'),
        'retained_A': reference(left), 'retained_B': reference(right), **refs,
        'views': instructions, 'qualified': False, 'actual_LO_calls': 0, 'model_calls': 0})
    private = {
        'definition': write(output / 'definition.private.json', definition),
        'expected': write(output / 'expected.private.json', expected),
        'independent_comparison': write(output / 'independent_AB_comparison.json', comparison),
        'cold_start_audit': write(output / 'cold_start_audit.json', report),
        'retained_comparison': write(output / 'retained_comparison.json', retained),
        'pure_emission_census': write(output / 'pure_emission_census.json', census)}
    require(before == recipes(), 'Implementation changed during source preparation')
    return write(output / 'preparation.json', {
        'kind': KIND, 'version': 1, 'candidate_manifest': candidate, 'specification': reference(specification),
        'bindings': refs['bindings'], 'specification_sha256': schema.canonical_sha256(public),
        'cold_start': reference(cold), **private, 'cache_clearance': clearance,
        'runtime_profile': profile_ref, 'runtime_profile_value': profile_value, 'recipe': before,
        'stage_order': list(STAGES), 'required_actual_LO_calls': 3, 'cold_start_is_unseeded': True,
        'actual_LO_calls': 0, 'model_calls': 0, 'qualified': False})


def validate_prepared(output):
    f = read(Path(output) / 'preparation.json')
    require(f['kind'] == KIND and f['version'] == 1 and f['recipe'] == recipes()
            and f['stage_order'] == list(STAGES) and f['required_actual_LO_calls'] == 3
            and f['cold_start_is_unseeded'] is True and f['actual_LO_calls'] == f['model_calls'] == 0
            and f['qualified'] is False, 'The frozen source3 scope or recipe changed')
    for key in ('candidate_manifest', 'specification', 'bindings', 'cold_start', 'definition', 'expected',
                'independent_comparison', 'cold_start_audit', 'runtime_profile', 'retained_comparison', 'pure_emission_census'):
        checked(f[key])
    require(runtime(checked(f['runtime_profile'])) == (f['runtime_profile'], f['runtime_profile_value']),
            'The source runtime contract changed')
    candidate = read(f['candidate_manifest'])
    for key in ('specification', 'raw_generation', 'retained_A', 'retained_B', 'source', 'FM_input',
                'DBG_input', 'bindings', 'view_plans', 'emission_receipt'):
        checked(candidate[key])
    for view in candidate['views'].values(): checked(view['instruction'])
    public, bindings, a, b, comparison, census = _inputs(
        checked(candidate['specification']), checked(candidate['source']).parent,
        checked(candidate['retained_A']), checked(candidate['retained_B']))
    require(candidate['kind'] == 'prepared_unverified_fixed_operating_reports_200_pair'
            and candidate['specification'] == f['specification'] and candidate['bindings'] == f['bindings']
            and candidate['raw_generation'] == reference(Path(f['specification']['path']).parent / 'receipt.json')
            and all(Path(candidate[key]['path']).parent == Path(candidate['source']['path']).parent
                    for key in ('FM_input', 'DBG_input', 'bindings', 'view_plans', 'emission_receipt'))
            and candidate['qualified'] is False and candidate['actual_LO_calls'] == candidate['model_calls'] == 0,
            'Candidate/source input originals differ')
    definition = source_definition(checked(candidate['source']), bindings, public)
    expected = {row['sheet'] + '!' + row['cell']: target(b['typed_2dp_values'][key])
                for key, row in bindings['financial'].items()}
    require(definition == read(f['definition']) and expected == read(f['expected'])
            and comparison == read(f['retained_comparison']) == read(f['independent_comparison'])
            and census == read(f['pure_emission_census']), 'Independent full targets or source definition changed')
    report = audit_workbook(checked(f['cold_start']), definition, expected, empty_caches=True)
    require(report['passed'] and report == read(f['cold_start_audit'])
            and f['cache_clearance']['source'] == candidate['source']
            and f['cache_clearance']['output'] == f['cold_start']
            and f['cache_clearance']['all_formula_caches_cleared'] == 88676,
            'The original cold cache clearance or full audit changed')
    require(f['specification_sha256'] == schema.canonical_sha256(public), 'Source specification identity changed')
    for mode, text in BRIEFS.items():
        require(checked(candidate['views'][mode]['instruction']).read_text() == text,
                'The public business brief changed')
    return f


_ns.update(recipes=recipes, crosscheck=crosscheck, source_definition=source_definition,
           audit_workbook=audit_workbook, prepare=prepare, validate_prepared=validate_prepared)
execute_prepared = _ns['execute_prepared']
validate_source = _ns['validate_source']
validate_completed = validate_source
compare_typed = _ns['compare_typed']


def main(argv=None):
    parser = argparse.ArgumentParser(__doc__); sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    for name in ('spec', 'emission', 'oracle-a', 'oracle-b', 'output'): p.add_argument('--' + name, required=True, type=Path)
    for name in ('validate', 'run'):
        p = sub.add_parser(name); p.add_argument('--prepared', required=True, type=Path)
    p = sub.add_parser('validate-source'); p.add_argument('--manifest', required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == 'prepare': result = prepare(args.spec, args.emission, args.oracle_a, args.oracle_b, args.output)
    elif args.command == 'validate': result = validate_prepared(args.prepared)
    elif args.command == 'run': result = execute_prepared(args.prepared)
    else: result = validate_source(args.manifest)
    print(json.dumps(result)); return 0


if __name__ == '__main__': raise SystemExit(main())

"""Pure, predeclared whole-class DBG plans over the unchanged C00 source."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path

from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils import quote_sheetname
from openpyxl.utils.cell import range_to_tuple

from . import audit, schema

SPECIFICATION_SHA256 = '4eaf468d8d7c0764f1cb70cbba7aa60a05c512bb00d0e9cad6137503f080ee40'
SOURCE_MANIFEST_SHA256 = 'beee954067fa061616a65b045ff176bc3e052726931f5788c93ea71deb032fca'
GOAL_SHA256 = '5f38a984cf7fc689e030602aab0f0bc95a51b05d54711d4a79207f04445936ef'
TASK8_SHA256 = 'fba1c365aeead7902953dd1b8c6877ece8687fd35e757ec3e5286a53e3cf67aa'
SIGN_EVIDENCE_SHA256 = '7bfd4c102129c41877a9e20ac84fc3cd6d87a4aef126c575748694c351f30c73'
KIND = 'prepared_operating_reports_200_full_class_debug_variants'
PLAN_KIND = 'pure_operating_reports_200_full_class_debug_view_plan'
PROOF_KIND = 'pure_operating_reports_200_full_class_debug_proof'
VARIANTS = ('S800', 'SG4000')
COUNTS = {'S800': 800, 'SG4000': 4000}
FORECAST = schema.QUARTERS[4:]
RATE_SCALE = {'fraction': 1, 'percent_units': 100, 'basis_points': 10000}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reference(value):
    path = Path(value).absolute()
    require(path == path.resolve() and path.is_file() and not path.is_symlink(), 'Use an immutable regular artifact')
    data = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def read(value):
    row = value if isinstance(value, dict) else reference(value)
    require(set(row) == {'path', 'sha256', 'bytes'} and reference(row['path']) == row, 'A retained artifact changed')
    return json.loads(Path(row['path']).read_text())


def recipes():
    return {row['path']: row for row in (reference(path) for path in (__file__, schema.__file__, audit.__file__))}


def _physical(binding):
    return binding['sheet'] + '!' + binding['cell']


def _ref(binding):
    return quote_sheetname(binding['sheet']) + '!' + binding['cell']


def _quant(number):
    number = Fraction(number)
    scaled = abs(number)*100 + Fraction(1, 2)
    integer = scaled.numerator // scaled.denominator
    return ('-' if number < 0 and integer else '') + f'{integer//100}.{integer%100:02d}'


def _wrong_sign(core, total):
    return Fraction(core) - Fraction(total)


def _growth(current, base, scale):
    current, base = Fraction(current), Fraction(base)
    require(current > 0 and base > 0 and scale in RATE_SCALE.values(), 'Growth requires positive revenue and a declared rate unit')
    return (current/base - 1)*scale, current/base*scale


def _classes(public, variant):
    require(variant in VARIANTS, 'Use one of the two predeclared variants')
    for entity in public['entities']:
        identity = entity['id']
        if entity['statement_sign'] == 'positive_deductions':
            for period in FORECAST:
                yield f'{identity}/{period}/reported_associate_line', 'associate_presentation_sign'
        if variant == 'SG4000':
            for period in FORECAST:
                for field in ('yoy_percent', 'qoq_percent'):
                    yield f'{identity}/{period}/{field}', 'ratio_as_quarterly_change'


def _validate_inputs(public, bindings, definition, original_plans):
    schema.validate_spec(public)
    digest = schema.canonical_sha256(public)
    require(public['dimension_mode'] == 'toy' or digest == SPECIFICATION_SHA256, 'Only the fixed C00 production contract is supported')
    expected = dict(schema.points(public))
    require(bindings['specification_sha256'] == definition['specification_sha256'] == digest
        and set(bindings['financial']) == set(expected), 'Keep the complete original financial binding inventory')
    physical = [_physical(row) for row in bindings['financial'].values()]
    require(len(physical) == len(set(physical)), 'Financial bindings must be physically unique')
    given = {_physical(row) for row in bindings['provided_facts'].values()}
    given |= {_physical(row) for row in bindings['provided_context'].values()}
    require(not set(physical) & given, 'Financial outputs cannot overlap supplied facts or public context')
    require(original_plans['kind'] == 'pure_operating_reports_200_view_plans' and original_plans['version'] == 1
        and original_plans['actual_D_unknown'] is True and original_plans['native_calls'] == 0,
        'Preserve the exact original pure rendered view plan')
    mask = [key for key, kind in expected.items() if kind != 'text'
        and key.split('/')[1].startswith(('2026', '2027', 'FY2026', 'FY2027'))]
    require(len(original_plans['FM_mask']) == len(set(original_plans['FM_mask']))
        and set(original_plans['FM_mask']) == set(mask), 'The complete original FM mask must remain unchanged')
    require(set(definition['formulas']) | set(definition['literals']) >= set(physical), 'Healthy source definitions are incomplete')


def design(public, bindings, healthy_definition, original_plans, variant):
    """Return a whole-class plan, never a workbook or an expected-value cache."""
    _validate_inputs(public, bindings, healthy_definition, original_plans)
    entities = {e['id']: e for e in public['entities']}
    financial = bindings['financial']
    faults = {}
    kinds = dict(schema.points(public))
    for key, family in _classes(public, variant):
        identity, period, field = key.split('/')
        binding = financial[key]
        point = _physical(binding)
        require(kinds[key] == 'number' and binding['role'] == 'report'
            and point in healthy_definition['formulas'] and point not in healthy_definition['literals'],
            'A whole-class root must be an applicable forecast formula, never an NA or given literal')
        ref = lambda p, f: _ref(financial[f'{identity}/{p}/{f}'])
        if family == 'associate_presentation_sign':
            wrong = '=' + ref(period, 'core_net_income') + '-' + ref(period, 'net_income')
        else:
            index = schema.QUARTERS.index(period)
            base = schema.QUARTERS[index-(4 if field == 'yoy_percent' else 1)]
            scale = RATE_SCALE[entities[identity]['rate_unit']]
            wrong = '=' + ref(period, 'revenue') + '/' + ref(base, 'revenue') + ('*'+str(scale) if scale != 1 else '')
        healthy = healthy_definition['formulas'][point]
        require(healthy.startswith('=') and wrong != healthy, 'A declared root must change its actual healthy definition')
        faults[key] = {'family': family, 'sheet': binding['sheet'], 'cell': binding['cell'],
            'healthy_formula': healthy, 'faulty_formula': wrong}
    if public['dimension_mode'] == 'production':
        require(len(faults) == COUNTS[variant], 'Do not filter, replace or resample any member of a complete class')
    return {'kind': PLAN_KIND, 'version': 1, 'variant_id': variant,
        'FM_mask': deepcopy(original_plans['FM_mask']), 'DBG_faults': faults,
        'actual_D_unknown': True, 'native_calls': 0,
        'policy_or_given_fact_changes': 0, 'qualified': False}


def _outside_dependents(definition, faults):
    """Prove these report leaves have no downstream formulas outside the roots."""
    root_points = {_physical(row) for row in faults.values()}
    roots_by_sheet = {}
    from openpyxl.utils.cell import coordinate_to_tuple
    for point in root_points:
        sheet, cell = point.rsplit('!', 1)
        row, column = coordinate_to_tuple(cell)
        roots_by_sheet.setdefault(sheet, set()).add((column, row))
    outside = []
    for destination, formula in definition['formulas'].items():
        if destination in root_points:
            continue
        for token in Tokenizer(formula).items:
            if token.type != 'OPERAND' or token.subtype != 'RANGE':
                continue
            try:
                sheet, (min_c, min_r, max_c, max_r) = range_to_tuple(token.value)
            except (ValueError, TypeError) as error:
                raise ValueError('Unsupported source reference prevents a complete leaf proof: '+token.value) from error
            # openpyxl retains doubled apostrophes in a quoted sheet token.
            sheet = sheet.replace("''", "'")
            if any(min_c <= col <= max_c and min_r <= row <= max_r for col, row in roots_by_sheet.get(sheet, ())):
                outside.append({'destination': destination, 'reference': token.value})
    return outside


def prove(public, bindings, healthy_definition, original_plans, plan, retained_A, retained_B):
    require(plan == design(public, bindings, healthy_definition, original_plans, plan['variant_id']),
        'Only the complete predeclared classes and formulas are permitted')
    comparison = audit.compare(public, retained_A, retained_B)
    require(comparison['passed'], 'The complete retained independent A/B values disagree')
    raw = retained_A['raw_cell_exact_values']; witnesses = []
    entities = {e['id']: e for e in public['entities']}
    def value(key):
        require(raw[key]['kind'] == 'rational', 'Every fault root and dependency requires an exact retained rational')
        return Fraction(raw[key]['value'])
    for key, row in plan['DBG_faults'].items():
        identity, period, field = key.split('/')
        if row['family'] == 'associate_presentation_sign':
            core = value(f'{identity}/{period}/core_net_income')
            total = value(f'{identity}/{period}/net_income')
            associate = value(f'{identity}/{period}/associate_income')
            healthy, wrong = associate, _wrong_sign(core, total)
            require(total-core == associate and healthy == Fraction(entities[identity]['associate_results'][period])
                and wrong == -healthy, 'The supplied income-positive result and exact net-income reconciliation differ')
            dependency_values = {'core_net_income': str(core), 'net_income': str(total), 'associate_income': str(associate)}
        else:
            index = schema.QUARTERS.index(period)
            base = schema.QUARTERS[index-(4 if field == 'yoy_percent' else 1)]
            current, denominator = value(f'{identity}/{period}/revenue'), value(f'{identity}/{base}/revenue')
            scale = RATE_SCALE[entities[identity]['rate_unit']]
            healthy, wrong = _growth(current, denominator, scale)
            require(wrong-healthy == scale and wrong > 0, 'The full positive period-ratio offset must match the declared rate unit')
            dependency_values = {'current_revenue': str(current), 'comparison_period': base,
                'comparison_revenue': str(denominator), 'rate_unit': entities[identity]['rate_unit'], 'ratio_offset': scale}
        expected = retained_A['typed_2dp_values'][key]
        require(healthy == value(key) and expected == retained_B['typed_2dp_values'][key]
            and expected == {'type': 'number', 'value': _quant(healthy)} and _quant(wrong) != expected['value'],
            'Every root must have a nonzero exact primary-value impact; never silently omit a zero-impact root')
        witnesses.append({'key': key, 'family': row['family'], 'healthy_exact': str(healthy),
            'wrong_exact': str(wrong), 'healthy_primary': expected,
            'wrong_primary': {'type': 'number', 'value': _quant(wrong)}, 'dependency_values': dependency_values})
    outside = _outside_dependents(healthy_definition, plan['DBG_faults'])
    require(not outside, 'Unexpected downstream formulas require expanded independent coverage before use')
    roots = plan['DBG_faults']
    return {'kind': PROOF_KIND, 'version': 1, 'variant_id': plan['variant_id'], 'passed': True,
        'specification_sha256': schema.canonical_sha256(public), 'complete_original_A_B_comparison': comparison,
        'root_count': len(roots), 'roots_by_family': dict(Counter(r['family'] for r in roots.values())),
        'roots_by_layout': dict(Counter(entities[k.split('/')[0]]['layout'] for k in roots)),
        'all_roots_exact_nonzero_primary_impact': True, 'outside_root_formula_dependents': outside,
        'exact_arithmetic_predicted_D_count': len(roots), 'actual_native_D_or_error_absence_proved': False,
        'unchanged_full_original_business_fields': len(raw), 'FM_mask_unchanged': True,
        'goal_public_policy_facts_NA_and_history_unchanged': True, 'witnesses': witnesses,
        'new_financial_forwards': 0, 'LO_calls': 0, 'model_calls': 0, 'workbooks_written': 0,
        'actual_D_unknown': True, 'difficulty_validated': False, 'qualified': False}


def _ancestry(source_ref, task_ref, sign_ref):
    require(source_ref['sha256'] == SOURCE_MANIFEST_SHA256 and task_ref['sha256'] == TASK8_SHA256
        and sign_ref['sha256'] == SIGN_EVIDENCE_SHA256, 'Use the exact original healthy C00 source, completed task and sign-failure evidence')
    source, task = read(source_ref), read(task_ref)
    read(sign_ref)
    require(source['kind'] == 'independently_checked_fixed_operating_reports_200_source_revision2'
        and source['passed'] is True and source['version'] == 1
        and source['actual_LO_calls_started'] == source['actual_LO_calls_completed'] == 3
        and [c['role'] for c in source['actual_calls']] == ['source1', 'source2', 'source3']
        and all(c['completed'] is True for c in source['actual_calls']), 'Retain the completed genuine unchanged source3 lineage')
    require(task['kind'] == 'complete_fixed_operating_reports_200_task_engineering_revision2'
        and task['passed'] is True and task['version'] == 1 and task['source_manifest'] == source_ref
        and task['actual_LO_calls_started'] == task['actual_LO_calls_completed'] == 8,
        'Do not inherit status from a failed or different original task')
    preparation = read(source['preparation']); candidate = read(preparation['candidate_manifest'])
    task_preparation = read(task['preparation'])
    require(task_preparation['source_preparation'] == source['preparation']
        and task_preparation['candidate_preparation'] == preparation['candidate_manifest']
        and task_preparation['genuine_goal'] == source['source']
        and task_preparation['source_definition'] == preparation['definition'], 'The healthy source/task/candidate definitions differ')
    require(source['source']['sha256'] == GOAL_SHA256 and reference(source['source']['path']) == source['source'],
        'The unchanged genuine healthy goal bytes changed')
    for key in ('specification', 'bindings'):
        require(source[key] == preparation[key] == candidate[key] == task_preparation[key], 'A healthy material binding changed')
    require(schema.canonical_sha256(read(source['specification'])) == SPECIFICATION_SHA256, 'The fixed raw business contract changed')
    refs = {'source_manifest': source_ref, 'completed_original_task8': task_ref, 'observed_FM_sign_failure': sign_ref,
        'genuine_healthy_goal': source['source'], 'source_preparation': source['preparation'],
        'original_task_preparation': task['preparation'], 'original_candidate': preparation['candidate_manifest'],
        'specification': source['specification'], 'bindings': source['bindings'], 'healthy_definition': preparation['definition'],
        'original_view_plans': candidate['view_plans'], 'retained_A': candidate['retained_A'], 'retained_B': candidate['retained_B']}
    for row in refs.values():
        require(reference(row['path']) == row, 'An exact original artifact changed')
    return refs


def freeze_variants(source_manifest, completed_original_task8, sign_evidence, output):
    """Freeze BOTH prospective variants in one fresh directory; emit no workbook."""
    input_refs = [row if isinstance(row, dict) else reference(row)
        for row in (source_manifest, completed_original_task8, sign_evidence)]
    refs = _ancestry(*input_refs)
    public, bindings, definition, original, A, B = [read(refs[key]) for key in
        ('specification', 'bindings', 'healthy_definition', 'original_view_plans', 'retained_A', 'retained_B')]
    designed = {variant: design(public, bindings, definition, original, variant) for variant in VARIANTS}
    proofs = {variant: prove(public, bindings, definition, original, designed[variant], A, B) for variant in VARIANTS}
    out = Path(output).absolute()
    require(out == out.resolve() and not out.exists(), 'Preserve all old attempts and use a fresh plan directory')
    out.mkdir(parents=True)
    def save(name, value):
        path = out/name
        with path.open('x') as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False); handle.write('\n')
        return reference(path)
    variants = {variant: {'view_plans': save(variant+'_view_plans.json', designed[variant]),
        'proof': save(variant+'_proof.json', proofs[variant])} for variant in VARIANTS}
    return save('prospective.json', {'kind': KIND, 'version': 1, 'variant_order': list(VARIANTS),
        'second_variant_condition': 'Only if S800 is solved or its predeclared assumptions fail actual validation; no automatic expansion.',
        'lineage': refs, 'variants': variants, 'recipe': recipes(), 'all_variants_frozen_before_fault_emission': True,
        'workbooks_written': 0, 'new_financial_forwards': 0, 'LO_calls': 0, 'model_calls': 0,
        'actual_D_unknown': True, 'quality_or_development_scores_inherited': False, 'qualified': False})


def validate_frozen(value, *, variant=None):
    """Replay every retained proof, including the unused predeclared variant."""
    frozen = read(value)
    require(frozen['kind'] == KIND and frozen['version'] == 1 and frozen['variant_order'] == list(VARIANTS)
        and set(frozen['variants']) == set(VARIANTS) and frozen['recipe'] == recipes()
        and frozen['all_variants_frozen_before_fault_emission'] is True,
        'Both exact prospective variants and the current pure implementation are required')
    refs = frozen['lineage']
    require(refs == _ancestry(refs['source_manifest'], refs['completed_original_task8'], refs['observed_FM_sign_failure']),
        'The unchanged material and prior actual evidence lineage changed')
    public, bindings, definition, original, A, B = [read(refs[key]) for key in
        ('specification', 'bindings', 'healthy_definition', 'original_view_plans', 'retained_A', 'retained_B')]
    plans = {}
    for name in VARIANTS:
        plans[name] = read(frozen['variants'][name]['view_plans'])
        require(read(frozen['variants'][name]['proof']) == prove(public, bindings, definition, original, plans[name], A, B),
            'A complete root-impact proof changed')
    require(variant is None or variant in VARIANTS, 'Only a predeclared variant can be selected')
    return frozen if variant is None else plans[variant]

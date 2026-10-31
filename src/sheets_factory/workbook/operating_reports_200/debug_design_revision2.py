"""Pure replacement of two failed DBG fault classes; healthy finance is frozen."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path

from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils import quote_sheetname

from . import audit, schema

SPECIFICATION_SHA256 = '4eaf468d8d7c0764f1cb70cbba7aa60a05c512bb00d0e9cad6137503f080ee40'
FAILED_TASK8_SHA256 = '16d21e7770a5aa53b9787dcd407e8efdf1372c92644610f2f36a6aaad8811c74'
ORIGINAL_PLAN_SHA256 = 'aed02cc8b1c756013bb96c770bd62bb3d4d1c3f7bdc7dcc64b9494ca5f5b726d'
RENDERER_SHA256 = 'b4fb12d296b5c8b5457fc6d8bbf8a1a412ed0587267beb8e81d996f7e6432e97'
KIND = 'prepared_operating_reports_200_debug_design_revision2'
PLAN_KIND = 'pure_operating_reports_200_view_plans_debug_revision2'
PROOF_KIND = 'pure_operating_reports_200_debug_design_revision2_proof'
FAMILIES = {'associate_sign': 50, 'ratio_as_change': 50, 'money_scale': 50, 'wrong_reference_quarter': 50}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def reference(value):
    path = Path(value).absolute()
    require(path == path.resolve() and path.is_file() and not path.is_symlink(), 'A real immutable artifact is required')
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def read(value):
    row = value if isinstance(value, dict) else reference(value)
    require(reference(row['path']) == row, 'A retained artifact changed')
    return json.loads(Path(row['path']).read_text())


def _point(binding):
    return quote_sheetname(binding['sheet']) + '!' + binding['cell']


def _replace_comparison(healthy, correct, wrong, driver):
    """Replace one parsed reference token, never translate another coordinate."""
    tokens = Tokenizer(healthy).items
    require(sum(t.type == 'OPERAND' and t.subtype == 'RANGE' and t.value == correct for t in tokens) == 1,
            'The healthy comparison must occur exactly once as a range token')
    require(sum(t.type == 'OPERAND' and t.subtype == 'RANGE' and t.value == driver for t in tokens) == 1,
            'The current supplied forecast driver must occur exactly once')
    require(correct != wrong and correct != driver and wrong != driver, 'Comparison and driver identities must differ')
    result = '=' + ''.join(wrong if t.type == 'OPERAND' and t.subtype == 'RANGE' and t.value == correct else t.value for t in tokens)
    before = [(t.type, t.subtype, t.value) for t in tokens]
    after = [(t.type, t.subtype, t.value) for t in Tokenizer(result).items]
    expected = [(kind, subtype, wrong if kind == 'OPERAND' and subtype == 'RANGE' and value == correct else value)
                for kind, subtype, value in before]
    require(after == expected, 'A token outside the historical comparison changed')
    return result


def _revenue(entity, basis, period):
    given = F(entity['forecast_sales'][period])
    scale = {'fraction': 1, 'percent_units': 100, 'basis_points': 10000}[entity['rate_unit']]
    form = entity['driver_form_by_year'][period[:4]]
    return (basis + given if form == 'money_delta' else basis * (1 + given/scale) if form == 'change_rate'
            else basis * given if form == 'level_multiple' else basis * given/100)


def _trajectory(entity, family=None):
    values = {q: F(entity['actual_sales'][q]) for q in schema.QUARTERS[:4]}
    for index, quarter in enumerate(schema.QUARTERS[4:], 4):
        prior = schema.QUARTERS[index - (4 if entity['forecast_reference'] == 'same_quarter_last_year' else 1)]
        if quarter == '2026Q1' and family == 'wrong_reference_quarter':
            prior = '2025Q4' if entity['forecast_reference'] == 'same_quarter_last_year' else '2025Q1'
        amount = _revenue(entity, values[prior], quarter)
        if quarter == '2026Q1' and family == 'money_scale':
            amount *= 1000
        require(amount > 0, 'Counterfactual forecast revenue must remain strictly positive')
        values[quarter] = amount
    return values


def _quant(value):
    number = F(value); scaled = abs(number)*100 + F(1, 2)
    integer = scaled.numerator//scaled.denominator
    return ('-' if number < 0 and integer else '') + f'{integer//100}.{integer%100:02d}'


def _validate_inputs(public, plans, bindings):
    schema.validate_spec(public)
    require(schema.canonical_sha256(public) == SPECIFICATION_SHA256, 'Only the frozen fixed200 public contract is supported')
    require(plans.get('kind') == 'pure_operating_reports_200_view_plans' and plans.get('version') == 1
        and plans.get('native_calls') == 0 and plans.get('actual_D_unknown') is True, 'The original pure rendered plan is required')
    wanted = [key for key, kind in schema.points(public) if kind != 'text'
        and key.split('/')[1].startswith(('2026', '2027', 'FY2026', 'FY2027'))]
    require(len(plans['FM_mask']) == len(set(plans['FM_mask'])) == 62322 and set(plans['FM_mask']) == set(wanted),
            'The complete original forecast mask must be preserved')
    require(bindings.get('specification_sha256') == SPECIFICATION_SHA256 and len(bindings['financial']) == 93510,
            'The original complete report bindings are required')
    roots = plans['DBG_faults']
    require(len(roots) == 200 and Counter(r['family'] for r in roots.values()) == FAMILIES
        and {key.split('/')[0] for key in roots} == {e['id'] for e in public['entities']}, 'Preserve all four fixed50-root families')
    for key, row in roots.items():
        binding = bindings['financial'][key]
        require((row['sheet'], row['cell']) == (binding['sheet'], binding['cell']), 'A root binding changed')
        require(row['healthy_formula'].startswith('=') and row['faulty_formula'].startswith('='), 'Explicit formulas are required')
        family = row['family']
        suffix = '/2026Q1/net_income' if family == 'associate_sign' else '/2027Q4/yoy_percent' if family == 'ratio_as_change' else '/2026Q1/revenue'
        require(key.endswith(suffix), 'A family root moved to another business field or period')


def revise(public, original_plans, bindings):
    """Return new plans only; write no workbook, cache, source or business fact."""
    _validate_inputs(public, original_plans, bindings)
    revised = deepcopy(original_plans)
    revised.update(kind=PLAN_KIND, version=2)
    entities = {e['id']: e for e in public['entities']}
    for key, row in revised['DBG_faults'].items():
        family = row['family']
        if family == 'money_scale':
            row['faulty_formula'] = '=(' + row['healthy_formula'][1:] + ')*1000'
        elif family == 'wrong_reference_quarter':
            identity = key.split('/')[0]
            previous = entities[identity]['forecast_reference'] == 'previous_calendar_quarter'
            correct, wrong = ('2025Q4', '2025Q1') if previous else ('2025Q1', '2025Q4')
            row['faulty_formula'] = _replace_comparison(row['healthy_formula'],
                _point(bindings['financial'][identity+'/'+correct+'/revenue']),
                _point(bindings['financial'][identity+'/'+wrong+'/revenue']),
                _point(bindings['provided_facts'][identity+'/forecast_sales/2026Q1']))
    return revised


def prove(public, original_plans, revised_plans, bindings, retained_A, retained_B):
    """Check the full A/B baseline and exact fault arithmetic without forwards."""
    require(revised_plans == revise(public, original_plans, bindings), 'Only the two declared complete fault classes may change')
    require(audit.compare(public, retained_A, retained_B)['passed'], 'Complete retained independent A/B values disagree')
    raw = retained_A['raw_cell_exact_values']; witnesses = []
    changed = []; unchanged = []; trajectory_count = 0; minimum = None
    for entity in public['entities']:
        identity = entity['id']
        key = next(key for key in original_plans['DBG_faults'] if key.startswith(identity+'/'))
        row = revised_plans['DBG_faults'][key]; family = row['family']; period = key.split('/')[1]
        healthy = _trajectory(entity)
        require(all(raw[identity+'/'+q+'/revenue'] == {'kind': 'rational', 'value': str(value)}
            for q, value in healthy.items()), 'Exact supplied-fact revenue arithmetic differs from retained A/B')
        def value(field, quarter=period):
            return F(raw[identity+'/'+quarter+'/'+field]['value'])
        if family in ('money_scale', 'wrong_reference_quarter'):
            wrong = _trajectory(entity, family)
            wrong_root = wrong['2026Q1']; changed.append(key); trajectory_count += 8
            minimum = min(wrong.values()) if minimum is None else min(minimum, *wrong.values())
            trajectory = {q: str(wrong[q]) for q in schema.QUARTERS[4:]}
        else:
            unchanged.append(key); trajectory = None
            wrong_root = value('core_net_income')-value('associate_income') if family == 'associate_sign' else value('revenue')/value('revenue', '2026Q4')*{'fraction': 1, 'percent_units': 100, 'basis_points': 10000}[entity['rate_unit']]
        expected = retained_A['typed_2dp_values'][key]
        require(expected == retained_B['typed_2dp_values'][key] and expected['type'] == 'number'
            and _quant(wrong_root) != expected['value'], 'Every root must retain nonzero primary2dp impact')
        require(row['healthy_formula'] == original_plans['DBG_faults'][key]['healthy_formula'], 'A healthy source formula changed')
        witnesses.append({'key': key, 'family': family, 'expected_primary': expected,
            'healthy_root_exact': raw[key]['value'], 'wrong_root_exact': str(wrong_root),
            'wrong_root_primary': _quant(wrong_root), 'forecast_revenue_exact': trajectory})
    require(len(changed) == len(unchanged) == 100 and trajectory_count == 800, 'The complete class census changed')
    physical_changes = Counter(row['family'] for key, row in revised_plans['DBG_faults'].items()
        if row['faulty_formula'] != original_plans['DBG_faults'][key]['faulty_formula'])
    return {'kind': PROOF_KIND, 'version': 2, 'passed': True, 'specification_sha256': SPECIFICATION_SHA256,
        'revised_class_root_count': 100, 'unchanged_other_family_root_count': 100,
        'physical_faulty_definition_change_count': sum(physical_changes.values()),
        'physical_definition_changes_by_family': dict(physical_changes),
        'byte_identical_revised_class_root_count': 100-sum(physical_changes.values()),
        'total_roots_primary_impact_proved': 200,
        'changed_root_forecast_quarters_positive': trajectory_count, 'minimum_counterfactual_revenue_exact': str(minimum),
        'all93510_original_A_B_points_unchanged': True, 'FM_mask_unchanged': True,
        'healthy_source_formulas_and_values_unchanged': True, 'public_facts_and_policies_unchanged': True,
        'wrong_quarter_rule': '2026Q1 uses2025Q4 instead of required2025Q1, or2025Q1 instead of required2025Q4; current forecast driver is retained.',
        'money_scale_rule': 'All50 healthy2026Q1 revenue formulas multiplied by1000.',
        'revenue_denominators_and_annual_CAGR_bases_positive': True, 'witnesses': witnesses,
        'actual_native_error_absence_or_full_D_proved': False, 'actual_D_unknown': True,
        'new_financial_forwards': 0, 'LO_calls': 0, 'model_calls': 0, 'workbooks_written': 0}


def _ancestry(public_ref, plans_ref, bindings_ref, a_ref, b_ref, failed_ref):
    failed = read(failed_ref)
    require(reference(failed_ref['path'])['sha256'] == FAILED_TASK8_SHA256 and failed['passed'] is False
        and [c['role'] for c in failed['actual_calls']] == ['FM_input1', 'FM_input2', 'DBG_input1']
        and all(c['completed'] is True for c in failed['actual_calls']), 'Retain the exact completed three-call task-design failure')
    preparation = read(failed['preparation']); candidate = read(preparation['candidate_preparation'])
    require(preparation['specification'] == public_ref and preparation['bindings'] == bindings_ref
        and candidate['specification'] == public_ref and candidate['bindings'] == bindings_ref
        and candidate['view_plans'] == plans_ref and candidate['retained_A'] == a_ref and candidate['retained_B'] == b_ref,
        'Original failed task, public contract, rendering plan and retained A/B must share exact ancestry')
    source = read(failed['source_manifest'])
    require(source['kind'] == 'independently_checked_fixed_operating_reports_200_source_revision2'
        and source['version'] == 1 and source['passed'] is True
        and source['source'] == preparation['genuine_goal'] and source['specification'] == public_ref
        and source['bindings'] == bindings_ref
        and [c['role'] for c in source['actual_calls']] == ['source1', 'source2', 'source3']
        and all(c['completed'] is True for c in source['actual_calls']),
        'The preserved task failure must retain its unchanged complete source3 goal')
    require(plans_ref['sha256'] == ORIGINAL_PLAN_SHA256, 'The original failed view plan must remain immutable')
    renderer = Path(__file__).with_name('excel_revision2.py')
    require(reference(renderer)['sha256'] == RENDERER_SHA256, 'The frozen healthy renderer changed')
    return {'failed_task8': failed_ref, 'failed_preparation': failed['preparation'],
        'original_candidate': preparation['candidate_preparation'], 'unchanged_source_manifest': failed['source_manifest'],
        'unchanged_genuine_goal': preparation['genuine_goal'], 'healthy_renderer': reference(renderer)}


def write_revision(public_ref, original_plans_ref, bindings_ref, oracle_a_ref, oracle_b_ref, failed_task8_ref, output):
    """Freeze a pure plan/proof/lineage; reject before creating a bad revision."""
    refs = [row if isinstance(row, dict) else reference(row) for row in
        (public_ref, original_plans_ref, bindings_ref, oracle_a_ref, oracle_b_ref, failed_task8_ref)]
    public_ref, original_plans_ref, bindings_ref, oracle_a_ref, oracle_b_ref, failed_task8_ref = refs
    ancestry = _ancestry(*refs)
    public, original, bindings, A, B = (read(row) for row in refs[:5])
    revised = revise(public, original, bindings); proof = prove(public, original, revised, bindings, A, B)
    out = Path(output).absolute()
    require(out == out.resolve() and not out.exists(), 'Preserve every earlier plan and failure; use a fresh output directory')
    out.mkdir(parents=True)
    def save(name, value):
        path = out/name
        with path.open('x') as handle:
            json.dump(value, handle, indent=2, ensure_ascii=False); handle.write('\n')
        return reference(path)
    value = {'kind': KIND, 'version': 2, 'passed': True, 'specification': public_ref,
        'original_view_plans': original_plans_ref, 'bindings': bindings_ref, 'retained_A': oracle_a_ref, 'retained_B': oracle_b_ref,
        'view_plans': save('view_plans.json', revised), 'proof': save('proof.json', proof), 'ancestry': ancestry,
        'implementation': reference(__file__), 'specification_sha256': SPECIFICATION_SHA256,
        'workbooks_written': 0, 'new_financial_forwards': 0, 'actual_D_unknown': True, 'qualified': False}
    return save('fault_design.json', value)


def validate_revision(value, candidate=None):
    """Replay the pure proof from exact retained artifacts; return new plans."""
    frozen = read(value)
    require(frozen['kind'] == KIND and frozen['version'] == 2 and frozen['passed'] is True
        and frozen['implementation'] == reference(__file__), 'Use the exact new fault-design implementation')
    refs = [frozen[k] for k in ('specification', 'original_view_plans', 'bindings', 'retained_A', 'retained_B')]
    require(frozen['ancestry'] == _ancestry(*refs, frozen['ancestry']['failed_task8']), 'Fault-design failure/source lineage changed')
    public, original, bindings, A, B = (read(row) for row in refs)
    revised = read(frozen['view_plans'])
    require(read(frozen['proof']) == prove(public, original, revised, bindings, A, B), 'The complete pure design proof changed')
    require(frozen['specification_sha256'] == SPECIFICATION_SHA256 and frozen['workbooks_written'] == 0
        and frozen['new_financial_forwards'] == 0 and frozen['actual_D_unknown'] is True and frozen['qualified'] is False,
        'Pure design is not native task validation or qualification')
    if candidate is not None:
        candidate = read(candidate) if isinstance(candidate, (str, Path)) or set(candidate) == {'path', 'sha256', 'bytes'} else candidate
        require(candidate == read(frozen['ancestry']['original_candidate']), 'Use the unchanged genuine source candidate')
    return revised

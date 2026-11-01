"""Read-only economic-error witnesses, separate from the primary workbook score.

This module starts no calculation or service. Its three snapshots must already
have complete native LibreOffice receipts. Numeric primary values alone cannot
establish economic error: the unrounded native values are required as well.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path
import re

import yaml

from .streaming_verifier import _sparse_cells, normalize

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / 'config/business_difficulty_v1.yaml'
ABSOLUTE_GBP = Decimal('0.01')
RELATIVE = Decimal('1e-10')
SCALES = {'GBP': Decimal(1), 'GBP000': Decimal(1000), 'mGBP': Decimal(1000000)}
CATEGORIES = {
    'tax': ('current_tax', 'tax', 'tax_expense', 'deferred_tax', 'income_tax'),
    'recognition': ('revenue', 'direct_cost', 'operating_expense', 'operating_profit', 'interest',
        'pretax_before_associate', 'core_net_income', 'associate_income', 'net_income', 'income',
        'parent_income', 'profit_after_tax', 'profit_before_tax'),
    'noncash_cashbridge': ('operating_cash_flow', 'cash_flow', 'closing_cash', 'opening_cash',
        'cash', 'cash_balance', 'associate_cash_receipt', 'associate_cash_dividend'),
    'investment': ('opening_investment', 'closing_investment', 'investment', 'investment_balance'),
    'distribution': ('dividend', 'dividends', 'distribution', 'distributions', 'lp_distribution', 'gp_distribution'),
    'rollforward': ('opening_retained_earnings', 'closing_retained_earnings', 'retained_earnings',
        'total_assets', 'assets', 'debt', 'liabilities', 'total_liabilities', 'total_liabilities_equity',
        'contributed_capital', 'capital', 'equity'),
}
CORE_FIELDS = {field: category for category, fields in CATEGORIES.items() for field in fields}
ENGINE_PINS = {
    'implementation': 'cc4fb863740a0fc403a5947a52fa1c2e644b81b75c358e2a3cbf47e7d33a9c8d',
    'upstream_engine': '0f67176358f45e0d0a73edbafd928b8bde305aec3493a576db9040f823c7b700',
    'thread_cap_adapter': '82c2e2d5f0ca5c68973f893a66de5d3455e76e67235e462f1d76351a05044361',
}


def _require(value, reason):
    if not value:
        raise ValueError(reason)


def reference(path):
    path = Path(path).absolute()
    _require(path == path.resolve() and path.is_file() and not path.is_symlink(), 'Evidence must be a real file')
    before = path.stat(); digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            digest.update(block)
    after = path.stat()
    _require((before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        == (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'Evidence changed while hashing')
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': after.st_size}


def _read(record):
    _require(isinstance(record, dict) and set(record) == {'path', 'sha256', 'bytes'}
        and reference(record['path']) == record, 'Evidence reference is missing or changed')
    return json.loads(Path(record['path']).read_text())


def _decimal(value):
    _require(type(value) in (str, int, float, Decimal), 'Numeric evidence must be a finite decimal')
    result = Decimal(str(value))
    _require(result.is_finite(), 'Numeric evidence must be finite')
    return result


def _typed(value):
    _require(isinstance(value, (tuple, list)) and len(value) == 2, 'Use normalized two-item typed values')
    kind, data = value
    if kind == 'number':
        number = _decimal(data).quantize(Decimal('.01'), rounding=ROUND_HALF_UP)
        return ('number', str(number.copy_abs() if number == 0 else number))
    _require(kind in ('empty', 'bool', 'text', 'error', 'datetime', 'time', 'duration'), 'Unknown normalized type')
    if kind == 'bool': _require(type(data) is bool, 'Boolean evidence has the wrong type')
    return (kind, data)


def extract_native_maps(path):
    """Extract complete actual cached values; this never recalculates a workbook."""
    from openpyxl import load_workbook
    from openpyxl.utils.cell import get_column_letter
    typed, raw = {}, {}
    book = load_workbook(path, data_only=True, read_only=True, keep_links=False)
    try:
        names = book.sheetnames
        for sheet in book:
            for _, cell in _sparse_cells(sheet):
                point = sheet.title + '!' + get_column_letter(cell['column']) + str(cell['row'])
                value = cell['value']
                item = ('error', value) if cell['data_type'] == 'e' else normalize(value)
                if item[0] != 'empty': typed[point] = list(item)
                if item[0] == 'number': raw[point] = str(_decimal(value))
        return {'typed': typed, 'raw_numeric': raw, 'sheetnames': names}
    finally:
        book.close()


def _role_proof(role, values, raw_values, provenance):
    item = provenance['roles'][role]
    _require(item.get('map_scope') == 'complete_sparse_workbook', 'A complete recalculated map is required')
    original = item['original_workbook']; output = item['recalculated_workbook']
    for record in (original, output): _require(reference(record['path']) == record, 'Native workbook changed')
    stored_typed, stored_raw = _read(item['typed_map']), _read(item['raw_numeric_map'])
    _require(stored_typed == {p: list(v) for p, v in values.items()} and stored_raw == raw_values,
             'The supplied maps differ from their complete retained artifacts')
    receipt = _read(item['native_receipt'])
    _require(receipt.get('kind') == 'resource_bound_libreoffice_call'
        and receipt.get('status') == 'completed' and receipt.get('role') in ('source', 'verifier')
        and receipt.get('source') == original and receipt.get('output') == output
        and receipt.get('actual_resources_verified') is True and receipt.get('thread_cap_verified') is True
        and receipt.get('finished_at') and receipt.get('started_at')
        and re.fullmatch(r'[0-9a-f]{64}', receipt.get('container_id', '')),
        'A genuine complete native recalculation receipt is required')
    for name, digest in ENGINE_PINS.items():
        _require(receipt[name]['sha256'] == digest and reference(receipt[name]['path']) == receipt[name],
                 'The native calculation implementation is not the supported frozen engine')
    actual = receipt.get('actual_resources', {})
    _require(actual.get('cpus_nanoseconds') == 2_000_000_000
        and actual.get('memory_bytes') == 32 * 1024**3 and actual.get('pids_limit') == 256,
        'The native calculation resource evidence is incomplete')
    for stage in ('before', 'after'):
        cap = receipt.get('thread_cap_' + stage, {})
        _require(cap.get('container_id') == receipt['container_id'] and cap.get('values') == ['MAX_CONCURRENCY=2'],
                 'The native worker-cap identity is incomplete')
    _require(receipt['thread_cap_after'].get('exit_code_observed') == '0', 'Native recalculation did not exit normally')
    extracted = extract_native_maps(output['path'])
    _require(extracted['typed'] == stored_typed and extracted['raw_numeric'] == stored_raw,
             'The retained maps do not cover the full actual recalculated workbook')
    for record in (original, output, item['typed_map'], item['raw_numeric_map'], item['native_receipt']):
        _require(reference(record['path']) == record, 'Native evidence changed during full map inspection')
    return extracted['sheetnames']


def analyze(input_values, reference_values, output_values, *, bindings, entity_money_scales,
            provenance, original_reward, raw_reference=None, raw_output=None, trace_refs=(), enabled=None):
    """Return economic witnesses without changing the OJ result.

    ``provenance.roles`` has input/reference/output entries, each with full REFs
    for original_workbook, recalculated_workbook, typed_map, raw_numeric_map and
    native_receipt, plus map_scope='complete_sparse_workbook'. Input raw values
    are read from its retained raw_numeric_map. All three maps are checked
    against the complete actual recalculated workbooks, never source caches.
    Top-level provenance bindings/entity_money_scales REFs bind both mappings.
    Bindings are semantic-key -> {sheet, cell, optional field/entity_id/role};
    the usual {financial: bindings, ...} envelope is also accepted.
    """
    config = yaml.safe_load(CONFIG.read_text())
    result = {'kind': 'auxiliary_business_failure_evidence', 'version': 1,
        'state': 'unknown', 'business_failure_evidence': None, 'business_qualified': None,
        'original_reward': original_reward, 'primary_reward_modified': False,
        'economic_witnesses': [], 'quality_issues': [], 'coverage_issues': [],
        'excluded_differences': [], 'category_counts': {}, 'provenance': provenance,
        'classification_basis': 'affected_economic_field_not_inferred_model_reasoning',
        'trace_refs': list(trace_refs), 'config': reference(CONFIG), 'implementation': reference(__file__),
        'new_LO_model_Harbor_calls': 0}
    active = config['enabled'] if enabled is None else enabled
    if active is False:
        result.update(state='disabled'); return result
    try:
        _require(type(active) is bool and active, 'The evidence switch must be boolean')
        _require(_decimal(config['economic_absolute_tolerance_gbp']) == ABSOLUTE_GBP
            and _decimal(config['economic_relative_tolerance']) == RELATIVE,
            'Use the declared economic-evidence tolerances')
        _require(type(original_reward) in (int, float) and original_reward in (0, 1), 'The original reward is unavailable')
        _require(provenance.get('kind') == 'three_complete_native_recalculated_value_maps'
            and provenance.get('version') == 1 and set(provenance['roles']) == {'input', 'reference', 'output'},
            'All three actual native recalculations and complete maps are required')
        _require(_read(provenance['bindings']) == bindings
            and _read(provenance['entity_money_scales']) == entity_money_scales,
            'Semantic positions and entity money scales must match retained source evidence')
        _require(raw_reference is not None and raw_output is not None, 'Unrounded native numeric maps are required')
        raw_input = _read(provenance['roles']['input']['raw_numeric_map'])
        names = [_role_proof(role, values, raw, provenance) for role, values, raw in (
            ('input', input_values, raw_input), ('reference', reference_values, raw_reference),
            ('output', output_values, raw_output))]
        for record in trace_refs: _require(reference(record['path']) == record, 'Model trace changed')
        if names[0] != names[1] or names[1] != names[2]:
            result['coverage_issues'].append({'reason': 'sheet_structure_mismatch'})
        maps = [{point: _typed(value) for point, value in values.items()}
                for values in (input_values, reference_values, output_values)]
        original, goal, submitted = maps
        empty = ('empty', None)
        wrong = {p for p in goal.keys() | submitted.keys() if goal.get(p, empty) != submitted.get(p, empty)}
        scope = bindings.get('financial', bindings)
        physical = {}
        for key, binding in scope.items():
            point = binding['sheet'] + '!' + binding['cell']
            _require(point not in physical, 'Semantic bindings contain a duplicate physical cell')
            physical[point] = (key, binding)
        for point in sorted(wrong):
            expected, actual = goal.get(point, empty), submitted.get(point, empty)
            if expected[0] != actual[0] or actual[0] in ('error', 'empty'):
                target = 'coverage_issues' if actual[0] == 'empty' else 'quality_issues'
                result[target].append({'point': point, 'reason': 'missing_value' if actual[0] == 'empty' else 'type_or_native_error',
                    'expected': list(expected), 'actual': list(actual)})
                continue
            if point not in physical:
                result['coverage_issues'].append({'point': point, 'reason': 'outside_semantic_bindings'}); continue
            key, binding = physical[point]
            field = binding.get('field', key.rsplit('/', 1)[-1])
            entity = binding.get('entity_id', key.split('/', 1)[0])
            if field.startswith('reported_') or field not in CORE_FIELDS:
                result['excluded_differences'].append({'point': point, 'semantic_key': key,
                    'reason': 'presentation_or_noncore_metric'}); continue
            if binding.get('role') in ('given_NA', 'provided', 'given', 'provided_fact'):
                result['quality_issues'].append({'point': point, 'reason': 'changed_given_fact'}); continue
            if expected[0] != 'number':
                result['quality_issues'].append({'point': point, 'reason': 'nonnumeric_core_field'}); continue
            _require(point in raw_reference and point in raw_output, 'A core raw numeric value is missing')
            scale_value = entity_money_scales[entity]
            scale = SCALES.get(scale_value) if isinstance(scale_value, str) and scale_value in SCALES else _decimal(scale_value)
            _require(scale in SCALES.values(), 'Entity money scale must be GBP, GBP000, or mGBP')
            expected_raw, actual_raw = _decimal(raw_reference[point]), _decimal(raw_output[point])
            _require(_typed(('number', expected_raw)) == expected and _typed(('number', actual_raw)) == actual,
                     'Raw and primary numeric values disagree')
            expected_gbp, actual_gbp = expected_raw * scale, actual_raw * scale
            difference = abs(actual_gbp - expected_gbp)
            threshold = max(ABSOLUTE_GBP, abs(expected_gbp) * RELATIVE)
            if difference <= threshold:
                result['excluded_differences'].append({'point': point, 'semantic_key': key,
                    'reason': 'economic_difference_at_or_below_tolerance', 'absolute_difference_gbp': str(difference),
                    'tolerance_gbp': str(threshold)}); continue
            result['economic_witnesses'].append({'point': point, 'semantic_key': key, 'entity_id': entity,
                'field': field, 'category': CORE_FIELDS[field], 'expected_gbp': str(expected_gbp),
                'actual_gbp': str(actual_gbp), 'absolute_difference_gbp': str(difference),
                'relative_difference': str(difference / abs(expected_gbp)) if expected_gbp else None,
                'tolerance_gbp': str(threshold), 'money_scale_to_gbp': str(scale),
                'expected_primary': list(expected), 'actual_primary': list(actual),
                'original_to_goal_change': original.get(point, empty) != expected})
        result['category_counts'] = dict(Counter(w['category'] for w in result['economic_witnesses']))
        has_business_error = bool(result['economic_witnesses']) and original_reward == 0
        if original_reward == 1 and result['economic_witnesses']:
            result['quality_issues'].append({'reason': 'original_success_conflicts_with_recalculated_core_values'})
        result.update(state='diagnosed', business_failure_evidence=has_business_error,
            business_qualified=has_business_error, primary_wrong_count=len(wrong))
        for record in (provenance['bindings'], provenance['entity_money_scales'], *trace_refs):
            _require(reference(record['path']) == record, 'Semantic or trace evidence changed during inspection')
    except (ValueError, KeyError, TypeError, AttributeError, OSError, InvalidOperation) as error:
        result.update(state='unknown', business_failure_evidence=None, business_qualified=None,
            unknown_reason=str(error))
    return result

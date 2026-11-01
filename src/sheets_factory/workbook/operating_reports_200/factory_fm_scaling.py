"""Whole-history FM masks over one retained operating-report source.

Planning and package emission do not calculate a workbook or invoke a model.
The reference bytes, supplied facts, labels, policies and NA text stay intact.
"""
from __future__ import annotations

from collections import Counter
from io import BytesIO
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils.cell import coordinate_to_tuple, range_to_tuple

from . import schema

SPECIFICATION_SHA256 = '4eaf468d8d7c0764f1cb70cbba7aa60a05c512bb00d0e9cad6137503f080ee40'
GOAL_SHA256 = '5f38a984cf7fc689e030602aab0f0bc95a51b05d54711d4a79207f04445936ef'
VARIANTS = tuple(f'F{i:02d}' for i in range(1, 21))
GROWTH_FIELDS = frozenset(('yoy_percent', 'qoq_percent', 'prior_year_multiple',
    'prior_year_index', 'yoy_sales_delta', 'qoq_sales_delta', 'cagr_percent', 'annual_sales_delta'))
INSTRUCTION = ('Complete the missing historical calculations and forecast management reports '
    'throughout the workbook. Use the supplied business data, assumptions, and reporting '
    'conventions, and preserve the existing inputs and workbook layout.\n')
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'
_CELL = re.compile(rb'<(?:[A-Za-z_][\w.-]*:)?c\b[^>]*(?<!/)>.*?</(?:[A-Za-z_][\w.-]*:)?c>', re.S)
_ADDRESS = re.compile(rb'\br=(["\'])([A-Z]+[1-9][0-9]*)\1')
_CALC_CHILD = re.compile(rb'<(?:[A-Za-z_][\w.-]*:)?(?:f|v)\b[^>]*(?:/>|>.*?</(?:[A-Za-z_][\w.-]*:)?(?:f|v)>)', re.S)
_PREFIX_DECLARATION = re.compile(rb'\s+xmlns:[A-Za-z_][\w.-]*=(["\']).*?\1')


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def reference(path):
    path = Path(path).absolute()
    _require(path == path.resolve() and path.is_file() and not path.is_symlink(), 'Use a real regular input file')
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _inventory(public, bindings, definition, original_plans):
    schema.validate_spec(public)
    signature = schema.canonical_sha256(public)
    _require(public['dimension_mode'] == 'toy' or signature == SPECIFICATION_SHA256,
        'Use the retained production specification or an explicit toy fixture')
    expected = dict(schema.points(public))
    _require(bindings['specification_sha256'] == definition['specification_sha256'] == signature
        and set(bindings['financial']) == set(expected), 'The full source report inventory must agree')
    financial = bindings['financial']; physical = {k: v['sheet']+'!'+v['cell'] for k, v in financial.items()}
    _require(len(set(physical.values())) == len(physical), 'Report bindings must be unique')
    formulas = definition['formulas']; literals = definition['literals']
    _require(not set(formulas) & set(literals), 'A source position cannot be both formula and literal')
    provided = set(definition.get('provided_financial_inputs', {}))
    _require(not set(formulas) & provided, 'Given raw facts cannot be formula mask candidates')
    forecast = sorted(original_plans['FM_mask'])
    _require(len(forecast) == len(set(forecast)) and set(forecast) <= set(financial), 'The original forecast mask must be complete and unique')
    _require(all(physical[k] in formulas and expected[k] != 'text' for k in forecast),
        'Original forecast targets must be formulas, never NA text or facts')
    historical = {k for k in financial if k.split('/')[1] in (*schema.QUARTERS[:4], 'FY2025')
        and physical[k] in formulas}
    _require(not historical & set(forecast), 'Historical and forecast masks must be disjoint')
    _require(set(physical[k] for k in historical | set(forecast)) == set(formulas),
        'Every healthy source formula must belong to the historical or original forecast inventory')
    groups = {}
    for key in sorted(historical):
        identity, _, field = key.split('/')
        groups.setdefault((identity, field), []).append(key)
    if public['dimension_mode'] == 'production':
        _require(len(formulas) == 88676 and len(forecast) == 62322 and len(historical) == 26354,
            'The retained 88676-formula / 62322-forecast source must remain unchanged')
    return physical, forecast, historical, groups


def _dependency_groups(definition, physical, historical, groups):
    """Parse every historical formula and retain its complete group consumers."""
    point_groups = {physical[key]: group for group, keys in groups.items() for key in keys}
    reverse = {group: set() for group in groups}; by_sheet = {}
    for point, group in point_groups.items():
        sheet, address = point.rsplit('!', 1); row, column = coordinate_to_tuple(address)
        by_sheet.setdefault(sheet, {})[(column, row)] = group
    parsed = 0
    for key in historical:
        destination = point_groups[physical[key]]
        for token in Tokenizer(definition['formulas'][physical[key]]).items:
            if token.type != 'OPERAND' or token.subtype != 'RANGE':
                continue
            try:
                sheet, bounds = range_to_tuple(token.value)
            except (ValueError, TypeError) as error:
                raise ValueError('A complete historical dependency proof requires a bounded sheet reference: '+token.value) from error
            _require(all(type(v) is int for v in bounds), 'Unbounded source ranges require explicit support')
            sheet = sheet.replace("''", "'"); min_c, min_r, max_c, max_r = bounds
            if min_c == max_c and min_r == max_r:
                group = by_sheet.get(sheet, {}).get((min_c, min_r)); sources = () if group is None else (group,)
            else:
                sources = {group for (column, row), group in by_sheet.get(sheet, {}).items()
                    if min_c <= column <= max_c and min_r <= row <= max_r}
            for source in sources:
                if source != destination:
                    reverse[source].add(destination)
            parsed += 1
    closures = {}
    for group in groups:
        reached = {group}; pending = [group]
        while pending:
            current = pending.pop()
            for consumer in reverse[current]-reached:
                reached.add(consumer); pending.append(consumer)
        closures[group] = reached
    return closures, reverse, parsed


def _design(public, definition, variant_id, inventory, dependencies):
    _require(variant_id in VARIANTS, 'Select F01 through F20')
    physical, forecast, historical, groups = inventory
    closures, consumers, references_parsed = dependencies
    index = VARIANTS.index(variant_id)
    growth = {k for k in historical if k.split('/')[2] in GROWTH_FIELDS}
    selected_groups = set().union(*(closures[group] for group in groups if group[1] in GROWTH_FIELDS))
    selected = {key for group in selected_groups for key in groups[group]}
    if public['dimension_mode'] == 'production':
        budget = 9005 + (26000-9005)*index//19
    else:
        budget = max(len(growth), (len(historical)*(35+64*index//19)+99)//100)
    candidates = [(group, keys) for group, keys in groups.items() if group[1] not in GROWTH_FIELDS]
    candidates.sort(key=lambda item: hashlib.sha256((variant_id+'|'+item[0][0]+'|'+item[0][1]).encode()).digest())
    for group, _ in candidates:
        additional = closures[group]-selected_groups
        if len(selected)+sum(len(groups[g]) for g in additional) <= budget:
            selected_groups.update(additional)
            selected.update(key for g in additional for key in groups[g])
    _require(growth <= selected and selected <= historical, 'All historical growth formulas must be masked')
    _require(all(not set(keys) & selected or set(keys) <= selected for keys in groups.values()),
        'Mask whole entity/metric historical groups')
    if public['dimension_mode'] == 'production':
        _require(9000 <= len(selected) <= 26000, 'Historical mask size must stay within the declared range')
    keys = sorted(set(forecast) | selected)
    remaining_edges = [(source, destination) for source in selected_groups
        for destination in consumers[source] if destination not in selected_groups]
    _require(not remaining_edges, 'No retained historical formula may consume a masked formula group')
    content = {'kind': 'operating_reports_FM_history_scaling_plan', 'version': 1,
        'variant_id': variant_id, 'mode': 'financial_modeling',
        'specification_sha256': schema.canonical_sha256(public),
        'forecast_mask_count': len(forecast), 'historical_growth_mask_count': len(growth),
        'historical_mask_count': len(selected), 'historical_formula_budget': budget,
        'mask_count': len(keys), 'mask_keys': keys,
        'mask_points': sorted(physical[k] for k in keys),
        'historical_groups': [list(group) for group, values in sorted(groups.items()) if set(values) <= selected],
        'historical_by_metric': dict(sorted(Counter(k.split('/')[2] for k in selected).items())),
        'protected_formula_points': sorted(set(definition['formulas'])-{physical[k] for k in keys}),
        'protected_formula_dependency_check': {'passed': True,
            'historical_references_parsed': references_parsed,
            'masked_group_edges_to_retained_groups': len(remaining_edges),
            'all_forecast_formulas_masked': True,
            'retained_formulas_should_keep_healthy_values_on_recalculation': True,
            'native_error_absence_certified': False},
        'instruction': INSTRUCTION, 'only_formulas_masked': True,
        'given_facts_policy_labels_NA_unchanged': True,
        'native_calls': 0, 'model_calls': 0, 'actual_D_pending': True, 'qualified': False}
    return {**content, 'plan_sha256': _digest(content)}


def design(public, bindings, definition, original_plans, variant_id):
    """Mask whole historical metric groups and all downstream historical consumers."""
    inventory = _inventory(public, bindings, definition, original_plans)
    dependencies = _dependency_groups(definition, inventory[0], inventory[2], inventory[3])
    return _design(public, definition, variant_id, inventory, dependencies)


def design_all(public, bindings, definition, original_plans):
    """Plan the fixed twenty variants before observing any model outcome."""
    inventory = _inventory(public, bindings, definition, original_plans)
    dependencies = _dependency_groups(definition, inventory[0], inventory[2], inventory[3])
    plans = [_design(public, definition, variant, inventory, dependencies) for variant in VARIANTS]
    _require(len({p['plan_sha256'] for p in plans}) == 20, 'Twenty distinct plans are required')
    if public['dimension_mode'] == 'production':
        _require(len({_digest(p['mask_points']) for p in plans}) == 20, 'Twenty physically different masks are required')
    return plans


def _masked_sheet(raw, sheet, points, definition):
    wanted = {p.rsplit('!', 1)[1] for p in points if p.rsplit('!', 1)[0] == sheet}
    if not wanted:
        return raw, 0
    seen = set()
    namespace_declarations = b''.join(match.group() for match in _PREFIX_DECLARATION.finditer(raw))
    def replace(match):
        cell = match.group(); address_match = _ADDRESS.search(cell.split(b'>', 1)[0])
        if address_match is None or address_match[2].decode() not in wanted:
            return cell
        address = address_match[2].decode(); point = sheet+'!'+address
        # A temporary wrapper supplies the existing worksheet namespace only.
        parsed = ET.fromstring(b'<root xmlns="'+NS[1:-1].encode()+b'"'+namespace_declarations+b'>'+cell+b'</root>')[0]
        formula = parsed.find(NS+'f')
        _require(address not in seen and formula is not None and formula.text is not None
            and '='+formula.text == definition['formulas'][point], 'A mask target must contain its exact healthy formula')
        _require(parsed.find(NS+'is') is None, 'Never remove an inline literal')
        seen.add(address)
        blank = _CALC_CHILD.sub(b'', cell)
        opening, ending = blank.split(b'>', 1)
        opening = re.sub(rb'\s+t=(["\']).*?\1', b'', opening)
        return opening+b'>'+ending
    changed = _CELL.sub(replace, raw)
    _require(seen == wanted, 'Every planned formula must be found exactly once')
    return changed, len(seen)


def emit(goal_path, public, bindings, definition, original_plans, plan, output_directory):
    """Write one masked input and a byte-identical reference; run no calculation."""
    _require(plan == design(public, bindings, definition, original_plans, plan['variant_id']),
        'The complete plan must match its declared deterministic mask')
    source = reference(goal_path); raw = Path(source['path']).read_bytes()
    if public['dimension_mode'] == 'production':
        _require(source['sha256'] == GOAL_SHA256, 'The shared reference must be the original recalculated source3')
    output = Path(output_directory).absolute()
    _require(output == output.resolve() and not output.exists(), 'Use a fresh real output directory')
    output.mkdir(parents=True)
    with ZipFile(BytesIO(raw)) as archive:
        _require('xl/calcChain.xml' not in archive.namelist(), 'A calculation chain requires a separate supported emitter')
        workbook = ET.fromstring(archive.read('xl/workbook.xml'))
        rels = {row.attrib['Id']: row.attrib['Target'].lstrip('/') for row in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        sheets = {}
        for row in workbook.find(NS+'sheets'):
            name = rels[row.attrib[REL]]
            if not name.startswith('xl/'):
                name = 'xl/'+name
            sheets[name] = row.attrib['name']
        points = set(plan['mask_points']); changed_members = []; count = 0
        with ZipFile(output/'input.xlsx', 'w') as target:
            target.comment = archive.comment
            for info in archive.infolist():
                payload = archive.read(info.filename)
                if info.filename in sheets:
                    transformed, n = _masked_sheet(payload, sheets[info.filename], points, definition)
                    if n:
                        changed_members.append(info.filename)
                    count += n; payload = transformed
                target.writestr(info, payload)
    _require(count == plan['mask_count'], 'The emitted mask must cover the entire plan')
    (output/'reference.xlsx').write_bytes(raw)
    (output/'instruction.md').write_text(plan['instruction'])
    with (output/'plan.private.json').open('x') as stream:
        json.dump(plan, stream, ensure_ascii=False, indent=2); stream.write('\n')
    _require(reference(goal_path) == source and reference(output/'reference.xlsx')['sha256'] == source['sha256'],
        'The original and copied goal bytes must remain unchanged')
    receipt = {'kind': 'emitted_operating_reports_FM_history_scaling', 'version': 1,
        'variant_id': plan['variant_id'], 'goal': source, 'input': reference(output/'input.xlsx'),
        'reference': reference(output/'reference.xlsx'), 'instruction': reference(output/'instruction.md'),
        'plan': reference(output/'plan.private.json'), 'mask_count': count,
        'forecast_mask_count': plan['forecast_mask_count'], 'historical_mask_count': plan['historical_mask_count'],
        'changed_package_members': changed_members, 'unselected_cell_and_nonworksheet_payload_bytes_unchanged': True,
        'goal_bytes_unchanged': True, 'native_calls': 0, 'model_calls': 0,
        'actual_D_pending': True, 'qualified': False}
    with (output/'receipt.json').open('x') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2); stream.write('\n')
    return receipt

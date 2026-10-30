"""Offline source presentation and lineage preflight; never selects a seed.

A prepared copy still requires actual LibreOffice normalization, full exact
value equivalence, formula allowlist, two-pass stability and explicit audit
transfer before it can become an input source. This module performs no calls.
"""
from collections import Counter
from copy import copy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import math
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import openpyxl
from openpyxl.utils import get_column_letter, range_boundaries

from .composite_family import discover_composite_families
from .lease_family import MAIN, NS, _paths, compare_exact_typed, ref, sha
from .presentation_source import verify_formula_allowlist, IMAGE_ID

NOTE = ('Schedule presentation: fixed numeric zeros are supplied for zero-valued monetary entries in selected '
    'financial schedules. These provided values preserve the contractual source results. Preserve supplied '
    'constants, inputs, calendars and regulatory context; apply the public financial contracts to formula repairs.')


def _write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def _read_ref(record):
    path = Path(record['path'])
    if sha(path) != record['sha256'] or ('bytes' in record and path.stat().st_size != record['bytes']):
        raise ValueError('Financial evidence identity changed: ' + str(path))
    return json.loads(path.read_text())


def audited_zero_coverage(conversions, audit_data):
    """Every zero conversion must have a successful independent money check."""
    index = {}
    for module, audit in audit_data.items():
        for check in audit['cell_checks']:
            address = check.get('address', '')
            if module == 'operating' and not address.startswith('Operating '):
                address = 'Operating ' + address
            if check.get('passed', check.get('matched')) is not True:
                raise ValueError('An original independent check failed')
            expected = check.get('expected_independent', check.get('expected'))
            try:
                number = Decimal(str(expected))
            except (InvalidOperation, ValueError):
                continue
            if number.is_finite() and number == 0:
                index.setdefault(address, set()).add(module)
    result = []
    for item in conversions:
        address = item['sheet'] + '!' + item['cell']
        if address not in index:
            raise ValueError('Zero is not covered by an original independent financial check: ' + address)
        result.append({'address': address, 'expected_independent': '0',
                       'source_independent_modules': sorted(index[address])})
    return result


def present_composite_zero_schedules(source, destination, policy):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError('Do not overwrite a presentation attempt')
    book = openpyxl.load_workbook(source, keep_links=False)
    values = openpyxl.load_workbook(source, data_only=True, keep_links=False)
    try:
        groups = discover_composite_families(book, policy)
        conversions, by_sheet = [], {}
        for group in groups:
            for column in group['columns']:
                c = book[group['sheet']].cell(group['row'], column)
                v = values[group['sheet']][c.coordinate]
                if c.data_type != 'f':
                    raise ValueError('The original full formula family must be present')
                if type(v.value) not in (int, float) or not math.isfinite(v.value) or v.is_date or v.data_type == 'e':
                    raise ValueError('A finite numeric monetary cache is required')
                if v.value != 0:
                    continue
                item = {'sheet': group['sheet'], 'cell': c.coordinate, 'family': group['family'],
                        'algorithm': group['algorithm'], 'original_formula': c.value,
                        'original_cached_value': v.value, 'provided_value': 0}
                conversions.append(item)
                by_sheet.setdefault(group['sheet'], {})[c.coordinate] = item
        note_sheet, note_row = 'Partner Contract', book['Partner Contract'].max_row + 2
        with ZipFile(source) as original:
            paths = _paths(original)
            changed = {paths[name] for name in by_sheet} | {paths[note_sheet]}
            with ZipFile(destination, 'x') as output:
                for info in original.infolist():
                    raw = original.read(info.filename)
                    name = next((n for n, path in paths.items() if path == info.filename), None)
                    if info.filename in changed:
                        root = ET.fromstring(raw)
                        pending = dict(by_sheet.get(name, {}))
                        for c in root.findall('.//m:sheetData/m:row/m:c', NS):
                            item = pending.pop(c.get('r'), None)
                            if item is None:
                                continue
                            formula, value = c.find('m:f', NS), c.find('m:v', NS)
                            if (formula is None or value is None or Decimal(value.text) != 0
                                    or c.get('t') in ('b', 'd', 'e', 's', 'str', 'inlineStr')
                                    or '=' + (formula.text or '') != item['original_formula']):
                                raise ValueError('Raw XML zero/formula assertion differs')
                            c.remove(formula)
                            c.set('t', 'n')
                            value.text = '0'
                        if pending:
                            raise ValueError('A declared zero was not found in raw XML')
                        if name == note_sheet:
                            row = ET.SubElement(root.find('m:sheetData', NS), '{' + MAIN + '}row', r=str(note_row))
                            c = ET.SubElement(row, '{' + MAIN + '}c', r='A' + str(note_row), t='inlineStr')
                            ET.SubElement(ET.SubElement(c, '{' + MAIN + '}is'), '{' + MAIN + '}t').text = NOTE
                            dim = root.find('m:dimension', NS)
                            if dim is not None:
                                _, _, end_column, _ = range_boundaries(dim.get('ref'))
                                dim.set('ref', 'A1:' + get_column_letter(end_column) + str(note_row))
                        raw = ET.tostring(root, encoding='utf-8')
                    output.writestr(copy(info), raw)
            with ZipFile(destination) as output:
                unchanged = [i.filename for i in original.infolist() if i.filename not in changed]
                if any(original.read(n) != output.read(n) for n in unchanged):
                    raise ValueError('An unselected package part changed')
        return {'source': ref(source), 'raw_presentation': ref(destination), 'conversions': conversions,
            'converted_formula_count': len(conversions), 'counts_by_algorithm': dict(Counter(i['algorithm'] for i in conversions)),
            'changed_package_parts': sorted(changed), 'unchanged_package_part_count': len(unchanged),
            'public_note': {'sheet': note_sheet, 'cell': 'A' + str(note_row), 'value': NOTE}}
    finally:
        book.close()
        values.close()


def prepare_offline_presentation(source_manifest, output, policy):
    """Write only an unqualified offline preflight; no engine or model access."""
    source_manifest, output = Path(source_manifest).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = json.loads(source_manifest.read_text())
    try:
        required = {'lease', 'programme', 'operating', 'holding', 'contingent'}
        if source.get('financial_audit_passed') is not True or set(source.get('financial_audits', {})) != required:
            raise ValueError('The fully audited six-algorithm original source is required')
        if source.get('contingent_all_years_unique') is not True or source['runtime']['image_id'] != IMAGE_ID:
            raise ValueError('The correct original source must retain its certified cycle and runtime')
        original = Path(source['local_path'])
        if sha(original) != source['derived_workbook_sha256']:
            raise ValueError('Original workbook identity differs')
        audit_data, audit_refs = {}, {}
        for module in required:
            record = ref(source_manifest.parent / 'private' / (module + '_financial_audit.json'))
            data = _read_ref(record)
            if (data.get('passed') is not True or data.get('checked_cells') != source['financial_audits'][module]['checked_cells']
                    or data.get('workbook', {}).get('sha256') != sha(original)):
                raise ValueError('Original independent audit identity/coverage differs')
            if any(data.get(k) for k in ('mismatches', 'uncovered', 'uncovered_formulas', 'native_errors', 'control_mismatches')):
                raise ValueError('Original source contains unresolved financial findings')
            audit_data[module], audit_refs[module] = data, record
        if _read_ref(source['stability']).get('stable') is not True:
            raise ValueError('Original actual stability proof is missing')
        raw = output / 'presentation_raw.xlsx'
        presentation = present_composite_zero_schedules(original, raw, policy)
        _write(output / 'presentation.json', presentation)
        coverage = audited_zero_coverage(presentation['conversions'], audit_data)
        _write(output / 'original_independent_zero_coverage.json', coverage)
        equality = compare_exact_typed(original, raw, public_note=presentation['public_note'])
        allowlist = verify_formula_allowlist(original, raw, presentation['conversions'])
        _write(output / 'offline_exact_values.json', equality)
        _write(output / 'offline_formula_allowlist.json', allowlist)
        if equality['passed'] is not True or allowlist['passed'] is not True:
            raise ValueError('Raw presentation equivalence failed')
        receipt = {'schema_version': 1, 'status': 'offline_preflight_only_not_a_certified_source',
            'created_at': datetime.now(timezone.utc).isoformat(), 'selected': [], 'qualified': False, 'task_count': 0,
            'source_manifest': ref(source_manifest), 'original_source': ref(original), 'raw_presentation': ref(raw),
            'original_independent_audits': audit_refs, 'original_source_stability': source['stability'],
            'original_source_unique_cycle': True, 'source_original_ancestors': 2,
            'presentation': ref(output / 'presentation.json'),
            'independent_zero_coverage': ref(output / 'original_independent_zero_coverage.json'),
            'offline_value_equivalence': ref(output / 'offline_exact_values.json'),
            'offline_formula_allowlist': ref(output / 'offline_formula_allowlist.json'),
            'source_financial_audit_transferred': False, 'policy': policy, 'actual_LO_executions': 0, 'model_calls': 0,
            'pending_source_certification': ['Actual pinned-runtime full recalculation.',
                'Complete exact typed equivalence and formula allowlist after actual recalculation.',
                'Two additional actual recalculations with full exact typed stability.',
                'Explicit new-source audit-transfer receipts preserving old audit identities and scope.'],
            'pending_task_certification': ['Full D and all five controls.',
                'Every root active individually and marginally in the full mutation; mixed DAG/SCC local certificates.',
                'Normal independent public recovery, quality gates and fresh strongest evaluation.'],
            'counterfactual_global_uniqueness_claimed': False}
        _write(output / 'offline_source_receipt.json', receipt)
        return receipt
    except Exception as error:
        _write(output / 'rejection.json', {'reason': str(error), 'selected': [], 'qualified': False, 'task_count': 0})
        raise

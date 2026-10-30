"""Exact-zero presentation for the complete financial graph, offline only.

Every unmodified OOXML package part is copied byte for byte. The derived copy
is not admitted as a source by this module. Actual full typed equivalence,
pinned-runtime stability and honest audit transfer remain mandatory.
"""
from collections import Counter
from copy import copy
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from .composite_full_family_v2 import ADAPTER_ID, canonical_sha, inventory_complete_graph
from .composite_presentation_source import _read_ref, audited_zero_coverage
from .lease_family import MAIN, NS, _paths, compare_exact_typed, ref, sha
from .presentation_source import IMAGE_ID, verify_formula_allowlist

NOTE = ('Financial schedule presentation: exact zero monetary entries are supplied as fixed numeric '
    'constants with the same contractual source values. Preserve these constants, original inputs, calendars '
    'and regulatory reference context. Nullable owner-return formulas remain provided where no return is qualified.')


def _write(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def present_complete_zero_schedules(source, destination, scope_inventory):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError('Presentation output exists; attempts are immutable')
    if scope_inventory.get('adapter') != ADAPTER_ID or sha(source) != scope_inventory['source']['sha256']:
        raise ValueError('Complete scope is not bound to this original source')
    conversions, by_sheet = [], {}
    for family in scope_inventory['families']:
        for item in family['cells']:
            if item['source_kind'] != 'exact_numeric_zero':
                continue
            record = {'sheet': family['sheet'], 'cell': item['cell'],
                'family': family['algorithm'] + '/' + family['sheet'] + '/' + str(family['row']),
                'algorithm': family['algorithm'], 'field': family['field'],
                'original_formula_sha256': item['formula_sha256'],
                'original_cached_value': 0, 'provided_value': 0}
            conversions.append(record)
            by_sheet.setdefault(family['sheet'], {})[item['cell']] = record
    import openpyxl
    book = openpyxl.load_workbook(source, read_only=True, keep_links=False)
    try:
        note_row = book['Partner Contract'].max_row + 2
    finally:
        book.close()
    note_sheet = 'Partner Contract'
    with ZipFile(source) as original:
        paths = _paths(original)
        modified = {paths[name] for name in by_sheet} | {paths[note_sheet]}
        reverse = {path: name for name, path in paths.items()}
        with ZipFile(destination, 'x') as output:
            for info in original.infolist():
                raw = original.read(info.filename)
                name = reverse.get(info.filename)
                if info.filename in modified:
                    root = ET.fromstring(raw)
                    pending = dict(by_sheet.get(name, {}))
                    for cell in root.findall('.//m:sheetData/m:row/m:c', NS):
                        record = pending.pop(cell.get('r'), None)
                        if record is None:
                            continue
                        formula, value = cell.find('m:f', NS), cell.find('m:v', NS)
                        if (formula is None or value is None or Decimal(value.text) != 0
                                or cell.get('t') in ('b', 'd', 'e', 's', 'str', 'inlineStr')):
                            raise ValueError('A declared zero is not a finite numeric formula in raw XML')
                        text = '=' + (formula.text or '')
                        import hashlib
                        if hashlib.sha256(text.encode()).hexdigest() != record['original_formula_sha256']:
                            raise ValueError('Original formula differs from bound full scope')
                        record['original_formula'] = text
                        cell.remove(formula)
                        cell.set('t', 'n')
                        value.text = '0'
                    if pending:
                        raise ValueError('A declared zero is absent in raw XML')
                    if name == note_sheet:
                        row = ET.SubElement(root.find('m:sheetData', NS), '{' + MAIN + '}row', r=str(note_row))
                        cell = ET.SubElement(row, '{' + MAIN + '}c', r='A' + str(note_row), t='inlineStr')
                        ET.SubElement(ET.SubElement(cell, '{' + MAIN + '}is'), '{' + MAIN + '}t').text = NOTE
                        dimension = root.find('m:dimension', NS)
                        if dimension is not None:
                            end = dimension.get('ref').split(':')[-1]
                            import re
                            dimension.set('ref', 'A1:' + re.sub(r'\d+$', str(note_row), end))
                    raw = ET.tostring(root, encoding='utf-8')
                output.writestr(copy(info), raw)
        with ZipFile(destination) as output:
            unchanged = [i.filename for i in original.infolist() if i.filename not in modified]
            if any(original.read(name) != output.read(name) for name in unchanged):
                raise ValueError('An undeclared source package part changed')
    return {'adapter': ADAPTER_ID, 'source': ref(source), 'raw_presentation': ref(destination),
        'scope_inventory_sha256': canonical_sha(scope_inventory), 'conversions': conversions,
        'converted_formula_count': len(conversions),
        'counts_by_algorithm': dict(Counter(c['algorithm'] for c in conversions)),
        'changed_package_parts': sorted(modified), 'unchanged_package_part_count': len(unchanged),
        'public_note': {'sheet': note_sheet, 'cell': 'A' + str(note_row), 'value': NOTE},
        'provided_nullable_return_templates': scope_inventory.get('provided_nullable_return_templates', [])}


def prepare_complete_offline_presentation(source_manifest, output, policy):
    """Perform offline proof preflight; never grant financial source admission."""
    source_manifest, output = Path(source_manifest).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    try:
        source = json.loads(source_manifest.read_text())
        original = Path(source['local_path'])
        modules = {'lease', 'programme', 'operating', 'holding', 'contingent'}
        if (source.get('financial_audit_passed') is not True or set(source.get('financial_audits', {})) != modules
                or sha(original) != source['derived_workbook_sha256']
                or source.get('contingent_all_years_unique') is not True
                or source['runtime']['image_id'] != IMAGE_ID):
            raise ValueError('Original fully audited six-algorithm financial source is required')
        audits, audit_refs = {}, {}
        for module in sorted(modules):
            record = ref(source_manifest.parent / 'private' / (module + '_financial_audit.json'))
            audit = _read_ref(record)
            if (audit.get('passed') is not True or audit.get('workbook', {}).get('sha256') != sha(original)
                    or audit.get('checked_cells') != source['financial_audits'][module]['checked_cells']
                    or any(audit.get(k) for k in ('mismatches', 'uncovered', 'uncovered_formulas', 'native_errors', 'control_mismatches'))):
                raise ValueError('Original independent financial audit fails its own workbook/coverage binding')
            audits[module], audit_refs[module] = audit, record
        if _read_ref(source['stability']).get('stable') is not True:
            raise ValueError('Original actual stability is missing')
        scope = inventory_complete_graph(original, max_roots=policy.get('max_roots', 100000))
        _write(output / 'scope_inventory.json', scope)
        raw = output / 'presentation_raw.xlsx'
        presentation = present_complete_zero_schedules(original, raw, scope)
        _write(output / 'presentation.json', presentation)
        coverage = audited_zero_coverage(presentation['conversions'], audits)
        _write(output / 'original_independent_zero_coverage.json', coverage)
        equality = compare_exact_typed(original, raw, public_note=presentation['public_note'])
        allowlist = verify_formula_allowlist(original, raw, presentation['conversions'])
        _write(output / 'offline_exact_values.json', equality)
        _write(output / 'offline_formula_allowlist.json', allowlist)
        if equality.get('passed') is not True or allowlist.get('passed') is not True:
            raise ValueError('Offline exact typed source projection differs')
        receipt = {'schema_version': 2, 'adapter': ADAPTER_ID,
            'status': 'offline_only_not_a_certified_source', 'created_at': datetime.now(timezone.utc).isoformat(),
            'source_manifest': ref(source_manifest), 'original_source': ref(original), 'raw_presentation': ref(raw),
            'scope_inventory': ref(output / 'scope_inventory.json'),
            'presentation': ref(output / 'presentation.json'), 'original_independent_audits': audit_refs,
            'original_source_stability': source['stability'],
            'independent_zero_coverage': ref(output / 'original_independent_zero_coverage.json'),
            'offline_value_equivalence': ref(output / 'offline_exact_values.json'),
            'offline_formula_allowlist': ref(output / 'offline_formula_allowlist.json'),
            'policy': policy, 'policy_sha256': canonical_sha(policy), 'source_original_ancestors': 2,
            'source_financial_audit_transferred': False, 'actual_LO_executions': 0, 'model_calls': 0,
            'selected': [], 'qualified': False, 'task_count': 0,
            'pending': ['Actual full pinned-runtime financial source proof and two-pass exact typed stability.',
                'Explicit audit transfer or fresh independent audits bound to the new workbook SHA.',
                'Public table/JSON agreement and complete numeric timing proof before input-priority rule admission.',
                'All-root actual two-context activity, full D, five controls, public recovery and all quality gates.']}
        _write(output / 'offline_source_receipt.json', receipt)
        return receipt
    except Exception as error:
        _write(output / 'rejection.json', {'reason': str(error), 'selected': [], 'qualified': False})
        raise

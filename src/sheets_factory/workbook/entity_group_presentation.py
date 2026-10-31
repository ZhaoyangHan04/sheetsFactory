"""Text-only native business presentation for an existing entity-group book.

This module changes neither financial formulas nor primitive values. Its audit
is not source admission: new private recovery, actual source recalculation,
financial validation, quality and difficulty remain pending. No reconstruction
reader, canonical map, or executable joins are added to the agent workbook.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import stat
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from openpyxl.formula import Tokenizer
from openpyxl.utils.cell import column_index_from_string, coordinate_from_string
from .entity_group import spec as contract

NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
PKG_REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
MAX_MEMBER_BYTES = 2 * 1024**3
MAX_TOTAL_BYTES = 4 * 1024**3
SPEC_SHA256 = 'f98ae807d392bcfe79ef9ae7d9df12e226eb55ddc53fd0e5b4579835715fa509'
MODE = 'native_business_tables'
EXPECTED_SHEETS = ('Group Rules', 'Group Contract', 'Group Inputs', 'S01 Close', 'S02 Close', 'S03 Close')
_ALLOWED_FUNCTIONS = {'IF', 'AND', 'OR', 'INT', 'ABS', 'MOD', 'ROUND', 'MIN', 'MAX', 'SUM'}
_RANGE = re.compile(r"(?:(?:'((?:[^']|'')+)'|([A-Za-z_][A-Za-z0-9_ .]*))!)?(\$?[A-Za-z]{1,3}\$?[1-9][0-9]*)(?::(\$?[A-Za-z]{1,3}\$?[1-9][0-9]*))?\Z")


class PresentationHold(ValueError):
    """Unsupported source or incomplete proof; no successful admission."""


def _require(value, message):
    if not value:
        raise PresentationHold(message)


def _sha(data): return hashlib.sha256(data).hexdigest()


def _reference(path):
    path = Path(path).absolute()
    _require(path == path.resolve() and path.is_file(), 'Use a real regular source without symlink components')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024**2), b''): digest.update(chunk)
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': path.stat().st_size}


def _xml(data):
    _require(b'<!DOCTYPE' not in data.upper() and b'<!ENTITY' not in data.upper(), 'DTD and entity declarations are unsupported')
    try: return ET.fromstring(data, parser=ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True)))
    except ET.ParseError as error: raise PresentationHold('Malformed package XML') from error


def _serial(node):
    # ElementTree may rename prefixes. QName-valued extension attributes need
    # their original namespace scope, which this minimal adapter cannot prove.
    _require(not any(key.startswith('{http://schemas.openxmlformats.org/markup-compatibility/2006}')
                     or key == '{http://www.w3.org/2001/XMLSchema-instance}type'
                     for item in node.iter() for key in item.attrib),
             'Namespace-valued extension metadata requires a separate lexical adapter')
    return ET.tostring(node, encoding='utf-8', xml_declaration=True)


def _structure(node):
    return node.tag, tuple(sorted(node.attrib.items())), node.text, tuple(_structure(child) for child in node)


def _text(node):
    _require(node is not None, 'Missing plain string content')
    return ''.join(node.itertext())


def _flatten(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items(): yield from _flatten(item, (*path, key))
    elif isinstance(value, list):
        for key, item in enumerate(value): yield from _flatten(item, (*path, key))
    else: yield path, value


def _caption(text):
    text = str(text).replace('ic_', 'intercompany_').replace('asof_', 'effective_').replace('_', ' ')
    text = re.sub(r'\bFX\b', 'FX', text)
    return text[:1].upper() + text[1:]


def _input_label(path, public):
    """Ordinary visible context derived only from the source public primitives."""
    head, *rest = path
    root_labels = {'schema_version': 'Model format version', 'dimension_mode': 'Forecast dimension',
        'reporting_currency': 'Group reporting currency', 'fiscal_year_end_month': 'Fiscal year end month',
        'plan_policy': 'Investment mandate: supplied fixed choices', 'shared_bank_limit_gbp_pence': 'Shared bank limit [GBP pence]'}
    if not rest:
        _require(head in root_labels, 'Unknown root primitive has no business label')
        return root_labels[head]
    if head == 'months': return f'Forecast period {rest[0] + 1}: month starting date'
    if head == 'opening_fx_gbp_p12': return f'Opening FX for {rest[0]}: GBP pence per functional minor unit [numerator / 10^12]'
    if head == 'fixed_plan': return f'Fixed investment choice for project {rest[0]} [0=no, 1=yes]'
    if head in ('bank_priority', 'loan_priority'):
        return ('Shared bank funding' if head == 'bank_priority' else 'Intercompany funding') + f' priority {rest[0] + 1}'
    _require(head in ('entities', 'projects', 'bank_terms', 'intercompany_loans', 'intercompany_terms', 'scenarios'), 'Unknown native input family')
    record = public[head][rest[0]]; tail = rest[1:]
    _require(tail, 'A native table field is missing')
    if head == 'entities': context = f'Entity {record["id"]} ({record["currency"]})'
    elif head == 'projects': context = f'Project {record["id"]}; owner {record["entity_id"]} ({record["currency"]})'
    elif head == 'bank_terms':
        context = f'Entity {record["entity_id"]}; facility {record["facility_id"]} ({record["currency"]}); amendment effective {record["effective_month"]}'
    elif head in ('intercompany_loans', 'intercompany_terms'):
        identity = record.get('id', record.get('loan_id'))
        context = f'Loan {identity}: lender {record["lender_id"]}, borrower {record["borrower_id"]} ({record["currency"]})'
        if head == 'intercompany_terms': context += '; amendment effective ' + record['effective_month']
    else: context = 'Scenario ' + record['id']
    field = str(tail[0]); detail = _caption(field)
    if field == 'fx_gbp_p12': detail = 'Closing FX [GBP pence per functional minor unit; numerator / 10^12]'
    elif field.endswith('_p12'): detail = _caption(field[:-4]) + ' [numerator / 10^12]'
    elif field.endswith('_minor'): detail = _caption(field[:-6]) + ' [functional minor units]'
    elif field == 'opening_trap': detail = 'Opening cash restriction status [0=false, 1=true]'
    if len(tail) > 1: detail += '; ' + '; '.join(map(str, tail[1:]))
    return context + ' — ' + detail


def _close_label(text, sheet, public):
    parts = text.split('/')
    _require(len(parts) >= 2, 'A canonical close label lacks context')
    scenarios = set(contract.SCENARIOS)
    entities = {e['id']: e['currency'] for e in public['entities']}
    projects = {p['id']: p for p in public['projects']}
    loans = {p['id']: p for p in public['intercompany_loans']}
    currencies = {e['currency'] for e in public['entities']}
    result = []; field = parts[-1]
    for part in parts[:-1]:
        if part in scenarios: result.append('Scenario ' + part)
        elif part in entities: result.append('Entity ' + part + ' (' + entities[part] + ')')
        elif part in projects:
            p = projects[part]; result.append('Project ' + part + '; owner ' + p['entity_id'] + ' (' + p['currency'] + ')')
        elif part in loans:
            p = loans[part]; result.append('Loan ' + part + ': ' + p['lender_id'] + ' to ' + p['borrower_id'] + ' (' + p['currency'] + ')')
        elif part == 'group_FX': result.append('Group currency translation')
        elif part in currencies: result.append('Functional currency ' + part)
        elif re.fullmatch(r'\d{4}-\d{2}-01', part):
            _require(part in public['months'], 'A close label period is outside the supplied horizon'); result.append('Month ' + part)
        elif re.fullmatch(r'FY\d{4}', part): result.append('Fiscal year ending March ' + part[2:])
        else: raise PresentationHold('Unknown close label context; do not invent an opaque replacement')
    if not any(p.startswith('Scenario ') for p in result): result.insert(0, 'Scenario ' + sheet[:3])
    detail = _caption(field).replace('.whole', ' — exact whole component').replace('.remainder', ' — exact remainder component')
    if '_p12' in field: detail = _caption(field.replace('_p12', '')) + ' [numerator / 10^12]'
    elif 'gbp_pence' in field: detail += ' [GBP pence]'
    result.append(detail)
    return '; '.join(result)


class _Package:
    def __init__(self, path):
        self.parts = {}; self.info = []
        with ZipFile(path) as archive:
            self.comment = archive.comment
            _require(sum(entry.file_size for entry in archive.infolist()) <= MAX_TOTAL_BYTES, 'Workbook exceeds the declared package byte limit')
            names = archive.namelist()
            _require(len(names) == len(set(names)), 'Duplicate ZIP member names are unsupported')
            for entry in archive.infolist():
                name = entry.filename; pure = PurePosixPath(name)
                _require(not pure.is_absolute() and '..' not in pure.parts and '\\' not in name
                    and not entry.flag_bits & 1 and not stat.S_ISLNK(entry.external_attr >> 16), 'Unsafe ZIP member')
                _require(entry.file_size <= MAX_MEMBER_BYTES, 'A ZIP member exceeds the declared byte limit')
                _require(not name.startswith(('xl/embeddings/', 'customXml/')) and 'vbaProject' not in name,
                         'Embedded/active/custom XML packages need a separate audited adapter')
                self.info.append(deepcopy(entry)); self.parts[name] = archive.read(name)
        _require(sum(map(len, self.parts.values())) <= MAX_TOTAL_BYTES, 'Workbook exceeds the declared package byte limit')
        self.workbook = _xml(self.parts['xl/workbook.xml'])
        names_node = self.workbook.find('{'+NS+'}definedNames')
        _require(names_node is None or not len(names_node), 'Defined names require a separate reference proof')
        _require(not any(p.startswith('xl/externalLinks/') for p in self.parts), 'External formula links are unsupported')
        rels = _xml(self.parts['xl/_rels/workbook.xml.rels'])
        targets = {r.attrib['Id']: r.attrib for r in rels}
        self.sheets = {}; self.sheet_parts = {}
        for sheet in self.workbook.find('{'+NS+'}sheets'):
            relationship = targets[sheet.attrib['{'+REL+'}id']]
            _require(relationship.get('TargetMode') != 'External', 'External worksheet relationships are unsupported')
            target = relationship['Target']
            part = posixpath.normpath(target.lstrip('/') if target.startswith('/') else 'xl/' + target)
            _require(part.startswith('xl/worksheets/') and part in self.parts, 'Invalid worksheet part')
            name = sheet.attrib['name']; _require(name not in self.sheets, 'Duplicate worksheet name')
            self.sheets[name] = _xml(self.parts[part]); self.sheet_parts[name] = part
        _require(tuple(self.sheets) == EXPECTED_SHEETS, 'Only the unchanged six-sheet entity close layout is supported')
        self.sst = _xml(self.parts['xl/sharedStrings.xml']) if 'xl/sharedStrings.xml' in self.parts else None
        self.string_nodes = [] if self.sst is None else [item for item in self.sst if item.tag == '{'+NS+'}si']
        self.strings = [_text(item) for item in self.string_nodes]
        self.cells = {}; self.shared_users = defaultdict(set)
        for sheet, tree in self.sheets.items():
            for cell in tree.iter('{'+NS+'}c'):
                key = sheet, cell.attrib['r']; _require(key not in self.cells, 'Duplicate physical cell')
                self.cells[key] = cell
                if cell.attrib.get('t') == 's':
                    value = cell.find('{'+NS+'}v'); _require(value is not None and value.text is not None, 'Missing shared-string index')
                    index = int(value.text); _require(0 <= index < len(self.strings), 'Invalid shared-string index')
                    self.shared_users[index].add(key)

    def value(self, key):
        cell = self.cells.get(key)
        if cell is None: return None
        _require(cell.find('{'+NS+'}f') is None, 'A public primitive or text label cannot be a formula')
        kind = cell.attrib.get('t'); value = cell.find('{'+NS+'}v')
        if kind == 's': return self.strings[int(value.text)]
        if kind == 'inlineStr': return _text(cell.find('{'+NS+'}is'))
        if value is None or value.text is None: return None
        if kind in ('str', 'd', 'e'): return value.text
        if kind == 'b': return value.text == '1'
        try:
            numeric = Decimal(value.text)
            _require(numeric.is_finite(), 'Nonfinite native primitive')
            return int(numeric) if numeric == numeric.to_integral_value() else numeric
        except InvalidOperation as error: raise PresentationHold('Invalid numeric primitive') from error


def _signature(cell): return _structure(cell)


def _read_public(package):
    rows = sorted(int(address[1:]) for sheet, address in package.cells
                  if sheet == 'Group Contract' and address.startswith('B') and address != 'B1')
    pieces = [package.value(('Group Contract', 'B'+str(row))) for row in rows]
    _require(pieces and all(type(part) is str for part in pieces), 'The original complete public JSON is required')
    raw = ''.join(pieces)
    try: public = contract.load_spec(json.loads(raw))
    except (ValueError, TypeError, RecursionError) as error: raise PresentationHold('The original public contract is invalid') from error
    rows = sorted((int(address[1:]), package.value((sheet, address))) for sheet, address in package.cells
                  if sheet == 'Group Rules' and address.startswith('B'))
    _require([text for _, text in rows] == list(contract.PHASES) + list(contract.RULES), 'Keep all original phase and business policies verbatim')
    leaves = {'/'.join(map(str, path)): (path, value) for path, value in _flatten(public)}
    locations = {}; bool_count = 0
    for sheet, address in package.cells:
        if sheet != 'Group Inputs' or not re.fullmatch(r'A[2-9][0-9]*|A1[0-9]+', address): continue
        path = package.value((sheet, address)); _require(path in leaves and path not in locations, 'Native primitive labels are missing, unknown or duplicated')
        _, expected = leaves[path]; observed = package.value((sheet, 'B'+address[1:]))
        if type(expected) is bool:
            bool_count += 1; valid = type(observed) is int and observed == int(expected)
        else: valid = type(observed) is type(expected) and observed == expected
        _require(valid, 'A native primitive differs from the full public contract')
        locations[path] = (sheet, address)
    _require(set(locations) == set(leaves), 'Every public primitive must have its exact native counterpart')
    return public, leaves, locations, pieces, raw, bool_count


def _static_references(package, changed):
    by_col = defaultdict(lambda: defaultdict(list))
    for sheet, cell in changed:
        col, row = coordinate_from_string(cell); by_col[sheet][column_index_from_string(col)].append(row)
    for columns in by_col.values():
        for rows in columns.values(): rows.sort()
    functions = Counter(); references = 0; formulas = 0
    for (sheet, address), cell in package.cells.items():
        formula = cell.find('{'+NS+'}f')
        if formula is None: continue
        _require(formula.attrib.get('t', 'normal') == 'normal' and formula.text is not None,
                 'Shared, array or implicit formula definitions need a separate proof')
        formulas += 1
        try: tokens = Tokenizer('=' + formula.text).items
        except Exception as error: raise PresentationHold('Unsupported financial formula syntax') from error
        for token in tokens:
            if token.type == 'FUNC' and token.subtype == 'OPEN':
                function = token.value[:-1].upper(); _require(function in _ALLOWED_FUNCTIONS, 'Dynamic, lookup or unsupported formula function')
                functions[function] += 1
            if token.type != 'OPERAND' or token.subtype != 'RANGE': continue
            match = _RANGE.fullmatch(token.value)
            _require(match is not None, 'Only explicit static cell/range references are supported')
            target = (match[1] or match[2] or sheet).replace("''", "'")
            _require(target in package.sheets, 'Formula reference uses an unknown/external worksheet')
            c1, r1 = coordinate_from_string(match[3].replace('$', '')); c2, r2 = coordinate_from_string((match[4] or match[3]).replace('$', ''))
            x1, x2 = sorted((column_index_from_string(c1), column_index_from_string(c2))); y1, y2 = sorted((r1, r2))
            _require(x2 <= 16384 and y2 <= 1048576, 'Formula reference exceeds worksheet limits')
            references += 1
            for column, rows in by_col.get(target, {}).items():
                if x1 <= column <= x2:
                    index = bisect_left(rows, y1)
                    _require(index == len(rows) or rows[index] > y2, 'A financial formula depends on proposed changed text')
    return {'formula_definitions': formulas, 'static_reference_tokens': references,
            'functions': dict(functions), 'changed_text_is_unreferenced': True,
            'shared_array_dynamic_named_external_formulas_supported': False}


def _plain_text_cell(cell, package, key):
    _require(type(package.value(key)) is str and cell.find('{'+NS+'}f') is None, 'Only existing plain text cells may change')
    node = (package.string_nodes[int(cell.find('{'+NS+'}v').text)] if cell.attrib.get('t') == 's'
            else cell.find('{'+NS+'}is'))
    _require(node is not None and len(node) == 1 and node[0].tag == '{'+NS+'}t', 'Rich-text labels require a separate style-preserving adapter')


def _replace_text(cell, text):
    cell.attrib['t'] = 'inlineStr'
    for child in list(cell): cell.remove(child)
    content = ET.SubElement(cell, '{'+NS+'}is'); target = ET.SubElement(content, '{'+NS+'}t')
    target.attrib['{http://www.w3.org/XML/1998/namespace}space'] = 'preserve'; target.text = text


def _same_contract_object(text, public):
    decoder = json.JSONDecoder()
    offset = 0
    while True:
        start = text.find('{', offset)
        if start < 0: return False
        try:
            value, end = decoder.raw_decode(text[start:])
            if value == public: return True
        except (ValueError, RecursionError): pass
        offset = start + 1


def _no_payload(parts, obsolete, json_parts, public):
    canonical = re.compile(r'[A-Za-z][A-Za-z0-9_.-]*(?:/[A-Za-z0-9_.-]+)+')
    for name, data in parts.items():
        if not name.startswith('__') and name.endswith(('.xml', '.rels')):
            node = _xml(data); text = ''.join(node.itertext())
            _require(not any(piece and piece in text for piece in json_parts)
                     and not _same_contract_object(text, public), 'An obsolete JSON payload survives in a package part')
            _require(not any(value in obsolete for value in node.itertext())
                     and not any(match.group().rstrip('.') in obsolete for match in canonical.finditer(text)),
                     'An obsolete canonical label survives in a package part')
        else:
            text = data.decode('utf-8', errors='ignore')
            _require(not any(piece.encode() in data for piece in json_parts if piece)
                     and not _same_contract_object(text, public), 'An obsolete JSON payload survives in binary or ZIP metadata')
            _require(not any(match.group().rstrip('.') in obsolete for match in canonical.finditer(text)),
                     'An obsolete canonical label survives in binary or ZIP metadata')


def transform(source, destination_fresh, mode=MODE):
    """Materialize a fresh text-only presentation; return its PRIVATE static audit.

    This is an explicit source adapter, not task qualification. The old JSON
    reader/auditor are not relabelled as compatible with the new presentation.
    """
    _require(mode == MODE, 'Unsupported explicit presentation mode')
    _require(_reference(contract.__file__)['sha256'] == SPEC_SHA256, 'The frozen financial policy changed')
    source = Path(source).absolute(); before_ref = _reference(source)
    destination = Path(destination_fresh).absolute()
    _require(destination == destination.resolve() and not destination.exists() and destination != source,
             'Use a fresh destination without symlink components; never modify the source')
    package = _Package(source)
    public, leaves, locations, json_parts, raw, bool_count = _read_public(package)
    changed = {}
    for key, cell in package.cells.items():
        sheet, address = key
        if (sheet == 'Group Contract' and type(package.value(key)) is str
            and (address == 'A1' or (address.startswith('A') and re.fullmatch(r'JSON part [1-9][0-9]*', package.value(key)))
                 or (address.startswith('B') and address != 'B1'))):
            changed[key] = ('Model documentation: all numerical assumptions are in Group Inputs; policies remain in Group Rules.'
                            if address == 'A1' else 'Native business assumptions' if address.startswith('A') else '')
        elif sheet == 'Group Inputs' and address == 'A1': changed[key] = 'Business assumption / legal owner / reporting period'
        elif sheet.endswith(' Close') and address.startswith('A') and address != 'A1':
            value = package.value(key)
            if type(value) is str and '/' in value: changed[key] = _close_label(value, sheet, public)
    for path, key in locations.items(): changed[key] = _input_label(leaves[path][0], public)
    _require(len(set(changed[key] for key in locations.values())) == len(locations), 'Native labels must remain unambiguous')
    for key in changed: _plain_text_cell(package.cells[key], package, key)
    static = _static_references(package, changed)
    old_text = {package.value(key) for key in changed}
    before_signatures = {key: _signature(cell) for key, cell in package.cells.items()}
    before_attributes = {key: dict(cell.attrib) for key, cell in package.cells.items()}
    obsolete_indices = set()
    for index, text in enumerate(package.strings):
        if text in old_text or text == raw or ('{' in text and _same_contract_object(text, public)):
            _require(package.shared_users.get(index, set()) <= changed.keys(), 'A shared text value is also used by a nonallowlisted cell; HOLD')
            _require(len(package.string_nodes[index]) == 1 and package.string_nodes[index][0].tag == '{'+NS+'}t', 'Rich shared text needs a separate adapter')
            obsolete_indices.add(index)
    for key, replacement in changed.items(): _replace_text(package.cells[key], replacement)
    for index in obsolete_indices:
        node = package.string_nodes[index]
        for child in list(node): node.remove(child)
        ET.SubElement(node, '{'+NS+'}t').text = ''
    output_parts = dict(package.parts)
    changed_members = set()
    for sheet in {key[0] for key in changed}:
        part = package.sheet_parts[sheet]; output_parts[part] = _serial(package.sheets[sheet]); changed_members.add(part)
    if obsolete_indices:
        package.sst.attrib.pop('count', None); package.sst.attrib.pop('uniqueCount', None)
        output_parts['xl/sharedStrings.xml'] = _serial(package.sst); changed_members.add('xl/sharedStrings.xml')
    # Match whole obsolete labels, but only long JSON chunks. A one-character
    # numerical assumption must never be mistaken for a duplicate JSON payload.
    metadata = {'__archive_comment__': package.comment}
    for entry in package.info:
        metadata['__member_comment__'+entry.filename] = entry.comment
        metadata['__member_extra__'+entry.filename] = entry.extra
    _no_payload({**output_parts, **metadata}, old_text, [piece for piece in [*json_parts, raw] if len(piece) >= 32], public)
    _require(_reference(source) == before_ref, 'The source changed during its static presentation proof')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, 'x') as archive:
        archive.comment = package.comment
        for info in package.info: archive.writestr(info, output_parts[info.filename])
    checked = _Package(destination)
    _require(checked.comment == package.comment, 'The ZIP archive comment changed')
    original_info = {entry.filename: entry for entry in package.info}
    for entry in checked.info:
        prior = original_info[entry.filename]
        _require((entry.comment, entry.extra, entry.external_attr) == (prior.comment, prior.extra, prior.external_attr),
                 'ZIP member comment, extra data or attributes changed')
    _require(tuple(checked.sheets) == tuple(package.sheets) and checked.cells.keys() == package.cells.keys(), 'Worksheet order or physical cells changed')
    for key, cell in checked.cells.items():
        if key in changed:
            _require(checked.value(key) == changed[key], 'A native presentation label was not written exactly')
            _require({k:v for k,v in cell.attrib.items() if k != 't'} ==
                     {k:v for k,v in before_attributes[key].items() if k != 't'}, 'A changed label style or cell attribute changed')
        else: _require(_signature(cell) == before_signatures[key], 'An uneditable value/type/formula/cache/style changed')
    for name, data in package.parts.items():
        _require(name in changed_members or checked.parts[name] == data, 'A nonallowlisted package member changed')
    _require(_reference(source) == before_ref, 'The original workbook changed')
    changes = Counter(sheet for sheet, _ in changed)
    return {'kind': 'entity_group_native_business_presentation_static_audit', 'version': 1,
        'status': 'materialized_static_preservation_passed_financial_and_quality_pending', 'mode': mode,
        'private_only': True, 'agent_facing_reconstruction_reader_supplied': False,
        'source': before_ref, 'destination': _reference(destination), 'implementation': _reference(__file__),
        'financial_policy': _reference(contract.__file__), 'native_public_leaf_count': len(leaves),
        'explicit_boolean_as_integer_count': bool_count, 'all_native_primitive_values_preserved': True,
        'all_original_phases_and_rules_preserved': True, 'static_reference_proof': static,
        'changed_text_cells_by_sheet': dict(changes), 'changed_text_cell_count': len(changed),
        'shared_string_entries_scrubbed': len(obsolete_indices), 'complete_shared_string_usage_inventory_checked': True,
        'allowed_changed_members': sorted(changed_members),
        'package_members': {name: {'before_sha256': _sha(data), 'after_sha256': _sha(checked.parts[name]),
            'allowed_text_member_change': name in changed_members} for name, data in package.parts.items()},
        'uneditable_cells_and_formulas_and_cached_values_and_styles_preserved': True,
        'old_JSON_reader_compatibility_pending': True, 'new_private_source_only_recovery_pending': True,
        'new_source_financial_admission_and_actual_LO_pending': True, 'normal_quality_Harbor_and_difficulty_pending': True,
        'new_LO_calls': 0, 'model_calls': 0, 'qualified': False, 'task_count': 0}

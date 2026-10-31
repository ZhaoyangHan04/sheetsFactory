"""Public additive reporting over four unchanged local mandate workbooks.

The renderer writes formulas and public policies only. Certificate amounts
remain private expectations; no cached financial answers enter the workbook.
This pure module does not admit a source or repeat the four cold validators.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree as E
from zipfile import ZipFile, ZIP_DEFLATED

from openpyxl.utils import get_column_letter, quote_sheetname

from . import contract as c, stream_composition as base

SHEET = 'Group reporting'
S, R, P, C = base.S, base.R, base.P, base.C
COMPOSER_SHA256 = '7f0ff72c9a8a9cd6de949b9824d821174643453c740e8856117446cdec1094bb'
FIELDS = c.GROUP_FIELDS
FIELD_LABELS = ('New LP calls / GBP pence', 'Year-end debt / GBP pence',
    'LP distributions / GBP pence', 'Net LP cash flow / GBP pence', 'Asset net book value / GBP pence')
require, reference = base.require, base.reference


def _read(value):
    return json.loads(base._checked(value).read_text()) if isinstance(value, dict) and set(value) == {'path', 'sha256', 'bytes'} else value


def plan(public_contract, composed):
    """Plan all report cells using public mappings, never a winner vector."""
    public, composed = _read(public_contract), _read(composed)
    require(public['policies'] == c.POLICIES and public['group_fields'] == list(FIELDS)
        and public['scenario_ids'] == list(c.SCENARIOS) and public['years'] == list(c.YEARS),
        'Use the complete fixed public reporting and ringfencing contract')
    require([d['id'] for d in composed['donors']] == list(c.MANDATE_ORDER), 'Keep all four fixed mandates in order')
    if all('prefix' in d for d in composed['donors']):
        require([(d['id'], d['prefix']) for d in composed['donors']] == base.FIXED, 'Fixed mandate prefixes changed')
    require([m['id'] for m in public['mandates']] == list(c.MANDATE_ORDER), 'The report cannot omit a mandate')
    maps = {d['id']: d['sheet_map'] for d in composed['donors']}
    require(all(SHEET not in mapping.values() for mapping in maps.values()), 'Group report sheet already exists')
    def local(identity, sheet, cell):
        require(sheet in maps[identity], 'A required local reporting sheet is absent')
        prefix = next(m['sheet_prefix'] for m in public['mandates'] if m['id'] == identity)
        require(maps[identity][sheet] == prefix+sheet, 'Public contract and composer sheet namespaces differ')
        return quote_sheetname(maps[identity][sheet])+'!'+cell
    literals = {
        'A1': 'Four ringfenced mandates: group reporting',
        'A2': public['policies']['business_header'],
        'A3': 'FX conversion', 'B3': 'n/a (all mandates report GBP pence)',
        'A4': 'Interfund tax, debt and funding netting', 'B4': 'n/a (mandates remain legally ringfenced)',
        'A5': 'Each mandate retains its provided budgets, resources, tax accounts and funding rules. Group reporting creates no shared financial constraint.',
        'A6': 'All mandate choices complete and feasible',
        'A7': 'Selected group objective / sum of posted S01 NPVs / GBP pence',
        'A8': 'Aligned scenarios and fiscal years; selected local portfolios only. Monetary reports retain integer GBP pence.',
        **{get_column_letter(i)+'9': label for i, label in enumerate(('Scenario', 'Fiscal year', *FIELD_LABELS), 1)},
    }
    checks = [local(identity, 'Portfolio', point)+'=1' for identity in c.MANDATE_ORDER for point in ('B3', 'B369')]
    formulas = {'B6': '=AND('+','.join(checks)+')',
        'B7': '=IF($B$6,SUM('+','.join(local(identity, 'Portfolio', 'B370') for identity in c.MANDATE_ORDER)+'),"")'}
    financial = {'B6': {'kind': 'boolean', 'role': 'all_complete_and_feasible'},
        'B7': {'kind': 'integer_pence', 'role': 'objective'}}
    for si, scenario in enumerate(c.SCENARIOS):
        for yi, year in enumerate(c.YEARS):
            row, local_row = 10+si*20+yi, 5+si*20+yi
            literals['A'+str(row)] = scenario; literals['B'+str(row)] = 2026+year
            for fi, field in enumerate(FIELDS, 3):
                cell, original = get_column_letter(fi)+str(row), get_column_letter(fi)+str(local_row)
                formulas[cell] = '=IF($B$6,SUM('+','.join(local(identity, 'GroupSummary', original) for identity in c.MANDATE_ORDER)+'),"")'
                financial[cell] = {'kind': 'integer_pence', 'scenario': scenario, 'year': year,
                    'fiscal_year': 2026+year, 'field': field, 'local_cell': original}
    require(len(formulas) == len(financial) == 302 and set(formulas).isdisjoint(literals), 'Complete report census changed')
    return {'kind': 'pure_four_ringfenced_group_reporting_plan', 'version': 1, 'sheet': SHEET,
        'formulas': formulas, 'literals': literals, 'financial': financial,
        'added_geometry': {'sheets': 1, 'formulas': len(formulas), 'nonempty': len(formulas)+len(literals), 'targets': len(financial)},
        'standalone_local_coordinates_unchanged': True, 'cached_answers_written': False,
        'source_admitted': False, 'LO_calls': 0}


def expectations(certificate, report_plan):
    """Project retained independent certificate values, without financial solves.

    This checks shapes and exact integers; it is not a replacement for genuine
    composition.validate_certificate in the future producer entry.
    """
    certificate = _read(certificate); value = certificate['composition']
    require(certificate['mathematical_composition_certified'] is True
        and certificate['new_group_source_admitted'] is False and value['unique_best'] is True,
        'Use the mathematical composition certificate, not a group source claim')
    expected = {}
    for point, binding in report_plan['financial'].items():
        if binding['kind'] == 'boolean': expected[point] = {'type': 'boolean', 'value': True}; continue
        if binding.get('role') == 'objective': number = value['winner_objective_pence']
        else:
            row = value['winner_report'][binding['scenario']]['annual'][binding['year']-1]
            require(row['year'] == binding['year'] and row['fiscal_year'] == binding['fiscal_year']
                and set(row) == {'year', 'fiscal_year', *FIELDS}, 'The independent report periods or fields changed')
            number = row[binding['field']]
        require(type(number) is int and abs(number) < 2**53, 'Group monetary expectations require exact integer pence')
        expected[point] = {'type': 'number', 'value': str(number)}
    require(len(expected) == 302, 'All300 monetary fields, objective and boolean gate require expectations')
    return expected


def _worksheet(report):
    sheet = E.Element('{'+S+'}worksheet')
    E.SubElement(sheet, '{'+S+'}dimension', ref='A1:G69')
    columns = E.SubElement(sheet, '{'+S+'}cols')
    E.SubElement(columns, '{'+S+'}col', min='1', max='1', width='52', customWidth='1')
    E.SubElement(columns, '{'+S+'}col', min='2', max='7', width='25', customWidth='1')
    data = E.SubElement(sheet, '{'+S+'}sheetData'); rows = {}
    def row(index):
        if index not in rows: rows[index] = E.SubElement(data, '{'+S+'}row', r=str(index))
        return rows[index]
    def position(cell):
        from openpyxl.utils.cell import coordinate_to_tuple
        return coordinate_to_tuple(cell)
    points = sorted(set(report['formulas']) | set(report['literals']), key=position)
    for point in points:
        cell = E.SubElement(row(position(point)[0]), '{'+S+'}c', r=point, s='0')
        if point in report['formulas']:
            E.SubElement(cell, '{'+S+'}f').text = report['formulas'][point][1:]
        else:
            value = report['literals'][point]
            if type(value) is int: E.SubElement(cell, '{'+S+'}v').text = str(value)
            elif type(value) is bool: cell.set('t', 'b'); E.SubElement(cell, '{'+S+'}v').text = '1' if value else '0'
            else: cell.set('t', 'inlineStr'); E.SubElement(E.SubElement(cell, '{'+S+'}is'), '{'+S+'}t').text = value
    return E.tostring(sheet, encoding='UTF-8', xml_declaration=True)


def append_report(composed, public_contract, output):
    """Append one tiny report; stream-copy every other ZIP part unchanged.

    Inputs are renderer evidence, not source admission. A real producer must
    separately cold-validate the composition certificate before invoking this.
    Current pure assignment permits only fixture emission.
    """
    composed = _read(composed); public = _read(public_contract); report = plan(public, composed)
    require(reference(base.__file__)['sha256'] == COMPOSER_SHA256, 'The frozen streaming composer changed')
    require(composed['kind'] == 'uncalculated_ringfenced_group_stream_composition' and composed['new_group_source_admitted'] is False,
        'Use the complete uncalculated composition, never inherited source admission')
    original = base._checked(composed['output']); output = Path(output).absolute()
    require(output == output.resolve() and output.suffix == '.xlsx' and not output.exists(), 'Preserve the previous composition; use a fresh report output')
    geometry = {key: composed['geometry'][key]+report['added_geometry'][key] for key in ('formulas', 'nonempty', 'targets')}
    require(all(geometry[key] <= cap for key, cap in base.LIMITS.items()), 'The complete group report exceeds unchanged geometry ceilings')
    output.parent.mkdir(parents=True, exist_ok=True); changed_parts = []
    with TemporaryDirectory(prefix='.ringfenced-report-', dir=output.parent) as folder:
        pending = Path(folder)/'pending.xlsx'
        with ZipFile(original) as source, ZipFile(pending, 'w', ZIP_DEFLATED, compresslevel=6) as result:
            styles = E.fromstring(source.read('xl/styles.xml')); zero = styles.find('{'+S+'}cellXfs')[0]
            require(zero.get('numFmtId', '0') == '0', 'Report style0 must retain General, including Boolean results')
            workbook = E.fromstring(source.read('xl/workbook.xml')); sheets = workbook.find('{'+S+'}sheets')
            require(len(sheets) == composed['sheet_count'] and [n.get('name') for n in sheets] ==
                [name for donor in composed['donors'] for name in donor['sheet_map'].values()], 'Complete local sheet order or namespace changed')
            require(SHEET not in [n.get('name') for n in sheets], 'An existing group report cannot be replaced')
            rels = E.fromstring(source.read('xl/_rels/workbook.xml.rels')); rel_id = 'ringfenced_group_report'
            require(rel_id not in {r.get('Id') for r in rels}, 'Group report relationship collision')
            part = 'xl/worksheets/ringfenced_group_reporting.xml'; require(part not in source.namelist(), 'Group report part collision')
            sheet_id = max(int(n.get('sheetId')) for n in sheets)+1
            E.SubElement(sheets, '{'+S+'}sheet', name=SHEET, sheetId=str(sheet_id), attrib={'{'+R+'}id': rel_id})
            E.SubElement(rels, '{'+P+'}Relationship', Id=rel_id, Type=R+'/worksheet', Target='worksheets/ringfenced_group_reporting.xml')
            content = E.fromstring(source.read('[Content_Types].xml'))
            E.SubElement(content, '{'+C+'}Override', PartName='/'+part,
                ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml')
            changed = {'xl/workbook.xml': E.tostring(workbook), 'xl/_rels/workbook.xml.rels': E.tostring(rels),
                '[Content_Types].xml': E.tostring(content), part: _worksheet(report)}
            for info in source.infolist():
                if info.filename in changed: result.writestr(info.filename, changed.pop(info.filename)); changed_parts.append(info.filename)
                else:
                    with source.open(info.filename) as src, result.open(info.filename, 'w') as dst:
                        for chunk in iter(lambda: src.read(4*1024**2), b''): dst.write(chunk)
            for name, raw in changed.items(): result.writestr(name, raw); changed_parts.append(name)
        require(reference(original) == composed['output'] and not output.exists(), 'Original composition changed or output was concurrently claimed')
        pending.replace(output)
    return {'kind': 'uncalculated_four_ringfenced_group_with_public_report', 'version': 1,
        'output': reference(output), 'local_composition': deepcopy(composed), 'public_contract': deepcopy(public_contract),
        'report_plan': report, 'sheet_count': composed['sheet_count']+1, 'geometry': geometry,
        'changed_parts': changed_parts, 'all_local_sheet_parts_byte_identical': True,
        'report_formulas_uncached': True, 'private_expected_values_embedded': False,
        'new_group_source_admitted': False, 'qualified': False, 'LO_model_solver_Harbor_calls': 0}

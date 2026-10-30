"""Emit supplied contract terms and genuine same-year circular rent formulas.

This module imports no solver, financial journal or expected forecast values.
"""
from copy import deepcopy
from datetime import date
import json

from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .contract import validate_spec

SHEETS = {'inputs': 'Contingent Inputs', 'annual': 'Contingent Annual', 'contract': 'Contingent Contract'}
CONTRACT_INPUTS = ('active', 'rate', 'threshold', 'annual_cap', 'rounding_quantum', 'rounding_mode')
ANNUAL_ROWS = {'total_recovery_entitlement': 3, 'variable_rents.P01': 4, 'variable_rents.P02': 5,
               'variable_rents.P03': 6, 'variable_rents.P04': 7, 'variable_lease_cash': 8,
               'variable_lease_allowance': 9, 'variable_book_expense': 10, 'variable_tax_deduction': 11}
LABELS = {'total_recovery_entitlement': 'Same-year total regulatory recovery entitlement',
          'variable_rents.P01': 'P01 current variable cash rent', 'variable_rents.P02': 'P02 current variable cash rent',
          'variable_rents.P03': 'P03 current variable cash rent', 'variable_rents.P04': 'P04 current variable cash rent',
          'variable_lease_cash': 'Total current variable rent: cash paid',
          'variable_lease_allowance': 'Separately posted current variable regulatory allowance',
          'variable_book_expense': 'Current variable rent book expense',
          'variable_tax_deduction': 'Current variable rent tax deduction'}


def emit_contingent_workbook(book, spec, programme_annual_refs):
    """Return actual finance-formula refs for the caller's regulatory cycle.

    ``programme_annual_refs[year]['capital_entitlement']`` must mean total
    recovery entitlement INCLUDING this variable allowance and current tax.
    The caller feeds the returned variable cash and allowance back into that
    same year's taxable base, recovery, cash, income and funding settlement.
    """
    spec = validate_spec(spec)
    if set(programme_annual_refs) != set(range(2024, 2044)):
        raise ValueError('Explicit programme references for all twenty reporting years are required')
    for year in range(2024, 2044):
        if not isinstance(programme_annual_refs[year].get('capital_entitlement'), str):
            raise ValueError('A genuine programme total recovery entitlement reference is required')
    if any(name in book.sheetnames for name in SHEETS.values()):
        raise ValueError('Contingent-recovery sheet names must be new and unique')
    inputs = book.create_sheet(SHEETS['inputs'])
    annual = book.create_sheet(SHEETS['annual'])
    policy = book.create_sheet(SHEETS['contract'])
    inputs['A1'] = 'Supplied same-year contingent-rent terms; nominal GBP'
    inputs['A2'], inputs['A3'] = 'Reporting year starts', 'Reporting year ends'
    inputs['A4'] = 'Separately posted variable expense eligibility fraction'
    annual['A1'] = 'Same-year contingent rents and recovery feedback; nominal GBP'
    annual['A2'] = 'Reporting year ends'
    for field, row in ANNUAL_ROWS.items():
        annual.cell(row, 1, LABELS[field])
    input_rows = {}
    for index, identity in enumerate(('P01', 'P02', 'P03', 'P04')):
        input_rows[identity] = {}
        for offset, field in enumerate(CONTRACT_INPUTS):
            row = 7 + index * len(CONTRACT_INPUTS) + offset
            input_rows[identity][field] = row
            inputs.cell(row, 1, identity + ' supplied ' + field.replace('_', ' '))
    input_bindings, calendar_bindings, cell_bindings, refs = [], [], [], {}
    for index, terms in enumerate(spec['annual_terms']):
        year, column = terms['year'], index + 3
        col = get_column_letter(column)
        for ws in (inputs, annual):
            ws.cell(1, column, year)
            calendar_bindings.append({'sheet': ws.title, 'cell': col + '1', 'year': year, 'field': 'year'})
        for row, field, value in [(2, 'period_start', date(year - 1, 4, 1)), (3, 'period_end', date(year, 3, 31))]:
            inputs.cell(row, column, value).number_format = 'yyyy-mm-dd'
            calendar_bindings.append({'sheet': inputs.title, 'cell': col + str(row), 'year': year, 'field': field})
        annual.cell(2, column, date(year, 3, 31)).number_format = 'yyyy-mm-dd'
        calendar_bindings.append({'sheet': annual.title, 'cell': col + '2', 'year': year, 'field': 'period_end'})
        inputs.cell(4, column, float(terms['eligible_fraction'])).number_format = '0.000000%'
        input_bindings.append({'sheet': inputs.title, 'cell': col + '4', 'year': year, 'field': 'eligible_fraction'})
        contracts = {contract['lease_id']: contract for contract in terms['contracts']}
        for identity, contract in contracts.items():
            for field, row in input_rows[identity].items():
                value = contract[field] if field in {'active', 'rounding_mode'} else float(contract[field])
                inputs.cell(row, column, value)
                input_bindings.append({'sheet': inputs.title, 'cell': col + str(row), 'year': year,
                                       'lease_id': identity, 'field': field})
        annual.cell(3, column, '=' + programme_annual_refs[year]['capital_entitlement'])
        for identity in ('P01', 'P02', 'P03', 'P04'):
            def term(field):
                return "'" + inputs.title + "'!" + col + str(input_rows[identity][field])
            formula = (f'=IF({term("active")},MIN({term("annual_cap")},'
                       f'ROUND({term("rate")}*MAX(0,{col}3-{term("threshold")})/'
                       f'{term("rounding_quantum")},0)*{term("rounding_quantum")}),0)')
            annual.cell(ANNUAL_ROWS['variable_rents.' + identity], column, formula)
        annual.cell(8, column, f'=SUM({col}4:{col}7)')
        annual.cell(9, column, f'=ROUND({col}8*\'{inputs.title}\'!{col}4,2)')
        annual.cell(10, column, f'={col}8')
        annual.cell(11, column, f'={col}8')
        refs[year] = {}
        for field, row in ANNUAL_ROWS.items():
            address = col + str(row)
            refs[year][field] = "'" + annual.title + "'!" + address
            cell_bindings.append({'sheet': annual.title, 'cell': address, 'year': year, 'field': field, 'kind': 'money'})
            annual.cell(row, column).number_format = '#,##0.00;[Red](#,##0.00)'
    policy['A1'] = 'Public contractual rules: current variable rent and same-year recovery'
    policy['A2'] = 'Supplied JSON terms only; no calculated forecast or reference amounts'
    policy['B2'] = json.dumps(spec, ensure_ascii=False, separators=(',', ':'))
    if len(policy['B2'].value) > 32000:
        raise ValueError('The explicit public contract exceeds the safe Excel cell length')
    for row, text in enumerate(spec['public_rules'], 4):
        policy.cell(row, 1, text)
    for ws in (inputs, annual):
        ws.freeze_panes = 'C4'
        ws.column_dimensions['A'].width = 63
        for column in range(3, 23):
            ws.column_dimensions[get_column_letter(column)].width = 18
        for cell in ws[1]:
            cell.font = Font(bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='244A64')
    policy.column_dimensions['A'].width = 115
    policy.column_dimensions['B'].width = 115
    return {'schema_version': 1, 'sheets': deepcopy(SHEETS), 'annual_refs': refs,
            'cell_bindings': cell_bindings, 'input_bindings': input_bindings,
            'calendar_bindings': calendar_bindings, 'public_spec_cell': {'sheet': policy.title, 'cell': 'B2'},
            'public_rule_cells': [{'sheet': policy.title, 'cell': 'A' + str(row)} for row in range(4, 4 + len(spec['public_rules']))],
            'public_spec': deepcopy(spec), 'formula_count': len(cell_bindings),
            'rounding_units': ['100', '1000'], 'cycle_basis': 'programme capital_entitlement'}

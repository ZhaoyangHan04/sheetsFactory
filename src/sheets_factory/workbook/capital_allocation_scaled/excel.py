"""Prospective dynamic-dimension capital formula emitter.

The financial loop is an explicit copy of the SHA-bound original emitter.
Its exact arithmetic compiler is reused without mutation. Public schema labels
are explicit from the first template. No optimiser or ledger is imported.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import re

from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

from ..capital_allocation import excel as arithmetic_module
from ..capital_allocation import spec as original_schema
from .spec import SCALE, load_spec, project_ids

ExactArithmetic = arithmetic_module.ExactArithmetic
expression_formula = arithmetic_module.expression_formula
UPSTREAM_EXCEL_SHA256 = 'fbf80d60d7d4ba78cde1e7af71473880da674a8a5f9a11ffe97ac950e8b02a7a'
UPSTREAM_SCHEMA_SHA256 = 'e943eac9e5f139b8957a86e4e5c1c679be5a5be7aa596cf17e9b1f9aa8eb0f94'

PUBLIC_PROJECT_RULE = (
    'Every scenario Projects sheet is the complete, unweighted candidate schedule for EVERY listed project, including projects with common binary choice 0. '
    'Populate each candidate capex, revenue, opex, depreciation, sale proceeds, sale carrying, sale gain, closing book and certified NAV without multiplying by its investment choice. '
    'Only the scenario Annual aggregates multiply each candidate project amount by its common Investment Plan choice. Do not zero an unselected project candidate schedule.'
)
PUBLIC_SUMMARY_RULE = (
    'Capital Summary rows 3, 4, 5 correspond to S01, S02, S03. Column B is scenario feasible flag 1 or 0; column C is diagnostic LP NPV in pence even when infeasible; column D is feasible LP NPV in pence or empty when infeasible. '
    'Capital Summary B7 is all-scenarios-feasible flag 1 or 0; D7 is the minimum of the three feasible scenario NPVs, or empty when any scenario is infeasible. '
    'Summary column C is not a funding-gap column; the Annual funding_gap row carries that amount.'
)
PUBLIC_RULES = (original_schema.RULES[0].replace('eighteen', 'supplied'),
                *original_schema.RULES[1:], PUBLIC_PROJECT_RULE, PUBLIC_SUMMARY_RULE)


def _reference(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size}


def assert_upstream_recipe():
    math_ref, schema_ref = _reference(arithmetic_module.__file__), _reference(original_schema.__file__)
    if math_ref['sha256'] != UPSTREAM_EXCEL_SHA256 or schema_ref['sha256'] != UPSTREAM_SCHEMA_SHA256:
        raise ValueError('The reused arithmetic/schema implementation changed; review the copied financial loop')
    return {'scaled_emitter': _reference(__file__), 'scaled_schema': _reference(Path(__file__).with_name('spec.py')),
            'exact_arithmetic': math_ref, 'financial_field_schema': schema_ref}


def public_rules(count):
    project_ids(count)
    if 'same eighteen binary' not in original_schema.RULES[0]:
        raise ValueError('The original public rule identity changed')
    return PUBLIC_RULES


def validate_declared_plan(plan, ids):
    if not isinstance(plan, dict) or set(plan) != set(ids) or any(type(plan[p]) is not int or plan[p] not in (0, 1) for p in ids):
        raise ValueError('Supply the complete common integer 0/1 plan for this exact public dimension')
    return dict(plan)


def label_public_schema(book, count):
    summary = book['Capital Summary']
    labels = {'A2': 'Scenario / combined plan', 'B2': 'Feasible flag: 1 yes, 0 no',
        'C2': 'Diagnostic LP NPV (pence)', 'D2': 'Feasible LP NPV (pence; empty if infeasible)',
        'A7': 'All scenarios feasible (B7); worst feasible LP NPV in pence (D7)'}
    for cell, text in labels.items():
        summary[cell] = text
    candidate_headers = {}
    for sid in ('S01', 'S02', 'S03'):
        sheet = book[sid + ' Projects']
        sheet['A1'] = sid + ' complete UNWEIGHTED candidate schedules for all ' + str(count) + ' projects; Annual applies common choices'
        candidate_headers[sheet.title] = 'A1'
    return {'version': 1, 'project_count': count, 'summary_labels': labels,
        'candidate_headers': candidate_headers,
        'project_schedule_convention': 'complete_unweighted_candidates_including_unselected_projects',
        'annual_aggregation_convention': 'candidate_amount_times_common_binary_choice',
        'summary_schema': {'B3:B5': 'scenario_feasible_flag', 'C3:C5': 'diagnostic_npv_pence',
            'D3:D5': 'feasible_npv_pence_or_empty', 'B7': 'all_scenarios_feasible_flag', 'D7': 'worst_feasible_npv_pence_or_empty'},
        'rules': [PUBLIC_PROJECT_RULE, PUBLIC_SUMMARY_RULE], 'quality_or_difficulty_certified': False}


def emit_capital_allocation_workbook(book, spec, plan=None):
    """Emit one shared plan and three forward financial forecasts.

    ``plan=None`` leaves decision cells empty. A caller must independently
    validate a complete unique-best search certificate before supplying gold
    choices with both prospective independent kernels; this emitter has no
    optimiser or ledger access and does not certify that external proof.
    """
    from ..capital_allocation.spec import (ANNUAL_FIELDS, PROJECT_FIELDS,
                       SCENARIO_IDS, VINTAGE_FIELDS, YEARS)
    assert_upstream_recipe()
    spec = load_spec(spec)
    PROJECT_IDS = project_ids(len(spec['projects']))
    RULES = public_rules(len(PROJECT_IDS))
    plan = None if plan is None else validate_declared_plan(plan, PROJECT_IDS)
    if book.sheetnames:
        raise ValueError('The capital-allocation emitter requires an empty workbook')
    rules = book.create_sheet('Capital Rules')
    contract = book.create_sheet('Capital Contract')
    inputs = book.create_sheet('Capital Inputs')
    decisions = book.create_sheet('Investment Plan')
    summary = book.create_sheet('Capital Summary')
    arithmetic = ExactArithmetic(book.create_sheet('Exact Arithmetic'))
    input_bindings, financial_bindings, decision_bindings, refs = [], [], [], {}
    def ref(sheet, address):
        return "'" + sheet.replace("'", "''") + "'!" + re.sub(r'([A-Z]+)([0-9]+)', r'$\1$\2', address)
    def flatten(value, path=()):
        if isinstance(value, dict):
            for key, child in value.items(): yield from flatten(child, (*path, key))
        elif isinstance(value, list):
            for index, child in enumerate(value): yield from flatten(child, (*path, index))
        else:
            yield path, value
    inputs['A1'], inputs['B1'] = 'Supplied public primitive (JSON path)', 'Exact supplied value'
    for row, (path, value) in enumerate(flatten(spec), 3):
        inputs.cell(row, 1, '/'.join(map(str, path)))
        cell = inputs.cell(row, 2, value)
        if type(value) is int: cell.number_format = '0'
        refs[path] = ref(inputs.title, cell.coordinate)
        input_bindings.append({'sheet': inputs.title, 'cell': cell.coordinate, 'path': list(path)})
    def inp(*path): return refs[path]
    rules['A1'] = 'Synthetic capital allocation: public accounting and optimisation contract'
    rules['A2'] = 'GBP pence; one common binary plan; no scenario-specific investment decisions'
    for row, text in enumerate(RULES, 4): rules.cell(row, 1, text)
    contract['A1'] = 'Complete supplied JSON primitives; concatenate B2 onward in order'
    raw = json.dumps(spec, ensure_ascii=False, separators=(',', ':'))
    chunks = []
    for row, offset in enumerate(range(0, len(raw), 30000), 2):
        contract.cell(row, 1, 'JSON part ' + str(row - 1))
        contract.cell(row, 2, raw[offset:offset + 30000])
        chunks.append({'sheet': contract.title, 'cell': 'B' + str(row)})
    decisions['A1'] = 'Common binary choice for each of ' + str(len(PROJECT_IDS)) + ' candidate projects; one shared plan across scenarios'
    decisions['A2'], decisions['B2'] = 'Project', 'Common binary choice: 0 or 1'
    choice = {}
    validation = DataValidation(type='whole', operator='between', formula1=0, formula2=1, allow_blank=False)
    validation.errorTitle, validation.error = 'A common binary choice is required', 'Enter 0 or 1.'
    validation.showErrorMessage = True; decisions.add_data_validation(validation)
    for row, identifier in enumerate(PROJECT_IDS, 3):
        decisions.cell(row, 1, identifier)
        cell = decisions.cell(row, 2)
        if plan is not None: cell.value = '=' + str(plan[identifier])
        validation.add(cell)
        choice[identifier] = ref(decisions.title, cell.coordinate)
        decision_bindings.append({'sheet': decisions.title, 'cell': cell.coordinate,
                                  'project_id': identifier, 'kind': 'binary', 'target_eligible': True})
    def put(sheet, address, expression, expected_path, *, kind='integer'):
        formula = '=' + expression_formula(expression)
        sheet[address] = formula
        sheet[address].number_format = '0'
        financial_bindings.append({'sheet': sheet.title, 'cell': address, 'formula': formula,
            'expected_path': expected_path, 'kind': kind, 'target_eligible': True})
        return ref(sheet.title, address)
    scenario_refs, project_refs, vintage_refs = {}, {}, {}
    for scenario_index, identity in enumerate(SCENARIO_IDS):
        arithmetic.plan_dependent = False
        project_sheet = book.create_sheet(identity + ' Projects')
        annual_sheet = book.create_sheet(identity + ' Annual')
        vintage_sheet = book.create_sheet(identity + ' Tax Vintages')
        for sheet in (project_sheet, annual_sheet, vintage_sheet):
            sheet['A1'] = identity + ' forward accounting; integer pence'
            for index, year in enumerate(YEARS, 3):
                sheet.cell(2, index, date(year, 3, 31)).number_format = 'yyyy-mm-dd'
        p_refs = {identifier: {year: {} for year in YEARS} for identifier in PROJECT_IDS}
        for pi, identifier in enumerate(PROJECT_IDS):
            for fi, field in enumerate(PROJECT_FIELDS):
                row = 4 + pi * len(PROJECT_FIELDS) + fi
                project_sheet.cell(row, 1, identifier); project_sheet.cell(row, 2, field)
                for yi, year in enumerate(YEARS):
                    p_refs[identifier][year][field] = ref(project_sheet.title, get_column_letter(yi + 3) + str(row))
        a_refs = {year: {} for year in YEARS}
        for fi, field in enumerate(ANNUAL_FIELDS, 4):
            annual_sheet.cell(fi, 1, field)
            for yi, year in enumerate(YEARS):
                a_refs[year][field] = ref(annual_sheet.title, get_column_letter(yi + 3) + str(fi))
        v_refs = {year: {origin: {} for origin in YEARS} for year in YEARS}
        for vi, origin in enumerate(YEARS):
            for fi, field in enumerate(VINTAGE_FIELDS):
                row = 4 + vi * len(VINTAGE_FIELDS) + fi
                vintage_sheet.cell(row, 1, origin); vintage_sheet.cell(row, 2, field)
                for yi, year in enumerate(YEARS):
                    v_refs[year][origin][field] = ref(vintage_sheet.title, get_column_letter(yi + 3) + str(row))
        def supplied(field, year): return inp('scenarios', scenario_index, field, str(year))
        for pi, identifier in enumerate(PROJECT_IDS):
            cost = inp('projects', pi, 'acquisition_cost_pence')
            commission = inp('projects', pi, 'commission_year')
            sale = inp('projects', pi, 'sale_year')
            life = inp('projects', pi, 'depreciation_years')
            for yi, year in enumerate(YEARS):
                values = p_refs[identifier][year]
                old_book = p_refs[identifier][YEARS[yi - 1]]['closing_book_value'] if yi else 0
                age = ('sub', year, commission)
                active = ('and', ('lt', commission, year), ('le', year, sale), ('le', age, life))
                label = identity + '.' + identifier + '.' + str(year)
                revenue = arithmetic.round_project_factor(inp('projects', pi, 'annual_revenue_pence', str(year)),
                    supplied('revenue_factors_p12', year), label + '.revenue')
                opex = arithmetic.round_project_factor(inp('projects', pi, 'annual_opex_pence', str(year)),
                    supplied('opex_factors_p12', year), label + '.opex')
                proceeds = arithmetic.round_project_factor(inp('projects', pi, 'sale_proceeds_pence'),
                    supplied('sale_factors_p12', year), label + '.sale')
                nav = arithmetic.round_project_factor(values['closing_book_value'], supplied('nav_factors_p12', year), label + '.NAV')
                formulas = {'capex': ('if', ('eq', year, commission), cost, 0),
                    'revenue': revenue, 'opex': opex,
                    'depreciation': ('if', active, ('if', ('eq', age, life), old_book,
                        ('min', old_book, ('max', 0, ('rounddiv', cost, life)))), 0),
                    'sale_proceeds': ('if', ('eq', year, sale), proceeds, 0),
                    'sale_carrying': ('if', ('eq', year, sale), ('sub', old_book, values['depreciation']), 0),
                    'sale_gain': ('sub', values['sale_proceeds'], values['sale_carrying']),
                    'closing_book_value': ('if', ('eq', year, commission), cost,
                        ('if', ('lt', commission, year), ('sub', ('sub', old_book, values['depreciation']), values['sale_carrying']), 0)),
                    'certified_nav': nav}
                for fi, field in enumerate(PROJECT_FIELDS):
                    address = get_column_letter(yi + 3) + str(4 + pi * len(PROJECT_FIELDS) + fi)
                    put(project_sheet, address, formulas[field], ['scenarios', identity, 'project_flows', identifier, yi, field])
        arithmetic.plan_dependent = True
        for yi, year in enumerate(YEARS):
            col, current = get_column_letter(yi + 3), a_refs[year]
            old = a_refs[YEARS[yi - 1]] if yi else {}
            def previous(field, first=0): return old[field] if yi else first
            def annual_sum(field):
                return ('sum', *(('mul', p_refs[identifier][year][field], choice[identifier]) for identifier in PROJECT_IDS))
            def vintages(field): return ('sum', *(v_refs[year][origin][field] for origin in YEARS))
            for vi, origin in enumerate(YEARS):
                vintage = v_refs[year][origin]
                opening = v_refs[YEARS[yi - 1]][origin]['closing'] if yi else 0
                used_older = ('sum', *(v_refs[year][before]['used'] for before in YEARS if before < origin))
                values = {'opening': opening,
                    'expired': ('if', ('lt', inp('tax_loss_carry_years'), year - origin), vintage['opening'], 0),
                    'used': ('if', ('lt', origin, year), ('min', ('sub', vintage['opening'], vintage['expired']),
                        ('max', 0, ('sub', current['taxable_before_losses'], used_older))), 0),
                    'created': ('if', ('eq', origin, year), ('max', 0, ('sub', 0, current['taxable_before_losses'])), 0),
                    'closing': ('sum', ('sub', ('sub', vintage['opening'], vintage['expired']), vintage['used']), vintage['created'])}
                for fi, field in enumerate(VINTAGE_FIELDS):
                    put(vintage_sheet, col + str(4 + vi * len(VINTAGE_FIELDS) + fi), values[field],
                        ['scenarios', identity, 'tax_vintages', yi * len(YEARS) + vi, field])
            minimum = 0 if year == YEARS[-1] else inp('minimum_cash_pence')
            interest = arithmetic.round_product((current['bank_open'], supplied('bank_rates_p12', year)), 2,
                                               identity + '.' + str(year) + '.interest')
            tax = arithmetic.round_product((current['taxable_after_losses'], inp('tax_rate_p12')), 2,
                                          identity + '.' + str(year) + '.tax')
            collateral = arithmetic.round_product((current['prior_certified_nav'], inp('advance_rate_p12'),
                ('sub', SCALE, supplied('haircuts_p12', year))), 4, identity + '.' + str(year) + '.collateral')
            remaining_debt = ('sub', ('sub', current['bank_open'], current['mandatory_margin']), current['optional_repayment'])
            cash_bridge = ('sub', ('sum', current['cash_open'], current['revenue'], current['sale_proceeds']),
                ('sum', current['opex'], current['capex'], current['bank_interest'], current['current_tax']))
            values = {'cash_open': previous('cash_close', inp('opening_cash_pence')),
                'bank_open': previous('bank_close'), 'capital_open': previous('capital_close', inp('opening_cash_pence')),
                'retained_open': previous('retained_close'), 'lp_called_open': previous('lp_called_close'),
                'prior_certified_nav': previous('certified_nav'),
                **{field: annual_sum(field) for field in ('revenue', 'opex', 'capex', 'depreciation', 'sale_proceeds', 'sale_carrying', 'sale_gain', 'certified_nav')},
                'bank_interest': interest,
                'taxable_before_losses': ('sub', ('sum', current['revenue'], current['sale_gain']),
                    ('sum', current['opex'], current['depreciation'], current['bank_interest'])),
                'loss_open': vintages('opening'), 'loss_expired': vintages('expired'), 'loss_used': vintages('used'),
                'loss_created': vintages('created'), 'loss_close': vintages('closing'),
                'taxable_after_losses': ('max', 0, ('sub', current['taxable_before_losses'], current['loss_used'])),
                'current_tax': tax, 'net_income': ('sub', current['taxable_before_losses'], current['current_tax']),
                'borrowing_base': 0 if year == YEARS[-1] else ('min', inp('facility_limit_pence'), collateral),
                'cash_before_financing': cash_bridge,
                'mandatory_margin': ('max', 0, ('sub', current['bank_open'], current['borrowing_base'])),
                'cash_after_margin': ('sub', current['cash_before_financing'], current['mandatory_margin']),
                'optional_repayment': ('min', ('sub', current['bank_open'], current['mandatory_margin']),
                    ('max', 0, ('sub', current['cash_after_margin'], minimum))),
                'cash_after_optional': ('sub', current['cash_after_margin'], current['optional_repayment']),
                'bank_draw': ('min', ('max', 0, ('sub', current['borrowing_base'], remaining_debt)),
                    ('max', 0, ('sub', minimum, current['cash_after_optional']))),
                'lp_required': ('max', 0, ('sub', ('sub', minimum, current['cash_after_optional']), current['bank_draw'])),
                'lp_call': ('min', current['lp_required'], ('max', 0, ('sub', inp('lp_commitment_pence'), current['lp_called_open']))),
                'funding_gap': ('sub', current['lp_required'], current['lp_call']),
                'cash_before_distribution': ('sum', current['cash_after_optional'], current['bank_draw'], current['lp_call']),
                'equity_before_distribution': ('sum', current['capital_open'], current['lp_call'], current['retained_open'], current['net_income']),
                'distribution': ('min', ('max', 0, ('sub', current['cash_before_distribution'], minimum)), ('max', 0, current['equity_before_distribution'])),
                'return_of_capital': ('min', current['distribution'], ('sum', current['capital_open'], current['lp_call'])),
                'profit_distribution': ('sub', current['distribution'], current['return_of_capital']),
                'net_lp_cashflow': ('sub', current['distribution'], current['lp_call']),
                'lp_called_close': ('sum', current['lp_called_open'], current['lp_call']),
                'lp_remaining': ('sub', inp('lp_commitment_pence'), ('sum', current['lp_called_open'], current['lp_call'])),
                'cash_close': ('sub', current['cash_before_distribution'], current['distribution']),
                'bank_close': ('sum', remaining_debt, current['bank_draw']),
                'capital_close': ('sub', ('sum', current['capital_open'], current['lp_call']), current['return_of_capital']),
                'retained_close': ('sub', ('sum', current['retained_open'], current['net_income']), current['profit_distribution']),
                'project_book_value': annual_sum('closing_book_value'),
                'total_assets': ('sum', current['cash_close'], current['project_book_value']),
                'total_liabilities': current['bank_close'],
                'total_equity': ('sum', current['capital_close'], current['retained_close']),
                'balance_check': ('sub', current['total_assets'], ('sum', current['total_liabilities'], current['total_equity'])),
                'cash_check': ('sub', current['cash_close'], ('sub', ('sum', cash_bridge, current['bank_draw'], current['lp_call']),
                    ('sum', current['mandatory_margin'], current['optional_repayment'], current['distribution']))),
                'bank_check': ('sub', current['bank_close'], ('sum', remaining_debt, current['bank_draw'])),
                'capital_check': ('sub', current['capital_close'], ('sub', ('sum', current['capital_open'], current['lp_call']), current['return_of_capital'])),
                'loss_check': ('sub', current['loss_close'], ('sub', ('sum', current['loss_open'], current['loss_created']), ('sum', current['loss_expired'], current['loss_used'])))}
            if set(values) != set(ANNUAL_FIELDS): raise ValueError('Independent annual field schema changed')
            for fi, field in enumerate(ANNUAL_FIELDS, 4):
                put(annual_sheet, col + str(fi), values[field], ['scenarios', identity, 'annual', yi, field])
        scenario_refs[identity], project_refs[identity], vintage_refs[identity] = a_refs, p_refs, v_refs
    summary['A1'] = 'One shared plan: scenario feasibility and maximin LP present value'
    summary_refs = {}
    for index, identity in enumerate(SCENARIO_IDS, 3):
        summary.cell(index, 1, identity)
        annual = scenario_refs[identity]
        end = annual[YEARS[-1]]
        feasible = ('and', *(('eq', annual[year]['funding_gap'], 0) for year in YEARS),
                    ('eq', end['bank_close'], 0), ('eq', end['project_book_value'], 0), ('eq', end['cash_close'], 0))
        flag = put(summary, 'B' + str(index), ('if', feasible, 1, 0), ['scenarios', identity, 'feasible'], kind='flag')
        discounted = arithmetic.sum_discounted([annual[year]['net_lp_cashflow'] for year in YEARS],
            [inp('discount_factors_p12', str(year)) for year in YEARS], identity + '.LP_NPV', opening=inp('opening_cash_pence'))
        diagnostic = put(summary, 'C' + str(index), discounted,
            ['scenarios', identity, 'diagnostic_npv_pence'])
        npv = put(summary, 'D' + str(index), ('if', ('eq', flag, 1), diagnostic, ('empty',)),
            ['scenarios', identity, 'npv_pence'], kind='nullable_integer')
        summary_refs[identity] = {'feasible': flag, 'npv_pence': npv}
    all_feasible = ('and', *(('eq', value['feasible'], 1) for value in summary_refs.values()))
    put(summary, 'B7', ('if', all_feasible, 1, 0), ['feasible'], kind='flag')
    put(summary, 'D7', ('if', all_feasible, ('min', *(value['npv_pence'] for value in summary_refs.values())), ('empty',)),
        ['objective_pence'], kind='nullable_integer')
    for sheet in book:
        sheet.freeze_panes = 'C3'
        sheet.column_dimensions['A'].width = 58
        sheet.column_dimensions['B'].width = 34
        sheet['A1'].font = Font(bold=True, size=13)
    rules.column_dimensions['A'].width = 125
    contract.column_dimensions['B'].width = 120
    schema_binding = label_public_schema(book, len(PROJECT_IDS))
    literals = []
    for sheet in book:
        for cell in sheet._cells.values():
            if cell.value is not None and cell.data_type != 'f':
                value = cell.value.isoformat() if isinstance(cell.value, date) else cell.value
                literals.append({'sheet': sheet.title, 'cell': cell.coordinate, 'value': value,
                                 'kind': 'date' if isinstance(cell.value, date) else type(cell.value).__name__})
    return {'schema_version': 1, 'public_schema_binding': schema_binding, 'public_rules': list(PUBLIC_RULES),
        'emitter_recipe': assert_upstream_recipe(),
        'gold_optimizer_proof_checked_by_emitter': False,
        'independent_financial_audit_performed': False,
        'source_or_quality_or_difficulty_certified': False,
        'sheet_names': list(book.sheetnames), 'public_spec': deepcopy(spec),
        'input_bindings': input_bindings, 'decision_bindings': decision_bindings,
        'financial_bindings': financial_bindings, 'arithmetic_bindings': arithmetic.bindings,
        'public_spec_chunks': chunks, 'public_rule_cells': [{'sheet': rules.title, 'cell': 'A' + str(row)} for row in range(4, 4 + len(RULES))],
        'literal_bindings': literals,
        'annual_refs': scenario_refs, 'project_refs': project_refs, 'vintage_refs': vintage_refs,
        'gold_plan_supplied': plan is not None, 'optimisation_performed': False,
        'formula_count': len(financial_bindings) + len(arithmetic.bindings) + (len(PROJECT_IDS) if plan is not None else 0),
        'arithmetic_support_target_eligible': False,
        'arithmetic_support_values_are_protected': False,
        'plan_dependent_caches_must_be_cleared_before_task_input': True,
        'task_input_requires_actual_recalculation_and_audit': True,
        'complete_required_D_includes_changed_arithmetic_helpers': True,
        'task_input_and_complete_D_not_built': True}

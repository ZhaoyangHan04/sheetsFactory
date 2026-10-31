"""Uncached nine-case reports over one unchanged standalone project ledger."""
from copy import deepcopy
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
from xml.etree import ElementTree as ET

from ..linear_capital_scaled import excel as base, task_views
from . import contract

NA = 'N/A (not applicable)'
INCOMPLETE = 'N/A (incomplete choices)'
KIND = 'unverified_shared_ledger_nine_case_excel_bindings'
FAMILIES = tuple(task_views.FAMILIES)
GROUP_SOURCES = {'new_lp_calls': 'lp_call', 'year_end_debt': 'debt_close',
    'lp_distributions': 'lp_distribution', 'net_lp_cashflow': 'net_lp_cashflow', 'asset_nbv': 'asset_nbv_close'}
INSTRUCTIONS = {
    'financial_modeling': 'Complete the financial forecasts and all nine budget and capacity alternatives. Choose a feasible portfolio that maximises the stated investor NPV separately for each alternative, then complete every cash and constraint report. The contract notes and report labels give the business rules. Preserve supplied assumptions and all provided N/A labels. The portfolio is hypothetical.',
    'debugging': 'Audit and repair the financial forecasts and all nine budget and capacity alternatives. Replace the provisional choices with a feasible NPV-maximising portfolio for each alternative, and reconcile every cash and constraint report. The contract notes and report labels give the business rules. Preserve supplied assumptions and all provided N/A labels. The portfolio is hypothetical.'}


def _inputs(public, models, plans):
    public = contract.spec.load_spec(public); order = [c['id'] for c in contract.CASES]
    contract.require(set(models) == set(plans) == set(order), 'Every fixed case requires its own model and complete choices')
    expected = contract.expected_rows(public); baseline = None
    for case in contract.CASES:
        identity = case['id']; contract.spec.validate_plan(public, plans[identity])
        for side in ('A', 'B'):
            model = models[identity][side]
            (contract.model_a if side == 'A' else contract.model_b).validate_model(model)
            contract.require(model['project_ids'] == public['project_ids'] and len(model['rows']) == len(expected)
                and {r['id'] for r in model['rows']} == set(expected), 'Require complete original rows and project columns')
            for row in model['rows']:
                family, sid, year, original = expected[row['id']]
                factor = case['budget_percent'] if family == 'initial_sponsor_equity' else case['capacity_percent'] if family == 'resource' else 100
                contract.require((row['family'], row['scenario_id'], row['year'], row['limit'])
                    == (family, sid, year, original * factor // 100), 'Only the two declared RHS families may change')
            common = (model['project_ids'], model['objective_pence'], [(r['id'], r['coefficients']) for r in model['rows']])
            if baseline is None: baseline = common
            contract.require(common == baseline, 'Every case must reuse the same project financial coefficients')
    return public, expected


def emit_workbook(path, public, models, plans, *, max_formulas=1_500_000):
    """Pure translation only; no oracle values or cached financial results embedded."""
    public, original_rows = _inputs(public, models, plans)
    destination = Path(path); contract.require(not destination.exists(), 'Preserve existing workbooks')
    writer = base._Book(public, None, max_formulas)
    assumptions, scenarios, usage, limits = base._inputs(writer)
    # Replace the original blank-slot policy in this NEW workbook only.
    for row in writer.literals:
        if row['sheet'] == 'ContractNotes' and type(row['value']) is str:
            text = row['value'].replace('not applicable and intentionally blank', 'not applicable and show the supplied N/A (not applicable) literal')
            text = text.replace('Portfolio totals and tests are blank until', 'Portfolio totals and tests show N/A (incomplete choices) until')
            row['value'] = text; writer.book[row['sheet']][row['cell']] = text
    notes = writer.book['ContractNotes']; first_note = notes.max_row + 2
    for i, text in enumerate(contract.POLICY.values()): writer.literal(notes, first_note+i, 1, text)
    writer.literal(notes, first_note+len(contract.POLICY), 1,
        'Every alternative has an independent full choice vector. Repeated optimal vectors are allowed; all nine reports remain required. Yellow cells are decisions, not supplied assumptions.')
    schedules = {}
    for project in public['projects']:
        pid = project['id']; schedules[pid] = base._project(writer, project, assumptions[pid], scenarios)
        # Invalid pre-FY1 vintage origins are supplied text, never empty targets.
        sheet = writer.book[pid]
        for si, sid in enumerate(public['scenario_ids']):
            annual_top = 5 + si*175 + 17
            vintage_top = annual_top + len(('operating_active', 'feasible', *contract.spec.ANNUAL_FIELDS)) + 3
            for age in range(4, -1, -1):
                for fi, field in enumerate(contract.spec.VINTAGE_FIELDS):
                    for yi, year in enumerate(public['years']):
                        if year-age < 1:
                            writer.literal(sheet, vintage_top+(4-age)*len(contract.spec.VINTAGE_FIELDS)+fi, yi+2, NA)
    ids = public['project_ids']; n = len(ids); first = 6; last = n+5
    aliases = writer.sheet('SharedCoefficients'); writer.literal(aliases, 1, 1, 'One shared standalone coefficient and cash ledger / GBP pence', header=True)
    writer.literal(aliases, 5, 1, 'Project', header=True)
    columns = {}; col = 2
    for sid in public['scenario_ids']:
        for field in ('npv_pence', 'feasible'):
            columns[sid, field] = col; writer.literal(aliases, 5, col, sid+' '+field, header=True); col += 1
    initial_column = col; writer.literal(aliases, 5, col, 'Initial sponsor equity / pence', header=True); col += 1
    for sid in public['scenario_ids']:
        for year in public['years']:
            for field in GROUP_SOURCES:
                columns[sid, year, field] = col
                writer.literal(aliases, 5, col, f'{sid} FY{year} {field} / pence', header=True); col += 1
    for index, pid in enumerate(ids):
        row = first+index; writer.literal(aliases, row, 1, pid)
        for sid in public['scenario_ids']:
            for field, source, kind in (('npv_pence', 'npv', 'nullable_money_pence'), ('feasible', 'feasible', 'flag')):
                writer.formula(aliases, row, columns[sid, field], schedules[pid][sid][source],
                    expected_path=['projects', pid, 'scenarios', sid, field], kind=kind,
                    role={'schedule': 'shared_candidate_alias', 'project_id': pid, 'field': field})
        writer.formula(aliases, row, initial_column, schedules[pid]['S01']['t0']['lp_call'],
            expected_path=['projects', pid, 'scenarios', 'S01', 't0', 'lp_call'],
            role={'schedule': 'shared_candidate_alias', 'project_id': pid, 'field': 'lp_call'})
        for (sid, year, field), column in [(k, v) for k, v in columns.items() if len(k) == 3]:
            source = GROUP_SOURCES[field]
            writer.formula(aliases, row, column, schedules[pid][sid]['annual'][year][source],
                expected_path=['projects', pid, 'scenarios', sid, 'annual', year-1, source],
                role={'schedule': 'shared_candidate_alias', 'project_id': pid, 'field': source})
    cases = writer.sheet('Cases')
    for ci, text in enumerate(('Alternative', 'Sponsor equity / percent', 'Physical capacity / percent'), 1): writer.literal(cases, 1, ci, text, header=True)
    choices = writer.sheet('CaseChoices'); writer.literal(choices, 1, 1, 'Independent binary project choices / all scenarios within each alternative', header=True)
    writer.literal(choices, 3, 1, 'All project choices complete /1 yes,0 no')
    writer.literal(choices, 5, 1, 'Project', header=True)
    rhs = writer.sheet('CaseRHS')
    for ci, text in enumerate(('Business row', 'Family', 'Scenario', 'FY', 'Original provided limit'), 1): writer.literal(rhs, 1, ci, text, header=True)
    rhs_rows = {}; row_ids = sorted(original_rows)
    for ri, identity in enumerate(row_ids, 2):
        family, sid, year, limit = original_rows[identity]; rhs_rows[identity] = ri
        for ci, value in enumerate((identity, family, sid if sid is not None else NA, year if year is not None else NA, limit), 1): writer.literal(rhs, ri, ci, value)
    complete = {}; choice_refs = {}; ranges = {}
    for case_index, definition in enumerate(contract.CASES):
        identity = definition['id']; column = case_index+2
        for ci, value in enumerate((identity, definition['budget_percent'], definition['capacity_percent']), 1): writer.literal(cases, case_index+2, ci, value)
        writer.literal(choices, 5, column, identity, header=True); writer.literal(rhs, 1, case_index+6, identity, header=True)
        for index, pid in enumerate(ids):
            row = first+index
            if case_index == 0: writer.literal(choices, row, 1, pid)
            value = plans[identity][pid]; point = writer.literal(choices, row, column, value); writer.literals.pop()
            writer.decisions.append({'sheet': choices.title, 'cell': choices.cell(row, column).coordinate,
                'project_id': pid, 'case_id': identity, 'value': value, 'kind': 'binary_decision', 'worksheet_scale': 1})
            choices.cell(row, column).fill = base._CHOICE; choice_refs[identity, pid] = point
        ranges[identity] = base._range(choices.title, first, column, last)
        ran = ranges[identity]
        complete[identity] = writer.formula(choices, 3, column,
            ('if', ('and', ('eq', ('count', ran), n), ('eq', ('sum', ('countif', ran, 0), ('countif', ran, 1)), n)), 1, 0),
            kind='flag', role={'schedule': 'choice_completion', 'case_id': identity},
            derivation={'kind': 'complete_binary_decisions', 'case_id': identity, 'project_ids': list(ids)})
        by_id = {r['id']: r for r in models[identity]['A']['rows']}
        for name, ri in rhs_rows.items(): writer.literal(rhs, ri, case_index+6, by_id[name]['limit'])
    cash = writer.sheet('CaseCash'); checks = writer.sheet('CaseChecks'); summary = writer.sheet('CaseSummary')
    for ci, text in enumerate(('Alternative', 'Scenario', 'FY', 'Calendar FY', *contract.spec.GROUP_FIELDS), 1): writer.literal(cash, 1, ci, text, header=True)
    for ci, text in enumerate(('Alternative', 'Business row', 'Family', 'Scenario', 'FY', 'Usage', 'Provided limit', 'Slack', 'Pass1 / fail0'), 1): writer.literal(checks, 1, ci, text, header=True)
    for ci, text in enumerate(('Alternative', 'Feasible1 / fail0', 'Maximise independent investor NPV / pence', 'Selected projects'), 1): writer.literal(summary, 1, ci, text, header=True)
    cash_row = check_row = 2
    for case_index, definition in enumerate(contract.CASES):
        identity = definition['id']; ran = ranges[identity]
        gated = lambda expression: ('if', ('eq', complete[identity], 1), expression, INCOMPLETE)
        group = {}
        for sid in public['scenario_ids']:
            for yi, year in enumerate(public['years']):
                for ci, value in enumerate((identity, sid, year, public['fiscal_year_start']+year-1), 1): writer.literal(cash, cash_row, ci, value)
                for ci, field in enumerate(contract.spec.GROUP_FIELDS, 5):
                    group[sid, year, field] = writer.formula(cash, cash_row, ci,
                        gated(('sumproduct', ran, base._range(aliases.title, first, columns[sid, year, field], last))),
                        expected_path=['cases', identity, 'group', 'scenarios', sid, 'annual', yi, field],
                        role={'schedule': 'case_group', 'case_id': identity, 'scenario_id': sid, 'year': year, 'field': field})
                cash_row += 1
        start_check = check_row
        for name in row_ids:
            family, sid, year, _ = original_rows[name]
            if family == 'initial_sponsor_equity': lhs = ('sumproduct', ran, base._range(aliases.title, first, initial_column, last))
            elif family in ('annual_new_lp', 'annual_debt_close'):
                lhs = group[sid, year, 'new_lp_calls' if family == 'annual_new_lp' else 'year_end_debt']
            elif family == 'resource':
                resource = name.split(':')[1]; lhs = ('sumproduct', ran, base._range('ResourceUse', 2, usage[resource, sid, year], n+1))
            elif family in ('region_exposure', 'sector_exposure'):
                _, label, _ = name.split(':'); attr = 'region' if family == 'region_exposure' else 'sector'
                fields = [f for f in public['projects'][0] if f != 'resource_usage_units']
                lhs = ('sumproduct', ran, base._range(aliases.title, first, columns['S01', year, 'asset_nbv'], last),
                       ('flag', ('eq', base._range('Projects', 2, fields.index(attr)+1, n+1), label)))
            elif family == 'exclusivity':
                group_spec = next(g for g in public['exclusivity_groups'] if 'exclusivity:'+g['id'] == name)
                lhs = ('sum', *(choice_refs[identity, pid] for pid in group_spec['project_ids']))
            else:
                edge = next(e for e in public['prerequisites'] if 'prerequisite:'+e['id'] == name)
                lhs = ('sub', choice_refs[identity, edge['dependent']], choice_refs[identity, edge['prerequisite']])
            for ci, value in enumerate((identity, name, family, sid if sid is not None else NA, year if year is not None else NA), 1): writer.literal(checks, check_row, ci, value)
            for ci, field, expression in ((6, 'lhs', gated(lhs)), (7, 'limit', base._ref(rhs.title, rhs_rows[name], case_index+6)),
                (8, 'slack', gated(('sub', base._ref(checks.title, check_row, 7), base._ref(checks.title, check_row, 6)))),
                (9, 'passed', gated(('if', ('le', base._ref(checks.title, check_row, 6), base._ref(checks.title, check_row, 7)), 1, 0)))):
                writer.formula(checks, check_row, ci, expression, expected_path=['cases', identity, 'constraints'],
                    kind='flag' if field == 'passed' else 'integer', role={'schedule': 'case_capacity', 'case_id': identity, 'field': field},
                    constraint_id=name, constraint_field=field)
            check_row += 1
        writer.literal(summary, case_index+2, 1, identity)
        standalone = [('eq', ('sumproduct', ran, ('sub', 1, base._range(aliases.title, first, columns[sid, 'feasible'], last))), 0) for sid in public['scenario_ids']]
        feasible = writer.formula(summary, case_index+2, 2, gated(('if', ('and', ('eq', ('countif', base._range(checks.title, start_check, 9, check_row-1), 1), len(row_ids)), *standalone), 1, 0)),
            expected_path=['cases', identity, 'feasible'], kind='flag', role={'schedule': 'case_summary', 'case_id': identity, 'field': 'feasible'})
        writer.formula(summary, case_index+2, 3, ('if', ('and', ('eq', complete[identity], 1), ('eq', feasible, 1)),
            ('sumproduct', ran, base._range(aliases.title, first, columns['S01', 'npv_pence'], last)), 'N/A (infeasible or incomplete)'),
            expected_path=['cases', identity, 'objective_pence'], kind='nullable_money_pence', role={'schedule': 'case_summary', 'case_id': identity, 'field': 'objective_pence'})
        writer.formula(summary, case_index+2, 4, gated(('sum', ran)), kind='integer', role={'schedule': 'case_summary', 'case_id': identity, 'field': 'selected_project_count'},
            derivation={'kind': 'selected_project_count', 'case_id': identity, 'project_ids': list(ids)})
    result = {'kind': KIND, 'version': 1, 'specification_sha256': contract.spec.canonical_sha256(public),
        'case_order': [c['id'] for c in contract.CASES], 'sheetnames': writer.book.sheetnames,
        'formula_count': writer.count, 'input_bindings': writer.inputs, 'literal_bindings': writer.literals,
        'decision_bindings': writer.decisions, 'financial_bindings': writer.financial, 'arithmetic_bindings': writer.arithmetic,
        'shared_project_ledger_copies': 1, 'project_sheet_count': n, 'choice_count': 9*n,
        'case_cash_rows': cash_row-2, 'case_constraint_rows': check_row-2,
        'provided_NA_literal_count': sum(r['value'] == NA for r in writer.literals),
        'financial_expected_values_embedded': False, 'actual_engine_validated': False, 'qualified': False}
    contract.require(writer.count == len(writer.arithmetic), 'Every formula requires a physical audit locator')
    destination.parent.mkdir(parents=True, exist_ok=True); writer.book.save(destination); writer.book.close()
    return result


def view_edits(bindings, public, *, mode):
    """Same original financial fault families, plus provisional zero choices."""
    contract.require(mode in INSTRUCTIONS, 'Choose FM or DBG explicitly')
    financial = {(r['sheet'], r['cell']): r for r in bindings['financial_bindings']}
    current = {point: r['formula'] if r['formula'] is not None else r['expression'] for point, r in financial.items()}
    formula_edits = task_views._faults(public, financial, current) if mode == 'debugging' else []
    masked = sorted(set(financial) | {(r['sheet'], r['cell']) for r in bindings['arithmetic_bindings']}
                    | {(r['sheet'], r['cell']) for r in bindings['decision_bindings']}) if mode == 'financial_modeling' else []
    choices = [{'sheet': r['sheet'], 'cell': r['cell'], 'case_id': r['case_id'],
                'project_id': r['project_id'], 'after': 0} for r in bindings['decision_bindings']] if mode == 'debugging' else []
    provided = {(r['sheet'], r['cell']) for r in bindings['input_bindings']+bindings['literal_bindings']} - set(financial)
    contract.require(set(masked).isdisjoint(provided)
        and {(r['sheet'], r['cell']) for r in formula_edits+choices}.isdisjoint(provided), 'A task edit touches supplied facts or N/A literals')
    return {'mode': mode, 'masked': masked, 'formula_edits': formula_edits, 'choice_edits': choices,
        'fault_families': list(FAMILIES), 'instruction': INSTRUCTIONS[mode], 'qualified': False,
        'actual_full_D_controls_or_stability_verified': False}


def materialize_view(goal, output, bindings, public, *, mode):
    """Fresh OOXML surgery only; no recalculation and no seeded formula caches."""
    output = Path(output); contract.require(not output.exists(), 'Use a fresh view output')
    (output/'public').mkdir(parents=True); edits = view_edits(bindings, public, mode=mode)
    masks = set(edits['masked']); replacements = {(r['sheet'], r['cell']): r['after'] for r in edits['formula_edits']+edits['choice_edits']}
    with ZipFile(goal) as source, ZipFile(output/'public/input.xlsx', 'x', ZIP_DEFLATED) as target:
        sheets = ET.fromstring(source.read('xl/workbook.xml')).find('{*}sheets')
        parts = {f'xl/worksheets/sheet{i+1}.xml': node.get('name') for i, node in enumerate(sheets)}
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename in parts:
                sheet = parts[info.filename]; tree = ET.fromstring(data)
                for cell in tree.findall('{*}sheetData/{*}row/{*}c'):
                    point = sheet, cell.get('r')
                    if point in masks or point in replacements:
                        for child in list(cell):
                            if child.tag.rsplit('}', 1)[-1] in ('f', 'v', 'is'): cell.remove(child)
                        cell.attrib.pop('t', None)
                        if point in replacements:
                            value = replacements[point]; tag = 'f' if type(value) is str else 'v'
                            ET.SubElement(cell, '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'+tag).text = value[1:] if tag == 'f' else str(value)
                data = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
            target.writestr(info, data)
    (output/'public/instruction.md').write_text(edits['instruction']+'\n')
    return edits

"""Native tax-vintage schedules; this renderer has no financial oracle input."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from openpyxl import load_workbook
from openpyxl.utils import quote_sheetname

from ..associate_bridge_v1 import excel as bridge_excel
from ..operating_reports_200 import excel as report_excel, schema as shape
from . import spec

BRIDGE_EXCEL_SHA = 'ce389fb3d3dc4b235661bdd127cdbca291f1eb2c2c837a2f292f8dcbc9bf919b'
POOLS = ('ordinary', 'investment')
FIELDS = tuple('tax_'+pool+'_'+side+'_losses' for pool in POOLS for side in ('before', 'after')) + tuple(
    'loss_'+pool+'_'+side for pool in POOLS for side in ('expired', 'used', 'created', 'close')) + ('cash_tax_paid', 'tax_payable_close')
STOCKS = {'loss_ordinary_close', 'loss_investment_close', 'tax_payable_close'}



def _ref(path):
    p = Path(path).resolve(); raw = p.read_bytes()
    return {'path': str(p), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _term(policy, index):
    return max((t for t in policy['terms'] if t['effective_index'] <= index), key=lambda t: t['effective_index'])


def _quarter(index):
    year, quarter = divmod(index, 4)
    return str(2025+year)+'Q'+str(quarter+1)


def _label(field):
    if field.startswith('tax_lot_'):
        return field.removeprefix('tax_lot_').replace('_', ' ')
    return field.replace('_', ' ')


def emit(public, output):
    spec.validate(public)
    output = Path(output)
    if output.exists():
        raise ValueError('Use a fresh native source directory')
    if _ref(bridge_excel.__file__)['sha256'] != BRIDGE_EXCEL_SHA:
        raise ValueError('The frozen investment renderer changed')
    output.mkdir(parents=True)
    bridge_receipt = bridge_excel.emit(public['bridge'], output/'investment_base')
    book = load_workbook(output/'investment_base/source_uncalculated.xlsx', keep_links=False)
    bindings = json.loads((output/'investment_base/private_bindings.json').read_text())
    financial = bindings['financial']; facts = bindings['provided_facts']
    entities = {e['id']: e for e in public['bridge']['base']['entities']}
    policies = public['tax_policies']
    lots = tuple(spec.LOT_IDS)

    def cell(record):
        return quote_sheetname(record['sheet'])+'!'+record['cell']
    def r(identity, period, field):
        return cell(financial[identity+'/'+period+'/'+field])
    def put_fact(ws, row, identity, name, label, value):
        ws.cell(row, 1, label); target = ws.cell(row, 2)
        target.value = float(value) if isinstance(value, (int, str)) and str(value).replace('-', '', 1).replace('.', '', 1).isdigit() else value
        target.number_format = '0.###############'
        record = {'sheet': ws.title, 'cell': target.coordinate, 'value': str(value), 'role': 'provided_fact'}
        facts[identity+'/'+name] = record
    def f(identity, name):
        return cell(facts[identity+'/'+name])

    # Allocate every additional field before writing cross-referencing formulas.
    for identity, entity in entities.items():
        ws = book[financial[identity+'/2025Q1/revenue']['sheet']]
        row = ws.max_row+3
        ws.cell(row, 1, 'Tax terms: effective from the stated quarter')
        for term in policies[identity]['terms']:
            row += 1
            ws.cell(row, 1, 'Effective '+_quarter(term['effective_index']))
            for name in ('ordinary_cap_bp', 'investment_cap_bp', 'carry_quarters', 'cash_tax_lag'):
                row += 1
                put_fact(ws, row, identity, 'tax_term_'+str(term['effective_index'])+'_'+name,
                         _quarter(term['effective_index'])+' '+name.replace('_', ' '), term[name])
        row += 2; ws.cell(row, 1, 'Opening tax-loss register (report currency)')
        # A deterministic display permutation makes origin, rather than row number, authoritative.
        for lot in sorted(policies[identity]['opening_lots'], key=lambda x: x['lot_id'], reverse=True):
            for name in ('origin_index', 'last_eligible_index', 'ordinary', 'investment'):
                row += 1
                val = lot[name]
                label = lot['lot_id']+' '+name.replace('_index', ' quarter').replace('_', ' ')
                if name.endswith('_index'):
                    label += ' ('+_quarter(val)+')'
                put_fact(ws, row, identity, 'tax_opening_'+lot['lot_id']+'_'+name, label, val)
        row += 3; ws.cell(row, 1, 'Quarterly tax and loss reports ('+report_excel.MONEY_LABEL[entity['money_unit']]+')')
        for c, period in enumerate(shape.QUARTERS, 2):
            ws.cell(row, c, period)
        display_lots = tuple(reversed(lots[::2]))+tuple(reversed(lots[1::2]))
        helper_fields = tuple('tax_lot_'+lot+'_'+pool+'_'+side for lot in display_lots for pool in POOLS for side in ('used', 'close'))
        for field in FIELDS+helper_fields:
            row += 1; ws.cell(row, 1, _label(field))
            for c, period in enumerate(shape.QUARTERS, 2):
                financial[identity+'/'+period+'/'+field] = {
                    'sheet': ws.title, 'cell': ws.cell(row, c).coordinate, 'role': 'report',
                    'money_unit': entity['money_unit'], 'rate_unit': entity['rate_unit']}
        row += 3; ws.cell(row, 1, 'Full-year tax and loss reports')
        for c, year in enumerate(shape.YEARS, 2):
            ws.cell(row, c, 'FY'+str(year))
        for field in FIELDS:
            row += 1; ws.cell(row, 1, _label(field))
            for c, year in enumerate(shape.YEARS, 2):
                financial[identity+'/FY'+str(year)+'/'+field] = {
                    'sheet': ws.title, 'cell': ws.cell(row, c).coordinate, 'role': 'report',
                    'money_unit': entity['money_unit'], 'rate_unit': entity['rate_unit']}

    members = {'DIV_'+d.upper(): [e['id'] for e in entities.values() if e['division'] == d]
               for d in public['bridge']['base']['divisions']}
    members['PORTFOLIO'] = list(entities)
    for identity in members:
        ws = book[financial[identity+'/2025Q1/revenue']['sheet']]
        row = ws.max_row+3; ws.cell(row, 1, 'Tax and loss reports (GBP)')
        periods = shape.QUARTERS+tuple('FY'+str(y) for y in shape.YEARS)
        for c, period in enumerate(periods, 2):
            ws.cell(row, c, period)
        for field in FIELDS:
            row += 1; ws.cell(row, 1, _label(field))
            for c, period in enumerate(periods, 2):
                financial[identity+'/'+period+'/'+field] = {'sheet': ws.title, 'cell': ws.cell(row, c).coordinate,
                    'role': 'report', 'money_unit': 'GBP', 'rate_unit': 'percent_units'}

    for identity, entity in entities.items():
        policy = policies[identity]; investment = public['bridge']['policies'][identity]
        opening = {lot['lot_id']: lot for lot in policy['opening_lots']}
        origin = {lot: opening[lot]['origin_index'] if lot in opening else int(lot[1:]) for lot in lots}
        ordered = sorted(lots, key=lambda lot: (origin[lot], lot))
        for q, period in enumerate(shape.QUARTERS):
            term = _term(policy, q)
            t = lambda name: f(identity, 'tax_term_'+str(term['effective_index'])+'_'+name)
            before = r(identity, period, 'pretax_before_associate')
            capital = investment['receipt_kind'][period] == 'capital_return'
            inv = '0' if investment['tax_class'] == 'exempt' else r(identity, period, 'associate_income') if investment['tax_class'] == 'recognized' else '0' if capital else f(identity, 'investment_cash_receipt/'+period)
            formulas = {'tax_ordinary_before_losses': before, 'tax_investment_before_losses': inv}
            for pool in POOLS:
                cap = 'MAX(0,'+r(identity, period, 'tax_'+pool+'_before_losses')+')*'+t(pool+'_cap_bp')+'/10000'
                previous_used = []
                expired = []
                for lot in ordered:
                    used_field = 'tax_lot_'+lot+'_'+pool+'_used'
                    close_field = 'tax_lot_'+lot+'_'+pool+'_close'
                    birth = origin[lot]
                    if q <= birth:
                        formulas[used_field] = '0'
                        formulas[close_field] = r(identity, period, 'loss_'+pool+'_created') if q == birth else '0'
                        continue
                    old = r(identity, shape.QUARTERS[q-1], close_field) if q else f(identity, 'tax_opening_'+lot+'_'+pool)
                    if lot in opening:
                        expiry = f(identity, 'tax_opening_'+lot+'_last_eligible_index')
                    else:
                        birth_term = _term(policy, birth)
                        expiry = str(birth)+'+'+f(identity, 'tax_term_'+str(birth_term['effective_index'])+'_carry_quarters')
                    live = 'IF('+str(q)+'<='+expiry+','+old+',0)'
                    remaining = cap+('-SUM('+','.join(previous_used)+')' if previous_used else '')
                    formulas[used_field] = 'MIN('+live+',MAX(0,'+remaining+'))'
                    formulas[close_field] = live+'-'+r(identity, period, used_field)
                    previous_used.append(r(identity, period, used_field))
                    expired.append('IF('+str(q)+'>'+expiry+','+old+',0)')
                formulas['loss_'+pool+'_used'] = 'SUM('+','.join(r(identity, period, 'tax_lot_'+lot+'_'+pool+'_used') for lot in lots)+')'
                formulas['loss_'+pool+'_expired'] = 'SUM('+','.join(expired)+')' if expired else '0'
                formulas['loss_'+pool+'_created'] = 'MAX(0,-'+r(identity, period, 'tax_'+pool+'_before_losses')+')'
                formulas['loss_'+pool+'_close'] = 'SUM('+','.join(r(identity, period, 'tax_lot_'+lot+'_'+pool+'_close') for lot in lots)+')'
                formulas['tax_'+pool+'_after_losses'] = 'MAX(0,'+r(identity, period, 'tax_'+pool+'_before_losses')+')-'+r(identity, period, 'loss_'+pool+'_used')
            paid = [r(identity, shape.QUARTERS[j], 'current_tax') for j in range(q+1)
                    if j+_term(policy, j)['cash_tax_lag'] == q]
            formulas['cash_tax_paid'] = 'SUM('+','.join(paid)+')' if paid else '0'
            prior_payable = r(identity, shape.QUARTERS[q-1], 'tax_payable_close') if q else '0'
            formulas['tax_payable_close'] = prior_payable+'+'+r(identity, period, 'current_tax')+'-'+r(identity, period, 'cash_tax_paid')
            rate_scale = {'fraction':1, 'percent_units':100, 'basis_points':10000}[entity['rate_unit']]
            formulas['current_tax'] = '('+r(identity, period, 'tax_ordinary_after_losses')+'+'+r(identity, period, 'tax_investment_after_losses')+')*'+f(identity, 'parent_tax_rate')+'/'+str(rate_scale)
            formulas['operating_cash_flow'] = r(identity, period, 'net_income')+'-'+r(identity, period, 'associate_income')+'+'+f(identity, 'investment_cash_receipt/'+period)+'+'+r(identity, period, 'current_tax')+'-'+r(identity, period, 'cash_tax_paid')
            formulas['total_liabilities_equity'] = r(identity, period, 'debt')+'+'+r(identity, period, 'contributed_capital')+'+'+r(identity, period, 'closing_retained_earnings')+'+'+r(identity, period, 'tax_payable_close')
            for field, formula in formulas.items():
                record = financial[identity+'/'+period+'/'+field]
                book[record['sheet']][record['cell']] = '='+formula
        for year in shape.YEARS:
            period = 'FY'+str(year)
            for field in FIELDS:
                formula = r(identity, str(year)+'Q4', field) if field in STOCKS else 'SUM('+','.join(r(identity, str(year)+'Q'+str(q), field) for q in range(1,5))+')'
                record = financial[identity+'/'+period+'/'+field]
                book[record['sheet']][record['cell']] = '='+formula
    for identity, children in members.items():
        for period in shape.QUARTERS+tuple('FY'+str(y) for y in shape.YEARS):
            for field in FIELDS:
                record = financial[identity+'/'+period+'/'+field]
                formula = '+'.join(r(child, period, field)+'*'+str(bridge_excel.MONEY[entities[child]['money_unit']]) for child in children)
                book[record['sheet']][record['cell']] = '='+formula

    readme = book['ReadMe']
    for row, paragraph in enumerate(spec.PUBLIC_POLICY, readme.max_row+2):
        readme.cell(row, 1, paragraph)
        readme.row_dimensions[row].height = 90
    # Replace the two earlier same-quarter/no-loss tax paragraphs with the new authoritative treatment.
    for row in range(1, readme.max_row+1):
        value = readme.cell(row, 1).value
        if isinstance(value, str) and value.startswith('The hypothetical parent tax class'):
            readme.cell(row, 1, 'The entity parent tax class selects its taxable investment earnings. The tax-vintage and settlement terms below replace the former no-loss, same-quarter tax treatment.')
        elif isinstance(value, str) and value.startswith('Sales and operating costs, cash interest and current parent tax'):
            readme.cell(row, 1, value.replace('Sales and operating costs, cash interest and current parent tax settle within their quarter.', 'Sales and operating costs and cash interest settle within their quarter. Parent tax settles under the assessment-specific lag below.'))
    expected = dict(spec.points(public))
    if set(financial) != set(expected):
        raise ValueError('Incomplete extended financial binding inventory')
    count = 0
    for key, record in financial.items():
        target = book[record['sheet']][record['cell']]
        if target.data_type == 'f':
            count += 1
            if len(target.value) > 8192:
                raise ValueError('A formula exceeds the workbook limit')
        if expected[key] != 'text' and target.value is None:
            raise ValueError('An extended financial formula is missing: '+key)
    if count != sum(kind != 'text' for kind in expected.values()):
        raise ValueError('Extended formula count differs from complete declared points')
    if count > 400000 or any(ws.max_row > 1000 or ws.max_column > 80 for ws in book):
        raise ValueError('Tax-vintage construction cap exceeded')
    path = output/'source_uncalculated.xlsx'
    book.save(path)
    report_excel._exact_numeric_inputs(path, facts)
    financial_cells = {(b['sheet'], b['cell']) for b in financial.values()}
    exact_facts = {(b['sheet'], b['cell']): b['value'] for b in facts.values()}
    context = {}
    for ws in book:
        for target in ws._cells.values():
            if target.value is None or (ws.title, target.coordinate) in financial_cells:
                continue
            context[ws.title+'!'+target.coordinate] = {'sheet':ws.title, 'cell':target.coordinate,
                'role':'provided_context', 'value':exact_facts.get((ws.title, target.coordinate), target.value),
                'cell_type':target.data_type, 'number_format':target.number_format, 'style_id':target.style_id,
                'hyperlink':target.hyperlink.target if target.hyperlink else None}
    bindings.update(kind='private_tax_vintage_bridge_business_bindings_v2',
                    specification_sha256=spec.canonical_sha256(public), provided_context=context)
    binding_path = output/'private_bindings.json'
    binding_path.write_text(json.dumps(bindings, ensure_ascii=False, indent=2)+'\n')
    receipt = {'kind':'uncalculated_tax_vintage_bridge_business_source_v2', 'case_id':public['case_id'],
        'specification_sha256':spec.canonical_sha256(public), 'formulas':count, 'report_positions':len(expected),
        'sheets':len(book.sheetnames), 'actual_LO_calls':0, 'source_caches_seeded':False,
        'implementation':_ref(__file__), 'investment_renderer':_ref(bridge_excel.__file__),
        'bindings':_ref(binding_path), 'investment_base_receipt':bridge_receipt}
    (output/'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
    return receipt

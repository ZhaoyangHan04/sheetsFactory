"""Render investment-accounting policies into the existing report layouts.

The renderer owns no expected financial values. It writes formulas and public
facts; two independent ledgers and actual LibreOffice calls check the result.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
from types import FunctionType

from openpyxl.utils import quote_sheetname

from sheets_factory.workbook.operating_reports_200 import excel as base
from sheets_factory.workbook.operating_reports_200 import excel_revision2 as growth
from sheets_factory.workbook.operating_reports_200 import schema as shape

BASE_SHA = '50ee9cdcc19d3cff39494d47c43ea6e41ac2c4a824a200b381b366e2fe71baa8'
GROWTH_SHA = 'b4fb12d296b5c8b5457fc6d8bbf8a1a412ed0587267beb8e81d996f7e6432e97'
MONEY = {'GBP': 1, 'GBP_thousands': 1000, 'GBP_millions': 1000000}
UNIT = {1: 'GBP', 1000: 'GBP thousands', 1000000: 'GBP millions'}
POLICY = (
    'These hypothetical businesses report FY2025 actual and FY2026–FY2027 forecasts. '
    'Each entity states its calendar periods, reporting units and presentation basis. '
    'Source facts remain supplied; report calculations may require completion or repair.',
    'Sales drivers identify their comparison period and their measure: change rate, level multiple, '
    'base-100 index or monetary change. Currency scales are GBP, GBP thousands or GBP millions; '
    'rate scales are fractions, percentage units or basis points.',
    'The investment posting feed has its own stated currency and year-specific direction. '
    'Income-positive means a positive posting is a share profit. Charge/(credit) means a positive '
    'posting is a share loss and a negative posting is a share profit. Apply that direction to '
    'both profits and losses. Cash receipts are separately supplied in report currency.',
    'Under the equity method, recognize the signed share result as investment income; all cash '
    'receipts reduce the investment carrying amount. Under the cost method, recognize cash '
    'dividends as income, ignore share postings for income, and reduce investment only for '
    'capital returns. Capital returns do not create income. Equity-method share results also '
    'change the investment carrying amount. Investment income is presented income-positive '
    'in both statement formats. There are no disposals or other investment movements.',
    'The hypothetical parent tax class is stated for each entity. Exempt excludes investment '
    'amounts from taxable earnings. Recognized includes recognized investment income or loss. '
    'Cash-dividends includes cash dividend receipts and excludes capital returns. Apply parent '
    'current tax only to positive total taxable earnings after cash interest; no loss credit, carryforward or deferred tax.',
    'Sales and operating costs, cash interest and current parent tax settle within their quarter. '
    'Investment share results are noncash. The net-cash-before-owner-distributions report line '
    'includes operating cash and all investment cash receipts, including capital returns; it is '
    'a total cash bridge rather than an operating-cash-flow subtotal. Fixed debt bears its annual '
    'interest rate evenly over four quarters. Debt and '
    'contributed capital remain fixed; no working capital, capex or depreciation is modelled.',
    'Only FY2027 Q4 may distribute 20% of positive FY2027 net income, and only if unrounded '
    'FY2025-to-FY2027 annual sales CAGR is at least 8% and unrounded Q4 year-on-year sales '
    'growth is at least 5%. Equality qualifies. Other periods distribute zero. CAGR spans two '
    'annual intervals. Owner distributions reduce cash and retained earnings.',
    'Each entity enters its named division once, and each division enters the master portfolio '
    'once. Aggregates use GBP, sum entity owner distributions, and calculate ratios from aggregate '
    'financial amounts. No FX, ownership weighting or intercompany elimination applies. '
    'This is management reporting. Stocks are period-end balances; annual flows sum quarters.',
    'Use full precision for financial calculations. Final numeric values use the common two-decimal '
    'comparison; text and booleans retain their types. Provided nonapplicable literals remain '
    'unchanged. Empty spacing cells are not report fields. Opening and closing statements reconcile.',
)


def _reference(path):
    path = Path(path).resolve()
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def _formula(public):
    ordinary = growth._replacement(growth.rules(public['base']))
    policies = public['policies']

    def formula(identity, period, field, entity, members, ref, fact, entity_scales):
        if entity is None or period.startswith('FY'):
            return ordinary(identity, period, field, entity, members, ref, fact, entity_scales)
        policy = policies[identity]
        report_scale = MONEY[entity['money_unit']]
        r = lambda name: ref(identity, period, name)
        cash = fact(identity, 'investment_cash_receipt', period)
        capital = policy['receipt_kind'][period] == 'capital_return'
        is_equity = policy['method'] == 'equity'
        sign = -1 if policy['direction_by_year'][period[:4]] == 'charge_credit' else 1
        share = '(' + fact(identity, 'associate_results', period) + f'*{sign}*{policy["feed_scale"]}/{report_scale})'
        if field == 'associate_income':
            return share if is_equity else '0' if capital else cash
        if field == 'current_tax':
            extra = '0' if policy['tax_class'] == 'exempt' else r('associate_income') if policy['tax_class'] == 'recognized' else '0' if capital else cash
            scale = {'fraction': 1, 'percent_units': 100, 'basis_points': 10000}[entity['rate_unit']]
            return 'MAX(0,'+r('pretax_before_associate')+'+'+extra+')*'+fact(identity, 'parent_tax_rate')+f'/{scale}'
        if field == 'operating_cash_flow':
            return r('net_income')+'-'+r('associate_income')+'+'+cash
        if field == 'closing_investment':
            index = shape.QUARTERS.index(period)
            prior = ref(identity, shape.QUARTERS[index-1], field) if index else fact(identity, 'opening_investment')
            addition = share if is_equity else '0'
            reduction = cash if is_equity or capital else '0'
            return prior+'+'+addition+'-'+reduction
        return ordinary(identity, period, field, entity, members, ref, fact, entity_scales)
    return formula


def _inputs(public):
    original = base._inputs
    policies = public['policies']

    def inputs(ws, entity, start, facts):
        original(ws, entity, start, facts)
        identity = entity['id']; policy = policies[identity]
        directions = '; '.join('FY'+year+' '+('charge/(credit)' if direction == 'charge_credit' else 'income-positive')
                               for year, direction in sorted(policy['direction_by_year'].items()))
        tax = {'exempt': 'exempt', 'recognized': 'recognized', 'cash_dividends': 'cash-dividends'}[policy['tax_class']]
        ws['A5'] = ('Investment method: '+policy['method']+'; parent tax class: '+tax+'. '
                    'Posting feed currency: '+UNIT[policy['feed_scale']]+'. '+directions+'. '
                    'Cash receipts and their nature are separately labelled below.')
        ws.row_dimensions[5].height = 75
        for period in shape.QUARTERS:
            item = facts[identity+'/associate_results/'+period]
            item['value'] = policy['share_postings'][period]
            ws[item['cell']] = float(item['value'])
            address = ws[item['cell']]
            ws.cell(address.row, 1, period+' investment posting ('+UNIT[policy['feed_scale']]+')')
        row = ws.max_row+2
        ws.cell(row, 1, 'Investment cash receipts in report currency')
        for period in shape.QUARTERS:
            row += 1
            label = period+' cash '+('capital return' if policy['receipt_kind'][period] == 'capital_return' else 'dividend')+' received ('+base.MONEY_LABEL[entity['money_unit']]+')'
            ws.cell(row, 1, label)
            ws.cell(row, 2, float(policy['cash_receipts'][period]))
            ws.cell(row, 2).number_format = '0.###############'
            facts[identity+'/investment_cash_receipt/'+period] = {
                'sheet': ws.title, 'cell': ws.cell(row, 2).coordinate,
                'value': policy['cash_receipts'][period], 'role': 'provided_fact'}
    return inputs


def emit(public, output):
    from . import spec
    spec.validate(public)
    if _reference(base.__file__)['sha256'] != BASE_SHA or _reference(growth.__file__)['sha256'] != GROWTH_SHA:
        raise ValueError('The retained report or decimal-input renderer changed')
    render_base = deepcopy(public['base'])
    render_base['public_policy'] = '\n\n'.join(POLICY)
    namespace = {**vars(base), '_formula': _formula(public), '_inputs': _inputs(public),
                 '_views': lambda *args, **kwargs: None}
    namespace['LABELS'] = {**base.LABELS,
        'associate_income': 'Investment income / (loss)',
        'reported_associate_line': 'Presented investment income / (loss)',
        'pretax_before_associate': 'Earnings after interest, before parent tax and investment income',
        'core_net_income': 'After parent tax, before investment income',
        'operating_cash_flow': 'Net cash before owner distributions',
        'closing_investment': 'Investment carrying amount'}
    for name in ('_label', '_allocate'):
        original = getattr(base, name)
        namespace[name] = FunctionType(original.__code__, namespace, original.__name__, original.__defaults__)
    emitter = FunctionType(base.emit.__code__, namespace, base.emit.__name__, base.emit.__defaults__)
    result = emitter(render_base, output)
    output = Path(output)
    binding_path = output/'private_bindings.json'
    bindings = json.loads(binding_path.read_text())
    bindings['kind'] = 'private_associate_bridge_business_bindings_v1'
    bindings['specification_sha256'] = spec.canonical_sha256(public)
    binding_path.write_text(json.dumps(bindings, ensure_ascii=False, indent=2)+'\n')
    receipt = {**result, 'kind': 'uncalculated_associate_bridge_business_source_v1',
               'specification_sha256': spec.canonical_sha256(public), 'case_id': public['case_id'],
               'implementation': _reference(__file__), 'base_renderer': _reference(base.__file__),
               'growth_renderer': _reference(growth.__file__), 'actual_LO_calls': 0,
               'public_policy': list(POLICY), 'bindings': _reference(binding_path)}
    (output/'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')
    return receipt

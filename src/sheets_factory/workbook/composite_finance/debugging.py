"""Private, event-driven defects for the documented heterogeneous finance model.

Only public input contracts, labels, formulas and recalculated values are read.
Local arithmetic sensitivity screens are proposals, never executed root-impact
certificates or oracle evidence. The normal constructor must prove every root's
individual and full-context marginal effect with the actual spreadsheet engine.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import json
from pathlib import Path

import openpyxl
from openpyxl.formula import Tokenizer
from openpyxl.utils import get_column_letter as L

from .tasks import _label, _policy_evidence

_CENT = Decimal('.01')


def _q(value):
    return Decimal(value).quantize(_CENT, rounding=ROUND_HALF_UP)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError('A recalculated finite numeric source cache is required')
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('A recalculated finite numeric source cache is required')
    return result


def _public_contracts(book):
    if 'Model Input Contracts' not in book:
        raise ValueError('Composite debugging requires the explicit public input contracts')
    found = {}
    for row in book['Model Input Contracts'].iter_rows(min_row=3, max_col=2):
        if row[0].value in ('lease', 'programme', 'operating', 'holding'):
            key = row[0].value
            if key in found or not isinstance(row[1].value, str):
                raise ValueError('Ambiguous public input contract')
            found[key] = json.loads(row[1].value)
    if set(found) != {'lease', 'programme', 'operating', 'holding'}:
        raise ValueError('Incomplete public input contracts')
    return found


class _Draft:
    def __init__(self, book, cached):
        self.book, self.cached = book, cached
        self.rows, self.edits, self.seen = {}, [], set()

    def row(self, sheet, field):
        if sheet not in self.rows:
            rows = {}
            for cell in self.book[sheet]['A']:
                key = _label(cell.value)
                if key:
                    if key in rows:
                        raise ValueError('Ambiguous composite financial row label')
                    rows[key] = cell.row
            self.rows[sheet] = rows
        key = _label(field)
        if key not in self.rows[sheet]:
            raise ValueError(f'Missing composite financial label {sheet}: {field}')
        return self.rows[sheet][key]

    def address(self, sheet, field, column):
        return L(column) + str(self.row(sheet, field))

    def ref(self, sheet, field, column):
        return "'" + sheet.replace("'", "''") + "'!" + self.address(sheet, field, column)

    def value(self, sheet, field, column):
        return _number(self.cached[sheet][self.address(sheet, field, column)].value)

    def formula(self, sheet, field, column):
        cell = self.book[sheet][self.address(sheet, field, column)]
        if cell.data_type != 'f' or not isinstance(cell.value, str):
            raise ValueError('A selected financial field is not an ordinary Excel formula')
        return cell.value

    def add(self, sheet, field, column, after, prediction, mechanism, rule, context):
        address = self.address(sheet, field, column)
        key = sheet, address
        if key in self.seen:
            return
        cell, cached = self.book[sheet][address], self.cached[sheet][address]
        before = self.formula(sheet, field, column)
        if (cell.is_date or cached.is_date or isinstance(cached.value, (date, datetime, time, timedelta))):
            raise ValueError('A semantic bug must not overwrite a public date')
        if not isinstance(after, str) or not after.startswith('=') or after == before:
            return
        Tokenizer(after)  # Structural tokenization; the engine remains authoritative.
        actual, proposed = _number(cached.value), Decimal(prediction)
        if not proposed.is_finite() or _q(actual) == _q(proposed):
            return
        self.seen.add(key)
        self.edits.append({'sheet': sheet, 'cell': address, 'before': before, 'after': after,
            'reason': 'A business-policy defect at an economically active boundary.',
            'business_rule': rule, 'mechanism': mechanism,
            'event_context': {'field': field, **context},
            'private_expected_activity': {
                'cached_original_value': str(actual),
                'local_counterfactual_value': str(proposed),
                'normalized_local_change_expected': True,
                'method': 'local_arithmetic_on_original_caches_not_engine_execution',
                'individual_and_combined_marginal_engine_proof_required': True}})


def _columns(sheet):
    result = {}
    for cell in sheet[2]:
        value = cell.value
        year = value.year if isinstance(value, (date, datetime)) else value
        if isinstance(year, int) and not isinstance(year, bool) and 2000 <= year <= 2200:
            if year in result:
                raise ValueError('Ambiguous public fiscal-year header')
            result[year] = cell.column
    if not result:
        raise ValueError('Public annual reporting periods are missing')
    return result


def _lease_defects(draft, contract):
    for lease in contract['leases']:
        identity, sheet = lease['lease_id'], 'Lease ' + lease['lease_id']
        start, frequency = lease['start_month'], lease['payment_frequency']
        events = {event['month']: event for event in lease['events']}
        # A modification replaces the end; a full termination stops service
        # before its event month. These dates come from the public contract.
        end = lease['end_month']
        for event in lease['events']:
            if event['kind'] == 'termination':
                end = event['month'] - 1
                break
            if event.get('new_end_month') is not None:
                end = event['new_end_month']
        for month in sorted({start, *events}):
            col, c = month + 2, L(month + 2)
            event = events.get(month, {'kind': 'commencement'})
            kind = event['kind']
            context = {'module': 'lease', 'lease_id': identity, 'global_month': month, 'event_kind': kind}
            v = lambda field: draft.value(sheet, field, col)
            r = lambda field: draft.address(sheet, field, col)
            # Beginning-of-month event payments remain month-end arrears.
            pv, rate = v('lease_pv_at_measurement'), v('lease_monthly_discount_rate')
            before = draft.formula(sheet, 'lease_pv_at_measurement', col)
            after = before.replace('-' + c + '$2+1)', '-' + c + '$2)')
            if pv > 0 and rate > 0:
                draft.add(sheet, 'lease_pv_at_measurement', col, after, _q(pv * (1 + rate)),
                    'lease_payment_timing', 'Lease present values include the current event month end payment and discount every payment in arrears.', context)
            charge = v('lease_depreciation_charge')
            if month == start:
                draft.add(sheet, 'lease_book_depreciation', col, '=ROUND(' + r('lease_depreciation_charge') + '/2,2)', _q(charge / 2),
                    'lease_commencement_service', 'Lease commencement is at the start of a full service month; the capital-programme half-year convention does not apply to leases.', context)
                liability = v('liability_after_measurement')
                direct = v('lease_direct_cost_cash')
                draft.add(sheet, 'liability_after_measurement', col,
                    '=ROUND(' + r('lease_pv_at_measurement') + '+' + r('lease_direct_cost_cash') + ',2)', liability + direct,
                    'lease_direct_cost_classification', 'Initial direct costs increase ROU and cash outflow but do not increase the contractual lease liability.', context)
            elif kind != 'termination':
                previous = draft.address(sheet, 'lease_depreciation_charge', col - 1)
                draft.add(sheet, 'lease_book_depreciation', col, '=' + previous,
                    draft.value(sheet, 'lease_depreciation_charge', col - 1), 'lease_remeasurement_depreciation',
                    'A remeasurement resets straight-line depreciation using the revised remaining ROU and service term.', context)
            if v('lease_book_interest') != 0:
                draft.add(sheet, 'lease_book_interest', col,
                    '=ROUND(' + r('lease_liability_open') + '*' + r('lease_monthly_discount_rate') + ',2)',
                    _q(v('lease_liability_open') * rate), 'lease_event_interest_basis',
                    'Event-month interest uses liability after the beginning-of-month remeasurement, rather than the old opening liability.', context)
            if event.get('retention_fraction') is not None and Decimal(str(event['retention_fraction'])) > 0:
                for field, opening in [('retained_rou', 'lease_rou_open'), ('retained_liability', 'lease_liability_open')]:
                    draft.add(sheet, field, col, '=ROUND(' + r(opening) + '*(1-' + r('event_retention_fraction') + '),2)',
                        _q(v(opening) * (1 - v('event_retention_fraction'))), 'lease_retained_vs_surrendered',
                        'Partial termination retains the stated fraction of each opening stock and derecognizes its complement.', context)
            fee = v('lease_termination_fee_cash')
            if fee:
                draft.add(sheet, 'lease_termination_gain_loss', col,
                    '=ROUND(' + r('lease_liability_derecognized') + '-' + r('lease_rou_derecognized') +
                    '+MAX(0,-(' + r('retained_rou') + '+' + r('lease_remeasurement_delta') + '+' + r('lease_direct_cost_cash') + ')),2)',
                    v('lease_termination_gain_loss') + fee, 'lease_termination_fee_sign',
                    'The immediate termination fee reduces signed gain and is included once in total cash.', context)
            ratio = event.get('index_ratio')
            if ratio is not None and (Decimal(str(ratio)) < Decimal(lease['index_floor_factor']) or Decimal(str(ratio)) > Decimal(lease['index_cap_factor'])):
                # Alter the payment, not the small rate helper whose two-decimal
                # normalized value might remain unchanged.
                bounded = min(Decimal(lease['index_cap_factor']), max(Decimal(lease['index_floor_factor']), Decimal(str(ratio))))
                draft.add(sheet, 'nominal_contract_payment', col,
                    '=ROUND(' + draft.formula(sheet, 'nominal_contract_payment', col)[1:] +
                    '*' + r('event_index_ratio') + '/MIN(\'Lease Inputs\'!$' + L(3 + contract['leases'].index(lease)) + '$16,MAX(\'Lease Inputs\'!$' +
                    L(3 + contract['leases'].index(lease)) + '$15,' + r('event_index_ratio') + ')),2)',
                    _q(v('nominal_contract_payment') * Decimal(str(ratio)) / bounded), 'lease_per_review_index_bound',
                    'Each index review applies the individual lease review floor and cap before carrying the revised level forward.', context)
        # Select actual contractual steps and fiscal-year/payment boundaries,
        # rather than a repeated arbitrary monthly pricing perturbation.
        step_months = range(start + lease['fixed_step_months'], end + 1, lease['fixed_step_months']) if Decimal(lease['fixed_step_rate']) else []
        boundary_months = {end, *step_months}
        if frequency > 1:
            boundary_months |= {month for month in range(start, end + 1)
                               if month % 12 == 0 and (month - start + 1) % frequency == 0}
        for month in sorted(boundary_months):
            col = month + 2
            v = lambda field: draft.value(sheet, field, col)
            r = lambda field: draft.address(sheet, field, col)
            context = {'module': 'lease', 'lease_id': identity, 'global_month': month,
                       'event_kind': 'contractual_end' if month == end else 'fixed_step_or_reporting_payment'}
            if frequency > 1 and v('nominal_contract_payment'):
                draft.add(sheet, 'nominal_contract_payment', col,
                    '=ROUND(' + draft.formula(sheet, 'nominal_contract_payment', col)[1:] + '/' + str(frequency) + ',2)',
                    _q(v('nominal_contract_payment') / frequency), 'lease_periodic_vs_monthly_rent',
                    'A periodic payment is the payment frequency times that month\'s separately posted monthly rent.', context)
            if month == end:
                draft.add(sheet, 'lease_recurring_rent', col, '=' + r('nominal_contract_payment'),
                    v('nominal_contract_payment'), 'lease_terminal_penny_settlement',
                    'The final contractual payment settles the remaining liability and current interest, absorbing cumulative penny differences.', context)
                draft.add(sheet, 'lease_book_depreciation', col, '=' + r('lease_depreciation_charge'),
                    v('lease_depreciation_charge'), 'lease_terminal_rou_settlement',
                    'The final service month depreciates the remaining ROU rather than leaving its accumulated penny residue.', context)
        # Misclassifying accrual expense as cash tax deduction is observable in
        # the annual interface and feeds the regulatory tax calculation.
        annual_columns = _columns(draft.book['Lease Annual'])
        for year, col in annual_columns.items():
            cash = draft.value('Lease Annual', 'lease_tax_deduction', col)
            expense = draft.value('Lease Annual', 'lease_book_expense', col)
            # One aggregate defect per year, added only once across contracts.
            if cash:
                draft.add('Lease Annual', 'lease_tax_deduction', col,
                    '=' + draft.address('Lease Annual', 'lease_book_expense', col), expense,
                    'lease_cash_vs_book_tax_interface',
                    'The programme deducts total actual lease cash, not lease book expense, under the stated hypothetical tax agreement.',
                    {'module': 'lease_programme_interface', 'fiscal_year': year})


def _regulatory_defects(draft, contract):
    sheets = {'rav': 'Reopener RAV', 'tax': 'Reopener Tax Basis', 'claims': 'Reopener Claims',
              'loss': 'Reopener Tax Loss', 'annual': 'Reopener Statements'}
    columns = _columns(draft.book[sheets['annual']])
    p, batches = contract['parameters'], contract['batches']
    for index, batch in enumerate(batches):
        year, col = batch['commission_year'], columns[batch['commission_year']]
        label = lambda field: batch['id'] + ' | ' + field
        asset_row = next(cell.row for cell in draft.book['Reopener Assets']['A'] if cell.value == batch['id'])
        cost = "'Reopener Assets'!$F$" + str(asset_row)
        life = "'Reopener Assets'!$D$" + str(asset_row)
        context = {'module': 'programme', 'batch_id': batch['id'], 'fiscal_year': year, 'event_kind': 'commissioning'}
        dep = draft.value(sheets['rav'], label('depreciation'), col)
        draft.add(sheets['rav'], label('depreciation'), col, '=MIN(ROUND(' + cost + '/' + life + ',2),' + cost + ')',
            min(Decimal(batch['real_cost']), _q(Decimal(batch['real_cost']) / Decimal(batch['regulatory_life']))),
            'rav_first_service_half_year', 'Regulatory depreciation starts with the stated half-year charge, separately from lease monthly service.', context)
        before = draft.formula(sheets['tax'], label('capital_allowance'), col)
        # New reducing-balance additions receive half the pool rate in their
        # commissioning year; older balances and transfers receive the full rate.
        after = before.replace('/2)', ')')
        pool = batch['tax_pool']
        if pool in ('General', 'Special'):
            rate_key = 'general_rate' if pool == 'General' else 'special_rate'
            inp = next(row for row in contract['annual_inputs'] if int(row['year']) == year)
            allowance = draft.value(sheets['tax'], label('capital_allowance'), col)
            increment = _q(Decimal(batch['nominal_cost']) * Decimal(inp[rate_key])) - _q(Decimal(batch['nominal_cost']) / 2 * Decimal(inp[rate_key]))
            draft.add(sheets['tax'], label('capital_allowance'), col, after, allowance + increment,
                'tax_new_pool_half_rate', 'Only new commissioning additions receive half-rate pool allowances; their nominal tax cost is never indexed.', context)
        if pool == 'General':
            for inp in contract['annual_inputs']:
                year = int(inp['year'])
                if not Decimal(inp['general_transfer_fraction']) or year not in columns or columns[year] <= 3:
                    continue
                col = columns[year]
                before = draft.formula(sheets['tax'], label('special_close'), col)
                previous = draft.address(sheets['tax'], label('general_close'), col - 1)
                older = draft.address(sheets['tax'], label('general_close'), col - 2)
                # Shift the transferred opening pool back a reporting period;
                # this is a wrong vintage reference, without making a cycle.
                after = before.replace(previous, older)
                transfer_rate = Decimal(inp['general_transfer_fraction'])
                current = draft.value(sheets['tax'], label('special_close'), col)
                delta = _q((draft.value(sheets['tax'], label('general_close'), col - 2) -
                            draft.value(sheets['tax'], label('general_close'), col - 1)) * transfer_rate)
                prediction = current + delta - _q(delta * Decimal(inp['special_rate']))
                draft.add(sheets['tax'], label('special_close'), col, after, prediction,
                    'tax_transfer_opening_vintage', 'The General-to-Special transfer uses the immediately opening nominal General balance before current allowances.',
                    {'module': 'programme_tax', 'batch_id': batch['id'], 'fiscal_year': year, 'event_kind': 'pool_transfer'})
    for year, col in columns.items():
        ann = sheets['annual']
        v = lambda field: draft.value(ann, field, col)
        r = lambda field: draft.ref(ann, field, col)
        context = {'module': 'programme', 'fiscal_year': year}
        b, loss, tax_rate = v('pre_allowance_taxable_profit'), v('losses_available'), Decimal(next(row for row in contract['annual_inputs'] if int(row['year']) == year)['tax_rate'])
        if b > 0 and loss > 0:
            # An 80% limit applies to taxable income including its own tax
            # allowance; applying the cap only before gross-up is a real defect.
            cap = Decimal(p['loss_use_cap'])
            wrong_loss = min(loss, cap * b)
            draft.add(ann, 'losses_used', col, '=ROUND(MIN(' + r('losses_available') + ",\'Reopener Inputs\'!$B$32*" + r('pre_allowance_taxable_profit') + '),2)',
                _q(wrong_loss), 'tax_loss_limit_before_grossup',
                'Loss use is capped against taxable income including the continuous tax allowance before either result is posted.', context)
            draft.add(ann, 'current_tax_allowance', col,
                '=ROUND(' + r('pre_allowance_taxable_profit') + "*'Reopener Inputs'!" + L(col) + '5,2)',
                _q(b * tax_rate), 'tax_allowance_grossup_and_losses',
                'The current tax allowance itself is taxable; apply available FIFO losses and solve the stated continuous gross-up before posting.', context)
        # Actual positive expired vintages and constrained collection events.
        for vintage in contract['years']:
            vintage = int(vintage)
            for sheet, field in [(sheets['loss'], 'expired'), (sheets['claims'], 'collected')]:
                label = str(vintage) + ' | ' + field
                original = draft.value(sheet, label, col)
                if original <= 0:
                    continue
                before = draft.formula(sheet, label, col)
                if field == 'expired':
                    after = before.replace("'Reopener Inputs'!$B$31", "'Reopener Inputs'!$B$33")
                    # The receipt lag is longer than the actual loss window;
                    # only select a boundary where that lookup delays expiry.
                    if year <= vintage + int(p['claim_lag_years']):
                        draft.add(sheet, label, col, after, Decimal(0), 'tax_loss_expiry_policy_lookup',
                            'Tax losses expire under the loss carry window at the start of the year, independently of the revenue receipt lag.',
                            {**context, 'vintage': vintage, 'event_kind': 'loss_expiry'})
                elif col > 3:
                    close = draft.value(sheet, str(vintage) + ' | close', col - 1)
                    interest = draft.value(sheet, str(vintage) + ' | interest', col)
                    due = close + interest
                    if due > original:
                        draft.add(sheet, label, col,
                            '=ROUND(' + draft.ref(sheet, str(vintage) + ' | close', col - 1) + '+' +
                            draft.ref(sheet, str(vintage) + ' | interest', col) + ',2)', due,
                            'claim_shared_cap_fifo', 'All eligible claim vintages share the annual cash cap and settle oldest first, after current carrying interest.',
                            {**context, 'vintage': vintage, 'event_kind': 'binding_collection_cap'})
        if v('lease_regulatory_allowance'):
            # Sample the transfer/write-down/ownership-sale years and horizon,
            # where cash tax, receivables and parent funding are all linked.
            special = year in {min(columns), max(columns), 2030, 2031}
            if special:
                draft.add(ann, 'pre_allowance_taxable_profit', col,
                    '=ROUND(' + r('depreciation_nominal') + '+' + r('return_nominal') + '+' + r('claim_carrying_interest') +
                    '-' + r('debt_interest') + '-' + r('tax_capital_allowances') + '+' + r('lease_regulatory_allowance') +
                    '-' + r('lease_book_expense') + ',2)' if _label('lease_book_expense') in draft.rows.get(ann, {}) else
                    '=ROUND(' + draft.formula(ann, 'pre_allowance_taxable_profit', col)[1:] + '+' + r('lease_tax_deduction') +
                    '-' + r('lease_book_depreciation') + '-' + r('lease_book_interest') + '+' + r('lease_termination_gain_loss') + ',2)',
                    v('pre_allowance_taxable_profit') + v('lease_tax_deduction') - v('lease_book_depreciation') - v('lease_book_interest') + v('lease_termination_gain_loss'),
                    'programme_lease_cash_tax_bridge', 'Deduct actual total lease cash, while book depreciation, interest and signed gain remain separate profit measures.', context)
        if v('disallowance_real'):
            draft.add(ann, 'net_income', col,
                '=ROUND(' + draft.formula(ann, 'net_income', col)[1:] + '+' + r('disallowance_nominal') + ',2)',
                v('net_income') + v('disallowance_nominal'), 'rav_disallowance_book_expense',
                'Disallowed RAV is a noncash book loss without a current cash or tax-basis deduction.', {**context, 'event_kind': 'rav_disallowance'})


def _holding_defects(draft, contracts):
    holding = contracts['holding']
    parameters = holding['parameters']
    ownership, fx = Decimal(parameters['operating_ownership']), Decimal(parameters['gbp_per_usd'])
    sheet, parent, group = 'Holding Operating Link', 'Holding Statements', 'Holding Consolidated'
    # Bridge rows are identified by dates; their public date/FY definitions
    # themselves remain untouched. Only economic translation cells are roots.
    headers = {_label(cell.value): cell.column for cell in draft.book[sheet][2] if cell.value}
    for row in range(3, draft.book[sheet].max_row + 1):
        when = draft.cached[sheet].cell(row, headers['date']).value
        if not isinstance(when, (date, datetime)):
            raise ValueError('Operating translation requires the original cached calendar dates')
        for field, source in [('income gbp', 'income usd'), ('dividend gbp', 'dividend usd')]:
            address = draft.book[sheet].cell(row, headers[field]).coordinate
            before = draft.book[sheet][address].value
            usd_address = draft.book[sheet].cell(row, headers[source]).coordinate
            usd_formula = draft.book[sheet][usd_address].value
            # The raw original project cell is the first range token of its
            # USD-share formula. Read it to test whether omitted intermediate
            # USD posting actually changes the GBP penny.
            tokens = [token.value for token in Tokenizer(usd_formula).items
                      if token.type == 'OPERAND' and token.subtype == 'RANGE']
            if not tokens or '!' not in tokens[0]:
                raise ValueError('Unrecognized original operating ownership formula')
            sn, source_address = tokens[0].rsplit('!', 1)
            sn = sn[1:-1].replace("''", "'") if sn.startswith("'") else sn
            raw = _number(draft.cached[sn][source_address].value)
            actual = _number(draft.cached[sheet][address].value)
            wrong = _q(raw * ownership * fx)
            if _q(actual) != wrong:
                # _Draft.add is row-label based; this vertical bridge instead
                # uses the same checked insertion through a temporary label map.
                key = '__bridge_' + str(row) + '_' + str(headers[field])
                draft.rows.setdefault(sheet, {})[_label(key)] = row
                draft.add(sheet, key, headers[field],
                    '=ROUND(' + tokens[0] + "*'Holding Inputs'!$B$9*'Holding Inputs'!$B$10,2)", wrong,
                    'associate_usd_then_gbp_posting',
                    'Post each monthly ownership share to USD cents before separately translating that posted amount to GBP cents.',
                    {'module': 'holding_operating_bridge', 'date': when.isoformat(), 'field': field})
    columns = _columns(draft.book[parent])
    annual_inputs = {int(row['year']): row for row in holding['annual_inputs']}
    for year, col in columns.items():
        context = {'module': 'holding', 'fiscal_year': year}
        v = lambda field: draft.value(parent, field, col)
        r = lambda field: draft.ref(parent, field, col)
        if v('operating_income') or v('operating_dividend'):
            for field, sourcecol in [('operating_income', 'G'), ('operating_dividend', 'H')]:
                # Calendar-year aggregation is a plausible mismatch when the
                # source project is Jan–Dec and holding is Apr–Mar.
                wrong = sum((_number(draft.cached[sheet].cell(row, openpyxl.utils.column_index_from_string(sourcecol)).value)
                             for row in range(3, draft.book[sheet].max_row + 1)
                             if draft.cached[sheet].cell(row, 1).value.year == year), Decimal(0))
                draft.add(parent, field, col,
                    '=ROUND(SUMIFS(\'Holding Operating Link\'!$' + sourcecol + '$3:$' + sourcecol + '$38,'
                    "'Holding Operating Link'!$A$3:$A$38,\">=\"&DATE(" + str(year) + ',1,1),'
                    "'Holding Operating Link'!$A$3:$A$38,\"<\"&DATE(" + str(year + 1) + ',1,1)),2)', wrong,
                    'associate_calendar_vs_fiscal_year',
                    'Aggregate the original monthly project dates into the holding April–March reporting year without shifting those dates.', context)
        if v('operating_sale'):
            draft.add(parent, 'operating_sale_carrying', col,
                '=ROUND(' + r('operating_investment_open') + '+' + r('operating_acquisition') + '-' + r('operating_dividend') + ',2)',
                v('operating_investment_open') + v('operating_acquisition') - v('operating_dividend'),
                'associate_disposal_current_income', 'Sale derecognizes carrying amount after the current posted equity-method income and dividends.',
                {**context, 'event_kind': 'associate_exit'})
            draft.add(parent, 'operating_sale_gain', col, '=' + r('operating_sale'), v('operating_sale'),
                'associate_proceeds_vs_disposal_gain', 'Recognize proceeds less the derecognized associate carrying amount as disposal gain.',
                {**context, 'event_kind': 'associate_exit'})
        if col > min(columns.values()) and Decimal(annual_inputs[year]['claim_haircut']) != Decimal(annual_inputs[year - 1]['claim_haircut']):
            before = draft.formula(parent, 'claims_after_haircut', col)
            current = "'Holding Inputs'!" + L(col) + '18'
            previous = "'Holding Inputs'!" + L(col - 1) + '18'
            after = before.replace(current, previous)
            # The programme claim is the first direct source range token.
            tokens = [t.value for t in Tokenizer(before).items if t.type == 'OPERAND' and t.subtype == 'RANGE']
            source = next(t for t in tokens if 'Reopener Statements' in t)
            sn, address = source.rsplit('!', 1)
            sn = sn[1:-1].replace("''", "'") if sn.startswith("'") else sn
            claims = _number(draft.cached[sn][address].value)
            draft.add(parent, 'claims_after_haircut', col, after,
                _q(claims * (1 - Decimal(annual_inputs[year - 1]['claim_haircut']))),
                'holding_current_collateral_haircut', 'The current fiscal-year haircut applies to closing programme claims before the advance percentage.',
                {**context, 'event_kind': 'credit_policy_transition'})
        senior = v('senior_obligations')
        if senior and 0 < v('borrowing_base') < Decimal(parameters['facility_limit']):
            prog_annual = contracts['programme']['years']
            pc = list(map(int, prog_annual)).index(year) + 3
            lease_liability = draft.value('Reopener Statements', 'lease_liability_close', pc)
            if lease_liability:
                draft.add(parent, 'senior_obligations', col,
                    '=' + draft.ref('Reopener Statements', 'debt_close', pc), senior - lease_liability,
                    'holding_senior_lease_collateral',
                    'Closing programme lease liabilities and bank debt both reduce the borrowing base; ROU is not additional eligible collateral.', context)
        if v('mandatory_margin'):
            draft.add(parent, 'mandatory_margin', col,
                '=MAX(0,' + r('borrowing_base') + '-' + r('bank_open') + ')',
                max(Decimal(0), v('borrowing_base') - v('bank_open')),
                'holding_margin_direction', 'Opening debt above closing collateral capacity must be repaid before discretionary repayment, new draws or LP calls.',
                {**context, 'event_kind': 'mandatory_margin_call'})
            draft.add(parent, 'bank_draw', col,
                '=MIN(MAX(0,\'Holding Inputs\'!$B$4-' + r('funding_after_repayments') + '),MAX(0,\'Holding Inputs\'!$B$5-' +
                r('bank_open') + '+' + r('mandatory_margin') + '+' + r('optional_repayment') + '))',
                min(max(Decimal(0), Decimal(parameters['minimum_cash']) - v('funding_after_repayments')),
                    max(Decimal(0), Decimal(parameters['facility_limit']) - v('bank_open') + v('mandatory_margin') + v('optional_repayment'))),
                'holding_facility_vs_collateral_headroom', 'New draws are limited by the current borrowing base after repayments, not merely the contractual facility limit.',
                {**context, 'event_kind': 'mandatory_margin_call'})
        if v('optional_repayment') and (year == max(columns) or not draft.value(parent, 'optional_repayment', col - 1)):
            draft.add(parent, 'optional_repayment', col,
                '=MIN(' + r('bank_open') + '-' + r('mandatory_margin') + ',MAX(0,' + r('funding_after_margin') + '))',
                min(v('bank_open') - v('mandatory_margin'), max(Decimal(0), v('funding_after_margin'))),
                'holding_minimum_cash_priority', 'Only cash exceeding the required minimum is available for optional bank repayment.',
                {**context, 'event_kind': 'discretionary_repayment_transition'})
        # Whole group cash classifications, not a stand-alone presentation
        # helper: these are externally scored cash-flow results and feed the
        # consolidated cash reconciliation.
        gv = lambda field: draft.value(group, field, col)
        gr = lambda field: draft.ref(group, field, col)
        if year in {min(columns), 2030, 2031, 2037, max(columns)}:
            for field, elim, sign in [('cfi', 'owner_capital_elimination', -1), ('cfo', 'owner_distribution_elimination', 1)]:
                amount = gv(elim)
                if amount:
                    draft.add(group, field, col,
                        '=ROUND(' + draft.formula(group, field, col)[1:] + ('-' if sign < 0 else '+') + gr(elim) + ',2)',
                        gv(field) + sign * amount, 'consolidation_owner_cash_classification',
                        'Eliminate both sides of programme owner cash across their originally different cash-flow classifications.', context)
            if gv('programme_lease_liability'):
                draft.add(group, 'liabilities', col,
                    '=ROUND(' + gr('parent_liabilities') + '+' + gr('programme_bank_debt') + ',2)',
                    gv('liabilities') - gv('programme_lease_liability'), 'consolidation_external_lease_obligation',
                    'Programme lease obligations remain external group liabilities after investment and equity eliminations.', context)
            if year != min(columns) and gv('programme_oci'):
                draft.add(group, 'oci', col,
                    '=ROUND(' + gr('parent_oci') + '+' + gr('programme_oci') + ',2)',
                    gv('parent_oci') + gv('programme_oci'), 'consolidation_duplicate_programme_oci',
                    'Eliminate programme OCI already recognized through the parent programme investment before reporting consolidated OCI.', context)


def propose_task(baseline: Path, mode: str = 'debugging', *, max_roots: int = 240) -> dict:
    """Propose 100–300 distinct active semantic defects with exact assertions.

    Each local activity record is private and uses original caches only. No
    mutated workbook or cached answer is written and no engine/model is called.
    """
    if mode != 'debugging':
        raise ValueError('Composite debugging adapter supports debugging only')
    if type(max_roots) is not int or not 100 <= max_roots <= 300:
        raise ValueError('max_roots must be an integer from 100 through 300')
    baseline = Path(baseline)
    book = openpyxl.load_workbook(baseline, data_only=False, keep_links=False)
    cached = None
    try:
        contracts = _public_contracts(book)
        evidence = _policy_evidence(book)
        cached = openpyxl.load_workbook(baseline, data_only=True, keep_links=False)
        draft = _Draft(book, cached)
        _lease_defects(draft, contracts['lease'])
        _regulatory_defects(draft, contracts['programme'])
        _holding_defects(draft, contracts)
        # Keep module/mechanism diversity when an explicit smaller budget is
        # requested. Round-robin is deterministic and never selects by score.
        families = {}
        for edit in draft.edits:
            families.setdefault(edit['mechanism'], []).append(edit)
        selected = []
        while families and len(selected) < max_roots:
            for mechanism in list(families):
                selected.append(families[mechanism].pop(0))
                if not families[mechanism]:
                    del families[mechanism]
                if len(selected) == max_roots:
                    break
        if len(selected) < 100:
            raise ValueError(f'Composite source supports fewer than 100 locally active heterogeneous defects: {len(selected)}')
        modules = {edit['event_context']['module'].split('_')[0] for edit in selected}
        if not {'lease', 'programme', 'holding'}.issubset(modules):
            raise ValueError('Semantic debugging proposal does not cover all linked finance modules')
        return {
            'title': 'Repair the linked lease, regulatory and holding finance model',
            'business_context': 'A hypothetical capital programme and lease portfolio funded through a holding partnership with an operating associate.',
            'public_instruction': (
                'Review and repair the hypothetical integrated financial model using the business briefs and provided contracts. '
                'Lease measurements and payments, regulatory capital and tax recovery, ownership translation, parent funding '
                'and consolidated reporting may disagree with the stated policies. Trace inconsistencies across the linked '
                'modules and restore economically consistent results over the original reporting horizon, including event '
                'boundaries and closing balances. Preserve primitive assumptions, dates, labels, the published regulatory '
                'background and unaffected calculations. Allow dependent financial results to recalculate and save the '
                'repaired workbook to the required output path.'),
            'public_rules': ['Use the supplied inputs and explicit public business policies for every affected module and its stated links, units and calendar.'],
            'reference_evidence': evidence,
            'scenario_inputs': [], 'edits': selected,
            'target_sheets': sorted({edit['sheet'] for edit in selected}),
            'involved_sheets': list(book.sheetnames), 'native_issues': [],
            'semantic_authoring_receipt': {
                'version': 1, 'baseline_sha256': hashlib.sha256(baseline.read_bytes()).hexdigest(),
                'candidate_count': len(draft.edits), 'selected_count': len(selected),
                'mechanism_counts': dict(Counter(edit['mechanism'] for edit in selected)),
                'local_arithmetic_screen_only': True, 'actual_root_impact_certified': False,
                'source_modified': False, 'model_calls': 0,
                'required_next_step': 'Actual individual and full-combined marginal impact proof; then controls and independent quality gates.'}}
    finally:
        book.close()
        if cached is not None:
            cached.close()


def suggest_root_impact_batches(baseline: Path, edits: list, *,
                                max_dependency_cells: int = 500000,
                                per_formula_reference_cells: int = 50000,
                                max_dependency_edges: int = 5000000) -> dict:
    """Color the root-interference graph for later *actual* batch proofs.

    An edge exists if either original or fully mutated ancestry lets one root
    read the other. An unresolved reference, cycle or exhausted bound rejects
    this proposal; the helper never turns missing analysis into independence.
    A returned partition is only preparation for the executed batch checker.
    """
    from ..profile import formula_references
    from ..static_references import static_formula_text

    if not isinstance(edits, list) or not edits:
        raise ValueError('Nonempty edits are required for root grouping')
    bounds = ((max_dependency_cells, 500000), (per_formula_reference_cells, 50000),
              (max_dependency_edges, 5000000))
    if any(type(value) is not int or not 1 <= value <= maximum for value, maximum in bounds):
        raise ValueError('Unsupported dependency grouping limit')
    roots = [(edit['sheet'], edit['cell']) for edit in edits]
    if len(set(roots)) != len(roots):
        raise ValueError('Duplicate roots cannot be grouped')
    indices = {root: index for index, root in enumerate(roots)}
    book = openpyxl.load_workbook(baseline, data_only=False, keep_links=False)
    neighbors = [set() for _ in roots]
    receipts = {}
    try:
        for edit in edits:
            cell = book[edit['sheet']][edit['cell']]
            if cell.data_type != 'f' or cell.value != edit['before']:
                raise ValueError('Grouping before assertion differs from the immutable source')
        for variant in ('original', 'fully_mutated'):
            if variant == 'fully_mutated':
                for edit in edits:
                    book[edit['sheet']][edit['cell']] = edit['after']
            graph, state, order, reference_cache = {}, {}, [], {}
            edges = 0
            for root in roots:
                pending = [(root, False)]
                while pending:
                    node, leaving = pending.pop()
                    if leaving:
                        if state[node] != 2:
                            state[node] = 2
                            order.append(node)
                        continue
                    if state.get(node) == 2:
                        continue
                    if state.get(node) == 1:
                        raise ValueError('Cycle in root dependency analysis')
                    state[node] = 1
                    if len(state) > max_dependency_cells:
                        raise ValueError('Root grouping dependency cell bound exceeded')
                    name, address = node
                    if name not in book:
                        raise ValueError('Missing dependency worksheet during root grouping')
                    cell = book[name][address]
                    dependencies = []
                    if cell.data_type == 'f':
                        formula = static_formula_text(cell)
                        found = formula_references(formula, name,
                            max_expansion=per_formula_reference_cells, workbook=book,
                            cache=reference_cache)
                        if not found['fully_supported']:
                            raise ValueError('Unresolved formula ancestry cannot establish root separation')
                        dependencies = list(dict.fromkeys((ref['sheet'], ref['cell'])
                                                         for ref in found['references']))
                    graph[node] = dependencies
                    edges += len(dependencies)
                    if edges > max_dependency_edges:
                        raise ValueError('Root grouping dependency edge bound exceeded')
                    pending.append((node, True))
                    for dependency in reversed(dependencies):
                        if state.get(dependency) == 1:
                            raise ValueError('Cycle in root dependency analysis')
                        if state.get(dependency) != 2:
                            pending.append((dependency, False))
            # Postorder propagation avoids one complete long-chain walk per
            # root. A Python integer stores its exact reachable-root bitset.
            ancestors = {}
            for node in order:
                bits = 0
                for dependency in graph[node]:
                    bits |= ancestors[dependency]
                    if dependency in indices:
                        bits |= 1 << indices[dependency]
                ancestors[node] = bits
                if node in indices:
                    index = indices[node]
                    if bits & (1 << index):
                        raise ValueError('A root recursively depends on itself')
                    while bits:
                        bit = bits & -bits
                        other = bit.bit_length() - 1
                        neighbors[index].add(other)
                        neighbors[other].add(index)
                        bits ^= bit
            receipts[variant] = {'visited_cells': len(graph), 'dependency_edges': edges,
                                 'all_references_resolved': True, 'cycles': False}
        colors = {}
        for index in sorted(range(len(roots)), key=lambda i: (-len(neighbors[i]), i)):
            unavailable = {colors[neighbor] for neighbor in neighbors[index] if neighbor in colors}
            color = 0
            while color in unavailable:
                color += 1
            colors[index] = color
        batches = [sorted(index for index, color in colors.items() if color == group)
                   for group in range(max(colors.values()) + 1)]
        conflicts = [[index, other] for index, values in enumerate(neighbors)
                     for other in sorted(values) if index < other]
        return {'version': 1, 'planning_only': True, 'actual_root_impact_certified': False,
            'method': 'original_and_fully_mutated_ancestor_interference_graph',
            'baseline_sha256': hashlib.sha256(Path(baseline).read_bytes()).hexdigest(),
            'edits_sha256': hashlib.sha256(json.dumps(edits, sort_keys=True,
                separators=(',', ':'), allow_nan=False).encode()).hexdigest(),
            'root_count': len(roots), 'batch_count': len(batches),
            'root_impact_batches': batches, 'conflict_pairs': conflicts,
            'graph_coverage': receipts,
            'required_next_step': 'Recalculate each batch in original and full-mutated restoration contexts and run the fail-closed batch certificates.'}
    finally:
        book.close()

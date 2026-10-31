"""Public-table recovery for the version-two heterogeneous business template.

Only the supplied workbook is parsed. No source manifest, private specification,
goal, binding map, emitter, or projection planner is imported or read. The
Decimal ledger is shared with the source's independent audit implementation; it
is independent of the native Excel formula implementation, not a third ledger.
This module does not launch Calc or claim an actual isolated replay witness.
"""
from __future__ import annotations

import calendar
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import openpyxl
from openpyxl.utils.datetime import WINDOWS_EPOCH

from .heterogeneous_contracts import spec, ledger

PUBLIC_SHEETS = ('Contract Notes', 'Calendar', 'Entity Policies', 'Opening Balances',
    'Facilities', 'Facility Terms', 'Asset Register', 'Operating Forecast',
    'Scenario Assumptions', 'Portfolio Funding', 'Allocation Priorities', 'Opening Tax Attributes')
FORECAST_VIEWS = ('Statements', 'Debt', 'Tax', 'Covenants', 'Assets', 'Interest Carry', 'Loss Carry', 'Group')
ASSET_POLICY = ('Pay for and capitalise an asset at the end of its commissioning month. '
    'From the following month, charge monthly straight-line depreciation using original cost and stated useful-life months, '
    'rounded to pennies with halves away from zero. Cap each charge at remaining net book value and charge any remaining '
    'balance in the final useful-life month. Use supplied opening accumulated depreciation as the opening book balance.')
CLOSED_POLICY = ('Closed facilities have no current coupon, principal instalment or DSCR test. '
    'A blank non-applicable covenant display is intentional.')
BACKEND = 'heterogeneous_public_tables_shared_decimal_financial_ledger'

HEADERS = {
    'Calendar': ('Month', 'Month end', 'Actual days', 'Quarter end'),
    'Entity Policies': ('Entity', 'Name', 'Tax policy', 'Tax rate', 'Interest cap', 'Interest carry months',
        'Loss carry months', 'Covenant policy', 'Minimum DSCR times', 'Minimum cash GBP', 'Reserve target GBP',
        'Additional LP GBP', 'Opening restriction', 'Opening cure count'),
    'Opening Balances': ('Entity', 'Cash GBP', 'Restricted cash GBP', 'Paid-in capital GBP', 'Retained earnings GBP', 'Income tax payable GBP'),
    'Facilities': ('Facility', 'Entity', 'Contract type', 'Opening principal GBP', 'Opening accrued interest GBP'),
    'Facility Terms': ('Term', 'Facility', 'Effective month', 'Annual quote', 'Day-count basis', 'Local limit GBP',
        'Maturity', 'Draw cutoff', 'Voluntary repayment fraction', 'Next coupon month'),
    'Asset Register': ('Asset', 'Entity', 'Description', 'Commission month', 'Original cost GBP', 'Opening depreciation GBP', 'Useful life months', 'Capex class'),
    'Operating Forecast': ('Entity', 'Month', 'Cash revenue GBP', 'Cash operating cost GBP'),
    'Scenario Assumptions': ('Scenario', 'Month', 'Revenue factor', 'Operating cost factor', 'Annual rate spread'),
    'Portfolio Funding': ('Contract item', 'Effective month', 'Amount GBP'),
    'Allocation Priorities': ('Allocation', 'Priority', 'Entity'),
    'Opening Tax Attributes': ('Entity', 'Attribute', 'Origin month', 'Amount GBP'),
}


class PublicRecoveryError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PublicRecoveryError(message)


def _reference(path):
    p = Path(path).absolute()
    require(p == p.resolve() and p.is_file() and not p.is_symlink(), 'A regular nonsymlink public artifact is required')
    before = p.stat()
    h = hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b''):
            h.update(block)
    after = p.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
        'A public artifact changed while hashing')
    return {'path': str(p), 'sha256': h.hexdigest(), 'bytes': after.st_size}


def _text(value):
    require(type(value) is str and bool(value) and '/data/' not in value and 'file://' not in value,
        'A nonempty public business label is required')
    if value.lstrip().startswith(('{', '[')):
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = None
        require(not isinstance(parsed, (dict, list)), 'Prejoined JSON is not a public business table')
    return value


def _integer(value, scale=1):
    require(type(value) in (int, float, Decimal), 'A numeric business primitive is required')
    n = Decimal(str(value))
    require(n.is_finite() and (n * scale) == (n * scale).to_integral_value(),
        'A public primitive does not match its stated exact unit')
    return int(n * scale)


def _day(value, *, nullable=False, month=False):
    if nullable and value is None:
        return None
    require(type(value) in (date, datetime), 'A real public date cell is required')
    if isinstance(value, datetime):
        require(value.time() == datetime.min.time() and value.tzinfo is None, 'Public dates must be whole local dates')
    result = value.date() if isinstance(value, datetime) else value
    require(not month or result.day == 1, 'A month-start date is required')
    return result.isoformat()


def _rows(book, title, headers):
    sheet = book[title]
    result = []
    for index, cells in enumerate(sheet.iter_rows(values_only=True), 1):
        values = list(cells)
        require(all(v is None for v in values[len(headers):]), 'Unexpected public table columns')
        values = (values + [None] * len(headers))[:len(headers)]
        if index == 1:
            require(tuple(values) == tuple(headers), 'Public business table headers changed: ' + title)
        elif any(v is not None for v in values):
            result.append(values)
    return result


def _public_contract(book):
    require(book.epoch == WINDOWS_EPOCH and not book.defined_names
        and not getattr(book, '_external_links', []), 'Unsupported public epoch, names or external links')
    require(all(name in book.sheetnames for name in PUBLIC_SHEETS), 'A native public input/notes sheet is missing')
    for sheet in book:
        require(sheet.sheet_state == 'visible', 'Every public business worksheet must be visible')
        for row in sheet.iter_rows():
            for cell in row:
                require(cell.data_type not in ('f', 'e') and type(cell.value) is not bool,
                    'The public business template must have no formulas, error caches or Boolean encodings')
    notes = []
    for row in book['Contract Notes'].iter_rows(values_only=True):
        require(all(v is None for v in row[2:]), 'Unexpected policy-note columns')
        if any(v is not None for v in row):
            notes.append(tuple((list(row) + [None, None])[:2]))
    expected = [('Heterogeneous debt and tax contracts', 'Public policy')]
    expected += [('Policy ' + str(i), value) for i, value in enumerate((*spec.RULES, CLOSED_POLICY), 1)]
    expected += [('Close phase', value) for value in spec.PHASES]
    expected += [('Asset depreciation', ASSET_POLICY)]
    require(notes == expected, 'The complete public financial policy, including the asset convention, is required')


def _parse_book(book):
    _public_contract(book)
    months = []
    for start, end, days, quarter in _rows(book, 'Calendar', HEADERS['Calendar']):
        month = _day(start, month=True)
        d = date.fromisoformat(month)
        count = calendar.monthrange(d.year, d.month)[1]
        require(_day(end) == d.replace(day=count).isoformat()
            and _integer(days) == count and _integer(quarter) == int(d.month % 3 == 0),
            'The supplied public calendar is inconsistent')
        months.append(month)
    entities = []
    for r in _rows(book, 'Entity Policies', HEADERS['Entity Policies']):
        flag = _integer(r[12]); require(flag in (0, 1), 'An opening restriction must be numeric zero or one')
        entities.append({'id': _text(r[0]), 'name': _text(r[1]), 'functional_currency': 'GBP',
            'tax_policy': _text(r[2]), 'tax_rate_p12': _integer(r[3], spec.SCALE),
            'interest_cap_fraction_p12': _integer(r[4], spec.SCALE), 'interest_carry_months': _integer(r[5]),
            'loss_carry_months': _integer(r[6]), 'dscr_policy': _text(r[7]),
            'dscr_threshold_p12': _integer(r[8], spec.SCALE), 'minimum_cash_pence': _integer(r[9], 100),
            'reserve_target_pence': _integer(r[10], 100), 'additional_lp_commitment_pence': _integer(r[11], 100),
            'opening_trap': bool(flag), 'opening_cure_count': _integer(r[13]),
            'opening_interest_carry': [], 'opening_tax_losses': []})
    require(len({e['id'] for e in entities}) == len(entities), 'Duplicate public entity')
    entities.sort(key=lambda e: e['id'])
    by_entity = {e['id']: e for e in entities}
    opening_seen = set()
    opening_fields = ('opening_cash_pence', 'opening_restricted_cash_pence', 'opening_paid_in_capital_pence',
        'opening_retained_earnings_pence', 'opening_tax_payable_pence')
    for eid, *amounts in _rows(book, 'Opening Balances', HEADERS['Opening Balances']):
        require(eid in by_entity and eid not in opening_seen, 'Missing or duplicate public opening identity')
        opening_seen.add(eid)
        by_entity[eid].update({field: _integer(value, 100) for field, value in zip(opening_fields, amounts)})
    require(opening_seen == set(by_entity), 'The public opening balances are incomplete')
    loans = []
    for lid, eid, kind, principal, accrued in _rows(book, 'Facilities', HEADERS['Facilities']):
        loans.append({'id': _text(lid), 'entity_id': _text(eid), 'type': _text(kind),
            'opening_principal_pence': _integer(principal, 100), 'opening_accrued_interest_pence': _integer(accrued, 100), 'terms': []})
    by_loan = {l['id']: l for l in loans}
    require(len(by_loan) == len(loans), 'Duplicate public facility')
    for r in _rows(book, 'Facility Terms', HEADERS['Facility Terms']):
        require(r[1] in by_loan, 'A public term references an unknown facility')
        by_loan[r[1]]['terms'].append({'id': _text(r[0]), 'effective_month': _day(r[2], month=True),
            'annual_rate_p12': _integer(r[3], spec.SCALE), 'day_count': _text(r[4]),
            'local_limit_pence': _integer(r[5], 100), 'maturity_date': _day(r[6]),
            'draw_cutoff_month': _day(r[7], nullable=True, month=True),
            'optional_repayment_fraction_p12': _integer(r[8], spec.SCALE),
            'next_coupon_month': _day(r[9], nullable=True, month=True)})
    for loan in loans:
        loan['terms'].sort(key=lambda t: t['effective_month'])
    assets = [{'id': _text(r[0]), 'entity_id': _text(r[1]), 'description': _text(r[2]),
        'commission_month': _day(r[3], month=True), 'original_cost_pence': _integer(r[4], 100),
        'opening_accumulated_depreciation_pence': _integer(r[5], 100), 'useful_life_months': _integer(r[6]),
        'capex_category': _text(r[7])} for r in _rows(book, 'Asset Register', HEADERS['Asset Register'])]
    operating = {eid: {} for eid in by_entity}
    for eid, day, revenue, cost in _rows(book, 'Operating Forecast', HEADERS['Operating Forecast']):
        month = _day(day, month=True)
        require(eid in operating and month in months and month not in operating[eid], 'Duplicate or unknown operating identity/month')
        operating[eid][month] = {'month': month, 'base_cash_revenue_pence': _integer(revenue, 100),
            'base_cash_opex_pence': _integer(cost, 100)}
    require(all(set(rows) == set(months) for rows in operating.values()), 'The public operating calendar is incomplete')
    scenarios = {}
    for sid, day, revenue, cost, spread in _rows(book, 'Scenario Assumptions', HEADERS['Scenario Assumptions']):
        month = _day(day, month=True); sid = _text(sid)
        values = scenarios.setdefault(sid, {})
        require(month in months and month not in values, 'Duplicate or unknown scenario month')
        values[month] = {'month': month, 'revenue_factor_p12': _integer(revenue, spec.SCALE),
            'opex_factor_p12': _integer(cost, spec.SCALE), 'annual_rate_spread_p12': _integer(spread, spec.SCALE)}
    require(bool(scenarios) and all(set(rows) == set(months) for rows in scenarios.values()), 'The public scenario calendar is incomplete')
    scenario_ids = sorted(scenarios)
    group, commitments = {'shared_bank_limit_schedule': []}, 0
    for item, day, amount in _rows(book, 'Portfolio Funding', HEADERS['Portfolio Funding']):
        if item == 'Additional LP commitment':
            require(day is None and commitments == 0, 'The public group commitment is duplicated or dated')
            group['additional_lp_commitment_pence'] = _integer(amount, 100); commitments += 1
        else:
            require(item == 'Shared bank limit', 'Unknown public funding item')
            group['shared_bank_limit_schedule'].append({'effective_month': _day(day, month=True), 'limit_pence': _integer(amount, 100)})
    require(commitments == 1, 'The public group commitment is missing')
    group['shared_bank_limit_schedule'].sort(key=lambda r: r['effective_month'])
    priorities = {'Shared margin': 'shared_margin_priority', 'Bank funding': 'bank_funding_priority', 'LP funding': 'lp_funding_priority'}
    ranked = {key: {} for key in priorities}
    for kind, rank, eid in _rows(book, 'Allocation Priorities', HEADERS['Allocation Priorities']):
        require(kind in priorities, 'Unknown allocation policy')
        position = _integer(rank)
        require(position not in ranked[kind], 'Duplicate allocation rank')
        ranked[kind][position] = _text(eid)
    for label, key in priorities.items():
        require(set(ranked[label]) == set(range(1, len(entities) + 1)), 'Allocation ranks must be complete')
        group[key] = [ranked[label][i] for i in range(1, len(entities) + 1)]
    vintages_seen = set()
    for eid, kind, origin, amount in _rows(book, 'Opening Tax Attributes', HEADERS['Opening Tax Attributes']):
        require(eid in by_entity and kind in ('Denied interest', 'Tax loss'), 'Unknown public tax-attribute identity')
        month = _day(origin, month=True); key = eid, kind, month
        require(key not in vintages_seen, 'Duplicate public tax-attribute origin')
        vintages_seen.add(key)
        by_entity[eid]['opening_interest_carry' if kind == 'Denied interest' else 'opening_tax_losses'].append(
            {'origin_month': month, 'amount_pence': _integer(amount, 100)})
    for entity in entities:
        for key in ('opening_interest_carry', 'opening_tax_losses'):
            entity[key].sort(key=lambda r: r['origin_month'])
    n, periods = len(entities), len(months)
    mode = {(6, 24): 'prototype_6_24_3', (12, 60): 'candidate_12_60_3'}.get((n, periods))
    if mode is None:
        require(1 <= n <= 3 and 1 <= periods <= 3, 'Unsupported complete public dimensions')
        mode = 'toy'
    public = {'schema_version': 1, 'dimension_mode': mode, 'currency': 'GBP', 'rate_scale': spec.SCALE,
        'months': months, 'start_month': months[0] if months else None, 'scenario_ids': scenario_ids,
        'entities': entities, 'loans': loans, 'assets': assets,
        'operating_inputs': {eid: [values[m] for m in months] for eid, values in operating.items()},
        'scenarios': [{'id': sid, 'monthly_schedule': [scenarios[sid][m] for m in months]} for sid in scenario_ids], 'group': group}
    try:
        public = spec.load_spec(public)
    except (ValueError, KeyError, TypeError, IndexError) as error:
        raise PublicRecoveryError('The complete public primitives violate the financial schema: ' + str(error)) from error
    require(book.sheetnames == list(PUBLIC_SHEETS) + [sid + ' ' + name for sid in scenario_ids for name in FORECAST_VIEWS],
        'The complete business worksheet names or order changed')
    return public


def parse_public_workbook(input_path):
    """Read only actual public cells, never a JSON or private source artifact."""
    before = _reference(input_path)
    book = openpyxl.load_workbook(input_path, read_only=True, data_only=False, keep_links=True)
    try:
        public = _parse_book(book)
        public_forecast_slots(book, public)
    finally:
        book.close()
    require(_reference(input_path) == before, 'The public workbook changed during parsing')
    return public


_IS = set('revenue cash_opex ebitda depreciation ebit interest_accrual current_tax_expense net_income'.split())
_COV = set('cfads mandatory_debt_service dscr_window_cfads dscr_window_debt_service test_applicable test_pass dscr_ratio_millionths trap_open trap_operative trap_next facility_closed_open facility_closed_next feasible'.split())
_TAX = set('tax_payable_open eligible_current_interest interest_capacity interest_carry_open interest_expired interest_old_used interest_current_allowed interest_denied_created interest_carry_close taxable_before_losses loss_open loss_expired loss_used loss_created loss_close taxable_after_losses'.split())
_DEBT = set('principal_open scheduled_principal local_margin_principal shared_margin_principal voluntary_principal bank_draw interest_payable_open lp_call lp_called_cumulative funding_gap'.split())
_BS = set('cash_close reserve_close asset_nbv_open asset_nbv_close principal_close interest_payable_close tax_payable_close total_assets total_liabilities total_equity paid_in_close retained_close'.split())
_EQUITY = set('paid_in_open retained_open distribution return_of_capital profit_distribution'.split())
_SPECIAL_LABELS = {'annual_rate_p12': 'Effective annual interest rate', 'dscr_ratio_millionths': 'Debt-service coverage ratio',
    'trap_open': 'Restriction at month opening', 'trap_operative': 'Restriction applying this month',
    'trap_next': 'Restriction at next month opening', 'test_applicable': 'Covenant test applies',
    'test_pass': 'Covenant test passed', 'facility_closed_open': 'Facility closed at opening',
    'facility_closed_next': 'Facility closed at next opening', 'recast_due': 'Principal instalment reset applies',
    'recast_instalment': 'Reset principal instalment', 'day_basis': 'Interest day-count denominator',
    'coupon_due': 'Cash coupon due', 'days': 'Actual days in month'}
_LOAN_MONEY = set(spec.LOAN_FIELDS) - {'month', 'term_id', 'annual_rate_p12', 'day_basis', 'days',
    'coupon_due', 'recast_due', 'facility_closed_open', 'facility_closed_next'}


def _label(field):
    return _SPECIAL_LABELS.get(field, field.replace('_check', ' reconciliation').replace('_', ' ').capitalize())


def _field_contract(domain, field):
    if field == 'test_pass':
        return 1, '0/1 or policy blank'
    if field == 'dscr_ratio_millionths':
        return 10**6, 'times or policy blank'
    if field == 'annual_rate_p12':
        return spec.SCALE, 'annual rate'
    if field in ('days', 'day_basis'):
        return 1, 'days'
    if (domain == 'entities' and field in set(spec.FLAG_FIELDS) | {'feasible'}) or field in (
            'coupon_due', 'recast_due', 'facility_closed_open', 'facility_closed_next') or (domain == 'group' and field == 'feasible'):
        return 1, '0/1'
    return 100, 'GBP'


def _field_sheet(domain, field):
    if domain == 'assets': return 'Assets'
    if domain == 'loans': return 'Debt'
    if domain == 'group': return 'Group'
    if field in _COV: return 'Covenants'
    if field in _TAX: return 'Tax'
    if field in _DEBT: return 'Debt'
    return 'Statements'


def _category(domain, field):
    if domain == 'loans': return 'Facility'
    if field in _IS: return 'Income statement'
    if field in _BS: return 'Balance sheet'
    if field in _EQUITY: return 'Equity'
    if field.endswith('_check'): return 'Reconciliations'
    return _field_sheet(domain, field)


def _fifo_origins(public, entity, attribute, t):
    """Public dated origin scope, including its first expired display month."""
    month = public['months'][t]
    carry = entity['interest_carry_months' if attribute == 'opening_interest_carry' else 'loss_carry_months']
    origins = set(public['months'][:t + 1]) | {v['origin_month'] for v in entity[attribute]}
    return {origin for origin in origins if t == 0
        or spec.month_index(month) - spec.month_index(origin) <= carry + 1}


def public_forecast_slots(book, public, *, require_masked=True):
    """Resolve a complete scope from public identities, accounts and dates only."""
    expected = {}
    domains = [('entities', public['entities'], [f for f in spec.ENTITY_FIELDS if f not in
        ('month', 'term_id', 'tax_policy', 'dscr_policy', 'cure_open', 'cure_next')]),
        ('loans', public['loans'], [f for f in spec.LOAN_FIELDS if f not in ('month', 'term_id')]),
        ('assets', public['assets'], [f for f in spec.ASSET_FIELDS if f != 'month']),
        ('group', [{'id': 'Group'}], [f for f in spec.GROUP_FIELDS if f != 'month'])]
    for sid in public['scenario_ids']:
        for domain, identities, fields in domains:
            for identity in identities:
                for field in fields:
                    key = sid + ' ' + _field_sheet(domain, field), identity['id'], _label(field)
                    require(key not in expected, 'Ambiguous public account label')
                    expected[key] = domain, field
    slots, seen = [], set()
    for sid in public['scenario_ids']:
        for name in FORECAST_VIEWS:
            sheet = book[sid + ' ' + name]
            rows = sheet.iter_rows(values_only=True)
            title = next(rows)
            require(title[0] == sheet.title + ' — monthly business forecast'
                and all(v is None for v in title[1:]), 'The public forecast title changed or gained helper contents')
            require(not any(v is not None for v in next(rows)), 'Unexpected forecast header contents')
            header = next(rows)
            fifo = name in ('Interest Carry', 'Loss Carry')
            wanted = ('Entity', 'Origin month', 'Forecast month', 'Opening GBP', 'Expired GBP', 'Used GBP', 'Created GBP', 'Closing GBP') if fifo else (
                'Entity / facility / asset', 'Statement / schedule', 'Account', 'Unit')
            require(tuple(header[:len(wanted)]) == wanted, 'Public forecast headers changed')
            if not fifo:
                require([_day(v, month=True) for v in header[4:4 + len(public['months'])]] == public['months']
                    and all(v is None for v in header[4 + len(public['months']):]), 'Public forecast dates changed')
            else:
                require(all(v is None for v in header[8:]), 'Unexpected FIFO forecast columns')
            for rownum, row in enumerate(rows, 4):
                if not any(v is not None for v in row): continue
                if not fifo:
                    require(len(row) >= 4, 'Incomplete public forecast descriptors')
                    key = sheet.title, row[0], row[2]
                    require(key in expected and key not in seen, 'Unknown, duplicate or internal-only forecast account')
                    seen.add(key); domain, field = expected[key]
                    scale, unit = _field_contract(domain, field)
                    require(row[1] == _category(domain, field) and row[3] == unit, 'Public account category or unit changed')
                    for t in range(len(public['months'])):
                        value = row[4 + t] if 4 + t < len(row) else None
                        require(not require_masked or value is None, 'A public forecast contains a prefilled answer')
                        slots.append({'sheet': sheet.title, 'row': rownum, 'column': 5 + t, 'scenario': sid,
                            'domain': domain, 'identity': row[0], 'month_index': t, 'field': field, 'scale': scale})
                    require(all(v is None for v in row[4 + len(public['months']):]), 'Unexpected forecast values outside the public calendar')
                else:
                    eid, origin, month = row[:3]
                    origin, month = _day(origin, month=True), _day(month, month=True)
                    require(eid in {e['id'] for e in public['entities']} and month in public['months'], 'Unknown FIFO public identity or month')
                    entity = next(e for e in public['entities'] if e['id'] == eid)
                    attribute = 'opening_interest_carry' if name == 'Interest Carry' else 'opening_tax_losses'
                    require(origin in _fifo_origins(public, entity, attribute, public['months'].index(month)),
                        'FIFO origin is not in the supplied public dated window')
                    key = sheet.title, eid, origin, month
                    require(key not in seen, 'Duplicate FIFO public identity')
                    seen.add(key)
                    for index, field in enumerate(('opening', 'expired', 'used', 'created', 'closing'), 4):
                        require(not require_masked or len(row) < index or row[index - 1] is None, 'A public FIFO forecast contains a prefilled answer')
                        slots.append({'sheet': sheet.title, 'row': rownum, 'column': index, 'scenario': sid,
                            'domain': 'interest_vintages' if name == 'Interest Carry' else 'loss_vintages',
                            'identity': eid, 'month_index': public['months'].index(month), 'origin': origin, 'field': field, 'scale': 100})
                    require(all(v is None for v in row[8:]), 'Unexpected FIFO forecast values')
    require(set(expected) <= seen, 'The complete public business account set is missing')
    for sid in public['scenario_ids']:
        for name, attribute in [('Interest Carry', 'opening_interest_carry'), ('Loss Carry', 'opening_tax_losses')]:
            for entity in public['entities']:
                for t, month in enumerate(public['months']):
                    for origin in _fifo_origins(public, entity, attribute, t):
                        require((sid + ' ' + name, entity['id'], origin, month) in seen, 'The complete public FIFO calendar is missing')
    return slots


def _posted(forward, slot):
    scenario = forward['scenarios'][slot['scenario']]
    domain, identity, t, field = (slot[k] for k in ('domain', 'identity', 'month_index', 'field'))
    if domain == 'group': return scenario['group_monthly'][t][field]
    row = scenario[domain][identity]['monthly'][t]
    if domain in ('interest_vintages', 'loss_vintages'):
        return next((v[field] for v in row['entries'] if v['origin_month'] == slot['origin']), 0)
    return row[field]


def write_public_results(book, public, forward):
    """Fill every publicly labelled slot; keep all supplied literals unchanged."""
    require(forward.get('specification_sha256') == spec.canonical_sha256(public)
        and forward.get('checks', {}).get('all_journals_and_financial_bridges_verified') is True,
        'The shared Decimal result must bind the reconstructed public primitives')
    slots = public_forecast_slots(book, public)
    blanks = 0
    for slot in slots:
        value = _posted(forward, slot)
        if value is None:
            require(slot['field'] in ('test_pass', 'dscr_ratio_millionths'), 'Unexpected non-applicable business result')
            rendered = None; blanks += 1
        else:
            require(type(value) in (int, bool), 'A complete integer financial posting is required')
            number = Decimal(int(value)) / slot['scale']
            rendered = int(number) if number == number.to_integral_value() else float(number)
        book[slot['sheet']].cell(slot['row'], slot['column'], rendered)
    return {'declared_business_slots': len(slots), 'numeric_results_written': len(slots) - blanks,
        'intentional_policy_blank_results': blanks, 'written_by_schedule': dict(Counter(s['domain'] for s in slots))}


def _values(book):
    return {(s.title, c.coordinate): (c.data_type, c.value, c.number_format)
        for s in book for row in s.iter_rows() for c in row if c.value is not None}


def recover_public(source, destination, report_path=None, *, instruction_path=None):
    """Public-only host API; this is not an isolated replay or LO receipt."""
    source_ref = _reference(source)
    instruction_ref = _reference(instruction_path) if instruction_path is not None else None
    destination = Path(destination).absolute()
    require(destination == destination.resolve() and not destination.exists()
        and destination != Path(source).absolute(), 'Use a fresh recovered output path')
    if report_path is not None:
        require(not Path(report_path).exists() and Path(report_path).absolute() != destination, 'Use a fresh separate report path')
    book = openpyxl.load_workbook(source, keep_links=True, data_only=False)
    try:
        public = _parse_book(book)
        before = _values(book)
        slots = public_forecast_slots(book, public)
        forward = ledger.simulate(public)
        written = write_public_results(book, public, forward)
        targets = {(s['sheet'], openpyxl.utils.get_column_letter(s['column']) + str(s['row'])) for s in slots}
        require({k: v for k, v in _values(book).items() if k not in targets} == before,
            'A provided business input, label or unrelated blank changed')
        book.save(destination)
    finally:
        book.close()
    calculated = openpyxl.load_workbook(destination, read_only=True, data_only=False, keep_links=True)
    try:
        public_forecast_slots(calculated, public, require_masked=False)
        saved_values = _values(calculated)
        require({k: v for k, v in saved_values.items() if k not in targets} == before,
            'Saved output changed a provided business cell')
        for slot in slots:
            coordinate = openpyxl.utils.get_column_letter(slot['column']) + str(slot['row'])
            observed = saved_values.get((slot['sheet'], coordinate), (None, None, None))[1]
            expected = _posted(forward, slot)
            require(observed is None if expected is None else _integer(observed, slot['scale']) == int(expected),
                'A saved business result lost its posted precision or value')
    finally:
        calculated.close()
    require(_reference(source) == source_ref, 'The public input changed during recovery')
    if instruction_ref is not None:
        require(_reference(instruction_path) == instruction_ref, 'The public instruction changed during recovery')
    report = {'kind': 'public_table_heterogeneous_business_recovery', 'version': 1, 'backend': BACKEND,
        'input': source_ref, 'instruction': instruction_ref, 'output': _reference(destination),
        'reconstructed_public_specification_sha256': spec.canonical_sha256(public), **written,
        'all_public_primitives_reconstructed': True, 'all_labelled_forecasts_written': True,
        'shared_Decimal_source_audit_implementation': True, 'independent_from_native_Excel_formulas': True,
        'third_independent_financial_implementation': False, 'public_policy_sufficiency_independently_certified': False,
        'private_goal_specification_bindings_or_parent_plan_parameters_supported': False,
        'physical_public_only_mount_isolation_verified': False,
        'actual_LO_calls': 0, 'actual_isolated_replay_executed': False,
        'quality_or_difficulty_certified': False, 'all_scenarios_feasible': forward['feasible']}
    if report_path is not None:
        with Path(report_path).open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2); stream.write('\n')
    return report

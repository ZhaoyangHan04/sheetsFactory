"""Public vocabulary and deterministic raw policies; no financial forward."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
import re

from ..associate_bridge_v1 import spec as bridge_spec
from ..operating_reports_200 import schema as base_schema

KIND = 'tax_vintage_bridge_business_spec_v2'
RESULT_KIND = 'tax_vintage_bridge_values_v2'
CASE_IDS = tuple(f'T{i:02d}' for i in range(1, 9))
QUARTERS = base_schema.QUARTERS
YEARS = base_schema.YEARS
POOLS = ('ordinary', 'investment')
LOT_IDS = tuple(f'O{i:02d}' for i in range(1, 5)) + tuple(f'C{i:02d}' for i in range(12))
NEW_FLOWS = ('tax_ordinary_before_losses', 'tax_investment_before_losses',
             'tax_ordinary_after_losses', 'tax_investment_after_losses',
             'loss_ordinary_expired', 'loss_ordinary_used', 'loss_ordinary_created',
             'loss_investment_expired', 'loss_investment_used', 'loss_investment_created',
             'cash_tax_paid')
NEW_STOCKS = ('loss_ordinary_close', 'loss_investment_close', 'tax_payable_close')
LOT_FIELDS = tuple(f'tax_lot_{lot}_{pool}_{metric}' for lot in LOT_IDS
                   for pool in POOLS for metric in ('used', 'close'))
MONEY_SCALES = bridge_spec.MONEY_SCALES
PUBLIC_POLICY = (
    'The investment accounting and all supplied operating and sales policies remain in force. This tax-vintage policy replaces the earlier tax netting, loss and payment rules from the first reported quarter.',
    'Ordinary taxable income is operating profit after interest and before investment income. Investment taxable income is zero for the exempt class, recognized investment income for the recognized class, or only cash receipts labelled dividend for the cash-dividends class. The two pools do not offset each other, including in the current quarter.',
    'Opening loss vintages state their origin and last eligible quarter. At each quarter opening, expire balances whose last eligible index is smaller than the current quarter index. An origin remains eligible in its last eligible quarter. Apply eligible older losses separately in each pool, oldest origin first and then lot identifier, subject to that pool positive income times its current utilization cap.',
    'After old losses are used, each negative pool income creates a loss in the current quarter slot. New losses first become available next quarter. Their last eligible index is the birth-quarter index plus the carry quarters in force at birth. Later term changes do not change an existing loss expiry.',
    'A term applies from its effective quarter index. Tax expense is the sum of the two nonnegative income pools after loss use times the original parent tax rate. There are no deferred taxes, refunds, carryback or transfers between entities.',
    'Each tax assessment is paid once at its assessment index plus the cash-tax lag in force when assessed. Later lag changes do not reschedule earlier assessments. Opening tax payable is zero. Assessments due after the final report remain payable; the forecast boundary does not accelerate payment.',
    'Net cash before owner distributions equals net income less recognized investment income plus all investment cash receipts plus tax expense less cash tax paid. The balance sheet includes unpaid tax as a liability. Investment and retained-earnings movements and the original FY2027 owner-distribution conditions remain in force.',
    'Indices 0 through 11 denote 2025Q1 through 2027Q4. All loss amounts use the entity report currency scale. Calculate without intermediate rounding and compare displayed outputs at two decimals. Annual flows sum quarters; annual closing balances use Q4. Division and portfolio reports sum each member in GBP.',
)
POLICY = '\n\n'.join(PUBLIC_POLICY)


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _number(value):
    if type(value) is not str or re.fullmatch(base_schema.DECIMAL_PATTERN, value) is None:
        raise ValueError('Use finite decimal strings for raw losses')
    result = Fraction(value)
    if result < 0:
        raise ValueError('Opening loss balances cannot be negative')
    return result


def _text(value):
    with localcontext() as ctx:
        ctx.prec = 250
        number = Decimal(value.numerator) / Decimal(value.denominator)
    if Fraction(number) != value:
        raise ValueError('A raw loss must be an exact finite decimal')
    return format(number, 'f')


def bridge_case(case_id):
    if case_id not in CASE_IDS:
        raise ValueError('Choose one fixed T01 through T08 case')
    return f'B{5 + CASE_IDS.index(case_id) % 4:02d}'


def _policies(bridge, case_id):
    n = CASE_IDS.index(case_id)
    result = {}
    for i, entity in enumerate(bridge['base']['entities']):
        # All sizes depend on supplied raw sales, not an oracle outcome.
        sales = Fraction(entity['actual_sales'][QUARTERS[0]])
        lots = []
        for j in range(4):
            lots.append({'lot_id': f'O{j+1:02d}', 'origin_index': -8+2*j,
                         'last_eligible_index': (0, 2, 5, 8)[j]+(i+n) % 2,
                         'ordinary': _text(sales*Fraction(4+j+(i+n) % 3, 10)),
                         'investment': _text(sales*Fraction(4*(j+1)+(i+n) % 3, 1000))})
        lag = 1+(i+n) % 2
        first = {'effective_index': 0,
                 'ordinary_cap_bp': (4000, 6000, 8000)[(i+n) % 3],
                 'investment_cap_bp': (3000, 5000, 7000)[(2*i+n) % 3],
                 'carry_quarters': (4, 6, 8)[(i+n) % 3], 'cash_tax_lag': lag}
        second = {'effective_index': 6+2*((i+n) % 2),
                  'ordinary_cap_bp': (5000, 7000, 9000)[(i+2*n) % 3],
                  'investment_cap_bp': (4000, 6000, 8000)[(i+n) % 3],
                  'carry_quarters': (8, 4, 6)[(i+n) % 3], 'cash_tax_lag': 3-lag}
        result[entity['id']] = {'opening_lots': lots, 'terms': [first, second]}
    return result


def build(bridge, case_id):
    bridge_spec.validate(bridge)
    if bridge['case_id'] != bridge_case(case_id):
        raise ValueError('This tax case requires its declared unchanged bridge case')
    public = {'kind': KIND, 'case_id': case_id, 'bridge': deepcopy(bridge),
              'tax_policies': _policies(bridge, case_id)}
    return validate(public)


def validate(public):
    if (type(public) is not dict or set(public) != {'kind', 'case_id', 'bridge', 'tax_policies'}
            or public['kind'] != KIND or public['case_id'] not in CASE_IDS):
        raise ValueError('Unknown tax-vintage bridge specification')
    bridge = bridge_spec.validate(public['bridge'])
    if bridge['case_id'] != bridge_case(public['case_id']):
        raise ValueError('The original bridge case mapping changed')
    policies = public['tax_policies']
    if type(policies) is not dict or set(policies) != {e['id'] for e in bridge['base']['entities']}:
        raise ValueError('Every entity requires a complete tax-vintage policy')
    for policy in policies.values():
        if type(policy) is not dict or set(policy) != {'opening_lots', 'terms'}:
            raise ValueError('Unknown tax-vintage policy fields')
        if type(policy['opening_lots']) is not list or len(policy['opening_lots']) != 4:
            raise ValueError('Supply exactly four opening vintages')
        for j, lot in enumerate(policy['opening_lots']):
            if (type(lot) is not dict or set(lot) != {'lot_id', 'origin_index', 'last_eligible_index', *POOLS}
                    or lot['lot_id'] != LOT_IDS[j] or type(lot['origin_index']) is not int
                    or lot['origin_index'] >= 0 or type(lot['last_eligible_index']) is not int):
                raise ValueError('Invalid opening vintage identity or index')
            for pool in POOLS:
                _number(lot[pool])
        if type(policy['terms']) is not list or len(policy['terms']) != 2:
            raise ValueError('Supply both fixed effective tax terms')
        for j, term in enumerate(policy['terms']):
            if (type(term) is not dict or set(term) != {'effective_index', 'ordinary_cap_bp', 'investment_cap_bp', 'carry_quarters', 'cash_tax_lag'}
                    or any(type(v) is not int for v in term.values())
                    or term['effective_index'] not in ((0,) if j == 0 else (6, 8))
                    or not all(0 <= term[p+'_cap_bp'] <= 10000 for p in POOLS)
                    or term['carry_quarters'] not in (4, 6, 8) or term['cash_tax_lag'] not in (1, 2)):
                raise ValueError('Invalid effective tax terms')
    if policies != _policies(bridge, public['case_id']):
        raise ValueError('The predeclared raw vintage or term assignments changed')
    return public


def points(public):
    """Return the complete output inventory without evaluating any business math."""
    public = validate(public)
    base = public['bridge']['base']
    yield from base_schema.points(base)
    identities = [e['id'] for e in base['entities']] + list(base_schema.groups(base))
    for identity in identities:
        for period in (*QUARTERS, *(f'FY{year}' for year in YEARS)):
            for field in NEW_FLOWS + NEW_STOCKS:
                yield f'{identity}/{period}/{field}', 'number'
    for entity in base['entities']:
        for period in QUARTERS:
            for field in LOT_FIELDS:
                yield f'{entity["id"]}/{period}/{field}', 'number'


validate_spec = validate
validate_public = validate

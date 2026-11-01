"""Fixed public bridge vocabulary and raw-fact lineage; no financial solver."""
from __future__ import annotations
from copy import deepcopy
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
from ..operating_reports_200 import schema as base_schema

KIND = 'associate_bridge_business_spec_v1'
RESULT_KIND = 'associate_bridge_values_v1'
CASE_IDS = tuple(f'B{i:02d}' for i in range(1, 9))
MONEY_SCALES = {'GBP': 1, 'GBP_thousands': 1000, 'GBP_millions': 1000000}
DIRECTIONS = ('income_positive', 'charge_credit')
METHODS = ('equity', 'cost')
TAX_CLASSES = ('exempt', 'recognized', 'cash_dividends')
QUARTERS = base_schema.QUARTERS
BASE_SCHEMA_SHA = '91e4176ceaa43775cc100febd6f38347699ad03b5b84bd7402ac0878fdf1290e'
BASE_SPEC_SHA = '4eaf468d8d7c0764f1cb70cbba7aa60a05c512bb00d0e9cad6137503f080ee40'
PUBLIC_POLICY = (
    'This investment bridge replaces the original associate-recognition, investment and tax treatment. Other supplied operating facts and sales policies remain in force.',
    'Each investment feed states its currency scale and annual sign convention. An income-positive feed records profits positive. A charge-credit feed records charges positive and credits negative. Convert the feed to the report currency scale before recognizing its economic profit or loss.',
    'Under the equity method, recognize the decoded share of profit or loss in income and add it to investment carrying value. All cash receipts reduce investment carrying value. Under the cost method, recognize cash receipts labelled dividend in income. Capital returns do not enter income and reduce investment carrying value. Other cost-method cash dividends do not change carrying value.',
    'The declared planning tax class applies to operating profit before investment recognition: exempt adds nothing; recognized adds the recognized investment income or loss; cash_dividends adds only cash receipts labelled dividend. Apply the stated parent tax rate to positive taxable profit. There is no refund or loss carryforward. Tax is paid in the same quarter.',
    'Cash from operations equals net income less recognized investment income plus all investment cash receipts. Roll cash, investment carrying value and retained earnings forward. Keep fixed debt and contributed capital unchanged. Cash receipts may distribute earlier retained investment earnings even when the current investee result is a loss.',
    'The original sales conditions still control the FY2027 Q4 owner distribution. If they pass, distribute 20% of positive full-year net income after the bridge. There is no owner distribution in other quarters. Owner distributions reduce cash and retained earnings.',
    'The forecast presented investment-income line is income-positive under both statement layouts. All FY2025 investment feeds and receipts are zero. Keep full calculation precision and the original two-decimal comparison rule. Do not insert a rounding allowance.',
)
POLICY = '\n\n'.join(PUBLIC_POLICY)


def canonical_sha256(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def _decimal(value):
    if type(value) is not str or re.fullmatch(base_schema.DECIMAL_PATTERN,value) is None:
        raise ValueError('Use finite decimal strings')
    return Fraction(value)


def _text(value):
    with localcontext() as ctx:
        ctx.prec = 200
        result = Decimal(value.numerator) / Decimal(value.denominator)
    if Fraction(result) != value:
        raise ValueError('A generated raw amount is not an exact finite decimal')
    return format(result, 'f')


def _policies(base, case_id):
    n = CASE_IDS.index(case_id)
    result = {}
    for i, entity in enumerate(base['entities']):
        report_scale = MONEY_SCALES[entity['money_unit']]
        method = 'equity' if n == 0 or (i+n) % 2 == 0 else 'cost'
        tax_class = 'exempt' if n < 2 else TAX_CLASSES[(i+n) % 3]
        feed_scale = report_scale if n < 3 else (1,1000,1000000)[((1,1000,1000000).index(report_scale)+1+(i+n)%2)%3]
        direction = {'2025':'income_positive','2026':'charge_credit','2027':'income_positive'}
        if n >= 3:
            direction['2026'] = DIRECTIONS[(i+n)%2]
            direction['2027'] = DIRECTIONS[1-(i+n)%2]
        postings, receipts, kinds = {}, {}, {}
        for q, period in enumerate(QUARTERS):
            sign = -1 if direction[period[:4]] == 'charge_credit' else 1
            postings[period] = _text(_decimal(entity['associate_results'][period])*report_scale/feed_scale*sign)
            # This cap uses supplied opening facts only, never an oracle outcome.
            pounds = min(Fraction(10000+5000*((7*(i+1)+3*n+q)%11)),
                         _decimal(entity['opening']['investment'])*report_scale/20)
            receipts[period] = '0' if q < 4 else _text(pounds/report_scale)
            kinds[period] = 'capital_return' if n >= 4 and q >= 4 and (i+q+n)%3 == 0 else 'dividend'
        result[entity['id']] = {'method':method,'tax_class':tax_class,'feed_scale':feed_scale,
            'direction_by_year':direction,'share_postings':postings,'cash_receipts':receipts,'receipt_kind':kinds}
    return result


def build(base, case_id):
    if case_id not in CASE_IDS:
        raise ValueError('Choose one fixed B01 through B08 case')
    base_schema.validate_spec(base)
    public = {'kind':KIND,'case_id':case_id,'base':deepcopy(base),'policies':_policies(base,case_id)}
    return validate_spec(public)


def validate_spec(public):
    if type(public) is not dict or set(public) != {'kind','case_id','base','policies'} or public['kind'] != KIND or public['case_id'] not in CASE_IDS:
        raise ValueError('Unknown bridge specification')
    base = base_schema.validate_spec(public['base'])
    if hashlib.sha256(Path(base_schema.__file__).read_bytes()).hexdigest() != BASE_SCHEMA_SHA:
        raise ValueError('The retained base schema changed')
    if base['dimension_mode'] == 'production' and base_schema.canonical_sha256(base) != BASE_SPEC_SHA:
        raise ValueError('Production bridge cases require the unchanged original base')
    if type(public['policies']) is not dict or set(public['policies']) != {e['id'] for e in base['entities']}:
        raise ValueError('Every original entity requires one policy')
    for policy in public['policies'].values():
        if (type(policy) is not dict or policy.get('method') not in METHODS
            or policy.get('tax_class') not in TAX_CLASSES or type(policy.get('feed_scale')) is not int
            or policy['feed_scale'] not in (1,1000,1000000)):
            raise ValueError('Invalid investment method, tax class or feed scale')
    if public['policies'] != _policies(base,public['case_id']):
        raise ValueError('The fixed case assignments or original decoded financial facts changed')
    for entity in base['entities']:
        policy = public['policies'][entity['id']]
        if set(policy) != {'method','tax_class','feed_scale','direction_by_year','share_postings','cash_receipts','receipt_kind'}:
            raise ValueError('Unknown policy fields')
        for period in QUARTERS:
            raw = _decimal(policy['share_postings'][period]); cash = _decimal(policy['cash_receipts'][period])
            sign = -1 if policy['direction_by_year'][period[:4]] == 'charge_credit' else 1
            if raw*policy['feed_scale']/MONEY_SCALES[entity['money_unit']]*sign != _decimal(entity['associate_results'][period]):
                raise ValueError('The feed no longer represents the original public economic fact')
            if cash < 0 or (period.startswith('2025') and (raw or cash)):
                raise ValueError('Historical investment facts must remain zero')
    return public


validate_public = validate_spec
validate = validate_spec

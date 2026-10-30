"""Independent formula close for fixed-plan legal entities; no ledger import.

Identical definitions share a physical calculation. Large FX numerators use a
floor quotient and a nonnegative remainder, never an inexact large double.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from math import gcd
import re

from openpyxl.utils import get_column_letter

from .spec import PHASES, RULES, SCALE, load_spec

BASE = 10**6
REF = re.compile(r"^'(?:[^']|'')+'!\$[A-Z]+\$[1-9][0-9]*$")


def _ref(sheet, cell):
    match = re.fullmatch(r'([A-Z]+)([0-9]+)', cell)
    return "'" + sheet.replace("'", "''") + "'!$" + match[1] + '$' + match[2]


def _parts(a, b):
    """Bounded base10^6 decomposition of a two-factor exact product."""
    aa, bb = 'ABS(' + a + ')', 'ABS(' + b + ')'
    low = '(MOD(' + aa + ',' + str(BASE) + ')*MOD(' + bb + ',' + str(BASE) + '))'
    middle = '(INT(' + aa + '/' + str(BASE) + ')*MOD(' + bb + ',' + str(BASE) + ')'
    middle += '+MOD(' + aa + ',' + str(BASE) + ')*INT(' + bb + '/' + str(BASE) + ')'
    middle += '+INT(' + low + '/' + str(BASE) + '))'
    quotient = '(INT(' + aa + '/' + str(BASE) + ')*INT(' + bb + '/' + str(BASE) + ')'
    quotient += '+INT(' + middle + '/' + str(BASE) + '))'
    remainder = '(MOD(' + middle + ',' + str(BASE) + ')*' + str(BASE)
    remainder += '+MOD(' + low + ',' + str(BASE) + '))'
    negative = '((' + a + '<0)<>(' + b + '<0))'
    return quotient, remainder, negative


def expression_formula(value):
    if type(value) is bool:
        return '1' if value else '0'
    if type(value) is int:
        return str(value)
    if isinstance(value, str):
        return value if REF.fullmatch(value) else '"' + value.replace('"', '""') + '"'
    if not isinstance(value, (tuple, list)) or not value:
        raise ValueError('An explicit static entity-group expression is required')
    op, *values = value
    args = [expression_formula(item) for item in values]
    if op == 'sum': return '(' + '+'.join(args) + ')' if args else '0'
    if op in ('sub', 'mul', 'lt', 'le', 'eq', 'ge') and len(args) == 2:
        return '(' + args[0] + {'sub': '-', 'mul': '*', 'lt': '<', 'le': '<=', 'eq': '=', 'ge': '>='}[op] + args[1] + ')'
    if op in ('if', 'min', 'max', 'and', 'or', 'abs', 'mod'):
        return op.upper() + '(' + ','.join(args) + ')'
    if op in ('floordiv', 'ceildiv', 'rounddiv') and len(args) == 2:
        return {'floordiv': 'INT(' + args[0] + '/' + args[1] + ')',
            'ceildiv': '(-INT(-' + args[0] + '/' + args[1] + '))',
            'rounddiv': 'ROUND(' + args[0] + '/' + args[1] + ',0)'}[op]
    if op in ('round_product', 'product_whole', 'product_remainder') and len(args) == 2:
        whole, remainder, negative = _parts(*args)
        if op == 'round_product':
            return '(IF(' + negative + ',-1,1)*(' + whole + '+IF(' + remainder + '>=' + str(SCALE // 2) + ',1,0)))'
        if op == 'product_whole':
            return 'IF(' + negative + ',-' + whole + '-IF(' + remainder + '>0,1,0),' + whole + ')'
        return 'IF(' + negative + ',IF(' + remainder + '=0,0,' + str(SCALE) + '-' + remainder + '),' + remainder + ')'
    raise ValueError('Unsupported static entity-group expression: ' + str(op))


def _sum(*args): return ('sum', *args)
def _sub(a, b): return ('sub', a, b)
def _mul(a, b): return ('mul', a, b)
def _max(a, b=0): return ('max', a, b)
def _min(*args): return ('min', *args)
def _if(c, a, b): return ('if', c, a, b)
def _round(a, b): return ('round_product', a, b)


class _CounterCell:
    def __init__(self, row, column, value):
        self.coordinate = get_column_letter(column) + str(row); self.value = value


class _CounterSheet:
    def __init__(self, title):
        self.title, self.max_row, self.cells = title, 0, 0

    def append(self, values):
        self.max_row += 1; self.cells += sum(value is not None for value in values)

    def cell(self, row, column, value=None):
        self.max_row = max(self.max_row, row)
        if value is not None: self.cells += 1
        return _CounterCell(row, column, value)


class _CounterBook:
    def __init__(self): self.sheets = []

    @property
    def sheetnames(self): return [sheet.title for sheet in self.sheets]

    def create_sheet(self, title):
        sheet = _CounterSheet(title); self.sheets.append(sheet); return sheet


class _CountLog:
    def __init__(self):
        self.count = self.max_depth = self.max_formula_length = self.formula_characters = 0
        self.digest = hashlib.sha256(); self.encodings = {}; self.refs = set()

    def __len__(self): return self.count

    def append(self, value):
        self.count += 1
        self.digest.update(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode() + b'\n')
        def depth(item): return 1 + max((depth(child) for child in item[1:]), default=0) if isinstance(item, (tuple, list)) else 1
        if 'expression' in value: self.max_depth = max(self.max_depth, depth(value['expression']))
        if 'formula' in value:
            length = len(value['formula']); self.max_formula_length = max(self.max_formula_length, length); self.formula_characters += length
        if 'encoding' in value:
            kind = value['encoding']; self.encodings[kind] = self.encodings.get(kind, 0) + 1
        for key in ('reference', 'whole', 'remainder'):
            if key in value: self.refs.add(value[key])


class _Emitter:
    def __init__(self, book, spec, maximum, *, count_only=False):
        self.book, self.spec, self.maximum = book, spec, maximum
        self.count_only = count_only
        self.inputs = {}
        self.literals, self.formulas, self.bindings = ((_CountLog(), _CountLog(), _CountLog()) if count_only else ([], [], []))
        self.memo = {}
        self.sheet = None
        rules = book.create_sheet('Group Rules')
        rules.append(['Fixed-plan legal entities: monthly close; no optimisation'])
        for phase in PHASES: rules.append(['Phase', phase])
        for rule in RULES: rules.append(['Rule', rule])
        contract = book.create_sheet('Group Contract')
        contract.append(['Complete public primitive JSON'])
        text = json.dumps(spec, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
        for start in range(0, len(text), 30000): contract.append(['JSON part ' + str(start // 30000 + 1), text[start:start + 30000]])
        sheet = book.create_sheet('Group Inputs'); sheet.append(['Public primitive path', 'Literal value (Boolean flags: 0=false, 1=true)'])
        def flatten(value, path=()):
            if isinstance(value, dict):
                for key, child in value.items(): flatten(child, (*path, key))
            elif isinstance(value, list):
                for index, child in enumerate(value): flatten(child, (*path, index))
            else:
                encoding = 'public_boolean_as_binary_integer' if type(value) is bool else 'identity'
                stored = int(value) if type(value) is bool else value
                sheet.append(['/'.join(map(str, path)), stored]); address = 'B' + str(sheet.max_row)
                self.inputs[path] = _ref(sheet.title, address)
                self.literals.append({'sheet': sheet.title, 'cell': address, 'path': list(path),
                    'value': value, 'stored_value': stored, 'encoding': encoding})
        flatten(spec)

    def inp(self, *path): return self.inputs[tuple(path)]

    def put(self, expression, label, path=None, *, monetary=True):
        if isinstance(expression, str) and REF.fullmatch(expression):
            result = expression
        else:
            identity = (self.sheet.title, hashlib.sha256(repr(expression).encode()).digest())
            result = self.memo.get(identity)
            if result is None:
                if len(self.formulas) >= self.maximum: raise ValueError('The declared physical formula budget was exceeded; nothing is truncated')
                row = self.sheet.max_row + 1
                if row > 1048576: raise ValueError('The close exceeded an Excel worksheet row limit')
                self.sheet.cell(row, 1, label); formula = '=' + expression_formula(expression)
                if len(formula) > 8192: raise ValueError('A static formula exceeds the supported Excel formula length')
                self.sheet.cell(row, 2, formula)
                result = _ref(self.sheet.title, 'B' + str(row))
                self.formulas.append({'sheet': self.sheet.title, 'cell': 'B' + str(row), 'formula': formula,
                    'expression': deepcopy(expression), 'label': label, 'monetary': monetary})
                self.memo[identity] = result
        if path is not None: self.bindings.append({'path': list(path), 'reference': result, 'encoding': 'scalar', 'monetary': monetary})
        return result

    def triple(self, a, b, c, label):
        def digits(value):
            return [('mod', ('floordiv', ('abs', value), BASE**index), BASE) for index in range(3)]
        def multiply(left, right, tag):
            limbs, carry = [], 0
            for index in range(len(left) + len(right)):
                terms = [_mul(item, right[index - pos]) for pos, item in enumerate(left) if 0 <= index - pos < len(right)]
                total = self.put(_sum(carry, *terms), label + tag + str(index), monetary=False)
                limbs.append(('mod', total, BASE)); carry = ('floordiv', total, BASE)
            return limbs
        product = multiply(multiply(digits(b), digits(c), '.rate'), digits(a), '.money')
        quotient = _sum(*(_mul(value, BASE**index) for index, value in enumerate(product[4:])))
        # Four base10^6 remainder limbs: a half tie is determined by the top limb.
        return _sum(quotient, _if(('ge', product[3], BASE // 2), 1, 0))

    def scale_divide(self, amount, fx, known_fx, bound, label, *, ceiling=False):
        """Exact contractual FX capacity conversion with a finite range proof.

        A reduction by the GCD of two provided FX primitives is arithmetic,
        not a cached financial answer. The compact path has numerator <2^49;
        otherwise base100 long division keeps every coefficient <10^15.
        """
        common = gcd(SCALE, known_fx); multiplier, divisor = SCALE // common, known_fx // common
        if bound * multiplier < 2**49:
            numerator = _mul(amount, multiplier)
            denominator = ('floordiv', fx, common)
            return ('ceildiv' if ceiling else 'floordiv', numerator, denominator)
        quotient = remainder = 0
        digits = [('mod', ('floordiv', amount, 100**index), 100) for index in range(6, -1, -1)] + [0] * 6
        for index, digit in enumerate(digits):
            coefficient = self.put(_sum(_mul(remainder, 100), digit), label + '.coefficient' + str(index), monetary=False)
            quotient = self.put(_sum(_mul(quotient, 100), ('floordiv', coefficient, fx)), label + '.quotient' + str(index), monetary=False)
            remainder = self.put(('mod', coefficient, fx), label + '.remainder' + str(index), monetary=False)
        return _sum(quotient, _if(('ge', remainder, 1), 1, 0)) if ceiling else quotient

    def pair(self, expression, path, label):
        whole, remainder = expression
        whole = self.put(whole, label + '.whole', monetary=False)
        remainder = self.put(remainder, label + '.remainder', monetary=False)
        self.bindings.append({'path': list(path), 'encoding': 'exact_integer_pair', 'whole': whole,
            'remainder': remainder, 'scale': SCALE, 'monetary': True})
        return whole, remainder


def _pair_product(a, b): return ('product_whole', a, b), ('product_remainder', a, b)


def _pair_sum(pairs):
    wholes, remainders = zip(*pairs) if pairs else ((), ())
    total = _sum(*remainders)
    return _sum(*wholes, ('floordiv', total, SCALE)), ('mod', total, SCALE)


def _pair_sub(left, right):
    return _pair_sum([left, (_sub(0, right[0]), _sub(0, right[1]))])


def _pair_round(pair):
    whole, remainder = pair
    # A floor representation must move an exact negative half away from zero.
    increment = _if(('lt', whole, 0), _if(('le', remainder, SCALE // 2), 0, 1), _if(('ge', remainder, SCALE // 2), 1, 0))
    return _sum(whole, increment)


def _rounded_equity_sum(out, rows, exact_product, label):
    """Materialize each independently rounded legal-entity amount once."""
    references = [out.put(_pair_round(exact_product(row['equity_close'], row['fx_close_p12'])),
        label + '/' + identity + '/rounded_equity_GBP', monetary=False) for identity, row in rows.items()]
    return _sum(*references)


def _currency_grouped_exact(out, rows, currencies, amount, rate, exact_product, label):
    """Sum exact, unrounded FX numerators after grouping a common currency.

    A shared rate is an explicit public contract. This identity applies before
    rounding; individually translated postings must still be rounded separately.
    Materialize each amount sum so exact multiplication has short operands.
    """
    buckets = {}
    for identity, row in rows.items():
        buckets.setdefault(currencies[identity], []).append(row)
    products = []
    for currency, members in buckets.items():
        shared = rate(members[0])
        if any(rate(row) != shared for row in members[1:]):
            raise ValueError('Exact currency aggregation requires an identical public FX expression')
        subtotal = out.put(_sum(*(amount(row) for row in members)),
            label + '/' + currency + '/unrounded_functional_sum', monetary=False)
        products.append(exact_product(subtotal, shared))
    return _pair_sum(products)


def emit_entity_group_workbook(book, specification, *, max_formulas=1_000_000, allow_production=False, _count_only=False):
    """Emit formulas from primitive contracts only; never inspect a journal.

    Production emission is a separate explicit operation. This implementation
    makes no qualification, mechanism-activation or runtime-capacity claim.
    """
    public = load_spec(specification)
    if book.sheetnames: raise ValueError('An empty workbook is required')
    if public['dimension_mode'] == 'production' and not allow_production:
        raise ValueError('Production emission requires a separately authorised explicit opt-in')
    if _count_only and not isinstance(book, _CounterBook): raise ValueError('Count-only compilation cannot materialize an actual workbook')
    if type(max_formulas) is not int or not 1 <= max_formulas <= (10_000_000 if _count_only else 1_000_000): raise ValueError('Invalid physical formula budget')
    out = _Emitter(book, public, max_formulas, count_only=_count_only)
    months = public['months']; entity_ids = [e['id'] for e in public['entities']]
    entities = {e['id']: (i, e) for i, e in enumerate(public['entities'])}
    loans = {loan['id']: (i, loan) for i, loan in enumerate(public['intercompany_loans'])}
    for si, scenario in enumerate(public['scenarios']):
        sid = scenario['id']; out.sheet = book.create_sheet(sid + ' Close')
        out.sheet.append(['Public accounting definition / period / legal owner', 'Functional minor units; explicit GBP where labelled'])
        prefix = ('scenarios', sid)
        states, loan_balances, project_books = {}, {loan: 0 for loan in loans}, {p['id']: 0 for p in public['projects']}
        prior_groups = []
        for identity, (ei, e) in entities.items():
            opening = _sum(out.inp('entities', ei, 'opening_cash_minor'), out.inp('entities', ei, 'opening_restricted_minor'))
            fx = out.inp('opening_fx_gbp_p12', e['currency'])
            states[identity] = {'cash_close': out.inp('entities', ei, 'opening_cash_minor'),
                'restricted_close': out.inp('entities', ei, 'opening_restricted_minor'), 'bank_close': 0,
                'capital_close': opening, 'retained_close': 0, 'called_close': 0, 'certified_nav_close': 0,
                'trap_next': out.inp('entities', ei, 'opening_trap'), 'cure_count_next': out.inp('entities', ei, 'opening_cure_count'),
                'fx_close_p12': fx, 'capital_historical_gbp': _round(opening, fx), 'retained_historical_gbp': 0,
                'economic_FX_reserve_gbp': 0, 'posting_translation_rounding_reserve_gbp': 0,
                'interest_vintages': [], 'tax_vintages': []}
        def factor(field, month): return out.inp('scenarios', si, field, month)
        def asof(records, container, keys, month, field):
            result = 0
            # Complete-key equality is retained in the formula. Effective dates
            # determine precedence independently of the supplied table row order.
            matches = [(index, record) for index, record in enumerate(records)
                if all(record[key] == value for key, value in keys.items())]
            for index, record in sorted(matches, key=lambda item: item[1]['effective_month']):
                conditions = [('eq', out.inp(container, index, key), value) for key, value in keys.items()]
                conditions.append(('le', out.inp(container, index, 'effective_month'), month))
                result = _if(('and', *conditions), out.inp(container, index, field), result)
            return result
        for mi, month in enumerate(months):
            rows, terms, loan_rows, loan_terms = {}, {}, {}, {}
            def bind(identity, field, expression, *, monetary=True):
                path = (*prefix, 'entities', identity, 'monthly', mi, field)
                rows[identity][field] = out.put(expression, sid + '/' + identity + '/' + month + '/' + field, path, monetary=monetary)
                return rows[identity][field]
            for identity, (ei, e) in entities.items():
                prior = states[identity]; rows[identity] = {}
                aliases = {'cash_open': 'cash_close', 'restricted_open': 'restricted_close', 'bank_open': 'bank_close',
                    'capital_open': 'capital_close', 'retained_open': 'retained_close', 'called_open': 'called_close',
                    'prior_certified_nav': 'certified_nav_close', 'trap_open': 'trap_next', 'cure_count_open': 'cure_count_next', 'fx_open_p12': 'fx_close_p12'}
                for field, original in aliases.items(): bind(identity, field, prior[original], monetary=field not in ('trap_open', 'cure_count_open', 'fx_open_p12'))
                bind(identity, 'fx_close_p12', out.inp('scenarios', si, 'fx_gbp_p12', e['currency'], month), monetary=False)
                keys = {'entity_id': identity, 'facility_id': e['facility_id'], 'currency': e['currency']}
                terms[identity] = {field: out.put(asof(public['bank_terms'], 'bank_terms', keys, month, field),
                    identity + '/' + month + '/asof_bank_' + field, monetary=False) for field in
                    ('effective_month', 'maturity_month', 'local_limit_minor', 'monthly_rate_p12', 'advance_rate_p12')}
                bind(identity, 'bank_term_effective_month', terms[identity]['effective_month'], monetary=False)
                rate = bind(identity, 'bank_monthly_rate_p12', _round(terms[identity]['monthly_rate_p12'], factor('rate_factor_p12', month)), monetary=False)
                bind(identity, 'bank_interest', _round(rows[identity]['bank_open'], rate))
            project_totals = {identity: {} for identity in entities}
            for pi, project in enumerate(public['projects']):
                pid, identity = project['id'], project['entity_id']; prior = project_books[pid]
                selected = out.inp('fixed_plan', pid); commission = out.inp('projects', pi, 'commission_month')
                sale_date = out.inp('projects', pi, 'sale_month'); life = out.inp('projects', pi, 'depreciation_months')
                cost = out.inp('projects', pi, 'cost_minor')
                active = ('and', ('lt', commission, month), ('le', month, sale_date), ('eq', selected, 1))
                acquisition = _if(('and', ('eq', commission, month), ('eq', selected, 1)), cost, 0)
                basis = _sum(prior, acquisition); age = mi - months.index(project['commission_month'])
                depr = _if(('and', active, ('le', age, life)), _min(basis, _if(('eq', age, life), basis, ('rounddiv', cost, life))), 0)
                carrying_before_sale = _sub(basis, depr)
                sold = ('and', ('eq', sale_date, month), ('eq', selected, 1))
                values = {'opening_book_minor': prior, 'capex': acquisition,
                    'revenue': _if(active, _round(out.inp('projects', pi, 'revenue_minor', month), factor('revenue_factor_p12', month)), 0),
                    'opex': _if(active, _round(out.inp('projects', pi, 'opex_minor', month), factor('opex_factor_p12', month)), 0),
                    'depreciation': depr, 'sale': _if(sold, _round(out.inp('projects', pi, 'sale_minor'), factor('sale_factor_p12', month)), 0),
                    'sale_carrying': _if(sold, carrying_before_sale, 0), 'closing_book_minor': _if(sold, 0, carrying_before_sale)}
                for field, expression in values.items():
                    value = out.put(expression, sid + '/' + pid + '/' + month + '/' + field, (*prefix, 'projects', pid, mi, field))
                    values[field] = value
                    target = {'opening_book_minor': 'project_book_open', 'closing_book_minor': 'project_book_close', 'certified_nav_minor': 'certified_nav_close'}.get(field, field)
                    project_totals[identity].setdefault(target, []).append(value)
                for field, expression in {'sale_gain': _sub(values['sale'], values['sale_carrying']),
                    'certified_nav_minor': _round(values['closing_book_minor'], factor('nav_factor_p12', month))}.items():
                    value = out.put(expression, sid + '/' + pid + '/' + month + '/' + field, (*prefix, 'projects', pid, mi, field))
                    values[field] = value
                    project_totals[identity].setdefault('certified_nav_close' if field == 'certified_nav_minor' else field, []).append(value)
                project_books[pid] = values['closing_book_minor']
            for identity in entities:
                for field in ('revenue', 'opex', 'capex', 'depreciation', 'sale', 'sale_carrying', 'sale_gain', 'project_book_open', 'project_book_close', 'certified_nav_close'):
                    values = project_totals[identity].get(field, [])
                    bind(identity, field, values[0] if len(values) == 1 else _sum(*values))
            for lid, (li, loan) in loans.items():
                keys = {'loan_id': lid, **{key: loan[key] for key in ('lender_id', 'borrower_id', 'currency')}}
                term = {field: out.put(asof(public['intercompany_terms'], 'intercompany_terms', keys, month, field),
                    lid + '/' + month + '/asof_loan_' + field, monetary=False) for field in
                    ('effective_month', 'maturity_month', 'limit_minor', 'monthly_rate_p12')}
                loan_terms[lid] = term
                effective_rate = out.put(_round(term['monthly_rate_p12'], factor('rate_factor_p12', month)),
                    sid + '/' + lid + '/' + month + '/effective_rate_p12', monetary=False)
                interest = _round(loan_balances[lid], effective_rate)
                loan_rows[lid] = {'opening_principal': loan_balances[lid], 'interest': interest,
                    'term_effective_month': term['effective_month']}
                for field in list(loan_rows[lid]):
                    loan_rows[lid][field] = out.put(loan_rows[lid][field], sid + '/' + lid + '/' + month + '/' + field,
                        (*prefix, 'intercompany', lid, mi, field), monetary=field != 'term_effective_month')
            def loans_for(identity, field, side):
                return _sum(*(loan_rows[lid][field] for lid, (_, loan) in loans.items() if loan[side] == identity))
            cash, debt = {}, {}
            queue_totals = {}
            for identity, (ei, e) in entities.items():
                r, prior = rows[identity], states[identity]
                for field, loan_field, side in (('ic_interest_income', 'interest', 'lender_id'), ('ic_interest_expense', 'interest', 'borrower_id'),
                    ('ic_receivable_open', 'opening_principal', 'lender_id'), ('ic_payable_open', 'opening_principal', 'borrower_id')):
                    bind(identity, field, loans_for(identity, loan_field, side))
                bind(identity, 'ebitda', _sub(r['revenue'], r['opex']))
                capacity = bind(identity, 'interest_capacity', _round(_max(r['ebitda']), out.inp('entities', ei, 'interest_limit_p12')))
                def vintage_queue(kind, capacity, created):
                    carry = e[kind + '_carry_months']; old = prior[kind + '_vintages']
                    live = [(origin, value) for origin, value in old if mi - origin <= carry]
                    expired = [(origin, value) for origin, value in old if mi - origin > carry]
                    available = _sum(*(value for _, value in live)); used = _min(available, capacity)
                    result = []; remaining = capacity
                    for origin, amount in live:
                        taken = _min(amount, remaining)
                        closing = out.put(_sub(amount, taken), sid + '/' + identity + '/' + month + '/' + kind + '_vintage_' + str(origin), monetary=True)
                        result.append((origin, closing)); remaining = _max(_sub(remaining, amount))
                    if created is not None: result.append((mi, created))
                    return result, used, _sum(*(value for _, value in expired)), _sum(*(value for _, value in old))
                interest_live, old_used, interest_expired, interest_open = vintage_queue('interest', capacity, None)
                old_used = bind(identity, 'interest_old_used', old_used)
                expense = _sum(r['bank_interest'], r['ic_interest_expense'])
                current_allowed = bind(identity, 'interest_current_allowed', _min(expense, _max(_sub(capacity, old_used))))
                denied = bind(identity, 'interest_denied_created', _sub(expense, current_allowed))
                interest_live.append((mi, denied))
                bind(identity, 'interest_vintage_open', interest_open); bind(identity, 'interest_vintage_close', _sum(*(value for _, value in interest_live)))
                taxable = bind(identity, 'taxable_before_loss', _sub(_sum(r['ebitda'], r['sale_gain'], r['ic_interest_income']), _sum(r['depreciation'], old_used, current_allowed)))
                loss_created = bind(identity, 'tax_loss_created', _max(_sub(0, taxable)))
                tax_live, loss_used, tax_expired, loss_open = vintage_queue('tax', _max(taxable), loss_created)
                queue_totals[identity] = {'interest_expired': interest_expired, 'tax_expired': tax_expired}
                bind(identity, 'tax_loss_open', loss_open); bind(identity, 'tax_loss_close', _sum(*(value for _, value in tax_live)))
                bind(identity, 'tax_loss_used', loss_used)
                bind(identity, 'taxable_after_loss', _max(_sub(taxable, r['tax_loss_used'])))
                bind(identity, 'current_tax', _round(r['taxable_after_loss'], out.inp('entities', ei, 'tax_rate_p12')))
                bind(identity, 'net_income', _sub(_sum(r['ebitda'], r['sale_gain'], r['ic_interest_income']), _sum(r['depreciation'], expense, r['current_tax'])))
                # Sparse queue metadata is audited from complete bounded-vintage
                # schedules, without a zero-filled horizon square.
                out.bindings.append({'path': [*prefix, 'entities', identity, 'monthly', mi], 'encoding': 'queues',
                    'interest': [{'origin': origin, 'reference': value} for origin, value in interest_live],
                    'tax': [{'origin': origin, 'reference': value} for origin, value in tax_live],
                    'prior_interest': [{'origin': origin, 'reference': value} for origin, value in prior['interest_vintages']],
                    'prior_tax': [{'origin': origin, 'reference': value} for origin, value in prior['tax_vintages']]})
                prior['next_interest_vintages'], prior['next_tax_vintages'] = interest_live, tax_live
                cash[identity] = out.put(_sum(r['cash_open'], r['revenue'], r['sale'], r['ic_interest_income'],
                    _sub(0, _sum(r['opex'], r['capex'], r['bank_interest'], r['ic_interest_expense'], r['current_tax']))), identity + '/' + month + '/cash_post_operations')
                debt[identity] = r['bank_open']
            for lid, (_, loan) in loans.items():
                term, lr = loan_terms[lid], loan_rows[lid]
                repayment = _if(('ge', month, term['maturity_month']), lr['opening_principal'], _max(_sub(lr['opening_principal'], term['limit_minor'])))
                lr['mandatory_repayment'] = out.put(repayment, lid + '/' + month + '/mandatory_repayment', (*prefix, 'intercompany', lid, mi, 'mandatory_repayment'))
                loan_balances[lid] = _sub(lr['opening_principal'], lr['mandatory_repayment'])
                cash[loan['lender_id']] = _sum(cash[loan['lender_id']], lr['mandatory_repayment'])
                cash[loan['borrower_id']] = _sub(cash[loan['borrower_id']], lr['mandatory_repayment'])
            for identity, (ei, e) in entities.items():
                r, term = rows[identity], terms[identity]
                collateral = out.triple(r['prior_certified_nav'], term['advance_rate_p12'], _sub(SCALE, factor('haircut_p12', month)), identity + '/' + month + '/collateral')
                base = bind(identity, 'borrowing_base', _if(('ge', month, term['maturity_month']), 0, _min(term['local_limit_minor'], collateral)))
                margin = bind(identity, 'bank_local_margin', _max(_sub(debt[identity], base)))
                debt[identity], cash[identity] = _sub(debt[identity], margin), _sub(cash[identity], margin)
            def usage():
                return _sum(*(out.put(_sum(('product_whole', debt[identity], rows[identity]['fx_close_p12']),
                    _if(('ge', ('product_remainder', debt[identity], rows[identity]['fx_close_p12']), 1), 1, 0)),
                    identity + '/' + month + '/shared_usage_after_current_priority_state', monetary=False) for identity in entities))
            for identity in public['bank_priority']:
                excess = _max(_sub(usage(), out.inp('shared_bank_limit_gbp_pence')))
                currency = entities[identity][1]['currency']; known_fx = scenario['fx_gbp_p12'][currency][month]
                maximum_usage = sum((max(t['local_limit_minor'] for t in public['bank_terms'] if t['entity_id'] == owner)
                    * scenario['fx_gbp_p12'][e['currency']][month] + SCALE - 1) // SCALE for owner, (_, e) in entities.items())
                conversion = out.scale_divide(excess, rows[identity]['fx_close_p12'], known_fx, maximum_usage,
                    identity + '/' + month + '/shared_margin_FX', ceiling=True)
                repayment = bind(identity, 'bank_shared_margin', _min(debt[identity], conversion))
                debt[identity], cash[identity] = _sub(debt[identity], repayment), _sub(cash[identity], repayment)
            for identity, (ei, e) in entities.items():
                r = rows[identity]
                locked = bind(identity, 'reserve_locked', _if(r['trap_open'], _min(_max(cash[identity]), _max(_sub(out.inp('entities', ei, 'reserve_target_minor'), r['restricted_open']))), 0))
                released = bind(identity, 'reserve_released', _if(r['trap_open'], 0, r['restricted_open']))
                bind(identity, 'restricted_close', _sum(r['restricted_open'], locked, _sub(0, released)))
                cash[identity] = out.put(_sum(cash[identity], released, _sub(0, locked)), identity + '/' + month + '/cash_after_reserve')
            for lid in public['loan_priority']:
                li, loan = loans[lid]; term, lr = loan_terms[lid], loan_rows[lid]
                lender, borrower = loan['lender_id'], loan['borrower_id']
                amount = _if(('ge', month, term['maturity_month']), 0, _min(_max(_sub(term['limit_minor'], loan_balances[lid])),
                    _max(_sub(cash[lender], out.inp('entities', entities[lender][0], 'minimum_cash_minor'))),
                    _max(_sub(out.inp('entities', entities[borrower][0], 'minimum_cash_minor'), cash[borrower]))))
                lr['draw'] = out.put(amount, lid + '/' + month + '/draw', (*prefix, 'intercompany', lid, mi, 'draw'))
                loan_balances[lid] = out.put(_sum(loan_balances[lid], lr['draw']), lid + '/' + month + '/closing_principal', (*prefix, 'intercompany', lid, mi, 'closing_principal'))
                cash[lender] = out.put(_sub(cash[lender], lr['draw']), lender + '/' + month + '/cash_after_' + lid)
                cash[borrower] = out.put(_sum(cash[borrower], lr['draw']), borrower + '/' + month + '/cash_after_' + lid)
                out.put(_sub(loan_balances[lid], _sum(lr['opening_principal'], lr['draw'], _sub(0, lr['mandatory_repayment']))),
                    lid + '/' + month + '/principal_bridge_residual', (*prefix, 'intercompany', lid, mi, 'principal_bridge_residual'), monetary=False)
            for identity in public['bank_priority']:
                r, ei = rows[identity], entities[identity][0]
                headroom = _sub(out.inp('shared_bank_limit_gbp_pence'), usage())
                known_fx = scenario['fx_gbp_p12'][entities[identity][1]['currency']][month]
                available = out.scale_divide(headroom, r['fx_close_p12'], known_fx, public['shared_bank_limit_gbp_pence'], identity + '/' + month + '/draw_FX')
                desired = _min(_max(_sub(out.inp('entities', ei, 'minimum_cash_minor'), cash[identity])), _max(_sub(r['borrowing_base'], debt[identity])))
                draw = bind(identity, 'bank_draw', _min(desired, available))
                cash[identity] = _sum(cash[identity], draw); debt[identity] = out.put(_sum(debt[identity], draw), identity + '/' + month + '/bank_close')
            for identity, (ei, e) in entities.items():
                r, prior = rows[identity], states[identity]
                for field, loan_field, side in (('ic_principal_received', 'mandatory_repayment', 'lender_id'), ('ic_principal_paid', 'mandatory_repayment', 'borrower_id'),
                    ('ic_draw_lent', 'draw', 'lender_id'), ('ic_draw_received', 'draw', 'borrower_id')):
                    bind(identity, field, loans_for(identity, loan_field, side))
                required = _max(_sub(out.inp('entities', ei, 'minimum_cash_minor'), cash[identity]))
                call = bind(identity, 'capital_call', _min(required, _sub(out.inp('entities', ei, 'additional_commitment_minor'), r['called_open'])))
                bind(identity, 'called_close', _sum(r['called_open'], call)); bind(identity, 'funding_gap', _sub(required, call))
                cash[identity] = _sum(cash[identity], call)
                equity = bind(identity, 'equity_before_distribution', _sum(r['capital_open'], call, r['retained_open'], r['net_income']))
                dist = bind(identity, 'distribution', _min(_max(_sub(cash[identity], out.inp('entities', ei, 'minimum_cash_minor'))), _max(equity)))
                roc = bind(identity, 'return_of_capital', _min(dist, _sum(r['capital_open'], call)))
                profit = bind(identity, 'profit_distribution', _sub(dist, roc))
                bind(identity, 'cash_close', _sub(cash[identity], dist)); bind(identity, 'bank_close', debt[identity])
                bind(identity, 'capital_close', _sub(_sum(r['capital_open'], call), roc))
                bind(identity, 'retained_close', _sub(_sum(r['retained_open'], r['net_income']), profit))
                service = bind(identity, 'debt_service', _sum(r['bank_interest'], r['ic_interest_expense'], r['bank_local_margin'], r['bank_shared_margin'], r['ic_principal_paid']))
                threshold = out.inp('entities', ei, 'covenant_threshold_p12')
                required_ebitda = _sum(('product_whole', service, threshold), _if(('ge', ('product_remainder', service, threshold), 1), 1, 0))
                passed = bind(identity, 'covenant_passed', _if(('or', ('eq', service, 0), ('ge', r['ebitda'], required_ebitda)), 1, 0), monetary=False)
                run = bind(identity, 'cure_run_after_test', _if(passed, _if(r['trap_open'], _sum(r['cure_count_open'], 1), 0), 0), monetary=False)
                released = ('and', r['trap_open'], ('ge', run, 2))
                trap = bind(identity, 'trap_next', _if(passed, _if(released, 0, _if(r['trap_open'], 1, 0)), 1), monetary=False)
                bind(identity, 'cure_count_next', _if(released, 0, run), monetary=False)
                for field, side in (('ic_receivable_close', 'lender_id'), ('ic_payable_close', 'borrower_id')):
                    bind(identity, field, _sum(*(loan_balances[lid] for lid, (_, loan) in loans.items() if loan[side] == identity)))
                bind(identity, 'total_assets', _sum(r['cash_close'], r['restricted_close'], r['project_book_close'], r['ic_receivable_close']))
                bind(identity, 'total_liabilities', _sum(r['bank_close'], r['ic_payable_close']))
                bind(identity, 'net_assets', _sub(r['total_assets'], r['total_liabilities']))
                bind(identity, 'equity_close', _sum(r['capital_close'], r['retained_close']))
                external = bind(identity, 'external_cash_flow', _sub(_sum(r['revenue'], r['sale'], r['bank_draw'], call),
                    _sum(r['opex'], r['capex'], r['bank_interest'], r['current_tax'], r['bank_local_margin'], r['bank_shared_margin'], dist)))
                internal = bind(identity, 'internal_cash_flow', _sub(_sum(r['ic_interest_income'], r['ic_principal_received'], r['ic_draw_received']),
                    _sum(r['ic_interest_expense'], r['ic_principal_paid'], r['ic_draw_lent'])))
                residuals = {
                    'cash': _sub(_sum(r['cash_close'], r['restricted_close']), _sum(r['cash_open'], r['restricted_open'], external, internal)),
                    'bank': _sub(r['bank_close'], _sum(r['bank_open'], r['bank_draw'], _sub(0, _sum(r['bank_local_margin'], r['bank_shared_margin'])))),
                    'capital': _sub(r['capital_close'], _sum(r['capital_open'], call, _sub(0, roc))),
                    'retained': _sub(r['retained_close'], _sum(r['retained_open'], r['net_income'], _sub(0, profit))),
                    'project_book': _sub(r['project_book_close'], _sum(r['project_book_open'], r['capex'], _sub(0, _sum(r['depreciation'], r['sale_carrying'])))),
                    'ic_receivable': _sub(r['ic_receivable_close'], _sum(r['ic_receivable_open'], r['ic_draw_lent'], _sub(0, r['ic_principal_received']))),
                    'ic_payable': _sub(r['ic_payable_close'], _sum(r['ic_payable_open'], r['ic_draw_received'], _sub(0, r['ic_principal_paid']))),
                    'net_assets': _sub(r['net_assets'], r['equity_close']),
                    'interest_vintage': _sub(r['interest_vintage_close'], _sum(r['interest_vintage_open'], r['interest_denied_created'], _sub(0, _sum(queue_totals[identity]['interest_expired'], r['interest_old_used'])))),
                    'tax_loss_vintage': _sub(r['tax_loss_close'], _sum(r['tax_loss_open'], r['tax_loss_created'], _sub(0, _sum(queue_totals[identity]['tax_expired'], r['tax_loss_used']))))}
                for field, expression in residuals.items():
                    out.put(expression, identity + '/' + month + '/residual_' + field, (*prefix, 'entities', identity, 'monthly', mi, 'residuals', field), monetary=False)
                fx, previous_fx = r['fx_close_p12'], r['fx_open_p12']; opening_equity = _sum(r['capital_open'], r['retained_open'])
                capgbp = bind(identity, 'capital_historical_gbp', _sub(_sum(prior['capital_historical_gbp'], _round(call, fx)), _round(roc, fx)))
                retgbp = bind(identity, 'retained_historical_gbp', _sub(_sum(prior['retained_historical_gbp'], _round(r['net_income'], fx)), _round(profit, fx)))
                economic = bind(identity, 'economic_FX_this_month_gbp', _sub(_round(opening_equity, fx), _round(opening_equity, previous_fx)))
                postround = bind(identity, 'posting_translation_rounding_this_month_gbp', _sub(
                    _sum(_round(r['equity_close'], fx), _round(roc, fx), _round(profit, fx)),
                    _sum(_round(opening_equity, fx), _round(call, fx), _round(r['net_income'], fx))))
                fxreserve = bind(identity, 'economic_FX_reserve_gbp', _sum(prior['economic_FX_reserve_gbp'], economic))
                roundreserve = bind(identity, 'posting_translation_rounding_reserve_gbp', _sum(prior['posting_translation_rounding_reserve_gbp'], postround))
                bind(identity, 'translation_residual_gbp', _sub(_round(r['net_assets'], fx), _sum(capgbp, retgbp, fxreserve, roundreserve)), monetary=False)
                states[identity] = {**r, 'interest_vintages': prior['next_interest_vintages'], 'tax_vintages': prior['next_tax_vintages']}
            gp = {}; group_path = (*prefix, 'group_monthly', mi)
            def gp_pair(field, pair):
                gp[field] = out.pair(pair, (*group_path, field), sid + '/' + month + '/group_' + field)
                return gp[field]
            def exact_product(a, b):
                whole, remainder = _pair_product(a, b)
                return (out.put(whole, sid + '/' + month + '/exact_FX_whole', monetary=False),
                    out.put(remainder, sid + '/' + month + '/exact_FX_remainder', monetary=False))
            currency_by_entity = {identity: entity['currency'] for identity, (_, entity) in entities.items()}
            def grouped(amount, rate):
                return _currency_grouped_exact(out, rows, currency_by_entity, amount, rate,
                    exact_product, sid + '/' + month + '/group_FX')
            def translated(field): return grouped(lambda r: r[field], lambda r: r['fx_close_p12'])
            for stem, opening, closing, flow in (
                ('cash', lambda r: _sum(r['cash_open'], r['restricted_open']), lambda r: _sum(r['cash_close'], r['restricted_close']), lambda r: r['external_cash_flow']),
                ('bank', lambda r: r['bank_open'], lambda r: r['bank_close'], lambda r: _sub(r['bank_draw'], _sum(r['bank_local_margin'], r['bank_shared_margin']))),
                ('net_assets', lambda r: _sum(r['capital_open'], r['retained_open']), lambda r: r['equity_close'], lambda r: _sub(_sum(r['net_income'], r['capital_call']), r['distribution']))):
                start = gp_pair(stem + '_open_gbp_numerator', grouped(opening, lambda r: r['fx_open_p12']))
                end = gp_pair(stem + '_close_gbp_numerator', grouped(closing, lambda r: r['fx_close_p12']))
                movement = gp_pair(stem + '_external_movement_gbp_numerator', grouped(flow, lambda r: r['fx_close_p12']))
                fx = gp_pair(stem + '_FX_gbp_numerator', grouped(opening, lambda r: _sub(r['fx_close_p12'], r['fx_open_p12'])))
                gp_pair(stem + '_residual_gbp_numerator', _pair_sub(_pair_sub(_pair_sub(end, start), movement), fx))
            asset = gp_pair('intercompany_principal_eliminated_gbp_numerator', translated('ic_receivable_close'))
            income = gp_pair('intercompany_interest_eliminated_gbp_numerator', translated('ic_interest_income'))
            gp_pair('principal_elimination_residual_gbp_numerator', _pair_sub(asset, translated('ic_payable_close')))
            gp_pair('interest_elimination_residual_gbp_numerator', _pair_sub(income, translated('ic_interest_expense')))
            scalars = {'shared_bank_usage_gbp_pence': usage(), 'consolidated_cash_gbp_pence': _pair_round(gp['cash_close_gbp_numerator']),
                'consolidated_book_gbp_pence': _pair_round(translated('project_book_close')),
                'consolidated_external_bank_gbp_pence': _pair_round(translated('bank_close')),
                'consolidated_net_assets_gbp_pence': _pair_round(translated('equity_close')),
                'economic_FX_reserve_gbp_pence': _sum(*(r['economic_FX_reserve_gbp'] for r in rows.values())),
                'posting_rounding_reserve_gbp_pence': _sum(*(r['posting_translation_rounding_reserve_gbp'] for r in rows.values())),
                'historical_capital_gbp_pence': _sum(*(r['capital_historical_gbp'] for r in rows.values())),
                'historical_retained_gbp_pence': _sum(*(r['retained_historical_gbp'] for r in rows.values()))}
            for field, expression in scalars.items(): gp[field] = out.put(expression, sid + '/' + month + '/' + field, (*group_path, field))
            for field, expression in {
                'group_equity_translation_rounding_gbp_pence': _sub(gp['consolidated_net_assets_gbp_pence'], _rounded_equity_sum(out, rows, exact_product, sid + '/' + month)),
                'aggregate_line_rounding_gbp_pence': _sub(_sum(gp['consolidated_net_assets_gbp_pence'], gp['consolidated_external_bank_gbp_pence']), _sum(gp['consolidated_cash_gbp_pence'], gp['consolidated_book_gbp_pence']))}.items():
                gp[field] = out.put(expression, sid + '/' + month + '/' + field, (*group_path, field))
            prior_groups.append(gp)
        fiscal = {}
        for index, month in enumerate(months):
            year = int(month[:4]) + (int(month[5:7]) > 3); fiscal.setdefault(year, []).append(index)
        for fi, (year, indices) in enumerate(sorted(fiscal.items())):
            for stem in ('cash', 'bank', 'net_assets'):
                fields = {stem + '_open_gbp_numerator': prior_groups[indices[0]][stem + '_open_gbp_numerator'],
                    stem + '_close_gbp_numerator': prior_groups[indices[-1]][stem + '_close_gbp_numerator'],
                    stem + '_external_movement_gbp_numerator': _pair_sum([prior_groups[index][stem + '_external_movement_gbp_numerator'] for index in indices]),
                    stem + '_FX_gbp_numerator': _pair_sum([prior_groups[index][stem + '_FX_gbp_numerator'] for index in indices])}
                fields[stem + '_residual_gbp_numerator'] = _pair_sub(_pair_sub(_pair_sub(fields[stem + '_close_gbp_numerator'], fields[stem + '_open_gbp_numerator']), fields[stem + '_external_movement_gbp_numerator']), fields[stem + '_FX_gbp_numerator'])
                for field, pair in fields.items(): out.pair(pair, (*prefix, 'fiscal_years', fi, field), sid + '/FY' + str(year) + '/' + field)
    if _count_only:
        return {'kind': 'entity_group_complete_formula_count_only', 'version': 1,
            'dimension_mode': public['dimension_mode'], 'entity_count': len(public['entities']), 'month_count': len(months),
            'scenario_count': len(public['scenarios']), 'physical_formula_count': len(out.formulas),
            'logical_output_binding_count': len(out.bindings), 'binding_encodings': out.bindings.encodings,
            'unique_output_definition_references': len(out.bindings.refs), 'public_primitive_count': len(out.literals),
            'physical_nonempty_cells': sum(sheet.cells for sheet in book.sheets),
            'worksheet_count': len(book.sheets), 'worksheet_rows': {sheet.title: sheet.max_row for sheet in book.sheets},
            'maximum_expression_depth': out.formulas.max_depth, 'maximum_formula_length': out.formulas.max_formula_length,
            'formula_text_characters': out.formulas.formula_characters,
            'complete_expression_stream_sha256': out.formulas.digest.hexdigest(),
            'complete_logical_binding_stream_sha256': out.bindings.digest.hexdigest(),
            'within_one_million_physical_formulas': len(out.formulas) <= 1_000_000,
            'production_workbook_materialized': False, 'ledger_execution': False, 'LO_calls': 0, 'model_calls': 0,
            'qualified': False, 'task_count': 0}
    monetary_refs = {item['reference'] for item in out.bindings if item['encoding'] == 'scalar' and item['monetary']}
    monetary_refs.update(_ref(item['sheet'], item['cell']) for item in out.formulas if item['monetary'])
    actual_formula_refs = {_ref(item['sheet'], item['cell']) for item in out.formulas}
    return {'kind': 'entity_group_independent_excel_bindings', 'version': 1, 'public_spec': public,
        'worksheet_order': list(book.sheetnames),
        'formula_bindings': out.formulas, 'output_bindings': out.bindings, 'input_bindings': out.literals,
        'formula_count': len(out.formulas), 'physical_formula_limit': max_formulas,
        'monetary_formula_references': sorted(monetary_refs & actual_formula_refs),
        'monetary_field_aliases_cannot_protect_a_formula_value': True,
        'formula_flags_encoding': 'integer_0_or_1',
        'shared_definitions_are_aliases_not_duplicate_cells': True,
        'large_FX_numerators_use_exact_quotient_remainder_pairs': True,
        'unrounded_group_FX_aggregates_by_public_currency': True,
        'individual_posting_and_equity_rounding_retained': True,
        'fixed_plan_provided_and_protected': True, 'optimisation_performed': False,
        'independent_financial_audit_required': True, 'actual_LO_calls': 0, 'qualified': False, 'task_count': 0}


def count_entity_group_formulas(specification):
    """Run the complete compiler without openpyxl or any calculated values."""
    return emit_entity_group_workbook(_CounterBook(), specification, max_formulas=10_000_000,
        allow_production=True, _count_only=True)

"""Complete financial-graph inventory and field-level fault design.

This deliberately does not emit a partially covered task. Every monetary
family and qualified numeric return is inventoried. Nullable reference
formulas are reported by family, not treated as automatic task defects.
Unmapped financial faults block construction instead of shrinking its scope.
No financial reference calculation or engine is called.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import re

import openpyxl
from openpyxl.formula.tokenizer import Tokenizer
from openpyxl.utils import get_column_letter
from openpyxl.utils.cell import range_boundaries

from ..workbook.composite_finance.tasks import propose_task
from .lease_family import ref

FAULT_DESIGNS = {
    'measurement': 'Use contractual annuity timing or payment-unit error; zero-rate contracts require a separately specified payment-frequency error.',
    'opening': 'Use the wrong financial account or time-stage from the same public schema (ROU versus liability, capital versus retained earnings, gross versus net basis).',
    'closing': 'Mispost a named financial movement: wrong expense/principal account, omitted carrying interest, wrong return-of-capital or elimination sign. Rewrite the affected reference/operator inside the definition.',
    'interest': 'Use the wrong stated rate basis or wrong opening financial balance; do not append a multiplier to the correct complete calculation.',
    'depreciation': 'Use an incorrect service life or half-year convention, wrong tax pool rate or wrong remaining-basis cap; all in-service periods belong to the family.',
    'cash_settlement': 'Use the wrong contractual payment frequency or principal/interest component and calendar stage, across every contract and reporting period.',
    'vintage': 'Use the wrong vintage account, maturity/expiry boundary, transfer destination or FIFO capacity basis. Coverage must include all remaining nonzero vintage members, not only competition years.',
    'funding': 'Use the wrong borrowing-base component, haircut basis, available facility balance or finite commitment account; change the account definition itself.',
    'distribution': 'Use the wrong partner capital/profit base, cash priority or catch-up denominator; distinguish ROC from profit and current from next-FY carry.',
    'aggregate': 'Average monetary flows instead of summing them, sum a stock instead of taking the stated closing snapshot, or aggregate the wrong financial account.',
    'return': 'Use the wrong actual owner/partner cash-flow stream or annualisation convention. Preserve unqualified states; never treat a blank return as numeric zero.',
    'financial_identity': 'Misclassify a financial account or reverse one journal/elimination component, without introducing a balance-sheet plug.',
}


def _algorithm(sheet):
    prefix = sheet.split()[0].lower()
    return {'reopener': 'regulatory', 'partner': 'waterfall'}.get(prefix, prefix)


def field_role(sheet, label):
    label = str(label or '').lower().replace('_', ' ')
    if any(s in label for s in ('irr', 'npv', 'equity value', 'enterprise value')):
        return 'return'
    if 'pv' in label or 'measurement' in label or 'remeasure' in label:
        return 'measurement'
    if any(s in label for s in ('vintage', 'expired', 'losses', 'loss ', 'nol', 'tax basis', 'tax pool', 'capital allowance')) or sheet in ('Reopener Claims', 'Reopener Tax Loss', 'Reopener Tax Basis', 'Operating Tax Vintages'):
        return 'vintage'
    if any(s in label for s in ('collateral', 'borrowing base', 'headroom', 'commitment', 'lp required', 'lp capital', 'bank draw', 'margin', 'funding')):
        return 'funding'
    if any(s in label for s in ('preference', 'catchup', 'residual', 'distribution', 'return of capital', 'contribution')):
        return 'distribution'
    if 'interest' in label:
        return 'interest'
    if any(s in label for s in ('depreciation', 'amortisation', 'amortization')):
        return 'depreciation'
    if any(s in label for s in ('open', 'opening')):
        return 'opening'
    if any(s in label for s in ('close', 'closing')):
        return 'closing'
    if any(s in label for s in ('cash', 'payment', 'principal', 'repay', 'capex', 'rent', 'dividend')):
        return 'cash_settlement'
    if sheet in ('Lease Monthly', 'Lease Annual', 'Operating Annual Statements') or 'total' in label:
        return 'aggregate'
    return 'financial_identity'


def inventory_complete_graph(baseline, *, max_roots=100000):
    if type(max_roots) is not int or not 1 <= max_roots <= 100000:
        raise ValueError('max_roots must be from 1 to 100000')
    baseline = Path(baseline)
    proposal = propose_task(baseline, 'financial_modeling')
    formulas = openpyxl.load_workbook(baseline, keep_links=False)
    values = openpyxl.load_workbook(baseline, data_only=True, keep_links=False)
    try:
        cells = set()
        families = defaultdict(list)
        counts = defaultdict(Counter)
        for region in proposal['mask_ranges']:
            left, top, right, bottom = range_boundaries(region['range'])
            sheet = formulas[region['sheet']]
            for row in range(top, bottom + 1):
                for column in range(left, right + 1):
                    cell = sheet.cell(row, column)
                    if cell.data_type != 'f' or (sheet.title, cell.coordinate) in cells:
                        continue
                    cells.add((sheet.title, cell.coordinate))
                    cache = values[sheet.title][cell.coordinate]
                    if (type(cache.value) not in (int, float) or not math.isfinite(cache.value)
                            or cache.is_date or cache.data_type == 'e'):
                        raise ValueError('Unsupported typed financial target: ' + sheet.title + '!' + cell.coordinate)
                    kind = 'exact_numeric_zero' if cache.value == 0 else 'finite_numeric_nonzero'
                    label = sheet.cell(row, 1).value
                    role = field_role(sheet.title, label)
                    algorithm = _algorithm(sheet.title)
                    counts[algorithm][kind] += 1
                    families[(algorithm, sheet.title, row, str(label), role)].append(
                        {'cell': cell.coordinate, 'source_kind': kind,
                         'formula_sha256': hashlib.sha256(cell.value.encode()).hexdigest()})
        # A returned blank is not a monetary zero. Retain its legitimate
        # formula and disclose the limited reference coverage by family.
        nullable_donors = []
        if 'Partner Waterfall' in formulas:
            sheet = formulas['Partner Waterfall']
            for row in sheet:
                if str(row[0].value or '').replace('_', ' ').lower() != 'lp xirr':
                    continue
                for cell in row[2:]:
                    if cell.data_type == 'f' and values[sheet.title][cell.coordinate].value in (None, ''):
                        nullable_donors.append({'sheet': sheet.title, 'cell': cell.coordinate,
                            'typed_state': 'unqualified_blank_return',
                            'reason': 'Legitimate unqualified XIRR formula remains provided. Report template reuse coverage separately; do not count it as an active root or convert it to zero.'})
        nonzero = sum(v['finite_numeric_nonzero'] for v in counts.values())
        if nonzero > max_roots:
            raise ValueError('Complete graph exceeds bound; no prefix or subset may be emitted')
        records = [{'algorithm': k[0], 'sheet': k[1], 'row': k[2], 'field': k[3], 'role': k[4],
                    'cells': v, 'fault_design': FAULT_DESIGNS[k[4]],
                    'concrete_mutation_status': 'unimplemented_field_mapping',
                    'activity_status': 'requires_actual_two_context_proof'}
                   for k, v in sorted(families.items())]
        return {'schema_version': 2, 'adapter': 'composite_complete_financial_graph_v2',
            'status': 'full_scope_inventory_not_constructible', 'source': ref(baseline),
            'created_at': datetime.now(timezone.utc).isoformat(), 'families': records,
            'family_count': len(records), 'formula_slots': len(cells), 'prospective_nonzero_roots': nonzero,
            'counts_by_algorithm': {k: dict(v) for k, v in counts.items()},
            'provided_nullable_return_templates': nullable_donors,
            'global_correct_donor_absence_claimed': False,
            'typed_support': {'money': 'finite signed numbers; actual verifier normalization at 0.01',
                'numeric_return': 'finite numeric IRR/XIRR outputs; actual normalization activity required',
                'exact_zero': 'eligible for separately audited same-value provided zero presentation',
                'unqualified_blank_return': 'preserved with original formula and reported as a legitimate per-family reference',
                'dates_booleans_flags_phase_states': 'protected, not monetary roots'},
            'construction_blockers': ['Concrete business-field mutation mappings are required for every nonzero member; no fallback wrapper is permitted.',
                'New source full exact equivalence, actual pinned-runtime two-pass stability and independent audit lineage remain pending.',
                'Every planned root needs actual own-value activity in original and fully-mutated contexts; coupled suppression rejects the whole proposed graph.'],
            'actual_LO_executions': 0, 'model_calls': 0, 'selected': [], 'qualified': False}
    finally:
        formulas.close()
        values.close()


ADAPTER_ID = 'composite_complete_financial_graph_v2'
INPUT_PRIORITY_RULE = ('Scenario-specific values in the labelled input sheets govern timing, '
    'rates and amounts whenever a narrative brief gives a different default.')


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(',', ':'), allow_nan=False).encode()).hexdigest()


class IncompleteMutationCoverage(ValueError):
    """The complete report is available even though no partial task is emitted."""
    def __init__(self, report):
        self.report = report
        super().__init__('Complete financial mutation coverage rejected: '
            + str(len(report['unsatisfied_roots'])) + ' unsatisfied roots')


def _normal(label):
    return re.sub(r'[^a-z0-9]+', ' ', str(label or '').lower()).strip()


# These pairs identify actual related accounts in the public layout. An alias
# fault changes the account reference itself; it never appends an answer offset.
_PAIRS = (
 ('lease rou open', 'lease liability open'), ('lease rou close', 'lease liability close'),
 ('retained rou', 'retained liability'), ('lease rou derecognized', 'lease liability derecognized'),
 ('rou after measurement', 'liability after measurement'),
 ('lease cash rent', 'lease book expense'), ('lease tax deduction', 'lease book depreciation'),
 ('lease regulatory expense', 'lease book interest'),
 ('lease net temporary difference', 'lease liability close'),
 ('lease termination gain loss', 'lease termination fee cash'),
 ('lease direct cost cash', 'lease recurring rent'),
 ('asset initial gross', 'asset refresh gross'), ('accumulated depreciation', 'net ppe'),
 ('assets', 'liabilities'), ('equity', 'retained close'),
 ('cash open', 'cash close'), ('cash before allocation', 'cash close'),
 ('total cash including dsra', 'cash close'),
 ('ar open', 'ap open'), ('ar close', 'ap close'), ('inventory open', 'inventory close'),
 ('loan a open', 'loan b open'), ('loan a close', 'loan b close'),
 ('loan a interest', 'loan b interest'), ('loan a payment', 'loan b principal'),
 ('revolver open', 'loan a open'), ('revolver close', 'loan a close'),
 ('nol open', 'nol close'), ('interest cf close', 'nol close'),
 ('dta close', 'dtl close'), ('retained open', 'retained close'),
 ('dsra open', 'dsra close'), ('debt open', 'debt close'),
 ('opening cwip real', 'opening rav real'), ('closing cwip real', 'closing rav real'),
 ('capital entitlement', 'pre tax recovery'), ('losses created', 'losses used'),
 ('losses open', 'losses close'), ('claims open', 'claims close'),
 ('claims receipts', 'claim carrying interest'),
 ('total current variable rent cash paid', 'separately posted current variable regulatory allowance'),
 ('current variable rent book expense', 'separately posted current variable regulatory allowance'),
 ('current variable rent tax deduction', 'separately posted current variable regulatory allowance'),
 ('cash close', 'bank close'), ('bank open', 'cash open'),
 ('programme investment close', 'operating investment close'),
 ('programme income', 'programme distribution'), ('programme capital', 'programme distribution'),
 ('programme oci', 'programme income'),
 ('parent assets', 'programme assets'), ('parent equity', 'programme equity'),
 ('parent income', 'programme income'), ('parent oci', 'programme oci'),
 ('investment elimination', 'equity elimination'),
 ('owner capital', 'owner distribution'), ('net income', 'total equity'),
 ('lp capital open', 'gp capital open'), ('lp capital close', 'gp capital close'),
 ('lp distribution', 'gp distribution'), ('lp contribution', 'gp contribution'),
 ('capital distribution', 'profit distribution'), ('lp cumulative profit', 'gp cumulative profit'),
 ('lp net cashflow', 'gp net cashflow'),
 ('capital entitlement', 'earned revenue'), ('total assets', 'total equity'),
 ('net income', 'earned revenue'), ('net income', 'ebitda'),
 ('net income', 'programme income'),
 ('asset revaluation', 'revaluation reserve'),
 ('lp capital', 'lp required'), ('lp capital', 'lp called close'),
 ('capital called', 'distributable cash'),
 ('opening cash', 'facility limit'), ('opening cash', 'equity paid in'),
 ('lp capital fraction', 'initial carry rate'),
 ('operating ownership', 'gbp per usd'),
 ('management fee', 'bank rate'), ('rav advance rate', 'operating ownership'),
 ('claim advance rate', 'operating ownership'),
 ('initial direct cost', 'monthly base rent'),
 ('initial asset cost', 'refresh capex'), ('loan a principal', 'loan b principal'),
 ('original loan a level payment', 'loan a principal'),
 ('cash ebitda margin', 'cash cogs fraction'), ('dso', 'dpo'), ('dio', 'dso'),
 ('next ebitda', 'next annual sales'), ('enterprise value', 'equity exit'),
 ('initial asset depreciation', 'refresh depreciation'),
 ('capex', 'total depreciation'),
 ('total depreciation', 'accumulated depreciation'),
 ('total cash interest', 'loan a interest'), ('loan a scheduled principal', 'loan a extra principal'),
 ('dividend', 'cff'),
 ('quarter service', 'quarter cfads'), ('dsra net transfer', 'dsra funding'),
 ('nol used', 'nol new'), ('nol expired', 'nol used'),
 ('current tax', 'book tax'), ('deferred tax expense', 'book tax'),
 ('deferred tax expense', 'current tax'),
 ('real return', 'depreciation real'),
 ('capital spend nominal', 'commissioning nominal'),
)


def _related_rows(sheet, row):
    """Ordered, schema-based account alternatives, independent of cached answers."""
    labels = {_normal(c.value): c.row for c in sheet['A'] if c.value is not None}
    label = _normal(sheet.cell(row, 1).value)
    names = []
    for left, right in _PAIRS:
        if label == left:
            names.append(right)
        elif label == right:
            names.append(left)
    # Vintage rows carry an explicit batch identity, followed by a field. Keep
    # the batch fixed and misclassify its movement, rather than use another ID.
    if '|' in str(sheet.cell(row, 1).value):
        prefix, field = str(sheet.cell(row, 1).value).rsplit('|', 1)
        fields = {
            'close': ('collected', 'interest'), 'collected': ('interest', 'close'),
            'interest': ('collected', 'close'), 'expired': ('used', 'close'),
            'used': ('expired', 'close'), 'cwip close': ('rav close', 'depreciation'),
            'rav close': ('cwip close', 'depreciation'),
            'tax cip close': ('general close', 'structures close'),
            'general close': ('special close', 'capital allowance'),
            'special close': ('general close', 'capital allowance'),
            'structures close': ('tax cip close', 'capital allowance'),
            'capital allowance': ('structures close', 'general close'),
        }.get(_normal(field), ())
        names += [_normal(prefix + '|' + field) for field in fields]
    # A stock/flow or opening/closing confusion is defined by field names.
    for a, b in [(' open', ' close'), ('opening ', 'closing '),
                 (' interest', ' principal'), (' income', ' dividend'),
                 (' depreciation', ' capex'), (' capital', ' retained')]:
        if a in label:
            names.append(label.replace(a, b))
        if b in label:
            names.append(label.replace(b, a))
    return [labels[name] for name in dict.fromkeys(names) if name in labels and labels[name] != row]


_SINGLE_REF = re.compile(r"^(?:(?P<sheet>'(?:[^']|'')+'|[A-Za-z_][A-Za-z0-9_ ]*)!)?(?P<col>\$?[A-Z]{1,3})(?P<row>\$?\d+)$")


def _reference_parts(value, default_sheet):
    match = _SINGLE_REF.fullmatch(value)
    if not match:
        return None
    name = match['sheet']
    if name:
        name = name[1:-1].replace("''", "'") if name.startswith("'") else name
    return name or default_sheet, match['col'], match['row']


def _render(tokens):
    return '=' + ''.join(t.value for t in tokens)


def _retains_complete_operand(before, after):
    """Token boundaries avoid confusing C3 with the unrelated cell C30."""
    old = [(t.type, t.subtype, t.value) for t in Tokenizer(before).items if t.type != 'WHITE-SPACE']
    new = [(t.type, t.subtype, t.value) for t in Tokenizer(after).items if t.type != 'WHITE-SPACE']
    return len(new) > len(old) and any(new[i:i + len(old)] == old for i in range(len(new) - len(old) + 1))


def _field_fault(family, cell, book, *, lease_groups):
    """Compile a financial definition fault without calculating its result.

    The grammar is selected from the field and its parsed definition. It does
    not search for a mutation using oracle values. Actual numerical activity
    and financial validity of erroneous counterfactuals are separate gates.
    """
    before, sheet, label = cell.value, cell.parent.title, _normal(family['field'])
    tokens = Tokenizer(before).items
    # Use the tested contractual lease errors for the four measurement fields.
    if (sheet, cell.row) in lease_groups:
        from .composite_family import mutate_composite_cell
        group, cache = lease_groups[(sheet, cell.row)]
        after, reason = mutate_composite_cell(group, cell, book, cache)
        return after, 'lease_contract_definition', reason
    if 'XIRR(' in before.upper():
        if label != 'lp xirr' or sheet != 'Partner Waterfall':
            raise ValueError('Unmapped qualified return cash-flow identity')
        after = re.sub(r'(\$?B\$?)27(:\$?[A-Z]+\$?)27', r'\g<1>28\g<2>28', before)
        if after == before:
            raise ValueError('Qualified LP XIRR does not expose the documented partner stream')
        return after, 'partner_return_cashflow', 'Compute the LP displayed return from the GP actual dated net cash flows.'
    # A return convention is changed inside its exponent, not by attaching a
    # factor to the complete correct expression.
    if 'irr' in label and re.search(r'\^12\b', before):
        return re.sub(r'\^12\b', '^1', before), 'return_annualisation', 'Report the monthly compounding period as the annual owner return period.'
    if 'irr' in label and 'IRR(' in before.upper():
        # Drop the final dated owner settlement from the measurement window.
        # The earlier owner cash flows are still actual named financial data.
        for token in tokens:
            if token.type == 'OPERAND' and token.subtype == 'RANGE' and ':' in token.value:
                left, right = token.value.rsplit(':', 1)
                match = re.fullmatch(r'(\$?)([A-Z]+)(\$?\d+)', right)
                if match:
                    from openpyxl.utils import column_index_from_string
                    number = column_index_from_string(match[2])
                    if number > 2:
                        token.value = left + ':' + match[1] + get_column_letter(number - 1) + match[3]
                        return _render(tokens), 'owner_return_settlement_window', 'Omit the final owner cash-flow period from the return measurement window.'
    # Flow aggregation across time/entities is a distinct accounting fault.
    for token in tokens:
        if token.type == 'FUNC' and token.subtype == 'OPEN' and token.value.upper() in {'SUM(', 'SUMIF(', 'SUMIFS('}:
            old = token.value
            token.value = {'SUM(': 'AVERAGE(', 'SUMIF(': 'AVERAGEIF(', 'SUMIFS(': 'AVERAGEIFS('}[old.upper()]
            return _render(tokens), 'monetary_aggregation_average', 'Average the named financial movements instead of adding the required period or entity flows.'
    # Posting sign faults affect a named component inside the definition.
    # Prefer account substitutions first for simple aliases and rate products.
    arithmetic = [t for t in tokens if t.type == 'OPERATOR-INFIX' and t.value in '+-*/^']
    if not any(t.value in '+-' for t in arithmetic):
        for token in tokens:
            if token.type != 'OPERAND' or token.subtype != 'RANGE':
                continue
            parsed = _reference_parts(token.value, sheet)
            if not parsed or parsed[0] not in book:
                continue
            target, column, row = parsed
            if target == 'Reopener Assets' and column.replace('$', '') in {'F', 'G'}:
                old = column.replace('$', '')
                changed = 'G' if old == 'F' else 'F'
                token.value = token.value.rsplit('!', 1)[0] + '!' + ('$' if column.startswith('$') else '') + changed + row
                return _render(tokens), 'nominal_real_capital_basis', 'Misclassify the public asset batch nominal cost as its constant-price cost, or conversely.'
            for other in _related_rows(book[target], int(row.replace('$', ''))):
                original = token.value
                token.value = (original.rsplit('!', 1)[0] + '!' if '!' in original else '') + column + ('$' if row.startswith('$') else '') + str(other)
                return _render(tokens), 'related_account_misclassification', ('Post ' + family['field'] + ' using the related public account '
                    + target + '!' + str(book[target].cell(other, 1).value) + ' instead of ' + str(book[target].cell(int(row.replace('$', '')), 1).value) + '.')
    # Pick the first additive posting within the expression, not a synthetic
    # addition outside it. All fields retain their own control/calendar logic.
    for token in tokens:
        if token.type == 'OPERATOR-INFIX' and token.value in '+-':
            old = token.value
            token.value = '-' if old == '+' else '+'
            return _render(tokens), 'financial_component_posting_sign', ('Reverse the ' + ('additive' if old == '+' else 'subtractive')
                + ' component inside the ' + family['field'] + ' definition.')
    # Explicit time-period basis errors in non-additive depreciation/interest
    # definitions alter a denominator, never multiply the entire correct answer.
    for i, token in enumerate(tokens):
        if token.type == 'OPERATOR-INFIX' and token.value == '/' and i + 1 < len(tokens):
            next_token = tokens[i + 1]
            if next_token.type == 'OPERAND' and next_token.subtype == 'NUMBER' and next_token.value in {'12', '2'}:
                next_token.value = '1'
                return _render(tokens), 'financial_period_denominator', 'Treat the stated annual or half-year basis as one financial period in ' + family['field'] + '.'
    # MIN/MAX determine account-specific caps and priority; exchanging them is
    # an explicit cap/floor error and can be checked by the actual root gate.
    for token in tokens:
        if token.type == 'FUNC' and token.subtype == 'OPEN' and token.value.upper() in {'MIN(', 'MAX('}:
            token.value = 'MAX(' if token.value.upper() == 'MIN(' else 'MIN('
            return _render(tokens), 'account_cap_floor', 'Apply the opposite cap/floor to the named financial account ' + family['field'] + '.'
    raise ValueError('No documented account, posting, aggregation or period fault matches this field definition')


def compile_complete_report(presented_baseline, scope_inventory, policy=None):
    """Return the complete offline report, with no partial admission or calls."""
    policy = policy or {}
    if policy.get('adapter', ADAPTER_ID) != ADAPTER_ID:
        raise ValueError('Full graph policy identity differs')
    bound = policy.get('max_roots', 100000)
    if type(bound) is not int or not 1 <= bound <= 100000:
        raise ValueError('Full graph root bound must be from 1 to 100000')
    if scope_inventory.get('adapter') != ADAPTER_ID:
        raise ValueError('Scope adapter identity differs')
    families = scope_inventory['families']
    roots = {(f['sheet'], c['cell']) for f in families for c in f['cells'] if c['source_kind'] == 'finite_numeric_nonzero'}
    slots = [(f['sheet'], c['cell']) for f in families for c in f['cells']]
    if len(slots) != len(set(slots)) or len(roots) != scope_inventory['prospective_nonzero_roots']:
        raise ValueError('Duplicate or inconsistent complete scope inventory')
    if not roots or len(roots) > bound:
        raise ValueError('Complete graph exceeds bound; no roots may be truncated')
    book = openpyxl.load_workbook(presented_baseline, keep_links=False)
    caches = openpyxl.load_workbook(presented_baseline, data_only=True, keep_links=False)
    edits, unsatisfied, field_reports = [], [], []
    try:
        lease_groups = {}
        if 'Lease Inputs' in book and 'Lease Calendar' in book:
            from .lease_family import discover_families
            for g in discover_families(book, {'mutation_profile': 'contract_conditioned_v2'}):
                g = {**g, 'family': 'lease.' + g['family']}
                lease_groups[(g['sheet'], g['row'])] = (g, caches)
        for family in families:
            family_id = family['algorithm'] + '/' + family['sheet'] + '/' + str(family['row'])
            count, failed = 0, 0
            for item in family['cells']:
                address = (family['sheet'], item['cell'])
                cell = book[address[0]][address[1]]
                try:
                    if item['source_kind'] == 'exact_numeric_zero':
                        if type(cell.value) not in (int, float) or cell.value != 0 or cell.is_date:
                            raise ValueError('Exact zero must be presented as a provided numeric zero before task compilation')
                        continue
                    if cell.data_type != 'f' or not isinstance(cell.value, str):
                        raise ValueError('Every nonzero scoped monetary member must retain its original formula')
                    if not item.get('formula_sha256') or hashlib.sha256(cell.value.encode()).hexdigest() != item['formula_sha256']:
                        raise ValueError('Original monetary formula identity differs from complete scope')
                    after, mechanism, reason = _field_fault(family, cell, book, lease_groups=lease_groups)
                    if after == cell.value or not after.startswith('=') or _retains_complete_operand(cell.value, after):
                        raise ValueError('Unchanged or whole-correct-formula wrapper is forbidden')
                    Tokenizer(after)  # Syntax tokenization, not an engine validity claim.
                    edits.append({'sheet': address[0], 'cell': address[1], 'before': cell.value,
                        'after': after, 'family_id': family_id, 'field': family['field'],
                        'algorithm': family['algorithm'], 'mechanism': mechanism, 'reason': reason,
                        'business_rule': 'Apply the unchanged public contract and financial posting policies.'})
                    count += 1
                except (ValueError, KeyError, IndexError) as error:
                    failed += 1
                    unsatisfied.append({'sheet': address[0], 'cell': address[1], 'field': family['field'], 'reason': str(error)})
            field_reports.append({'family_id': family_id, 'field': family['field'], 'compiled_roots': count,
                'unsatisfied_roots': failed, 'status': 'compiled_pending_actual_activity' if failed == 0 else 'unmapped_or_invalid'})
        compiled = {(e['sheet'], e['cell']) for e in edits}
        passed = not unsatisfied and compiled == roots
        return {'schema_version': 2, 'adapter': ADAPTER_ID, 'status': 'offline_complete_pending_actual_proofs' if passed else 'rejected_incomplete_offline_coverage',
            'offline_compile_complete': passed, 'presented_baseline': ref(presented_baseline),
            'original_scope_source': scope_inventory['source'], 'scope_inventory_sha256': canonical_sha(scope_inventory),
            'policy_sha256': canonical_sha(policy), 'root_count': len(roots), 'compiled_root_count': len(edits),
            'family_count': len(families), 'family_reports': field_reports, 'unsatisfied_roots': unsatisfied,
            'counts_by_algorithm': dict(Counter(e['algorithm'] for e in edits)),
            'counts_by_mechanism': dict(Counter(e['mechanism'] for e in edits)),
            'edits': edits, 'edits_sha256': canonical_sha(edits),
            'provided_zero_count': len(slots) - len(roots),
            'provided_nullable_return_templates': scope_inventory.get('provided_nullable_return_templates', []),
            'global_correct_donor_absence_claimed': False,
            'activity_status': 'not_executed_individual_or_joint', 'counterfactual_global_uniqueness_claimed': False,
            'actual_LO_executions': 0, 'model_calls': 0, 'selected': [], 'qualified': False}
    finally:
        book.close()
        caches.close()


def compile_complete_mutation(presented_baseline, scope_inventory, policy=None):
    """Compile every proposed monetary root, or reject the complete proposal."""
    report = compile_complete_report(presented_baseline, scope_inventory, policy)
    if report['offline_compile_complete'] is not True:
        raise IncompleteMutationCoverage(report)
    return {'title': 'Audit the interconnected financial model',
        'public_instruction': 'Audit and repair inconsistent financial formulas across the financial model. Apply the public contracts and business briefs, preserve provided inputs, inactive monetary constants, calendars and original regulatory context, and save /app/output.xlsx.',
        'public_rules': [INPUT_PRIORITY_RULE, 'The stated contractual and accounting policies apply across all original reporting periods.'],
        'edits': report['edits'], 'mask_ranges': [], 'assumptions_added': [],
        'family_adapter': {'id': ADAPTER_ID, 'status': 'planned_not_activity_proven',
            **{k: report[k] for k in ('root_count', 'family_count', 'edits_sha256', 'policy_sha256',
                'scope_inventory_sha256', 'presented_baseline', 'original_scope_source',
                'counts_by_algorithm', 'counts_by_mechanism', 'provided_zero_count',
                'provided_nullable_return_templates', 'global_correct_donor_absence_claimed')},
            'root_proof_route': 'mixed_DAG_SCC_local_two_context_own_value_lower_bounds',
            'difficulty_measured': False, 'selected': [], 'qualified': False}}


def propose_complete_debugging_task(baseline, policy=None, *, scope_inventory=None):
    if scope_inventory is None:
        raise ValueError('A bound original full-scope inventory is required; source presentation alone is not proof')
    return compile_complete_mutation(baseline, scope_inventory, policy)

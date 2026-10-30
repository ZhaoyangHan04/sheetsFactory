"""Extract one audited project without shifting its dates or currency.

Formula references are rewritten as tokens. Text literals are never rewritten.
Independent results and provenance stay in the caller's private evidence.
"""
from copy import copy
import hashlib
import json
from pathlib import Path

import openpyxl
from openpyxl.formula import Tokenizer
from openpyxl.utils import get_column_letter

from ..derived_gold.ledger import simulate
from ..derived_gold.validate import ledger_invariants_pass


OPERATING_CASH_STAGE_POLICY = (
    'Cash before allocation is operating cash after CFO, refresh capital spending and scheduled '
    'Loan A and Loan B principal, before DSRA transfers, revolver draws or repayments, optional '
    'prepayment and dividends. Cash gap is the unmet operating minimum after reserve support and '
    'the permitted revolver draw. Available excess is operating cash above minimum after DSRA '
    'transfers and revolver repayment, before optional prepayment and dividends. The optional '
    'allocation allowed flag is one from the stated allocation-start month onward and zero before, '
    'independently of the distribution lock and reserve shortfall.'
)


def clarify_operating_cash_stages(book, spec, sheet_name):
    """Add explicit stage definitions without changing financial inputs or formulas."""
    rules = spec['public_rules']
    if not isinstance(rules, list) or any(not isinstance(rule, str) for rule in rules):
        raise ValueError('Operating public policies must be an explicit list of text rules')
    if OPERATING_CASH_STAGE_POLICY in rules:
        raise ValueError('Operating cash-stage policy already exists')
    rules.append(OPERATING_CASH_STAGE_POLICY)
    sheet = book[sheet_name]
    row = sheet.max_row + 2
    sheet.cell(row, 1, 'Cash reporting stages')
    sheet.cell(row, 2, OPERATING_CASH_STAGE_POLICY)
    return {'sheet': sheet_name, 'cell': 'B' + str(row), 'public_policy': OPERATING_CASH_STAGE_POLICY,
            'scope': 'Clarifies existing cash-reporting stage definitions; no financial formula, parameter or result is changed.'}


def checked_json(reference):
    path = Path(reference['path'])
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != reference['sha256']:
        raise ValueError('Changed operating evidence: ' + path.name)
    return json.loads(payload)


def rewrite_formula(formula, mapping):
    tokens = Tokenizer(formula)
    for token in tokens.items:
        if token.type != 'OPERAND' or token.subtype != 'RANGE' or '!' not in token.value:
            continue
        name, address = token.value.rsplit('!', 1)
        if name.startswith("'") and name.endswith("'"):
            name = name[1:-1].replace("''", "'")
        if name not in mapping:
            raise ValueError('Operating formula has an unmapped sheet dependency: ' + name)
        token.value = "'" + mapping[name].replace("'", "''") + "'!" + address
    return tokens.render()


def append_operating_entity(book, manifest_path, *, entity_id='T01', prefix='Operating ', contract_revision=1):
    manifest_path = Path(manifest_path)
    if type(contract_revision) is not int or contract_revision not in (1, 2):
        raise ValueError('Unsupported explicit operating public-contract revision')
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('financial_audit_passed') is not True:
        raise ValueError('An actually financially audited portfolio source is required')
    source_path = Path(manifest['local_path'])
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != manifest['derived_workbook_sha256']:
        raise ValueError('Changed operating source workbook')
    candidates = [entity for entity in manifest['entities'] if entity['id'] == entity_id]
    if len(candidates) != 1:
        raise ValueError('Operating entity selection must be unique')
    entity = candidates[0]
    spec = checked_json(entity['public_scenario'])
    previous_ledger = checked_json(entity['ledger'])
    bindings = checked_json(entity['bindings'])
    ledger = simulate(spec)
    if (json.loads(json.dumps(ledger, default=str)) != previous_ledger
            or not ledger_invariants_pass(ledger['checks'])):
        raise ValueError('Operating independent journal no longer reproduces the bound source')
    source_mapping = entity['sheet_mapping']
    mapping = {name: prefix + name for name in source_mapping}
    full_mapping = {full: mapping[name] for name, full in source_mapping.items()}
    if (len(set(mapping.values())) != len(mapping)
            or any(len(name) > 31 or name in book.sheetnames for name in mapping.values())):
        raise ValueError('Operating worksheet names collide or exceed Excel limits')
    source = openpyxl.load_workbook(source_path, keep_links=False)
    formula_count = 0
    try:
        if source.defined_names:
            raise ValueError('Named operating dependencies require an explicit adapter')
        for original, full in source_mapping.items():
            ws = source[full]
            if (ws.tables or ws._charts or ws._images or ws.data_validations.count
                    or len(ws.conditional_formatting)):
                raise ValueError('Unsupported operating worksheet objects require an explicit adapter')
            target = book.create_sheet(mapping[original])
            for cell in ws._cells.values():
                value = cell.value
                if cell.data_type == 'f':
                    value = rewrite_formula(value, full_mapping)
                    formula_count += 1
                out = target.cell(cell.row, cell.column, value)
                # Workbook-local style IDs cannot be copied across workbooks.
                for style in ('font', 'fill', 'border', 'alignment', 'protection'):
                    setattr(out, style, copy(getattr(cell, style)))
                out.number_format = cell.number_format
                if cell.comment is not None:
                    out.comment = copy(cell.comment)
            for dimension, value in ws.column_dimensions.items():
                target.column_dimensions[dimension] = copy(value)
                target.column_dimensions[dimension].parent = target
            for dimension, value in ws.row_dimensions.items():
                target.row_dimensions[dimension] = copy(value)
                target.row_dimensions[dimension].parent = target
            for merged in ws.merged_cells.ranges:
                target.merge_cells(str(merged))
            target.freeze_panes = ws.freeze_panes
            target.sheet_state = ws.sheet_state
    finally:
        source.close()

    policy_adapters = []
    if contract_revision == 2:
        policy_adapters.append(clarify_operating_cash_stages(book, spec, mapping['Read Me']))

    def reference(sheet, address):
        return "'" + mapping[sheet].replace("'", "''") + "'!" + address

    monthly = []
    for index in range(len(ledger['monthly'])):
        col = get_column_letter(index + 3)
        monthly.append({key: reference(bindings['monthly'][key]['sheet'],
                       col + str(bindings['monthly'][key]['row']))
                        for key in ('date', 'net_income', 'dividend')})
    refs = {'monthly': monthly,
            'equity_paid_in': reference('Scenario', '$B$' + str(bindings['parameter_rows']['equity_paid_in'])),
            'equity_exit': reference('Equity Value', bindings['valuation']['equity_exit'])}
    return {'sheet_mapping': mapping, 'source_sheet_mapping': source_mapping,
            'public_scenario': spec, 'ledger': ledger, 'bindings': bindings,
            'formula_count': formula_count, 'operating_refs': refs,
            'lineage': {'portfolio_manifest': str(manifest_path.resolve()),
                        'portfolio_manifest_sha256': hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
                        'portfolio_workbook_sha256': manifest['derived_workbook_sha256'],
                        'entity_id': entity_id, 'original_dates_preserved': True,
                        'original_currency': 'USD', 'independent_journal_recomputed': True,
                        'public_contract_revision': contract_revision, 'public_policy_adapters': policy_adapters}}

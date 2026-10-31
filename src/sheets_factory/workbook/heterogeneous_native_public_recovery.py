"""Public native-table/formula recovery using the shared Excel implementation.

No private specification, binding file, goal, cached financial answer or defect
list is accepted. The frozen parser's pure table routines are reused in a new
namespace; intact public asset formulas establish its otherwise unstated asset
convention. Formula regeneration is not a third independent financial ledger.
"""
from __future__ import annotations

import ast
import calendar
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path

import openpyxl
from openpyxl.utils.datetime import WINDOWS_EPOCH, from_excel

from .heterogeneous_contracts import spec, specialized_excel
from ..task_adapters import heterogeneous_formula_identity as lexical

BACKEND = 'heterogeneous_native_tables_shared_specialized_excel_reconstruction_v1'
PARSER = Path(__file__).with_name('heterogeneous_financial_view_public_recovery.py')
PARSER_SHA256 = '009a454cd9a6a03b14054be7218b54e6809f7188622b088153f24c9aa059b5bf'
LEXICAL_SHA256 = 'a4f6be1aa36b9b2fae34fbd7c313afc2bbbb8526256b88008a110850acf84ab5'
SHARED_SHA256 = {
    'heterogeneous_contracts/spec.py': 'e501a93319532c7132f256a0c2e01e0354ea3ababaf2627237e56f166d90bdcf',
    'heterogeneous_contracts/excel.py': '8f45b0f1e325c987f6f31c4fa89a8ee0698e74f46478015110ac4e53287b70c7',
    'heterogeneous_contracts/specialized_excel.py': '8d1c7a52a61276aa5be95cad5918a60235d1efde1ff2c846356cd2cb349835ee',
    'heterogeneous_contracts/policy_specialization.py': 'e3eb1c0836325afe6db217de6522a11783076cd2ac2250c2bb7c40b8ea655e21',
    'entity_group/excel.py': '65049b4749c269b01efeed0a10d3f06bd50638396ebd8967bd7132c076733da4',
    'entity_group/spec.py': 'f98ae807d392bcfe79ef9ae7d9df12e226eb55ddc53fd0e5b4579835715fa509',
}
_RAW = ('Contract Notes', 'Calendar', 'Entity Policies', 'Opening Balances', 'Facilities',
    'Facility Terms', 'Asset Register', 'Operating Forecast', 'Scenario Assumptions',
    'Portfolio Funding', 'Allocation Priorities', 'Opening Tax Attributes')
_REPORTS = ('Calculations', 'Entity Close', 'Loan Close', 'Asset Close',
    'Interest FIFO', 'Loss FIFO', 'Group Close')


class PublicRecoveryError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise PublicRecoveryError(message)


def reference(value):
    p = Path(value).absolute()
    require(p == p.resolve() and p.is_file() and not p.is_symlink(), 'A real regular public file is required')
    before = p.stat(); h = hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            h.update(block)
    after = p.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
        'A public artifact changed during hashing')
    return {'path': str(p), 'sha256': h.hexdigest(), 'bytes': after.st_size}


def implementation_recipe():
    result = {'recovery': reference(__file__), 'pure_parser_template': reference(PARSER),
        'lexical_identity': reference(lexical.__file__)}
    require(result['pure_parser_template']['sha256'] == PARSER_SHA256,
        'The frozen public table parser changed')
    require(result['lexical_identity']['sha256'] == LEXICAL_SHA256,
        'The bounded formula token identity implementation changed')
    for relative, digest in SHARED_SHA256.items():
        result[relative] = reference(Path(__file__).parent / relative)
        require(result[relative]['sha256'] == digest, 'A shared financial or arithmetic implementation changed')
    return result


def native_sheetnames(scenarios):
    return list(_RAW) + ['Input Calculations'] + [sid + ' ' + name for sid in scenarios for name in _REPORTS]


def _public_contract(book):
    require(book.epoch == WINDOWS_EPOCH and not book.defined_names
        and not getattr(book, '_external_links', []), 'Unsupported epoch, names or external links')
    require(all(name in book.sheetnames for name in _RAW), 'A native public input/notes sheet is absent')
    require(all(sheet.sheet_state == 'visible' for sheet in book), 'All public worksheets must be visible')
    for title in _RAW:
        for row in book[title].iter_rows():
            for cell in row:
                require(cell.data_type not in ('f', 'e') and type(cell.value) is not bool,
                    'Native public tables require provided literals and numeric Boolean encodings')
    notes = []
    for row in book['Contract Notes'].iter_rows(values_only=True):
        require(all(value is None for value in row[2:]), 'Unexpected policy-note columns')
        if any(value is not None for value in row):
            notes.append(tuple((list(row) + [None, None])[:2]))
    expected = [('Heterogeneous debt and tax contracts', 'Public policy')]
    expected += [('Policy ' + str(i), value) for i, value in enumerate(specialized_excel.PUBLIC_NOTES, 1)]
    expected += [('Close phase', value) for value in spec.PHASES]
    require(notes == expected, 'The complete original native public policies and phases are required')


def pure_parser_ast():
    """Extract only frozen primitive parsing, with one exact native layout edit."""
    raw = PARSER.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == PARSER_SHA256, 'The frozen pure parser template changed')
    tree = ast.parse(raw)
    functions = {'_text', '_integer', '_day', '_rows', '_parse_book'}
    constants = {'HEADERS', 'PUBLIC_SHEETS'}
    selected = []; found = set(); changed = 0
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in constants:
            selected.append(node); found.add(node.targets[0].id)
        elif isinstance(node, ast.FunctionDef) and node.name in functions:
            if node.name == '_parse_book':
                for statement in node.body:
                    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
                        call = statement.value
                        if isinstance(call.func, ast.Name) and call.func.id == 'require' \
                                and len(call.args) == 2 and isinstance(call.args[1], ast.Constant) \
                                and call.args[1].value == 'The complete business worksheet names or order changed':
                            call.args[0] = ast.parse('book.sheetnames == native_sheetnames(scenario_ids)', mode='eval').body
                            changed += 1
            selected.append(node); found.add(node.name)
    require(found == functions | constants and changed == 1, 'The exact pure-parser extraction/layout changed')
    return ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))


def parse_public_inputs(book):
    namespace = {'calendar': calendar, 'date': date, 'datetime': datetime, 'Decimal': Decimal,
        'json': json, 'spec': spec, 'PublicRecoveryError': PublicRecoveryError, 'require': require,
        '_public_contract': _public_contract, 'native_sheetnames': native_sheetnames}
    exec(compile(pure_parser_ast(), '<SHA-bound native primitive parser>', 'exec'), namespace)
    return namespace['_parse_book'](book)


def _typed(cell, epoch):
    value = cell.value
    if value is None:
        return ('empty', None)
    if type(value) is bool:
        return ('bool', value)
    if cell.is_date and isinstance(value, (int, float)):
        value = from_excel(value, epoch)
    if isinstance(value, datetime):
        return ('date', value.isoformat())
    if isinstance(value, date):
        return ('date', datetime.combine(value, datetime.min.time()).isoformat())
    if type(value) in (int, float, Decimal):
        return ('number', Decimal(str(value)))
    return (cell.data_type, value)


def _literal_inventory(book):
    return {(s.title, c.coordinate): _typed(c, book.epoch) for s in book for c in s._cells.values()
        if c.value is not None and c.data_type != 'f'}


def attest_public_asset_rules(source, regenerated, bindings):
    """Match the complete public asset definition closure; never read caches.

    Bindings here were freshly generated from public primitives, not supplied
    by a private source or goal. This recognizes the shared emitter's exact
    asset convention, including prior states and primitive-only conversions.
    """
    compiler = specialized_excel.compiler
    graph = {compiler._reference(r): r for r in bindings['arithmetic_bindings']}
    inputs = {compiler._reference(r): r for r in bindings['input_bindings'] + bindings['literal_bindings']}
    roots = [r for r in bindings['financial_bindings']
        if len(r['expected_path']) >= 3 and r['expected_path'][2] == 'assets']
    require(bool(roots), 'An intact public asset formula convention must be observable')
    stack = [compiler._reference(r) for r in roots]; checked = set(); leaves = set()
    while stack:
        ref = stack.pop()
        if ref in checked:
            continue
        row = graph.get(ref)
        if row is None:
            leaf = inputs.get(ref)
            require(leaf is not None and leaf['sheet'] in ('Asset Register', 'Calendar'),
                'An asset rule depends on an unsupported external or non-asset account')
            leaves.add(ref)
            continue
        owner = row.get('semantic_owner')
        require((isinstance(owner, list) and len(owner) >= 3 and owner[2] == 'assets')
            or (row['sheet'] == 'Input Calculations' and isinstance(row.get('provided_input'), list)
                and row['provided_input'][:1] == ['assets']),
            'An asset rule depends on an unknown financial policy')
        actual = source[row['sheet']][row['cell']]
        require(actual.data_type == 'f' and lexical.formula_signature(actual.value)
            == lexical.formula_signature(regenerated[row['sheet']][row['cell']].value),
            'An intact public asset formula/rounding/commissioning rule cannot be established')
        checked.add(ref); stack.extend(compiler._refs(row['expression']))
    return {'kind': 'public_asset_formula_policy_recognition', 'asset_financial_roots': len(roots),
        'complete_definition_formulas_checked': len(checked), 'native_input_leaves': sorted(leaves),
        'all_asset_periods_and_scenarios_covered': True, 'computed_caches_used': False,
        'policy_note_injected': False, 'independent_financial_implementation_claimed': False}


def recover_public(source, destination, report, instruction_path=None):
    """Regenerate same-geometry formulas solely from native public facts."""
    source_ref = reference(source); recipe = implementation_recipe()
    instruction_ref = reference(instruction_path) if instruction_path is not None else None
    destination, report = Path(destination).absolute(), Path(report).absolute()
    require(destination != report and str(destination) != source_ref['path']
        and str(report) != source_ref['path'] and not destination.exists() and not report.exists()
        and not destination.is_symlink() and not report.is_symlink()
        and destination.parent == destination.parent.resolve() and report.parent == report.parent.resolve(),
        'Fresh distinct regular output/report paths are required')
    book = openpyxl.load_workbook(source_ref['path'], data_only=False, keep_links=True)
    regenerated = openpyxl.Workbook()
    try:
        public = parse_public_inputs(book)
        before_literals = _literal_inventory(book)
        original_order = list(book.sheetnames)
        original_styles = {(s.title, c.coordinate): (None if c._style is None else tuple(c._style))
            for s in book for c in s._cells.values()}
        bindings = specialized_excel.emit_heterogeneous_workbook(regenerated, public,
            max_formulas=1_000_000, allow_production=public['dimension_mode'] != 'toy')
        expected = {(r['sheet'], r['cell']): r['formula'] for r in bindings['arithmetic_bindings']}
        actual = {(s.title, c.coordinate) for s in book for c in s._cells.values() if c.data_type == 'f'}
        require(regenerated.sheetnames == original_order and actual == set(expected),
            'The complete native formula geometry is missing or contains additional definitions')
        require(_literal_inventory(regenerated) == before_literals,
            'The public primitive/report identities or supplied literal geometry differs')
        asset = attest_public_asset_rules(book, regenerated, bindings)
        rewritten = 0
        for (sheet, cell), formula in expected.items():
            if lexical.formula_signature(book[sheet][cell].value) != lexical.formula_signature(formula):
                rewritten += 1
            book[sheet][cell].value = formula
        require(book.sheetnames == original_order and _literal_inventory(book) == before_literals,
            'Formula reconstruction changed a provided literal or worksheet identity')
        require(original_styles == {(s.title, c.coordinate): (None if c._style is None else tuple(c._style))
            for s in book for c in s._cells.values()}, 'A supplied style changed during recovery')
        require(source_ref == reference(source) and recipe == implementation_recipe(),
            'The exact public input or reconstruction code changed during recovery')
        if instruction_ref is not None:
            require(reference(instruction_path) == instruction_ref, 'The exact instruction changed')
        book.save(destination)
        result = {'kind': 'public_native_specialized_formula_reconstruction', 'version': 1,
            'backend': BACKEND, 'input': source_ref, 'instruction': instruction_ref,
            'output': reference(destination), 'implementation_recipe': recipe,
            'public_specification_sha256': spec.canonical_sha256(public),
            'public_specification_is_not_private_construction_JSON_identity': True,
            'scope': {'entities': len(public['entities']), 'months': len(public['months']),
                'scenarios': len(public['scenarios'])},
            'worksheets': len(original_order), 'complete_formula_count': len(expected),
            'lexically_different_formula_count': rewritten, 'asset_policy': asset,
            'public_literals_styles_and_sheet_order_preserved': True,
            'shared_source_Excel_reconstruction': True, 'third_independent_financial_implementation': False,
            'private_goal_spec_bindings_defect_list_or_cached_answers_used': False,
            'independent_Decimal_journal_executed': False, 'actual_LO_calls': 0,
            'actual_isolated_replay_verified': False, 'whole_D_host_scoring_pending': True,
            'quality_or_difficulty_certified': False}
        with report.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write('\n')
        require(source_ref == reference(source) and recipe == implementation_recipe(),
            'The public input or code changed before finalizing the report')
        return result
    finally:
        book.close(); regenerated.close()

"""Independent full-value audit for heterogeneous contract workbooks.

Financial expectations come from a separately supplied journal. Support
expressions are replayed with exact Fractions from private primitives, never
from workbook caches. This module imports neither financial implementation.
"""
from collections import defaultdict, deque
from datetime import date, datetime
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re
from xml.etree import ElementTree
from zipfile import ZipFile

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import WINDOWS_EPOCH, from_excel, to_excel

from ...evaluation.streaming_verifier import _sparse_cells

SCALE = 10**12
REF = re.compile(r"^'((?:[^']|'')+)'!\$([A-Z]+)\$([1-9][0-9]*)$")


class ValidationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def canonical_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _path(value, path):
    require(isinstance(path, (tuple, list)), 'A private source/result path is required')
    for key in path:
        try:
            value = value[key]
        except (KeyError, IndexError, TypeError) as error:
            raise ValidationError('A bound source/result path does not exist') from error
    return value


def _number(value):
    require(type(value) is not bool, 'A numeric posting cannot be a boolean')
    if isinstance(value, Fraction):
        return value
    require(isinstance(value, (int, float, Decimal)), 'A finite numeric value is required')
    require(not isinstance(value, float) or math.isfinite(value), 'A finite numeric value is required')
    try:
        return Fraction(str(value))
    except (ValueError, OverflowError) as error:
        raise ValidationError('A finite numeric value is required') from error


def _round(value):
    value = _number(value)
    answer = (2*abs(value.numerator) + value.denominator) // (2*value.denominator)
    return Fraction(-answer if value < 0 else answer)


def _serial(value):
    if type(value) in (int, float, Decimal):
        return _number(value)
    if isinstance(value, str):
        value = date.fromisoformat(value)
    require(isinstance(value, (date, datetime)), 'An ISO date is required')
    return _number(to_excel(value, epoch=WINDOWS_EPOCH))


def _projection(value, row):
    kind = row['kind']
    scale = row.get('worksheet_scale', 1)
    require(type(scale) is int and scale > 0, 'A positive integer worksheet scale is required')
    require(kind in {'money_pence', 'rate_p12', 'ratio_micro', 'ratio_millionths',
        'integer', 'flag', 'nullable_flag', 'nullable_ratio_micro',
        'date', 'nullable_date', 'text', 'string'}, 'Unknown projection kind')
    if value is None:
        require(kind.startswith('nullable_'), 'A nonnullable financial value is missing')
        return ''
    if kind in ('date', 'nullable_date'):
        require(row.get('epoch', '1900') == '1900' and scale == 1, 'Only explicit 1900 dates are supported')
        return _serial(value)
    if kind in ('text', 'string'):
        require(type(value) is str and scale == 1, 'A text binding has the wrong source type')
        return value
    if kind in ('flag', 'nullable_flag'):
        require(value in (0, 1) and type(value) in (int, bool) and scale == 1, 'A numeric 0/1 flag is required')
        return Fraction(int(value))
    require(type(value) is int, 'A financial posting must be an integer in its private unit')
    require(abs(value) < 2**53, 'A private posting exceeds the exact worksheet integer envelope')
    return Fraction(value, scale)


def _ref(value):
    match = REF.fullmatch(value) if isinstance(value, str) else None
    return (match[1].replace("''", "'"), match[2]+match[3]) if match else None


def _dependencies(expression):
    found = _ref(expression)
    if found:
        return {found}
    if not isinstance(expression, (tuple, list)):
        return set()
    require(bool(expression) and isinstance(expression[0], str), 'An explicit arithmetic operation is required')
    return set().union(*(_dependencies(arg) for arg in expression[1:]))


def _truth(value):
    return bool(_number(value))


def _evaluate(expression, values):
    reference = _ref(expression)
    if reference:
        return values[reference]
    if type(expression) in (int, bool):
        return Fraction(int(expression))
    if isinstance(expression, str):
        return expression
    require(isinstance(expression, (list, tuple)) and bool(expression), 'Unsupported arithmetic literal')
    op, *args = expression
    if op == 'if':
        require(len(args) == 3, 'IF requires three arguments')
        return _evaluate(args[1] if _truth(_evaluate(args[0], values)) else args[2], values)
    items = [_evaluate(arg, values) for arg in args]
    if op in ('year', 'month'):
        require(len(items) == 1, 'A date extraction requires one argument')
        serial = _number(items[0])
        require(serial.denominator == 1 and serial >= 61, 'Use a supported whole 1900-epoch date')
        when = from_excel(int(serial), epoch=WINDOWS_EPOCH)
        require(isinstance(when, datetime), 'A supported calendar date is required')
        return Fraction(getattr(when, op))
    if op in ('eq', 'lt', 'le', 'ge'):
        require(len(items) == 2, 'A comparison requires two arguments')
        return Fraction(int({'eq':lambda: items[0] == items[1],
            'lt':lambda: items[0] < items[1], 'le':lambda: items[0] <= items[1],
            'ge':lambda: items[0] >= items[1]}[op]()))
    if op in ('and', 'or'):
        return Fraction(int((all if op == 'and' else any)(_truth(item) for item in items)))
    nums = [_number(item) for item in items]
    if op == 'sum': return sum(nums, Fraction(0))
    if op in ('min', 'max'):
        require(bool(nums), 'An extremum needs an argument')
        return (min if op == 'min' else max)(nums)
    if op == 'abs':
        require(len(nums) == 1, 'ABS requires one argument')
        return abs(nums[0])
    require(len(nums) == 2, 'A binary arithmetic operation requires two arguments')
    a, b = nums
    if op == 'sub': return a-b
    if op == 'mul': return a*b
    if op in ('div', 'floordiv', 'ceildiv', 'rounddiv', 'mod'):
        require(b > 0, 'The supported arithmetic denominator must be positive')
        if op == 'div': return a/b
        if op == 'floordiv': return Fraction(a//b)
        if op == 'ceildiv': return Fraction(-((-a)//b))
        if op == 'rounddiv': return _round(a/b)
        return a-b*(a//b)
    if op in ('product_whole', 'product_remainder', 'round_product'):
        require(a.denominator == b.denominator == 1, 'Exact product operands must be integers')
        if op == 'round_product': return _round(a*b/SCALE)
        whole = Fraction((a*b)//SCALE)
        return whole if op == 'product_whole' else a*b-whole*SCALE
    raise ValidationError('Unsupported arithmetic operation: '+str(op))


def _financial_value(result, row):
    value = _path(result, row['expected_path'])
    if 'vintage_origin' not in row:
        require('vintage_field' not in row, 'A vintage field needs an origin')
        return value
    origin, field = row['vintage_origin'], row['vintage_field']
    require(type(origin) is str and date.fromisoformat(origin).isoformat() == origin,
        'A vintage origin must be an ISO date')
    fields = ('opening', 'expired', 'used', 'created', 'closing')
    require(field in fields and isinstance(value, dict) and isinstance(value.get('entries'), list),
        'The complete sparse vintage month is required')
    origins, answer = set(), 0
    for entry in value['entries']:
        require(isinstance(entry, dict) and type(entry.get('origin_month')) is str,
            'A sparse vintage entry has no origin')
        key = entry['origin_month']
        require(key not in origins and all(type(entry.get(name)) is int and entry[name] >= 0 for name in fields),
            'A sparse vintage origin is duplicated or incomplete')
        require(entry['closing'] == entry['opening']-entry['expired']-entry['used']+entry['created'],
            'The independent vintage bridge does not close')
        origins.add(key)
        if key == origin: answer = entry[field]
    return answer


def expected_values(specification, result, bindings):
    """Replay the entire definition DAG, then compare all finance to the journal."""
    require(bindings.get('binding_version') == 1, 'An explicit version-one binding is required')
    sha = canonical_sha(specification)
    require(result.get('specification_sha256') == sha and bindings.get('specification_sha256') == sha,
        'The independent journal and workbook must use the exact same specification')
    values, owners, inputs = {}, {}, {}
    def add(key, value, role):
        require(key not in values, 'A literal/input cell was bound more than once')
        values[key], owners[key] = value, role
    for row in bindings['input_bindings']:
        value = _projection(_path(specification, row['path']), row)
        key = row['sheet'], row['cell']
        require(_matches(_observed(row['stored_value']), value, row), 'A stored primitive does not round-trip')
        add(key, value, 'input')
        inputs[key] = row
    for row in bindings['literal_bindings']:
        value = row['value']
        if row['kind'] == 'date': value = _serial(value)
        elif type(value) in (int, float, Decimal): value = _number(value)
        require(value is not None and type(value) is not bool, 'Use explicit empty text and numeric flags')
        add((row['sheet'], row['cell']), value, 'literal')
    definitions = {(row['sheet'], row['cell']):row for row in bindings['arithmetic_bindings']}
    require(len(definitions) == len(bindings['arithmetic_bindings']) == bindings['formula_count'],
        'Every actual physical formula must have exactly one arithmetic definition')
    require(not set(definitions) & set(values), 'A formula overlaps a supplied literal')
    reverse, outstanding = defaultdict(list), {}
    definition_keys, provided_keys = set(definitions), set(values)
    all_keys = definition_keys | provided_keys
    for key, row in definitions.items():
        deps = _dependencies(row['expression'])
        require(deps <= all_keys, 'An arithmetic reference is not bound')
        pending = deps & definition_keys
        outstanding[key] = len(pending)
        for dependency in pending: reverse[dependency].append(key)
    ready = deque(key for key, count in outstanding.items() if count == 0)
    while ready:
        key = ready.popleft()
        values[key], owners[key] = _evaluate(definitions[key]['expression'], values), 'arithmetic'
        if isinstance(values[key], Fraction):
            require(abs(values[key]) < 2**53, 'A physical calculation exceeds the exact worksheet envelope')
        for child in reverse[key]:
            outstanding[child] -= 1
            if outstanding[child] == 0: ready.append(child)
    require(all(key in values for key in definitions), 'The full arithmetic graph contains a cycle')
    financial = {}
    for row in bindings['financial_bindings']:
        key = row['sheet'], row['cell']
        require(key in definitions and key not in financial, 'A financial binding is absent or duplicated')
        require(row['formula'] == definitions[key]['formula'] and row['expression'] == definitions[key]['expression'],
            'A financial alias does not describe the actual physical formula')
        expected = _projection(_financial_value(result, row), row)
        require(values[key] == expected, 'The independent journal disagrees with the financial definition: '+str(key))
        financial[key] = row
    require(bool(financial), 'No independent financial expectations were supplied')
    return {'values': values, 'owners': owners, 'financial': financial, 'inputs': inputs,
        'definitions': definitions, 'specification_sha256': sha}


def _observed(value):
    if value is None or value == '': return ''
    if isinstance(value, (datetime, date)): return _serial(value)
    if type(value) is bool: raise ValidationError('Physical numeric flags cannot be Excel booleans')
    return _number(value) if isinstance(value, (int, float, Decimal)) else value


def _matches(observed, expected, row=None):
    if isinstance(expected, Fraction):
        if not isinstance(observed, Fraction): return False
        if row is not None:
            scale = row.get('worksheet_scale', 1)
            if scale == 1:
                return observed == expected
            return (_round(observed*scale) == expected*scale
                and abs(observed-expected)*scale < Fraction(1, 2))
        if expected.denominator == 1: return observed == expected
        # Only unposted rational support gets this absolute representation bound.
        # Financial outputs separately satisfy their exact private posting above.
        return abs(observed-expected) <= Fraction(1, 10**9)
    return type(observed) is type(expected) and observed == expected


def audit_workbook(path, specification, result, bindings):
    """Read all actual caches and check full scope; never launch recalculation."""
    expected = expected_values(specification, result, bindings)
    path = Path(path).resolve(strict=True)
    before = path.stat()
    book = openpyxl.load_workbook(path, data_only=True, read_only=True, keep_links=False)
    failures, mismatch_count, seen, error_count = [], 0, set(), 0
    def fail(key, reason):
        nonlocal mismatch_count
        mismatch_count += 1
        if len(failures) < 50: failures.append({'sheet':key[0], 'cell':key[1], 'reason':reason})
    try:
        require(book.epoch == WINDOWS_EPOCH and book.sheetnames == bindings['sheetnames'],
            'The workbook epoch or complete worksheet order differs')
        sheet_paths = [(sheet.title, sheet._worksheet_path) for sheet in book]
        for sheet in book:
            for (row, column), cell in _sparse_cells(sheet):
                key = sheet.title, get_column_letter(column)+str(row)
                seen.add(key)
                if cell['data_type'] == 'e':
                    error_count += 1; fail(key, 'native_error'); continue
                if key not in expected['values']:
                    fail(key, 'unbound_nonempty_cell'); continue
                try:
                    binding = expected['financial'].get(key, expected['inputs'].get(key))
                    matches = _matches(_observed(cell['value']), expected['values'][key], binding)
                except ValidationError:
                    matches = False
                if not matches: fail(key, 'cached_value_mismatch')
        for key, value in expected['values'].items():
            if key not in seen and value != '': fail(key, 'missing_nonempty_cache')
    finally:
        book.close()
    with ZipFile(path) as archive:
        actual_formulas = set()
        for title, name in sheet_paths:
            address = None
            with archive.open(name) as stream:
                for event, element in ElementTree.iterparse(stream, events=('start','end')):
                    tag = element.tag.rsplit('}',1)[-1]
                    if event == 'start' and tag == 'c': address = element.attrib['r']
                    if event == 'end':
                        if tag == 'f':
                            key = title, address
                            require(key not in actual_formulas, 'A physical formula address is duplicated')
                            actual_formulas.add(key)
                        element.clear()
    actual_count = len(actual_formulas)
    require(actual_formulas == set(expected['definitions']), 'The actual physical formula positions differ')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024**2), b''): digest.update(block)
    after = path.stat()
    require((before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        == (after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
        'The actual workbook changed during audit')
    return {'passed': mismatch_count == 0, 'all_values_checked': True,
        'financial_journal_fields_checked': len(expected['financial']),
        'physical_formulas_checked': actual_count, 'expected_bound_cells': len(expected['values']),
        'observed_nonempty_cells': len(seen), 'native_error_count': error_count,
        'mismatch_count': mismatch_count, 'mismatch_examples': failures,
        'mismatch_examples_limit': 50, 'specification_sha256': expected['specification_sha256'],
        'audited_file': {'path':str(path), 'sha256':digest.hexdigest(), 'bytes':after.st_size},
        'bindings_sha256':canonical_sha(bindings), 'independent_result_sha256':canonical_sha(result),
        'recalculation_performed': False, 'source_admission_claimed': False, 'qualified': False}


def compare_typed_caches(left, right):
    """Compare the entire physical value union, without money quantization."""
    books = []
    checked = mismatches = 0
    examples = []
    def typed(cell):
        if cell is None or cell['value'] is None or cell['value'] == '': return ('empty', None)
        value = cell['value']
        if cell['data_type'] == 'e': return ('error', str(value))
        if type(value) is bool: return ('boolean', value)
        if isinstance(value, (date, datetime)): return ('date', value.isoformat())
        if isinstance(value, (int, float, Decimal)): return ('number', _number(value))
        require(type(value) is str, 'An unsupported cache type was encountered')
        return ('text', value)
    try:
        books = [openpyxl.load_workbook(path, data_only=True, read_only=True, keep_links=False)
            for path in (left, right)]
        require(books[0].sheetnames == books[1].sheetnames and books[0].epoch == books[1].epoch,
            'Typed stability requires identical worksheet order and epoch')
        for title in books[0].sheetnames:
            streams = [iter(_sparse_cells(book[title])) for book in books]
            try:
                heads = [next(stream, None) for stream in streams]
                while any(head is not None for head in heads):
                    key = min(head[0] for head in heads if head is not None)
                    pair = []
                    for index, stream in enumerate(streams):
                        if heads[index] is not None and heads[index][0] == key:
                            pair.append(typed(heads[index][1])); heads[index] = next(stream, None)
                        else: pair.append(typed(None))
                    checked += 1
                    if pair[0] != pair[1]:
                        mismatches += 1
                        if len(examples) < 25:
                            examples.append({'sheet':title, 'cell':get_column_letter(key[1])+str(key[0])})
            finally:
                for stream in streams:
                    close = getattr(stream, 'close', None)
                    if close: close()
    finally:
        for book in books: book.close()
    return {'passed':mismatches == 0, 'union_cells_checked':checked,
        'typed_value_mismatches':mismatches, 'mismatch_examples':examples,
        'money_quantization_applied':False, 'entire_value_union_checked':True,
        'recalculation_performed':False, 'qualified':False}

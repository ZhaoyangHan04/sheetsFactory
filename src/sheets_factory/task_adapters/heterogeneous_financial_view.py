"""Default-off business template projection of a fully verified native source.

The source journal is used only to check already calculated source values. This
module never executes a ledger, emitter, optimizer, model, or calculation engine.
No source formula or arithmetic support sheet enters the projected workbooks.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import importlib.util
import json
from pathlib import Path
import re

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.utils.datetime import WINDOWS_EPOCH
from openpyxl.styles.numbers import BUILTIN_FORMATS

from ..evaluation.streaming_verifier import _sparse_cells
from ..workbook.heterogeneous_contracts import spec, validate

ROOT = Path(__file__).resolve().parents[3]
SETTING = 'heterogeneous_financial_view'
ADAPTER_ID = 'heterogeneous_business_financial_view_v1'
DEFAULT_POLICY = ROOT / 'config/task_adapters/heterogeneous_financial_view_v1.json'
SOURCE_BUILDER = ROOT / 'scripts/build_heterogeneous_source.py'
SOURCE_KIND = 'independently_verified_heterogeneous_contract_source'
PENDING = ['projected_workbook_actual_normalization', 'five_local_controls', 'public_only_recovery',
           'all_12_quality_diagnostics', 'actual_Harbor_controls', 'difficulty', 'confirmation']


class ViewError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ViewError(message)


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
        ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def reference(path):
    p = Path(path).absolute()
    require(p == p.resolve() and p.is_file() and not p.is_symlink(), 'A real nonsymlink artifact is required')
    before = p.stat(); h = hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b''):
            h.update(block)
    after = p.stat()
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) ==
        (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns), 'An artifact changed while hashing')
    return {'path': str(p), 'sha256': h.hexdigest(), 'bytes': after.st_size}


def _read(path):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, 'Duplicate JSON key')
            value[key] = item
        return value
    def invalid(_):
        raise ViewError('Nonfinite JSON number')
    value = json.loads(Path(path).read_text(), object_pairs_hook=unique, parse_constant=invalid)
    require(isinstance(value, dict), 'An object artifact is required')
    return value


class _References:
    """A single live admission hashes each unchanged file once, never a JSON cache."""
    def __init__(self):
        self.files = {}
        self.signatures = {}

    def check(self, value):
        require(isinstance(value, dict) and set(value) == {'path', 'sha256', 'bytes'}
            and type(value['bytes']) is int and value['bytes'] >= 0
            and isinstance(value['sha256'], str) and re.fullmatch('[0-9a-f]{64}', value['sha256']), 'A complete file reference is required')
        p = Path(value['path']); stat = p.stat()
        signature = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if value['path'] not in self.files or self.signatures[value['path']] != signature:
            actual = reference(p)
            require(actual == value, 'A source evidence file changed')
            self.files[value['path']] = actual; self.signatures[value['path']] = signature
        require(self.files[value['path']] == value, 'Conflicting references to one source file')
        return p

    def walk(self, value):
        if isinstance(value, dict):
            if {'path', 'sha256', 'bytes'} <= set(value):
                self.check(value)
            for child in value.values(): self.walk(child)
        elif isinstance(value, list):
            for child in value: self.walk(child)

    def finish(self):
        for record in tuple(self.files.values()): self.check(record)


def policy(value=DEFAULT_POLICY):
    record = reference(value); result = _read(record['path'])
    require(type(result.get('version')) is int and result['version'] == 1
        and result.get('adapter') == ADAPTER_ID and result.get('enabled_by_default') is False,
        'The view requires its explicit version-one default-off policy')
    require(result == _read(DEFAULT_POLICY), 'Only the complete current declared business layout is supported')
    return result


def setting(*, enabled=False):
    require(type(enabled) is bool, 'The opt-in must be a boolean')
    return {'enabled': enabled, 'version': 1, 'adapter': ADAPTER_ID,
        'implementation': reference(__file__), 'policy': reference(DEFAULT_POLICY),
        'source_builder': reference(SOURCE_BUILDER)}


def public_brief():
    return ('Complete the labelled monthly business forecasts for all supplied entities, facilities, assets and '
        'three scenarios, including the group statements and tax-attribute schedules. Use the supplied assumptions '
        'and Contract Notes without changing their policies. Fill every applicable forecast result, including zero '
        'amounts and numeric 0/1 states. Retain the policy-defined blank covenant ratios and test results where '
        'not applicable. Units are stated beside each account; provided identifiers, dates and assumptions are fixed. '
        'Keep the worksheet names and order, preserve supplied literals and unrelated blanks, and do not add '
        'worksheets or helper cells. Read /app/input.xlsx and save /app/output.xlsx. Values are checked after '
        'LibreOffice recalculation.')


def _builder():
    definition = importlib.util.spec_from_file_location('_heterogeneous_view_bound_source_builder', SOURCE_BUILDER)
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


def _load_source(value):
    graph = _References()
    original = value if isinstance(value, dict) else reference(value)
    source = _read(graph.check(original))
    require(source.get('kind') == SOURCE_KIND and type(source.get('version')) is int and source['version'] == 1
        and source.get('status') == 'source_verified_not_task_quality_or_difficulty_qualified',
        'A completed independently verified native source is required; offline probes are not source certificates')
    require({'source_preparation','source_recipe_sha256','source_recipe_digest','private_specification',
        'original_specification','specification_sha256','scope','runtime_profile','bindings','independent_ledger',
        'geometry','mechanism_coverage','financial_audits','stability','engine_calls','actual_LO_recalculations',
        'workbook','local_path','runtime'} <= set(source), 'Actual source evidence is incomplete')
    graph.walk(source)
    builder = _builder()
    prepared, public = builder.validate_prepared(graph.check(source['source_preparation']))
    require(source['source_recipe_sha256'] == prepared['recipe'] == builder.recipes()
        and source['source_recipe_digest'] == prepared['recipe_sha256'] == canonical(prepared['recipe']), 'The exact source recipe changed')
    require(source['private_specification'] == prepared['private_specification']
        and source['original_specification'] == prepared['original_specification']
        and source['specification_sha256'] == prepared['specification_sha256'] == spec.canonical_sha256(public)
        and source['scope'] == prepared['scope'], 'The source primitives or complete scope changed')
    require(source['runtime_profile'] == prepared['runtime_profile'], 'The source resource profile changed')
    bindings = _read(graph.check(source['bindings'])); forward = _read(graph.check(source['independent_ledger']))
    require(bindings.get('specification_sha256') == forward.get('specification_sha256') == source['specification_sha256'], 'The independent journal is for another source')
    require(builder.mechanism_coverage(forward) == _read(graph.check(source['mechanism_coverage'])), 'Dated source regimes or feasibility changed')
    shape = _read(graph.check(source['geometry']))
    require(shape.get('kind') == 'complete_heterogeneous_source_geometry' and shape.get('truncated') is False
        and shape['physical_formula_count'] == bindings['formula_count']
        and shape['all_financial_bindings'] == len(bindings['financial_bindings'])
        and shape['complete_scope'] == bindings['complete_scope'], 'Complete geometry is required')
    calls, audits = source['engine_calls'], source['financial_audits']
    require(len(calls) == len(audits) == source['actual_LO_recalculations'] == 3, 'Three actual source calculations and three full audits are required')
    outputs = []
    for index, (call, audit_ref) in enumerate(zip(calls, audits), 1):
        require(type(call.get('index')) is int and call['index'] == index and call.get('completed') is True,
            'An actual source pass is missing or incomplete')
        if outputs: require(call['input'] == outputs[-1], 'Actual source passes do not form the declared chain')
        evidence = call['actual_resource_evidence']
        require(builder.validate_actual_call(call, evidence['terminal'], prepared) == evidence,
            'An actual source resource chain differs')
        terminal = _read(graph.check(call['terminal_receipt']))
        require(terminal == {k: v for k, v in call.items() if k != 'terminal_receipt'}, 'A source pass terminal receipt changed')
        started = _read(graph.check(call['started_receipt']))
        require(started['index'] == index and started['input'] == call['input']
            and started['destination'] == call['destination'] and started['completed'] is False, 'A source pass started receipt differs')
        builder._audit_pass(_read(graph.check(audit_ref)), graph.check(call['output']), bindings, forward, public)
        require(_read(graph.check(audit_ref))['expected_bound_cells'] == shape['defined_graph_cells'],
            'A source audit does not cover the complete declared cell graph')
        outputs.append(call['output'])
    require(source['workbook'] == outputs[0] and source['local_path'] == outputs[0]['path'], 'The selected workbook is not the first fully audited source pass')
    stable = _read(graph.check(source['stability']))
    require(stable.get('kind') == 'three_actual_pass_full_typed_stability'
        and stable.get('money_quantization_applied') is False and len(stable.get('comparisons', [])) == 2,
        'Two complete typed comparisons are required')
    for record, right in zip(stable['comparisons'], outputs[1:]):
        result = record['comparison']
        require(record['left'] == outputs[0] and record['right'] == right and result.get('passed') is True
            and result.get('entire_value_union_checked') is True and result.get('money_quantization_applied') is False
            and result.get('typed_value_mismatches') == 0 and result.get('union_cells_checked', 0) > 0,
            'A complete actual typed stability comparison is absent')
    runtime = source['runtime']
    require(runtime['role'] == 'source' and runtime['network'] == 'none' and runtime['actual_calculation_calls_recorded'] == 3
        and runtime['actual_resource_receipts'] == [c['actual_resource_evidence']['terminal'] for c in calls]
        and runtime['image_id'] == prepared['runtime_profile_value']['image']['id'], 'Runtime receipts do not bind the three actual source passes')
    graph.finish()
    proof = {'kind': 'checked_heterogeneous_business_view_source', 'version': 1, 'source_manifest': original,
        'workbook': source['workbook'], 'public_specification': source['private_specification'],
        'bindings': source['bindings'], 'independent_ledger': source['independent_ledger'],
        'financial_audits': audits, 'stability': source['stability'], 'engine_calls': calls,
        'runtime_profile': source['runtime_profile'], 'source_recipe_sha256': source['source_recipe_sha256'],
        'verified_artifacts': deepcopy(graph.files), 'qualified': False}
    return proof, public, bindings, forward, graph


def validate_source(value):
    """Cold read-only admission; never runs financial forwards or Calc."""
    return _load_source(value)[0]


def _logical(row):
    return (tuple(row['expected_path']), row.get('vintage_origin'), row.get('vintage_field'))


def select_business_bindings(bindings, *, layout_policy=DEFAULT_POLICY):
    """Structural selection only. Its result is not a verified source or a view."""
    declared = policy(layout_policy)
    primary, support, coordinates = {}, [], set()
    for row in bindings['financial_bindings']:
        coordinate = row['sheet'],row['cell']
        require(coordinate not in coordinates, 'Duplicate physical financial alias')
        coordinates.add(coordinate)
        match = re.fullmatch(r'(S\d{2}) (.+)', row['sheet'])
        if match and match[2] in declared['source_reports'] and re.fullmatch(r'D[1-9]\d*', row['cell']):
            key = _logical(row)
            require(key not in primary, 'Duplicate primary financial logical path')
            require(row['kind'] in declared['target_kinds'] + declared['omitted_metadata_kinds'], 'Unknown business projection kind')
            require(type(row.get('worksheet_scale')) is int and row['worksheet_scale'] == {'money_pence':100,'rate_p12':10**12,
                'nullable_ratio_micro':10**6,'flag':1,'nullable_flag':1,'integer':1,'date':1,'text':1}[row['kind']],
                'A primary business alias has the wrong declared unit')
            primary[key] = row
        else:
            require(match and match[2] == 'Calculations' and re.fullmatch(r'B[1-9]\d*', row['cell']),
                'An unknown financial alias cannot be silently dropped')
            support.append(row)
    require(bool(primary), 'No native primary financial aliases exist')
    targets = [deepcopy(row) for row in primary.values() if row['kind'] in declared['target_kinds']]
    metadata = [deepcopy(row) for row in primary.values() if row['kind'] in declared['omitted_metadata_kinds']]
    totals = []
    for row in support:
        if _logical(row) in primary: continue
        p = row['expected_path']
        require(len(p) == 7 and p[:1] == ['scenarios'] and p[2] in declared['queue_total_aliases']
            and p[4] == 'monthly' and p[6] in declared['queue_total_aliases'][p[2]]
            and row['kind'] == 'money_pence' and row['worksheet_scale'] == 1,
            'An unpaired source financial field needs an explicit business scope rule')
        entity_field = declared['queue_total_aliases'][p[2]][p[6]]
        key = (tuple(['scenarios', p[1], 'entities', p[3], 'monthly', p[5], entity_field]), None, None)
        require(key in primary and primary[key]['kind'] == 'money_pence'
            and primary[key]['worksheet_scale'] == 100, 'A FIFO total has no declared business account alias')
        totals.append({'total': deepcopy(row), 'business_alias': deepcopy(primary[key]),
            'reason': 'Same legal-account amount already included in the entity business forecast; not a separate economic target.'})
    return {'targets': targets, 'omitted_metadata': metadata, 'explicit_queue_total_aliases': totals,
        'counts': {'primary_aliases': len(primary), 'business_targets': len(targets),
            'omitted_metadata': len(metadata), 'queue_total_aliases': len(totals),
            'target_kinds': dict(Counter(r['kind'] for r in targets))},
        'selection_consults_values': False, 'source_or_quality_certificate': False}


def _typed(value):
    if value is None or value == '': return ['empty', None]
    require(type(value) is not bool, 'Numeric public states cannot be Excel booleans')
    if isinstance(value, datetime): return ['datetime', value.isoformat()]
    if isinstance(value, date): return ['date', value.isoformat()]
    if isinstance(value, (int, float, Decimal)):
        n = Decimal(str(value)); require(n.is_finite(), 'A finite public value is required')
        return ['number', str(n)]
    require(type(value) is str, 'Unsupported public literal type')
    require('/data/' not in value and 'file://' not in value, 'Private paths cannot enter the business view')
    if value.lstrip().startswith(('{', '[')):
        try: parsed = json.loads(value)
        except ValueError: parsed = None
        require(not isinstance(parsed, (dict, list)), 'Prejoined JSON cannot enter the business view')
    return ['text', value]


def _untyped(value):
    kind, raw = value
    if kind == 'empty': return None
    if kind == 'number':
        n = Decimal(raw); return int(n) if n == n.to_integral_value() else float(n)
    if kind == 'datetime': return datetime.fromisoformat(raw)
    if kind == 'date': return date.fromisoformat(raw)
    require(kind == 'text', 'Unknown projected type')
    return raw


_IS = set('revenue cash_opex ebitda depreciation ebit interest_accrual current_tax_expense net_income'.split())
_COV = set('cfads mandatory_debt_service dscr_window_cfads dscr_window_debt_service test_applicable test_pass dscr_ratio_millionths trap_open trap_operative trap_next facility_closed_open facility_closed_next cure_open cure_next feasible'.split())
_TAX = set('tax_payable_open eligible_current_interest interest_capacity interest_carry_open interest_expired interest_old_used interest_current_allowed interest_denied_created interest_carry_close taxable_before_losses loss_open loss_expired loss_used loss_created loss_close taxable_after_losses'.split())
_DEBT = set('principal_open scheduled_principal local_margin_principal shared_margin_principal voluntary_principal bank_draw interest_payable_open lp_call lp_called_cumulative funding_gap'.split())
_BS = set('cash_close reserve_close asset_nbv_open asset_nbv_close principal_close interest_payable_close tax_payable_close total_assets total_liabilities total_equity paid_in_close retained_close'.split())
_EQUITY = set('paid_in_open retained_open distribution return_of_capital profit_distribution'.split())


def _label(field):
    special = {'annual_rate_p12':'Effective annual interest rate', 'dscr_ratio_millionths':'Debt-service coverage ratio',
        'trap_open':'Restriction at month opening', 'trap_operative':'Restriction applying this month',
        'trap_next':'Restriction at next month opening', 'cure_open':'Observed cure passes at opening',
        'cure_next':'Observed cure passes at next opening', 'test_applicable':'Covenant test applies',
        'test_pass':'Covenant test passed', 'facility_closed_open':'Facility closed at opening',
        'facility_closed_next':'Facility closed at next opening', 'recast_due':'Principal instalment reset applies',
        'recast_instalment':'Reset principal instalment', 'day_basis':'Interest day-count denominator',
        'coupon_due':'Cash coupon due', 'days':'Actual days in month'}
    if field in special: return special[field]
    return field.replace('_check', ' reconciliation').replace('_', ' ').capitalize()


def _unit(row):
    kind = row['kind']
    return {'money_pence':('GBP','#,##0.00;[Red](#,##0.00);0.00'),
        'flag':('0/1','0'),'nullable_flag':('0/1 or policy blank','0'),
        'nullable_ratio_micro':('times or policy blank','0.000000'),
        'integer':('days' if row['expected_path'][-1] in ('days','day_basis') else 'count','0'),
        'rate_p12':('annual rate','0.0000%')}[kind]


def _identity(row, public):
    p = row['expected_path']; require(p[0] == 'scenarios' and p[1] in public['scenario_ids'], 'Unknown scenario identity')
    if p[2] == 'group_monthly':
        require(len(p) == 5 and type(p[3]) is int and 0 <= p[3] < len(public['months']), 'Invalid group financial path')
        return p[1], 'Group', 'Group', p[3], p[4], None
    require(len(p) in (6,7) and p[4] == 'monthly' and type(p[5]) is int
        and 0 <= p[5] < len(public['months']), 'Invalid monthly business identity')
    domain, entity, t = p[2], p[3], p[5]
    ids = {'entities':[e['id'] for e in public['entities']], 'loans':[l['id'] for l in public['loans']],
        'assets':[a['id'] for a in public['assets']], 'interest_vintages':[e['id'] for e in public['entities']],
        'loss_vintages':[e['id'] for e in public['entities']]}
    require(domain in ids and entity in ids[domain], 'A forecast identity is not supplied publicly')
    if domain in ('interest_vintages','loss_vintages'):
        require(len(p) == 6 and row.get('vintage_field') in ('opening','expired','used','created','closing')
            and isinstance(row.get('vintage_origin'),str), 'A complete public vintage identity is required')
        origin = row['vintage_origin']
        require(date.fromisoformat(origin).isoformat() == origin, 'A vintage origin must be an explicit public month')
        entity_record = next(e for e in public['entities'] if e['id'] == entity)
        attribute = 'opening_interest_carry' if domain == 'interest_vintages' else 'opening_tax_losses'
        require(origin in set(public['months']) | {v['origin_month'] for v in entity_record[attribute]},
            'A forecast origin is absent from the raw public calendar and opening attributes')
        return p[1], 'Interest Carry' if domain == 'interest_vintages' else 'Loss Carry', entity, t, row['vintage_field'], row['vintage_origin']
    field = p[6]
    if domain == 'assets': view = 'Assets'
    elif domain == 'loans': view = 'Debt'
    elif field in _COV: view = 'Covenants'
    elif field in _TAX: view = 'Tax'
    elif field in _DEBT: view = 'Debt'
    else: view = 'Statements'
    return p[1], view, entity, t, field, None


def _check_nullable_policy(public, forward):
    """Reject ambiguity in the stated business blank encodings, including zero."""
    for sid in public['scenario_ids']:
        for entity in public['entities']:
            rows = forward['scenarios'][sid]['entities'][entity['id']]['monthly']
            require(len(rows) == len(public['months']), 'The complete covenant calendar is required')
            for row in rows:
                applies, passed, ratio = row['test_applicable'],row['test_pass'],row['dscr_ratio_millionths']
                require(type(applies) in (bool,int) and applies in (0,1), 'A covenant applicability state is invalid')
                if not applies:
                    require(passed is None and ratio is None, 'Both non-test covenant displays must be blank')
                elif row['dscr_window_debt_service'] == 0:
                    require(ratio is None and type(passed) in (bool,int)
                        and passed == int(row['dscr_window_cfads'] >= 0),
                        'A zero-service test has a blank ratio and a real cash-flow-based pass result')
                else:
                    require(type(passed) in (bool,int) and passed in (0,1) and type(ratio) is int,
                        'An applicable nonzero-service covenant result cannot be blank')


def _place_targets(rows, public):
    """Pure public identity/layout planning; no values or source caches consulted."""
    positions, group_rows, next_rows = [], {}, {}
    for row in rows:
        sid, view, identity, t, field, origin = _identity(row,public)
        sheet = sid+' '+view
        if origin is None:
            category = 'Facility' if row['expected_path'][2] == 'loans' else (
                'Income statement' if field in _IS else 'Balance sheet' if field in _BS else
                'Equity' if field in _EQUITY else 'Reconciliations' if field.endswith('_check') else view)
            key = sheet,identity,category,field
            if key not in group_rows:
                group_rows[key] = next_rows.get(sheet,4);next_rows[sheet] = group_rows[key]+1
            rr,cc = group_rows[key],5+t
            descriptors = [identity,category,_label(field),_unit(row)[0]]
        else:
            key = sheet,identity,origin,t
            if key not in group_rows:
                group_rows[key] = next_rows.get(sheet,4);next_rows[sheet] = group_rows[key]+1
            rr,cc = group_rows[key],4+('opening','expired','used','created','closing').index(field)
            descriptors = [identity,origin,public['months'][t]]
        positions.append({'source':deepcopy(row),'sheet':sheet,'cell':get_column_letter(cc)+str(rr),
            'descriptor_row':rr,'descriptors':descriptors,'number_format':_unit(row)[1]})
    require(len({(r['sheet'],r['cell']) for r in positions}) == len(positions), 'A business output position is duplicated')
    return positions


def _cached_source(path, raw_sheets, positions, alias_pairs, forward):
    """Only source caches that already passed all three source audits are used."""
    wanted = {(r['source']['sheet'],r['source']['cell']):r['source'] for r in positions}
    for pair in alias_pairs:
        for row in (pair['total'],pair['business_alias']): wanted[row['sheet'],row['cell']] = row
    wanted_sheets = {key[0] for key in wanted}
    observed, inputs = {}, []
    book = openpyxl.load_workbook(path,read_only=True,data_only=True,keep_links=False)
    try:
        require(book.epoch == WINDOWS_EPOCH, 'The source uses an unsupported date epoch')
        for sheet in book:
            if sheet.title not in raw_sheets and sheet.title not in wanted_sheets: continue
            for (r,c),cell in _sparse_cells(sheet):
                key = sheet.title,get_column_letter(c)+str(r)
                require(cell['data_type'] != 'e', 'An audited source contains a native error')
                if sheet.title in raw_sheets:
                    style = book._cell_styles[cell['style_id']]
                    format_id = style.numFmtId
                    number_format = BUILTIN_FORMATS.get(format_id) if format_id < 164 else book._number_formats[format_id-164]
                    inputs.append({'sheet':sheet.title,'cell':key[1],'value':_typed(cell['value']),
                        'number_format':number_format})
                if key in wanted: observed[key] = cell['value']
        for key,row in wanted.items():
            value = observed.get(key)
            expected = validate._projection(validate._financial_value(forward,row),row)
            require(validate._matches(validate._observed(value),expected,row), 'A selected actual source cache differs from its independently audited business posting')
        for pair in alias_pairs:
            require(validate._financial_value(forward,pair['total']) == validate._financial_value(forward,pair['business_alias']),
                'A declared queue total is not the same legal account as its entity business alias')
    finally: book.close()
    for row in positions:
        value = observed.get((row['source']['sheet'],row['source']['cell']))
        # Preserve the actual business posting, normalizing its declared display
        # precision; no internal pence, quotient or remainder is made public.
        if value is not None and value != '' and row['source']['kind'] in ('money_pence','nullable_ratio_micro'):
            places = Decimal('0.01') if row['source']['kind'] == 'money_pence' else Decimal('0.000001')
            value = Decimal(str(value)).quantize(places,rounding=ROUND_HALF_UP)
        row['reference_value'] = _typed(value)
    return inputs


def build_view_plan(source_manifest, *, enabled=False, layout_policy=DEFAULT_POLICY):
    require(enabled is True, 'The heterogeneous business view is default off')
    declared = policy(layout_policy)
    proof,public,bindings,forward,graph = _load_source(source_manifest)
    _check_nullable_policy(public,forward)
    require(not any(r['sheet'] in declared['input_sheets'] for r in bindings['arithmetic_bindings']),
        'The raw input/notes sheets cannot contain formula answers or conversions')
    selection = select_business_bindings(bindings,layout_policy=layout_policy)
    positions = _place_targets(selection['targets'],public)
    inputs = _cached_source(proof['workbook']['path'],declared['input_sheets'],positions,selection['explicit_queue_total_aliases'],forward)
    require(set(r['sheet'] for r in inputs) == set(declared['input_sheets']), 'A complete native public input/notes sheet is absent')
    graph.finish()
    view = {'kind':'planned_heterogeneous_business_financial_view','version':1,'adapter':ADAPTER_ID,
        'source_admission':proof,'setting':setting(enabled=True),'months':list(public['months']),
        'scenario_ids':list(public['scenario_ids']),'sheet_order':declared['input_sheets']+
            [sid+' '+name for sid in public['scenario_ids'] for name in declared['forecast_views']],
        'provided_cells':inputs,'forecast_targets':positions,'declared_slot_count':len(positions),
        'scope_counts':selection['counts'],'omitted_future_term_ids_and_metadata':selection['omitted_metadata'],
        'queue_total_same_account_alias_evidence':selection['explicit_queue_total_aliases'],
        'selection_consults_values':False,'original_brief':public_brief(),'pending':PENDING,
        'quality_or_difficulty_certified':False,'actual_projection_LO_calls':0}
    view['plan_sha256'] = canonical(view)
    return view


def _book_from_plan(plan, *, masked):
    """Low-level writer. Public production callers must use materialize_view."""
    book = openpyxl.Workbook();book.remove(book.active);book.epoch=WINDOWS_EPOCH
    for title in plan['sheet_order']: book.create_sheet(title)
    for row in plan['provided_cells']:
        cell = book[row['sheet']][row['cell']];cell.value=_untyped(row['value'])
        if row['value'][0] == 'text': cell.data_type = 's'
        if row.get('number_format'):cell.number_format=row['number_format']
    for sid in plan['scenario_ids']:
        for title in [s for s in plan['sheet_order'] if s.startswith(sid+' ')]:
            sheet=book[title];sheet.cell(1,1,title+' — monthly business forecast')
            if title.endswith(('Interest Carry','Loss Carry')):
                headers=['Entity','Origin month','Forecast month','Opening GBP','Expired GBP','Used GBP','Created GBP','Closing GBP']
            else: headers=['Entity / facility / asset','Statement / schedule','Account','Unit',*[datetime.fromisoformat(m) for m in plan['months']]]
            for c,value in enumerate(headers,1):
                cell=sheet.cell(3,c,value)
                if isinstance(value,datetime):cell.number_format='mmm-yy'
            sheet.freeze_panes='E4'
    written = {}
    for row in plan['forecast_targets']:
        sheet=book[row['sheet']]
        row_key = row['sheet'],row['descriptor_row']
        if row_key in written:
            require(written[row_key] == row['descriptors'], 'Inconsistent public descriptors for a forecast row')
        else:
            written[row_key] = row['descriptors']
            for c,value in enumerate(row['descriptors'],1):
                if row['sheet'].endswith(('Interest Carry','Loss Carry')) and c in (2,3):
                    value=datetime.fromisoformat(value)
                cell=sheet.cell(row['descriptor_row'],c,value)
                if isinstance(value,datetime):cell.number_format='mmm-yy'
        cell=sheet[row['cell']];cell.number_format=row['number_format']
        if not masked:cell.value=_untyped(row['reference_value'])
    return book


def validate_view(plan, input_path, goal_path):
    """Check the entire written value union, public literals and masked scope.

    This is a projection check, not actual recalculation, task controls or QA.
    Source admission must already bind the exact plan before materialization.
    """
    counts = {}
    for masked,path in ((True,input_path),(False,goal_path)):
        expected = _book_from_plan(plan,masked=masked)
        observed = openpyxl.load_workbook(path,read_only=True,data_only=False,keep_links=True)
        try:
            require(observed.sheetnames == expected.sheetnames and observed.epoch == expected.epoch
                and not observed.defined_names and not getattr(observed,'_external_links',[]),
                'Projected worksheet structure, epoch or private metadata differs')
            checked = 0
            for sheet in observed:
                actual = {}
                for (r,c),cell in _sparse_cells(sheet):
                    require(cell['data_type'] not in ('f','e'), 'Business views must contain no formula/helper/cache or error cells')
                    if cell['value'] is not None and cell['value'] != '': actual[get_column_letter(c)+str(r)] = _typed(cell['value'])
                wanted = {c.coordinate:_typed(c.value) for c in expected[sheet.title]._cells.values() if c.value is not None and c.value != ''}
                require(actual == wanted, 'A projected forecast, provided literal, unrelated blank or private helper differs')
                checked += len(wanted)
            counts['input' if masked else 'goal'] = checked
        finally:
            expected.close();observed.close()
    nonempty = sum(r['reference_value'][0] != 'empty' for r in plan['forecast_targets'])
    return {'passed':True,'whole_value_union_checked':True,'declared_business_slots':len(plan['forecast_targets']),
        'expected_changed_value_count_before_actual_normalization':nonempty,'checked_nonempty_values':counts,
        'reference_values_are_constants':True,'actual_LO_calls':0,'source_or_quality_certified':False}


def materialize_view(plan, output, *, enabled=False):
    require(enabled is True, 'Materialization is default off and requires explicit authorization')
    require(isinstance(plan,dict) and plan.get('kind')=='planned_heterogeneous_business_financial_view', 'A complete checked view plan is required')
    checked=build_view_plan(plan['source_admission']['source_manifest'],enabled=True)
    require(checked==plan, 'A planned target, source, reference value or recipe changed')
    out=Path(output).absolute()
    require(out==out.resolve() and out.is_relative_to(ROOT/'outputs') and not out.exists(), 'Use a fresh private outputs directory')
    (out/'public').mkdir(parents=True);(out/'private').mkdir()
    for masked,path in [(True,out/'public/input.xlsx'),(False,out/'private/goal.xlsx')]:
        book=_book_from_plan(plan,masked=masked)
        try:book.save(path)
        finally:book.close()
    (out/'public/instruction.md').write_text(plan['original_brief'])
    projection_audit = validate_view(plan,out/'public/input.xlsx',out/'private/goal.xlsx')
    return {'kind':'materialized_heterogeneous_business_view_pending_task_checks','version':1,
        'input':reference(out/'public/input.xlsx'),'goal':reference(out/'private/goal.xlsx'),
        'instruction':reference(out/'public/instruction.md'),'source_admission':plan['source_admission'],
        'plan_sha256':plan['plan_sha256'],'declared_slot_count':plan['declared_slot_count'],
        'projection_audit':projection_audit,'pending':PENDING,'quality_or_difficulty_certified':False,'actual_LO_calls':0}

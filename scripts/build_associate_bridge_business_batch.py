#!/usr/bin/env python3
"""Engineer a frozen investment-policy case before any solver attempt."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from openpyxl import load_workbook
from openpyxl.utils.cell import get_column_letter
from sheets_factory.core.audit import AuditStore
from sheets_factory.dashboard.server import DashboardServer
from sheets_factory.evaluation.streaming_verifier import _sparse_cells, normalize
from sheets_factory.evaluation.thread_capped_harbor_export import export_resource_harbor, inspect_resource_export
from sheets_factory.workbook.associate_bridge_v1 import spec, oracle_a, oracle_b, excel
from sheets_factory.workbook.operating_reports_200 import factory_fm_scaling
from sheets_factory.workbook.thread_capped_resource_engine import ThreadCappedResourceLibreOfficeEngine

PROFILE = ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard', 'tool_budget_seconds': 1800, 'elapsed_guard_seconds': 14400}
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
RID = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id'


def require(value, message):
    if not value:
        raise ValueError(message)


def ref(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file(), 'Use a real evidence file')
    raw = path.read_bytes()
    return {'path': str(path), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}


def read(record):
    if isinstance(record, (str, Path)):
        record = ref(record)
    require(ref(record['path']) == record, 'A frozen artifact changed')
    return json.loads(Path(record['path']).read_text())


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False); stream.write('\n')
    return ref(path)


def recipes():
    return [ref(p) for p in (__file__, spec.__file__, oracle_a.__file__, oracle_b.__file__, excel.__file__)]


def scan(path, *, formulas=False):
    book = load_workbook(path, read_only=True, data_only=not formulas, keep_links=False)
    typed, numeric, definitions, errors, literal = {}, {}, {}, [], {}
    try:
        names = book.sheetnames
        for sheet in book:
            for _, cell in _sparse_cells(sheet):
                point = sheet.title+'!'+get_column_letter(cell['column'])+str(cell['row'])
                value = cell['value']
                if cell['data_type'] == 'f':
                    definitions[point] = value
                elif cell['data_type'] == 'e':
                    errors.append(point); typed[point] = ['error', value]
                else:
                    item = list(normalize(value))
                    if item[0] != 'empty':
                        typed[point] = item
                        if isinstance(value, (float, int, Decimal)) and not isinstance(value, bool):
                            numeric[point] = str(value)
                            literal[point] = ['number', str(Decimal(str(value)).normalize())]
                        else:
                            literal[point] = item
        return {'sheetnames': names, 'typed': typed, 'raw_numeric': numeric,
                'formulas': definitions, 'errors': errors, 'literals': literal}
    finally:
        book.close()


def difference(left, right):
    return sorted(p for p in left.keys() | right.keys() if left.get(p, ['empty', None]) != right.get(p, ['empty', None]))


def compare_oracles(A, B):
    for key in ('economic_exact_values', 'raw_cell_exact_values', 'typed_2dp_values'):
        require(A[key] == B[key], 'Independent full-scope oracles disagree: '+key)
    require(A['reconciliation_checks']['passed'] is B['reconciliation_checks']['passed'] is True,
            'Both independent business ledgers must reconcile')
    return {'passed': True, 'full_financial_fields': len(A['typed_2dp_values']),
            'complete_economic_raw_and_primary_values_equal': True}


def audit_source(observed, definition, expected, bindings):
    require(not observed['errors'] and observed['sheetnames'] == definition['sheetnames'],
            'The native source contains errors or changed sheets')
    require(all(observed['literals'].get(p) == value for p, value in definition['literals'].items()),
            'The native source changed a given literal')
    require(set(observed['typed']) == set(definition['literals']) | set(definition['formulas']),
            'The native source omitted or added cells')
    mismatches, boundary = [], []
    for semantic, wanted in expected['typed_2dp_values'].items():
        b = bindings['financial'][semantic]; point = b['sheet']+'!'+b['cell']
        actual = observed['typed'].get(point, ['empty', None])
        target = ['bool' if wanted['type'] == 'boolean' else wanted['type'], wanted['value']]
        if actual == target:
            continue
        exact = expected['raw_cell_exact_values'][semantic]
        # Preserve small numeric boundary observations. Reference values are
        # actual LO values; a new business-failure gate excludes these cases.
        if actual[0] == wanted['type'] == 'number' and exact['kind'] == 'rational':
            with localcontext() as context:
                context.prec = 90
                q = Fraction(exact['value']); want = Decimal(q.numerator)/Decimal(q.denominator)
                got = Decimal(observed['raw_numeric'][point])
                allowance = max(Decimal('1e-12'), abs(want)*Decimal('2e-13'))
                if abs(want-got) <= allowance:
                    boundary.append({'point': point, 'independent_primary': target,
                        'native_primary': actual, 'raw_error': str(abs(want-got)), 'allowance': str(allowance)})
                    continue
        mismatches.append({'point': point, 'expected': target, 'actual': actual})
    require(not mismatches, 'Full independent source audit failed: '+str(mismatches[:8]))
    return {'passed': True, 'all_financial_fields_checked': len(expected['typed_2dp_values']),
            'complete_given_literals_checked': len(definition['literals']), 'native_errors': [],
            'raw_numeric_tolerance': {'absolute': '1e-12', 'relative': '2e-13'},
            'primary_boundary_observations': boundary, 'unresolved_mismatches': mismatches,
            'boundary_observations_do_not_supply_business_failure_evidence': True}


def plan(public, bindings, definition, mode):
    variant = public['case_id']+('-FM' if mode == 'financial_modeling' else '-DBG')
    result = {'variant_id': variant, 'mode': mode, 'source_case': public['case_id'],
              'given_facts_and_policies_protected': True}
    if mode == 'financial_modeling':
        result['mask_points'] = sorted(definition['formulas'])
        return result
    entities = {e['id']: e for e in public['base']['entities']}
    facts = bindings['provided_facts']; financial = bindings['financial']; faults = {}
    def cell(record):
        from openpyxl.utils import quote_sheetname
        return quote_sheetname(record['sheet'])+'!'+record['cell']
    for semantic, b in financial.items():
        identity, period, field = semantic.split('/')
        if identity not in entities or not period.startswith(('2026', '2027')):
            continue
        e = entities[identity]
        r = lambda name: cell(financial[identity+'/'+period+'/'+name])
        if field == 'associate_income':
            wrong = cell(facts[identity+'/associate_results/'+period])
        elif field == 'current_tax':
            scale = {'fraction': 1, 'percent_units': 100, 'basis_points': 10000}[e['rate_unit']]
            wrong = 'MAX(0,'+r('pretax_before_associate')+')*'+cell(facts[identity+'/parent_tax_rate'])+f'/{scale}'
        elif field == 'operating_cash_flow':
            wrong = r('net_income')+'-'+r('associate_income')
        elif field == 'closing_investment':
            from sheets_factory.workbook.operating_reports_200.schema import QUARTERS
            prior = QUARTERS[QUARTERS.index(period)-1]
            wrong = cell(financial[identity+'/'+prior+'/'+field])+'+'+r('associate_income')
        else:
            continue
        point = b['sheet']+'!'+b['cell']
        if '='+wrong != definition['formulas'][point]:
            faults[point] = {'semantic_key': semantic, 'family': field, 'faulty_formula': '='+wrong}
    result['faults'] = faults
    result['injected_formula_count'] = len(faults)
    result['actual_primary_difference_pending'] = True
    return result


def emit_input(goal, definition, frozen_plan, output):
    edits = {}; mode = frozen_plan['mode']
    points = frozen_plan['mask_points'] if mode == 'financial_modeling' else frozen_plan['faults']
    for point in points:
        sheet, address = point.rsplit('!', 1); edits.setdefault(sheet, {})[address] = point
    seen = set()
    with ZipFile(goal) as incoming:
        rels = {e.attrib['Id']: e.attrib['Target'].lstrip('/') for e in ET.fromstring(incoming.read('xl/_rels/workbook.xml.rels'))}
        parts = {}
        for s in ET.fromstring(incoming.read('xl/workbook.xml')).find(NS+'sheets'):
            part = rels[s.attrib[RID]]; part = part if part.startswith('xl/') else 'xl/'+part
            parts[part] = s.attrib['name']
        with ZipFile(output, 'x', ZIP_DEFLATED) as outgoing:
            for name in incoming.namelist():
                raw = incoming.read(name); sheet = parts.get(name)
                if sheet in edits:
                    tree = ET.fromstring(raw)
                    for cell in tree.iter(NS+'c'):
                        point = edits[sheet].get(cell.attrib.get('r'))
                        if point is None:
                            continue
                        formula = cell.find(NS+'f')
                        require(formula is not None and '='+formula.text == definition['formulas'][point],
                                'A planned formula differs from the native healthy source')
                        seen.add(point)
                        for child in list(cell):
                            if child.tag == NS+'v' or mode == 'financial_modeling' and child.tag == NS+'f':
                                cell.remove(child)
                        if mode == 'debugging':
                            formula.text = frozen_plan['faults'][point]['faulty_formula'][1:]
                        cell.attrib.pop('t', None)
                    raw = ET.tostring(tree, encoding='utf-8', xml_declaration=True)
                outgoing.writestr(name, raw)
    require(seen == set(points), 'Every declared mask or formula edit must be emitted exactly once')


def build(raw_manifest, case_id, output, *, port=0):
    output = Path(output).absolute()
    require(not output.exists() and output == output.resolve(), 'Use a new immutable engineering directory')
    audit = AuditStore(output, {'id': output.name, 'status': 'running', 'stage': 'independent_business_ledgers', 'target_count': 2})
    server = DashboardServer(audit.snapshot, audit.events, port=port); url = server.start()
    print(json.dumps({'dashboard_url': url}), flush=True); audit.update_run(dashboard_url=url)
    write(output/'dashboard.json', {'url': url})
    started = time.monotonic(); recipe = recipes()
    try:
        cohort_ref = ref(raw_manifest); cohort = read(cohort_ref)
        require(cohort['fixed_before_financial_oracle_and_model'] is True and len(cohort['cases']) == 8,
                'Freeze all eight public cases before financial forwards')
        case = next(row for row in cohort['cases'] if row['case_id'] == case_id)
        public = spec.validate(read(case['specification']))
        A, B = oracle_a.solve(public), oracle_b.solve(public)
        crosscheck = compare_oracles(A, B)
        records = {'A': write(output/'private/oracle_A.json', A), 'B': write(output/'private/oracle_B.json', B),
                   'independent_comparison': write(output/'private/independent_comparison.json', crosscheck)}
        emission = excel.emit(public, output/'private/emission')
        write(output/'private/emission_receipt.json', emission)
        bindings = read(emission['bindings']); cold = output/'private/emission/source_uncalculated.xlsx'
        definition = scan(cold, formulas=True)
        require(len(definition['formulas']) == 88676 and not definition['errors'], 'Require the complete healthy formula inventory')
        write(output/'private/cold_definition.json', definition)
        current = cold; previous = None; calls = []
        for index in (1, 2, 3):
            audit.update_run(stage='native_source_'+str(index)); audit.emit('source.native_started', index=index)
            engine = ThreadCappedResourceLibreOfficeEngine(ROOT, PROFILE, role='source', receipt_directory=output/'private/source_receipts'/str(index))
            current = engine.recalculate(current, output/f'private/source{index}.xlsx')
            observed = scan(current); checked = audit_source(observed, definition, A, bindings)
            if previous is not None:
                require(observed['typed'] == previous['typed'] and observed['raw_numeric'] == previous['raw_numeric'],
                        'Repeated native source calculation is unstable')
            calls.append({'index': index, 'workbook': ref(current), 'audit': write(output/f'private/source{index}_audit.json', checked),
                          'native_metadata': engine.metadata()})
            previous = observed; audit.emit('source.native_completed', index=index)
        goal = current; goal_ref = ref(goal); goal_values = previous
        native_definition = scan(goal, formulas=True)
        source_ref = write(output/'private/source_manifest.json', {'kind': 'independently_verified_associate_bridge_business_source_v1',
            'passed': True, 'case_id': case_id, 'raw_cohort': cohort_ref, 'specification': case['specification'],
            'goal': goal_ref, 'bindings': emission['bindings'], 'independent_records': records,
            'complete_AB_financial_fields': crosscheck['full_financial_fields'], 'actual_LO_calls': calls,
            'actual_LO_calls_completed': 3, 'actual_formula_count': len(native_definition['formulas']), 'recipe': recipe})
        modes = ('financial_modeling', 'debugging')
        plans = [{'mode': mode, 'plan': plan(public, bindings, native_definition, mode)} for mode in modes]
        frozen = write(output/'plans_frozen.json', {'kind': 'frozen_associate_bridge_business_task_plans_v1',
            'frozen_at': datetime.now(timezone.utc).isoformat(), 'source': source_ref, 'plans': plans,
            'execution_budget': BUDGET, 'runtime_profile': ref(PROFILE), 'recipe': recipe})
        tasks = []
        for row in plans:
            mode, p = row['mode'], row['plan']; key = p['variant_id']; folder = output/'private'/key
            folder.mkdir(); audit.task(key, mode=mode, status='running', source_id=goal_ref['sha256'], stage='native_input')
            raw_input = folder/'input_uncalculated.xlsx'; emit_input(goal, native_definition, p, raw_input)
            engine = ThreadCappedResourceLibreOfficeEngine(ROOT, PROFILE, role='source', receipt_directory=folder/'native_receipts')
            native = engine.recalculate(raw_input, folder/'input.native.xlsx'); observed = scan(native)
            require(not observed['errors'] and observed['sheetnames'] == goal_values['sheetnames'], 'Invalid native candidate input')
            require(all(observed['literals'].get(point) == value for point, value in native_definition['literals'].items()),
                    'A candidate changed provided literals')
            D = difference(observed['typed'], goal_values['typed'])
            require(D and set(D) <= set(native_definition['formulas']), 'The actual primary effects must stay in financial formulas')
            if mode == 'financial_modeling':
                require(set(D) == set(p['mask_points']), 'Full-masking must affect exactly its declared financial formulas')
            engineering = write(folder/'individual_engineering.json', {'passed': True,
                'native_error_count': 0, 'given_literals_unchanged': True, 'sheet_structure_unchanged': True,
                'complete_primary_difference_count': len(D), 'complete_primary_difference': D,
                'injected_formula_count': p.get('injected_formula_count'), 'source': source_ref,
                'native_call_metadata': engine.metadata(), 'actual_Harbor_controls_pending': True})
            material = folder/'materialized'; (material/'public').mkdir(parents=True); (material/'private').mkdir()
            shutil.copyfile(native, material/'public/input.xlsx'); shutil.copyfile(goal, material/'private/goal.xlsx')
            brief = ('Complete the historical and forecast management reports for these businesses using the supplied operating data and investment-accounting policies. Preserve the source inputs, nonapplicable fields and workbook layout.' if mode == 'financial_modeling' else
                     'Audit and repair the management reports for these businesses. Apply the supplied operating assumptions and investment-accounting policies so the financial reports reconcile throughout. Preserve source inputs, nonapplicable fields and workbook layout.')
            instruction = brief+'\n\nRead /app/input.xlsx and save the completed workbook to /app/output.xlsx.\n'
            (material/'public/instruction.md').write_text(instruction)
            signature = hashlib.sha256(mode.encode()+native.read_bytes()+instruction.encode()).hexdigest()
            task_id = ('fm-' if mode == 'financial_modeling' else 'dbg-')+'bridge-'+case_id.lower()+'-'+signature[:20]
            cap = folder/'worker_cap.json'
            directory = export_resource_harbor(material, output/'SpreadsheetEval'/task_id,
                {'task_id': task_id, 'mode': mode, 'revision': 0, 'revision_hash': signature,
                 'source_kind': 'associate_bridge_business_revision', 'difficulty_status': 'development_pending', 'variant_id': key},
                ROOT, runtime_profile=PROFILE, audit_path=cap)
            task = {'task_id': task_id, 'mode': mode, 'revision': 0, 'revision_hash': signature,
                'source_id': goal_ref['sha256'], 'task_directory': str(directory), 'variant_id': key,
                'harbor_export_binding': inspect_resource_export(directory, audit_path=cap), 'execution_budget': BUDGET,
                'individual_engineering': engineering, 'worker_cap_audit': ref(cap), 'plan_freeze': frozen}
            tasks.append(task); write(folder/'task_record.json', task)
            audit.task(key, status='ready', stage='engineered', harbor_task_id=task_id, primary_difference_count=len(D)); audit.export()
        require(recipes() == recipe, 'Construction code changed during the actual source and task engineering')
        terminal = write(output/'engineered_batch.json', {'kind': 'individually_engineered_business_revision_batch', 'version': 1,
            'count': len(tasks), 'tasks': tasks, 'selected_task_ids': [t['task_id'] for t in tasks], 'source': source_ref,
            'source_count': 1, 'qualified': False, 'business_difficulty_evidence_pending': True,
            'actual_LO_calls_completed': 5, 'duration_seconds': time.monotonic()-started})
        audit.update_run(status='completed', stage='engineering_complete'); return terminal
    except BaseException as error:
        write(output/'failure.json', {'error_type': type(error).__name__, 'reason': str(error), 'qualified': False,
                                    'failure_is_not_model_zero': True})
        audit.update_run(status='failed', stage='engineering_failed', error=str(error)); raise
    finally:
        audit.export(); server.stop(); audit.db.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-manifest', type=Path, required=True)
    parser.add_argument('--case', choices=spec.CASE_IDS, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    print(json.dumps(build(args.raw_manifest, args.case, args.output, port=args.port)))

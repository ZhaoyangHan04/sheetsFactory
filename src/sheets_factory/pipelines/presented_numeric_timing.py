"""Projection-aware public timing and monetary-cache proof for a NEW source.

This never claims that the old 180-formula auditor accepted a source whose
independently covered zero formulas were intentionally provided as literals.
All numerical replay and cache checks are read-only: no LO or model calls.
"""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
from ..task_adapters.public_input_priority import checked, equivalent, read, ref, require, write


def same_artifact(left, right):
    return checked(left) == checked(right) and left['sha256'] == right['sha256']


def _public_timing_observations(source, scenarios):
    import openpyxl
    book = openpyxl.load_workbook(source, data_only=True, read_only=True)
    try:
        structured = json.loads(book['Model Input Contracts']['B5'].value)
        lag = structured['parameters']['claim_lag_years']
        labelled = book['Reopener Inputs']['B33'].value
        label = book['Reopener Inputs']['A33'].value
        narrative = book['Reopener Brief']['A21'].value
        require(structured == scenarios['programme'] and type(lag) is int
                and type(labelled) in (int,float) and labelled == lag and label == 'claim lag years',
                'Presented source labelled and JSON numeric timing inputs disagree')
        require(isinstance(narrative, str) and 'two-year collection lag' in narrative
                and 'two years after its creation' in narrative, 'Unsupported narrative default in presented timing audit')
        return {'structured_parameter':{'sheet':'Model Input Contracts','cell':'B5',
                    'path':'programme.parameters.claim_lag_years','value':lag},
                'labelled_input':{'sheet':'Reopener Inputs','label_cell':'A33','value_cell':'B33',
                    'label':label,'value':labelled},
                'narrative':{'sheet':'Reopener Brief','cell':'A21','text':narrative},
                'confirmed_conflict':lag != 2}
    finally:
        book.close()


def _timing_projection(source, bindings, presentation):
    import openpyxl
    targets = {(x['sheet'],x['cell']) for x in bindings['cell_bindings']}
    require(len(targets) == len(bindings['cell_bindings']) == 180, 'The original timing journal must cover all 180 monetary fields')
    projection = [item for item in presentation['conversions'] if (item['sheet'],item['cell']) in targets]
    provided = {(x['sheet'],x['cell']) for x in projection}
    book = openpyxl.load_workbook(source, keep_links=False)
    try:
        names = set(bindings['sheets'].values())
        actual = {(ws.title,c.coordinate) for ws in book if ws.title in names for c in ws._cells.values() if c.data_type == 'f'}
        require(actual == targets - provided, 'Projected timing formula set differs from the original bindings minus declared zeros')
        require(all(type(book[s][c].value) in (int,float) and book[s][c].value == 0
                    and not book[s][c].is_date for s,c in provided),
                'Projected contingent controls must be literal numeric zeros')
    finally:
        book.close()
    return projection


def _validate_timing_results(annual, original):
    require(set(annual) == {str(y) for y in range(2024,2044)}, 'Presented numeric replay must cover all twenty reporting years')
    for year,row in annual.items():
        proof = row.get('proof', {})
        require(equivalent(row, original[year]) and row.get('unique_fixed_point') is True
                and proof.get('unique_on_entire_contractual_grid') is True and proof.get('endpoint_coalescence') is True
                and equivalent(proof.get('lower_fixed_point'), row.get('variable_rent_total'))
                and equivalent(proof.get('upper_fixed_point'), row.get('mapped_variable_rent_total')),
                'The complete original twenty-year numeric policy or endpoint proof differs')


def _validate_timing_cache_report(report, annual, bindings, source, projection):
    import openpyxl
    from ..workbook.contingent_recovery.validate import FINANCIAL_FIELDS, _money_matches
    require(type(report.get('checked_cells')) is int and report['checked_cells'] == 180
            and len(report.get('cell_checks', [])) == 180
            and all(report.get(k) is True for k in ('public_parameters_verified',
                'programme_feedback_reconciled','all_twenty_years_uniquely_certified'))
            and not report.get('mismatches') and not report.get('control_mismatches'),
            'Presented timing cache report lacks complete actual amounts, public terms, calendars, or feedback')
    expected_semantics = {(year,field) for year in range(2024,2044) for field in FINANCIAL_FIELDS}
    expected_bindings = {(x['sheet']+'!'+x['cell'],x['year'],x['field']) for x in bindings['cell_bindings']}
    checks = report['cell_checks']
    require({(c['address'],c['year'],c['field']) for c in checks} == expected_bindings
            and {(c['year'],c['field']) for c in checks} == expected_semantics,
            'Presented timing amount checks omit or replace original financial fields')
    book = openpyxl.load_workbook(source, data_only=True, read_only=True)
    try:
        for check in checks:
            row = annual[str(check['year'])];field = check['field']
            expected = row['variable_rents'][field.split('.')[1]] if field.startswith('variable_rents.') else row[field]
            sheet,cell = check['address'].rsplit('!',1)
            observed = book[sheet][cell].value
            require(check.get('matched') is True and equivalent(check.get('expected_independent'), expected)
                    and type(observed) in (int,float) and _money_matches(observed, expected)
                    and equivalent(check.get('observed'), observed), 'An actual presented timing monetary cache differs')
    finally:
        book.close()
    complete_original_formula_set = not projection
    require(report.get('complete_formula_coverage') is complete_original_formula_set
            and report.get('all_formula_cells_independently_covered') is complete_original_formula_set
            and report.get('passed') is complete_original_formula_set
            and report.get('formula_count') == 180-len(projection),
            'Original formula auditor outcome must remain honest about provided-zero projection')


def audit_presented_numeric_timing(source_binding, output_directory):
    """Fresh 0-LO/0-model numeric timing proof after actual source certification.

    The original formula auditor report is saved exactly as returned, including
    ``passed=False`` when independently covered zero formulas became literals.
    This separate proof checks all 180 monetary values and all public controls;
    it does not claim a fresh full independent financial audit of the new book.
    """
    from ..workbook.lease_finance import ledger as lease_ledger
    from ..workbook.derived_regulatory import ledger as programme_ledger
    from ..workbook.contingent_recovery import validate as cache_auditor
    from .scc_activity_admission import validate_financial_admission
    financial = validate_financial_admission(source_binding)
    output = Path(output_directory).resolve();output.mkdir(parents=True, exist_ok=False)
    source = checked(source_binding['source']);manifest = read(source_binding['source_manifest'])
    scenarios_ref = manifest['public_scenarios'];scenarios = read(scenarios_ref)
    observations = _public_timing_observations(source, scenarios)
    old_manifest_path = checked(financial['original_manifest'])
    old_ledger = ref(old_manifest_path.parent/'private/programme_ledger.json')
    old_bindings = ref(old_manifest_path.parent/'private/programme_bindings.json')
    bindings = read(old_bindings)['contingent_binding']
    lease = lease_ledger.simulate_lease(scenarios['lease'])
    programme = programme_ledger.simulate(scenarios['programme'], external_lease_annual=lease['annual'],
        contingent_spec=scenarios['contingent'])
    annual = {str(year):row for year,row in programme['contingent_recovery']['annual'].items()}
    _validate_timing_results(annual, read(old_ledger)['contingent_recovery']['annual'])
    presentation = read(financial['presentation'])
    projection = _timing_projection(source, bindings, presentation)
    raw_audit = cache_auditor.audit_contingent_workbook(source, scenarios['contingent'], programme, bindings)
    _validate_timing_cache_report(raw_audit, annual, bindings, source, projection)
    write(output/'original_formula_auditor_report.json', raw_audit)
    record = {'kind':'fresh_numeric_timing_and_value_only_cache_verification','version':1,
        'source':deepcopy(source_binding['source']),'source_manifest':deepcopy(source_binding['source_manifest']),
        'financial_admission':deepcopy(source_binding['financial_admission']),'public_scenarios':scenarios_ref,
        'original_programme_ledger':old_ledger,'original_programme_bindings':old_bindings,
        'observations':observations,'annual_results':annual,
        'declared_zero_projection':projection,'original_formula_auditor_report':ref(output/'original_formula_auditor_report.json'),
        'original_180_formula_auditor_passed':raw_audit['passed'],
        'independent_numeric_amount_count':180,'provided_zero_binding_count':len(projection),
        'remaining_formula_binding_count':180-len(projection),'all_twenty_years_equal_original_full_proofs':True,
        'numeric_timing_and_value_cache_checks_passed':True,
        'fresh_full_independent_financial_audit_claimed':False,'quality_recovery_difficulty_certified':False,
        'numeric_implementations':[ref(Path(lease_ledger.__file__)),ref(Path(programme_ledger.__file__)),
            ref(Path(cache_auditor.__file__)),ref(Path(__file__))],'model_calls':0,'LO_calls':0}
    write(output/'numeric_timing_audit.json',record)
    return ref(output/'numeric_timing_audit.json')


def validate_presented_numeric_timing(reference, source_binding):
    record = read(reference)
    require(record.get('kind') == 'fresh_numeric_timing_and_value_only_cache_verification'
            and record.get('version') == 1 and record.get('numeric_timing_and_value_cache_checks_passed') is True
            and record.get('all_twenty_years_equal_original_full_proofs') is True
            and record.get('fresh_full_independent_financial_audit_claimed') is False,
            'The new presented source requires its own projection-aware numeric timing proof')
    for name in ('source','source_manifest','financial_admission'):
        require(same_artifact(record[name], source_binding[name]), 'Presented timing proof binds another source, manifest, or financial admission')
    for implementation in record['numeric_implementations']:
        checked(implementation)
    scenarios = read(record['public_scenarios'])
    require(same_artifact(record['public_scenarios'], read(source_binding['source_manifest'])['public_scenarios'])
            and record['observations'] == _public_timing_observations(checked(record['source']), scenarios),
            'Presented timing public observations changed')
    financial = read(source_binding['financial_admission'])
    parent = checked(financial['original_manifest']).parent
    require(checked(record['original_programme_ledger']) == (parent/'private/programme_ledger.json').resolve()
            and checked(record['original_programme_bindings']) == (parent/'private/programme_bindings.json').resolve(),
            'Presented timing original independent journal or bindings differ')
    _validate_timing_results(record['annual_results'], read(record['original_programme_ledger'])['contingent_recovery']['annual'])
    bindings = read(record['original_programme_bindings'])['contingent_binding']
    projection = _timing_projection(checked(record['source']), bindings, read(financial['presentation']))
    require(record.get('declared_zero_projection') == projection
            and record.get('independent_numeric_amount_count') == 180
            and record.get('provided_zero_binding_count') == len(projection)
            and record.get('remaining_formula_binding_count') == 180-len(projection), 'Presented timing zero-projection coverage differs')
    raw_audit = read(record['original_formula_auditor_report'])
    _validate_timing_cache_report(raw_audit, record['annual_results'], bindings, checked(record['source']), projection)
    require(record.get('original_180_formula_auditor_passed') is raw_audit.get('passed'),
            'Presented timing must preserve the original formula auditor outcome')
    return record



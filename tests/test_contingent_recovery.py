"""Posted policy parity, hand calculations and whole-grid uniqueness safeguards."""
from copy import deepcopy
from decimal import Decimal as D, localcontext
from pathlib import Path
import inspect
import xml.etree.ElementTree as ET
import zipfile

import openpyxl
import pytest

from sheets_factory.workbook.contingent_recovery import (
    load_spec, validate_spec, validate_contracts, solve_year, evaluate_total,
    monotonicity_proof, MonotonicityError, NonUniqueFixedPointError, ConvergenceError)
from sheets_factory.workbook.contingent_recovery.solver import gross_up_posted
from sheets_factory.workbook.derived_regulatory.ledger import gross_up
from sheets_factory.workbook.contingent_recovery.excel import emit_contingent_workbook
from sheets_factory.workbook.contingent_recovery.validate import audit_contingent_workbook

ROOT = Path(__file__).resolve().parents[1]


def contract(*, rate='.02', threshold='0.00', cap='1000.00', quantum='100', identity='P01'):
    return {'lease_id': identity, 'active': True, 'rate': rate, 'threshold': threshold,
            'annual_cap': cap, 'rounding_quantum': quantum, 'rounding_mode': 'ROUND_HALF_UP'}


@pytest.mark.parametrize('available,tax,used', [
    ('0.00', '1986.67', '0'), ('1000.00', '1653.33', '1000.00'),
    ('10000.00', '313.68', '5018.95')])
def test_hand_calculated_two_hundred_rent_feedback(available, tax, used):
    result = solve_year('10000.00', '6000.00', available, '.25', '.8', '.8', [contract()])
    # v=200, A=160, B=5960. Tax is posted separately from continuous loss use.
    assert result['variable_rent_total'] == D(200)
    assert result['variable_lease_allowance'] == D(160)
    assert result['taxable_base'] == D(5960)
    assert result['tax'] == D(tax) and result['loss_used'] == D(used)
    assert result['total_recovery_entitlement'] == D(10160) + D(tax)
    assert result['mapped_variable_rent_total'] == result['variable_rent_total']
    assert result['proof']['unique_on_entire_contractual_grid'] is True


def test_tax_rule_matches_original_regulatory_expression_and_posting_order():
    with localcontext() as context:
        context.prec = 50
        for base in map(D, ['-100.05', '0', '.01', '100', '5960', '123456789.23']):
            for available in map(D, ['0', '.01', '50', '100', '10000.01']):
                for cap in map(D, ['0', '.8', '1']):
                    for rate in map(D, ['0', '.25', '.28', '.49']):
                        assert gross_up_posted(base, available, cap, rate) == gross_up(base, available, cap, rate)
    assert gross_up_posted(D(100), D(50), D('.8'), D('.25')) == (D('16.67'), D(50), D(0))
    assert gross_up_posted(D(100), D(100), D('.8'), D('.25')) == (D('5.26'), D('84.21'), D(0))


def test_contract_half_up_unit_rounding_occurs_before_annual_cap():
    args = ('5000.00', '-100.00', '0.00', '0', '.8', '.85', [contract(rate='.01', cap='100.00')])
    assert evaluate_total('0.00', *args)['variable_rents']['P01'] == 100  # Exactly GBP50 -> GBP100.
    assert evaluate_total('0.00', '4999.99', *args[1:])['variable_rents']['P01'] == 0
    capped = evaluate_total('0.00', '20000.00', *args[1:])
    assert capped['contract_details']['P01']['rounded_before_cap'] == 200
    assert capped['variable_rents']['P01'] == 100
    assert capped['contract_details']['P01']['cap_binding'] is True


def test_rounding_noise_bound_proves_monotonicity_on_every_grid_point():
    contracts = [contract(cap='1000.00'), contract(rate='.01', cap='1000.00', quantum='1000', identity='P02')]
    args = ('10000.00', '400.00', '100.00', '.5', '.8', '.75003', contracts)
    proof = monotonicity_proof(*args)
    assert proof['grid_quantum'] == 100
    assert proof['allowance_increment_lower_bound'] == 75
    assert proof['tax_drop_upper_bound'] == 25
    assert proof['entitlement_increment_lower_bound'] == 50
    points = [evaluate_total(D(v), *args) for v in range(0, 2001, 100)]
    for left, right in zip(points, points[1:]):
        assert right['variable_lease_allowance'] - left['variable_lease_allowance'] >= 75
        assert left['tax'] - right['tax'] <= 25
        assert right['total_recovery_entitlement'] >= left['total_recovery_entitlement'] + 50
        assert right['mapped_variable_rent_total'] >= left['mapped_variable_rent_total']


def test_low_continuous_feedback_slope_does_not_certify_discrete_uniqueness():
    # F(0)=0 but F(100)=100 despite rate*eligibility=.0085 < 1.
    with pytest.raises(NonUniqueFixedPointError) as captured:
        solve_year('4990.00', '0.00', '0.00', '0', '.8', '.85', [contract(rate='.01', cap='100.00')])
    proof = captured.value.proof
    assert proof['lower_fixed_point'] == 0 and proof['upper_fixed_point'] == 100
    assert proof['unique_on_entire_contractual_grid'] is False


def test_insufficient_endpoint_budget_rejects_instead_of_accepting_a_one_sided_root():
    args = ('14600.00', '0.00', '0.00', '0', '.8', '.85', [contract(rate='.01')])
    with pytest.raises(ConvergenceError):
        solve_year(*args, max_iterations=1)
    solved = solve_year(*args)
    assert solved['variable_rent_total'] == 100 and solved['proof']['iterations'] == 2
    with pytest.raises(ValueError, match='128'):
        solve_year(*args, max_iterations=129)


def test_unproved_posted_monotonicity_rejects_before_endpoint_iteration():
    with pytest.raises(MonotonicityError) as captured:
        solve_year('10000.00', '10000.00', '0.00', '.9', '.8', '.1', [contract()])
    assert captured.value.proof['entitlement_increment_lower_bound'] < 0


@pytest.mark.parametrize('change', [
    {'annual_cap': '150.00'}, {'rounding_quantum': '1'}, {'rounding_mode': 'ROUND_HALF_EVEN'},
    {'active': False}, {'rate': 'NaN'}, {'rate': .01}, {'annual_cap': '-100.00'}])
def test_incomplete_or_noncontractual_terms_cannot_be_inferred(change):
    item = contract()
    item.update(change)
    with pytest.raises(ValueError):
        validate_contracts([item])
    missing = contract()
    missing.pop('threshold')
    with pytest.raises(ValueError, match='explicit'):
        validate_contracts([missing])


def test_twenty_explicit_years_have_positive_fees_without_inactive_padding():
    spec = load_spec(ROOT / 'config/derived_contingent_recovery_v1.json')
    assert len(spec['annual_terms']) == 20
    positive = []
    for annual in spec['annual_terms']:
        result = solve_year('1000000.00', '600000.00', '100000.00', '.25', '.8',
                            annual['eligible_fraction'], annual['contracts'])
        if result['variable_rent_total'] > 0:
            positive.append(annual['year'])
    assert positive == list(range(2024, 2044))
    counts = {identity: sum(next(c for c in row['contracts'] if c['lease_id'] == identity)['active']
                            for row in spec['annual_terms']) for identity in ['P01', 'P02', 'P03', 'P04']}
    assert counts == {'P01': 13, 'P02': 18, 'P03': 9, 'P04': 18}
    changed = deepcopy(spec)
    changed['annual_terms'][0].pop('eligible_fraction')
    with pytest.raises(ValueError, match='eligibility'):
        validate_spec(changed)


def emitted_fixture(tmp_path):
    """An explicit test fixture; manually supplied caches never certify LO work."""
    spec = load_spec(ROOT / 'config/derived_contingent_recovery_v1.json')
    book = openpyxl.Workbook()
    book.active.title = 'Programme Total'
    book.active['A1'] = 'existing source context remains intact'
    refs, independent, programme = {}, {}, {}
    for index, terms in enumerate(spec['annual_terms']):
        year, col = terms['year'], openpyxl.utils.get_column_letter(index + 3)
        result = solve_year('1000000.00', '600000.00', '100000.00', '.25', '.8',
                            terms['eligible_fraction'], terms['contracts'])
        independent[year] = {**result, 'year': year}
        programme[year] = {'capital_entitlement': result['total_recovery_entitlement'],
                          'variable_lease_cash': result['variable_lease_cash'],
                          'variable_lease_allowance': result['variable_lease_allowance']}
        book.active[col + '3'] = (f'=1000000+\'Contingent Annual\'!{col}9+'
                                 f'ROUND((600000+\'Contingent Annual\'!{col}9-\'Contingent Annual\'!{col}8-100000)/3,2)')
        refs[year] = {'capital_entitlement': "'Programme Total'!" + col + '3'}
    binding = emit_contingent_workbook(book, spec, refs)
    path = tmp_path / 'contingent-fixture.xlsx'
    book.save(path)
    ledger = {'annual': programme, 'contingent_recovery': {'annual': independent}}
    return path, book, spec, ledger, binding


def fixture_caches(path, book, ledger, binding):
    """Insert controlled test caches while preserving the emitted formulas."""
    index = book.sheetnames.index(binding['sheets']['annual']) + 1
    member = f'xl/worksheets/sheet{index}.xml'
    with zipfile.ZipFile(path) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    xml = ET.fromstring(files[member])
    cells = {cell.attrib['r']: cell for cell in xml.iter(ns + 'c')}
    for item in binding['cell_bindings']:
        result = ledger['contingent_recovery']['annual'][item['year']]
        field = item['field']
        expected = result['variable_rents'][field.split('.')[1]] if field.startswith('variable_rents.') else result[field]
        cell = cells[item['cell']]
        value = cell.find(ns + 'v')
        if value is None:
            value = ET.SubElement(cell, ns + 'v')
        value.text = str(expected)
    files[member] = ET.tostring(xml, encoding='utf-8', xml_declaration=True)
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)


def test_emitter_uses_real_regulatory_cycle_without_importing_financial_journal(tmp_path):
    path, book, spec, ledger, binding = emitted_fixture(tmp_path)
    assert book['Programme Total']['A1'].value == 'existing source context remains intact'
    assert book['Contingent Annual']['C3'].value == "='Programme Total'!C3"
    assert "'Contingent Annual'!C9" in book['Programme Total']['C3'].value
    assert binding['annual_refs'][2024]['variable_lease_cash'] == "'Contingent Annual'!C8"
    assert binding['annual_refs'][2024]['variable_lease_allowance'] == "'Contingent Annual'!C9"
    assert binding['formula_count'] == 180
    from sheets_factory.workbook.contingent_recovery import excel
    source = inspect.getsource(excel)
    assert 'from .solver' not in source and 'solve_year(' not in source and 'import simulate' not in source
    raw = audit_contingent_workbook(path, spec, ledger, binding)
    assert raw['complete_formula_coverage'] is True
    assert raw['public_parameters_verified'] is True
    assert raw['programme_feedback_reconciled'] is True
    assert raw['passed'] is False and raw['mismatch_count'] == 180  # No LO was run.


def test_auditor_accepts_independent_fixture_caches_and_rejects_changed_public_terms(tmp_path):
    path, book, spec, ledger, binding = emitted_fixture(tmp_path)
    fixture_caches(path, book, ledger, binding)
    good = audit_contingent_workbook(path, spec, ledger, binding)
    assert good['passed'] is True and good['checked_cells'] == 180
    book['Contingent Inputs']['C8'] = .019  # Provided P01 rate, while public JSON stays unchanged.
    book.save(path)
    fixture_caches(path, book, ledger, binding)
    bad = audit_contingent_workbook(path, spec, ledger, binding)
    assert bad['mismatch_count'] == 0
    assert bad['public_parameters_verified'] is False and bad['passed'] is False


def test_audit_rejects_unbound_finance_formula_and_parallel_report_only(tmp_path):
    path, book, spec, ledger, binding = emitted_fixture(tmp_path)
    book['Contingent Annual']['C15'] = '=1+1'
    book.save(path)
    fixture_caches(path, book, ledger, binding)
    bad = audit_contingent_workbook(path, spec, ledger, binding)
    assert bad['complete_formula_coverage'] is False and bad['passed'] is False
    ledger['annual'][2024]['variable_lease_cash'] += 100
    bad = audit_contingent_workbook(path, spec, ledger, binding)
    assert bad['programme_feedback_reconciled'] is False


def test_audit_requires_both_endpoint_uniqueness_receipts(tmp_path):
    path, book, spec, ledger, binding = emitted_fixture(tmp_path)
    fixture_caches(path, book, ledger, binding)
    ledger['contingent_recovery']['annual'][2024]['proof']['unique_on_entire_contractual_grid'] = False
    bad = audit_contingent_workbook(path, spec, ledger, binding)
    assert bad['all_twenty_years_uniquely_certified'] is False and bad['passed'] is False

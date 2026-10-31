"""Uncalculated fixture emission only: no production, search, LO or model."""
from copy import deepcopy
import inspect

import openpyxl
import pytest

from sheets_factory.task_adapters import sparse_compound_debugging as adapter
from sheets_factory.workbook.capital_allocation_sparse import spec


def public_fixture(n=40):
    def annual(value):
        return {str(year): value for year in spec.YEARS}
    return {'schema_version': 1, 'currency': 'GBP', 'monetary_unit': 'pence', 'years': list(spec.YEARS),
        'opening_cash_pence': 1000, 'minimum_cash_pence': 0, 'lp_commitment_pence': 300,
        'facility_limit_pence': 1000, 'advance_rate_p12': spec.SCALE // 2,
        'tax_rate_p12': spec.SCALE // 4, 'tax_loss_carry_years': 2,
        'discount_factors_p12': annual(spec.SCALE),
        'projects': [{'id': pid, 'commission_year': 2024, 'sale_year': 2026,
            'acquisition_cost_pence': 100+index, 'depreciation_years': 2,
            'annual_revenue_pence': {**annual(0), '2025': 80, '2026': 80},
            'annual_opex_pence': {**annual(0), '2025': 10, '2026': 10},
            'sale_proceeds_pence': 0} for index, pid in enumerate(spec.project_ids(n))],
        'scenarios': [{'id': sid, 'revenue_factors_p12': annual(spec.SCALE),
            'opex_factors_p12': annual(spec.SCALE), 'nav_factors_p12': annual(spec.SCALE),
            'sale_factors_p12': annual(spec.SCALE), 'bank_rates_p12': annual(spec.SCALE // 20),
            'haircuts_p12': annual(0)} for sid in spec.SCENARIO_IDS],
        'provenance': {'kind': 'synthetic_capital_allocation_extension',
                       'raw_ancestors': deepcopy(spec.RAW_ANCESTORS)}}


def empty_book():
    book = openpyxl.Workbook()
    book.remove(book.active)
    return book


@pytest.mark.parametrize('n', [40, 48, 56])
def test_provisional_plan_is_predeclared_public_position_not_a_gold_argument(n):
    public = public_fixture(n)
    plan = adapter.provisional_plan(public)
    assert list(plan) == list(spec.project_ids(n))
    assert [pid for pid, value in plan.items() if value] == [f'P{i:02d}' for i in range(1, n+1, 4)]
    assert all(type(value) is int for value in plan.values())
    public['opening_cash_pence'] += 10
    public['projects'][-1]['acquisition_cost_pence'] += 1
    assert adapter.provisional_plan(public) == plan
    assert set(inspect.signature(adapter.emit_input).parameters) == {'book','public','enabled','template'}


@pytest.mark.parametrize('enabled', [False, None, 1, 'yes'])
def test_no_emission_without_explicit_boolean_opt_in(enabled):
    book = empty_book()
    try:
        with pytest.raises(ValueError, match='disabled'):
            adapter.emit_input(book, public_fixture(), enabled=enabled)
        assert not book.sheetnames
    finally:
        book.close()


@pytest.mark.parametrize('field,value', [('enabled',True),('version',True),('scope','chosen_years'),
    ('qualified',True),('LO_calls_authorized',True)])
def test_template_cannot_silently_expand_or_authorize_execution(field,value):
    template = adapter.load_template()
    template[field] = value
    with pytest.raises(ValueError, match='template differs'):
        adapter.load_template(template)


@pytest.fixture(scope='module')
def emitted(tmp_path_factory):
    public = public_fixture()
    before = deepcopy(public)
    book = empty_book()
    construction = adapter.emit_input(book, public, enabled=True)
    assert public == before
    # This is an uncached test artifact, not a source producer or admission.
    path = tmp_path_factory.mktemp('TEST_compound_uncalculated')/'TEST_uncalculated_n40.xlsx'
    book.save(path)
    yield book, public, construction, path
    book.close()


def test_complete_existing_model_and_honest_non_gold_metadata(emitted):
    book, public, result, path = emitted
    binding = result['bindings']
    assert len(book.sheetnames) == 15
    assert len(binding['financial_bindings']) == 30911
    assert len(binding['arithmetic_bindings']) == 66372
    assert len(binding['decision_bindings']) == 40
    assert binding['formula_count'] == 97323
    assert binding['gold_plan_supplied'] is False and binding['provisional_plan_supplied'] is True
    assert result['gold_or_optimum_supplied'] is False
    assert result['financial_cells_masked'] == 0
    assert len([cell for sheet in book for cell in sheet._cells.values() if cell.data_type == 'f']) == 97323
    for row in binding['decision_bindings']:
        assert book[row['sheet']][row['cell']].value == '=' + str(result['provisional_plan'][row['project_id']])
    assert all(book[row['sheet']][row['cell']].data_type == 'f' for row in binding['financial_bindings'])
    assert all(row['after'].startswith('=') for row in result['faults'])
    assert path.is_file() and all(result['pending'].values())
    assert result['qualified'] is False and result['task_count'] == 0


def test_exact_two_policy_families_cover_all_scenarios_years_without_activity_claim(emitted):
    book, _, result, _ = emitted
    faults = result['faults']
    assert len(faults) == 120
    assert len({(row['sheet'],row['cell']) for row in faults}) == 120
    for field in ('lp_call','bank_interest'):
        rows = [row for row in faults if row['annual_field'] == field]
        assert len(rows) == 60
        assert {(row['scenario'],row['year']) for row in rows} == {
            (sid,year) for sid in spec.SCENARIO_IDS for year in spec.YEARS}
        assert all(row['individual_activity_claimed'] is False and row['before'] != row['after'] for row in rows)
    for row in faults:
        assert book[row['sheet']][row['cell']].value == row['after']
        if row['annual_field'] == 'bank_interest':
            assert row['after'] == '=0'
        else:
            assert row['after'].startswith('=MIN(')
            assert 'MAX(' not in row['after'] and 'MAX(' in row['before']
    assert result['mechanical_validation'] == adapter.verify_input(book, public_fixture(), result)
    assert result['mechanical_validation']['financial_audit_performed'] is False
    assert result['mechanical_validation']['cache_values_verified'] is False


def test_uncalculated_fixture_contains_no_preexisting_answer_caches(emitted):
    _, _, result, path = emitted
    book = openpyxl.load_workbook(path, data_only=True, read_only=True)
    try:
        # Check one cell of each domain, not a numerical financial audit.
        for key in ('financial_bindings','arithmetic_bindings','decision_bindings'):
            row = result['bindings'][key][0]
            assert book[row['sheet']][row['cell']].value is None
    finally:
        book.close()


def test_public_scope_discloses_reoptimisation_without_fault_locations(emitted):
    _, _, result, _ = emitted
    brief = result['public_instruction']
    assert 'provisional results, not fixed assumptions' in brief
    assert 'maximises the lowest LP net present value' in brief
    assert 'Do not introduce new funding or forecast assumptions' in brief
    assert 'otherwise unlabelled blanks' in brief and 'all three scenarios' in brief
    assert 'lp_call' not in brief and 'bank_interest' not in brief
    assert 'P01' not in brief and 'P05' not in brief


@pytest.mark.parametrize('change', ['fault_formula','unrelated_formula','decision','literal','helper','missing_formula'])
def test_actual_definition_or_literal_tampering_is_rejected(emitted, change):
    book, public, result, _ = emitted
    binding = result['bindings']
    if change == 'fault_formula':
        row = result['faults'][0]; cell = book[row['sheet']][row['cell']]; value = '=123'
    elif change in ('unrelated_formula','missing_formula'):
        row = binding['arithmetic_bindings'][0]; cell = book[row['sheet']][row['cell']]
        value = '=123' if change == 'unrelated_formula' else None
    elif change == 'decision':
        row = binding['decision_bindings'][0]; cell = book[row['sheet']][row['cell']]; value = '=0'
    elif change == 'literal':
        row = binding['input_bindings'][0]; cell = book[row['sheet']][row['cell']]; value = 'changed'
    else:
        cell = book['Investment Plan']['Z100']; value = 1
    original = cell.value
    cell.value = value
    try:
        with pytest.raises(ValueError):
            adapter.verify_input(book, public, result)
    finally:
        cell.value = original


@pytest.mark.parametrize('change', ['fault_list','fault_family','claim','version','pending','public_source','boolean_count'])
def test_overlay_or_claim_tampering_is_rejected(emitted,change):
    book, public, construction, _ = emitted
    result = dict(construction)
    if change == 'fault_list': result['faults'] = result['faults'][:-1]
    if change == 'fault_family':
        result['faults'] = deepcopy(result['faults']); result['faults'][0]['policy_family'] = 'some_other_policy'
    if change == 'claim': result['qualified'] = True
    if change == 'version': result['version'] = True
    if change == 'boolean_count': result['task_count'] = False
    if change == 'pending': result['pending'] = {}
    if change == 'public_source':
        public = deepcopy(public); public['lp_commitment_pence'] += 1
    with pytest.raises(ValueError):
        adapter.verify_input(book,public,result)


def test_default_template_and_existing_registry_are_not_enabled():
    assert adapter.load_template()['enabled'] is False
    assert not hasattr(adapter,'ConstructNode') and not hasattr(adapter,'Factory')

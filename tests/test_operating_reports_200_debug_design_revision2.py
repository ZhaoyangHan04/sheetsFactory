from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path

import pytest

from sheets_factory.workbook.operating_reports_200 import debug_design_revision2 as design


ROOT = Path(__file__).resolve().parents[1]
FAILURE = ROOT/'outputs/research/operating_reports_200_task8_prepared_20261031T222100Z/prepared/terminal.json'


@pytest.mark.parametrize('form,given,rate,expected', [
    ('money_delta', '-2', 'fraction', '8'),
    ('change_rate', '0.1', 'fraction', '11'),
    ('change_rate', '10', 'percent_units', '11'),
    ('change_rate', '1000', 'basis_points', '11'),
    ('level_multiple', '1.1', 'fraction', '11'),
    ('base100_index', '110', 'basis_points', '11'),
])
def test_exact_revenue_hand_arithmetic(form, given, rate, expected):
    entity = {'forecast_sales': {'2026Q1': given}, 'rate_unit': rate,
              'driver_form_by_year': {'2026': form}}
    assert design._revenue(entity, F(10), '2026Q1') == F(expected)


def test_only_one_reference_token_changes_even_with_similar_coordinates():
    healthy = "='Business'!B12*(1+'Business'!B125*100/100)"
    result = design._replace_comparison(healthy, "'Business'!B12", "'Business'!B9", "'Business'!B125")
    assert result == "='Business'!B9*(1+'Business'!B125*100/100)"
    assert 'B95' not in result  # A whole-formula translation would shift the supplied driver.
    for invalid in [healthy.replace('B125', 'B95'), healthy + "+'Business'!B12"]:
        with pytest.raises(ValueError):
            design._replace_comparison(invalid, "'Business'!B12", "'Business'!B9", "'Business'!B125")


def test_token_rewrite_preserves_quoted_sheet_and_absolute_driver():
    healthy = "='Owner''s report'!$M$16+'Owner''s report'!$B$125"
    assert design._replace_comparison(healthy, "'Owner''s report'!$M$16", "'Owner''s report'!$J$16",
        "'Owner''s report'!$B$125") == "='Owner''s report'!$J$16+'Owner''s report'!$B$125"


def test_fixed_wrong_quarter_and_multiplication_keep_additive_path_positive():
    entity = {'forecast_reference': 'previous_calendar_quarter', 'rate_unit': 'fraction',
        'actual_sales': {'2025Q1': '10', '2025Q2': '11', '2025Q3': '12', '2025Q4': '20'},
        'forecast_sales': {q: '-1' for q in design.schema.QUARTERS[4:]},
        'driver_form_by_year': {'2026': 'money_delta', '2027': 'money_delta'}}
    normal = design._trajectory(entity)
    wrong = design._trajectory(entity, 'wrong_reference_quarter')
    scaled = design._trajectory(entity, 'money_scale')
    assert normal['2026Q1'] == 19 and normal['2027Q4'] == 12
    assert wrong['2026Q1'] == 9 and wrong['2027Q4'] == 2
    assert scaled['2026Q1'] == 19000 and scaled['2027Q4'] == 18993
    entity['forecast_sales']['2026Q2'] = '-100'
    with pytest.raises(ValueError, match='positive'):
        design._trajectory(entity, 'wrong_reference_quarter')


@pytest.fixture(scope='module')
def retained():
    if not FAILURE.exists():
        pytest.skip('Production integration uses retained private artifacts; no substitute forwards')
    failed = design.read(FAILURE)
    preparation = design.read(failed['preparation'])
    candidate = design.read(preparation['candidate_preparation'])
    refs = [candidate[k] for k in ('specification', 'view_plans', 'bindings', 'retained_A', 'retained_B')]
    return (*[design.read(row) for row in refs], refs, candidate, failed)


def test_production_all100_changed_definitions_and_all200_root_impacts(retained):
    public, original, bindings, A, B, _, _, _ = retained
    saved = deepcopy(original)
    revised = design.revise(public, original, bindings)
    proof = design.prove(public, original, revised, bindings, A, B)
    assert original == saved
    assert proof['passed'] and proof['revised_class_root_count'] == proof['unchanged_other_family_root_count'] == 100
    assert proof['physical_definition_changes_by_family'] == {'money_scale': 50, 'wrong_reference_quarter': 4}
    assert proof['physical_faulty_definition_change_count'] == 54
    assert proof['byte_identical_revised_class_root_count'] == 46
    assert proof['total_roots_primary_impact_proved'] == 200
    assert proof['changed_root_forecast_quarters_positive'] == 800
    assert F(proof['minimum_counterfactual_revenue_exact']) > 0
    assert revised['FM_mask'] == original['FM_mask'] and len(revised['FM_mask']) == 62322
    for key, row in revised['DBG_faults'].items():
        old = original['DBG_faults'][key]
        assert {k: v for k, v in row.items() if k != 'faulty_formula'} == {k: v for k, v in old.items() if k != 'faulty_formula'}
        if row['family'] not in ('money_scale', 'wrong_reference_quarter'):
            assert row['faulty_formula'] == old['faulty_formula']
        elif row['family'] == 'money_scale':
            assert row['faulty_formula'] != old['faulty_formula']
    bad = revised['DBG_faults']['E198/2026Q1/revenue']['faulty_formula']
    assert '!B9*' in bad and '!B125' in bad and '!B95' not in bad
    assert revised['DBG_faults']['E049/2026Q1/revenue']['faulty_formula'].endswith(')*1000')
    assert proof['new_financial_forwards'] == proof['LO_calls'] == proof['model_calls'] == proof['workbooks_written'] == 0
    assert proof['actual_D_unknown'] and not proof['actual_native_error_absence_or_full_D_proved']


def test_proof_rejects_extra_edit_driver_shift_scope_change_and_policy_tuning(retained):
    public, original, bindings, A, B, _, _, _ = retained
    revised = design.revise(public, original, bindings)
    for mutation in ('driver', 'other_family', 'FM_mask'):
        bad = deepcopy(revised)
        if mutation == 'driver':
            key = 'E198/2026Q1/revenue'; bad['DBG_faults'][key]['faulty_formula'] = bad['DBG_faults'][key]['faulty_formula'].replace('B125', 'B95')
        elif mutation == 'other_family':
            key = next(k for k, r in bad['DBG_faults'].items() if r['family'] == 'associate_sign')
            bad['DBG_faults'][key]['faulty_formula'] += '+1'
        else:
            bad['FM_mask'].pop()
        with pytest.raises(ValueError):
            design.prove(public, original, bad, bindings, A, B)
    altered = deepcopy(public); altered['entities'][0]['forecast_sales']['2026Q1'] = '1.2'
    with pytest.raises(ValueError, match='frozen'):
        design.revise(altered, original, bindings)
    wrong_B = deepcopy(B); wrong_B['typed_2dp_values']['E198/2026Q1/revenue']['value'] = '0.00'
    with pytest.raises(ValueError):
        design.prove(public, original, revised, bindings, A, wrong_B)


def test_fresh_lineage_replay_and_changed_candidate_rejected(retained, tmp_path):
    _, _, _, _, _, refs, candidate, failed = retained
    before = {row['path']: design.reference(row['path']) for row in refs + [design.reference(FAILURE)]}
    record = design.write_revision(*refs, design.reference(FAILURE), tmp_path/'new')
    frozen = design.read(record)
    assert frozen['ancestry']['unchanged_source_manifest'] == failed['source_manifest']
    result = design.validate_revision(record, candidate)
    assert result['kind'] == design.PLAN_KIND and result['version'] == 2
    assert len(list((tmp_path/'new').iterdir())) == 3
    assert not list((tmp_path/'new').glob('*.xlsx'))
    bad = deepcopy(candidate); bad['source']['sha256'] = '0'*64
    with pytest.raises(ValueError, match='unchanged'):
        design.validate_revision(record, bad)
    with pytest.raises(ValueError, match='fresh'):
        design.write_revision(*refs, design.reference(FAILURE), tmp_path/'new')
    assert all(design.reference(path) == row for path, row in before.items())


def test_source_module_does_not_import_or_invoke_oracles():
    import ast
    tree = ast.parse(Path(design.__file__).read_text())
    assert not any(isinstance(n, (ast.Import, ast.ImportFrom)) and 'oracle' in ast.unparse(n) for n in ast.walk(tree))
    assert not any(isinstance(n, ast.Attribute) and n.attr in ('solve', 'emit', 'recalculate') for n in ast.walk(tree))

from copy import deepcopy
from fractions import Fraction as F
import hashlib
import json
from pathlib import Path

import pytest

from sheets_factory.workbook.operating_reports_200 import debug_class_variants as d
from test_operating_reports_200 import toy


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'outputs/research/operating_reports_200_source_revision2_prepared_20261031T221400Z/prepared/source_manifest.json'
TASK = ROOT/'outputs/research/operating_reports_200_task8_revision2_prepared_20261031T223700Z/prepared/terminal.json'
SIGN = ROOT/'outputs/research/operating_reports_200_FM_first_failure_readonly_20261031T231900Z/receipt.json'


@pytest.mark.parametrize('core,total,healthy,wrong', [('70', '85', '15', '-15'), ('70', '62', '-8', '8')])
def test_associate_reconciliation_hand_arithmetic_both_profit_and_loss(core, total, healthy, wrong):
    assert F(total)-F(core) == F(healthy)
    assert d._wrong_sign(core, total) == F(wrong)


@pytest.mark.parametrize('unit,healthy,wrong', [('fraction', '0.1', '1.1'),
    ('percent_units', '10', '110'), ('basis_points', '1000', '11000')])
def test_growth_hand_arithmetic_declared_unit(unit, healthy, wrong):
    assert d._growth('110', '100', d.RATE_SCALE[unit]) == (F(healthy), F(wrong))


@pytest.mark.parametrize('current,base', [('0', '10'), ('10', '0'), ('-1', '10'), ('10', '-1')])
def test_growth_never_silently_accepts_zero_or_negative_revenue(current, base):
    with pytest.raises(ValueError, match='positive'):
        d._growth(current, base, 1)


@pytest.fixture
def fixture():
    public = toy(); financial = {}; formulas = {}; literals = {}
    for index, (key, kind) in enumerate(d.schema.points(public), 1):
        financial[key] = {'sheet': "Owner's report", 'cell': 'A'+str(index), 'role': 'given_NA' if kind == 'text' else 'report'}
        (literals if kind == 'text' else formulas)["Owner's report!A"+str(index)] = d.schema.NA if kind == 'text' else '=0'
    digest = d.schema.canonical_sha256(public)
    bindings = {'specification_sha256': digest, 'financial': financial, 'provided_facts': {}, 'provided_context': {}}
    definition = {'specification_sha256': digest, 'formulas': formulas, 'literals': literals}
    mask = [key for key, kind in d.schema.points(public) if kind != 'text'
        and key.split('/')[1].startswith(('2026', '2027', 'FY2026', 'FY2027'))]
    plans = {'kind': 'pure_operating_reports_200_view_plans', 'version': 1, 'FM_mask': mask,
        'DBG_faults': {}, 'actual_D_unknown': True, 'native_calls': 0}
    return public, bindings, definition, plans


def test_toy_complete_class_membership_and_quoted_reference_formulas(fixture):
    public, bindings, definition, original = fixture
    saved = deepcopy(fixture)
    small = d.design(*fixture, 'S800')
    large = d.design(*fixture, 'SG4000')
    assert len(small['DBG_faults']) == 8 and len(large['DBG_faults']) == 24
    assert {k for k in large['DBG_faults'] if k.endswith('/reported_associate_line')} == set(small['DBG_faults'])
    assert {k.split('/')[1] for k in small['DBG_faults']} == set(d.FORECAST)
    assert all("'Owner''s report'!" in r['faulty_formula'] for r in large['DBG_faults'].values())
    assert all(r['healthy_formula'] == '=0' for r in large['DBG_faults'].values())
    assert all(not k.split('/')[1].startswith('2025') for k in large['DBG_faults'])
    assert large['FM_mask'] == original['FM_mask'] and fixture == saved


@pytest.mark.parametrize('problem', ['mask_missing', 'physical_duplicate', 'provided_overlap', 'given_NA', 'missing_formula', 'unknown_variant'])
def test_design_rejects_scope_or_given_mutation(fixture, problem):
    public, bindings, definition, plans = fixture
    key = 'E001/2026Q1/reported_associate_line'
    if problem == 'mask_missing': plans['FM_mask'].pop()
    elif problem == 'physical_duplicate': bindings['financial'][key] = deepcopy(bindings['financial']['E001/2026Q1/revenue'])
    elif problem == 'provided_overlap': bindings['provided_context']['instruction'] = deepcopy(bindings['financial'][key])
    elif problem == 'given_NA': bindings['financial'][key]['role'] = 'given_NA'
    elif problem == 'missing_formula': definition['formulas'].pop(d._physical(bindings['financial'][key]))
    with pytest.raises(ValueError):
        d.design(public, bindings, definition, plans, 'other' if problem == 'unknown_variant' else 'S800')


def test_complete_parsed_leaf_proof_catches_ranges_and_escaped_sheets():
    roots = {'root': {'sheet': "Owner's report", 'cell': 'B2'}}
    assert d._outside_dependents({'formulas': {"Owner's report!B2": '=1', 'Summary!A1': "='Owner''s report'!B3"}}, roots) == []
    observed = d._outside_dependents({'formulas': {'Summary!A1': "=SUM('Owner''s report'!A1:C3)"}}, roots)
    assert observed == [{'destination': 'Summary!A1', 'reference': "'Owner''s report'!A1:C3"}]
    with pytest.raises(ValueError, match='Unsupported source reference'):
        d._outside_dependents({'formulas': {'Summary!A1': '=UnresolvedName'}}, roots)


@pytest.fixture(scope='module')
def retained():
    if not SOURCE.exists():
        pytest.skip('Exact retained C00 artifacts are required; no replacement production forwards')
    refs = d._ancestry(d.reference(SOURCE), d.reference(TASK), d.reference(SIGN))
    public, bindings, definition, plans, A, B = [d.read(refs[key]) for key in
        ('specification', 'bindings', 'healthy_definition', 'original_view_plans', 'retained_A', 'retained_B')]
    designed = {v: d.design(public, bindings, definition, plans, v) for v in d.VARIANTS}
    proofs = {v: d.prove(public, bindings, definition, plans, designed[v], A, B) for v in d.VARIANTS}
    return refs, public, bindings, definition, plans, A, B, designed, proofs


def test_all_production_roots_complete_nonzero_and_full_original_A_B_retained(retained):
    refs, public, bindings, definition, original, A, B, plans, proofs = retained
    sign = {e['id'] for e in public['entities'] if e['statement_sign'] == 'positive_deductions'}
    assert len(sign) == 100
    assert set(plans['S800']['DBG_faults']) == {f'{e}/{q}/reported_associate_line' for e in sign for q in d.FORECAST}
    assert set(plans['SG4000']['DBG_faults'])-set(plans['S800']['DBG_faults']) == {
        f"{e['id']}/{q}/{f}" for e in public['entities'] for q in d.FORECAST for f in ('yoy_percent', 'qoq_percent')}
    for variant, proof in proofs.items():
        assert proof['root_count'] == proof['exact_arithmetic_predicted_D_count'] == d.COUNTS[variant]
        assert proof['all_roots_exact_nonzero_primary_impact'] and proof['outside_root_formula_dependents'] == []
        assert proof['complete_original_A_B_comparison']['points'] == proof['unchanged_full_original_business_fields'] == 93510
        assert set(proof['roots_by_layout']) == set(d.schema.LAYOUTS)
        assert plans[variant]['FM_mask'] == original['FM_mask'] and len(original['FM_mask']) == 62322
        assert proof['new_financial_forwards'] == proof['LO_calls'] == proof['model_calls'] == proof['workbooks_written'] == 0
        assert proof['actual_D_unknown'] and not proof['actual_native_D_or_error_absence_proved']
        for witness in proof['witnesses']:
            assert witness['healthy_primary'] == A['typed_2dp_values'][witness['key']] == B['typed_2dp_values'][witness['key']]
            assert witness['healthy_primary'] != witness['wrong_primary']
            if witness['family'] == 'associate_presentation_sign':
                assert F(witness['wrong_exact']) == -F(witness['healthy_exact'])
            else:
                assert F(witness['wrong_exact'])-F(witness['healthy_exact']) == witness['dependency_values']['ratio_offset']
                assert F(witness['dependency_values']['comparison_revenue']) > 0
    assert proofs['S800']['roots_by_family'] == {'associate_presentation_sign': 800}
    assert proofs['SG4000']['roots_by_family'] == {'associate_presentation_sign': 800, 'ratio_as_quarterly_change': 3200}


@pytest.mark.parametrize('problem', ['omit', 'extra', 'wrong_formula', 'historical', 'variant'])
def test_production_never_accepts_partial_or_edited_class(retained, problem):
    _, public, bindings, definition, original, A, B, plans, _ = retained
    plan = deepcopy(plans['S800']);key = next(iter(plan['DBG_faults']))
    if problem == 'omit': plan['DBG_faults'].pop(key)
    elif problem == 'extra': plan['DBG_faults']['E001/2026Q1/revenue'] = deepcopy(plan['DBG_faults'][key])
    elif problem == 'wrong_formula': plan['DBG_faults'][key]['faulty_formula'] += '+1'
    elif problem == 'historical': plan['DBG_faults'][key.replace('2026', '2025')] = plan['DBG_faults'].pop(key)
    else: plan['variant_id'] = 'SG4000'
    with pytest.raises(ValueError, match='predeclared'):
        d.prove(public, bindings, definition, original, plan, A, B)


def test_zero_impact_root_is_not_filtered(fixture, monkeypatch):
    public, bindings, definition, original = fixture
    plan = d.design(*fixture, 'S800')
    key = next(iter(plan['DBG_faults']));identity, period, _ = key.split('/')
    public['entities'][0]['associate_results'][period] = '0'
    digest = d.schema.canonical_sha256(public)
    bindings['specification_sha256'] = definition['specification_sha256'] = digest
    raw = {key: {'kind': 'rational', 'value': '0'}, f'{identity}/{period}/core_net_income': {'kind': 'rational', 'value': '70'},
        f'{identity}/{period}/net_income': {'kind': 'rational', 'value': '70'}, f'{identity}/{period}/associate_income': {'kind': 'rational', 'value': '0'}}
    result = {'raw_cell_exact_values': raw, 'typed_2dp_values': {key: {'type': 'number', 'value': '0.00'}}}
    monkeypatch.setattr(d.audit, 'compare', lambda *args: {'passed': True})
    with pytest.raises(ValueError, match='nonzero'):
        d.prove(public, bindings, definition, original, plan, result, deepcopy(result))


def test_ancestry_rejects_wrong_source_goal_or_other_raw_before_plans(tmp_path):
    row = {'path': str(tmp_path/'wrong.json'), 'sha256': '0'*64, 'bytes': 0}
    with pytest.raises(ValueError, match='exact original'):
        d._ancestry(row, row, row)


def test_pure_freeze_both_variants_and_replay_without_workbook_or_forward(retained, tmp_path):
    out = tmp_path/'plans'
    row = d.freeze_variants(SOURCE, TASK, SIGN, out)
    frozen = d.validate_frozen(row)
    assert frozen['variant_order'] == ['S800', 'SG4000']
    assert frozen['all_variants_frozen_before_fault_emission']
    assert set(p.name for p in out.iterdir()) == {'prospective.json', 'S800_view_plans.json', 'S800_proof.json', 'SG4000_view_plans.json', 'SG4000_proof.json'}
    assert frozen['workbooks_written'] == frozen['new_financial_forwards'] == frozen['LO_calls'] == frozen['model_calls'] == 0
    assert d.validate_frozen(row, variant='S800')['variant_id'] == 'S800'
    with pytest.raises(ValueError, match='fresh plan'):
        d.freeze_variants(SOURCE, TASK, SIGN, out)
    path = Path(frozen['variants']['SG4000']['view_plans']['path'])
    path.write_bytes(path.read_bytes()+b' ')
    with pytest.raises(ValueError, match='artifact changed'):
        d.validate_frozen(row, variant='S800')  # The unused variant is equally immutable.


def test_reference_rejects_symlink_and_changed_bytes(tmp_path):
    path = tmp_path/'record.json';path.write_text('{}');row = d.reference(path)
    link = tmp_path/'alias.json';link.symlink_to(path)
    with pytest.raises(ValueError, match='regular'):
        d.reference(link)
    path.write_text('{"changed":true}')
    with pytest.raises(ValueError, match='artifact changed'):
        d.read(row)

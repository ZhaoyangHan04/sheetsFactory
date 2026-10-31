"""Pure algebra and frozen-context gates; no workbook emission or services."""
from copy import deepcopy
from itertools import product
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sheets_factory.workbook.linear_capital_ringfenced_group import contract as c, composition as m


def local_fixture(gaps=(7, 3, 9, 11)):
    result = []
    for i, (mandate, profile, gap) in enumerate(zip(c.MANDATE_ORDER, c.PROFILE_ORDER, gaps, strict=True), 1):
        def report(offset):
            return {scenario: {'annual': [{'year': year, 'fiscal_year': 2026 + year,
                **{field: (i * 100000 + s * 10000 + year * 100 + f + offset) * (-1 if field == 'net_lp_cashflow' else 1)
                   for f, field in enumerate(c.GROUP_FIELDS)}} for year in c.YEARS]}
                    for s, scenario in enumerate(c.SCENARIOS, 1)}
        W = 1000 + i * 100
        result.append({'id': mandate, 'profile_id': profile, 'gap_pence': gap,
            'best': {'objective_pence': W, 'plan': {'P001': 1, 'P002': 0}, 'report_A': report(0), 'report_B': report(0)},
            'runner': {'objective_pence': W - gap, 'plan': {'P001': 0, 'P002': 1}, 'report_A': report(23), 'report_B': report(23)}})
    return result


@pytest.mark.parametrize('gaps', [(7, 3, 9, 11), (2, 2, 8, 2), (1, 1, 1, 1)])
def test_composition_exactly_matches_enumerated_cartesian_best_and_runner(gaps):
    locals_ = local_fixture(gaps)
    A, B = m.compose_values_a(locals_), m.compose_values_b(locals_)
    assert A == B
    possibilities = []
    for choices in product(range(3), repeat=4):
        values = [row['best']['objective_pence'] if k == 0 else row['runner']['objective_pence'] if k == 1
                  else row['runner']['objective_pence'] - 17 for row, k in zip(locals_, choices, strict=True)]
        possibilities.append((sum(values), choices))
    ranked = sorted(possibilities, reverse=True)
    assert ranked[0] == (A['winner_objective_pence'], (0, 0, 0, 0))
    assert ranked[1][0] == A['runner_objective_pence']
    assert A['gap_pence'] == min(gaps) and A['unique_best'] is True
    assert A['minimum_gap_mandates'] == [c.MANDATE_ORDER[i] for i, gap in enumerate(gaps) if gap == min(gaps)]
    changed = [i for i in range(4) if A['canonical_runner_plan'][c.MANDATE_ORDER[i]] != A['winner_plan'][c.MANDATE_ORDER[i]]]
    assert changed == [gaps.index(min(gaps))]
    # Concatenating four local runners is generally a strictly worse plan.
    assert sum(row['runner']['objective_pence'] for row in locals_) < A['runner_objective_pence']


def test_all_report_fields_periods_and_scenarios_are_linear_without_rounding_or_netting():
    locals_ = local_fixture(); result = m.compose_values_a(locals_)
    assert result == m.compose_values_b(locals_)
    for scenario in c.SCENARIOS:
        for i in range(20):
            for field in c.GROUP_FIELDS:
                expected = sum(row['best']['report_A'][scenario]['annual'][i][field] for row in locals_)
                assert result['winner_report'][scenario]['annual'][i][field] == expected
                expected_runner = sum(row['runner' if row['id'] == 'M02' else 'best']['report_A'][scenario]['annual'][i][field]
                                      for row in locals_)
                assert result['canonical_runner_report'][scenario]['annual'][i][field] == expected_runner
    assert len([1 for s in result['winner_report'].values() for r in s['annual'] for f in c.GROUP_FIELDS]) == 300


def test_signed_objectives_and_negative_cashflows_are_not_discarded():
    locals_ = local_fixture()
    for row in locals_:
        row['best']['objective_pence'] -= 2000; row['runner']['objective_pence'] -= 2000
    result = m.compose_values_a(locals_)
    assert result == m.compose_values_b(locals_) and result['winner_objective_pence'] < 0


@pytest.mark.parametrize('bad', [0, -1, True, 0.5])
def test_nonpositive_or_noninteger_local_gaps_fail_closed(bad):
    rows = local_fixture(); rows[0]['gap_pence'] = bad
    rows[0]['runner']['objective_pence'] = rows[0]['best']['objective_pence'] - bad
    for implementation in (m.compose_values_a, m.compose_values_b):
        with pytest.raises(ValueError): implementation(rows)


def test_identical_winner_runner_and_incomplete_quartet_are_rejected():
    rows = local_fixture(); rows[0]['runner']['plan'] = deepcopy(rows[0]['best']['plan'])
    for implementation in (m.compose_values_a, m.compose_values_b):
        with pytest.raises(ValueError): implementation(rows)
        with pytest.raises(ValueError): implementation(local_fixture()[:3])


def test_no_mutation_or_shared_plan_aliases():
    rows = local_fixture(); old = deepcopy(rows)
    result = m.compose_values_a(rows); assert rows == old
    result['winner_plan']['M01']['P001'] = 0
    result['winner_report']['S01']['annual'][0]['asset_nbv'] = 0
    assert rows == old


@pytest.mark.parametrize('value', [True, 1.5, 2 ** 53, -(2 ** 53)])
def test_numeric_domain_and_aggregate_exactness_bounds(value):
    rows = local_fixture()
    for side in ('report_A', 'report_B'): rows[0]['best'][side]['S01']['annual'][0]['asset_nbv'] = value
    for implementation in (m.compose_values_a, m.compose_values_b):
        with pytest.raises(ValueError, match='exact integers'): implementation(rows)
    rows = local_fixture()
    for row in rows:
        for side in ('report_A', 'report_B'): row['best'][side]['S01']['annual'][0]['asset_nbv'] = 2 ** 52
    for implementation in (m.compose_values_a, m.compose_values_b):
        with pytest.raises(ValueError, match='exact integers'): implementation(rows)


def test_public_contract_has_fixed_first_quartet_and_no_coupling():
    contexts = [{'id': mandate, 'profile_id': profile, 'specification': {'unit_fixture': profile}}
                for mandate, profile in zip(c.MANDATE_ORDER, c.PROFILE_ORDER, strict=True)]
    public = c.public_contract(contexts)
    assert c.validate_contract(public, contexts) is public
    assert [row['sheet_prefix'] for row in public['mandates']] == ['P01 - ', 'P02 - ', 'P07 - ', 'P09 - ']
    assert public['policies']['cross_mandate_binding_constraints'] == []
    assert public['policies']['intermandate_tax_or_loss_netting'] is False
    assert public['policies']['intermandate_lending'] is False
    assert public['policies']['currency'] == 'GBP'
    assert public['coupled_1440_project_MIP_claimed'] is False
    changed = deepcopy(public); changed['policies']['cross_mandate_binding_constraints'] = ['group_budget']
    with pytest.raises(ValueError, match='ringfencing'): c.validate_contract(changed, contexts)
    with pytest.raises(ValueError, match='fixed complete'): c.public_contract(contexts[::-1])


def test_genuine_first_pilot_metadata_exists_without_hydrating_reference_bodies():
    contexts = c.first_pilot_inventory()
    assert [row['profile_id'] for row in contexts] == list(c.PROFILE_ORDER)
    assert [row['reference']['sha256'] for row in contexts] == [
        'df23daf7ab2f83eb2ca5a40b06b419bacb612a9aa1208e8b9d54ed95e61e56d0',
        '40fe7fd578d6c10daaabc133584c275055cbc654b3eb1e93f9e164615bbfc860',
        '8c37cee51064616639610bea98ce5ca4cd244d421cfa47364a749d965fc06e3d',
        '367b0e24a30dc22a70c76b915a0715511e8842f4e2254a2cc6e8545a7b1a3e1b']


def test_prospective_is_frozen_before_either_cold_validator_and_cannot_be_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(c, 'ROOT', tmp_path)
    monkeypatch.setattr(c, 'recipes', lambda: {'unit_protocol': 'no_services'})
    output = tmp_path / 'outputs' / 'prospective'
    record = c.freeze_first_pilot(output); frozen = c.validate_prospective(record)
    assert frozen['reference_or_source_admission_performed'] is False
    assert frozen['all_assignments_fixed_before_full_reference_hydration'] is True
    assert frozen['workbooks_written'] == frozen['solver_calls'] == frozen['LO_calls'] == frozen['model_calls'] == 0
    with pytest.raises(ValueError, match='fresh private'): c.freeze_first_pilot(output)
    public_path = Path(frozen['contract']['path']); public = json.loads(public_path.read_text())
    public['policies']['intermandate_lending'] = True; public_path.write_text(json.dumps(public))
    with pytest.raises(ValueError, match='reference changed'): c.validate_prospective(record)


def test_cold_reference_validator_is_first_and_json_flags_cannot_replace_it():
    called = []
    def rejected(value): called.append('reference'); raise ValueError('A real complete reference is missing')
    source = SimpleNamespace(validate_source=lambda value: pytest.fail('Source admission must follow strict reference admission'))
    with pytest.raises(ValueError, match='real complete'):
        m._hydrate({'reference': {'passed': True}}, SimpleNamespace(validate_completed=rejected), source)
    assert called == ['reference']


def hydrated_fixture(tmp_path):
    rows = local_fixture()
    for row in rows:
        row['geometry'] = deepcopy(m.LOCAL_GEOMETRY)
        for field in ('reference', 'source_manifest', 'workbook', 'specification', 'model_A', 'model_B',
                      'best_solver_receipt', 'excluded_runner_solver_receipt', 'best_solver_validation',
                      'runner_solver_validation', 'whole_financial_validation'):
            row[field] = {'unit_fixture': row['id'] + '/' + field}
    contexts = [{'id': row['id'], 'profile_id': row['profile_id'], 'specification': row['specification']} for row in rows]
    path = tmp_path / 'contract.json'; path.write_text(json.dumps(c.public_contract(contexts)))
    return rows, {'contract': c.reference(path), 'contexts': contexts}


def test_complete_composition_orchestration_keeps_all_four_and_no_quality_inheritance(tmp_path, monkeypatch):
    rows, frozen = hydrated_fixture(tmp_path); visited = []
    provider = SimpleNamespace(recipes=lambda: {'unit_mock': 'no_services'})
    monkeypatch.setattr(m, '_providers', lambda: (provider, provider))
    def hydrate(context, reference_provider, source_provider):
        visited.append(context['id']); return deepcopy(rows[c.MANDATE_ORDER.index(context['id'])])
    monkeypatch.setattr(m, '_hydrate', hydrate)
    result = m._compose(frozen)
    assert visited == list(c.MANDATE_ORDER) and len(result['local_whole_evidence']) == 4
    assert result['composition'] == m.compose_values_b(rows)
    assert result['mathematical_composition_certified'] is True
    assert result['new_group_source_admitted'] is result['qualified'] is result['normal_task_quality_passed'] is False
    assert result['difficulty_qualified'] is result['local_quality_or_development_inherited'] is False
    assert result['new_solver_calls'] == result['LO_calls'] == result['model_calls'] == result['workbooks_written'] == 0
    assert result['geometry_before_global_header_and_reports']['physical_formulas'] == 4989312
    assert result['geometry_before_global_header_and_reports']['profile_targets_including_360_choices'] == 6088748
    assert result['FM_mask_projection_including_four_completion_gates'] == 6088752
    assert result['proof']['all_possible_global_runner_vectors_enumerated'] is False


def test_all_four_cold_gates_and_independent_report_comparison_precede_any_output(tmp_path, monkeypatch):
    rows, frozen = hydrated_fixture(tmp_path)
    monkeypatch.setattr(c, 'ROOT', tmp_path)
    monkeypatch.setattr(c, 'validate_prospective', lambda _: frozen)
    provider = SimpleNamespace(recipes=lambda: {})
    monkeypatch.setattr(m, '_providers', lambda: (provider, provider))
    visited = []
    def failed(context, *_):
        visited.append(context['id'])
        if context['id'] == 'M04': raise ValueError('Retained fourth source proof failed')
        return deepcopy(rows[c.MANDATE_ORDER.index(context['id'])])
    monkeypatch.setattr(m, '_hydrate', failed)
    output = tmp_path / 'outputs' / 'certificate'
    with pytest.raises(ValueError, match='fourth source'): m.build_certificate({}, output)
    assert visited == list(c.MANDATE_ORDER) and not output.exists()
    rows[0]['best']['report_B']['S01']['annual'][0]['asset_nbv'] += 1
    monkeypatch.setattr(m, '_hydrate', lambda context, *_: deepcopy(rows[c.MANDATE_ORDER.index(context['id'])]))
    with pytest.raises(ValueError, match='independent group'): m.build_certificate({}, output)
    assert not output.exists()


def test_genuine_frozen_validator_imports_are_service_free():
    reference, source = m._providers()
    assert reference.KIND == 'linear_capital_scaled_producer16_best_runner_dual_financial_reference'
    assert source.SOURCE_KIND == 'independently_verified_linear_capital_scaled_native_source'
    assert m.LOCAL_GEOMETRY['profile_targets_including_360_choices'] + 1 == 1522188

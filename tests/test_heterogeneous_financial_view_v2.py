"""Hand-written tiny scopes only; no actual source, materialization or LO."""
from copy import deepcopy
import json

import openpyxl
import pytest

from sheets_factory.task_adapters import heterogeneous_financial_view as parent
from sheets_factory.task_adapters import heterogeneous_financial_view_v2 as view


def target(field, month=0, *, value=0, kind='integer', row=4):
    source = {'sheet': 'S01 Entity Close', 'cell': 'D' + str(row),
        'expected_path': ['scenarios', 'S01', 'entities', 'E01', 'monthly', month, field],
        'kind': kind, 'worksheet_scale': 100 if kind == 'money_pence' else 1,
        'formula': '=0', 'expression': 0, 'semantic_owner': [], 'is_complete_answer': kind == 'money_pence'}
    return {'source': source, 'sheet': 'S01 Covenants', 'cell': ('E' if month == 0 else 'F') + str(row),
        'descriptor_row': row, 'descriptors': ['E01', 'Covenants', parent._label(field),
            'GBP' if kind == 'money_pence' else 'count'], 'number_format': '0',
        'reference_value': parent._typed(value)}


def tiny_base():
    targets = []
    for month in range(2):
        for field, kind, value, row in [('cfads', 'money_pence', 0, 4),
                ('trap_open', 'flag', 1, 5), ('test_pass', 'nullable_flag', None, 6),
                ('dscr_ratio_millionths', 'nullable_ratio_micro', None, 7),
                ('cure_open', 'integer', 2, 8), ('cure_next', 'integer', 2, 9)]:
            targets.append(target(field, month, value=value, kind=kind, row=row))
    return {'months': ['2027-01-01', '2027-02-01'], 'scenario_ids': ['S01'],
        'sheet_order': ['Contract Notes', 'Entity Policies', 'S01 Covenants'],
        'provided_cells': [{'sheet': 'Contract Notes', 'cell': 'A1', 'value': parent._typed('Policy'),
                'number_format': 'General'},
            {'sheet': 'Contract Notes', 'cell': 'B1', 'value': parent._typed('Two observed passes clear a restriction.'),
                'number_format': 'General'},
            {'sheet': 'Entity Policies', 'cell': 'N2', 'value': parent._typed(0), 'number_format': '0'}],
        'forecast_targets': targets, 'declared_slot_count': len(targets),
        'scope_counts': {'business_targets': len(targets), 'target_kinds': {}, 'queue_total_aliases': 1},
        'queue_total_same_account_alias_evidence': [{'hand_written_alias_evidence_not_source_proof': True}],
        'engineering_only_fixture_not_source_proof': True}


def test_default_off_before_source_read(monkeypatch, tmp_path):
    monkeypatch.setattr(parent, 'build_view_plan', lambda *a, **k: pytest.fail('Read a source while off'))
    assert view.setting()['enabled'] is False
    with pytest.raises(view.ViewError, match='default off'):
        view.build_view_plan(tmp_path / 'missing')
    with pytest.raises(view.ViewError, match='default off'):
        view.materialize_view({}, tmp_path / 'missing')


@pytest.mark.parametrize('enabled', [1, 'true', None])
def test_opt_in_must_be_bool(enabled):
    with pytest.raises(view.ViewError):
        view.setting(enabled=enabled)


def test_setting_binds_own_and_parent_code_and_policies():
    setting = view.setting(enabled=True)
    assert setting['implementation'] == view.reference(view.__file__)
    assert setting['policy'] == view.reference(view.DEFAULT_POLICY)
    assert setting['parent_implementation'] == view.reference(parent.__file__)
    assert setting['parent_policy'] == view.reference(parent.DEFAULT_POLICY)
    assert setting['source_builder'] == view.reference(parent.SOURCE_BUILDER)


@pytest.mark.parametrize('change', ['boolean_version', 'exclude_financial_flag', 'missing_asset_policy'])
def test_altered_layout_policy_rejected(tmp_path, change):
    declared = view.policy()
    if change == 'boolean_version':
        declared['version'] = True
    elif change == 'exclude_financial_flag':
        declared['excluded_counter_fields'].append('trap_open')
    else:
        declared['asset_policy_note'] = ''
    path = tmp_path / 'changed.json'
    path.write_text(json.dumps(declared))
    with pytest.raises(view.ViewError):
        view.policy(path)


def test_counter_scope_only_retains_exact_all_other_values_positions_and_aliases():
    base = tiny_base()
    original = deepcopy(base)
    result = view._revise_scope(base, view.policy())
    expected = [r for r in base['forecast_targets'] if r['source']['expected_path'][-1] not in view._COUNTERS]
    assert base == original
    assert result['forecast_targets'] == expected
    assert result['provided_cells'][:len(base['provided_cells'])] == base['provided_cells']
    assert result['queue_total_same_account_alias_evidence'] == base['queue_total_same_account_alias_evidence']
    assert result['declared_slot_count'] == 8
    assert result['scope_revision']['excluded_internal_counter_slots'] == 4
    assert result['scope_counts']['target_kinds'] == {
        'money_pence': 2, 'flag': 2, 'nullable_flag': 2, 'nullable_ratio_micro': 2}
    assert result['scope_revision']['new_actual_changed_value_set_pending'] is True
    assert all(r['reference_value'] == parent._typed(0)
        for r in result['forecast_targets'] if r['source']['kind'] == 'money_pence')


def test_only_asset_note_is_added_and_opening_cure_input_is_preserved():
    base = tiny_base()
    result = view._revise_scope(base, view.policy())
    added = result['provided_cells'][len(base['provided_cells']):]
    assert [(r['sheet'], r['cell']) for r in added] == [('Contract Notes', 'A2'), ('Contract Notes', 'B2')]
    assert parent._untyped(added[1]['value']) == view.policy()['asset_policy_note']
    assert next(r for r in result['provided_cells'] if r['sheet'] == 'Entity Policies')['value'] == parent._typed(0)
    text = view.policy()['asset_policy_note']
    for phrase in ['commissioning month', 'following month', 'original cost', 'useful-life months',
            'halves away from zero', 'remaining net book value', 'opening accumulated depreciation']:
        assert phrase in text
    assert all(word not in text for word in ['A01N', '65000', '1354', 'cure_open', 'expected_path'])


@pytest.mark.parametrize('tamper', ['missing_pair', 'outside_entities', 'wrong_kind', 'boolean_scale', 'duplicate', 'scope_count'])
def test_counter_removal_cannot_silently_drop_or_expand_scope(tamper):
    base = tiny_base()
    if tamper == 'missing_pair':
        base['forecast_targets'].pop()
        base['declared_slot_count'] -= 1
    elif tamper == 'outside_entities':
        base['forecast_targets'][-1]['source']['expected_path'][2] = 'loans'
    elif tamper == 'wrong_kind':
        base['forecast_targets'][-1]['source']['kind'] = 'money_pence'
    elif tamper == 'boolean_scale':
        base['forecast_targets'][-1]['source']['worksheet_scale'] = True
    elif tamper == 'duplicate':
        base['forecast_targets'].append(deepcopy(base['forecast_targets'][-1]))
        base['declared_slot_count'] += 1
    else:
        base['declared_slot_count'] += 1
    with pytest.raises(view.ViewError):
        view._revise_scope(base, view.policy())


def test_tiny_low_level_written_scope_has_no_cure_rows_and_keeps_policy_na(tmp_path):
    plan = view._revise_scope(tiny_base(), view.policy())
    paths = []
    for masked, name in [(True, 'input.xlsx'), (False, 'goal.xlsx')]:
        book = parent._book_from_plan(plan, masked=masked)
        path = tmp_path / name
        try:
            book.save(path)
        finally:
            book.close()
        paths.append(path)
    audit = view.validate_view(plan, *paths)
    assert audit['declared_business_slots'] == 8
    assert audit['expected_changed_value_count_before_actual_normalization'] == 4
    assert audit['actual_LO_calls'] == 0 and audit['source_or_quality_certified'] is False
    book = openpyxl.load_workbook(paths[1])
    try:
        assert book['S01 Covenants']['E4'].value == 0
        assert book['S01 Covenants']['E5'].value == 1
        assert book['S01 Covenants']['E6'].value is None
        assert book['S01 Covenants']['E7'].value is None
        assert book['S01 Covenants']['C8'].value is None
        assert book['S01 Covenants']['C9'].value is None
        assert book['Contract Notes']['B2'].value == view.policy()['asset_policy_note']
    finally:
        book.close()


def test_public_brief_preserves_business_scope_without_implementation_hints():
    assert view.public_brief() == parent.public_brief()
    assert 'including zero' in view.public_brief()
    assert 'policy-defined blank' in view.public_brief()
    assert all(s not in view.public_brief() for s in ['cure_open', 'cure_next', 'expected_path', 'source_manifest'])


def test_full_declared_dimensions_remove_864_synthetic_counters_without_value_selection():
    # Scope-only fixture: no production source values or workbook are created.
    base = tiny_base()
    base['forecast_targets'] = []
    for scenario in range(1, 4):
        for entity in range(1, 7):
            for month in range(24):
                for field in ['trap_open', 'cure_open', 'cure_next']:
                    r = target(field, value=(month + entity) % 3,
                        kind='flag' if field == 'trap_open' else 'integer')
                    r['source']['expected_path'][1] = f'S{scenario:02d}'
                    r['source']['expected_path'][3] = f'E{entity:02d}'
                    r['source']['expected_path'][5] = month
                    r['sheet'] = f'S{scenario:02d} Covenants'
                    r['cell'] = f'E{len(base["forecast_targets"]) + 4}'
                    base['forecast_targets'].append(r)
    base['declared_slot_count'] = len(base['forecast_targets'])
    result = view._revise_scope(base, view.policy())
    assert result['scope_revision']['excluded_internal_counter_slots'] == 864
    assert len(result['forecast_targets']) == 432
    assert {r['source']['expected_path'][-1] for r in result['forecast_targets']} == {'trap_open'}


def test_builder_uses_parent_cold_admission_and_binds_own_revision(monkeypatch):
    # An explicit test double isolates routing; it is not a real admission.
    base = tiny_base()
    base.update(kind='planned_heterogeneous_business_financial_view', version=1,
        adapter=parent.ADAPTER_ID, setting=parent.setting(enabled=True),
        source_admission={'kind': 'unit_fixture_not_source_certificate'},
        quality_or_difficulty_certified=False)
    base['plan_sha256'] = view.canonical(base)
    calls = []
    def checked_parent(source, *, enabled):
        calls.append((source, enabled))
        return deepcopy(base)
    monkeypatch.setattr(parent, 'build_view_plan', checked_parent)
    result = view.build_view_plan('unit-fixture-only', enabled=True)
    assert calls == [('unit-fixture-only', True)]
    assert result['version'] == 2 and result['setting'] == view.setting(enabled=True)
    assert result['source_admission'] == base['source_admission']
    assert result['parent_projection_provenance']['parent_plan_sha256'] == base['plan_sha256']
    assert result['parent_projection_provenance']['parent_quality_or_difficulty_evidence_transferred'] is False
    assert result['quality_or_difficulty_certified'] is False and result['actual_projection_LO_calls'] == 0
    assert result['plan_sha256'] == view.canonical({k: v for k, v in result.items() if k != 'plan_sha256'})


@pytest.mark.parametrize('tamper', ['parent_digest', 'parent_implementation', 'boolean_version'])
def test_parent_plan_identity_tamper_rejected_before_scope_projection(monkeypatch, tamper):
    base = tiny_base()
    base.update(kind='planned_heterogeneous_business_financial_view', version=1,
        adapter=parent.ADAPTER_ID, setting=parent.setting(enabled=True))
    base['plan_sha256'] = view.canonical(base)
    if tamper == 'parent_digest':
        base['plan_sha256'] = '0' * 64
    elif tamper == 'parent_implementation':
        base['setting']['implementation']['sha256'] = '0' * 64
    else:
        base['version'] = True
    monkeypatch.setattr(parent, 'build_view_plan', lambda *a, **k: base)
    with pytest.raises(view.ViewError, match='parent plan'):
        view.build_view_plan('unit-fixture-only', enabled=True)


@pytest.mark.parametrize('wrong_kind', [
    'planned_heterogeneous_business_financial_view', 'complete_offline_math_probe', None])
def test_materialization_never_accepts_old_or_probe_plan(tmp_path, wrong_kind):
    with pytest.raises(view.ViewError):
        view.materialize_view({'kind': wrong_kind}, tmp_path / 'unused', enabled=True)
    assert not (tmp_path / 'unused').exists()


@pytest.mark.parametrize('tamper', ['typed_value', 'parent_recipe', 'own_recipe', 'new_policy'])
def test_materialize_cold_rebuild_rejects_modified_plan_before_any_write(monkeypatch, tmp_path, tamper):
    # This exercises the equality gate only. No synthetic admission is accepted
    # as a real source, and no workbook is materialized.
    checked = {'kind': 'planned_heterogeneous_business_financial_view_v2', 'version': 2,
        'adapter': view.ADAPTER_ID, 'source_admission': {'source_manifest': {'hand_fixture': True}},
        'setting': view.setting(enabled=True), 'forecast_targets': [{'reference_value': ['number', '0']}],
        'scope_revision': {'asset_note': view.policy()['asset_policy_note']}}
    modified = deepcopy(checked)
    if tamper == 'typed_value':
        modified['forecast_targets'][0]['reference_value'] = ['number', '1']
    elif tamper == 'parent_recipe':
        modified['setting']['parent_implementation']['sha256'] = '0' * 64
    elif tamper == 'own_recipe':
        modified['setting']['implementation']['sha256'] = '0' * 64
    else:
        modified['scope_revision']['asset_note'] = 'Other convention'
    called = []
    def rebuild(source, *, enabled):
        called.append((source, enabled))
        return checked
    monkeypatch.setattr(view, 'build_view_plan', rebuild)
    with pytest.raises(view.ViewError, match='changed'):
        view.materialize_view(modified, tmp_path / 'unused', enabled=True)
    assert called == [(checked['source_admission']['source_manifest'], True)]
    assert not (tmp_path / 'unused').exists()


def test_offline_census_does_not_claim_new_D_or_quality():
    counts = view.policy()['offline_prototype_census_not_source_certificate']
    assert counts['parent_business_slots'] - counts['excluded_internal_counter_slots'] == counts['retained_business_slots'] == 99432
    assert counts['new_actual_changed_value_set_count'] is None
    assert 'actual_Harbor_controls' in view.PENDING

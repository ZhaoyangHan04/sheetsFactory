"""Scope-only fixtures; no actual source admission, financial forward or Calc."""
from copy import deepcopy
import json

import openpyxl
from openpyxl.utils.cell import get_column_letter
import pytest

from sheets_factory.task_adapters import heterogeneous_financial_view as original
from sheets_factory.task_adapters import heterogeneous_financial_view_v2 as parent
from sheets_factory.task_adapters import heterogeneous_financial_view_v3 as view


def target(field, month, row, *, sid='S01', entity='E01', kind='money_pence', value=0):
    sheet = sid + (' Covenants' if field in ('trap_open', 'trap_operative', 'trap_next',
        'test_pass', 'dscr_ratio_millionths') else ' Statements')
    source = {'sheet': sid + ' Entity Close', 'cell': 'D' + str(row),
        'expected_path': ['scenarios', sid, 'entities', entity, 'monthly', month, field],
        'kind': kind, 'worksheet_scale': {'money_pence': 100, 'flag': 1,
            'nullable_flag': 1, 'nullable_ratio_micro': 10**6}[kind],
        'formula': '=0', 'expression': 0, 'semantic_owner': [],
        'is_complete_answer': kind == 'money_pence'}
    return {'source': source, 'sheet': sheet, 'cell': get_column_letter(month + 5) + str(row),
        'descriptor_row': row, 'descriptors': [entity,
            'Covenants' if sheet.endswith('Covenants') else 'Statements', original._label(field),
            'GBP' if kind == 'money_pence' else '0/1'], 'number_format': '0.00',
        'reference_value': original._typed(value)}


def tiny_parent():
    targets = []
    for month in range(2):
        for field, row, kind, value in [
                ('cash_open', 4, 'money_pence', 5),
                ('cash_before_financing', 5, 'money_pence', 0),
                ('cash_close', 6, 'money_pence', 6),
                ('reserve_close', 7, 'money_pence', 2),
                ('cfo', 8, 'money_pence', 1), ('cfi', 9, 'money_pence', 0),
                ('cff', 10, 'money_pence', 0), ('cash_delta', 11, 'money_pence', 1),
                ('cash_check', 12, 'money_pence', 0),
                ('trap_open', 4, 'flag', 0), ('trap_operative', 5, 'flag', month),
                ('trap_next', 6, 'flag', 1), ('test_pass', 7, 'nullable_flag', None),
                ('dscr_ratio_millionths', 8, 'nullable_ratio_micro', None)]:
            targets.append(target(field, month, row, kind=kind, value=value))
    return {'months': ['2027-01-01', '2027-02-01'], 'scenario_ids': ['S01'],
        'sheet_order': ['Contract Notes', 'Opening Balances', 'S01 Statements', 'S01 Covenants'],
        'provided_cells': [{'sheet': 'Contract Notes', 'cell': 'A1',
            'value': original._typed('Public policies'), 'number_format': 'General'},
            {'sheet': 'Contract Notes', 'cell': 'B1',
            'value': original._typed('Use supplied facility and reserve policies.'),
            'number_format': 'General'}, {'sheet': 'Opening Balances', 'cell': 'B2',
            'value': original._typed(0), 'number_format': '0.00'}],
        'forecast_targets': targets, 'declared_slot_count': len(targets),
        'scope_counts': {'business_targets': len(targets), 'target_kinds': {},
            'excluded_internal_cure_counter_slots': 4},
        'scope_revision': {'excluded_fields': ['cure_open', 'cure_next']},
        'queue_total_same_account_alias_evidence': [{'fixture_not_a_source_proof': True}],
        'original_brief': parent.public_brief(), 'engineering_only_fixture': True}


def admitted_parent_fixture():
    base = tiny_parent()
    base.update(kind='planned_heterogeneous_business_financial_view_v2', version=2,
        adapter=parent.ADAPTER_ID, setting=parent.setting(enabled=True),
        source_admission={'source_manifest': {'fixture_not_a_source_proof': True}})
    base['plan_sha256'] = view.canonical(base)
    return base


def test_default_off_never_reads_source(monkeypatch, tmp_path):
    monkeypatch.setattr(parent, 'build_view_plan', lambda *a, **k: pytest.fail('Unexpected source read'))
    with pytest.raises(view.ViewError, match='default off'):
        view.build_view_plan(tmp_path / 'absent')
    with pytest.raises(view.ViewError, match='default off'):
        view.materialize_view({}, tmp_path / 'absent')


@pytest.mark.parametrize('bad', [1, 'true', None])
def test_explicit_boolean_setting_required(bad):
    with pytest.raises(view.ViewError):
        view.setting(enabled=bad)


def test_setting_binds_all_parent_recipes_and_source_builder():
    s = view.setting(enabled=True)
    assert s['version'] == 3 and s['adapter'] == view.ADAPTER_ID
    assert s['implementation'] == view.reference(view.__file__)
    assert s['policy'] == view.reference(view.DEFAULT_POLICY)
    assert s['parent_implementation'] == view.reference(parent.__file__)
    assert s['parent_policy'] == view.reference(parent.DEFAULT_POLICY)
    assert s['parent_setting'] == parent.setting(enabled=True)
    assert s['parent_setting']['parent_implementation'] == view.reference(original.__file__)
    assert s['source_builder'] == view.reference(original.SOURCE_BUILDER)


@pytest.mark.parametrize('change', ['version', 'parent', 'cash_delta', 'policy_text'])
def test_only_predeclared_exact_policy_accepted(tmp_path, change):
    p = view.policy()
    if change == 'version':
        p['version'] = True
    elif change == 'parent':
        p['parent_adapter'] = original.ADAPTER_ID
    elif change == 'cash_delta':
        p['excluded_display_fields'].append('cash_delta')
    else:
        p['public_notes_and_instruction'] = 'Add explanatory formulas'
    f = tmp_path / 'policy.json'
    f.write_text(json.dumps(p))
    with pytest.raises(view.ViewError):
        view.policy(f)


def test_exact_whole_row_removal_preserves_money_states_policy_and_source_values():
    base = tiny_parent()
    unchanged = deepcopy(base)
    revised = view._revise_scope(base, view.policy())
    assert base == unchanged
    assert revised['declared_slot_count'] == 24
    assert revised['provided_cells'] == base['provided_cells']
    assert revised['original_brief'] == base['original_brief']
    assert revised['queue_total_same_account_alias_evidence'] == base['queue_total_same_account_alias_evidence']
    assert revised['parent_scope_revision'] == base['scope_revision']
    assert revised['scope_revision']['deleted_rows_by_sheet'] == {
        'S01 Covenants': [5], 'S01 Statements': [5]}
    kept = {tuple(t['source']['expected_path']): t for t in revised['forecast_targets']}
    for before in base['forecast_targets']:
        key = tuple(before['source']['expected_path'])
        if key[-1] in view._EXCLUDED:
            assert key not in kept
            continue
        after = kept[key]
        assert after['source'] == before['source']
        assert after['reference_value'] == before['reference_value']
        assert after['descriptors'] == before['descriptors']
        assert after['number_format'] == before['number_format']
        assert after['descriptor_row'] == before['descriptor_row'] - (before['descriptor_row'] > 5)
    assert {'cfo', 'cfi', 'cff', 'cash_delta', 'cash_check', 'reserve_close', 'trap_next'} <= {
        p[-1] for p in kept}


def test_no_value_dependent_selection_including_zeros_and_flags():
    a = tiny_parent()
    b = deepcopy(a)
    for t in b['forecast_targets']:
        t['reference_value'] = original._typed(-123.45 if t['source']['kind'] == 'money_pence' else 0)
    ra = view._revise_scope(a, view.policy())
    rb = view._revise_scope(b, view.policy())
    assert [(x['sheet'], x['cell'], x['source']) for x in ra['forecast_targets']] == [
        (x['sheet'], x['cell'], x['source']) for x in rb['forecast_targets']]
    assert ra['scope_revision']['deleted_rows_by_sheet'] == rb['scope_revision']['deleted_rows_by_sheet']


@pytest.mark.parametrize('tamper', ['missing_field', 'wrong_domain', 'wrong_kind', 'bool_scale',
    'duplicate_cell', 'duplicate_logical', 'wrong_descriptor_row', 'mixed_account_row',
    'incomplete_calendar', 'provided_literal_on_removed_row', 'count'])
def test_partial_or_unclear_whole_row_scope_is_rejected(tamper):
    base = tiny_parent()
    selected = next(t for t in base['forecast_targets'] if t['source']['expected_path'][-1] == 'trap_operative')
    if tamper == 'missing_field':
        base['forecast_targets'].remove(selected)
    elif tamper == 'wrong_domain':
        selected['source']['expected_path'][2] = 'loans'
    elif tamper == 'wrong_kind':
        selected['source']['kind'] = 'integer'
    elif tamper == 'bool_scale':
        selected['source']['worksheet_scale'] = True
    elif tamper == 'duplicate_cell':
        base['forecast_targets'].append(deepcopy(selected))
    elif tamper == 'duplicate_logical':
        other = deepcopy(selected)
        other['cell'] = 'G5'
        base['forecast_targets'].append(other)
    elif tamper == 'wrong_descriptor_row':
        selected['descriptor_row'] += 1
    elif tamper == 'mixed_account_row':
        other = target('cfads', 0, 5, kind='money_pence')
        other['sheet'] = 'S01 Covenants'
        other['cell'] = 'G5'
        base['forecast_targets'].append(other)
    elif tamper == 'incomplete_calendar':
        # Missing one complete period for both excluded fields must not let a
        # shorter removed row silently pass the complete calendar requirement.
        base['forecast_targets'] = [t for t in base['forecast_targets']
            if not (t['source']['expected_path'][-1] in view._EXCLUDED
                and t['source']['expected_path'][5] == 1)]
        base['forecast_targets'] = [t for t in base['forecast_targets']
            if t['source']['expected_path'][5] == 0]
    elif tamper == 'provided_literal_on_removed_row':
        base['provided_cells'].append({'sheet': 'S01 Covenants', 'cell': 'A5',
            'value': original._typed('Required input'), 'number_format': 'General'})
    else:
        base['declared_slot_count'] += 1
    if tamper != 'count':
        base['declared_slot_count'] = len(base['forecast_targets'])
    with pytest.raises(view.ViewError):
        view._revise_scope(base, view.policy())


def test_retained_literal_below_deleted_row_is_moved_without_value_change():
    base = tiny_parent()
    base['provided_cells'].append({'sheet': 'S01 Covenants', 'cell': 'A20',
        'value': original._typed('Unchanged optional caption'), 'number_format': 'General'})
    after = view._revise_scope(base, view.policy())['provided_cells'][-1]
    assert after == dict(base['provided_cells'][-1], cell='A19')


def test_only_tiny_synthetic_serialization_scope_has_no_excluded_public_rows(tmp_path):
    plan = view._revise_scope(tiny_parent(), view.policy())
    paths = []
    for masked, name in [(True, 'input.xlsx'), (False, 'goal.xlsx')]:
        b = original._book_from_plan(plan, masked=masked)
        path = tmp_path / name
        b.save(path)
        b.close()
        paths.append(path)
    audit = view.validate_view(plan, *paths)
    assert audit['declared_business_slots'] == 24
    assert audit['expected_changed_value_count_before_actual_normalization'] == 20
    assert audit['actual_LO_calls'] == 0 and audit['source_or_quality_certified'] is False
    b = openpyxl.load_workbook(paths[1])
    try:
        assert b['S01 Statements']['C5'].value == 'Cash close'
        assert b['S01 Statements']['C10'].value == 'Cash delta'
        assert b['S01 Statements']['E10'].value == 1
        assert b['S01 Covenants']['C5'].value == 'Restriction at next month opening'
        assert b['S01 Covenants']['E6'].value is None
        for sheet in b:
            assert all(c.value not in ('Cash before financing', 'Restriction applying this month')
                for row in sheet for c in row)
    finally:
        b.close()


def test_full_dimension_scope_fixture_removes_all_864_slots_and_36_rows():
    base = tiny_parent()
    base['months'] = [f'{y}-{m:02d}-01' for y in (2027, 2028) for m in range(1, 13)]
    base['scenario_ids'] = ['S01', 'S02', 'S03']
    base['sheet_order'] = ['Contract Notes', 'Opening Balances'] + [
        sid + ' ' + label for sid in base['scenario_ids'] for label in ('Statements', 'Covenants')]
    base['forecast_targets'] = []
    for sid in base['scenario_ids']:
        for entity in range(1, 7):
            for month in range(24):
                for field, kind, row in [('cash_before_financing', 'money_pence', 4),
                        ('cash_delta', 'money_pence', 5), ('trap_operative', 'flag', 4),
                        ('trap_next', 'flag', 5)]:
                    base['forecast_targets'].append(target(field, month, row + (entity - 1) * 2,
                        sid=sid, entity=f'E{entity:02d}', kind=kind, value=0))
    base['declared_slot_count'] = len(base['forecast_targets'])
    after = view._revise_scope(base, view.policy())
    assert after['scope_revision']['excluded_intermediate_display_slots'] == 864
    assert after['scope_revision']['removed_account_rows'] == 36
    assert len(after['forecast_targets']) == 864
    assert {t['source']['expected_path'][-1] for t in after['forecast_targets']} == {'cash_delta', 'trap_next'}


def test_cold_parent_admission_called_and_all_ancestry_bound(monkeypatch):
    base = admitted_parent_fixture()
    calls = []
    def cold(source, *, enabled):
        calls.append((source, enabled))
        return deepcopy(base)
    monkeypatch.setattr(parent, 'build_view_plan', cold)
    after = view.build_view_plan('explicit-test-double-not-source', enabled=True)
    assert calls == [('explicit-test-double-not-source', True)]
    assert after['version'] == 3 and after['adapter'] == view.ADAPTER_ID
    assert after['source_admission'] == base['source_admission']
    assert after['parent_projection_provenance']['parent_plan_sha256'] == base['plan_sha256']
    assert after['parent_projection_provenance']['parent_setting'] == parent.setting(enabled=True)
    assert after['parent_projection_provenance']['parent_quality_or_difficulty_evidence_transferred'] is False
    assert after['quality_or_difficulty_certified'] is False and after['actual_projection_LO_calls'] == 0
    assert after['plan_sha256'] == view.canonical({k: v for k, v in after.items() if k != 'plan_sha256'})


@pytest.mark.parametrize('tamper', ['digest', 'parent_code', 'grandparent_code', 'bool_version'])
def test_cold_parent_recipe_or_identity_tamper_rejected(monkeypatch, tamper):
    base = admitted_parent_fixture()
    if tamper == 'digest':
        base['plan_sha256'] = '0' * 64
    elif tamper == 'parent_code':
        base['setting']['implementation']['sha256'] = '0' * 64
    elif tamper == 'grandparent_code':
        base['setting']['parent_implementation']['sha256'] = '0' * 64
    else:
        base['version'] = True
    monkeypatch.setattr(parent, 'build_view_plan', lambda *a, **k: base)
    with pytest.raises(view.ViewError, match='parent plan'):
        view.build_view_plan('test-only', enabled=True)


@pytest.mark.parametrize('version,kind', [(1, 'planned_heterogeneous_business_financial_view'),
    (2, 'planned_heterogeneous_business_financial_view_v2'), (True, None)])
def test_materialize_rejects_prior_or_probe_identity_before_writing(tmp_path, version, kind):
    with pytest.raises(view.ViewError):
        view.materialize_view({'kind': kind, 'version': version}, tmp_path / 'unused', enabled=True)
    assert not (tmp_path / 'unused').exists()


@pytest.mark.parametrize('change', ['typed_value', 'source', 'parent', 'own', 'row_map'])
def test_materialization_rebuilds_before_any_write(monkeypatch, tmp_path, change):
    checked = {'kind': 'planned_heterogeneous_business_financial_view_v3', 'version': 3,
        'adapter': view.ADAPTER_ID, 'source_admission': {'source_manifest': {'fixture': True}},
        'setting': view.setting(enabled=True), 'forecast_targets': [{'reference_value': ['number', '0']}],
        'scope_revision': {'deleted_rows_by_sheet': {'S01 Statements': [5]}}}
    bad = deepcopy(checked)
    if change == 'typed_value':
        bad['forecast_targets'][0]['reference_value'] = ['number', '1']
    elif change == 'source':
        bad['source_admission']['source_manifest']['fixture'] = False
    elif change == 'parent':
        bad['setting']['parent_setting']['parent_implementation']['sha256'] = '0' * 64
    elif change == 'own':
        bad['setting']['implementation']['sha256'] = '0' * 64
    else:
        bad['scope_revision']['deleted_rows_by_sheet']['S01 Statements'] = [6]
    calls = []
    def rebuild(source, *, enabled):
        calls.append((source, enabled))
        return checked
    monkeypatch.setattr(view, 'build_view_plan', rebuild)
    with pytest.raises(view.ViewError, match='recipe changed'):
        view.materialize_view(bad, tmp_path / 'unused', enabled=True)
    assert len(calls) == 1
    assert not (tmp_path / 'unused').exists()


def test_no_new_public_policy_or_algorithm_and_no_actual_census_claim():
    assert view.public_brief() == parent.public_brief() == original.public_brief()
    p = view.policy()
    c = p['offline_prototype_census_not_source_certificate']
    assert c['parent_business_slots'] - c['excluded_intermediate_display_slots'] == c['retained_business_slots']
    assert c['new_actual_changed_value_set_count'] is None
    assert p['cash_delta_CFO_CFI_CFF_and_reconciliations_preserved'] is True
    assert 'actual_Harbor_controls' in view.PENDING

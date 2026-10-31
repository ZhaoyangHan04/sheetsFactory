"""Default-off projection omitting two complete intermediate display families.

The source and both parent admissions remain unchanged. This version removes
whole account rows, keeps every other business value, and supplies no additional
financial policy or solution guidance. It executes no financial forward or Calc.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

from openpyxl.utils.cell import coordinate_from_string

from . import heterogeneous_financial_view_v2 as parent

ROOT = parent.ROOT
SETTING = 'heterogeneous_financial_view_v3'
ADAPTER_ID = 'heterogeneous_business_financial_view_v3'
DEFAULT_POLICY = ROOT / 'config/task_adapters/heterogeneous_financial_view_v3.json'
PARENT_IMPLEMENTATION = Path(parent.__file__).resolve()
PARENT_POLICY = parent.DEFAULT_POLICY
SOURCE_BUILDER = parent.SOURCE_BUILDER
SOURCE_KIND = parent.SOURCE_KIND
PENDING = list(parent.PENDING)
ViewError = parent.ViewError
require = parent.require
reference = parent.reference
canonical = parent.canonical
validate_source = parent.validate_source
validate_view = parent.validate_view
_EXCLUDED = frozenset(('cash_before_financing', 'trap_operative'))
_TYPES = {'cash_before_financing': ('money_pence', 100), 'trap_operative': ('flag', 1)}


def policy(value=DEFAULT_POLICY):
    record = reference(value)
    declared = parent.parent._read(record['path'])
    require(type(declared.get('version')) is int and declared['version'] == 3
        and declared.get('adapter') == ADAPTER_ID
        and declared.get('enabled_by_default') is False
        and declared.get('parent_adapter') == parent.ADAPTER_ID,
        'The view requires its explicit version-three default-off policy')
    require(declared == parent.parent._read(DEFAULT_POLICY)
        and declared.get('excluded_display_fields') == ['cash_before_financing', 'trap_operative']
        and declared.get('selection_consults_values_or_model_scores') is False,
        'Only the complete current version-three display policy is supported')
    return declared


def setting(*, enabled=False):
    require(type(enabled) is bool, 'The opt-in must be a boolean')
    return {'enabled': enabled, 'version': 3, 'adapter': ADAPTER_ID,
        'implementation': reference(__file__), 'policy': reference(DEFAULT_POLICY),
        'parent_implementation': reference(PARENT_IMPLEMENTATION),
        'parent_policy': reference(PARENT_POLICY),
        'parent_setting': parent.setting(enabled=True),
        'source_builder': reference(SOURCE_BUILDER)}


def public_brief():
    return parent.public_brief()


def _revise_scope(base, declared):
    """Pure private scope projection; a caller fixture is never an admission.

    Every excluded field must occur once for each complete supplied entity-month.
    A row containing any other account is rejected rather than partly removed.
    Row positions change by the same deterministic deletion on both workbooks.
    """
    require(declared == policy(), 'The bounded display-removal policy changed')
    view = deepcopy(base)
    require(len(view['forecast_targets']) == view['declared_slot_count'],
        'The complete parent forecast scope differs')
    coordinates, rows, entity_months, excluded_months = set(), defaultdict(list), set(), {}
    removed, retained = [], []
    for target in view['forecast_targets']:
        path = target['source']['expected_path']
        require(isinstance(path, list) and bool(path), 'A complete logical account is required')
        column, row = coordinate_from_string(target['cell'])
        require(type(target['descriptor_row']) is int and row == target['descriptor_row']
            and row >= 4 and target['sheet'] in view['sheet_order'],
            'A forecast coordinate and its account descriptor row differ')
        position = target['sheet'], target['cell']
        require(position not in coordinates, 'A projected target position is duplicated')
        coordinates.add(position)
        rows[target['sheet'], row].append(target)
        if parent._entity_month(path):
            require(path[1] in view['scenario_ids'] and 0 <= path[5] < len(view['months']),
                'An entity month is outside the complete public calendar')
            entity_months.add((path[1], path[3], path[5]))
        if path[-1] in _EXCLUDED:
            kind, scale = _TYPES[path[-1]]
            require(parent._entity_month(path) and target['source']['kind'] == kind
                and type(target['source']['worksheet_scale']) is int
                and target['source']['worksheet_scale'] == scale,
                'An unexpected logical field or unit cannot be removed')
            key = path[1], path[3], path[5]
            fields = excluded_months.setdefault(key, set())
            require(path[-1] not in fields, 'An intermediate display account is duplicated')
            fields.add(path[-1])
            removed.append(target)
        else:
            retained.append(target)
    require(bool(entity_months) and set(excluded_months) == entity_months
        and all(fields == _EXCLUDED for fields in excluded_months.values()),
        'Both complete display families must cover every supplied entity month')

    deleted = defaultdict(set)
    evidence = []
    for (sheet, row), members in rows.items():
        chosen = [t for t in members if t['source']['expected_path'][-1] in _EXCLUDED]
        if not chosen:
            continue
        require(len(chosen) == len(members), 'A removed account row contains another financial field')
        owners = {(t['source']['expected_path'][1], t['source']['expected_path'][3],
            t['source']['expected_path'][-1]) for t in chosen}
        require(len(owners) == 1 and len(chosen) == len(view['months'])
            and {t['source']['expected_path'][5] for t in chosen} == set(range(len(view['months'])))
            and all(t['descriptors'] == chosen[0]['descriptors'] for t in chosen),
            'A display row must contain one complete owner/account calendar')
        deleted[sheet].add(row)
        evidence.append({'sheet': sheet, 'parent_row': row,
            'scenario': next(iter(owners))[0], 'entity': next(iter(owners))[1],
            'field': next(iter(owners))[2], 'calendar_slots': len(chosen)})
    deleted = {sheet: sorted(rowset) for sheet, rowset in sorted(deleted.items())}

    def reflow(sheet, cell):
        column, row = coordinate_from_string(cell)
        omitted = deleted.get(sheet, [])
        require(row not in omitted, 'A removed account row contains a supplied literal or retained target')
        return column + str(row - bisect_left(omitted, row))

    for supplied in view['provided_cells']:
        supplied['cell'] = reflow(supplied['sheet'], supplied['cell'])
    for target in retained:
        target['cell'] = reflow(target['sheet'], target['cell'])
        target['descriptor_row'] = coordinate_from_string(target['cell'])[1]
    require(len({(t['sheet'], t['cell']) for t in retained}) == len(retained),
        'Whole-row removal produced a target collision')
    view['forecast_targets'] = retained
    view['declared_slot_count'] = len(retained)
    view['scope_counts']['business_targets'] = len(retained)
    view['scope_counts']['target_kinds'] = dict(Counter(t['source']['kind'] for t in retained))
    view['scope_counts']['excluded_intermediate_display_slots'] = len(removed)
    view['parent_scope_revision'] = deepcopy(base.get('scope_revision'))
    view['scope_revision'] = {'parent_business_slots': len(base['forecast_targets']),
        'retained_business_slots': len(retained), 'excluded_intermediate_display_slots': len(removed),
        'excluded_fields': sorted(_EXCLUDED), 'removed_account_rows': sum(map(len, deleted.values())),
        'deleted_rows_by_sheet': deleted, 'complete_account_row_evidence': evidence,
        'excluded_display_evidence': [{'source': deepcopy(t['source']),
            'previous_business_position': {'sheet': t['sheet'], 'cell': t['cell']}}
            for t in removed],
        'retained_positions_unchanged': False,
        'retained_row_reflow': declared['row_reflow'],
        'retained_typed_values_and_source_bindings_unchanged': True,
        'queue_total_alias_evidence_unchanged': True,
        'public_notes_and_instruction_unchanged': True,
        'new_actual_changed_value_set_pending': True,
        'actual_removed_row_materialization_certified': False}
    return view


def build_view_plan(source_manifest, *, enabled=False, layout_policy=DEFAULT_POLICY):
    require(enabled is True, 'The heterogeneous version-three business view is default off')
    declared = policy(layout_policy)
    base = parent.build_view_plan(source_manifest, enabled=True)
    require(type(base.get('version')) is int and base['version'] == 2
        and base.get('kind') == 'planned_heterogeneous_business_financial_view_v2'
        and base.get('adapter') == parent.ADAPTER_ID
        and base.get('setting') == parent.setting(enabled=True)
        and base.get('plan_sha256') == canonical({k: v for k, v in base.items() if k != 'plan_sha256'}),
        'The complete current cold-admitted version-two parent plan is required')
    view = _revise_scope(base, declared)
    view.update(kind='planned_heterogeneous_business_financial_view_v3', version=3,
        adapter=ADAPTER_ID, setting=setting(enabled=True), original_brief=public_brief(),
        parent_projection_provenance={'parent_plan_sha256': base['plan_sha256'],
            'parent_implementation': reference(PARENT_IMPLEMENTATION),
            'parent_policy': reference(PARENT_POLICY),
            'parent_setting': parent.setting(enabled=True),
            'parent_quality_or_difficulty_evidence_transferred': False},
        pending=list(PENDING), quality_or_difficulty_certified=False, actual_projection_LO_calls=0)
    del view['plan_sha256']
    view['plan_sha256'] = canonical(view)
    return view


def materialize_view(plan, output, *, enabled=False):
    require(enabled is True, 'Materialization is default off and requires explicit authorization')
    require(isinstance(plan, dict)
        and plan.get('kind') == 'planned_heterogeneous_business_financial_view_v3'
        and type(plan.get('version')) is int and plan['version'] == 3
        and plan.get('adapter') == ADAPTER_ID, 'A complete checked version-three plan is required')
    checked = build_view_plan(plan['source_admission']['source_manifest'], enabled=True)
    require(checked == plan, 'A target, typed value, source or complete version-three parent recipe changed')
    out = Path(output).absolute()
    require(out == out.resolve() and out.is_relative_to(ROOT / 'outputs') and not out.exists(),
        'Use a fresh private outputs directory')
    (out / 'public').mkdir(parents=True)
    (out / 'private').mkdir()
    for masked, path in [(True, out / 'public/input.xlsx'), (False, out / 'private/goal.xlsx')]:
        book = parent.parent._book_from_plan(plan, masked=masked)
        try:
            book.save(path)
        finally:
            book.close()
    (out / 'public/instruction.md').write_text(plan['original_brief'])
    audit = validate_view(plan, out / 'public/input.xlsx', out / 'private/goal.xlsx')
    return {'kind': 'materialized_heterogeneous_business_view_v3_pending_task_checks', 'version': 3,
        'input': reference(out / 'public/input.xlsx'), 'goal': reference(out / 'private/goal.xlsx'),
        'instruction': reference(out / 'public/instruction.md'), 'source_admission': plan['source_admission'],
        'plan_sha256': plan['plan_sha256'], 'declared_slot_count': plan['declared_slot_count'],
        'scope_revision_counts': {k: plan['scope_revision'][k] for k in
            ('parent_business_slots', 'retained_business_slots',
             'excluded_intermediate_display_slots', 'removed_account_rows')},
        'projection_audit': audit, 'pending': list(PENDING),
        'quality_or_difficulty_certified': False, 'actual_LO_calls': 0}

"""Default-off business projection with an explicit asset policy.

The complete version-one source admission and cache checks remain mandatory.
This revision removes only two internal cure-counter forecasts and adds one
public asset policy. It runs no ledger, emitter, optimizer, or Calc process.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from pathlib import Path

from openpyxl.utils.cell import coordinate_from_string

from . import heterogeneous_financial_view as parent

ROOT = parent.ROOT
SETTING = 'heterogeneous_financial_view_v2'
ADAPTER_ID = 'heterogeneous_business_financial_view_v2'
DEFAULT_POLICY = ROOT / 'config/task_adapters/heterogeneous_financial_view_v2.json'
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
_COUNTERS = frozenset(('cure_open', 'cure_next'))


def policy(value=DEFAULT_POLICY):
    record = reference(value)
    declared = parent._read(record['path'])
    require(type(declared.get('version')) is int and declared['version'] == 2
        and declared.get('adapter') == ADAPTER_ID
        and declared.get('enabled_by_default') is False
        and declared.get('parent_adapter') == parent.ADAPTER_ID,
        'The view requires its explicit version-two default-off policy')
    require(declared == parent._read(DEFAULT_POLICY),
        'Only the complete current version-two business policy is supported')
    require(declared.get('excluded_counter_fields') == ['cure_open', 'cure_next']
        and declared.get('retained_positions_and_values') == 'exact_version_one_subset'
        and declared.get('asset_policy_note_title') == 'Asset depreciation'
        and isinstance(declared.get('asset_policy_note'), str)
        and bool(declared['asset_policy_note']), 'The bounded public revision changed')
    return declared


def setting(*, enabled=False):
    require(type(enabled) is bool, 'The opt-in must be a boolean')
    return {'enabled': enabled, 'version': 2, 'adapter': ADAPTER_ID,
        'implementation': reference(__file__), 'policy': reference(DEFAULT_POLICY),
        'parent_implementation': reference(PARENT_IMPLEMENTATION),
        'parent_policy': reference(PARENT_POLICY),
        'source_builder': reference(SOURCE_BUILDER)}


def public_brief():
    # The business objective and exact output boundary do not change.
    return parent.public_brief()


def _entity_month(path):
    return (isinstance(path, list) and len(path) == 7 and path[0] == 'scenarios'
        and path[2] == 'entities' and path[4] == 'monthly'
        and type(path[5]) is int)


def _revise_scope(base, declared):
    """Pure private-plan transformation; never an admission certificate.

    Production callers enter through build_view_plan, which obtains this base
    from the complete cold version-one source admission, not from caller JSON.
    Coordinates and typed values of retained targets are copied without reflow.
    """
    view = deepcopy(base)
    retained, omitted, entity_months, counter_months = [], [], set(), {}
    coordinates = set()
    for target in view['forecast_targets']:
        path = target['source']['expected_path']
        position = target['sheet'], target['cell']
        require(position not in coordinates, 'A projected target position is duplicated')
        coordinates.add(position)
        if _entity_month(path):
            key = path[1], path[3], path[5]
            entity_months.add(key)
        if path[-1] in _COUNTERS:
            require(_entity_month(path) and target['source']['kind'] == 'integer'
                and type(target['source']['worksheet_scale']) is int
                and target['source']['worksheet_scale'] == 1,
                'An unexpected cure-counter field cannot be silently removed')
            key = path[1], path[3], path[5]
            fields = counter_months.setdefault(key, set())
            require(path[-1] not in fields, 'A cure-counter logical field is duplicated')
            fields.add(path[-1])
            omitted.append({'source': deepcopy(target['source']),
                'previous_business_position': {'sheet': target['sheet'], 'cell': target['cell']},
                'reason': 'Internal completed-cure memo representation is outside the business forecast scope.'})
        else:
            retained.append(target)
    require(bool(entity_months) and set(counter_months) == entity_months
        and all(fields == _COUNTERS for fields in counter_months.values()),
        'Both cure counters must be identified for every supplied entity month')
    require(len(retained) + len(omitted) == len(base['forecast_targets'])
        == base['declared_slot_count'], 'The complete parent forecast scope differs')

    notes = [r for r in view['provided_cells'] if r['sheet'] == 'Contract Notes']
    require(bool(notes), 'The supplied public Contract Notes are absent')
    row = max(coordinate_from_string(r['cell'])[1] for r in notes) + 1
    added = [{'sheet': 'Contract Notes', 'cell': f'{column}{row}',
        'value': parent._typed(text), 'number_format': 'General'}
        for column, text in [('A', declared['asset_policy_note_title']),
                             ('B', declared['asset_policy_note'])]]
    require(not ({(r['sheet'], r['cell']) for r in added}
        & {(r['sheet'], r['cell']) for r in view['provided_cells']}),
        'The new public policy would overwrite supplied information')
    view['provided_cells'].extend(added)
    view['forecast_targets'] = retained
    view['declared_slot_count'] = len(retained)
    view['scope_counts']['business_targets'] = len(retained)
    view['scope_counts']['target_kinds'] = dict(Counter(r['source']['kind'] for r in retained))
    view['scope_counts']['excluded_internal_cure_counter_slots'] = len(omitted)
    view['scope_revision'] = {'parent_business_slots': len(base['forecast_targets']),
        'retained_business_slots': len(retained), 'excluded_internal_counter_slots': len(omitted),
        'excluded_fields': sorted(_COUNTERS), 'excluded_counter_evidence': omitted,
        'retained_positions_unchanged': True, 'retained_typed_values_unchanged': True,
        'queue_total_alias_evidence_unchanged': True,
        'new_actual_changed_value_set_pending': True,
        'added_public_policy_cells': added}
    return view


def build_view_plan(source_manifest, *, enabled=False, layout_policy=DEFAULT_POLICY):
    require(enabled is True, 'The heterogeneous version-two business view is default off')
    declared = policy(layout_policy)
    base = parent.build_view_plan(source_manifest, enabled=True)
    require(type(base.get('version')) is int and base['version'] == 1
        and base.get('kind') == 'planned_heterogeneous_business_financial_view'
        and base.get('adapter') == parent.ADAPTER_ID
        and base.get('setting') == parent.setting(enabled=True)
        and base.get('plan_sha256') == canonical({k: v for k, v in base.items() if k != 'plan_sha256'}),
        'The complete current admitted parent plan is required')
    view = _revise_scope(base, declared)
    view.update(kind='planned_heterogeneous_business_financial_view_v2', version=2,
        adapter=ADAPTER_ID, setting=setting(enabled=True), original_brief=public_brief(),
        parent_projection_provenance={'parent_plan_sha256': base['plan_sha256'],
            'parent_implementation': reference(PARENT_IMPLEMENTATION),
            'parent_policy': reference(PARENT_POLICY),
            'parent_quality_or_difficulty_evidence_transferred': False},
        pending=list(PENDING), quality_or_difficulty_certified=False, actual_projection_LO_calls=0)
    del view['plan_sha256']
    view['plan_sha256'] = canonical(view)
    return view


def materialize_view(plan, output, *, enabled=False):
    require(enabled is True, 'Materialization is default off and requires explicit authorization')
    require(isinstance(plan, dict)
        and plan.get('kind') == 'planned_heterogeneous_business_financial_view_v2'
        and type(plan.get('version')) is int and plan['version'] == 2
        and plan.get('adapter') == ADAPTER_ID, 'A complete checked version-two plan is required')
    # A JSON plan or previous recipe cannot confer source/cache trust. Rebuild
    # this exact revision with its own and parent implementation/policy refs.
    checked = build_view_plan(plan['source_admission']['source_manifest'], enabled=True)
    require(checked == plan, 'A planned target, source, typed value or version-two recipe changed')
    out = Path(output).absolute()
    require(out == out.resolve() and out.is_relative_to(ROOT / 'outputs') and not out.exists(),
        'Use a fresh private outputs directory')
    (out / 'public').mkdir(parents=True)
    (out / 'private').mkdir()
    for masked, path in [(True, out / 'public/input.xlsx'), (False, out / 'private/goal.xlsx')]:
        book = parent._book_from_plan(plan, masked=masked)
        try:
            book.save(path)
        finally:
            book.close()
    (out / 'public/instruction.md').write_text(plan['original_brief'])
    audit = validate_view(plan, out / 'public/input.xlsx', out / 'private/goal.xlsx')
    return {'kind': 'materialized_heterogeneous_business_view_v2_pending_task_checks', 'version': 2,
        'input': reference(out / 'public/input.xlsx'), 'goal': reference(out / 'private/goal.xlsx'),
        'instruction': reference(out / 'public/instruction.md'), 'source_admission': plan['source_admission'],
        'plan_sha256': plan['plan_sha256'], 'declared_slot_count': plan['declared_slot_count'],
        'scope_revision_counts': {k: plan['scope_revision'][k] for k in
            ('parent_business_slots', 'retained_business_slots', 'excluded_internal_counter_slots')},
        'projection_audit': audit, 'pending': list(PENDING),
        'quality_or_difficulty_certified': False, 'actual_LO_calls': 0}

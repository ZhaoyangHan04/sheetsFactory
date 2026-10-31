"""Default-off policy faults in an uncalculated specialized contract graph.

Every applicable entity/month/scenario of a selected rule is changed together.
This is a pure proposal compiler, not source admission or a claim that every
physical edit is active. Actual individual effects and full task gates follow.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy

from . import heterogeneous_localized_debugging as base
from ..workbook.heterogeneous_contracts import policy_specialization as compiler

ADAPTER_ID = 'heterogeneous_specialized_policy_faults_v1'
FAMILIES = ('quarter_coupon_calendar', 'cash_tax_eligible_basis',
    'cash_tax_settlement', 'quarter_covenant_operative')
PENDING = ('fresh_specialized_source_admission', 'actual_individual_family_effects',
    'actual_joint_mutant_recalculation', 'full_typed_mutant_stability',
    'complete_whole_workbook_D', 'five_local_controls', 'public_only_recovery',
    'all_enabled_quality_checks', 'actual_Harbor_oracle_nop', 'fresh_difficulty_confirmation')


def setting(*, enabled=False, families=FAMILIES):
    base._require(type(enabled) is bool, 'An explicit Boolean opt-in is required')
    chosen = tuple(families)
    base._require(bool(chosen) and len(chosen) == len(set(chosen))
        and all(value in FAMILIES for value in chosen), 'Unknown or duplicate policy family')
    return {'adapter': ADAPTER_ID, 'version': 1, 'enabled': enabled,
        'families': [value for value in FAMILIES if value in chosen],
        'all_applicable_periods': True, 'consults_cached_values_or_model_scores': False}


def _context(row):
    path = row.get('semantic_owner')
    if isinstance(path, list) and len(path) == 7 and path[0] == 'scenarios' \
            and path[2] == 'entities' and path[4] == 'monthly' \
            and isinstance(row.get('cell'), str) and row['cell'].startswith('B'):
        return path[1], path[3], path[5], path[6]
    return None


def _replacement(locator, public, family, row, context, loan_index):
    sid, eid, month, _ = context
    before = base._tree(row['expression'])
    ref = lambda field: base._ref(locator.field(sid, eid, month, field))
    if family == 'quarter_coupon_calendar':
        index = loan_index[eid]
        loan = public['loans'][index]
        selected = locator.helper(sid, eid, month, 'term_id',
            loan['id'] + ' {month} effective next_coupon_month')
        initial = base._ref(locator.inputs[('loans', index, 'terms', 0, 'next_coupon_month')])
        after, count = base._replace(before, base._ref(selected), initial)
        base._require(count == 3, 'The effective coupon calendar must occur in comparison, year and month')
    elif family == 'cash_tax_eligible_basis':
        base._require(before == ref('cash_coupon'), 'The specialized cash-coupon tax basis changed')
        after = ref('interest_accrual')
    elif family == 'cash_tax_settlement':
        base._require(isinstance(before, list) and len(before) == 4 and before[0] == 'if'
            and before[2] == ['sum', ref('tax_payable_open'), ref('current_tax_expense')]
            and before[3] == 0, 'The specialized quarterly cash-tax settlement changed')
        calendar = "'Calendar'!$D$" + str(month + 2)
        base._require(before[1] == calendar, 'Quarterly settlement must use the native quarter-end calendar')
        after = ref('current_tax_expense')
    else:
        base._require(family == 'quarter_covenant_operative' and isinstance(before, list)
            and len(before) == 4 and before[0] == 'if' and before[2] == 0
            and before[3] == ref('trap_open'), 'The specialized lagged operative restriction changed')
        after = deepcopy(before)
        after[3] = ['if', ['or', ref('trap_open'),
            ['and', ref('test_applicable'), ['eq', ref('test_pass'), 0]]], 1, 0]
    base._require(after != before, 'The policy edit must change the expression')
    return after


def compile_policy_mutations(public, bindings, *, enabled=False, families=FAMILIES):
    """Return all selected fault definitions without executing financial paths."""
    policy = setting(enabled=enabled, families=families)
    base._require(policy['enabled'], 'Specialized debugging is disabled by default')
    materialization = bindings.get('specialized_materialization')
    base._require(isinstance(materialization, dict)
        and materialization.get('geometry', {}).get('all_financial_roots_and_references_present') is True
        and materialization.get('original_templates_saved_or_materialized_as_archive') is False,
        'Only an explicitly specialized complete physical graph is supported')
    locator = base._Locator(public, bindings)
    entities = {row['id']: row for row in public['entities']}
    loans = {row['entity_id']: row for row in public['loans']}
    loan_index = {row['entity_id']: index for index, row in enumerate(public['loans'])}
    base._require(len(entities) == len(public['entities']) == len(public['loans']) == len(loans)
        and len({row['id'] for row in public['loans']}) == len(loans)
        and set(entities) == set(loans), 'Every supplied entity must have its own unique facility')
    scenarios = {row['id'] for row in public['scenarios']}
    base._require(bool(scenarios) and len(scenarios) == len(public['scenarios'])
        and bool(public['months']) and len(set(public['months'])) == len(public['months']),
        'The complete public scenario and month identities must be unique')
    labels = {(row['sheet'], row['cell']): row['value'] for row in bindings['literal_bindings']}
    financial = {(row['sheet'], row['cell']) for row in bindings['financial_bindings']}
    all_by_role, targets, role_periods, changed_periods = Counter(), [], set(), set()
    for row in bindings['arithmetic_bindings']:
        context = _context(row)
        if context is None:
            continue
        sid, eid, month, field = context
        base._require(sid in scenarios and eid in entities and type(month) is int
            and 0 <= month < len(public['months']) and row['sheet'] == sid + ' Calculations',
            'A policy node has an unknown physical owner or period')
        label = labels.get((row['sheet'], 'A' + row['cell'][1:]))
        family = None
        if field == 'cash_coupon' and label == eid + ' ' + public['months'][month] + ' coupon due':
            family = 'quarter_coupon_calendar'
        elif (row['sheet'], row['cell']) in financial:
            family = {'eligible_current_interest': 'cash_tax_eligible_basis',
                'cash_tax': 'cash_tax_settlement', 'trap_operative': 'quarter_covenant_operative'}.get(field)
        if family is None or family not in policy['families']:
            continue
        role = family, sid, eid, month
        base._require(role not in role_periods, 'A policy role repeats an owner/scenario/month')
        role_periods.add(role)
        all_by_role[family] += 1
        applicable = (loans[eid]['type'] == 'BULLET_QUARTERLY_ACCRUAL'
            if family == 'quarter_coupon_calendar' else
            entities[eid]['tax_policy'] == 'CASH_COUPON_QUARTERLY'
            if family.startswith('cash_tax_') else entities[eid]['dscr_policy'] == 'QUARTERLY_LAGGED')
        if not applicable:
            continue
        after = _replacement(locator, public, family, row, context, loan_index)
        changed_periods.add(role)
        targets.append({'family': family, 'sheet': row['sheet'], 'cell': row['cell'],
            'owner': deepcopy(row['semantic_owner']), 'before_expression': deepcopy(row['expression']),
            'after_expression': after, 'before_formula': row['formula'],
            'after_formula': '=' + base.excel.expression_formula(after)})
    actual = Counter(row['family'] for row in targets)
    periods = len(scenarios) * len(public['months'])
    for family in policy['families']:
        eligible_entities = {eid for eid in entities if (loans[eid]['type'] == 'BULLET_QUARTERLY_ACCRUAL'
            if family == 'quarter_coupon_calendar' else
            entities[eid]['tax_policy'] == 'CASH_COUPON_QUARTERLY'
            if family.startswith('cash_tax_') else entities[eid]['dscr_policy'] == 'QUARTERLY_LAGGED')
            }
        complete = {(family, sid, eid, month) for sid in scenarios for eid in entities
            for month in range(len(public['months']))}
        applicable = {role for role in complete if role[2] in eligible_entities}
        base._require(bool(eligible_entities) and actual[family] == len(eligible_entities) * periods
            and all_by_role[family] == len(entities) * periods
            and {role for role in role_periods if role[0] == family} == complete
            and {role for role in changed_periods if role[0] == family} == applicable,
            'A selected policy family lacks complete applicable or legal-peer coverage')
    base._require(len({(row['sheet'], row['cell']) for row in targets}) == len(targets),
        'Two policy faults target the same physical node')
    return {'kind': 'uncalculated_specialized_heterogeneous_policy_faults', 'version': 1,
        'setting': policy, 'bindings_sha256': compiler.canonical(bindings),
        'specification_sha256': base.canonical(public), 'mutations': targets,
        'physical_edit_count': len(targets), 'family_edit_counts': dict(actual),
        'unaffected_policy_peer_counts': {key: all_by_role[key] - actual[key] for key in policy['families']},
        'all_applicable_periods_covered': True, 'independent_active_root_count': None,
        'workbooks_written': 0, 'LO_calls': 0, 'model_calls': 0,
        'quality_or_difficulty_certified': False, 'pending': list(PENDING)}

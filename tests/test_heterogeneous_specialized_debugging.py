"""Hand-written specialized graph fixtures, never actual source calculations."""
import ast
from collections import Counter
from copy import deepcopy
from pathlib import Path

import pytest

from sheets_factory.task_adapters import heterogeneous_specialized_debugging as policy
from sheets_factory.task_adapters import heterogeneous_localized_debugging as base
from sheets_factory.workbook.heterogeneous_contracts import excel


@pytest.fixture
def graph():
    # Policies cross rather than coincide: the quarterly loan has accrual tax
    # and monthly DSCR, while the other two loan types have cash tax/lagged DSCR.
    # This is a tiny graph-layout fixture, not a complete source specification.
    public = {'months': ['2027-01-01', '2027-02-01', '2027-03-01'],
        'entities': [
            {'id': 'E01', 'tax_policy': 'CASH_COUPON_QUARTERLY', 'dscr_policy': 'QUARTERLY_LAGGED'},
            {'id': 'E02', 'tax_policy': 'ACCRUAL_MONTHLY', 'dscr_policy': 'MONTHLY_CURRENT'},
            {'id': 'E03', 'tax_policy': 'CASH_COUPON_QUARTERLY', 'dscr_policy': 'QUARTERLY_LAGGED'}],
        'loans': [{'id': f'L{i+1:02d}', 'entity_id': f'E{i+1:02d}', 'type': kind,
            'terms': [{'next_coupon_month': '2027-03-01'}, {'next_coupon_month': '2027-05-01'}]}
            for i, kind in enumerate(('BULLET_MONTHLY', 'BULLET_QUARTERLY_ACCRUAL', 'LEVEL_PRINCIPAL_MONTHLY'))],
        'scenarios': [{'id': 'S01'}, {'id': 'S02'}]}
    bindings = {'arithmetic_bindings': [], 'financial_bindings': [],
        'input_bindings': [], 'literal_bindings': [],
        'specialized_materialization': {'geometry': {'all_financial_roots_and_references_present': True},
            'original_templates_saved_or_materialized_as_archive': False,
            'financial_equivalence_verified': False, 'actual_LO_calls': 0}}
    counters, fields, inputs = Counter(), {}, {}

    def add(sid, eid, month, field, expression, *, label=None, financial=True, expected_field=None):
        counters[sid] += 1
        row = {'sheet': sid + ' Calculations', 'cell': 'B' + str(counters[sid]),
            'semantic_owner': ['scenarios', sid, 'entities', eid, 'monthly', month, field],
            'expression': deepcopy(expression), 'formula': '=' + excel.expression_formula(expression)}
        bindings['arithmetic_bindings'].append(row)
        bindings['literal_bindings'].append({'sheet': row['sheet'], 'cell': 'A' + row['cell'][1:],
            'value': label or eid + ' ' + public['months'][month] + ' ' + field})
        if financial:
            bindings['financial_bindings'].append({**deepcopy(row),
                'expected_path': ['scenarios', sid, 'entities', eid, 'monthly', month, expected_field or field],
                'kind': 'money_pence', 'worksheet_scale': 1})
        return row

    def field(sid, eid, month, name, expression=0):
        row = add(sid, eid, month, name, expression)
        fields[sid, eid, month, name] = row
        return base._ref(row)

    def inp(path):
        if tuple(path) in inputs:
            return base._ref(inputs[tuple(path)])
        row = {'sheet': 'Facility Terms', 'cell': 'G' + str(len(bindings['input_bindings']) + 2),
            'path': path, 'kind': 'date', 'worksheet_scale': 1}
        bindings['input_bindings'].append(row)
        inputs[tuple(path)] = row
        return base._ref(row)

    for sid in ('S01', 'S02'):
        for i, entity in enumerate(public['entities']):
            eid = entity['id']
            for month in range(3):
                r = lambda name: base._ref(fields[sid, eid, month, name])
                for name in ('interest_accrual', 'interest_payable_open', 'tax_payable_open',
                        'current_tax_expense', 'trap_open', 'test_applicable', 'test_pass',
                        'facility_closed_open'):
                    field(sid, eid, month, name)
                # A legitimate helper and financial coupon remain for every
                # policy peer, including branches that can be inactive.
                if public['loans'][i]['type'] == 'BULLET_QUARTERLY_ACCRUAL':
                    initial = inp(['loans', i, 'terms', 0, 'next_coupon_month'])
                    selected = add(sid, eid, month, 'term_id', initial,
                        label=public['loans'][i]['id'] + ' ' + public['months'][month] + ' effective next_coupon_month',
                        financial=False)
                    chosen = base._ref(selected)
                    period = lambda date: ['sum', ['mul', ['year', date], 12], ['month', date]]
                    date = "'Calendar'!$A$" + str(month + 2)
                    due = ['if', ['ge', date, chosen],
                        ['if', ['eq', ['mod', ['sub', period(date), period(chosen)], 3], 0], 1, 0], 0]
                else:
                    due = ['if', ['eq', r('facility_closed_open'), 0], 1, 0]
                helper = add(sid, eid, month, 'cash_coupon', due,
                    label=eid + ' ' + public['months'][month] + ' coupon due', expected_field='coupon_due')
                field(sid, eid, month, 'cash_coupon', ['if', base._ref(helper),
                    ['sum', r('interest_payable_open'), r('interest_accrual')], 0])
                cash = entity['tax_policy'] == 'CASH_COUPON_QUARTERLY'
                field(sid, eid, month, 'eligible_current_interest', r('cash_coupon' if cash else 'interest_accrual'))
                field(sid, eid, month, 'cash_tax', ['if', "'Calendar'!$D$" + str(month + 2),
                    ['sum', r('tax_payable_open'), r('current_tax_expense')], 0] if cash else r('current_tax_expense'))
                operative = r('trap_open') if entity['dscr_policy'] == 'QUARTERLY_LAGGED' else [
                    'if', ['or', r('trap_open'), ['and', r('test_applicable'), ['eq', r('test_pass'), 0]]], 1, 0]
                field(sid, eid, month, 'trap_operative', ['if', r('facility_closed_open'), 0, operative])
                # Cure and next-state nodes are not selected by this policy.
                field(sid, eid, month, 'cure_next', 2)
                field(sid, eid, month, 'trap_next', r('trap_open'))
    bindings['formula_count'] = len(bindings['arithmetic_bindings'])
    return public, bindings


def test_default_off_and_bounded_family_selection(graph):
    public, bindings = graph
    with pytest.raises(ValueError, match='disabled'):
        policy.compile_policy_mutations(public, bindings)
    for chosen in [(), ('cure',), ('non_test_reset',), (policy.FAMILIES[0],) * 2]:
        with pytest.raises(ValueError):
            policy.setting(enabled=True, families=chosen)
    with pytest.raises(ValueError):
        policy.setting(enabled=1)


def test_all_four_families_cover_crossed_public_contract_types_and_periods(graph):
    public, bindings = graph
    old = deepcopy(bindings)
    result = policy.compile_policy_mutations(public, bindings, enabled=True)
    assert bindings == old
    assert result['physical_edit_count'] == 42
    assert result['family_edit_counts'] == {'quarter_coupon_calendar': 6,
        'cash_tax_eligible_basis': 12, 'cash_tax_settlement': 12, 'quarter_covenant_operative': 12}
    assert result['unaffected_policy_peer_counts'] == {'quarter_coupon_calendar': 12,
        'cash_tax_eligible_basis': 6, 'cash_tax_settlement': 6, 'quarter_covenant_operative': 6}
    owners = {f: {m['owner'][3] for m in result['mutations'] if m['family'] == f} for f in policy.FAMILIES}
    assert owners['quarter_coupon_calendar'] == {'E02'}
    assert all(owners[f] == {'E01', 'E03'} for f in policy.FAMILIES[1:])
    assert all(m['before_expression'] != m['after_expression'] for m in result['mutations'])
    assert all(m['before_formula'] == '=' + excel.expression_formula(m['before_expression'])
        and m['after_formula'] == '=' + excel.expression_formula(m['after_expression']) for m in result['mutations'])
    assert not any(m['owner'][-1] in ('cure_open', 'cure_next', 'trap_next', 'test_applicable', 'test_pass')
        for m in result['mutations'])
    assert result['all_applicable_periods_covered'] is True
    assert result['independent_active_root_count'] is None
    assert result['workbooks_written'] == result['LO_calls'] == result['model_calls'] == 0
    assert result['quality_or_difficulty_certified'] is False


@pytest.mark.parametrize('family', policy.FAMILIES)
def test_each_explicit_opt_in_selects_exactly_one_complete_family(graph, family):
    public, bindings = graph
    result = policy.compile_policy_mutations(public, bindings, enabled=True, families=[family])
    assert set(result['family_edit_counts']) == {family}
    assert {m['family'] for m in result['mutations']} == {family}


def test_cash_basis_and_monthly_settlement_use_actual_financial_field_names(graph):
    public, bindings = graph
    loc = base._Locator(public, bindings)
    result = policy.compile_policy_mutations(public, bindings, enabled=True)
    for m in result['mutations']:
        sid, eid, t = m['owner'][1], m['owner'][3], m['owner'][5]
        ref = lambda name: base._ref(loc.field(sid, eid, t, name))
        if m['family'] == 'cash_tax_eligible_basis':
            assert m['before_expression'] == ref('cash_coupon')
            assert m['after_expression'] == ref('interest_accrual')
        elif m['family'] == 'cash_tax_settlement':
            assert m['before_expression'] == ['if', "'Calendar'!$D$" + str(t + 2),
                ['sum', ref('tax_payable_open'), ref('current_tax_expense')], 0]
            assert m['after_expression'] == ref('current_tax_expense')
    assert 'tax_assessed' not in Path(policy.__file__).read_text()


def test_coupon_fault_rebinds_three_date_uses_without_changing_maturity_or_interest(graph):
    public, bindings = graph
    loc = base._Locator(public, bindings)
    result = policy.compile_policy_mutations(public, bindings, enabled=True,
        families=['quarter_coupon_calendar'])
    for m in result['mutations']:
        sid, eid, t = m['owner'][1], m['owner'][3], m['owner'][5]
        chosen = base._ref(loc.helper(sid, eid, t, 'term_id', 'L02 {month} effective next_coupon_month'))
        initial = base._ref(loc.inputs[('loans', 1, 'terms', 0, 'next_coupon_month')])
        assert str(m['before_expression']).count(chosen) == 3
        assert str(m['after_expression']).count(chosen) == 0
        assert str(m['after_expression']).count(initial) == 3


def test_lagged_operative_fault_is_current_failure_not_cure_or_nontest_reset(graph):
    public, bindings = graph
    loc = base._Locator(public, bindings)
    result = policy.compile_policy_mutations(public, bindings, enabled=True,
        families=['quarter_covenant_operative'])
    for m in result['mutations']:
        sid, eid, t = m['owner'][1], m['owner'][3], m['owner'][5]
        ref = lambda name: base._ref(loc.field(sid, eid, t, name))
        assert m['before_expression'] == ['if', ref('facility_closed_open'), 0, ref('trap_open')]
        assert m['after_expression'] == ['if', ref('facility_closed_open'), 0,
            ['if', ['or', ref('trap_open'), ['and', ref('test_applicable'), ['eq', ref('test_pass'), 0]]], 1, 0]]


@pytest.mark.parametrize('corruption', ['missing_family_node', 'wrong_policy_shape', 'wrong_calendar',
    'unknown_owner', 'wrong_physical_scenario', 'boolean_month', 'duplicate_entity',
    'duplicate_facility', 'duplicate_scenario', 'duplicate_month', 'unspecialized', 'archive'])
def test_incomplete_wrong_shape_or_wrong_owner_rejected(graph, corruption):
    public, bindings = graph
    selected = next(r for r in bindings['financial_bindings']
        if r['expected_path'][-1] == 'cash_tax' and r['expected_path'][3] == 'E01')
    arithmetic = next(r for r in bindings['arithmetic_bindings']
        if (r['sheet'], r['cell']) == (selected['sheet'], selected['cell']))
    if corruption == 'missing_family_node':
        bindings['financial_bindings'].remove(selected)
    elif corruption in ('wrong_policy_shape', 'wrong_calendar'):
        expression = 0 if corruption == 'wrong_policy_shape' else deepcopy(arithmetic['expression'])
        if corruption == 'wrong_calendar': expression[1] = "'Calendar'!$D$999"
        for row in (selected, arithmetic):
            row['expression'] = deepcopy(expression)
            row['formula'] = '=' + excel.expression_formula(expression)
    elif corruption == 'unknown_owner':
        arithmetic['semantic_owner'][3] = 'E99'
    elif corruption == 'wrong_physical_scenario':
        arithmetic['semantic_owner'][1] = 'S02'
    elif corruption == 'boolean_month':
        arithmetic['semantic_owner'][5] = True
    elif corruption == 'duplicate_entity': public['entities'].append(deepcopy(public['entities'][0]))
    elif corruption == 'duplicate_facility': public['loans'].append(deepcopy(public['loans'][0]))
    elif corruption == 'duplicate_scenario': public['scenarios'].append(deepcopy(public['scenarios'][0]))
    elif corruption == 'duplicate_month': public['months'][1] = public['months'][0]
    elif corruption == 'unspecialized': del bindings['specialized_materialization']
    else: bindings['specialized_materialization']['original_templates_saved_or_materialized_as_archive'] = True
    with pytest.raises(ValueError):
        policy.compile_policy_mutations(public, bindings, enabled=True)


def test_duplicate_role_cannot_offset_an_absent_period(graph):
    public, bindings = graph
    # Calendar helpers are not keyed in Locator.financial by their semantic
    # cash_coupon owner. Counts alone previously allowed one duplicate period
    # to stand in for a missing month while claiming all-period coverage.
    rows = [r for r in bindings['arithmetic_bindings'] if r['semantic_owner'][3] == 'E02'
        and r['semantic_owner'][-1] == 'cash_coupon'
        and next(x['value'] for x in bindings['literal_bindings']
            if (x['sheet'], x['cell']) == (r['sheet'], 'A' + r['cell'][1:])).endswith(' coupon due')]
    row = rows[0]
    row['semantic_owner'][5] = 1
    next_month = next(r for r in rows if r['sheet'] == row['sheet'] and r is not row
        and r['semantic_owner'][5] == 1)
    row['expression'] = deepcopy(next_month['expression'])
    row['formula'] = next_month['formula']
    next(x for x in bindings['literal_bindings']
        if (x['sheet'], x['cell']) == (row['sheet'], 'A' + row['cell'][1:]))['value'] = 'E02 2027-02-01 coupon due'
    # Keep the independent same-cell binding coherent to reach role coverage.
    financial = next(x for x in bindings['financial_bindings']
        if (x['sheet'], x['cell']) == (row['sheet'], row['cell']))
    financial['semantic_owner'] = deepcopy(row['semantic_owner'])
    financial['expression'] = deepcopy(row['expression'])
    financial['formula'] = row['formula']
    with pytest.raises(ValueError, match='repeats'):
        policy.compile_policy_mutations(public, bindings, enabled=True)


def test_no_production_io_or_forward_execution_is_part_of_proposal():
    tree = ast.parse(Path(policy.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            assert node.attr not in {'save', 'simulate', 'recalculate', 'Popen', 'run'}
    assert 'actual_joint_mutant_recalculation' in policy.PENDING
    assert 'all_enabled_quality_checks' in policy.PENDING

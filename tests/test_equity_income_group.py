"""Independent financial agreement and real OOXML prototype boundaries."""
from copy import deepcopy
from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path
from zipfile import ZipFile

import openpyxl
import pytest

from sheets_factory.workbook.equity_income_group import spec
from sheets_factory.workbook.equity_income_group import decimal_oracle as a
from sheets_factory.workbook.equity_income_group import fraction_oracle as b
from sheets_factory.workbook.equity_income_group import excel


def crosscheck(left, right):
    assert left['specification_sha256'] == right['specification_sha256']
    for key in ('scenario_order', 'entity_order', 'period_order'):
        assert left[key] == right[key]
    count = 0
    for sa, sb in zip(left['scenarios'], right['scenarios'], strict=True):
        assert sa['id'] == sb['id']
        for qa, qb in zip(sa['periods'], sb['periods'], strict=True):
            assert qa['period'] == qb['period']
            rows = [(qa['entities'][eid], qb['entities'][eid], spec.ENTITY_METRICS)
                    for eid in left['entity_order']]
            rows.append((qa['group'], qb['group'], spec.GROUP_METRICS))
            for ra, rb, metrics in rows:
                assert set(ra) == set(rb) == set(metrics)
                for key in metrics:
                    assert type(ra[key]) is Decimal and type(rb[key]) is Fraction
                    assert abs(Fraction(ra[key]) - rb[key]) < Fraction(1, 10**45)
                    assert Decimal(a.display(ra[key])) == Decimal(b.display(rb[key]))
                    count += 1
    return count


@pytest.fixture(scope='module')
def full():
    public = spec.build_spec()
    return public, a.solve(public), b.solve(public)


def test_default_complete_independent_agreement(full):
    public, left, right = full
    assert (len(public['entities']), len(public['periods']), len(public['scenarios'])) == (6, 12, 3)
    assert public['source_type'] == 'new_synthetic'
    assert public['official_workbook_seed_used'] is False
    assert all(row['equity_income'] == '0' for row in public['history'].values())
    assert all(sum(map(Fraction, row)) <= Fraction(35, 100) for row in public['ownership'])
    assert crosscheck(left, right) == 6912
    for sa, sb in zip(left['scenarios'], right['scenarios'], strict=True):
        for qa, qb in zip(sa['periods'], sb['periods'], strict=True):
            assert qa['solver']['contraction_modulus'] <= Decimal('.35')
            assert qa['solver']['mapping_residual'] < Decimal('1e-55')
            assert qb['solver']['regimes_checked'] == 64
            assert qb['solver']['valid_regime_count'] == 1


def test_all_entity_and_management_conservation_with_signed_results(full):
    public, _, result = full
    seen = dict(profit=0, loss=0, positive_equity=0, negative_equity=0, taxable=0, loss_used=0)
    for scenario in result['scenarios']:
        prior = {e['id']: {key: Fraction(e['opening_' + key])
                          for key in ('cash', 'ppe', 'investment', 'retained', 'loss')}
                 for e in public['entities']}
        for quarter in scenario['periods']:
            for eid, row in quarter['entities'].items():
                for state in prior[eid]:
                    assert row['opening_' + state] == prior[eid][state]
                    prior[eid][state] = row['closing_' + state]
                assert row['pretax_profit'] == row['standalone_pretax'] + row['equity_income']
                assert row['net_income'] == row['pretax_profit'] - row['current_tax']
                assert row['operating_cashflow'] == row['revenue'] - row['cash_opex'] - row['interest'] - row['current_tax']
                assert row['balance_residual'] == 0
                assert row['assets'] == row['liabilities_and_equity']
                assert min(row['closing_cash'], row['closing_ppe'], row['closing_investment']) >= 0
                seen['profit'] += row['net_income'] > 0
                seen['loss'] += row['net_income'] < 0
                seen['positive_equity'] += row['equity_income'] > 0
                seen['negative_equity'] += row['equity_income'] < 0
                seen['taxable'] += row['current_tax'] > 0
                seen['loss_used'] += row['opening_loss'] > 0 and row['pretax_profit'] > 0
            group = quarter['group']
            assert group['external_net_income'] == group['reported_entity_net_income'] - group['entity_equity_income']
            assert group['external_net_income'] == group['standalone_pretax'] - group['current_tax']
            assert group['assets'] == group['liabilities_and_capital']
            assert group['equity_income_elimination'] == -group['entity_equity_income']
            assert group['investment_elimination'] == -group['entity_investments']
            for field in ('balance_residual', 'profit_reconciliation_residual', 'cash_reconciliation_residual'):
                assert group[field] == 0
    assert all(value > 0 for value in seen.values())


def test_scenarios_reset_and_do_not_leak_state():
    public = spec.build_spec(entities=2, quarters=3, scenarios=3)
    baseline = b.solve(public)
    changed = deepcopy(public)
    changed['scenarios'][1]['inputs']['E01'][0]['revenue'] = '2800'
    actual = b.solve(changed)
    assert actual['scenarios'][0] == baseline['scenarios'][0]
    assert actual['scenarios'][2] == baseline['scenarios'][2]
    assert actual['scenarios'][1] != baseline['scenarios'][1]
    for scenario in actual['scenarios']:
        for e in public['entities']:
            row = scenario['periods'][0]['entities'][e['id']]
            for key in ('cash', 'ppe', 'investment', 'retained', 'loss'):
                assert row['opening_' + key] == Fraction(e['opening_' + key])


def test_loss_carryforward_is_used_before_current_tax():
    public = spec.build_spec(entities=1, quarters=3, scenarios=1)
    entity = public['entities'][0]
    entity.update(tax_rate='.25', annual_interest_rate='0', opening_loss='50')
    rows = public['scenarios'][0]['inputs']['E01']
    for row, revenue, opex in zip(rows, ('0', '300', '400'), ('100', '0', '0'), strict=True):
        row.update(revenue=revenue, cash_opex=opex, depreciation='0', capex='0')
    left, right = a.solve(public), b.solve(public)
    assert crosscheck(left, right) == 156
    actual = [q['entities']['E01'] for q in right['scenarios'][0]['periods']]
    assert [r['opening_loss'] for r in actual] == [50, 150, 0]
    assert [r['current_tax'] for r in actual] == [0, Fraction(75, 2), 100]
    assert [r['net_income'] for r in actual] == [-100, Fraction(525, 2), 300]


def test_signed_feedback_and_unrounded_later_posting():
    public = spec.build_spec(entities=2, quarters=2, scenarios=1)
    public['ownership'] = [['0', '.2'], ['.2', '0']]
    for entity in public['entities']:
        entity.update(tax_rate='0', annual_interest_rate='0', opening_loss='0')
    inputs = public['scenarios'][0]['inputs']
    for eid, values in {'E01': [('100', '0'), ('.01', '0')], 'E02': [('0', '50'), ('0', '0')]}.items():
        for row, (revenue, opex) in zip(inputs[eid], values, strict=True):
            row.update(revenue=revenue, cash_opex=opex, depreciation='0', capex='0')
    left, right = a.solve(public), b.solve(public)
    assert crosscheck(left, right) == 160
    q1, q2 = right['scenarios'][0]['periods']
    assert q1['entities']['E01']['net_income'] == Fraction(375, 4)
    assert q1['entities']['E02']['net_income'] == Fraction(-125, 4)
    assert q2['entities']['E01']['net_income'] == Fraction(1, 96)
    assert q2['entities']['E01']['closing_retained'] == Fraction(375, 4) + Fraction(1, 96)
    assert q2['entities']['E01']['closing_retained'] != Fraction(375, 4) + Fraction(1, 100)
    assert all(-2 * row['equity_income'] != 0 for row in q1['entities'].values())


@pytest.mark.parametrize('attack', ['row_cap', 'self_stake', 'overallocated', 'tax_rate',
    'period_order', 'missing_quarter', 'hidden_rounding', 'official_seed', 'policy'])
def test_both_oracles_reject_invalid_public_contract(attack):
    public = spec.build_spec(entities=4, quarters=2, scenarios=1)
    if attack == 'row_cap': public['ownership'][0][1] = '.36'
    elif attack == 'self_stake': public['ownership'][0][0] = '.01'
    elif attack == 'overallocated':
        public['ownership'] = [['0'] * 4 for _ in range(4)]
        for i in range(3): public['ownership'][i][3] = '.35'
    elif attack == 'tax_rate': public['entities'][0]['tax_rate'] = '1.01'
    elif attack == 'period_order': public['periods'].reverse()
    elif attack == 'missing_quarter': public['scenarios'][0]['inputs']['E01'].pop()
    elif attack == 'hidden_rounding': public['round_each_posting'] = True
    elif attack == 'official_seed': public['official_workbook_seed_used'] = True
    elif attack == 'policy': public['policy'][0] = 'Round inside the cycle.'
    for oracle in (a, b):
        with pytest.raises(ValueError): oracle.solve(public)


@pytest.fixture
def views(tmp_path):
    public = spec.build_spec(entities=2, quarters=3, scenarios=2)
    ref = excel.build_views(tmp_path / 'new_pair', public)
    return public, json.loads(Path(ref['path']).read_text())


def test_real_goal_caches_and_iterative_settings_remain_explicitly_unverified(views):
    _, prepared = views
    assert prepared['independent_oracle_cells_crosschecked'] == 480
    assert prepared['FM_mask_count'] == 432 and prepared['DBG_root_count'] == 12
    assert prepared['actual_LO_calls'] == prepared['model_calls'] == 0
    assert prepared['qualified'] is False
    assert prepared['oracle_seeded_goal_is_not_native_validation'] is True
    assert prepared['native_feedback_convergence_verified'] is False
    assert prepared['normal_quality_or_difficulty_certified'] is False
    expected = json.loads(Path(prepared['independent_expected']['path']).read_text())
    bindings = json.loads(Path(prepared['bindings']['path']).read_text())
    formulas = openpyxl.load_workbook(prepared['goal']['path'], data_only=False)
    cached = openpyxl.load_workbook(prepared['goal']['path'], data_only=True)
    assert formulas.calculation.iterate is True
    assert formulas.calculation.iterateCount == 10000
    assert formulas.calculation.iterateDelta == 1e-12
    for row in bindings['bindings']:
        key = row['sheet'] + '!' + row['cell']
        assert formulas[row['sheet']][row['cell']].data_type == 'f'
        assert round(cached[row['sheet']][row['cell']].value, 2) == float(expected[key]['value'])
    formulas.close(); cached.close()


def test_public_instructions_are_short_and_policies_remain_in_workbook(views):
    public, prepared = views
    for view in prepared['views'].values():
        text = Path(view['instruction']['path']).read_text()
        assert len(text.split()) < 80
        assert public['periods'][0] in text and public['periods'][-1] in text
        assert 'Read Me' in text
        assert all(policy not in text for policy in spec.POLICY)
        assert 'forecast formula' not in text
    book = openpyxl.load_workbook(prepared['goal']['path'], data_only=False)
    assert [book['Read Me'].cell(i + 2, 1).value for i in range(len(spec.POLICY))] == list(spec.POLICY)
    assert 'precedes the investment arrangements' in book['Read Me']['A8'].value
    assert 'do not specify' not in book['Read Me']['A8'].value
    book.close()


def test_real_FM_mask_DBG_sign_fault_and_all_provided_inputs_preserved(views):
    _, prepared = views
    bindings = json.loads(Path(prepared['bindings']['path']).read_text())
    targets = {(r['sheet'], r['cell']) for r in bindings['bindings']}
    roots = {(r['sheet'], r['cell']): r for r in bindings['DBG_root_edits']}
    goal = openpyxl.load_workbook(prepared['goal']['path'], data_only=False)
    fm_path = prepared['views']['financial_modeling']['input']['path']
    dbg_path = prepared['views']['debugging']['input']['path']
    fm = openpyxl.load_workbook(fm_path, data_only=False)
    dbg = openpyxl.load_workbook(dbg_path, data_only=False)
    dbg_cache = openpyxl.load_workbook(dbg_path, data_only=True)
    assert goal.sheetnames == fm.sheetnames == dbg.sheetnames
    count = 0
    for sheet in goal:
        for row in sheet:
            for cell in row:
                key = sheet.title, cell.coordinate
                if key in targets:
                    assert fm[sheet.title][cell.coordinate].value is None
                    assert dbg_cache[sheet.title][cell.coordinate].value is None
                    expected = roots[key]['after'] if key in roots else cell.value
                    assert dbg[sheet.title][cell.coordinate].value == expected
                    count += 1
                else:
                    assert fm[sheet.title][cell.coordinate].value == cell.value
                    assert dbg[sheet.title][cell.coordinate].value == cell.value
                assert fm[sheet.title][cell.coordinate].style_id == cell.style_id
                assert dbg[sheet.title][cell.coordinate].style_id == cell.style_id
    assert count == 432 and len(roots) == 12
    with ZipFile(prepared['goal']['path']) as original, ZipFile(fm_path) as left, ZipFile(dbg_path) as right:
        for index in range(1, 5):
            part = f'xl/worksheets/sheet{index}.xml'
            assert original.read(part) == left.read(part) == right.read(part)
    for book in (goal, fm, dbg, dbg_cache): book.close()


def test_default_sign_fault_has_no_zero_equity_root(full):
    _, left, right = full
    roots = [r['equity_income'] for s in right['scenarios'] for q in s['periods'] for r in q['entities'].values()]
    assert len(roots) == 216 and all(value != 0 for value in roots)
    assert any(value > 0 for value in roots) and any(value < 0 for value in roots)
    for result in (left, right):
        assert result['actual_LO_calls'] == result['model_calls'] == 0
        assert result['qualified'] is False

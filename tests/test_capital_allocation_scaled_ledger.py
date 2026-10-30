from copy import deepcopy
import importlib.util
from pathlib import Path
import struct

import pytest

from sheets_factory.workbook.capital_allocation_scaled import ledger, search_a, search_b, spec
from sheets_factory.workbook.capital_allocation import ledger as original

ROOT = Path(__file__).resolve().parents[1]
_module = importlib.util.spec_from_file_location('_scaled_journal_hand_cases', ROOT / 'tests/test_capital_allocation_ledger.py')
hand = importlib.util.module_from_spec(_module)
_module.loader.exec_module(hand)


def public(count, *, financed=False):
    value = hand.financed_spec() if financed else hand.specification()
    for index in range(18, count):
        extra = deepcopy(value['projects'][0])
        extra['id'] = f'P{index + 1:02d}'
        value['projects'].append(extra)
    return value


def choices(value, *selected):
    return {p['id']: int(p['id'] in selected) for p in value['projects']}


def test_original_complete_journal_preserved_without_original_public_loader(monkeypatch):
    value = public(18, financed=True)
    plan = choices(value, 'P01')
    expected = original.simulate(value, plan)
    monkeypatch.setattr(original, 'load_spec', lambda *a: pytest.fail('The original strict18 loader must not run'))
    assert ledger.simulate(value, plan) == expected


@pytest.mark.parametrize('count', (26, 28, 30))
def test_last_project_has_full_hand_calculated_postings_and_unselected_candidates(count):
    value = public(count)
    value['tax_rate_p12'] = spec.SCALE // 4
    last = f'P{count:02d}'
    before = deepcopy(value)
    result = ledger.simulate(value, choices(value, last))
    assert value == before
    assert result['feasible'] and result['objective_pence'] == 30
    assert result['optimisation_performed'] is result['unique_optimum_claimed'] is False
    for scenario in result['scenarios'].values():
        assert set(scenario['project_flows']) == {p['id'] for p in value['projects']}
        assert scenario['project_flows']['P01'][1]['revenue'] == 80
        assert scenario['project_flows'][last][1]['revenue'] == 80
        assert scenario['annual'][1]['revenue'] == 80
        assert scenario['annual'][1]['current_tax'] == 5
        assert scenario['annual'][2]['profit_distribution'] == 30
        assert scenario['all_journals_balance']
        assert any(row['event'] == last + '_acquisition' for row in scenario['journal'])
        assert not any(row['event'] == 'P01_acquisition' for row in scenario['journal'])
        assert all(row[field] == 0 for row in scenario['annual'] for field in
                   ('balance_check', 'cash_check', 'bank_check', 'capital_check', 'loss_check'))


@pytest.mark.parametrize('count', (26, 28, 30))
def test_last_project_real_margin_gap_is_not_zero_or_a_feasible_objective(count):
    value = public(count, financed=True)
    value['lp_commitment_pence'] = 100
    result = ledger.simulate(value, choices(value, f'P{count:02d}'))
    assert result['feasible'] is False and result['objective_pence'] is None
    assert result['scenarios']['S01']['first_violation'] == {
        'year': 2026, 'kind': 'unfunded_cash_deficiency', 'amount_pence': 33}
    assert result['scenarios']['S01']['annual'][2]['mandatory_margin'] == 38


@pytest.mark.parametrize('change', (
    lambda p: p.pop('P30'), lambda p: p.update(P31=0),
    lambda p: p.update(P30=True), lambda p: p.update(P30=1.0),
    lambda p: p.update(P30=-1), lambda p: p.update(P30=2),
))
def test_incomplete_or_nonbinary_plan_rejected(change):
    value = public(30)
    plan = choices(value, 'P30')
    change(plan)
    with pytest.raises(ValueError):
        ledger.simulate(value, plan)


def test_upstream_drift_fails_before_any_calculation(monkeypatch):
    monkeypatch.setitem(ledger.UPSTREAM, 'ledger', '0' * 64)
    with pytest.raises(ValueError, match='changed'):
        ledger.simulate(public(30), choices(public(30)))


@pytest.mark.parametrize('count', (26, 28, 30))
def test_nonprefix_last_project_toy_records_match_both_independent_kernels(tmp_path, count):
    value = public(count, financed=True)
    value['lp_commitment_pence'] = 250
    active = ['P01', f'P{count:02d}']
    expected = bytearray()
    for mask in range(4):
        plan = choices(value, *(key for bit, key in enumerate(active) if mask & (1 << bit)))
        state = ledger.simulate(value, plan)
        flags = sum(1 << si for si, sid in enumerate(spec.SCENARIO_IDS)
                    if state['scenarios'][sid]['feasible'])
        npvs = [state['scenarios'][sid]['npv_pence'] if state['scenarios'][sid]['feasible']
                else spec.NULL_NPV for sid in spec.SCENARIO_IDS]
        expected.extend(struct.pack(spec.RECORD_FORMAT, mask, flags, *npvs))
    import json
    a = search_a.enumerate_plans(value, tmp_path / 'a', active_project_ids=active)
    b = search_b.execute_prepared(search_b.prepare(value, tmp_path / 'b', active_project_ids=active))
    for reference in (a, b):
        receipt = json.loads(Path(reference['path']).read_bytes())
        assert receipt['plan_count'] == 4
        assert Path(receipt['records']['path']).read_bytes() == expected

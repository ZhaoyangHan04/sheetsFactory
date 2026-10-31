"""Explicit toy plans only; no complete18/30 search, workbook, LO or model."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import struct
import subprocess

import pytest

from sheets_factory.workbook.capital_allocation_scaled import fixed_plan_probe as probe
from sheets_factory.workbook.capital_allocation_scaled import spec as schema

ROOT = Path(__file__).resolve().parents[1]
_module = importlib.util.spec_from_file_location('_fixed_probe_hand_cases', ROOT / 'tests/test_capital_allocation_ledger.py')
hand = importlib.util.module_from_spec(_module)
_module.loader.exec_module(hand)


def read(ref):
    return json.loads(Path(ref['path']).read_text())


def choices(public, *selected):
    return {project['id']: int(project['id'] in selected) for project in public['projects']}


def declared(public):
    return [{'id': 'empty', 'plan': choices(public)},
            {'id': 'first', 'plan': choices(public, 'P01')},
            {'id': 'last', 'plan': choices(public, 'P18')},
            {'id': 'all', 'plan': choices(public, *(p['id'] for p in public['projects']))},
            {'id': 'empty_again', 'plan': choices(public)}]


def test_preparation_is_serialization_only_and_keeps_complete_plan_order(tmp_path, monkeypatch):
    public = hand.specification(); before = deepcopy(public)
    def forbidden(*args, **kwargs):
        raise AssertionError('Default preparation cannot execute finance, compile, search or start services')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    monkeypatch.setattr(probe.ledger, 'simulate', forbidden)
    monkeypatch.setattr(probe, 'DashboardServer', forbidden)
    monkeypatch.setattr(probe.search_a, 'enumerate_plans', forbidden)
    monkeypatch.setattr(probe.search_b, 'execute_prepared', forbidden)
    ref = probe.prepare(public, declared(public), tmp_path / 'prepared')
    frozen, checked, plans = probe.validate_prepared(ref)
    assert checked == public == before
    assert [row['id'] for row in plans] == ['empty', 'first', 'last', 'all', 'empty_again']
    assert [row['mask'] for row in plans] == [0, 1, 1 << 17, (1 << 18) - 1, 0]
    assert frozen['compiler_calls'] == frozen['kernel_calls'] == frozen['Decimal_forward_calls'] == 0
    assert frozen['enumeration_performed'] is frozen['ranking_performed'] is False
    assert frozen['global_optimum_claimed'] is frozen['qualified'] is False
    assert not (tmp_path / 'prepared/attempts').exists()


@pytest.mark.parametrize('mutation', ['empty', 'too_many', 'duplicate_id', 'unsafe_id',
                                    'missing_choice', 'extra_choice', 'bool_choice', 'float_choice', 'extra_field'])
def test_invalid_fixed_plan_declarations_fail_before_any_output(tmp_path, mutation):
    public = hand.specification(); plans = declared(public)
    if mutation == 'empty': plans = []
    if mutation == 'too_many': plans = [{'id': 'p' + str(i), 'plan': choices(public)} for i in range(257)]
    if mutation == 'duplicate_id': plans[1]['id'] = plans[0]['id']
    if mutation == 'unsafe_id': plans[1]['id'] = '../outside'
    if mutation == 'missing_choice': plans[1]['plan'].pop('P18')
    if mutation == 'extra_choice': plans[1]['plan']['P19'] = 0
    if mutation == 'bool_choice': plans[1]['plan']['P01'] = True
    if mutation == 'float_choice': plans[1]['plan']['P01'] = 1.0
    if mutation == 'extra_field': plans[1]['predicted_NPV'] = 10
    with pytest.raises(ValueError): probe.prepare(public, plans, tmp_path / 'rejected')
    assert not (tmp_path / 'rejected').exists()


def test_maximum_bound_is_explicit_not_a_search_dimension(tmp_path):
    public = hand.specification()
    plans = [{'id': 'duplicate_mask_' + str(i), 'plan': choices(public)} for i in range(256)]
    ref = probe.prepare(public, plans, tmp_path / 'max')
    frozen, _, checked = probe.validate_prepared(ref)
    assert frozen['plan_count'] == 256 and len(checked) == 256
    assert {row['mask'] for row in checked} == {0}
    with pytest.raises(ValueError, match='fresh'): probe.prepare(public, plans, tmp_path / 'max')


@pytest.mark.parametrize('artifact', ['raw_wires', 'explicit_masks', 'declared_plans', 'public_specification'])
def test_frozen_artifact_tampering_is_rejected_before_execution(tmp_path, artifact, monkeypatch):
    public = hand.specification()
    ref = probe.prepare(public, declared(public), tmp_path / artifact)
    frozen = read(ref)
    changed = frozen[artifact]['A'] if artifact == 'raw_wires' else frozen[artifact]
    with Path(changed['path']).open('a') as stream: stream.write(' ')
    def forbidden(*args, **kwargs): raise AssertionError('Tampered preparation must fail before process execution')
    monkeypatch.setattr(subprocess, 'run', forbidden)
    with pytest.raises(ValueError, match='artifact changed'): probe.execute_prepared(ref)
    assert not (tmp_path / artifact / 'attempts').exists()


def test_reserialization_detects_rebound_wrong_wire(tmp_path):
    public = hand.specification(); ref = probe.prepare(public, declared(public), tmp_path / 'rebound')
    frozen = read(ref); wire = Path(frozen['raw_wires']['A']['path'])
    wire.write_text(wire.read_text().replace('1000 0 1000 1000', '999 0 1000 1000', 1))
    frozen['raw_wires']['A'] = probe.reference(wire)
    Path(ref['path']).write_text(json.dumps(frozen))
    with pytest.raises(ValueError, match='wire differs'): probe.validate_prepared(ref['path'])


def test_wrapper_sources_reuse_only_their_corresponding_financial_kernel():
    for name in ('a', 'b'):
        text = (probe.ROOT / ('fixed_plan_probe_' + name + '.cpp')).read_text()
        assert '#include "search_' + name + '.cpp"' in text
        assert '#define main frozen_scaled_search_' + name + '_main' in text
        assert '#include "search_' + ('b' if name == 'a' else 'a') + '.cpp"' not in text
        assert 'half_table(' not in text and 'std::uint64_t(1) << p.' in text
        assert 'count > 256' in text


def test_actual_small_explicit_plans_match_both_native_kernels_and_complete_Decimal(tmp_path, monkeypatch):
    public = hand.specification()
    public['tax_rate_p12'] = schema.SCALE // 4
    public['lp_commitment_pence'] = 50
    prepared = probe.prepare(public, declared(public), tmp_path / 'actual_toy')
    actual = subprocess.run; calls = []
    def observe(command, **kwargs):
        assert Path(kwargs['env']['TMPDIR']).is_relative_to(tmp_path / 'actual_toy/attempts')
        calls.append(command)
        return actual(command, **kwargs)
    monkeypatch.setattr(subprocess, 'run', observe)
    result_ref = probe.execute_prepared(prepared)
    result = read(result_ref)
    assert len(calls) == 4 and sum('g++' in Path(call[0]).name for call in calls) == 2
    assert result['status'] == 'completed' and result['passed'] is True
    assert result['plan_count'] == 5 and result['all_declared_plans_checked'] is True
    assert result['records_equal_complete_for_declared_list'] is True
    assert result['Decimal_scenario_year_evaluations'] == 5 * 3 * 20
    assert result['kernel_results']['A']['records']['sha256'] == result['kernel_results']['B']['records']['sha256']
    assert result['checks'][1]['objective_pence'] == result['checks'][2]['objective_pence'] == 30
    assert result['checks'][3]['feasible'] is False and result['checks'][3]['objective_pence'] is None
    assert all(row['A_B_Decimal_match'] and row['all_journals_balance'] for row in result['checks'])
    for row in result['checks']:
        journal = read(row['ledger'])
        assert len(journal['scenarios']) == 3
        assert all(len(state['annual']) == 20 for state in journal['scenarios'].values())
        assert all(sum(entry['debits'].values()) == sum(entry['credits'].values())
                   for state in journal['scenarios'].values() for entry in state['journal'])
    dated = read(result['checks'][1]['dated_positive_postings'])
    assert dated['S01']['current_tax'] == [{'year': 2025, 'amount_pence': 5}, {'year': 2026, 'amount_pence': 5}]
    gaps = read(result['checks'][3]['dated_positive_postings'])
    assert gaps['S01']['funding_gap'][0] == {'year': 2024, 'amount_pence': 750}
    assert result['global_optimum_claimed'] is result['enumeration_performed'] is result['ranking_performed'] is False
    assert result['qualified'] is False and result['task_count'] == result['LO_calls'] == result['model_calls'] == 0
    assert all(key not in result for key in ('unique_best', 'best_mask', 'runnerup_mask', 'gap_pence'))
    started = read(result['started'])
    assert started['dashboard_url'].startswith('http://127.0.0.1:')
    assert read(probe.reference(tmp_path / 'actual_toy/producer.lock'))['status'] == 'released'
    summary = json.loads((Path(result_ref['path']).parent / 'summary.json').read_text())
    assert summary['run']['status'] == 'completed' and summary['run']['producer_active'] is False


def test_net_negative_half_penny_rounding_includes_opening_contribution(tmp_path):
    public = hand.specification()
    public.update(opening_cash_pence=1, minimum_cash_pence=0, lp_commitment_pence=1,
                  facility_limit_pence=0, tax_rate_p12=0)
    public['discount_factors_p12'] = hand.annual(schema.SCALE // 2)
    first = public['projects'][0]
    first.update(commission_year=2024, sale_year=2025, acquisition_cost_pence=1, depreciation_years=4,
                 sale_proceeds_pence=1, annual_revenue_pence=hand.annual(0), annual_opex_pence=hand.annual(0))
    plans = [{'id': 'empty', 'plan': choices(public)}, {'id': 'one', 'plan': choices(public, 'P01')}]
    result = read(probe.execute_prepared(probe.prepare(public, plans, tmp_path / 'halfpenny')))
    assert [row['objective_pence'] for row in result['checks']] == [-1, -1]
    assert all(row['A_B_Decimal_match'] for row in result['checks'])


def test_process_failure_is_terminal_preserved_and_releases_lease(tmp_path, monkeypatch):
    public = hand.specification(); output = tmp_path / 'failure'
    prepared = probe.prepare(public, declared(public), output)
    monkeypatch.setattr(subprocess, 'run', lambda command, **kwargs: subprocess.CompletedProcess(command, 1))
    with pytest.raises(ValueError, match='original logs'): probe.execute_prepared(prepared)
    failures = list((output / 'attempts').glob('*/failure.json'))
    assert len(failures) == 1
    failure = json.loads(failures[0].read_text())
    assert failure['status'] == 'failed' and failure['phase'] == 'compile_A'
    process = json.loads((failures[0].parent / 'compile_A/process.json').read_text())
    assert process['returncode'] == 1 and process['error'] is None
    assert (failures[0].parent / 'compile_A/stdout.txt').exists()
    assert not (failures[0].parent / 'receipt.json').exists()
    assert json.loads((output / 'producer.lock').read_text())['status'] == 'released'


@pytest.mark.parametrize('timeout', [0, True, 601, 1.0])
def test_invalid_execution_timeout_fails_without_attempts(tmp_path, timeout):
    public = hand.specification(); output = tmp_path / 'timeout'
    prepared = probe.prepare(public, declared(public), output)
    with pytest.raises(ValueError, match='one to 600'): probe.execute_prepared(prepared, timeout_seconds=timeout)
    assert not (output / 'attempts').exists()

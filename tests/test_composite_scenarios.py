"""Declared scenario safety, default execution and source-verification gates."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('composite_scenario_batch', ROOT / 'scripts/build_composite_sources.py')
batch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch)
CONFIG = ROOT / 'config/derived_composite_scenarios_v1.json'


def profiles():
    return batch.load_profiles(CONFIG)


def materialize(profile, directory):
    base = batch.load(ROOT / profiles()['base_config'])
    return batch.materialize_profile(profile, base, directory)


def test_ten_declared_contracts_keep_dates_currency_and_all_parent_regimes(tmp_path):
    declared = profiles()['profiles']
    assert 10 <= len(declared) <= 20
    assert [p['operating_entity'] for p in declared[:10]] == [f'T{i:02}' for i in range(1, 11)]
    assert len({p['mechanism'] for p in declared}) == len(declared)
    signatures = set()
    for profile in declared:
        record = materialize(profile, tmp_path / profile['id'])
        composite = batch.load(record['config']['path'])
        lease = batch.load(composite['lease_config'])
        programme = batch.load(composite['regulatory_config'])
        holding = batch.load(composite['holding_config'])
        assert lease['start_date'] == '2023-04-01' and lease['months'] == 240
        assert lease['currency'] == 'GBP_nominal'
        assert composite['operating_entity'] == profile['operating_entity']
        assert composite['operating_contract_revision'] == 2
        assert composite['operating_manifest'].endswith('portfolio_source_20261030T101350Z/manifest.json')
        assert batch.REQUIRED_REGIMES <= set(holding['required_observed_regimes'])
        assert all(set(row) == {'year', 'bank_rate', 'management_fee', 'claim_haircut'} for row in holding['annual_inputs'])
        signatures.add((tuple(c['share'] for c in programme['categories']),
                        tuple(tuple((e['month'], e['new_end_month'], e['retention_fraction']) for e in c['events'])
                              for c in lease['leases'])))
    assert len(signatures) >= 10


@pytest.mark.parametrize('section,patch', [
    ('programme', {'annual_inputs': [{'owner_capital': '1'}]}),
    ('holding', {'annual_defaults': {'bank_close': '1'}}),
    ('lease', {'P01': {'lease_liability_close': '1'}}),
])
def test_computed_annual_values_cannot_enter_public_input_patches(tmp_path, section, patch):
    profile = deepcopy(profiles()['profiles'][0])
    profile[section] = patch
    with pytest.raises(ValueError, match='public primitive'):
        materialize(profile, tmp_path / 'invalid')


def test_moved_lease_event_must_stay_on_contractual_payment_cycle(tmp_path):
    profile = deepcopy(profiles()['profiles'][1])
    profile['lease']['P02']['events']['85']['month'] = 86
    with pytest.raises(ValueError, match='payment-cycle'):
        materialize(profile, tmp_path / 'invalid')


def test_future_scenarios_refuse_implicit_or_legacy_operating_contract(tmp_path):
    base = batch.load(ROOT / 'config/derived_composite_finance_v1.json')
    with pytest.raises(ValueError, match='operating_contract_revision=2'):
        batch.materialize_profile(profiles()['profiles'][0], base, tmp_path / 'legacy')


def test_default_plan_never_calls_ledger_preflight_or_libreoffice(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Planning cannot execute finance or LibreOffice')
    monkeypatch.setattr(batch, 'preflight_case', forbidden)
    monkeypatch.setattr(batch, 'composite_build', forbidden)
    output = tmp_path / 'plan'
    result = batch.run_batch(CONFIG, output, limit=2, max_attempts=2, workers=2)
    assert result['status'] == 'planned_only'
    assert result['selected'] == [] and result['verified_derived_workbook_count'] == 0
    assert result['source_ancestor_unique_count'] is None
    assert result['api_calls'] == result['llm_tokens'] == 0
    assert len(batch.load(output / 'plan.json')['profiles']) == 2
    assert not (output / 'sources').exists()
    with pytest.raises(FileExistsError):
        batch.run_batch(CONFIG, output, limit=2, max_attempts=2)


def test_concurrency_is_bounded_before_creating_output(tmp_path):
    with pytest.raises(ValueError, match='two workers'):
        batch.run_batch(CONFIG, tmp_path / 'unsafe', workers=3)
    assert not (tmp_path / 'unsafe').exists()


def test_preflight_keeps_rejections_and_freezes_first_declared_passes_without_building(tmp_path, monkeypatch):
    def fake_preflight(record, destination):
        destination.mkdir(parents=True)
        if record['id'].startswith('C01-'):
            raise ValueError('Required holding regimes not activated: mandatory_margin')
        report = {'source_ancestors': [{'sha256': 'a' * 64}, {'sha256': 'b' * 64}],
                  'upstream_workbook_sha256': ['c' * 64, 'd' * 64]}
        batch.write(destination / 'preflight.json', report)
        return report
    def forbidden(*args, **kwargs):
        raise AssertionError('A preflight cannot build an actual workbook')
    monkeypatch.setattr(batch, 'preflight_case', fake_preflight)
    monkeypatch.setattr(batch, 'composite_build', forbidden)
    output = tmp_path / 'ledger-fixture-run'
    result = batch.run_batch(CONFIG, output, mode='preflight', limit=2, max_attempts=3, workers=2)
    assert result['attempted_profile_count'] == 3
    assert result['preflight_passed_count'] == 2 and result['preflight_rejected_count'] == 1
    assert result['verified_derived_workbook_count'] == 0 and result['selected'] == []
    assert result['source_ancestor_unique_count'] == 2
    frozen = batch.load(output / 'source_selection.json')
    assert frozen['profiles'] == [p['id'] for p in profiles()['profiles'][1:3]]
    failed = batch.load(output / 'preflight' / profiles()['profiles'][0]['id'] / 'failure.json')
    assert 'mandatory_margin' in failed['reason']


def operating_checks():
    return {'feasible': True, 'all_balanced': True, 'max_balance_error': 0,
            'max_cfo_reconciliation_error': 0, 'max_cash_reconciliation_error': 0,
            'max_income_reconciliation_error': 0, 'minimum_cash_gap': 0,
            'max_journal_error': 0, 'loan_a_payment_residual': 0,
            'irr_exists': True, 'irr_sign_changes': 1}


def test_preflight_rejects_absent_financing_regime_even_if_accounts_balance():
    ordinary = {'checks': {'journal_balanced': True}}
    operating = {'checks': operating_checks()}
    parent = {'checks': {'journal_balanced': True},
              'observed_regimes': {name: [2027] for name in batch.REQUIRED_REGIMES - {'mandatory_margin'}}}
    with pytest.raises(ValueError, match='mandatory_margin'):
        batch.validate_ledgers(ordinary, ordinary, operating, parent, batch.REQUIRED_REGIMES)
    parent['observed_regimes']['mandatory_margin'] = [2031]
    batch.validate_ledgers(ordinary, ordinary, operating, parent, batch.REQUIRED_REGIMES)
    operating['checks']['max_cash_reconciliation_error'] = 1
    with pytest.raises(ValueError, match='operating'):
        batch.validate_ledgers(ordinary, ordinary, operating, parent, batch.REQUIRED_REGIMES)


def source_receipts(directory):
    private = directory / 'private'
    private.mkdir(parents=True)
    goal = directory / 'goal.xlsx'
    goal.write_bytes(b'fixed test artifact for receipt-gating only')
    first, second = private / 'pass1.xlsx', private / 'pass2.xlsx'
    first.write_bytes(b'first actual-calculation receipt fixture')
    second.write_bytes(b'second actual-calculation receipt fixture')
    for name in batch.AUDIT_NAMES:
        batch.write(private / (name + '_financial_audit.json'),
                    {'passed': True, 'checked_cells': 1, 'workbook': batch.ref(goal)})
    batch.write(private / 'stability.json', {'stable': True, 'comparison': {'reward': 1},
        'first_against_goal': {'reward': 1}, 'second_against_goal': {'reward': 1},
        'first': str(first), 'second': str(second)})
    return {'financial_audit_passed': True, 'financial_audits': {name: {'passed': True} for name in batch.AUDIT_NAMES},
            'local_path': str(goal), 'derived_workbook_sha256': batch.sha(goal),
            'selected': [{'sha256': batch.sha(goal)}],
            'runtime': {'image_id': batch.RUNTIME_ID}, 'stability': batch.ref(private / 'stability.json')}


def test_selected_requires_four_real_audit_receipts_and_two_distinct_stable_artifacts(tmp_path):
    manifest = source_receipts(tmp_path / 'source')
    proof = batch.verify_built_source(manifest, tmp_path / 'source')
    assert len(proof['four_audits']) == 4 and len(proof['actual_stability_workbooks']) == 2
    manifest['financial_audits'].pop('operating')
    with pytest.raises(ValueError, match='Four actual financial audit'):
        batch.verify_built_source(manifest, tmp_path / 'source')


def test_changed_second_stability_receipt_is_not_verified(tmp_path):
    manifest = source_receipts(tmp_path / 'source')
    path = Path(manifest['stability']['path'])
    stable = batch.load(path)
    stable['second_against_goal']['reward'] = 0
    path.write_text(json.dumps(stable))
    manifest['stability'] = batch.ref(path)
    with pytest.raises(ValueError, match='Two actual stable'):
        batch.verify_built_source(manifest, tmp_path / 'source')

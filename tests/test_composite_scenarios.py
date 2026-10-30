"""Declared scenario safety, default execution and source-verification gates."""
from copy import deepcopy
from decimal import Decimal
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('composite_scenario_batch', ROOT / 'scripts/build_composite_sources.py')
batch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(batch)
CONFIG = ROOT / 'config/derived_composite_scenarios_v1.json'
FINANCIAL_CONFIG = ROOT / 'config/composite_financial_variant_catalog_v1.json'


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


def financial_profiles():
    return batch.load_profiles(FINANCIAL_CONFIG)


def test_new_catalog_declares_twenty_input_only_variants_and_preserves_optional_contracts(tmp_path):
    catalog = financial_profiles()
    assert len(catalog['profiles']) == 20
    assert catalog['base_config'] == 'config/derived_composite_finance_v4.json'
    assert [p['operating_entity'] for p in catalog['profiles'][:10]] == [f'T{i:02}' for i in range(1, 11)]
    assert {p['operating_entity'] for p in catalog['profiles']} == {f'T{i:02}' for i in range(1, 11)}
    assert len({p['mechanism'] for p in catalog['profiles']}) == 20
    original = (ROOT / 'config/derived_contingent_recovery_v2.json').read_bytes()
    signatures = set()
    for profile in catalog['profiles']:
        record = batch.materialize_profile(profile, batch.load(ROOT / catalog['base_config']), tmp_path / profile['id'])
        config = batch.load(record['config']['path'])
        contingent = batch.load(config['contingent_config'])
        waterfall = batch.load(config['waterfall_config'])
        assert [row['year'] for row in contingent['annual_terms']] == batch.YEARS
        assert waterfall['years'] == batch.YEARS and waterfall['opening_date'] == '2023-04-01'
        assert config['minimum_uncapped_feedback_years'] == 12
        assert len(config['required_waterfall_regimes']) == 6
        assert set(record['inputs']) == {'lease_config', 'regulatory_config', 'holding_config', 'contingent_config', 'waterfall_config'}
        signatures.add(tuple(record['inputs'][key]['sha256'] for key in sorted(record['inputs'])))
    assert len(signatures) == 20
    assert (ROOT / 'config/derived_contingent_recovery_v2.json').read_bytes() == original


def test_default_contingent_patches_preserve_inactive_zero_terms_and_dated_changes_are_explicit():
    spec = batch.load(ROOT / 'config/derived_contingent_recovery_v2.json')
    changed = batch.materialize_contingent(spec,
        {'contract_defaults': {'P01': {'rate': '0.010'}}}, 'C99-fixture')
    inactive = [(year['year'], item) for year in changed['annual_terms'] for item in year['contracts']
                if item['lease_id'] == 'P01' and not item['active']]
    assert inactive and all(item['rate'] == '0' and item['annual_cap'] == '0.00' for _, item in inactive)
    assert all(item['rate'] == '0.010' for year in changed['annual_terms'] for item in year['contracts']
               if item['lease_id'] == 'P01' and item['active'])
    changed = batch.materialize_contingent(spec, {'annual_overrides': [{'years': [2037],
        'contracts': {'P01': {'active': True, 'rate': '0.009', 'annual_cap': '180000.00'}}}]}, 'C99-fixture')
    row = next(row for row in changed['annual_terms'] if row['year'] == 2037)
    assert row['contracts'][0]['active'] is True
    assert next(row for row in spec['annual_terms'] if row['year'] == 2037)['contracts'][0]['active'] is False


@pytest.mark.parametrize('patch', [
    {'annual_defaults': {'current_tax': '1'}},
    {'contract_defaults': {'P01': {'variable_rent': '1'}}},
    {'contract_defaults': {'P01': {'active': True}}},
    {'annual_overrides': [{'years': [2044], 'eligible_fraction': '.85'}]},
    {'annual_overrides': [{'years': [2030], 'contracts': {'P01': {'annual_cap': '1.01'}}}]},
    {'annual_overrides': [{'years': [2030], 'eligible_fraction': '.82'},
                          {'years': [2030], 'eligible_fraction': '.83'}]},
])
def test_invalid_or_computed_contingent_patches_fail_closed(patch):
    with pytest.raises(ValueError):
        batch.materialize_contingent(batch.load(ROOT / 'config/derived_contingent_recovery_v2.json'), patch, 'C99-fixture')


@pytest.mark.parametrize('section,patch', [
    ('waterfall', {'lp_distribution': '1'}),
    ('waterfall', {'opening_date': '2024-01-01'}),
    ('programme', {'annual_input_overrides': {'2030': {'owner_capital': '1'}}}),
    ('programme', {'annual_input_overrides': {'2044': {'collection_cap_nominal': '1'}}}),
])
def test_optional_modules_and_dated_overrides_accept_no_calculated_answers(tmp_path, section, patch):
    catalog = financial_profiles()
    profile = deepcopy(catalog['profiles'][0])
    profile[section] = patch
    with pytest.raises(ValueError):
        batch.materialize_profile(profile, batch.load(ROOT / catalog['base_config']), tmp_path / 'invalid')


def optional_programme():
    annual = {year: {'unique_fixed_point': True, 'variable_rent_total': Decimal('100.00'),
        'proof': {'unique_on_entire_contractual_grid': True, 'endpoint_coalescence': True,
                  'lower_fixed_point': Decimal('100.00'), 'upper_fixed_point': Decimal('100.00')}}
              for year in batch.YEARS}
    return {'observed_regimes': {name: list(batch.YEARS[:-1]) for name in batch.PROGRAMME_REGIMES},
            'contingent_recovery': {'all_years_unique': True, 'annual': annual}}


def optional_parent():
    return {'partner_waterfall': [{'year': year} for year in batch.YEARS],
            'observed_waterfall_regimes': {name: [2038] for name in batch.WATERFALL_REGIMES}}


def optional_config():
    return {'contingent_config': 'explicit fixture only', 'waterfall_config': 'explicit fixture only',
            'minimum_uncapped_feedback_years': 12,
            'required_waterfall_regimes': sorted(batch.WATERFALL_REGIMES - {'capital_after_flip'})}


@pytest.mark.parametrize('change,message', [
    ('missing_year', 'twenty contingent'), ('multiple', 'twenty contingent'),
    ('endpoints', 'twenty contingent'), ('too_few_feedback', 'uncapped'),
    ('missing_waterfall_year', 'twenty independent'), ('missing_flip', 'partnership'),
    ('missing_tax_fifo', 'programme'), ('unknown_waterfall', 'Unknown required'),
])
def test_optional_preflight_requires_all_years_uniqueness_and_every_declared_regime(change, message):
    programme, parent, config = optional_programme(), optional_parent(), optional_config()
    if change == 'missing_year':
        programme['contingent_recovery']['annual'].pop(2043)
    elif change == 'multiple':
        programme['contingent_recovery']['annual'][2031]['proof']['endpoint_coalescence'] = False
    elif change == 'endpoints':
        programme['contingent_recovery']['annual'][2031]['proof']['upper_fixed_point'] = Decimal('200.00')
    elif change == 'too_few_feedback':
        programme['observed_regimes']['uncapped_contingent_feedback'] = list(range(2024, 2030))
    elif change == 'missing_waterfall_year':
        parent['partner_waterfall'].pop()
    elif change == 'missing_flip':
        parent['observed_waterfall_regimes']['carry_flip_earned'] = []
    elif change == 'missing_tax_fifo':
        programme['observed_regimes']['tax_loss_fifo_use'] = []
    elif change == 'unknown_waterfall':
        config['required_waterfall_regimes'] = ['fake_balancing_plug']
    with pytest.raises(ValueError, match=message):
        batch.validate_optional_ledgers(config, programme, parent, required_programme=batch.PROGRAMME_REGIMES)


def test_optional_preflight_receipt_matches_builder_kwargs_without_emitter_or_engine(tmp_path, monkeypatch):
    catalog = financial_profiles()
    record = batch.materialize_profile(catalog['profiles'][0],
        batch.load(ROOT / catalog['base_config']), tmp_path / 'config')
    config = batch.load(record['config']['path'])
    reg_config = batch.load(config['regulatory_config'])
    reg_raw, op_raw = tmp_path / 'original-reg.xlsx', tmp_path / 'original-op.xlsx'
    reg_raw.write_bytes(b'explicit original regulatory provenance fixture')
    op_raw.write_bytes(b'explicit original operating provenance fixture')
    record['regulatory_original_ancestor'] = {'local_path': str(reg_raw), 'sha256': batch.sha(reg_raw),
                                             'url': reg_config['official_url']}
    record['required_preflight_programme_regimes'] = sorted(batch.PROGRAMME_REGIMES)
    op_spec = {'source_lineage': {'sha256': batch.sha(op_raw), 'download_url': 'https://example.invalid/fixture'}}
    op = {'checks': operating_checks()}
    monkeypatch.setattr(batch, 'prepare_spec', lambda *args: {'years': batch.YEARS, 'parameters': {}})
    monkeypatch.setattr(batch, 'operating_inputs', lambda *args: (
        {'source_ancestor': {'local_path': str(op_raw), 'sha256': batch.sha(op_raw)},
         'derived_workbook_sha256': 'd' * 64}, op_spec, op))
    monkeypatch.setattr(batch, 'simulate_lease', lambda spec: {'annual': {year: {} for year in batch.YEARS},
                                                            'checks': {'explicit_fixture': True}})
    observed = {}
    def regulatory(spec, *, external_lease_annual, contingent_spec):
        observed['contingent'] = contingent_spec
        result = optional_programme()
        result['checks'] = {'explicit_fixture': True}
        return result
    def parent(spec, bridge, project, project_spec, *, waterfall_spec):
        observed['waterfall'] = waterfall_spec
        result = optional_parent()
        result.update(checks={'explicit_fixture': True},
            annual=[{'lp_called_close': Decimal(100), 'lp_remaining': Decimal(1000)}],
            observed_regimes={key: [2031] for key in batch.REQUIRED_REGIMES})
        return result
    monkeypatch.setattr(batch, 'regulatory_simulate', regulatory)
    monkeypatch.setattr(batch, 'simulate_parent', parent)
    monkeypatch.setattr(batch, 'annual_bridge', lambda *args: {'explicit_fixture': True})
    monkeypatch.setattr(batch, 'composite_build', lambda *args: pytest.fail('No emitter or LO allowed'))
    report = batch.preflight_case(record, tmp_path / 'preflight')
    assert observed['contingent'] == batch.load(config['contingent_config'])
    assert observed['waterfall'] == batch.load(config['waterfall_config'])
    assert report['enabled_optional_modules'] == ['contingent', 'waterfall']
    assert report['expected_component_audit_names'] == sorted(batch.AUDIT_NAMES | {'contingent'})
    assert report['contingent_unique_years'] == batch.YEARS
    assert len(report['source_ancestors']) == 2
    assert report['libreoffice_calls'] == report['model_calls'] == 0
    assert report['source_financial_audit_claimed'] is False
    assert len(report['ledger_refs']) == 4  # Optional journals are embedded in programme/holding.


def test_optional_actual_source_requires_five_audits_recipe_and_waterfall_regimes(tmp_path):
    directory = tmp_path / 'source'
    manifest = source_receipts(directory)
    config = optional_config()
    manifest['financial_audits']['contingent'] = {'passed': True}
    batch.write(directory / 'private/contingent_financial_audit.json',
        {'passed': True, 'checked_cells': 180, 'workbook': batch.ref(manifest['local_path'])})
    manifest['contingent_all_years_unique'] = True
    manifest['observed_contingent_regimes'] = {'uncapped_contingent_feedback': list(batch.YEARS[:-1])}
    manifest['observed_waterfall_regimes'] = optional_parent()['observed_waterfall_regimes']
    recipe = directory / 'private/explicit_recipe_fixture.py'
    recipe.write_text('# Explicit receipt fixture, not a financial implementation.\n')
    manifest['calculation_implementations'] = {str(recipe): batch.ref(recipe)}
    proof = batch.verify_built_source(manifest, directory, config)
    assert len(proof['component_audits']) == 5 and 'four_audits' not in proof
    assert 'holding financial audit' in proof['waterfall_audit_scope']
    manifest['financial_audits'].pop('contingent')
    with pytest.raises(ValueError, match='Five actual financial audit'):
        batch.verify_built_source(manifest, directory, config)


def test_recipe_binds_actual_optional_modules_and_input_configs():
    hashes = batch.recipe_hashes(ROOT, FINANCIAL_CONFIG)
    for path in ('config/derived_composite_finance_v4.json', 'config/derived_contingent_recovery_v2.json',
        'config/derived_partner_waterfall_v2.json',
        'src/sheets_factory/workbook/contingent_recovery/solver.py',
        'src/sheets_factory/workbook/partner_waterfall/ledger.py',
        'src/sheets_factory/workbook/partner_waterfall/contract.py'):
        assert hashes[path] == batch.sha(ROOT / path)


def test_sequential_preflight_preserves_rejected_endpoint_proof_and_selects_no_built_source(tmp_path, monkeypatch):
    import threading
    from sheets_factory.workbook.contingent_recovery.solver import NonUniqueFixedPointError
    observed = []
    def fixture_preflight(record, destination):
        destination.mkdir(parents=True)
        observed.append((record['id'], threading.current_thread().name))
        if len(observed) == 1:
            raise NonUniqueFixedPointError('Explicit fixture with different endpoints',
                {'lower_fixed_point': Decimal('100.00'), 'upper_fixed_point': Decimal('200.00'),
                 'unique_on_entire_contractual_grid': False})
        result = {'source_ancestors': [{'sha256': 'a' * 64}, {'sha256': 'b' * 64}],
                  'upstream_workbook_sha256': ['c' * 64, 'd' * 64]}
        batch.write(destination / 'preflight.json', result)
        return result
    monkeypatch.setattr(batch, 'preflight_case', fixture_preflight)
    monkeypatch.setattr(batch, 'composite_build', lambda *args: pytest.fail('Preflight cannot build a source'))
    output = tmp_path / 'explicit-rejection-fixture'
    result = batch.run_batch(FINANCIAL_CONFIG, output, mode='preflight', limit=1, max_attempts=2, workers=2)
    assert all(thread == threading.current_thread().name for _, thread in observed)
    assert result['preflight_workers'] == 1 and result['workers'] == 2
    assert result['preflight_passed_count'] == result['preflight_rejected_count'] == 1
    assert result['verified_derived_workbook_count'] == 0 and result['selected'] == []
    assert result['source_ancestor_unique_count'] == 2
    assert result['api_calls'] == result['llm_tokens'] == 0
    failed = batch.load(output / 'preflight' / observed[0][0] / 'failure.json')
    assert failed['proof']['lower_fixed_point'] == '100.00'
    assert failed['proof']['upper_fixed_point'] == '200.00'
    assert failed['proof']['unique_on_entire_contractual_grid'] is False

"""Public production primitives plus tiny report-binding tests; no large ledger."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

from sheets_factory.workbook.entity_group import catalog
from sheets_factory.workbook.entity_group.ledger import simulate

ROOT = Path(__file__).resolve().parents[1]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


entry = load(ROOT / 'scripts/prepare_entity_group_specs.py', 'entity_group_catalog_entry')
toy = load(ROOT / 'tests/test_entity_group_ledger.py', 'entity_group_catalog_hand_fixture')


def test_fixed_ten_actual_production_dimensions_and_distinct_dated_graphs():
    settings = catalog.load_catalog()
    specs = [catalog.build_spec(p, settings) for p in catalog.PROFILE_IDS]
    structures = [catalog.structural_evidence(s) for s in specs]
    assert len(specs) == len({s['structure_sha256'] for s in structures}) == 10
    assert len({s['spec_sha256'] for s in structures}) == 10
    for s, evidence in zip(specs, structures):
        assert (len(s['entities']), len(s['months']), len(s['scenarios'])) == (24, 120, 3)
        assert s['months'][0] == '2024-04-01' and s['months'][-1] == '2034-03-01'
        assert s['plan_policy'] == 'provided_fixed_not_an_optimisation_task'
        assert sum(s['fixed_plan'].values()) == 18 and len(s['fixed_plan']) == 24
        assert len(s['intercompany_loans']) == 24
        assert len(s['intercompany_terms']) == len(s['bank_terms']) == 48
        assert all(e['tax_carry_months'] == e['interest_carry_months'] == 3 for e in s['entities'])
        assert {e['currency'] for e in s['entities']} == {'GBP', 'USD', 'EUR'}
        assert evidence['full_ledger_executed'] is evidence['actual_mechanism_activation_certified'] is False
        assert evidence['treasury_entities'] == 6
    # Public contractual/dated changes, not ten copies with different money units.
    assert specs[0]['bank_priority'] != specs[1]['bank_priority']
    assert specs[0]['intercompany_loans'] != specs[2]['intercompany_loans']
    assert specs[0]['intercompany_terms'] != specs[4]['intercompany_terms']


def test_G01_hand_inspection_of_true_business_primitives():
    s = catalog.build_spec('G01')
    assert s['shared_bank_limit_gbp_pence'] == 35000
    assert s['fixed_plan']['P01'] == 0 and s['fixed_plan']['P03'] == 1
    assert s['entities'][0]['additional_commitment_minor'] == 0
    assert s['entities'][2]['additional_commitment_minor'] == 80000
    project = s['projects'][2]
    assert project['revenue_minor']['2024-08-01'] == 1000
    assert project['opex_minor']['2024-08-01'] == 8000
    assert project['revenue_minor']['2025-02-01'] == 12000
    assert s['intercompany_loans'][6] == {'id': 'L07', 'lender_id': 'E03', 'borrower_id': 'E06', 'currency': 'GBP'}
    terms = [t for t in s['intercompany_terms'] if t['loan_id'] == 'L07']
    assert [(t['effective_month'], t['limit_minor']) for t in terms] == [('2024-04-01', 0), ('2025-02-01', 30000)]
    assert s['loan_priority'][:2] == ['L07', 'L08']


@pytest.mark.parametrize('change', [
    lambda c: c['profiles'].pop(),
    lambda c: c['profiles'].reverse(),
    lambda c: c['profiles'][0].update(phase_order=[True, 1, 2, 3, 4, 5]),
    lambda c: c['profiles'][0].update(treasury_owner=[0] * 6),
    lambda c: c['profiles'][0].update(bridge_first=1),
    lambda c: c['profiles'][0].update(money_percent=1000),
    lambda c: c.update(tax_carry_months=120),
    lambda c: c.update(profiles=[None] * 10),
])
def test_catalog_rejects_incomplete_or_undeclared_contract(tmp_path, change):
    settings = catalog.load_catalog()
    change(settings)
    path = tmp_path / 'bad.json'
    path.write_text(json.dumps(settings))
    with pytest.raises(ValueError):
        catalog.load_catalog(path)


def test_default_prepare_is_immutable_raw_only_and_does_not_call_ledger(tmp_path, monkeypatch):
    import sheets_factory.workbook.entity_group.ledger as ledger
    monkeypatch.setattr(ledger, 'simulate', lambda *a, **k: pytest.fail('Preparation must not execute a ledger'))
    output = tmp_path / 'specifications'
    reference = entry.prepare(catalog.CONFIG, output)
    assert reference == entry.ref(output / 'catalog_manifest.json')
    manifest = entry.validate_prepared(output)
    assert manifest['profile_order'] == list(catalog.PROFILE_IDS)
    assert manifest['ledger_executions'] == manifest['workbook_engine_calls'] == manifest['model_calls'] == 0
    assert manifest['qualified'] is False and manifest['selected'] == []
    assert manifest['provenance']['new_company_is_an_original_source_company'] is False
    assert len(manifest['provenance']['raw_ancestor_hashes_for_provenance_only']) == 2
    assert not list(output.rglob('*.xlsx'))
    with pytest.raises(ValueError, match='fresh'):
        entry.prepare(catalog.CONFIG, output)
    path = output / 'G01.json'
    public = json.loads(path.read_text())
    public['shared_bank_limit_gbp_pence'] += 1
    path.write_text(json.dumps(public))
    with pytest.raises(ValueError, match='changed'):
        entry.validate_prepared(output)


def test_reachability_requires_real_dated_positive_amounts_not_summary_flags():
    public = toy.specification()
    result = simulate(public)
    for scenario in result['scenarios'].values():
        scenario['all_declared_mechanisms_active'] = True
        for record in scenario['mechanism_activation'].values():
            record['active'] = True
    evidence = catalog.reachability_evidence(public, result)
    assert evidence['passed'] is False  # Tiny hand fixture has no shared facility/FX/cure.
    assert evidence['feasible'] is True
    assert evidence['independent_financial_audit'] is False
    for scenario in evidence['scenarios'].values():
        assert scenario['entity_months_checked'] == 6
        assert scenario['mechanisms']['opening_trap_applied']['witnesses'][0]['restricted_minor'] == 20
        assert scenario['mechanisms']['intercompany_interest']['witnesses'][0]['amount_minor'] == 10
        assert scenario['mechanisms']['shared_facility_contention']['active'] is False


@pytest.mark.parametrize('change, message', [
    (lambda r: r.update(spec_sha256='0' * 64), 'bind'),
    (lambda r: r['scenarios']['S01']['entities']['E01']['monthly'].pop(), 'monthly'),
    (lambda r: r['scenarios']['S01']['entities']['E02']['monthly'][0]['residuals'].update(cash=1), 'residual'),
    (lambda r: r['scenarios']['S01']['group_monthly'][0].update(principal_elimination_residual_gbp_numerator=1), 'bridge'),
    (lambda r: r['scenarios']['S01']['entities']['E02']['monthly'][0].update(funding_gap=1), 'Feasibility'),
    (lambda r: r.update(fixed_plan={'P01': 1, 'P02': 1}), 'bind'),
])
def test_reachability_rejects_unbound_or_incomplete_reports(change, message):
    public = toy.specification()
    result = simulate(public)
    change(result)
    with pytest.raises(ValueError, match=message):
        catalog.reachability_evidence(public, result)


def test_failure_to_complete_original_attempt_is_retained_not_rerun(tmp_path):
    output = tmp_path / 'prepared'
    entry.prepare(catalog.CONFIG, output)
    attempt = tmp_path / 'attempt'
    attempt.mkdir()
    source = output / 'G01.json'
    terminal = {'kind': 'entity_group_G01_authorized_integer_attempt', 'source': entry.ref(source),
                'completed': False, 'workbook_engine_calls': 0, 'model_calls': 0}
    path = attempt / 'terminal.json'
    path.write_text(json.dumps(terminal))
    before = path.read_bytes()
    with pytest.raises(ValueError, match='explicit existing'):
        entry.attach_first_ledger(output, attempt)
    assert path.read_bytes() == before
    assert not (output / 'first_ledger_addendum.json').exists()


def test_unknown_profile_is_rejected():
    with pytest.raises(ValueError, match='Unknown'):
        catalog.build_spec('G11')


def test_recipe_cannot_be_emptied_or_redirected(tmp_path):
    output = tmp_path / 'prepared'
    entry.prepare(catalog.CONFIG, output)
    path = output / 'catalog_manifest.json'
    manifest = json.loads(path.read_text())
    manifest['recipe'] = []
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='recipe identities'):
        entry.validate_prepared(output)

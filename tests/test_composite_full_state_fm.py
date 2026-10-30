"""Offline target and routing tests. Fixtures do not certify financial truth."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
from pathlib import Path
from threading import RLock
from types import SimpleNamespace

import openpyxl
import pytest
import yaml

from sheets_factory.core.node import TaskRejected
from sheets_factory.pipelines.factory import FactoryPipeline
from sheets_factory.task_adapters import composite_full_state_fm as adapter
from sheets_factory.task_adapters import public_workbook_scope as scope

ROOT = Path(__file__).resolve().parents[1]


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')
    return scope.reference(path)


@pytest.fixture
def books(monkeypatch):
    formula, cached = openpyxl.Workbook(), openpyxl.Workbook()
    for book in (formula, cached):
        book.remove(book.active)
    leases = ['Lease P0' + str(i) for i in range(1, 5)]
    rows = [(sheet, adapter.LEASE_FIELDS, 240, 3) for sheet in leases]
    rows += [('Operating Covenants', adapter.COVENANT_FIELDS, 36, 3),
             ('Operating Cash Flow', ['optional_allocation_allowed'], 36, 3),
             ('Operating Equity Value', ['annual_discount_rate', 'monthly_discount_rate'], 1, 2),
             ('Partner Waterfall', adapter.PARTNER_FIELDS, 20, 3),
             ('Finance', ['cash'], 1, 3)]
    for name, fields, periods, first in rows:
        fs, cs = formula.create_sheet(name), cached.create_sheet(name)
        for ri, field in enumerate(fields, 3):
            fs.cell(ri, 1, field)
            cs.cell(ri, 1, field)
            for col in range(first, first + periods):
                fs.cell(ri, col, '=1')
                cs.cell(ri, col, 1)
    # Provided dates, nonformula inputs and unrelated blanks must stay outside.
    formula['Finance']['D3'] = datetime(2024, 1, 1)
    cached['Finance']['D3'] = datetime(2024, 1, 1)
    formula['Finance']['E3'] = 7
    cached['Finance']['E3'] = 7
    monkeypatch.setattr(adapter.monetary, '_financial_scope', lambda book: {'version': 'composite_financial_only_v4'})
    monkeypatch.setattr(adapter.monetary, '_lease_sheets', lambda book: leases)
    monkeypatch.setattr(adapter.openpyxl, 'load_workbook',
        lambda *a, **kw: cached if kw.get('data_only') else formula)
    old = {'title': 'old', 'public_instruction': 'Complete financial outputs using existing nonmonetary state helpers.',
        'public_rules': ['Use public contracts.'], 'reference_evidence': [
            'Financial-only reconstruction scope: nonmonetary event, calendar and contractual state helpers remain provided.',
            'Public business policy: Lease Read Me.'],
        'mask_ranges': [{'sheet': 'Finance', 'range': 'C3', 'reason': 'Cash', 'business_rule': 'Contract cash.'}],
        'edits': [], 'scenario_inputs': [], 'protected_inputs': ["'Finance'!E3"],
        'target_sheets': [r[0] for r in rows], 'involved_sheets': formula.sheetnames, 'native_issues': []}
    monkeypatch.setattr(adapter.monetary, 'propose_task', lambda *a, **kw: deepcopy(old))
    return SimpleNamespace(formula=formula, cached=cached, old=old)


def test_exact_explicit_states_and_monetary_superset(books):
    plan = adapter.propose_task('offline.xlsx')
    before = adapter.mask_cells(books.old)
    after = adapter.mask_cells(plan)
    states = adapter.state_cells(books.formula, books.cached)
    assert before < after and after - before == states.keys()
    assert len(states) == 13854 and len(after) == 13855
    assert ('Finance', 'D3') not in after and ('Finance', 'E3') not in after and ('Finance', 'F3') not in after
    assert plan['protected_inputs'] == books.old['protected_inputs'] and plan['scenario_inputs'] == []
    assert books.old['public_instruction'].endswith('existing nonmonetary state helpers.')
    assert 'provided nonmonetary state helpers' not in plan['public_instruction']
    assert 'existing nonmonetary state helpers' not in plan['public_instruction']
    assert plan['public_instruction'].endswith(scope.CLAUSES['financial_modeling'])
    assert not any(text.startswith('Financial-only reconstruction scope:') for text in plan['reference_evidence'])
    assert adapter.RULE in plan['public_rules'] and set(adapter.STATE_RULES) <= set(plan['public_rules'])


@pytest.mark.parametrize('value', [None, '', True, float('nan'), float('inf'), '#VALUE!', datetime(2024, 1, 1)])
def test_unsupported_selected_cache_is_rejected(books, value):
    books.cached['Lease P01']['C3'] = value
    with pytest.raises(ValueError, match='finite numeric cache'):
        adapter.state_cells(books.formula, books.cached)


def test_selected_input_or_blank_is_not_masked(books):
    books.formula['Lease P01']['C3'] = 0
    with pytest.raises(ValueError, match='existing scalar formula'):
        adapter.state_cells(books.formula, books.cached)


def test_duplicate_public_label_is_rejected(books):
    books.formula['Lease P01']['A40'] = adapter.LEASE_FIELDS[0]
    with pytest.raises(ValueError, match='requires one'):
        adapter.state_cells(books.formula, books.cached)


def test_already_masked_state_and_rectangle_overlap_are_rejected(books):
    books.old['mask_ranges'].append({'sheet': 'Lease P01', 'range': 'C3', 'reason': 'State', 'business_rule': 'State.'})
    with pytest.raises(ValueError, match='already includes'):
        adapter.propose_task('offline.xlsx')
    with pytest.raises(ValueError, match='overlap'):
        adapter.mask_cells({'mask_ranges': [books.old['mask_ranges'][0]] * 2})


def test_actual_factory_claim_routes_fm_masks_to_asserted_formula_edits(books, tmp_path):
    plan = adapter.propose_task('offline.xlsx')
    baseline = tmp_path / 'baseline.xlsx'
    baseline.write_bytes(b'Offline asserted-formula routing fixture')
    audit = SimpleNamespace(snapshot=lambda: {'tasks': []}, task=lambda *a, **kw: None)
    pipeline = object.__new__(FactoryPipeline)
    pipeline.config = {'run': {}, 'construction': {'max_edit_count': {'financial_modeling': 100000},
        'analysis_limits': {'max_mask_ranges': 1024, 'max_profile_cells': 500000}}}
    pipeline.audit, pipeline.lock, pipeline.target_claims = audit, RLock(), {}
    context = SimpleNamespace(task_id='offline-fm', mode='financial_modeling',
        config=pipeline.config, data={'plan': plan, 'baseline': baseline, 'source_id': 'fixture'})
    pipeline._claim_targets(context)
    compiled = context.data['plan']
    assert 'mask_ranges' not in compiled and len(compiled['edits']) == 13855
    assert all(edit['before'] == '=1' and edit['after'] is None for edit in compiled['edits'])
    assert {(e['sheet'], e['cell']) for e in compiled['edits']} == adapter.mask_cells(plan)


def test_no_debug_dispatch():
    with pytest.raises(TaskRejected, match='financial_modeling'):
        adapter.propose_task('never-read.xlsx', 'debugging')


def test_frozen_policy_and_only_plan_registry_change(tmp_path):
    file = ROOT / 'config/task_adapters/composite_full_state_fm_v1.json'
    assert adapter.load_policy(scope.reference(file)) == adapter.POLICY_SPEC
    base = yaml.safe_load((ROOT / 'config/task_adapters/public_workbook_scope_nodes.yaml').read_text())
    new = yaml.safe_load((ROOT / 'config/task_adapters/composite_full_state_fm_nodes.yaml').read_text())
    assert {key for key in base['nodes'] if base['nodes'][key] != new['nodes'][key]} == {'plan'}
    assert len(new['nodes']) == 11
    for value in [True, 2]:
        changed = deepcopy(adapter.POLICY_SPEC); changed['version'] = value
        with pytest.raises(ValueError, match='frozen version'):
            adapter.load_policy(dump(tmp_path / str(value) / 'bad.json', changed))


def test_minimal_public_encoding_definitions_do_not_include_answers():
    text = ' '.join(adapter.STATE_RULES)
    for phrase in ('event month minus one', 'including a supplied zero rate', 'without a covenant test',
                   'first year with the higher carry', 'before a flip is earned', 'unqualified'):
        assert phrase in text.lower()
    assert not any(token in text for token in ('private/', 'goal.xlsx', 'C01-', '60193', '13854', '46339'))
    assert 'full D' not in text and 'target values' not in text


@pytest.fixture
def audit_fixture(tmp_path):
    workbook = tmp_path / 'source.xlsx'; workbook.write_bytes(b'Offline fixture, not a workbook')
    source = scope.reference(workbook)
    records = {}
    for i, module in enumerate(('lease', 'programme', 'operating', 'holding', 'contingent'), 1):
        sn = 'Cash Flow' if module == 'operating' else module.title()
        record = {'passed': True, 'checked_cells': 1, 'workbook': source,
            'cell_checks': [{'address': sn + '!C3', 'passed': True}]}
        records[module] = dump(tmp_path / (module + '.json'), record)
    manifest = dump(tmp_path / 'source_manifest.json', {
        'status': 'independently_verified_composed_financial_seed', 'derived_workbook_sha256': source['sha256']})
    extra = {name: dump(tmp_path / (name + '.json'), {}) for name in
             ('provided_context_audit', 'public_scenarios', 'financial_audit_summary', 'stability')}
    verification = {'workbook': source, 'component_audits': records, 'stability': extra['stability']}
    attempt = {'stage': 'build', 'status': 'verified', 'verification': verification, 'source_manifest': manifest}
    batch = {'status': 'independently_verified_composed_financial_seed_batch', 'mode': 'build',
        'recipe_unchanged': True, 'attempts': [attempt]}
    batch_ref = dump(tmp_path / 'batch.json', batch)
    proof = {'workbook': source, 'source_manifest': manifest, **extra,
        'independent_financial_audits': {key: {**ref, 'checked_cells': 1} for key, ref in records.items()},
        'original_build_verification_sha256': hashlib.sha256(json.dumps(verification, sort_keys=True).encode()).hexdigest()}
    finance = {'financial_seed_verified': True, 'audited_source_binding': proof, 'source_batch_manifest': batch_ref,
        'full_original_private_evidence': {'retained': True}}
    plan = {'mask_ranges': [{'sheet': 'Lease', 'range': 'C3'}]}
    return SimpleNamespace(source=workbook, finance=finance, plan=plan, batch=batch, proof=proof)


def test_original_five_audits_cover_every_target(audit_fixture):
    f = audit_fixture
    result = adapter.audit_target_coverage(f.source, f.plan, f.finance)
    assert result['target_count'] == 1 and result['all_targets_independently_audited'] is True
    assert result['cell_proofs'] == [{'sheet': 'Lease', 'cell': 'C3', 'module': 'lease', 'cell_check_index': 0}]
    assert result['quality_or_difficulty_certified'] is False and result['model_calls'] == result['LO_calls'] == 0


def test_uncovered_target_rejected(audit_fixture):
    f = audit_fixture; f.plan['mask_ranges'][0]['range'] = 'C4'
    with pytest.raises(ValueError, match='without an original independent cell audit'):
        adapter.audit_target_coverage(f.source, f.plan, f.finance)


def test_audit_tamper_rejected_even_when_pass_count_stays_same(audit_fixture):
    f = audit_fixture
    record = f.proof['independent_financial_audits']['lease']; path = Path(record['path'])
    value = json.loads(path.read_text()); value['cell_checks'][0]['address'] = 'Lease!C4'
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match='bytes or SHA changed'):
        adapter.audit_target_coverage(f.source, f.plan, f.finance)


def test_rehashed_replacement_audit_rejected_against_original_attempt(audit_fixture):
    f = audit_fixture
    old = f.proof['independent_financial_audits']['lease']
    old['sha256'] = '0' * 64
    with pytest.raises(ValueError, match='original build receipt'):
        adapter.audit_target_coverage(f.source, f.plan, f.finance)


def test_node_retains_complete_source_assessment_and_no_llm(audit_fixture, monkeypatch, tmp_path):
    f = audit_fixture; saved = {}
    policy = scope.reference(ROOT / 'config/task_adapters/composite_full_state_fm_v1.json')
    ctx = SimpleNamespace(source=f.source, mode='financial_modeling', config={adapter.POLICY: {'version': 1, 'policy': policy},
        'construction': {'authoring_backend': 'composite_template', 'planning_scope': 'per_mode'}},
        data={'baseline': f.source, 'source_id': scope.reference(f.source)['sha256'], 'finance_evidence': f.finance},
        save=lambda name, value: saved.setdefault(name, value))
    monkeypatch.setattr(adapter, 'propose_task', lambda *a: deepcopy(f.plan))
    result = adapter.FullStateFMPlanNode().execute(ctx)
    assert result['source_assessment']['financial_evidence'] == f.finance
    assert result['source_assessment']['financial_evidence'] is not f.finance
    assert saved['composite_full_state_fm_application.json']['target_count'] == 1
    assert result['source_assessment']['quality_or_difficulty_certified'] is False
    ctx.config[adapter.POLICY]['version'] = True
    with pytest.raises(ValueError, match='opt-in'):
        adapter.FullStateFMPlanNode().execute(ctx)


def test_no_optin_uses_unchanged_scope_provider(monkeypatch):
    monkeypatch.setattr(adapter.ScopePlanNode, 'execute', lambda self, ctx: {'legacy': True})
    assert adapter.FullStateFMPlanNode().execute(SimpleNamespace(config={})) == {'legacy': True}

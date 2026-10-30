"""Offline binding/routing fixtures; these tests do not certify financial truth."""
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest
import yaml

from sheets_factory.core.audit import AuditStore
from sheets_factory.nodes.construction import NormalizeNode, PlanNode
from sheets_factory.pipelines import adapted_factory as adapter

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('adapted_quality_entry', ROOT / 'scripts/run_adapted_debug_quality.py')
entrypoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(entrypoint)


def dump(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return adapter.reference(path)


def make_source(folder, index=0):
    folder.mkdir(parents=True)
    old = folder / 'original.xlsx'
    new = folder / 'presentation.xlsx'
    workbook = openpyxl.Workbook()
    workbook.active.title = 'Schedule'
    workbook.active['A1'] = '=0'
    workbook.active['A2'] = index
    workbook.save(old)
    workbook.active['A1'] = 0
    workbook.save(new)
    workbook.close()
    old_ref, new_ref = adapter.reference(old), adapter.reference(new)
    old_audits = {}
    for name in adapter.MODULES:
        old_audits[name] = dump(folder / ('old_' + name + '.json'), {
            'passed': True, 'checked_cells': 3, 'workbook': old_ref, 'mismatches': []})
    provided = dump(folder / 'provided.json', {'passed': True, 'completed': old_ref, 'mismatches': [], 'missing_sheets': []})
    original_manifest = dump(folder / 'original_manifest.json', {'financial_audit_passed': True,
        'local_path': str(old), 'source_ancestors': [old_ref, provided],
        'derived_workbook_sha256': old_ref['sha256'], 'provided_context_audit': provided})
    public_note = {'sheet': 'Schedule', 'cell': 'B1', 'value': 'Offline contract fixture'}
    presentation = dump(folder / 'presentation.json', {'source': old_ref,
        'conversions': [{'sheet': 'Schedule', 'cell': 'A1', 'original_cached_value': 0, 'provided_value': 0, 'original_formula': '=0'}],
        'converted_formula_count': 1, 'public_note': public_note})
    equivalence = dump(folder / 'equivalence.json', {'passed': True, 'sheet_names_equal': True,
        'checked_existing_value_cells': 10, 'mismatches': [], 'public_note_only_metadata_exception': public_note,
        'comparison': 'Exact typed numeric Decimal(str(cache)) values; no grading/cent normalization.'})
    allowlist = dump(folder / 'allowlist.json', {'passed': True, 'all_remaining_formula_definitions_unchanged': True,
        'unexpected_formula_changes': [], 'removed_zero_formula_count': 1, 'actual_formula_definition_changes': 1})
    zeros = dump(folder / 'zeros.json', {'all_zero_bindings_independently_recomputed': True, 'zero_count': 1})
    audits, summary = {}, {}
    for name in adapter.MODULES:
        audit = {'passed': True, 'checked_cells': 3, 'workbook': new_ref, 'mismatches': []}
        if name == 'lease':
            audit.update(method='independent_decimal_future_cashflows_vs_actual_excel_caches',
                         fresh_independent_journal_execution=True, provided_zero_projection=zeros, provided_zero_count=1)
        else:
            audit.update(method=adapter.TRANSITIVE, new_independent_journal_execution_claimed=False,
                financial_policies_and_primitives_unchanged=True, original_source=old_ref,
                original_independent_audit=old_audits[name], exact_value_equivalence=equivalence, formula_allowlist=allowlist)
        audits[name] = dump(folder / (name + '.json'), audit)
        summary[name] = {'passed': True, 'checked_cells': 3}
    summary_ref = dump(folder / 'summary.json', summary)
    stability = dump(folder / 'stability.json', {'stable': True, 'actual_recalculations': 2, 'goal': new_ref,
        'checks': {name: {'passed': True, 'mismatches': []} for name in ('goal_to_first', 'first_to_second')}})
    scenarios = dump(folder / 'scenarios.json', {'fixture': 'not actual source certification'})
    lineage = dump(folder / 'lineage.json', {'method': 'exact_value_preserving_active_schedule_presentation',
        'old_audits_relabelled_as_new_source': False, 'original_manifest': original_manifest,
        'original_source': old_ref, 'new_source': new_ref, 'presentation': presentation,
        'full_exact_equivalence': equivalence, 'transitive_component_audits': audits,
        'original_evidence_sha256': {r['path']: r['sha256'] for r in old_audits.values()}})
    policy = {'adapter': adapter.ADAPTER, 'version': 1, 'families': ['interest'],
              'max_roots': 100000, 'root_impact_validation': 'shadow_roots', 'difficulty_measured': False,
              'source_presentation': 'exact_source_audited_numeric_zero_formulas_only'}
    evidence = {'financial_seed_verified': True, 'financial_modeling_eligible': True,
        'validation_method': adapter.VALIDATION, 'transitive_coverage': lineage, 'independent_financial_audits': audits}
    seed = {'sha256': new_ref['sha256'], 'source_sha256': new_ref['sha256'], 'local_path': str(new),
        'source_kind': adapter.SOURCE_KIND, 'modes': ['debugging'], 'finance_evidence': deepcopy(evidence)}
    from sheets_factory.task_adapters import lease_family
    implementation = adapter.reference(lease_family.__file__)
    presentation_implementation = adapter.reference(Path(lease_family.__file__).with_name('presentation_source.py'))
    manifest_path = folder / 'seed_manifest.json'
    manifest = {'status': 'actually_verified_active_schedule_source', 'financial_audit_passed': True,
        'financial_validation_method': adapter.VALIDATION, 'local_path': str(new),
        'source_ancestors': [old_ref, provided], 'source_original_ancestors': 2,
        'derived_workbook_sha256': new_ref['sha256'], 'selected': [deepcopy(seed)],
        'runtime': {'image': adapter.IMAGE, 'image_id': adapter.IMAGE_ID}, 'lineage': lineage,
        'financial_audits': summary, 'financial_audit': summary_ref, 'stability': stability,
        'public_scenarios': scenarios, 'presentation_policy': policy,
        'recipe': {implementation['path']: implementation['sha256'],
                   presentation_implementation['path']: presentation_implementation['sha256']}}
    dump(manifest_path, manifest)
    seed['source_manifest'] = adapter.reference(manifest_path)
    seed['task_adapter'] = {'id': adapter.ADAPTER, 'policy': policy, 'policy_sha256': adapter.canonical(policy),
                            'implementation': implementation, 'source_manifest': deepcopy(seed['source_manifest'])}
    return {'folder': folder, 'entry': seed, 'manifest': manifest_path}


def modify(source, name, fn):
    path = source['folder'] / name
    data = json.loads(path.read_text())
    fn(data)
    dump(path, data)


def refresh(source):
    """Rebind fixtures after semantic changes, so rejection is not just stale SHA."""
    def walk(value):
        if isinstance(value, dict):
            if 'path' in value and 'sha256' in value and Path(value['path']).is_file():
                value['sha256'] = adapter.sha(value['path'])
            for key, child in value.items():
                if key == 'original_evidence_sha256':
                    for path in child:
                        child[path] = adapter.sha(path)
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for _ in range(12):
        for path in source['folder'].glob('*.json'):
            data = json.loads(path.read_text())
            walk(data)
            dump(path, data)
    seed = source['entry']
    seed['source_manifest'] = adapter.reference(source['manifest'])
    seed['task_adapter']['source_manifest'] = deepcopy(seed['source_manifest'])
    seed['finance_evidence'] = deepcopy(json.loads(source['manifest'].read_text())['selected'][0]['finance_evidence'])


@pytest.fixture
def source(tmp_path):
    return make_source(tmp_path / 'source')


def test_complete_new_source_is_distinct_and_all_transitive_evidence_is_bound(source):
    bindings = {}
    proof = adapter.validate_presentation_seed(source['entry'], bindings)
    assert proof['validation_method'] == adapter.VALIDATION
    assert proof['workbook']['sha256'] == source['entry']['sha256']
    assert len(proof['independent_financial_audits']) == 4
    assert str(source['folder'] / 'original.xlsx') in bindings
    assert all(str(source['folder'] / ('old_' + name + '.json')) in bindings for name in adapter.MODULES)


def test_nested_adapter_cannot_disagree_with_hash_bound_explicit_adapter(source):
    source['entry']['finance_evidence']['task_adapter'] = {**source['entry']['task_adapter'], 'id': 'different'}
    with pytest.raises(ValueError, match='Nested and explicit'):
        adapter.validate_presentation_seed(source['entry'])


@pytest.mark.parametrize('defect', ['lease_fresh', 'audit_failed', 'audit_coverage', 'original_failed',
    'old_relabelled', 'equivalence', 'equivalence_partial', 'allowlist', 'one_stable', 'stable_failed',
    'zero_proof', 'wrong_book', 'runtime', 'missing_coverage'])
def test_invalid_source_semantics_reject_even_with_rebound_hashes(source, defect):
    if defect == 'lease_fresh': modify(source, 'lease.json', lambda d: d.update(fresh_independent_journal_execution=False))
    elif defect == 'audit_failed': modify(source, 'programme.json', lambda d: d.update(passed=False))
    elif defect == 'audit_coverage': modify(source, 'programme.json', lambda d: d.update(checked_cells=1))
    elif defect == 'original_failed': modify(source, 'old_programme.json', lambda d: d.update(passed=False))
    elif defect == 'old_relabelled': modify(source, 'lineage.json', lambda d: d.update(old_audits_relabelled_as_new_source=True))
    elif defect == 'equivalence': modify(source, 'equivalence.json', lambda d: d.update(mismatches=[{'cell': 'A1'}]))
    elif defect == 'equivalence_partial': modify(source, 'equivalence.json', lambda d: d.update(checked_existing_value_cells=0))
    elif defect == 'allowlist': modify(source, 'allowlist.json', lambda d: d.update(all_remaining_formula_definitions_unchanged=False))
    elif defect == 'one_stable': modify(source, 'stability.json', lambda d: d.update(actual_recalculations=1))
    elif defect == 'stable_failed': modify(source, 'stability.json', lambda d: d['checks']['goal_to_first'].update(passed=False))
    elif defect == 'zero_proof': modify(source, 'zeros.json', lambda d: d.update(zero_count=0))
    elif defect == 'wrong_book': modify(source, 'programme.json', lambda d: d.update(workbook=adapter.reference(source['folder'] / 'original.xlsx')))
    elif defect == 'runtime': modify(source, 'seed_manifest.json', lambda d: d['runtime'].update(image_id='different'))
    elif defect == 'missing_coverage': modify(source, 'seed_manifest.json', lambda d: d['selected'][0]['finance_evidence']['independent_financial_audits'].pop('holding'))
    refresh(source)
    with pytest.raises(ValueError):
        adapter.validate_presentation_seed(source['entry'])


@pytest.mark.parametrize('replacement', [False, datetime(2026, 1, 1), '=0', '0'])
def test_presented_zero_cannot_be_boolean_date_formula_or_text(source, replacement):
    path = source['folder'] / 'presentation.xlsx'
    book = openpyxl.load_workbook(path)
    book.active['A1'] = replacement
    book.save(path)
    book.close()
    identity = adapter.sha(path)
    modify(source, 'seed_manifest.json', lambda d: d.update(derived_workbook_sha256=identity))
    modify(source, 'seed_manifest.json', lambda d: d['selected'][0].update(sha256=identity, source_sha256=identity))
    source['entry'].update(sha256=identity, source_sha256=identity)
    refresh(source)
    with pytest.raises(ValueError, match='literal numeric zeros'):
        adapter.validate_presentation_seed(source['entry'])


def test_historical_source_recipe_requires_exact_snapshot_after_code_changes(source):
    fake_code = source['folder'] / 'historical.py'
    fake_code.write_text('historical source build\n')
    digest = adapter.sha(fake_code)
    modify(source, 'seed_manifest.json', lambda d: d['recipe'].update({str(fake_code): digest}))
    snapshot = source['folder'] / 'frozen.py'
    snapshot.write_bytes(fake_code.read_bytes())
    fake_code.write_text('new implementation\n')
    refresh(source)
    with pytest.raises(ValueError, match='snapshot'):
        adapter.validate_presentation_seed(source['entry'])
    source['entry']['finance_evidence']['source_recipe_snapshots'] = {str(fake_code): adapter.reference(snapshot)}
    proof = adapter.validate_presentation_seed(source['entry'])
    assert proof['historical_source_recipe'][str(fake_code)] == digest


@pytest.mark.parametrize('partial', [False, True])
def test_source_recipe_requires_both_named_builder_modules(source, partial):
    def remove_recipe(data):
        data['recipe'] = ({p: h for p, h in data['recipe'].items() if Path(p).name == 'lease_family.py'} if partial else {})
    modify(source, 'seed_manifest.json', remove_recipe)
    refresh(source)
    with pytest.raises(ValueError, match='recipe coverage'):
        adapter.validate_presentation_seed(source['entry'])


@pytest.mark.parametrize('mode,explicit', [('financial_modeling', True), ('financial_modeling', False), ('debugging', False)])
def test_dispatch_preserves_original_planner_for_fm_and_legacy(monkeypatch, mode, explicit):
    marker = {'plan': {'original': True}}
    context = SimpleNamespace(mode=mode, data={'finance_evidence': {'task_adapter': {'id': adapter.ADAPTER}} if explicit else {}})
    monkeypatch.setattr(PlanNode, 'execute', lambda self, ctx: marker if ctx is context else pytest.fail('Different context'))
    assert adapter.DispatchPlanNode().execute(context) is marker


def test_explicit_debug_dispatch_binds_source_policy_code_and_keeps_complete_plan(source, tmp_path, monkeypatch):
    seed = source['entry']
    plan = {'edits': [{'sheet': 'Schedule', 'cell': 'A2', 'before': '=1', 'after': '=2'}],
            'family_adapter': {'id': adapter.ADAPTER}}
    from sheets_factory.task_adapters import lease_family
    calls = []
    monkeypatch.setattr(lease_family, 'propose_debugging_task', lambda p, policy: calls.append((p, policy)) or deepcopy(plan))
    cache = tmp_path / 'cache'; cache.mkdir()
    events = []
    context = SimpleNamespace(mode='debugging', task_id='offline', audit=SimpleNamespace(emit=lambda *a, **k: events.append((a, k))),
        data={'finance_evidence': {'task_adapter': deepcopy(seed['task_adapter'])}, 'variant': 0,
              'baseline': Path(seed['local_path']), 'source_cache': cache})
    result = adapter.DispatchPlanNode().execute(context)
    assert result['plan']['edits'] == plan['edits'] and len(calls) == 1
    assert events[-1][1]['activity_certified'] is False
    assert adapter.DispatchPlanNode().execute(context)['plan'] == result['plan']
    assert len(calls) == 1
    context.data['finance_evidence']['task_adapter']['policy']['max_roots'] = 12
    with pytest.raises(ValueError, match='policy'):
        adapter.DispatchPlanNode().execute(context)


@pytest.mark.parametrize('count', [1, 10])
def test_prepare_freezes_entire_order_with_full_normal_quota_and_no_models(tmp_path, monkeypatch, count):
    sources = [make_source(tmp_path / ('source' + str(i)), i) for i in range(count)]
    manifest = sources[0]['manifest']
    if count == 10:
        manifest = tmp_path / 'batch.json'
        dump(manifest, {'selected': [s['entry'] for s in sources], 'model_scores_consulted': False})
    monkeypatch.setattr(entrypoint.cohort.CohortCodex, '__init__', lambda *a, **k: pytest.fail('No model initialization'))
    output = tmp_path / 'prepared'
    frozen = entrypoint.prepare_adapted(manifest, output, count=count)
    assert frozen['actual_model_calls'] == 0 and frozen['qualified'] is False
    config = yaml.safe_load((output / 'resolved_config.yaml').read_text())
    assert config['run']['targets'] == {'financial_modeling': 10, 'debugging': 10}
    assert config['diagnosis']['selection'] == {'include': 'all', 'exclude': []}
    assert config['diagnosis']['execution']['reference_evidence_transport'] == 'audited_summary'
    assert config['recovery']['compiler_backend'] == 'composite_journal'
    assert config['harbor']['execute_controls'] is True
    assert len(frozen['selected_source_sha256']) == count
    assert config['host_runtime']['temporary_directory'] == str(output / 'temporary')
    assert entrypoint.validate_prepared(output, require_activity=False) == frozen
    with pytest.raises(ValueError, match='probe'):
        entrypoint.validate_prepared(output)
    with pytest.raises(ValueError, match='fresh output'):
        entrypoint.prepare_adapted(manifest, output, count=count)


def test_factory_restores_validated_path_and_changes_only_plan_node(source, tmp_path):
    output = tmp_path / 'prepared'
    entrypoint.prepare_adapted(source['manifest'], output)
    config = yaml.safe_load((output / 'resolved_config.yaml').read_text())
    audit = AuditStore(output, {'id': 'offline', 'status': 'preflight'})
    class Engine:
        def normalize(self, *args): pytest.fail('Audited bytes must be copied exactly')
        def check_stable(self, *args): return {'stable': True}
        def metadata(self): return {'image_id': adapter.IMAGE_ID}
    pipeline = adapter.AdaptedSourceFactory(config, audit, None, Engine())
    seeds = pipeline.load_seeds()
    context = pipeline._context(seeds[0], 'debugging')
    NormalizeNode().run(context)
    assert adapter.sha(context.data['baseline']) == seeds[0]['sha256']
    assert seeds[0]['survey']['normalized_path'] == seeds[0]['local_path']
    assert isinstance(pipeline.load_node('plan'), adapter.DispatchPlanNode)
    assert type(pipeline.load_node('construct')).__name__ == 'ConstructNode'
    assert type(pipeline.load_node('independent_recovery')).__name__ == 'RecoveryNode'
    assert pipeline.templates['debugging']['phases']['revision'] == [
        'construct', 'instruction', 'precheck', 'independent_recovery', 'trajectory', 'diagnose']


def test_execution_checks_probe_inside_data_temp_scope_and_starts_nothing(source, tmp_path, monkeypatch):
    output = tmp_path / 'prepared'
    entrypoint.prepare_adapted(source['manifest'], output)
    previous = os.environ.get('TMPDIR')
    real_validate = entrypoint.validate_prepared
    def validate(*args, **kwargs):
        assert os.environ['TMPDIR'] == str(output / 'temporary')
        return real_validate(*args, **kwargs)
    monkeypatch.setattr(entrypoint, 'validate_prepared', validate)
    monkeypatch.setattr(entrypoint, '_execute_prepared', lambda *a, **k: pytest.fail('No admitted probe'))
    with pytest.raises(ValueError, match='probe'):
        entrypoint.execute_prepared(output)
    assert os.environ.get('TMPDIR') == previous
    assert not (output / 'run.sqlite').exists()


def test_legacy_sources_still_use_original_validation_and_fm_planner(tmp_path, monkeypatch):
    # Exercise routing directly without fabricating an actual finance proof.
    original = {'sha256': 'a' * 64, 'local_path': '/offline/source.xlsx', 'finance_evidence': {}}
    proof = {'workbook': {'path': original['local_path'], 'sha256': original['sha256']}}
    original['finance_evidence']['audited_source_binding'] = deepcopy(proof)
    seen = []
    pipeline = object.__new__(adapter.AdaptedSourceFactory)
    pipeline.legacy_validator = lambda seed: seen.append(seed) or proof
    monkeypatch.setattr(adapter.FactoryPipeline, 'load_seeds', lambda self: [original])
    assert pipeline.load_seeds()[0]['survey']['normalized_path'] == original['local_path']
    assert seen == [original]
    original['task_adapter'] = {'id': adapter.ADAPTER}
    with pytest.raises(ValueError, match='source kind'):
        pipeline.load_seeds()
    original.pop('task_adapter')
    original['finance_evidence']['task_adapter'] = {'id': adapter.ADAPTER}
    with pytest.raises(ValueError, match='source kind'):
        pipeline.load_seeds()


@pytest.mark.parametrize('defect', ['missing_snapshot', 'wrong_snapshot', 'wrong_reference', 'outside_recipe', 'workbook'])
def test_ancestor_resolver_is_limited_to_exact_historical_python_recipe_leaves(tmp_path, monkeypatch, defect):
    approved = tmp_path / 'approved';approved.mkdir()
    monkeypatch.setattr(adapter, 'HISTORICAL_CODE_ROOT', approved)
    original = approved / ('source.xlsx' if defect == 'workbook' else 'source.py')
    original.write_text('historical content\n')
    old = adapter.reference(original)
    snapshot = tmp_path / 'exact.py';snapshot.write_bytes(original.read_bytes())
    snapshots = {str(original): adapter.reference(snapshot)}
    original.write_text('current content\n')
    if defect == 'missing_snapshot': snapshots = {}
    elif defect == 'wrong_snapshot': snapshot.write_text('different content\n')
    elif defect == 'wrong_reference': old['sha256'] = '0' * 64
    data = {'evidence' if defect == 'outside_recipe' else 'recipe_proofs': {'declared': old}}
    with pytest.raises(ValueError):
        adapter.collect_references(data, {}, historical_recipe_snapshots=snapshots)


def test_exact_ancestor_source_snapshot_does_not_require_current_code_to_equal_old_code(tmp_path, monkeypatch):
    approved = tmp_path / 'approved';approved.mkdir()
    monkeypatch.setattr(adapter, 'HISTORICAL_CODE_ROOT', approved)
    original = approved / 'source.py';original.write_text('historical content\n')
    old = adapter.reference(original)
    snapshot = tmp_path / 'exact.py';snapshot.write_bytes(original.read_bytes())
    original.write_text('current content\n')
    bindings = {}
    adapter.collect_references({'recipe': {'code': old}}, bindings,
                               historical_recipe_snapshots={str(original): adapter.reference(snapshot)})
    assert str(original) not in bindings and bindings[str(snapshot)] == old['sha256']


@pytest.mark.parametrize('failure', ['update_run', 'export', 'server', 'session', 'lease'])
def test_cleanup_always_releases_lease_when_persistence_or_shutdown_fails(tmp_path, failure):
    calls = []
    def action(name):
        calls.append(name)
        if name == failure:
            raise OSError('Synthetic persistence/shutdown failure')
    class Lease:
        def __init__(self): self.stream = (tmp_path / 'lock').open('a+')
        def release(self): action('lease')
    lease = Lease()
    audit = SimpleNamespace(update_run=lambda **k: action('update_run'), export=lambda: action('export'))
    server = SimpleNamespace(stop=lambda: action('server'))
    session = SimpleNamespace(close=lambda: action('session'))
    with pytest.raises(OSError):
        entrypoint.finalize_execution(audit, server, session, lease, phase_wall=1, previous_wall=2, status=1)
    assert 'server' in calls and 'session' in calls and 'lease' in calls
    assert lease.stream is None


def make_probe(source, monkeypatch):
    from sheets_factory.task_adapters import lease_family
    from sheets_factory.nodes import construction
    plan = {'edits': [{'sheet': 'Schedule', 'cell': 'A2', 'before': '=1', 'after': '=2'}]}
    monkeypatch.setattr(lease_family, 'propose_debugging_task', lambda *a: deepcopy(plan))
    called = []
    monkeypatch.setattr(construction, 'validate_shadow_root_certificate', lambda *a: called.append(a) or ['proven fixture'])
    folder, seed = source['folder'], source['entry']
    policy = seed['task_adapter']['policy']
    source_recipe = json.loads(source['manifest'].read_text())['recipe']
    snapshot = dump(folder / 'recipe_snapshot.json', {p: {'path': p, 'sha256': h} for p, h in source_recipe.items()})
    controls = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
    instruction = folder / 'instruction.md'
    instruction.write_text('Offline public instruction\n')
    probe = {'passed': True, 'qualified': False, 'shadow_passed': True, 'actual_shadow_LO_executions': 2,
        'source_manifest': deepcopy(seed['source_manifest']), 'baseline': adapter.reference(seed['local_path']),
        'policy': policy, 'policy_canonical_sha256': adapter.canonical(policy),
        'adapter_implementation': seed['task_adapter']['implementation'], 'root_count': 1,
        'actual_plan': dump(folder / 'actual_plan.json', plan), 'shadow_certificate': dump(folder / 'shadow.json', {'fixture': True}),
        'goal': adapter.reference(seed['local_path']), 'public_input': adapter.reference(seed['local_path']),
        'local_controls': controls,
        'local_control_receipt': dump(folder / 'local_controls.json', {k: {'reward': v} for k, v in controls.items()}),
        'public_instruction': adapter.reference(instruction),
        'revision_hash': hashlib.sha256(Path(seed['local_path']).read_bytes() + instruction.read_bytes()).hexdigest(),
        'expected_delta': dump(folder / 'delta.json', {'expected_change_count': 2}), 'expected_change_count': 2,
        'source_build_recipe_snapshot': snapshot}
    return probe, called


def test_probe_gate_calls_original_shadow_validator_and_does_not_claim_quality(source, monkeypatch):
    probe, called = make_probe(source, monkeypatch)
    record = dump(source['folder'] / 'probe.json', probe)
    receipt = adapter.validate_activity_probe(source['entry'], record)
    assert len(called) == 1 and receipt['quality_recovery_difficulty_certified'] is False
    assert receipt['edits_sha256'] == adapter.canonical(json.loads(Path(probe['actual_plan']['path']).read_text())['edits'])


@pytest.mark.parametrize('defect', ['not_passed', 'shadow', 'calls', 'source', 'goal', 'policy', 'implementation', 'edits', 'controls', 'control_receipt', 'revision'])
def test_probe_gate_rejects_unpassed_or_changed_binding(source, monkeypatch, defect):
    probe, called = make_probe(source, monkeypatch)
    if defect == 'not_passed': probe['passed'] = False
    elif defect == 'shadow': probe['shadow_passed'] = False
    elif defect == 'calls': probe['actual_shadow_LO_executions'] = 0
    elif defect == 'source': probe['baseline']['sha256'] = '0' * 64
    elif defect == 'goal': probe['goal'] = adapter.reference(source['folder'] / 'original.xlsx')
    elif defect == 'policy': probe['policy_canonical_sha256'] = '0' * 64
    elif defect == 'implementation': probe['adapter_implementation'] = adapter.reference(source['manifest'])
    elif defect == 'edits': probe['actual_plan'] = dump(source['folder'] / 'changed_plan.json', {'edits': []})
    elif defect == 'controls': probe['local_controls']['nop'] = 1
    elif defect == 'control_receipt': probe['local_control_receipt'] = dump(source['folder'] / 'bad_controls.json', {'nop': {'reward': 1}})
    elif defect == 'revision': probe['revision_hash'] = '0' * 64
    record = dump(source['folder'] / 'probe.json', probe)
    with pytest.raises(ValueError):
        adapter.validate_activity_probe(source['entry'], record)


def test_existing_main_recipe_is_checked_before_terminal_continuation(tmp_path, monkeypatch):
    run = tmp_path / 'main';run.mkdir()
    code = tmp_path / 'original.py';code.write_text('frozen\n')
    dump(run / 'preflight_manifest.json', {'recipe_sha256': {str(code): adapter.sha(code)}})
    config = {'run': {'targets': {'financial_modeling': 10, 'debugging': 10}}}
    (run / 'resolved_config.yaml').write_text(yaml.safe_dump(config))
    monkeypatch.setattr(entrypoint, 'read_run', lambda p: {'run': {'status': 'constructing'}})
    seen = []
    def assert_terminal(run, snapshot):
        seen.append(snapshot)
        raise ValueError('Original producer is active')
    monkeypatch.setattr(entrypoint, 'assert_resume_allowed', assert_terminal)
    before = (run / 'resolved_config.yaml').read_bytes()
    with pytest.raises(ValueError, match='active'):
        entrypoint.validate_continuation(run)
    assert (run / 'resolved_config.yaml').read_bytes() == before
    code.write_text('changed\n')
    with pytest.raises(ValueError, match='main recipe'):
        entrypoint.validate_continuation(run)
    assert len(seen) == 1


def test_cli_prepare_never_executes_without_explicit_run(source, tmp_path, monkeypatch):
    monkeypatch.setattr(entrypoint, 'execute_prepared', lambda *a, **k: pytest.fail('Explicit --run is required'))
    output = tmp_path / 'prepared'
    assert entrypoint.main(['--source-manifest', str(source['manifest']), '--output', str(output)]) == 0
    assert not (output / 'run.sqlite').exists()

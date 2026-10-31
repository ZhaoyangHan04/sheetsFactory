"""Admission boundaries using explicitly mocked tiny evidence, never real LO."""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from openpyxl import Workbook
import pytest

from sheets_factory.pipelines import scaled_capital_admission as admission
from sheets_factory.workbook.capital_allocation_scaled import catalog, ledger
from sheets_factory.workbook import resource_engine


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
    return admission.reference(path)


def book(path, value):
    wb = Workbook(); wb.active.title = 'Fixture'; wb.active['B2'] = value
    wb.save(path); wb.close()
    return admission.reference(path)


@pytest.fixture
def tiny_mocked_source(tmp_path, monkeypatch):
    """The financial auditor/builder are mocks; fixture reports are not proofs."""
    root = tmp_path / 'mocked_source'; root.mkdir()
    public = catalog.build_spec('30-D01')
    public_ref = write(root / 'public_spec.json', public)
    contract = catalog.public_contract('30-D01')
    contract_ref = write(root / 'candidate_contract.json', contract)
    markdown = root / 'candidate_contract.md'; markdown.write_text(catalog.contract_markdown(contract))
    artifacts = {'spec': public_ref, 'candidate_contract': contract_ref,
        'candidate_contract_markdown': admission.reference(markdown),
        'public_summary': write(root / 'public_summary.json', catalog.describe_profile('30-D01'))}
    plan = {p['id']: 0 for p in public['projects']}
    forward = ledger.simulate(public, plan)
    forward_ref = write(root / 'independent_ledger.json', forward)
    fake_records = root / 'mock_records.bin'; fake_records.write_bytes(b'fixture-not-an-enumeration')
    fake_records_ref = admission.reference(fake_records)
    dual_ref = write(root / 'mock_dual.json', {'test_fixture': True})
    validated = {'terminal': {'records_equal_complete': True, 'plan_count': 1 << 30},
        'rank': {'best_plan': plan, 'unique_best': True, 'gap_pence': 1,
                 'objective_pence': forward['objective_pence']},
        'best_ledger': forward_ref,
        'verified_artifacts': {fake_records_ref['path']: fake_records_ref}}
    validated_ref = write(root / 'mock_validated_dual.json', validated)
    binding = {'test_fixture': True, 'formula_count': 77513, 'gold_plan_supplied': True,
        'optimisation_performed': False, 'financial_bindings': [{}] * 25511,
        'decision_bindings': [{}] * 30, 'arithmetic_bindings': [{}] * 51972,
        'arithmetic_support_values_are_protected': False,
        'plan_dependent_caches_must_be_cleared_before_task_input': True,
        'task_input_requires_actual_recalculation_and_audit': True,
        'complete_required_D_includes_changed_arithmetic_helpers': True}
    binding_ref = write(root / 'mock_bindings.json', binding)
    profile_path = admission.ROOT / 'config/runtime_profiles/entity_group_large_v2.yaml'
    profile_ref = admission.reference(profile_path)
    profile = resource_engine.load_runtime_profile(profile_path)
    recipe_file = root / 'mock_recipe.py'; recipe_file.write_text('# fixture only\n')
    recipe = {str(recipe_file): admission.reference(recipe_file)['sha256']}
    catalog_ref = write(root / 'mock_catalog_manifest.json', {'test_fixture': True})
    frozen = {'recipe_sha256': recipe, 'validated_dual_proof': validated_ref,
        'dual_search_proof': dual_ref, 'runtime_profile_value': profile,
        'copied_public_contract_artifacts': artifacts, 'catalog_manifest': catalog_ref}
    preparation_ref = write(root / 'preparation.json', frozen)
    calls, resource_refs, audits = [], [], []
    previous = book(root / 'raw.xlsx', 10)
    report = {'test_fixture': True, 'passed': True, 'formula_count': 77513, 'checked_cells': 77513,
        'all_formula_cells_independently_covered': True,
        'all_scenarios_feasible': True, 'all_journals_balance': True,
        'mismatches': [], 'control_mismatches': []}
    for index in range(1, 4):
        output = book(root / f'calculated_pass{index}.xlsx', 20)
        call = {'index': index, 'input': previous, 'destination': output['path'],
            'started_at': '2026-10-30T00:00:00+00:00', 'completed': True,
            'output': output, 'finished_at': '2026-10-30T00:00:03+00:00'}
        write(root / f'LO_pass{index}_started.json', {key: call[key] for key in
            ('index', 'input', 'destination', 'started_at')} | {'completed': False})
        write(root / f'LO_pass{index}_terminal.json', call)
        resource = {'test_fixture': True, 'kind': 'resource_bound_libreoffice_call', 'status': 'completed',
            'role': 'source', 'actual_resources_verified': True, 'source': previous, 'output': output,
            'profile': profile_ref, 'image_id': admission.IMAGE_ID,
            'implementation': admission.reference(resource_engine.__file__),
            'requested_resources': profile['docker_resources']['source'],
            'actual_resources': {'cpus_nanoseconds': 2 * 10**9, 'memory_bytes': 32 * 1024**3, 'pids_limit': 256},
            'workbook_file_timeout_seconds': 600, 'verifier_total_timeout_seconds': 2400,
            'solver_tool_budget': profile['solver_tool_budget'],
            'started_at': '2026-10-30T00:00:01+00:00', 'finished_at': '2026-10-30T00:00:02+00:00'}
        resource_ref = write(root / f'mock_resource_{index}.json', resource)
        call['resource_receipt'] = resource_ref
        calls.append(call); resource_refs.append(resource_ref)
        audits.append(write(root / f'mock_audit_{index}.json', {'workbook': output, **report}))
        previous = output
    runtime = {'image_id': admission.IMAGE_ID, 'backend': 'libreoffice_uno_docker',
        'network': 'none', 'macro_execution': 'never', 'external_updates': 'never', 'role': 'source',
        'runtime_profile': profile, 'runtime_profile_binding': profile_ref,
        'actual_resource_receipts': resource_refs, 'actual_calculation_calls_recorded': 3}
    goal = calls[0]['output']
    stable = {'first_against_goal': admission.compare_exact_typed(goal['path'], calls[1]['output']['path']),
              'second_against_goal': admission.compare_exact_typed(goal['path'], calls[2]['output']['path'])}
    stable['stable'] = True
    source = {'test_fixture': True, 'kind': 'independently_verified_scaled_capital_allocation_source',
        'version': 1, 'status': 'source_verified_not_task_quality_or_difficulty_qualified',
        'profile_id': '30-D01', 'project_count': 30, 'physical_formula_count': 77513,
        'financial_audit_passed': True, 'actual_LO_recalculations': 3, 'model_calls': 0, 'new_enumeration_calls': 0,
        'quality_or_difficulty_certified': False, 'qualified': False, 'task_count': 0,
        'raw_ancestors': dict(admission.spec.RAW_ANCESTORS), 'source_original_ancestors': 2,
        'raw_ancestry_is_provenance_only': True, 'hypothetical_forecasts_and_policy': True,
        'task_input_and_complete_D_not_built': True, 'gold_decisions_and_financials_require_normal_task_masking': True,
        'plan_dependent_helper_caches_require_clearing_and_actual_input_recalculation': True,
        'complete_required_D_must_include_changed_arithmetic_helpers': True,
        'full_public_sidecar_contract_must_be_transferred_to_task': True,
        'five_controls_recovery_all12_quality_Harbor_and_difficulty_pending': True,
        'source_preparation': preparation_ref, 'source_recipe_sha256': recipe,
        'validated_dual_proof': validated_ref, 'dual_search_proof': dual_ref,
        'public_contract_artifacts': artifacts, 'public_specification': public_ref,
        'independent_ledger': forward_ref, 'bindings': binding_ref,
        'engine_calls': calls, 'financial_audits': audits, 'runtime_profile': profile_ref, 'runtime': runtime,
        'agent_and_verifier_resources_actually_verified': False,
        'workbook': goal, 'derived_workbook_sha256': goal['sha256'], 'local_path': goal['path'],
        'stability': write(root / 'stability.json', stable)}
    source_ref = write(root / 'seed_manifest.json', source)
    count = {'builder': 0, 'audits': 0}

    def fake_validate(directory):
        assert directory == root
        count['builder'] += 1
        return deepcopy(frozen)

    def fake_audit(*args):
        count['audits'] += 1
        return deepcopy(report)

    monkeypatch.setattr(admission, '_builder', lambda session: SimpleNamespace(
        validate_prepared=fake_validate, recipes=lambda: deepcopy(recipe)))
    monkeypatch.setattr(admission.validate, 'audit_capital_allocation_workbook', fake_audit)
    return SimpleNamespace(root=root, source=source, source_ref=source_ref, frozen=frozen,
        count=count, forward=forward, write_source=lambda: write(root / 'modified_manifest.json', source))


def test_complete_mocked_admission_recomputes_all_three_audits_and_uses_one_dual_validation(tiny_mocked_source):
    value = tiny_mocked_source; session = admission.ReferenceSession()
    proof = admission.validate_source(value.source_ref, session=session)
    assert value.count == {'builder': 1, 'audits': 3}
    assert proof['kind'] == 'checked_first_scaled_capital_source_admission'
    assert proof['public_candidate_contract'] == value.source['public_contract_artifacts']['candidate_contract']
    assert proof['physical_formula_count'] == 77513 and proof['project_count'] == 30
    assert proof['agent_and_verifier_resources_actually_verified'] is False
    assert proof['artifact_sha256'] == {p: r['sha256'] for p, r in proof['verified_artifacts'].items()}
    assert admission.verify_admitted_proof(proof, session=session) == proof
    assert admission.verify_admitted_proof(proof, session=session) == proof
    assert value.count == {'builder': 1, 'audits': 3}


def test_new_session_never_trusts_persisted_checked_artifact_labels(tiny_mocked_source):
    value = tiny_mocked_source
    proof = admission.validate_source(value.source_ref)
    admission.verify_admitted_proof(proof)
    assert value.count == {'builder': 2, 'audits': 6}


def test_source_proof_is_identical_with_unrelated_prepopulated_caller_cache(tiny_mocked_source):
    value = tiny_mocked_source
    fresh = admission.validate_source(value.source_ref)
    caller = admission.ReferenceSession()
    unrelated = value.root / 'unrelated_quality_entry.py'
    unrelated.write_text('# checked by the quality entry before source admission\n')
    unrelated_ref = caller.ref(unrelated)
    warm = admission.validate_source(value.source_ref, session=caller)
    assert warm == fresh
    assert str(unrelated) not in warm['verified_artifacts']
    assert str(unrelated) not in warm['artifact_sha256']
    assert caller._checked[str(unrelated)][0] == unrelated_ref
    assert set(warm['verified_artifacts']) <= set(caller._checked)
    assert admission.spec.canonical_sha(warm) in caller._proofs
    assert value.count == {'builder': 2, 'audits': 6}
    # The imported proof identity keeps subsequent node guards on their fast
    # path instead of repeating complete source/search validation.
    assert admission.verify_admitted_proof(warm, session=caller) == fresh
    assert admission.verify_admitted_proof(warm, session=caller) == fresh
    assert value.count == {'builder': 2, 'audits': 6}


def test_source_session_merge_rejects_conflicts_without_partial_cache_or_proof_import(tiny_mocked_source):
    value = tiny_mocked_source
    caller = admission.ReferenceSession()
    # Simulate a caller that checked a previous identity at the same path.
    records = value.root / 'mock_records.bin'
    original = records.read_bytes()
    records.write_bytes(b'previous caller record identity')
    old = caller.ref(records)
    records.write_bytes(original)
    unrelated = value.root / 'unrelated.txt'; unrelated.write_text('unrelated')
    caller.ref(unrelated)
    before = deepcopy(caller._checked)
    with pytest.raises(ValueError, match='Conflicting.*merge'):
        admission.validate_source(value.source_ref, session=caller)
    assert caller._checked == before
    assert caller._checked[str(records)][0] == old
    assert caller._proofs == set()
    assert value.count == {'builder': 1, 'audits': 3}


def test_failed_semantic_source_validation_never_pollutes_caller_cache(tiny_mocked_source):
    value = tiny_mocked_source; caller = admission.ReferenceSession()
    unrelated = value.root / 'existing_config.json'; unrelated.write_text('{}\n')
    caller.ref(unrelated); before = deepcopy(caller._checked)
    value.source['financial_audit_passed'] = False
    with pytest.raises(ValueError, match='actual complete'):
        admission.validate_source(value.write_source(), session=caller)
    assert caller._checked == before and caller._proofs == set()
    assert value.count == {'builder': 0, 'audits': 0}


@pytest.mark.parametrize('change', ['old18', 'wrong_profile', 'missing_sidecar_flag', 'unprotected_helper',
                                   'missing_financial_field', 'missing_pass', 'wrong_source_image',
                                   'eight_gib', 'network_public', 'agent_resources_claim', 'not_feasible',
                                   'wrong_objective', 'changed_public_contract', 'wrong_terminal',
                                   'resource_unverified', 'resource_cpu', 'bad_time_order'])
def test_source_rejects_incomplete_financial_resource_and_public_evidence(tiny_mocked_source, change):
    value = tiny_mocked_source; source = value.source
    if change == 'old18': source['project_count'] = 18
    elif change == 'wrong_profile': source['profile_id'] = '30-G01'
    elif change == 'missing_sidecar_flag': source.pop('full_public_sidecar_contract_must_be_transferred_to_task')
    elif change in ('unprotected_helper', 'missing_financial_field'):
        b = json.loads(Path(source['bindings']['path']).read_text())
        if change == 'unprotected_helper': b['arithmetic_support_values_are_protected'] = True
        else: b['financial_bindings'].pop()
        source['bindings'] = write(value.root / 'changed_binding.json', b)
    elif change == 'missing_pass': source['engine_calls'].pop()
    elif change == 'wrong_source_image': source['runtime']['image_id'] = 'sha256:' + '0' * 64
    elif change == 'eight_gib': source['runtime']['runtime_profile']['docker_resources']['source']['memory_bytes'] = 8 * 1024**3
    elif change == 'network_public': source['runtime']['network'] = 'public'
    elif change == 'agent_resources_claim': source['agent_and_verifier_resources_actually_verified'] = True
    elif change in ('not_feasible', 'wrong_objective'):
        result = deepcopy(value.forward)
        if change == 'not_feasible': result['feasible'] = False
        else: result['objective_pence'] += 1
        source['independent_ledger'] = write(value.root / 'changed_ledger.json', result)
    elif change == 'changed_public_contract':
        sidecar = deepcopy(source['public_contract_artifacts'])
        wrong = catalog.public_contract('30-D01'); wrong['candidate_schedule_policy'] = 'Zero unselected candidates.'
        sidecar['candidate_contract'] = write(value.root / 'wrong_contract.json', wrong)
        source['public_contract_artifacts'] = sidecar
    elif change == 'wrong_terminal':
        p = value.root / 'LO_pass1_terminal.json'; item = json.loads(p.read_text()); item['completed'] = False
        p.write_text(json.dumps(item))
    elif change in ('resource_unverified', 'resource_cpu', 'bad_time_order'):
        ref = source['engine_calls'][0]['resource_receipt']; item = json.loads(Path(ref['path']).read_text())
        if change == 'resource_unverified': item['actual_resources_verified'] = False
        elif change == 'resource_cpu': item['actual_resources']['cpus_nanoseconds'] = 10**9
        else: item['finished_at'] = '2026-10-29T23:59:00+00:00'
        changed = write(value.root / 'changed_resource.json', item)
        source['engine_calls'][0]['resource_receipt'] = changed
        source['runtime']['actual_resource_receipts'][0] = changed
    with pytest.raises((ValueError, KeyError)):
        admission.validate_source(value.write_source())


def test_complete_second_audit_is_recomputed_instead_of_trusting_passed(tiny_mocked_source, monkeypatch):
    value = tiny_mocked_source
    original = admission.validate.audit_capital_allocation_workbook

    def wrong_second(*args):
        result = original(*args)
        if value.count['audits'] == 2: result['checked_cells'] -= 1
        return result

    monkeypatch.setattr(admission.validate, 'audit_capital_allocation_workbook', wrong_second)
    with pytest.raises(ValueError, match='77,513'):
        admission.validate_source(value.source_ref)


def test_both_further_typed_stability_comparisons_are_reproduced(tiny_mocked_source):
    value = tiny_mocked_source
    third = Path(value.source['engine_calls'][2]['output']['path'])
    # Preserve its declared reference via a new path and update its call
    # receipts: it is a different valid workbook, not merely a hash failure.
    changed = book(value.root / 'third_changed.xlsx', 21)
    call = value.source['engine_calls'][2]; call['output'] = changed; call['destination'] = changed['path']
    write(value.root / 'LO_pass3_started.json', {k: call[k] for k in ('index', 'input', 'destination', 'started_at')} | {'completed': False})
    write(value.root / 'LO_pass3_terminal.json', {k: v for k, v in call.items() if k != 'resource_receipt'})
    resource = json.loads(Path(call['resource_receipt']['path']).read_text()); resource['output'] = changed
    updated = write(value.root / 'changed_third_resource.json', resource)
    call['resource_receipt'] = updated; value.source['runtime']['actual_resource_receipts'][2] = updated
    r = json.loads(Path(value.source['financial_audits'][2]['path']).read_text()); r['workbook'] = changed
    value.source['financial_audits'][2] = write(value.root / 'changed_third_report.json', r)
    with pytest.raises(ValueError, match='exact typed stable'):
        admission.validate_source(value.write_source())


def test_artifact_cache_streams_once_and_detects_later_mutation(tmp_path, monkeypatch):
    p = tmp_path / 'file.bin'; p.write_bytes(b'a' * 1024)
    record = admission.reference(p); session = admission.ReferenceSession()
    calls = []
    original = admission.reference

    def counted(path):
        calls.append(str(path)); return original(path)

    monkeypatch.setattr(admission, 'reference', counted)
    assert admission.verify_references([record, {'again': record}], session=session) == {str(p): record['sha256']}
    assert len(calls) == 1
    p.write_bytes(b'b' * 1024)
    with pytest.raises(ValueError, match='changed'):
        admission.verify_references(record, session=session)
    assert len(calls) == 2


def test_cached_source_proof_rejects_mutated_manifest_and_never_skips_checks(tiny_mocked_source):
    value = tiny_mocked_source; session = admission.ReferenceSession()
    proof = admission.validate_source(value.source_ref, session=session)
    Path(proof['source_manifest']['path']).write_text('{}\n')
    with pytest.raises(ValueError, match='changed'):
        admission.verify_admitted_proof(proof, session=session)


def test_reference_rejects_bool_bytecount_and_symlink(tmp_path):
    p = tmp_path / 'file'; p.write_text('value')
    bad = admission.reference(p); bad['bytes'] = True
    with pytest.raises(ValueError): admission.verify_references(bad)
    alias = tmp_path / 'alias'; alias.symlink_to(p)
    with pytest.raises(ValueError): admission.reference(alias)


def test_reference_hash_never_materialises_a_binary_with_read_bytes(tmp_path, monkeypatch):
    path = tmp_path / 'record_fixture.bin'; path.write_bytes(b'\x00' * (1024 * 1024))
    monkeypatch.setattr(Path, 'read_bytes', lambda self: pytest.fail('Binary hashing must stream'))
    record = admission.reference(path)
    assert record['bytes'] == 1024 * 1024
    assert admission.verify_references(record) == {str(path): record['sha256']}


def test_factory_loads_exact_source_and_hands_private_session_to_normal_phase(tiny_mocked_source, monkeypatch):
    value = tiny_mocked_source; session = admission.ReferenceSession()
    proof = admission.validate_source(value.source_ref, session=session)
    seed = {'source_kind': admission.SOURCE_KIND, 'modes': ['financial_modeling'], 'variant': 0,
        'local_path': proof['workbook']['path'], 'sha256': proof['workbook']['sha256'],
        'finance_evidence': {'audited_source_binding': proof, 'source_manifest': proof['source_manifest']}}
    monkeypatch.setattr(admission.FactoryPipeline, '__init__', lambda self, *a, **kw: None)
    monkeypatch.setattr(admission.FactoryPipeline, 'load_seeds', lambda self: [deepcopy(seed)])
    monkeypatch.setattr(admission.FactoryPipeline, 'run_phase', lambda self, ctx, phase: {'phase': phase})
    factory = admission.ScaledCapitalFactory(admitted_proof=proof, admission_session=session)
    factory.targets = {'financial_modeling': 1, 'debugging': 0}
    assert factory.load_seeds()[0]['survey']['normalized_path'] == proof['workbook']['path']
    ctx = SimpleNamespace(source=proof['workbook']['path'], data={'baseline': proof['workbook']['path'],
        'source_id': proof['workbook']['sha256']})
    assert factory.run_phase(ctx, 'plan') == {'phase': 'plan'}
    assert ctx.data['_scaled_admission_session'] is session
    assert value.count['builder'] == 1
    factory.targets = {'financial_modeling': 10, 'debugging': 0}
    with pytest.raises(ValueError, match='first-development'):
        factory.load_seeds()

"""Pure receipt protocol regressions; no model, source admission or native service."""
from copy import deepcopy
import json
from pathlib import Path

import jsonschema
import pytest

from sheets_factory.llm import schemas
from sheets_factory.nodes import quality
from sheets_factory.task_adapters import reference_receipt_diagnosis as adapter
from test_reference_evidence_policy import context

ROOT = Path(__file__).resolve().parents[1]
BINDING = {'task_id': 'fixture', 'revision': 0, 'task_revision_hash': 'a' * 64,
    'input_sha256': 'b' * 64, 'instruction_sha256': 'c' * 64, 'goal_sha256': 'd' * 64}


def response(state='clear', receipt=None):
    receipt = receipt if receipt is not None else {'binding': deepcopy(BINDING),
        'business_evidence': ['Declared toy policy: reference sum is 1+1.'],
        'financial_validation_checks': [{'check': 'Toy sum', 'method': 'Independent integer addition',
            'passed': True, 'evidence': ['1 + 1 = 2; declared toy reference is 2.']}]}
    evidence = [quality.REFERENCE_REVIEW_PREFIX + json.dumps(receipt)] if state == 'clear' else []
    return {'assessments': {'Q04': {'check_id': 'Q04', 'state': state,
        'reason': 'Explicit offline protocol fixture only', 'evidence': evidence}},
        'issues': [], 'evidence_requests': []}


@pytest.fixture
def runner():
    result = adapter.ReceiptDiagnosisRunner(ROOT)
    result.resolve = lambda config: {'enabled_check_ids': ['Q04'],
        'disabled_check_ids': [key for key in result.specs if key != 'Q04'],
        'batches': [['Q04']], 'check_plan_hash': 'offline-q04-transport-only',
        'difficulty_deferred': True}
    return result


def bundle():
    return {'task_id': 'fixture', 'revision': 0, 'revision_hash': 'a' * 64,
        'reviewer_context_hash': adapter.PROTOCOL, 'public': {},
        'private': {'reference_review_requirements': {'binding': deepcopy(BINDING)}}}


def test_original_bytecode_globals_and_all_other_schema_branches_unchanged():
    old = adapter.upstream.LinearDiagnoseNode
    new = adapter.ReferenceReceiptDiagnosisNode
    assert new.run is old.run and new.execute is old.execute
    assert new._execute_diagnose.__code__ is old._execute_diagnose.__code__
    assert new._execute_diagnose.__globals__ is not old._execute_diagnose.__globals__
    assert old._execute_diagnose.__globals__['DiagnosisRunner'] is adapter.runner_module.DiagnosisRunner
    assert adapter.PRIVATE_RECEIPT_INSTRUCTIONS not in old._execute_diagnose.__globals__['PRIVATE_DIAGNOSTIC_EVIDENCE_INSTRUCTIONS']
    expected_changes = {'__builtins__', 'DiagnosisRunner', 'PRIVATE_DIAGNOSTIC_EVIDENCE_INSTRUCTIONS'}
    assert {key for key, value in adapter._namespace.items()
        if value is not old._execute_diagnose.__globals__[key]} == expected_changes
    assert adapter.diagnosis_output_schema(['Q01', 'Q02']) == schemas.diagnosis_output_schema(['Q01', 'Q02'])
    before = schemas.diagnosis_output_schema(['Q04'])
    adapter.diagnosis_output_schema(['Q04'])
    assert schemas.diagnosis_output_schema(['Q04']) == before
    adapter.verify_dependencies()


@pytest.mark.parametrize('state', ['unknown', 'not_applicable', 'flagged'])
def test_nonclear_schema_does_not_require_a_passed_receipt(state):
    jsonschema.validate(response(state), adapter.diagnosis_output_schema(['Q04']))


@pytest.mark.parametrize('evidence', [[], ['Business review, without required receipt'],
    ['reference_review_json:{}', 'reference_review_json:{}']])
def test_clear_schema_requires_exactly_one_anchored_receipt(evidence):
    value = response(); value['assessments']['Q04']['evidence'] = evidence
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(value, adapter.diagnosis_output_schema(['Q04']))


@pytest.mark.parametrize('fault', ['missing', 'duplicate', 'bad_json', 'binding',
    'business', 'checks', 'not_passed', 'empty_method'])
def test_invalid_clear_is_protocol_unknown_and_never_cached(runner, fault):
    value = response(); assessment = value['assessments']['Q04']
    receipt = json.loads(assessment['evidence'][0].split(':', 1)[1])
    if fault == 'missing': assessment['evidence'] = ['No receipt']
    elif fault == 'duplicate': assessment['evidence'] *= 2
    elif fault == 'bad_json': assessment['evidence'] = ['reference_review_json:{']
    else:
        if fault == 'binding': receipt['binding']['goal_sha256'] = 'f' * 64
        elif fault == 'business': receipt['business_evidence'] = []
        elif fault == 'checks': receipt['financial_validation_checks'] = []
        elif fault == 'not_passed': receipt['financial_validation_checks'][0]['passed'] = False
        else: receipt['financial_validation_checks'][0]['method'] = ''
        assessment['evidence'] = [quality.REFERENCE_REVIEW_PREFIX + json.dumps(receipt)]
    cache = {}
    report = runner.diagnose(bundle(), [], {}, lambda _: value, batch_cache=cache)
    assert report['assessments']['Q04']['state'] == 'unknown'
    assert report['execution_failures'][0]['error_type'] == 'ValueError'
    assert not cache[adapter.PROTOCOL]['entries'] and not report['releasable']
    assert report['llm_batches'][0]['status'] == 'failed'


def test_legacy_malformed_clear_is_retained_but_explicitly_refused(runner):
    bad = response(); bad['assessments']['Q04']['evidence'] = ['Actual old-style evidence, no prefix']
    cache = {'entries': {'legacy-fingerprint': {'assigned_check_ids': ['Q04'], 'result': bad,
        'diagnostic_run_id': 'original-run'}}, 'unrelated': 'preserve'}
    original = deepcopy(cache); calls = []
    report = runner.diagnose(bundle(), [], {}, lambda payload: calls.append(payload) or response(), batch_cache=cache)
    assert len(calls) == 1 and report['assessments']['Q04']['state'] == 'clear'
    assert cache['entries'] == original['entries'] and cache['unrelated'] == original['unrelated']
    rejected = report['reference_receipt_protocol']['rejected_cached_results']
    assert len(rejected) == 1 and rejected[0]['cache_scope'] == 'legacy'
    assert rejected[0]['fingerprint'] == 'legacy-fingerprint' and len(rejected[0]['result_sha256']) == 64
    assert report['reference_receipt_protocol']['legacy_cache_reused'] is False
    again = runner.diagnose(bundle(), [], {}, lambda _: pytest.fail('Valid new cache should be reused'), batch_cache=cache)
    assert again['llm_batches'][0]['cache_hit'] is True
    assert cache['entries'] == original['entries']


def test_corrupt_new_clear_cache_is_revalidated_before_reuse(runner):
    cache = {}; runner.diagnose(bundle(), [], {}, lambda _: response(), batch_cache=cache)
    entry = next(iter(cache[adapter.PROTOCOL]['entries'].values()))
    entry['result']['assessments']['Q04']['evidence'] = ['Lost receipt']
    calls = []
    report = runner.diagnose(bundle(), [], {}, lambda p: calls.append(p) or response(), batch_cache=cache)
    assert len(calls) == 1 and report['llm_batches'][0]['cache_hit'] is False
    assert report['reference_receipt_protocol']['rejected_cached_results'][0]['cache_scope'] == 'current'


def test_unknown_never_fabricates_receipt_or_cached_clear(runner):
    cache = {}; value = response('unknown')
    report = runner.diagnose(bundle(), [], {}, lambda _: value, batch_cache=cache)
    assert report['assessments']['Q04']['state'] == 'unknown'
    assert report['assessments']['Q04']['evidence'] == []
    assert not cache[adapter.PROTOCOL]['entries'] and not report['execution_failures']


def test_full_original_node_receives_new_private_prompt_schema_and_final_gate(context):
    # Only the existing tiny policy fixture is used; opaque production admission
    # is not minted or bypassed. The original protected execution body is called.
    context.data.update(quality.RecoveryNode().execute(context))
    context.config['diagnosis']['execution'] = {'reference_evidence_transport': 'audited_summary',
        'private_evidence_directory': str(context.revision_dir / 'private/evidence-fixture')}
    original = context.llm.complete; seen = []
    def complete(instruction, **options):
        seen.append((instruction, options['output_schema']))
        result = original(instruction, **options)
        if options['role'] == 'reference_diagnostician':
            for check_id, assessment in result['assessments'].items():
                assessment['check_id'] = check_id
            jsonschema.validate(result, options['output_schema'])
        return result
    context.llm.complete = complete
    report = adapter.ReferenceReceiptDiagnosisNode()._execute_diagnose(context)['diagnosis']
    assert report['reference_review']['passed'] is True and report['releasable'] is True
    assert len(seen) == 2 and adapter.PRIVATE_RECEIPT_INSTRUCTIONS not in seen[0][0]
    assert adapter.PRIVATE_RECEIPT_INSTRUCTIONS in seen[1][0]
    assert 'anyOf' in seen[1][1]['properties']['assessments']['properties']['Q04']
    assert report['reference_receipt_protocol']['id'] == adapter.PROTOCOL
    assert report['mandatory_gates']['reference_review']['passed'] is True


def test_dependency_change_fails_closed(monkeypatch, tmp_path):
    changed = tmp_path / 'changed.py'; changed.write_text('changed')
    monkeypatch.setattr(adapter, 'DEPENDENCIES', {str(changed): '0' * 64})
    with pytest.raises(ValueError, match='dependency changed'):
        adapter.verify_dependencies()

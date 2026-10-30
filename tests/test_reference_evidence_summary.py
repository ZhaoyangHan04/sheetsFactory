"""Complete privileged evidence with bounded transport; no API or workbook engine."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from sheets_factory.checkers import DiagnosisRunner
from sheets_factory.checkers.reference_evidence import reference_review_evidence


CONTROLS={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}


def bundle():
    return {'task_id':'fixture','revision':0,'revision_hash':'frozen',
        'public':{'instruction':'Inspect the provided fixture policy.','input_sha256':'input'},
        'private':{'expected_delta':{'expected_changes':['S!A'+str(i) for i in range(10000)]},
                   'independent_recovery':{'verified':True,'program':'private program\n'*10000}},
        'reviewer_context_hash':'unchanged-public-model-prompt-context',
        'engine_report':{'normalization_ok':True,'recalculation_ok':True,'stable':True},
        'infrastructure_health_report':{'healthy':True,'checks':['fixture']}}


def clear(payload):
    return {'assessments':{key:{'state':'clear','reason':'Offline fixture only',
                'evidence':['Declared fixture evidence']} for key in payload['assigned_check_ids']},
            'issues':[],'evidence_requests':[]}


def test_complete_private_artifact_roundtrip_and_compact_index(tmp_path):
    original=bundle()['private'];index=reference_review_evidence(original,tmp_path)
    artifact=Path(index['full_artifact']['path']);raw=artifact.read_bytes()
    assert json.loads(raw)==original
    assert hashlib.sha256(raw).hexdigest()==index['full_artifact']['sha256']
    assert len(json.dumps(index))<len(raw)//10
    assert index['private_summary']['expected_delta']['expected_changes']['count']==10000
    assert index['private_summary']['independent_recovery']['program']['summary_kind']=='complete_string_in_bound_artifact'
    assert index['summary_is_not_a_quality_verdict'] is True
    assert artifact.stat().st_mode&0o077==0


def test_summary_transport_reuses_exact_previous_public_fingerprint_only(tmp_path):
    runner=DiagnosisRunner();cache={};seen=[]
    def review(payload):
        seen.append(deepcopy(payload));return clear(payload)
    first=runner.diagnose(bundle(),[],CONTROLS,review,{'difficulty_deferred':True},batch_cache=cache)
    config={'difficulty_deferred':True,'execution':{'reference_evidence_transport':'audited_summary',
             'private_evidence_directory':str(tmp_path)}}
    second=runner.diagnose(bundle(),[],CONTROLS,review,config,batch_cache=cache)
    assert second['llm_batches'][0]['cache_hit']
    assert first['llm_batches'][0]['batch_fingerprint']==second['llm_batches'][0]['batch_fingerprint']
    assert first['check_plan_hash']==second['check_plan_hash']
    assert not second['llm_batches'][1]['cache_hit']
    assert [p['visibility'] for p in seen]==['public_only','review','review']
    assert 'private_evidence' not in seen[0] and 'private program' not in json.dumps(seen[0])
    assert 'reference_review_instructions' in seen[-1]
    changed=bundle();changed['private']['expected_delta']['expected_changes'][5000]='changed hidden middle record'
    third=runner.diagnose(changed,[],CONTROLS,review,config,batch_cache=cache)
    assert third['llm_batches'][0]['cache_hit'] and not third['llm_batches'][1]['cache_hit']
    assert len(seen)==4


def test_full_artifact_hash_detects_unlisted_edits_and_does_not_claim_coverage(tmp_path):
    private={'plan':{'edits':[{'sheet':'S','cell':f'A{i}','mechanism':'timing',
              'business_rule':'Fixture rule','event_context':{'month':i}} for i in range(100)]}}
    index=reference_review_evidence(private,tmp_path)
    assert index['mutation_boundaries']['complete_mechanism_counts']=={'timing':100}
    assert index['mutation_boundaries']['examples_are_not_full_root_coverage']
    assert len(index['mutation_boundaries']['boundary_examples'])==2
    altered=deepcopy(private);altered['plan']['edits'][50]['business_rule']='different'
    new=reference_review_evidence(altered,tmp_path)
    assert new['full_artifact']['sha256']!=index['full_artifact']['sha256']


def test_audit_summary_verifies_bytes_and_keeps_corrupt_or_missing_proofs_visible(tmp_path):
    audit=tmp_path/'financial_audit.json'
    audit.write_text(json.dumps({'passed':True,'checked_cells':4,
        'independent_journal_checks':{'cash':True},'cell_checks':[{'cell':str(i)} for i in range(4)],
        'mismatches':[],'native_errors':[]}))
    reference={'path':str(audit),'sha256':hashlib.sha256(audit.read_bytes()).hexdigest(),'checked_cells':4}
    private={'source_assessment':{'financial_evidence':{'independent_financial_audits':{'fixture':reference}}}}
    result=reference_review_evidence(private,tmp_path/'artifacts')
    proof=result['financial_audits'][0]
    assert proof['sha256_verified'] and proof['declared_coverage_and_invariants']['checked_cells']==4
    assert proof['complete_tables']['cell_checks']['count']==4
    audit.write_text('{"passed":false}')
    corrupt=reference_review_evidence(private,tmp_path/'artifacts')['financial_audits'][0]
    assert not corrupt['sha256_verified'] and 'SHA' in corrupt['integrity_problem']
    assert 'declared_coverage_and_invariants' not in corrupt
    audit.unlink()
    missing=reference_review_evidence(private,tmp_path/'artifacts')['financial_audits'][0]
    assert not missing['sha256_verified'] and 'missing' in missing['integrity_problem']

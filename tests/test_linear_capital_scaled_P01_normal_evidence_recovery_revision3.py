"""Synthetic stored evidence only; no original-run certificate or native calls."""
import ast
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT=Path(__file__).resolve().parents[1]


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.fixture
def entry():
    return load('scripts/recover_linear_capital_scaled_P01_normal_evidence_revision3.py','_test_P01_recovery_v3')


@pytest.fixture
def stored(tmp_path,monkeypatch,entry):
    fixtures=load('tests/test_linear_capital_scaled_P01_normal_evidence_recovery_revision2.py','_recovery_v3_stored_fixtures')
    old,run,tasks,contexts,calls,base=fixtures.stored.__wrapped__(tmp_path,monkeypatch)
    from test_reference_evidence_policy import diagnose
    for ctx in contexts:
        ctx.config['diagnosis']['execution']={
            'reference_evidence_transport':'audited_summary',
            'private_evidence_directory':str(tmp_path/'synthetic_complete_private_artifacts')}
        # Both compaction branches occur in current full context. The middle
        # records must remain bound even though examples contain only endpoints.
        ctx.data['source_assessment']['TEST_ONLY_complete_evidence']=[{'item':i} for i in range(9)]
        ctx.data['source_assessment']['TEST_ONLY_long_business_note']='declared synthetic evidence '*90
        diagnose(ctx)
    (run/'resolved_config.yaml').write_text(yaml.safe_dump(contexts[0].config))
    proposal=json.loads(Path(old._N['PROPOSAL']['path']).read_text())
    proposal['anchors']={key:entry.reference(row['path']) for key,row in proposal['anchors'].items()}
    proposal_path=tmp_path/'new_synthetic_approved_proposal.json';base.put(proposal_path,proposal)
    for name,value in {'RUN':run,'PROPOSAL':entry.reference(proposal_path),
            'validate_trial_observations':old._N['validate_trial_observations']}.items():
        monkeypatch.setitem(entry._N,name,value)
    return entry,run,tasks,contexts,calls,base


def test_complete_artifact_compaction_recovers_same_stored_proof_without_old_mutation(stored,tmp_path):
    m,run,tasks,contexts,calls,base=stored
    original=m._real_reporting._reference_review
    original_globals=dict(original.__globals__)
    prior=original(run,tasks[0])
    assert prior['verified'] is False and prior['reason']=='Diagnostic reference evidence differs from current goal'
    (run/'run.sqlite-wal').write_bytes(b'');(run/'run.sqlite-shm').write_bytes(b'S'*32768)
    before=base.tree(run);out=tmp_path/'new_revision3'
    prepared=m.prepare(out);frozen=json.loads(Path(prepared['path']).read_text())
    assert frozen['version']==3 and frozen['kind'].endswith('_revision3') and not calls
    certificate=m.certify(out);result=json.loads(Path(certificate['path']).read_text())
    assert result['version']==3 and result['kind'].endswith('_revision3')
    assert result['evidence_recovered'] is True and len(calls)==4
    assert result['new_calls']=={'model':0,'LO':0,'Harbor':0,'Docker':0}
    assert result['qualified'] is result['formal_release'] is result['original_statuses_changed'] is False
    assert result['raw_rewards_modified'] is result['quarantined_exports_moved_or_copied'] is False
    assert result['original_reporter_module_globals_changed'] is False
    assert result['sqlite_snapshot_at_preparation']==result['sqlite_snapshot_at_exit']==frozen['sqlite_snapshot']
    checks=result['audited_summary_transport_checks']
    assert len(checks)==2 and {row['task_id'] for row in checks}==set(m.TASKS)
    assert all(row['field_inventory_checked'] and row['unique_complete_context_fragment_checked']
        and row['exact_frozen_compaction_checked'] and row['new_financial_calculations']==0 for row in checks)
    accessed={row['reference']['path'] for row in result['read_only_access_inventory']}
    assert all(row['full_artifact']['path'] in accessed for row in checks)
    assert str(m.PRODUCER) in accessed and str(m.REPORTER) in accessed
    assert base.tree(run)==before
    assert m._real_reporting._reference_review is original
    assert original.__globals__==original_globals
    with pytest.raises(ValueError,match='first certificate'):m.certify(out)


@pytest.fixture
def compacted(tmp_path,entry):
    from sheets_factory.checkers.reference_evidence import reference_review_evidence
    context={'binding':{'task_id':'TEST_ONLY'},'business_records':[{'index':i,'amount':i+3} for i in range(9)],
        'complete_note':'synthetic complete note '*100}
    private={'reference_review_context':context,'goal_sha256':'test-only-not-a-goal'}
    transport=reference_review_evidence(private,tmp_path/'artifacts')
    evidence={'private':deepcopy(transport['private_summary']),'private_evidence':transport}
    return entry,evidence,evidence['private'],context


def test_pure_projection_binds_complete_list_and_string_not_just_examples(compacted):
    m,evidence,private,context=compacted;access=m.Access()
    assert private['reference_review_context']!=context
    assert m._bound_audited_context(evidence,private,context,access) is True
    access.guard()
    check,=access.audited_summary_checks
    assert check['canonical_context_sha256']==hashlib.sha256(m._bytes(context)).hexdigest()
    assert check['full_artifact']['path'] in access.records


@pytest.mark.parametrize('fault',['context_middle_record','inventory_count','inventory_hash','inventory_type',
    'summary_count','summary_pointer','summary_middle_hash','summary_version','summary_verdict_flag',
    'payload_private','complete_flag','encoding','extra_artifact_key','missing_artifact'])
def test_summary_inventory_and_transport_cannot_replace_full_context(compacted,fault):
    m,evidence,private,context=compacted
    transport=evidence['private_evidence'];summary=private['reference_review_context']['business_records']
    if fault=='context_middle_record':context['business_records'][4]['amount']+=1
    elif fault.startswith('inventory_'):
        key=fault.removeprefix('inventory_');transport['field_inventory']['reference_review_context'][key]=0 if key=='count' else 'wrong'
    elif fault=='summary_count':summary['count']-=1
    elif fault=='summary_pointer':summary['json_pointer']='/another/context'
    elif fault=='summary_middle_hash':summary['sha256']='0'*64
    elif fault=='summary_version':transport['summary_version']=2
    elif fault=='summary_verdict_flag':transport['summary_is_not_a_quality_verdict']=False
    elif fault=='payload_private':private['unexpected']='not in actual summary'
    elif fault=='complete_flag':transport['full_artifact']['complete']=False
    elif fault=='encoding':transport['full_artifact']['encoding']='unknown'
    elif fault=='extra_artifact_key':transport['full_artifact']['extra']='unbound'
    else:Path(transport['full_artifact']['path']).unlink()
    with pytest.raises((ValueError,OSError)):m._bound_audited_context(evidence,private,context,m.Access())


@pytest.mark.parametrize('fault',['unannounced_byte_change','changed_middle_with_new_artifact_hash',
    'duplicate_context','noncanonical_context','absent_context','bad_delimiter'])
def test_full_artifact_requires_original_sha_and_unique_exact_canonical_fragment(compacted,fault):
    m,evidence,private,context=compacted;full=evidence['private_evidence']['full_artifact'];path=Path(full['path'])
    if fault=='unannounced_byte_change':path.write_bytes(path.read_bytes()+b' ')
    else:
        canonical=m._bytes(context)
        if fault=='changed_middle_with_new_artifact_hash':
            changed=deepcopy(context);changed['business_records'][4]['amount']+=1
            raw=m._bytes({'reference_review_context':changed})
        elif fault=='duplicate_context':raw=b'{"reference_review_context": '+canonical+b', "nested": {"reference_review_context": '+canonical+b'}}'
        elif fault=='noncanonical_context':raw=json.dumps({'reference_review_context':context},sort_keys=False).encode()
        elif fault=='absent_context':raw=b'{"other_context": '+canonical+b'}'
        else:raw=b'{"reference_review_context": '+canonical+b'0}'
        path.write_bytes(raw);full.update(m.reference(path))
    with pytest.raises(ValueError):m._bound_audited_context(evidence,private,context,m.Access())


def test_frozen_producer_drift_rejected_without_editing_original_code(compacted,monkeypatch):
    m,evidence,private,context=compacted;monkeypatch.setattr(m,'PRODUCER_SHA','0'*64)
    with pytest.raises(ValueError,match='compaction policy changed'):
        m._bound_audited_context(evidence,private,context,m.Access())


@pytest.mark.parametrize('fault',['stale_Q04','wrong_goal','incomplete_resources','nonempty_WAL'])
def test_transport_fix_keeps_all_prior_quality_material_resource_and_WAL_gates(stored,tmp_path,monkeypatch,fault):
    m,run,_,contexts,calls,base=stored;out=tmp_path/'prepared'
    if fault=='nonempty_WAL':
        (run/'run.sqlite-wal').write_bytes(b'pending frame')
        with pytest.raises(ValueError,match='exact zero-byte regular WAL'):m.prepare(out)
        assert not out.exists() and not calls;return
    m.prepare(out);frozen,access=m.validate_prepared(out)
    if fault=='stale_Q04':
        path=contexts[0].revision_dir/'private/diagnosis.json';value=json.loads(path.read_text())
        value['assessments']['Q04']['evidence']=[];base.put(path,value)
    elif fault=='wrong_goal':(contexts[0].revision_dir/'private/goal.xlsx').write_bytes(b'changed')
    else:monkeypatch.setitem(m._N,'validate_trial_observations',lambda *args,**kwargs:{'passed':False,'complete':False})
    before=base.tree(run)
    with pytest.raises(ValueError):m._recover(frozen,access)
    assert base.tree(run)==before


def test_new_reporter_AST_changes_only_exact_context_transport_comparison(entry):
    m=entry;original=ast.parse(m.REPORTER.read_bytes())
    left=next(node for node in original.body if isinstance(node,ast.FunctionDef) and node.name=='_reference_review')
    right=m.reporter_ast().body[0]
    count=[]
    class Restore(ast.NodeTransformer):
        def visit_Call(self,node):
            if ast.unparse(node)=='_bound_audited_context(evidence, private, context)':
                count.append(1);return ast.parse("private.get('reference_review_context') == context").body[0].value
            return self.generic_visit(node)
    restored=Restore().visit(right)
    assert count==[1] and ast.dump(left,include_attributes=False)==ast.dump(restored,include_attributes=False)
    assert m.reference(m.FROZEN)['sha256']==m.FROZEN_SHA
    assert m.reference(m.REPORTER)['sha256']==m.REPORTER_SHA
    assert m.reference(m.PRODUCER)['sha256']==m.PRODUCER_SHA
    for record in m._V2['LINEAGE'].values():assert m.reference(record['path'])==record

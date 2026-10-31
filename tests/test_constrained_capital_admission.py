"""Explicit tiny mocked source fixtures; no complete record/source/LO/model run."""
import ast
from copy import deepcopy
import importlib.util
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sheets_factory.pipelines import constrained_capital_admission as admission

ROOT=Path(__file__).resolve().parents[1]
definition=importlib.util.spec_from_file_location('_D02_shared_admission_fixture',ROOT/'tests/test_scaled_capital_admission.py')
old_tests=importlib.util.module_from_spec(definition);definition.loader.exec_module(old_tests)


@pytest.fixture
def mocked_source(tmp_path,monkeypatch):
    """Adapt only unit fixture identities, never a production D01 receipt."""
    monkeypatch.setattr(old_tests,'admission',admission)
    value=old_tests.tiny_mocked_source.__wrapped__(tmp_path,monkeypatch)
    value.source['kind']='independently_verified_constrained_capital_allocation_source'
    value.source['profile_id']='30-D02'
    artifacts=value.source['public_contract_artifacts']
    contract=admission.catalog.public_contract('30-D02')
    artifacts['candidate_contract']=old_tests.write(value.root/'D02_UNIT_contract.json',contract)
    markdown=value.root/'D02_UNIT_contract.md';markdown.write_text(admission.catalog.contract_markdown(contract))
    artifacts['candidate_contract_markdown']=admission.reference(markdown)
    value.frozen['copied_public_contract_artifacts']=artifacts
    # The fake builder's closed-over preparation must bind the new fixture
    # sidecars, just as the real D02 builder binds its actual copied files.
    value.source['source_preparation']=old_tests.write(value.root/'D02_UNIT_preparation.json',value.frozen)
    value.source_ref=old_tests.write(value.root/'D02_UNIT_manifest.json',value.source)
    return value


def test_explicit_D02_source_reproduces_all_three_audits_and_complete_proof(mocked_source):
    value=mocked_source;session=admission.ReferenceSession()
    proof=admission.validate_source(value.source_ref,session=session)
    assert proof['kind']=='checked_first_constrained_capital_source_admission'
    assert proof['profile_id']=='30-D02' and proof['validation_method']==admission.METHOD
    assert proof['source_builder']['sha256']==admission.BUILDER_SHA256
    assert proof['shared_admission_helpers']['sha256']==admission.SHARED_HELPER_SHA256
    assert value.count=={'builder':1,'audits':3}
    assert admission.verify_admitted_proof(proof,session=session)==proof
    assert admission.verify_admitted_proof(proof,session=session)==proof
    assert value.count=={'builder':1,'audits':3}
    assert proof['physical_formula_count']==77513 and proof['quality_or_difficulty_certified'] is False


def test_caller_cache_scope_regression_has_identical_source_proof_and_keeps_fast_guards(mocked_source):
    value=mocked_source
    fresh=admission.validate_source(value.source_ref)
    session=admission.ReferenceSession();unrelated=value.root/'unrelated_ENTRY_fixture.py';unrelated.write_text('# unrelated\n')
    unrelated_ref=session.ref(unrelated)
    warm=admission.validate_source(value.source_ref,session=session)
    assert warm==fresh
    assert json.dumps(warm)==json.dumps(fresh)
    assert str(unrelated) not in warm['verified_artifacts'] and str(unrelated) not in warm['artifact_sha256']
    assert session._checked[str(unrelated)][0]==unrelated_ref
    admission.verify_admitted_proof(warm,session=session)
    assert value.count=={'builder':2,'audits':6}


def test_fresh_process_equivalent_session_revalidates_actual_source_not_persisted_labels(mocked_source):
    value=mocked_source;proof=admission.validate_source(value.source_ref)
    assert admission.verify_admitted_proof(proof)==proof
    assert value.count=={'builder':2,'audits':6}


def test_conflicting_caller_cache_cannot_be_partially_imported(mocked_source):
    value=mocked_source;session=admission.ReferenceSession()
    record=value.root/'mock_records.bin';original=record.read_bytes();record.write_bytes(b'old caller identity')
    session.ref(record);record.write_bytes(original);before=deepcopy(session._checked)
    with pytest.raises(ValueError,match='Conflicting.*merge'):
        admission.validate_source(value.source_ref,session=session)
    assert session._checked==before and session._proofs==set()


@pytest.mark.parametrize('change',['D01_kind','D01_profile','H01_profile'])
def test_old_source_identity_or_future_confirmation_profile_is_rejected(mocked_source,change):
    value=mocked_source
    if change=='D01_kind':value.source['kind']='independently_verified_scaled_capital_allocation_source'
    else:value.source['profile_id']='30-D01' if change=='D01_profile' else '30-H01'
    with pytest.raises(ValueError,match='actual complete'):
        admission.validate_source(value.write_source())
    assert value.count=={'builder':0,'audits':0}


@pytest.mark.parametrize('change',['old18','missing_sidecar_flag','unprotected_helper','missing_financial_field',
    'missing_pass','wrong_source_image','eight_gib','network_public','agent_resources_claim','not_feasible',
    'wrong_objective','changed_public_contract','wrong_terminal','resource_unverified','resource_cpu','bad_time_order'])
def test_unchanged_financial_resource_and_public_scope_fail_closed(mocked_source,change):
    old_tests.test_source_rejects_incomplete_financial_resource_and_public_evidence(mocked_source,change)


def test_current_formula_audit_recomputed_not_passed_flag(mocked_source,monkeypatch):
    old_tests.test_complete_second_audit_is_recomputed_instead_of_trusting_passed(mocked_source,monkeypatch)


def test_current_two_typed_stability_comparisons_recomputed(mocked_source):
    old_tests.test_both_further_typed_stability_comparisons_are_reproduced(mocked_source)


def test_normal_factory_is_FM1_and_transports_only_D02_source_session(mocked_source,monkeypatch):
    value=mocked_source;session=admission.ReferenceSession();proof=admission.validate_source(value.source_ref,session=session)
    seed={'source_kind':admission.SOURCE_KIND,'profile_id':'30-D02','modes':['financial_modeling'],'variant':0,
        'local_path':proof['workbook']['path'],'sha256':proof['workbook']['sha256'],
        'finance_evidence':{'audited_source_binding':proof,'source_manifest':proof['source_manifest']}}
    monkeypatch.setattr(admission.FactoryPipeline,'__init__',lambda self,*a,**kw:None)
    monkeypatch.setattr(admission.FactoryPipeline,'load_seeds',lambda self:[deepcopy(seed)])
    monkeypatch.setattr(admission.FactoryPipeline,'run_phase',lambda self,ctx,phase:{'phase':phase})
    factory=admission.ConstrainedCapitalFactory(admitted_proof=proof,admission_session=session)
    factory.targets={'financial_modeling':1,'debugging':0}
    assert factory.load_seeds()[0]['survey']['normalized_path']==proof['workbook']['path']
    ctx=SimpleNamespace(source=proof['workbook']['path'],data={'baseline':proof['workbook']['path'],'source_id':proof['workbook']['sha256']})
    assert factory.run_phase(ctx,'plan')=={'phase':'plan'}
    assert ctx.data['_constrained_admission_session'] is session and '_scaled_admission_session' not in ctx.data
    assert value.count=={'builder':1,'audits':3}
    seed['profile_id']='30-D01'
    with pytest.raises(ValueError,match='exact prospectively'):factory.load_seeds()
    seed['profile_id']='30-D02';factory.targets={'financial_modeling':10,'debugging':0}
    with pytest.raises(ValueError,match='first-development'):factory.load_seeds()


def test_math_audit_and_canonical_session_logic_match_frozen_D01_except_explicit_identity_binding():
    assert admission.ReferenceSession is admission.shared.ReferenceSession
    assert admission._actual_calls is admission.shared._actual_calls
    assert admission.verify_references is admission.shared.verify_references
    assert admission.shared.PROFILE_ID=='30-D01' and admission.PROFILE_ID=='30-D02'
    replacements={'independently_verified_scaled_capital_allocation_source':'independently_verified_constrained_capital_allocation_source',
        'checked_first_scaled_capital_source_admission':'checked_first_constrained_capital_source_admission',
        'scripts/build_scaled_capital_source.py':'scripts/build_constrained_capital_source.py'}
    class Identity(ast.NodeTransformer):
        def visit_Constant(self,node):
            if type(node.value) is str and node.value in replacements:node.value=replacements[node.value]
            return node
        def visit_Dict(self,node):
            pairs=[(k,v) for k,v in zip(node.keys,node.values) if not isinstance(k,ast.Constant) or k.value!='shared_admission_helpers']
            node.keys=[p[0] for p in pairs];node.values=[p[1] for p in pairs]
            return self.generic_visit(node)
    for name in ('validate_source','_validate_source','verify_admitted_proof'):
        old=ast.parse(inspect.getsource(getattr(admission.shared,name)))
        new=ast.parse(inspect.getsource(getattr(admission,name)))
        if name=='_validate_source':new.body[0].body.pop(0)  # extra shared-helper SHA guard
        assert ast.dump(Identity().visit(old))==ast.dump(Identity().visit(new))


def test_large_artifact_helpers_still_stream_and_reject_later_mutation(tmp_path,monkeypatch):
    # The streaming implementation is shared and unchanged, not another loader.
    old_tests.test_reference_hash_never_materialises_a_binary_with_read_bytes(tmp_path,monkeypatch)

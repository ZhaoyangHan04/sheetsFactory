"""Pure revision2 provenance/cold-binding tests; no financial forwards or services."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def module():
    path=ROOT/'scripts/build_operating_reports_200_source_revision2.py'
    spec=importlib.util.spec_from_file_location('_test_fixed200_source_revision2',path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    return m


def put(m,path,value):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return m.reference(path)


@pytest.fixture
def failure(module,tmp_path,monkeypatch):
    m=module;root=tmp_path/'original';root.mkdir()
    inp=put(m,root/'cold.xlsx',{'TEST_ONLY':'original cold input'})
    out=put(m,root/'source1.xlsx',{'TEST_ONLY':'original native output'})
    emission=put(m,root/'receipt.json',{'kind':'pure_operating_reports_200_emission'})
    candidate=put(m,root/'candidate.json',{'emission_receipt':emission,'source':inp})
    prepared={'kind':'prepared_fixed_operating_reports_200_cold_source','candidate_manifest':candidate,
        'specification':put(m,root/'spec.json',{}),'specification_sha256':m.SPECIFICATION_SHA256,'cold_start':inp}
    prepared_ref=put(m,root/'preparation.json',prepared)
    resource={'container_id':'a'*64,'TEST_ONLY':'mocked existing native-resource validation'}
    resource['terminal']=put(m,root/'resource.json',resource)
    call={'index':1,'role':'source1','completed':True,'input':inp,'output':out,'actual_resource_evidence':resource}
    call['terminal_receipt']=put(m,root/'call.json',deepcopy(call))
    report={'kind':'full_fixed_operating_reports_200_native_audit','passed':False,'workbook':out,
        'all_financial_fields_checked':93510,'all_derived_values_checked':93510,'physical_formulas_checked':88676,
        'mismatches':deepcopy(m._MISMATCHES),'native_errors':[]}
    cleanup={'all_owned_containers_absent':True,'daemon_reachable':True,
        'owned':[{'full_id':'a'*64,'absent':True,'returncode':1,'stdout':'\n','stderr':'error: no such object: '+'a'*64+'\n'}]}
    terminal={'kind':'independently_checked_fixed_operating_reports_200_source','version':1,'passed':False,'qualified':False,
        'actual_LO_calls_started':1,'actual_LO_calls_completed':1,'actual_calls':[call],'cold_start_is_unseeded':True,
        'specification_sha256':m.SPECIFICATION_SHA256,'specification':prepared['specification'],'preparation':prepared_ref,
        'source':out,'failure':{'type':'ValueError','message':'Complete independent financial/type/literal audit failed'},
        'model_calls':0,'solver_calls':0,'Harbor_calls':0,'task_count':0,'retry':0,
        'records':{'source1_audit':put(m,root/'audit.json',report),'failure_cleanup':put(m,root/'cleanup.json',cleanup)}}
    ref=put(m,root/'source_manifest.json',terminal);monkeypatch.setattr(m,'_OLD_FAILURE',ref)
    checks=[]
    def validated(call,record,frozen):checks.append((call,record,frozen));return resource
    monkeypatch.setattr(m,'validate_call',validated)
    return SimpleNamespace(m=m,root=root,terminal=terminal,report=report,cleanup=cleanup,checks=checks)


def test_distinct_identity_counted_clone_and_wrapped_lifecycle_globals(module):
    m=module;m._adapted_ast()
    assert m.KIND=='prepared_fixed_operating_reports_200_cold_source_revision2'
    assert m.SOURCE_KIND=='independently_checked_fixed_operating_reports_200_source_revision2'
    assert m._original_execute.__globals__['validate_prepared'] is m.validate_prepared
    assert m._original_validate_source.__globals__['validate_prepared'] is m.validate_prepared
    assert m._source_namespace['validate_prepared'] is m.validate_prepared
    assert m._source_namespace['recipes'] is m.recipes


def test_unfrozen_renderer_cannot_prepare_or_supply_recipes(module,monkeypatch):
    monkeypatch.setattr(module,'_RENDERER_SHA','PENDING')
    with pytest.raises(ValueError,match='not frozen'):module.recipes()


def test_real_recipe_freezes_both_original_source_and_final_renderer_without_execution(module):
    recipes=module.recipes()
    assert recipes[str(module._UPSTREAM)]['sha256']==module._UPSTREAM_SHA
    assert recipes[str(module._RENDERER)]['sha256']==module._RENDERER_SHA
    assert recipes[str(Path(module.__file__).resolve())]==module.reference(module.__file__)


def test_original_failure_exact_two_misses_resource_and_lowercase_absence_are_bound(failure):
    f=failure;proof=f.m._old_failure_proof()
    assert proof['failed_source']==f.m._OLD_FAILURE and len(f.checks)==1
    assert proof['audit']==f.terminal['records']['source1_audit']
    assert proof['cleanup']==f.terminal['records']['failure_cleanup']


@pytest.mark.parametrize('fault',['passed','calls','audit_error','audit_extra','cleanup','wrong_id','changed_bytes'])
def test_missing_or_changed_original_failure_evidence_rejected(failure,monkeypatch,fault):
    f=failure;m=f.m;t=deepcopy(f.terminal)
    if fault=='passed':t['passed']=True
    elif fault=='calls':t['actual_LO_calls_started']=2
    elif fault in ('audit_error','audit_extra'):
        report=deepcopy(f.report)
        if fault=='audit_error':report['native_errors']=['#VALUE!']
        else:report['mismatches'].append(deepcopy(report['mismatches'][0]))
        t['records']['source1_audit']=put(m,f.root/'modified_audit.json',report)
    elif fault in ('cleanup','wrong_id'):
        cleanup=deepcopy(f.cleanup)
        if fault=='cleanup':cleanup['daemon_reachable']=False
        else:cleanup['owned'][0]['full_id']='b'*64
        t['records']['failure_cleanup']=put(m,f.root/'modified_cleanup.json',cleanup)
    else:
        Path(m._OLD_FAILURE['path']).write_text('{}')
        with pytest.raises(ValueError):m._old_failure_proof()
        return
    monkeypatch.setattr(m,'_OLD_FAILURE',put(m,f.root/'modified_failure.json',t))
    with pytest.raises(ValueError):m._old_failure_proof()


@pytest.fixture
def renderer_case(module,tmp_path,monkeypatch):
    m=module;folder=tmp_path/'rendered';folder.mkdir();public={'TEST_ONLY':'public facts'}
    monkeypatch.setattr(m,'SPECIFICATION_SHA256',m.schema.canonical_sha256(public))
    spec=put(m,tmp_path/'spec.json',public);left=put(m,tmp_path/'A.json',{});right=put(m,tmp_path/'B.json',{})
    renderer=tmp_path/'renderer.py';renderer.write_text('# TEST ONLY renderer boundary\n');monkeypatch.setattr(m,'_RENDERER',renderer)
    base=put(m,folder/'base.json',{'original':'unchanged'});original=dict(base)
    original_path=tmp_path/'original_receipt.json';original_path.write_bytes(m.checked(base).read_bytes());original=m.reference(original_path)
    old={'base_emission_receipt':original,'base_emission_directory':str(tmp_path/'old')}
    monkeypatch.setattr(m,'_old_failure_proof',lambda:old)
    proof={'kind':'exact_finite_decimal_matching_growth_rendering','version':2,'renderer':m.reference(renderer),
        'specification_sha256':m.SPECIFICATION_SHA256,'matching_growth_fields':1600,'rules':{str(i):{} for i in range(1600)},
        'public_policy_and_facts_changed':False,'financial_intermediate_rounding':False,'hidden_epsilon':False,
        'native_calculations':0,'actual_D_unknown':True}
    proof_ref=put(m,folder/'rendering_proof.json',proof)
    receipt={'kind':'pure_operating_reports_200_emission_rendering_v2','version':2,'matching_growth_formulas':1600,
        'rendering_proof':proof_ref,'base_emission_receipt':base};put(m,folder/'receipt.json',receipt)
    fresh={'kind':'complete_exact_finite_decimal_rendering_equivalence','version':2,'passed':True,
        'specification_sha256':m.SPECIFICATION_SHA256,'matching_growth_exact_and_primary_checked':1600,
        'complete_original_A_B_points_unchanged':93510,'all_provided_facts_context_and_NA_unchanged':True,
        'all_other_formulas_unchanged':True,'original_DBG_fault_definitions_retained':200,
        'original_DBG_roots_primary_impact_proved':200,'native_calls':0,'actual_D_unknown':True,
        'original_emission_receipt':original,'base_emission_receipt':base,'rendering_proof':proof_ref}
    calls=[]
    def prove(*args):calls.append(args);return fresh
    monkeypatch.setattr(m,'_renderer',lambda:SimpleNamespace(prove=prove))
    return SimpleNamespace(m=m,root=folder,spec=spec,left=left,right=right,proof=proof,receipt=receipt,fresh=fresh,calls=calls)


def test_rendering_proof_is_freshly_replayed_over_original_inputs_and_all_counts(renderer_case):
    c=renderer_case;lineage=c.m._rendering_proof(c.spec,c.root,c.left,c.right)
    assert len(c.calls)==1 and c.calls[0][-1]==c.root
    assert lineage['complete_rendering_equivalence']==c.fresh and lineage['actual_LO_calls']==0
    assert lineage['normal_quality_inherited'] is False


@pytest.mark.parametrize('fault',['epsilon','policy','count','business','failed','base','faults'])
def test_asserted_success_cannot_replace_full_rendering_and_lineage_proof(renderer_case,fault):
    c=renderer_case;m=c.m
    if fault in ('epsilon','policy','count'):
        if fault=='epsilon':c.proof['hidden_epsilon']=True
        elif fault=='policy':c.proof['public_policy_and_facts_changed']=True
        else:c.proof['matching_growth_fields']=1599
        c.receipt['rendering_proof']=put(m,c.root/'modified_proof.json',c.proof)
        put(m,c.root/'receipt.json',c.receipt)
    elif fault=='base':
        c.receipt['base_emission_receipt']=put(m,c.root/'changed_base.json',{'changed':True});put(m,c.root/'receipt.json',c.receipt)
    elif fault=='business':c.fresh['complete_original_A_B_points_unchanged']=93509
    elif fault=='faults':c.fresh['original_DBG_roots_primary_impact_proved']=199
    else:c.fresh['passed']=False
    with pytest.raises(ValueError):m._rendering_proof(c.spec,c.root,c.left,c.right)


def test_sidecar_replayed_on_each_cold_validate_and_cannot_inherit_quality(module,tmp_path,monkeypatch):
    m=module;renderer=tmp_path/'renderer.py';renderer.write_text('# test renderer\n');monkeypatch.setattr(m,'_RENDERER',renderer)
    monkeypatch.setattr(m,'_OLD_FAILURE',put(m,tmp_path/'failed.json',{}))
    source=put(m,tmp_path/'source.xlsx',{});a=put(m,tmp_path/'A.json',{});b=put(m,tmp_path/'B.json',{});raw=put(m,tmp_path/'raw.json',{})
    candidate=put(m,tmp_path/'candidate.json',{'source':source,'retained_A':a,'retained_B':b})
    original={'kind':m.KIND,'candidate_manifest':candidate,'specification':raw};calls=[]
    monkeypatch.setattr(m,'_rendering_proof',lambda *args:calls.append(args) or {'TEST_ONLY':'fresh full proof'})
    def prepare(*args,**kwargs):
        output=Path(args[4]);output.mkdir();return put(m,output/'preparation.json',original)
    monkeypatch.setattr(m,'_original_prepare',prepare)
    monkeypatch.setattr(m,'_original_validate_prepared',lambda path:original)
    output=tmp_path/'fresh';result=m.prepare(raw,tmp_path,a,b,output)
    assert result==m.reference(output/'preparation.json') and len(calls)==2
    checked=m.validate_prepared(output);assert len(calls)==3 and checked['revision2_provenance']==m.reference(output/'revision2_provenance.json')
    sidecar=m.read(output/'revision2_provenance.json');sidecar['normal_quality_inherited']=True
    (output/'revision2_provenance.json').write_text(json.dumps(sidecar))
    with pytest.raises(ValueError):m.validate_prepared(output)
    assert len(calls)==4

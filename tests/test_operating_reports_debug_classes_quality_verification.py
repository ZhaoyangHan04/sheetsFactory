"""Absent-only goal metadata transport; all other quality guards stay strict."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sheets_factory.workbook.linear_capital_ringfenced_group import contract as files
from test_reference_review_reporting import reviewed_run
from test_reference_evidence_policy import context as reference_context
import test_operating_reports_financial_cohort_quality as transport

ROOT=Path(__file__).resolve().parents[1]


def entry():
    spec=importlib.util.spec_from_file_location('_SG_append_only_verifier_test',ROOT/'scripts/verify_operating_reports_debug_classes_quality.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.fixture
def goal(tmp_path):
    base=tmp_path/'revision';(base/'private').mkdir(parents=True)
    path=base/'private/goal.xlsx';path.write_bytes(b'the exact original goal bytes')
    full=files.reference(path);return base,full,{'goal_sha256':full['sha256']}


@pytest.mark.parametrize('flat',['absent','correct'])
def test_absent_flat_uses_only_exact_full_current_goal_reference(goal,flat):
    module=entry();base,full,binding=goal;native={'goal':full}
    if flat=='correct':native['goal_sha256']=full['sha256']
    before=deepcopy(native)
    assert module._bound_native_goal_digest(native,binding,base)==full['sha256']
    assert native==before


@pytest.mark.parametrize('flat',[None,'0'*64,True,1,'short'])
def test_present_wrong_flat_is_never_overridden_by_correct_nested_goal(goal,flat):
    module=entry();base,full,binding=goal
    with pytest.raises(ValueError,match='present flat'):
        module._bound_native_goal_digest({'goal_sha256':flat,'goal':full},binding,base)


@pytest.mark.parametrize('problem',['missing','sha','bytes','path','incomplete','symlink','changed'])
@pytest.mark.parametrize('flat',['absent','correct'])
def test_missing_or_conflicting_full_current_goal_rejects_without_artifact_repair(goal,tmp_path,problem,flat):
    module=entry();base,full,binding=goal;native={'goal':deepcopy(full)}
    if flat=='correct':native['goal_sha256']=full['sha256']
    if problem=='missing':
        native.pop('goal')
        if flat=='correct':
            # Preserve the original valid flat-only reporter representation.
            assert module._bound_native_goal_digest(native,binding,base)==full['sha256'];return
    elif problem=='sha':native['goal']['sha256']='0'*64
    elif problem=='bytes':native['goal']['bytes']+=1
    elif problem=='path':
        other=tmp_path/'other.xlsx';other.write_bytes(Path(full['path']).read_bytes());native['goal']=files.reference(other)
    elif problem=='incomplete':native['goal'].pop('bytes')
    elif problem=='symlink':
        alias=tmp_path/'alias.xlsx';alias.symlink_to(full['path']);native['goal']['path']=str(alias)
    else:Path(full['path']).write_bytes(b'different current material')
    with pytest.raises(ValueError):module._bound_native_goal_digest(native,binding,base)


def rewrite_native(fixture,module,mutation):
    root,run,audit,ctx=fixture;folder=ctx.revision_dir/'private'
    path=folder/'native_error_probe.json';native=json.loads(path.read_text())
    native['goal']=files.reference(folder/'goal.xlsx');mutation(native)
    path.write_text(json.dumps(native));receipt_path=folder/'reference_review.json';receipt=json.loads(receipt_path.read_text())
    receipt['artifacts']['native_error_probe.json']={'path':str(path.resolve()),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    receipt_path.write_text(json.dumps(receipt));diagnosis_path=folder/'diagnosis.json';diagnosis=json.loads(diagnosis_path.read_text())
    diagnosis['reference_review']=receipt;diagnosis_path.write_text(json.dumps(diagnosis))
    return transport.summarized_review(fixture,module.normal,True)


def test_new_private_reporter_accepts_exact_missing_flat_transport_without_old_global_or_file_mutation(reviewed_run):
    module=entry();r=rewrite_native(reviewed_run,module,lambda native:native.pop('goal_sha256'))
    before={str(p):p.read_bytes() for p in r.ctx.revision_dir.rglob('*') if p.is_file()}
    original=module.normal.generate_report(r.run,project_root=r.root)
    assert original['yield']['reported_qualified']==1 and original['yield']['verified_qualified']==0
    report=module.generate_report(r.run,project_root=r.root)
    assert report['yield']['verified_qualified']==1 and report['tasks'][0]['reference_validation']['verified']
    assert before=={str(p):p.read_bytes() for p in r.ctx.revision_dir.rglob('*') if p.is_file()}
    assert module.ADAPTATION_COUNTS=={'existing_complete_context':1,'missing_flat_goal_digest':1}
    assert module._reporting['_reference_review'].__globals__ is not module.normal._reporting
    assert not report['tasks'][0]['independent_recovery']['verified']


@pytest.mark.parametrize('problem',['wrong_flat','null_flat','nested_conflict','missing_both','native_error','Q04','Q12','full_context'])
def test_correct_nested_goal_cannot_bypass_original_reference_quality_requirements(reviewed_run,problem):
    module=entry()
    def mutate(native):
        if problem=='wrong_flat':native['goal_sha256']='0'*64
        elif problem=='null_flat':native['goal_sha256']=None
        elif problem=='nested_conflict':native['goal']={**native['goal'],'sha256':'0'*64}
        elif problem=='missing_both':native.pop('goal_sha256',None);native.pop('goal',None)
        elif problem=='native_error':native['blocking']=True
    r=rewrite_native(reviewed_run,module,mutate)
    if problem in ('Q04','Q12'):
        diagnosis=json.loads(r.diagnosis_path.read_text())
        if problem=='Q04':diagnosis['assessments']['Q04']['evidence']=[]
        else:diagnosis['enabled_check_ids'].remove('Q12')
        r.diagnosis_path.write_text(json.dumps(diagnosis))
    elif problem=='full_context':
        r.evidence['private_evidence']['field_inventory']['reference_review_context']['sha256']='0'*64
        r.evidence_path.write_text(json.dumps(r.evidence))
    report=module.generate_report(r.run,project_root=r.root)
    assert report['yield']['reported_qualified']==1 and report['yield']['verified_qualified']==0


def validation(tmp_path):
    observations=[]
    for index,role in enumerate(('agent','verifier'),1):
        cid=str(index)*64
        observations.append(files.write(tmp_path/(role+'.json'),{'role':role,'queried_container_id':cid,
            'container':{'Id':cid,'Image':'sha256:'+'3'*64}}))
    return {'passed':True,'complete':True,'roles_observed':['agent','verifier'],'observations':observations}


@pytest.mark.parametrize('problem',[None,'daemon','present','unknown','foreign_id','partial_roles'])
def test_cleanup_queries_only_exact_proven_owned_ids_and_never_turns_unknown_into_pass(tmp_path,monkeypatch,problem):
    module=entry();v=validation(tmp_path);calls=[]
    if problem=='foreign_id':
        row=files.read(v['observations'][0]);row['queried_container_id']='f'*64
        v['observations'][0]=files.write(tmp_path/'foreign.json',row)
    elif problem=='partial_roles':v['roles_observed']=['agent']
    def command(argv,**kwargs):
        calls.append(argv)
        if argv[:2]==['docker','info']:
            return SimpleNamespace(returncode=1 if problem=='daemon' else 0,stdout='' if problem=='daemon' else 'version',stderr='')
        assert argv[:4]==['docker','inspect','--type','container'] and argv[4] in {'1'*64,'2'*64}
        if problem=='present':return SimpleNamespace(returncode=0,stdout='[]',stderr='')
        return SimpleNamespace(returncode=1,stdout='',stderr='daemon unknown' if problem=='unknown' else 'No such object: '+argv[4])
    monkeypatch.setattr(module.subprocess,'run',command)
    if problem:
        with pytest.raises(ValueError):module._owned_absence([v])
    else:
        result=module._owned_absence([v,v])
        assert result['all_owned_containers_absent'] and len(result['owned'])==2
        assert len(calls)==3 and result['no_containers_created_changed_or_removed']
    if problem in ('foreign_id','partial_roles'):assert not calls


def test_verifier_early_panel_is_open_before_any_cold_replay(tmp_path,monkeypatch):
    from contextlib import contextmanager
    module=entry();events=[]
    @contextmanager
    def monitor(*a,**k):events.append('panel');yield {'passed':False}
    monkeypatch.setattr(module.normal,'admission_monitor',monitor)
    monkeypatch.setattr(module,'certify',lambda *a:events.append('cold') or {'test':'no services'})
    assert module.main(['--output',str(tmp_path/'fresh')])==0 and events==['panel','cold']

"""Root finalization fixtures are explicit mocks, never real qualification."""
from copy import deepcopy
import json
from pathlib import Path
import socket
import subprocess

import pytest

from sheets_factory.evaluation import linear_capital_scaled_finalization_v4 as final
from sheets_factory.evaluation import linear_capital_scaled_publication_v4 as publication


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value));return final.reference(path)


@pytest.fixture(autouse=True)
def no_services(monkeypatch):
    def forbidden(*a,**k):raise AssertionError('No actual commands or network in finalization tests')
    monkeypatch.setattr(subprocess,'run',forbidden);monkeypatch.setattr(subprocess,'Popen',forbidden)
    monkeypatch.setattr(socket,'create_connection',forbidden)


@pytest.fixture
def completed(tmp_path):
    root=tmp_path/'checkout';dataset=root/'SpreadsheetEval'
    rows=[{'task_id':('fm' if n<10 else 'dbg')+str(n),'mode':'financial_modeling' if n<10 else 'debugging'} for n in range(20)]
    manifest={'task_count':20,'counts_by_mode':{'financial_modeling':10,'debugging':10},'tasks':rows,
        'selected_task_ids':[r['task_id'] for r in rows],'final20_qualified':False,'final_root_controls_pending':True,
        'reference_evidence_policy':'reference_review'}
    manifest_ref=write(dataset/'dataset_manifest.json',manifest);commands={};audits={}
    for agent in ('oracle','nop'):
        job=root/'jobs'/agent;trials=[]
        for row in rows:
            path=job/row['task_id']/'result.json'
            write(path,{'started_at':'2026-10-31T19:01:00Z','finished_at':'2026-10-31T19:02:00Z'})
            write(path.parent/'config.json',{'fixture':True});trials.append({'task_id':row['task_id'],'result_file':str(path)})
        job_result=write(job/'result.json',{'fixture_only':True})
        observer=write(root/'private'/agent/'observer.json',{'mock':True})
        command={'kind':'executed_exact_root_harbor_control','version':1,'argv':final.COMMANDS[agent],
            'cwd':str(root),'returncode':0,'dataset_manifest':manifest_ref,'started_at':'2026-10-31T19:00:00Z',
            'finished_at':'2026-10-31T19:03:00Z','job_directory':str(job),'job_result':job_result,
            'resource_observation_receipts':[observer]}
        commands[agent]=write(root/'private'/agent/'command.json',command)
        audits[agent]={'status':'passed','agent':agent,'dataset_manifest_sha256':manifest_ref['sha256'],
            'counts':{'dataset_tasks':20,'trial_results':20,'matched_rewards':20,'exceptions':0,'missing':0,'unknown':0,'duplicates':0},
            'counts_by_mode':manifest['counts_by_mode'],'trials':trials}
    seen=[]
    def auditor(dataset_arg,job,*,agent,command_cwd,output):
        assert dataset_arg==dataset and command_cwd==root and output is None
        return deepcopy(audits[agent])
    def resources(config,result,*,receipts,expected_task_directory):
        assert expected_task_directory.parent==dataset and len(receipts)==1
        seen.append((config,result,expected_task_directory));return {'passed':True,'complete':True,'mock_not_actual_resources':True}
    return root,commands,audits,auditor,resources,seen


def test_all40_actual_role_checks_and_full20_jobs_required_read_only(completed):
    root,commands,_,auditor,resources,seen=completed
    before={p:p.read_bytes() for p in root.rglob('*') if p.is_file()}
    result=final.validate_root_controls(root,commands,auditor=auditor,resource_validator=resources)
    assert result['passed'] and len(result['root_controls'])==2 and len(seen)==40
    assert result['services_started']==0
    assert {p:p.read_bytes() for p in root.rglob('*') if p.is_file()}==before


@pytest.mark.parametrize('field,value',[
    ('argv',['harbor','run','-p','SpreadsheetEval','-a','oracle','--n-attempts','2']),
    ('argv',['harbor','run','-p','some-subset','-a','oracle']),
    ('cwd','/wrong/root'),('returncode',1),('returncode',True),('resource_observation_receipts',[])])
def test_exact_command_exit_and_evidence_contract(completed,field,value):
    root,commands,_,auditor,resources,_=completed
    record=final.checked(commands['oracle']);record[field]=value
    commands['oracle']=write(commands['oracle']['path'],record)
    with pytest.raises(ValueError):final.validate_root_controls(root,commands,auditor=auditor,resource_validator=resources)


def test_zero_exit_cannot_substitute_for_complete_results(completed):
    root,commands,audits,auditor,resources,_=completed
    audits['oracle']['counts']['matched_rewards']=19
    with pytest.raises(ValueError,match='twenty'):final.validate_root_controls(root,commands,auditor=auditor,resource_validator=resources)


def test_duplicate_or_missing_task_refuses_even_if_aggregate_claims20(completed):
    root,commands,audits,auditor,resources,_=completed
    audits['nop']['trials'][-1]=deepcopy(audits['nop']['trials'][0])
    with pytest.raises(ValueError,match='set differs'):final.validate_root_controls(root,commands,auditor=auditor,resource_validator=resources)


def test_missing_actual_agent_or_verifier_resources_refuses(completed):
    root,commands,_,auditor,_,_=completed
    with pytest.raises(ValueError,match='resource proof'):
        final.validate_root_controls(root,commands,auditor=auditor,resource_validator=lambda *a,**k:{'passed':False,'complete':False})


def test_changed_delivery_manifest_is_not_accepted_by_old_command(completed):
    root,commands,_,auditor,resources,_=completed
    path=root/'SpreadsheetEval/dataset_manifest.json';data=json.loads(path.read_text());data['extra']='changed';write(path,data)
    with pytest.raises(ValueError,match='original delivery'):final.validate_root_controls(root,commands,auditor=auditor,resource_validator=resources)


def test_actual_trial_outside_exact_command_window_refuses(completed):
    root,commands,audits,auditor,resources,_=completed
    path=Path(audits['oracle']['trials'][0]['result_file']);value=json.loads(path.read_text());value['finished_at']='2026-10-31T20:00:00Z';write(path,value)
    with pytest.raises(ValueError,match='outside'):final.validate_root_controls(root,commands,auditor=auditor,resource_validator=resources)


def test_original_root_auditor_code_is_reused_with_only_resource_inventory_namespace():
    auditor=final.resource_auditor();old=publication.support(final.ROOT,'audit_harbor_job.py')
    assert auditor.__code__.co_code==old.audit_harbor_job.__code__.co_code
    assert auditor.__code__.co_consts==old.audit_harbor_job.__code__.co_consts
    assert len(auditor.__globals__['EXPORT_FILES'])==17
    assert auditor.__globals__['inspect_export'] is publication.inspect_resource_export
    assert len(old.EXPORT_FILES)==13


def test_readme_lists_both_exact_root_commands_and_explicit_pending_state():
    assert 'final20_qualified=False' in final.PENDING_TEXT
    for command in final.COMMANDS.values():assert ' '.join(command) in final.PENDING_TEXT
    assert 'zero exit code alone does not qualify' in final.PENDING_TEXT

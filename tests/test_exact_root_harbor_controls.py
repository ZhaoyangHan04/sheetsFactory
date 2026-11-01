from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
loader=importlib.util.spec_from_file_location('exact_root_controls_test',ROOT/'scripts/run_exact_root_harbor_controls.py')
m=importlib.util.module_from_spec(loader);loader.loader.exec_module(m)


def test_exact_argv_and_private17file_original_auditor():
    assert m.COMMANDS=={'oracle':['harbor','run','-p','SpreadsheetEval','-a','oracle'],
                       'nop':['harbor','run','-p','SpreadsheetEval','-a','nop']}
    audit=m.auditor()
    assert audit.__globals__['EXPORT_FILES']==m.FILES and len(m.FILES)==17
    assert audit.__globals__['inspect_export'] is m.inspect_resource_export
    assert m.reference(m.AUDITOR)['sha256']==m.AUDITOR_SHA


def config(root,role='oracle'):
    # Exercise the actual installed Harbor exclude-defaults serializer; this is
    # a pure config construction, not CLI or native execution.
    from harbor.models.job.config import JobConfig,DatasetConfig
    from harbor.models.trial.config import AgentConfig
    value=JobConfig(job_name='one-new-job',datasets=[DatasetConfig(path=Path('SpreadsheetEval'))],
                    agents=[AgentConfig(name=role)])
    return json.loads(value.model_dump_json(exclude_defaults=True))


def test_owned_discovery_actual_sparse_default_config_excludes_prior_jobs(tmp_path):
    jobs=tmp_path/'jobs';jobs.mkdir();(jobs/'prior').mkdir();(jobs/'resource_observations').mkdir()
    assert m._new_job(jobs,{'prior'},'oracle',tmp_path) is None
    new=jobs/'one-new-job';new.mkdir()
    assert m._new_job(jobs,{'prior'},'oracle',tmp_path) is None
    value=config(tmp_path);assert 'n_attempts' not in value
    (new/'config.json').write_text(json.dumps(value))
    assert m._new_job(jobs,{'prior'},'oracle',tmp_path)==new


@pytest.mark.parametrize('change',[lambda v:v.update(agents=[{'name':'nop'}]),
    lambda v:v.update(job_name='another-name'),lambda v:v.update(n_attempts=2),
    lambda v:v.update(retry={'max_retries':1}),lambda v:v['datasets'][0].update(path='another-dataset'),
    lambda v:v.update(tasks=[{'path':'single-task'}])])
def test_other_role_repeat_wrong_dataset_or_name_cannot_be_owned(tmp_path,change):
    jobs=tmp_path/'jobs';new=jobs/'one-new-job';new.mkdir(parents=True)
    value=config(tmp_path);change(value);(new/'config.json').write_text(json.dumps(value))
    with pytest.raises(ValueError):m._new_job(jobs,set(),'oracle',tmp_path)


def test_two_new_jobs_are_ambiguous_before_any_container_query(tmp_path):
    jobs=tmp_path/'jobs';jobs.mkdir();(jobs/'a').mkdir();(jobs/'b').mkdir()
    with pytest.raises(ValueError,match='ambiguous'):m._new_job(jobs,set(),'oracle',tmp_path)


def test_observer_never_queries_old_jobs_and_binds_new_before_poll(tmp_path,monkeypatch):
    jobs=tmp_path/'jobs';jobs.mkdir();(jobs/'old').mkdir()
    calls=[];monkeypatch.setattr(m.ResourceObserver,'poll_once',lambda self:calls.append(self.job_dirs))
    observer=m.OwnedJobObserver(jobs,{'old'},'oracle',tmp_path)
    observer.poll_once();assert not calls
    new=jobs/'one-new-job';new.mkdir();(new/'config.json').write_text(json.dumps(config(tmp_path)))
    observer.poll_once();assert calls==[(new,)] and observer.owned_job==new


def test_cleanup_accepts_only_exact_full_owned_ids_and_case_insensitive_absence(tmp_path):
    cid='a'*64;path=tmp_path/'observation.json'
    path.write_text(json.dumps({'container':{'Id':cid},'queried_container_id':cid,'trial_name':'owned__trial','role':'agent'}))
    observations=[{'passed':True,'complete':True,'observations':[m.reference(path)]}]
    queries=[]
    def runner(argv,**kw):
        queries.append(argv)
        return SimpleNamespace(returncode=0,stdout='28.1',stderr='') if argv[1]=='info' else SimpleNamespace(returncode=1,stdout='',stderr='Error: No Such Container: '+cid)
    value=m.owned_absence(observations,runner=runner)
    assert value['all_owned_containers_absent'] and len(value['owned'])==1
    assert queries==[['docker','info','--format','{{.ServerVersion}}'],['docker','inspect','--type','container',cid]]
    assert not any('rm' in argv or 'prune' in argv for argv in queries)


@pytest.mark.parametrize('returncode,stderr',[(0,''),(1,'daemon unreachable'),(1,'no such object: wrong-id')])
def test_present_or_unknown_container_is_not_success(tmp_path,returncode,stderr):
    cid='b'*64;path=tmp_path/'observation.json'
    path.write_text(json.dumps({'container':{'Id':cid},'queried_container_id':cid,'trial_name':'owned','role':'verifier'}))
    def runner(argv,**kwargs):
        return SimpleNamespace(returncode=0,stdout='28',stderr='') if argv[1]=='info' else SimpleNamespace(returncode=returncode,stderr=stderr)
    with pytest.raises(ValueError):m.owned_absence([{'passed':True,'complete':True,'observations':[m.reference(path)]}],runner=runner)


def test_dataset_manifest_requires_exact20_and_both10(tmp_path):
    dataset=tmp_path/'SpreadsheetEval';dataset.mkdir()
    value={'task_count':19,'tasks':[],'selected_task_ids':[],'counts_by_mode':{}}
    (dataset/'dataset_manifest.json').write_text(json.dumps(value))
    with pytest.raises(ValueError,match='twenty'):m.dataset_inventory(tmp_path)


def test_timestamp_name_and_default_oracle_omitted_by_real_serializer(tmp_path):
    jobs=tmp_path/'jobs';job=jobs/'2026-11-01__04-42-00';job.mkdir(parents=True)
    value=config(tmp_path);value.pop('job_name');assert 'agents' not in value
    (job/'config.json').write_text(json.dumps(value))
    assert m._new_job(jobs,set(),'oracle',tmp_path)==job
    with pytest.raises(ValueError):m._new_job(jobs,set(),'nop',tmp_path)


def test_real_nop_config_is_explicit_and_accepted(tmp_path):
    jobs=tmp_path/'jobs';job=jobs/'one-new-job';job.mkdir(parents=True)
    value=config(tmp_path,'nop');assert value['agents'][0]['name']=='nop'
    (job/'config.json').write_text(json.dumps(value))
    assert m._new_job(jobs,set(),'nop',tmp_path)==job


@pytest.mark.parametrize('resource_passes',[True,False])
def test_role_runner_exact_command_inherited_env_whole20_and_resource_failure(tmp_path,monkeypatch,resource_passes):
    root=tmp_path/'repo';root.mkdir();out=root/'outputs/run';out.mkdir(parents=True)
    jobs=root/'jobs';job=jobs/'owned';job.mkdir(parents=True);(job/'result.json').write_text('{}')
    observation=out/'observer.json';observation.write_text('{}')
    manifest=root/'manifest.json';manifest.write_text('{}');inventory={'manifest':m.reference(manifest)}
    called=[];validated=[]
    class Observer:
        def __init__(self,*args):self.receipt=m.reference(observation);self.owned_job=job;self.finalization_error=None
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def poll_once(self):pass
    class Audit:
        def update_run(self,**kwargs):pass
        def export(self):pass
    def popen(argv,**kwargs):
        called.append((argv,kwargs));return SimpleNamespace(pid=1234,returncode=0,poll=lambda:0)
    whole={'status':'passed','counts':{'dataset_tasks':20,'trial_results':20,'matched_rewards':20,'exceptions':0,'missing':0,'unknown':0,'duplicates':0},
           'trials':[{'result_file':str(job/('task'+str(i))/'result.json'),'task_id':'task'+str(i)} for i in range(20)]}
    monkeypatch.setattr(m,'OwnedJobObserver',Observer);monkeypatch.setattr(m,'dataset_inventory',lambda _:inventory)
    monkeypatch.setattr(m,'auditor',lambda:lambda *args,**kwargs:whole)
    monkeypatch.setattr(m,'owned_absence',lambda values:{'all_owned_containers_absent':True})
    def validate(config,result,**kwargs):
        validated.append((config,result,kwargs));return {'passed':resource_passes,'complete':resource_passes}
    monkeypatch.setattr(m,'validate_trial_observations',validate)
    monkeypatch.setenv('ROOT_CONTROL_TEST_SENTINEL','retained');monkeypatch.setenv('PATH','/usr/bin')
    if resource_passes:
        receipt=m._run_role(root,out,'oracle',inventory,Audit(),popen=popen)
        record=m.read(receipt['path'])
        assert record['argv']==m.COMMANDS['oracle'] and record['qualification_claimed'] is False
        assert len(validated)==20
    else:
        with pytest.raises(ValueError,match='CPU/RAM/image'):m._run_role(root,out,'oracle',inventory,Audit(),popen=popen)
        assert not (out/'oracle_command_receipt.json').exists()
    assert called[0][0]==['harbor','run','-p','SpreadsheetEval','-a','oracle']
    assert called[0][1]['cwd']==root
    assert called[0][1]['env']['PATH']==str(root/'.venv312/bin')+':/usr/bin'
    assert called[0][1]['env']['ROOT_CONTROL_TEST_SENTINEL']=='retained'

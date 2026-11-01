import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT=Path(__file__).resolve().parents[1]
loader=importlib.util.spec_from_file_location('factory_finish_test',ROOT/'scripts/finish_operating_reports_factory_batch.py')
m=importlib.util.module_from_spec(loader);loader.loader.exec_module(m)


class Audit:
    def __init__(self,*args):self.rows=[];self.db=SimpleNamespace(close=lambda:None)
    def snapshot(self):return {}
    def events(self):return []
    def update_run(self,**kwargs):self.rows.append(kwargs)
    def task(self,*args,**kwargs):self.rows.append(kwargs)
    def record(self,*args):return 1
    def update_record(self,*args):pass
    def export(self):pass


def test_confirmation_exact_phase_whole20_and_controls_command(tmp_path):
    ids=['task'+str(i) for i in range(20)];batches=[tmp_path/'FM.json',tmp_path/'DBG.json']
    commands=m.commands(tmp_path/'dev.json',batches,ids,tmp_path,20)
    argv=commands['confirmation']
    assert argv[:3]==[str(ROOT/'.venv312/bin/python'),str(m.HELPERS['frontier']),'prepare']
    assert argv[argv.index('--phase')+1]=='confirmation' and '--run' in argv
    assert argv.count('--task-id')==20 and argv.count('--batch')==2
    assert argv[argv.index('--concurrency')+1]=='20'
    assert commands['root_controls']==[str(ROOT/'.venv312/bin/python'),str(m.HELPERS['controls']),'--output',str(tmp_path/'root_controls')]


def test_child_failure_waits_healthy_sibling_without_termination_retry_or_restart(tmp_path,monkeypatch):
    audit=Audit();calls=[];sleeps=[]
    class Process:
        def __init__(self,name):self.name=name;self.pid=1 if name=='failed' else 2;self.n=0;self.returncode=1 if name=='failed' else None
        def poll(self):
            self.n+=1
            if self.name=='healthy' and self.n>=5:self.returncode=0
            return self.returncode
        def terminate(self):raise AssertionError('Do not cancel a healthy child')
        def kill(self):raise AssertionError('Do not kill a healthy child')
    def popen(argv,**kwargs):calls.append(argv);return Process(argv[0])
    monkeypatch.setattr(m.time,'sleep',lambda seconds:sleeps.append(seconds))
    ticks=iter(range(100));monkeypatch.setattr(m.time,'monotonic',lambda:next(ticks))
    with pytest.raises(ValueError,match='child failed'):
        m.parallel({'confirmation':['failed'],'root_controls':['healthy']},tmp_path,audit,popen=popen)
    assert calls==[['failed'],['healthy']] and sleeps
    assert (tmp_path/'confirmation_launched.json').is_file() and (tmp_path/'root_controls_launched.json').is_file()
    assert any(r.get('status')=='running' for r in audit.rows) and any(r.get('status')=='completed' for r in audit.rows)
    finished=[r['duration_ms'] for r in audit.rows if r.get('node')=='confirmation' and r.get('status')=='failed']
    assert len(finished)>1 and len(set(finished))==1  # A finished sibling's duration stays frozen.


def test_second_spawn_error_does_not_cancel_first_or_restart(tmp_path,monkeypatch):
    audit=Audit();calls=[]
    process=SimpleNamespace(pid=1,returncode=0,poll=lambda:0)
    def popen(argv,**kwargs):
        calls.append(argv)
        if len(calls)==2:raise OSError('spawn failed')
        return process
    with pytest.raises(OSError,match='spawn failed'):
        m.parallel({'confirmation':['first'],'root_controls':['second']},tmp_path,audit,popen=popen)
    assert len(calls)==2


def test_dashboard_projection_uses_child_phase_and_links(tmp_path):
    child=tmp_path/'confirmation';(child/'execution_monitor').mkdir(parents=True)
    (child/'execution_monitor/dashboard.json').write_text(json.dumps({'dashboard_url':'http://127.0.0.1:1234'}))
    (child/'started.json').write_text('{}')
    assert m.child_status('confirmation',tmp_path)=={'phase':'native_confirmation','dashboard_urls':['http://127.0.0.1:1234']}
    (child/'terminal.json').write_text('{}');assert m.child_status('confirmation',tmp_path)['phase']=='terminal'


@pytest.fixture
def workflow(tmp_path,monkeypatch):
    root=tmp_path/'repo';root.mkdir();monkeypatch.setattr(m,'ROOT',root)
    events=[];audit=Audit()
    class Server:
        def __init__(self,*args,**kwargs):pass
        def start(self):events.append('early_UI');return 'http://127.0.0.1:1111'
        def stop(self):events.append('UI_stopped')
    monkeypatch.setattr(m,'AuditStore',lambda *args,**kwargs:(Path(args[0]).mkdir(parents=True),audit)[1])
    monkeypatch.setattr(m,'DashboardServer',Server)
    dev=root/'dev.json';dev.write_text(json.dumps({'kind':'operating_reports_factory_frontier_terminal_v6','phase':'development','outer_retries':0}))
    batches=[root/'FM.json',root/'DBG.json']
    for b in batches:b.write_text(json.dumps({'tasks':[{}]*20}))
    joins=[root/'FM_join.json',root/'DBG_join.json']
    for j in joins:j.write_text('{}')
    out=root/'outputs/finish'
    def freeze(development,case_batches,directory,destination):
        assert events[0]=='early_UI';events.append('freeze');destination.mkdir()
        directory.mkdir(parents=True);path=directory/'cohort_frozen.json'
        path.write_text(json.dumps({'count':20,'development':m.ref(dev),'selected_task_ids':['t'+str(i) for i in range(20)]}))
        return m.ref(path)
    def parallel(commands,output,store,**kwargs):
        events.append('parallel')
        for name in ('confirmation','root_controls'):
            child=output/name;child.mkdir();(child/'terminal.json').write_text('{}')
    def quality(*args):events.append('quality');return {'passed':True}
    def finalize(*args):events.append('finalize');return {'path':str(args[-1]),'sha256':'a'*64,'bytes':1}
    helpers={'freeze':SimpleNamespace(freeze=freeze),'quality':SimpleNamespace(build=quality),'finalize':SimpleNamespace(finalize=finalize)}
    monkeypatch.setattr(m,'load',lambda name:helpers[name]);monkeypatch.setattr(m,'parallel',parallel)
    return root,dev,batches,joins,out,events,helpers


def test_complete_mocked_followthrough_early_UI_freeze_parallel_quality_then_finalizer(workflow):
    root,dev,batches,joins,out,events,_=workflow
    result=m.finish(dev,batches,*joins,out,dataset_root=root/'SpreadsheetEval')
    assert events==['early_UI','freeze','parallel','quality','finalize','UI_stopped']
    terminal=m.read(result['path']);assert terminal['passed'] and terminal['outer_retries']==0
    assert terminal['README_or_git_publication_changed'] is False
    assert terminal['release']['path']==str(root/'reports/operating_report_factory_release.json')
    with pytest.raises(ValueError,match='fresh'):m.finish(dev,batches,*joins,out,dataset_root=root/'SpreadsheetEval')


def test_failed_quality_is_saved_and_finalizer_never_runs(workflow):
    root,dev,batches,joins,out,events,helpers=workflow
    helpers['quality'].build=lambda *args:{'passed':False,'failure':{'reason':'one unknown'}}
    with pytest.raises(ValueError,match='quality evidence'):m.finish(dev,batches,*joins,out,dataset_root=root/'SpreadsheetEval')
    assert m.read(out/'quality.json')['passed'] is False
    assert (out/'failure.json').is_file() and 'finalize' not in events


@pytest.mark.parametrize('field,value',[('phase','confirmation'),('outer_retries',1),('kind','foreign')])
def test_wrong_development_protocol_rejects_before_freeze(workflow,field,value):
    root,dev,batches,joins,out,events,_=workflow
    record=m.read(dev);record[field]=value;dev.write_text(json.dumps(record))
    with pytest.raises(ValueError,match='genuine development'):m.finish(dev,batches,*joins,out,dataset_root=root/'SpreadsheetEval')
    assert 'freeze' not in events and (out/'failure.json').is_file()


def test_no_arbitrary_dataset_or_confirmation_concurrency(workflow):
    root,dev,batches,joins,out,events,_=workflow
    with pytest.raises(ValueError,match='repository root'):m.finish(dev,batches,*joins,out,dataset_root=root/'another')
    with pytest.raises(ValueError,match='twenty'):m.finish(dev,batches,*joins,out,confirmation_concurrency=19,dataset_root=root/'SpreadsheetEval')
    assert not out.exists()


def test_waits_existing_producer_artifact_without_starting_a_model(tmp_path,monkeypatch):
    target=tmp_path/'future.json';sleeps=[];audit=Audit()
    def sleep(seconds):sleeps.append(seconds);target.write_text('{}')
    monkeypatch.setattr(m.time,'sleep',sleep)
    assert m.wait_file(target,audit,'wait_existing')['path']==str(target)
    assert len(sleeps)==1 and audit.rows[0]['stage']=='wait_existing'


def test_live_usage_projection_does_not_reimport_calls_or_double_add_cache(tmp_path):
    from sheets_factory.core.audit import AuditStore
    audit=AuditStore(tmp_path/'child',{'status':'running'})
    audit.record('calls',{'input_tokens':100,'output_tokens':7,'cached_input_tokens':80})
    audit.record('calls',{'input_tokens':None,'output_tokens':None,'cached_input_tokens':None})
    audit.task('t',status='running')
    path=tmp_path/'child/run.sqlite'
    a=m.child_summary({'development':path});b=m.child_summary({'development':path})
    assert a==b
    assert a['known_totals']=={'input_tokens':100,'output_tokens':7,'cached_input_tokens':80,
        'llm_calls':2,'unknown_usage_calls':1,'total_tokens':107}
    master=SimpleNamespace(snapshot=lambda:{'run':{'child_summary':a,'candidate_count':40},'metrics':{'llm_calls':0}})
    assert m.master_snapshot(master)['metrics']['total_tokens']==107
    assert m.master_snapshot(master)['metrics']['candidates']==40
    assert audit.db.execute('SELECT COUNT(*) FROM calls').fetchone()[0]==2
    audit.db.close()

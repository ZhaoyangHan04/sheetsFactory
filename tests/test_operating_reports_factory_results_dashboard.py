import importlib.util
import json
from pathlib import Path
import sqlite3
import pytest

PATH = Path(__file__).resolve().parents[1] / 'scripts/serve_operating_reports_factory_results.py'
spec=importlib.util.spec_from_file_location('factory_readonly_panel_test',PATH)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def write(p,z):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(z));return p


def ref(p):
    return m.Reader().read(p)[1]


def calls(p,n):
    p.parent.mkdir(parents=True,exist_ok=True);c=sqlite3.connect(p)
    c.execute('CREATE TABLE calls(id TEXT PRIMARY KEY,payload TEXT)')
    for i in range(n):c.execute('INSERT INTO calls VALUES(?,?)',(str(i),json.dumps({'input_tokens':100,'output_tokens':10,'cached_input_tokens':80,'model':'actual_model','status':'completed'})))
    c.commit();c.close()


@pytest.fixture
def data(tmp_path):
    dev_eval=write(tmp_path/'dev/evaluation.json',{});conf_eval=write(tmp_path/'conf/evaluation.json',{})
    calls(dev_eval.parent/'run.sqlite',40);calls(conf_eval.parent/'run.sqlite',20)
    rows=[];final=[];failure=[]
    for i in range(20):
        mode='financial_modeling'if i<10 else'debugging';ident=f'task{i}'
        row={'task_id':ident,'mode':mode,'score':{'raw_verifier_reward':0,'effective_reward':None if i==0 else 0,'state':'unknown'if i==0 else'complete'},'actual_attempt':{'tool_time':{'cumulative_tool_seconds':None if i==0 else 60,'state':'unknown'if i==0 else'verified'}},'resources':{'passed':True}}
        rows.append(row);final.append({'task_id':ident,'mode':mode,'reward':0,'tool_seconds':None if i==0 else 60,'tool_lower_seconds':'107.856734627'if i==0 else None,'tool_upper_seconds':'126.614143299'if i==0 else None})
        failure.append({'task_id':ident,'pattern':'boundary_only','missing_count':0,'extra_count':0,'wrong_value_count':2,'boundary_only':True,'wrong_fields':{'yoy_percent':1,'qoq_percent':1}})
    dev=write(tmp_path/'development.json',{'phase':'development','results':rows*2,'evaluation':ref(dev_eval)})
    conf=write(tmp_path/'confirmation.json',{'phase':'confirmation','results':rows,'evaluation':ref(conf_eval)})
    summary=write(tmp_path/'failure_summary.json',{'evidence':{'confirmation':ref(conf)},'rows':failure})
    cohort=write(tmp_path/'cohort.json',{'development':ref(dev)})
    control=write(tmp_path/'controls.json',{'passed':True,'oracle_all20_reward':1,'nop_all20_reward':0,'actual_role_resources_checked':True})
    semantic=[]
    for i in range(2):
        p=write(tmp_path/f'normal{i}/terminal.json',{'usage':{'llm_calls':2}});calls(p.parent/'run.sqlite',2);semantic.append(ref(p))
    quality=write(tmp_path/'quality.json',{'shared_semantic_reviews':semantic})
    release=write(tmp_path/'release.json',{'kind':'qualified_operating_report_factory_release','qualified':True,'task_count':20,'tasks':final,'confirmation':ref(conf),'cohort':ref(cohort),'quality':ref(quality),'controls':ref(control),'current_batch_model_calls':64,'current_batch_known_total_tokens':7040})
    return release,dev,conf,summary


def test_true_qualified_release_displays_40_20_ten_each_and_exact_usage(data):
    z=m.ResultView(*data).snapshot()
    assert z['run']['qualified']==20 and z['run']['financial_modeling']==z['run']['debugging']==10
    assert z['metrics']['candidates']==40 and z['metrics']['candidate_conversion']==0.5
    assert z['metrics']['llm_calls']==64 and len(z['llm_calls'])==64
    assert z['metrics']['input_tokens']==6400 and z['metrics']['output_tokens']==640
    assert z['metrics']['total_tokens']==7040 and z['metrics']['cached_input_tokens']==5120
    assert z['metrics']['usage_matches_qualified_release'] is True
    assert z['actual_root_controls']=={'oracle_tasks':20,'oracle_reward':1,'nop_tasks':20,'nop_reward':0,'resources_checked':True}
    assert z['actual_confirmation_raw_zero_count']==20


@pytest.mark.parametrize('qualified',[False,None,'true',1])
def test_only_literal_true_qualified_flag_admits_twenty(data,qualified):
    p=data[0];z=json.loads(p.read_text());z['qualified']=qualified;write(p,z)
    v=m.ResultView(*data).snapshot()
    assert v['run']['qualified']==0 and all(t['status']=='evidence_pending'for t in v['tasks'])


def test_missing_release_has_no_placeholder_qualification(data):
    data[0].unlink();z=m.ResultView(*data).snapshot()
    assert z['run']['qualified']==0 and z['metrics']['llm_calls']==60


def test_original_unknown_and_final_supplement_bounds_are_both_visible(data):
    z=m.ResultView(*data).snapshot();r=z['tasks'][0]
    assert z['original_confirmation_effective_counts']=={'unknown':1,'0':19}
    assert r['original_effective_reward'] is None and r['release_reward']==0
    assert '[107.857, 126.614]'in r['reason'] and '原v6 UNKNOWN保留'in r['reason']
    assert r['wrong_fields']=={'yoy_percent':1,'qoq_percent':1}


@pytest.mark.parametrize('which',['confirmation','cohort','summary'])
def test_wrong_final_dependency_binding_rejected(data,which):
    if which=='summary':
        p=data[3];z=json.loads(p.read_text());z['evidence']['confirmation']['sha256']='0'*64;write(p,z)
    else:
        p=data[0];z=json.loads(p.read_text());z[which]['sha256']='0'*64;write(p,z)
    with pytest.raises(ValueError):m.ResultView(*data).snapshot()


def test_snapshot_reads_never_update_artifacts_or_audit_databases(data):
    root=data[0].parent;before={p:p.read_bytes()for p in root.rglob('*')if p.is_file()}
    view=m.ResultView(*data);view.snapshot();view.snapshot()
    assert {p:p.read_bytes()for p in before}==before
    assert view.events(100)==[]


def test_cache_invalidates_changed_release_instead_of_retaining_qualified(data):
    view=m.ResultView(*data);assert view.snapshot()['run']['qualified']==20
    z=json.loads(data[0].read_text());z['qualified']=False;write(data[0],z)
    assert view.snapshot()['run']['qualified']==0

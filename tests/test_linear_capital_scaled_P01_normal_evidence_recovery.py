"""Synthetic stored-run tests; no original-case certification or native calls."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tests'))
from test_reference_evidence_policy import context as reference_context, diagnose


def entry():
    spec = importlib.util.spec_from_file_location('_test_P01_append_only_recovery', ROOT/'scripts/recover_linear_capital_scaled_P01_normal_evidence.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module


def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(value)+'\n')


def tree(path):
    return {str(p.relative_to(path)):p.read_bytes() for p in path.rglob('*') if p.is_file()}


@pytest.fixture
def stored(tmp_path,monkeypatch):
    from dirhash import dirhash
    from sheets_factory.evaluation.resource_harbor import export_resource_harbor, inspect_resource_export
    m = entry(); run = tmp_path/'old_closed_run'; monkeypatch.setattr(m,'RUN',run)
    observer = run/'resource_observations/fixture/receipt.json'
    put(observer,{'observations':[],'observation_errors':[]}); observer_ref = m.reference(observer)
    jobs = run/'harbor_jobs'/m.BATCH; staging = run/'harbor_batches'/m.BATCH/'SpreadsheetEval'
    tasks=[]; bindings={}; summary={}; trials=[]; contexts=[]; task_reports=[]
    for index,task_id in enumerate(m.TASKS):
        ctx=reference_context.__wrapped__(tmp_path/('context_'+str(index)))
        ctx.task_id=task_id; ctx.mode='financial_modeling' if index==0 else 'debugging'
        destination=run/'tasks'/task_id; destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.move(str(ctx.directory),destination); ctx.directory=destination
        ctx.data.update(input=ctx.revision_dir/'public/input.xlsx',goal=ctx.revision_dir/'private/goal.xlsx')
        ctx.data['instruction']+=' Save the completed workbook to /app/output.xlsx.'
        (ctx.revision_dir/'public/instruction.md').write_text(ctx.data['instruction'])
        ctx.data['revision_hash']=m.hashlib.sha256(ctx.data['input'].read_bytes()+ctx.data['instruction'].encode()).hexdigest()
        diagnose(ctx); contexts.append(ctx)
        quarantine=run/'quarantined_exports'/(task_id+'-resource-observation')
        export_resource_harbor(ctx.revision_dir,quarantine,{'task_id':task_id,'revision':0,
            'revision_hash':ctx.data['revision_hash']},runtime_profile=m.strict_entry().pipeline.PROFILE)
        staged=staging/task_id; shutil.copytree(quarantine,staged); binding=inspect_resource_export(staged)
        bindings[binding['task_name']]=binding; controls={}
        for agent,reward in [('oracle',1),('nop',0)]:
            directory=jobs/(agent+'-job')/(task_id+'__trial')
            thin={'task':{'path':str(staged),'source':'SpreadsheetEval'},'trial_name':directory.name,
                'trials_dir':str(directory.parent),'job_id':agent+'-job-id'}
            rich={**deepcopy(thin),'agent':{'name':agent}}
            if agent=='nop': thin['agent']={'name':'nop'}
            result={'config':rich,'trial_name':directory.name,'task_name':binding['task_name'],
                'agent_info':{'name':agent},'exception_info':None,'verifier_result':{'rewards':{'reward':reward}},
                'task_checksum':dirhash(staged,'sha256')}
            put(directory/'config.json',thin);put(directory/'result.json',result)
            controls[agent]={'task_name':binding['task_name'],'matched':True,'reward':reward,
                'exception_info':None,'result_file':str(directory/'result.json')}
            trials.append({'task_name':binding['task_name'],'agent':agent,'original_result':m.reference(directory/'result.json'),
                'original_sparse_config':m.reference(directory/'config.json')})
        summary[binding['task_name']]=controls
        report=run/'private/actual_control_resources'/(task_id+'.json')
        put(report,{'task_id':task_id,'passed':False,'error':"'agent'",'trials':[],'observer':observer_ref})
        task_reports.append(m.reference(report))
        tasks.append({'id':task_id,'mode':ctx.mode,'revision':0,'status':'infrastructure_failed','node':'actual_control_resources',
            'error':"'agent'",'harbor_controls':None,'harbor_export_binding':None,'historical_harbor_controls':controls,
            'historical_harbor_export_binding':binding,'harbor_summary_path':str(jobs/'control_summary.json')})
    put(jobs/'control_summary.json',{'per_task':summary})
    put(staging.parent/'batch_manifest.json',{'complete':True,'errors':[],'task_ids':list(m.TASKS),
        'staging':str(staging),'jobs_dir':str(jobs),'export_bindings':bindings})
    put(run/'normal_actual_control_resource_gate.json',{'passed':False,'qualified_tasks_checked':2,
        'infrastructure_task_ids':list(m.TASKS),'observer':observer_ref,'task_validations':task_reports})
    (run/'resolved_config.yaml').write_text(yaml.safe_dump(contexts[0].config))
    db=sqlite3.connect(run/'run.sqlite');db.execute('CREATE TABLE tasks(id TEXT PRIMARY KEY,payload TEXT)')
    db.executemany('INSERT INTO tasks VALUES (?,?)',[(t['id'],json.dumps(t)) for t in tasks]);db.commit();db.close()
    diagnostic=tmp_path/'original_resource_diagnostic.json'
    put(diagnostic,{'original_resource_observer':observer_ref,'trials':trials})
    anchors={str(p.relative_to(run)):m.reference(p) for p in [run/'run.sqlite',run/'normal_actual_control_resource_gate.json',
        run/'resolved_config.yaml',staging.parent/'batch_manifest.json',jobs/'control_summary.json',
        *(ctx.revision_dir/'private/diagnosis.json' for ctx in contexts)]}
    proposal=tmp_path/'approved_proposal.json';put(proposal,{'original_run':str(run),'anchors':anchors,
        'actual_resource_diagnostic':m.reference(diagnostic)})
    monkeypatch.setattr(m,'PROPOSAL',m.reference(proposal))
    calls=[]
    def observe(config,result,**kwargs):
        calls.append((config,result,kwargs));return {'passed':True,'complete':True,'roles_observed':['agent','verifier']}
    monkeypatch.setattr(m,'validate_trial_observations',observe)
    return m,run,tasks,contexts,calls


def test_full_two_mode_recovery_rechecks_review_exports_and_all_four_resources_without_old_writes(stored,tmp_path):
    m,run,tasks,contexts,calls=stored;before=tree(run);out=tmp_path/'new_certificate'
    frozen=m.prepare(out);assert m.reference(frozen['path'])==frozen and not calls
    certificate=m.certify(out);result=json.loads(Path(certificate['path']).read_text())
    assert result['evidence_recovered'] is True and result['qualified'] is result['formal_release'] is False
    assert result['new_calls']=={'model':0,'LO':0,'Harbor':0,'Docker':0}
    assert len(result['tasks'])==2 and len(calls)==4
    assert all(row['review']['reference_review']['verified'] for row in result['tasks'])
    assert all(row['review']['states']['Q08']=='not_applicable' for row in result['tasks'])
    assert all(len(row['identical_original_exports'])==17 for row in result['tasks'])
    assert result['original_statuses_changed'] is result['quarantined_exports_moved_or_copied'] is False
    assert tree(run)==before
    accessed={row['reference']['path'] for row in result['read_only_access_inventory']}
    for ctx in contexts:
        assert str(ctx.revision_dir/'private/diagnosis.json') in accessed
        assert str(ctx.revision_dir/'private/goal.xlsx') in accessed
        assert str(next(ctx.revision_dir.glob('diagnostic_private-*'))/'evidence.json') in accessed
    with pytest.raises(ValueError,match='first certificate'):m.certify(out)


@pytest.mark.parametrize('field',['input','goal','instruction','context','Q04_receipt','diagnostic_reference'])
def test_real_unchanged_reporter_rejects_stale_or_unsupported_material(stored,field):
    m,_,tasks,contexts,_=stored;ctx=contexts[0];base=ctx.revision_dir
    if field=='input':(base/'public/input.xlsx').write_bytes(b'changed')
    elif field=='goal':(base/'private/goal.xlsx').write_bytes(b'changed')
    elif field=='instruction':(base/'public/instruction.md').write_text('another business policy')
    elif field=='context':put(base/'private/reference_evidence_context.json',{})
    elif field=='Q04_receipt':
        p=base/'private/diagnosis.json';v=json.loads(p.read_text());v['assessments']['Q04']['evidence']=[];put(p,v)
    else:(next(base.glob('diagnostic_private-*'))/'reference.xlsx').write_bytes(b'changed')
    with pytest.raises(ValueError,match='all-twelve'):m._review(tasks[0],contexts[0].config,m.Access())


@pytest.mark.parametrize('fault',['other_failure','other_status','missing_task','missing_observer','resource_incomplete',
    'wrong_reward','wrong_agent','wrong_job','staged_change','quarantine_change','review_goal'])
def test_recovery_never_accepts_another_failure_or_incomplete_proof(stored,tmp_path,monkeypatch,fault):
    m,run,tasks,contexts,calls=stored;frozen=m._proposal();access=m.Access()
    if fault=='other_failure':
        p=run/'private/actual_control_resources'/(m.TASKS[0]+'.json');v=json.loads(p.read_text());v['error']='different';put(p,v)
    elif fault in ('other_status','missing_task'):
        db=sqlite3.connect(run/'run.sqlite')
        if fault=='missing_task':db.execute('DELETE FROM tasks WHERE id=?',(m.TASKS[0],))
        else:
            t=deepcopy(tasks[0]);t['status']='qualified';db.execute('UPDATE tasks SET payload=? WHERE id=?',(json.dumps(t),t['id']))
        db.commit();db.close()
    elif fault=='missing_observer':
        p=run/'resource_observations/fixture/receipt.json';p.unlink()
    elif fault=='resource_incomplete':monkeypatch.setattr(m,'validate_trial_observations',lambda *a,**k:{'passed':False,'complete':False})
    elif fault in ('wrong_reward','wrong_agent','wrong_job'):
        p=Path(tasks[0]['historical_harbor_controls']['oracle']['result_file']);v=json.loads(p.read_text())
        if fault=='wrong_reward':v['verifier_result']['rewards']['reward']=0
        elif fault=='wrong_agent':v['agent_info']['name']='nop'
        else:v['config']['job_id']='another'
        put(p,v)
    elif fault=='staged_change':(run/'harbor_batches'/m.BATCH/'SpreadsheetEval'/m.TASKS[0]/'instruction.md').write_text('changed')
    elif fault=='quarantine_change':(run/'quarantined_exports'/(m.TASKS[0]+'-resource-observation')/'instruction.md').write_text('changed')
    else:(contexts[0].revision_dir/'private/goal.xlsx').write_bytes(b'changed')
    # Bypass only the already-tested prospective anchor layer to exercise each
    # deeper recovery requirement using genuine file checks and reporter code.
    data={'resource_diagnostic':frozen['actual_resource_diagnostic']}
    before=tree(run)
    with pytest.raises((ValueError,OSError)):m._recover(data,access)
    assert tree(run)==before


def test_frozen_prepare_detects_drift_and_cannot_write_original_run(stored,tmp_path):
    m,run,_,_,calls=stored
    with pytest.raises(ValueError,match='never write'):m.prepare(run/'new')
    out=tmp_path/'prepared';m.prepare(out)
    with pytest.raises(ValueError,match='previous recovery'):m.prepare(out)
    (run/'resolved_config.yaml').write_text('changed: true')
    with pytest.raises(ValueError,match='artifact changed'):m.validate_prepared(out)
    assert not calls and not (out/'started.json').exists()


def test_failed_certificate_is_preserved_and_never_resampled(stored,tmp_path,monkeypatch):
    m,run,_,_,calls=stored;out=tmp_path/'prepared';m.prepare(out);before=tree(run)
    monkeypatch.setattr(m,'_recover',lambda *args:(_ for _ in ()).throw(ValueError('concrete retained failure')))
    with pytest.raises(ValueError,match='concrete retained'):m.certify(out)
    assert (out/'failure.json').exists() and not (out/'certificate.json').exists()
    with pytest.raises(ValueError,match='first certificate'):m.certify(out)
    assert tree(run)==before and not calls


def test_CLI_starts_existing_monitor_before_prepare_or_certification(tmp_path,monkeypatch):
    from contextlib import contextmanager
    m=entry();seen=[]
    @contextmanager
    def monitor(*args):
        seen.append('monitor started');yield {};seen.append('monitor stopped')
    monkeypatch.setattr(m,'strict_entry',lambda: type('E',(),{'admission_monitor':staticmethod(monitor)})())
    monkeypatch.setattr(m,'prepare',lambda p: seen.append('cold prepare') or {'prepared':True})
    assert m.main(['--output',str(tmp_path/'fresh')])==0
    assert seen==['monitor started','cold prepare','monitor stopped']
    with pytest.raises(ValueError,match='separate certification'):m.main(['--output',str(tmp_path/'fresh'),'--certify'])


def test_CLI_rejects_old_run_before_even_starting_the_outer_monitor(stored,monkeypatch):
    m,run,_,_,_=stored;before=tree(run)
    monkeypatch.setattr(m,'strict_entry',lambda:pytest.fail('No monitor or helper import may precede old-path rejection'))
    with pytest.raises(ValueError,match='never write'):m.main(['--output',str(run/'forbidden_new_folder')])
    assert tree(run)==before

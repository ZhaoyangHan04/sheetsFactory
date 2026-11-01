from contextlib import contextmanager
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import json
import pytest

ROOT=Path(__file__).resolve().parents[1]
def load():
    s=importlib.util.spec_from_file_location('_five_pair_review_test',ROOT/'scripts/run_ringfenced_shared_quality_review.py')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def test_every_assigned_check_is_kept_and_public_prompt_has_no_answer():
    m=load()
    for mode in m._N['MODES']:
        for role in ('public','reference'):
            text=m.prompt(mode,role)
            ids=json.loads(text.split('assigned_check_ids=')[-1])
            assert ids==(m._N['PUBLIC'] if role=='public' else m._N['PRIVATE'])
            assert 'R2-01' in text and 'R2-05' in text
            assert 'do not solve or submit' in text.lower()
            assert 'Q08' in text if role=='public' else 'Q05' in text
    assert set(m._N['PUBLIC'])|set(m._N['PRIVATE'])=={f'Q{i:02d}' for i in range(1,13)}


def test_ordinary_model_lifecycle_and_budget_are_not_changed():
    m=load()
    assert m._N['PROFILE']==m.PROFILE
    import ast
    tree=ast.parse(Path(m.BASE).read_text())
    run=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='run')
    text=ast.unparse(run)
    assert 'gpt-6-sol' in text and '720' in text
    assert 'gpt-6.1-sol' not in text
    assert 'max_workers=4' in text and 'outer_retries' in text
    assert 'actual_five_ringfenced_pairs_shared_quality_review_v1' in m._N['run'].__code__.co_consts


def make_toy_cohort(m,tmp_path):
    tasks=[];batches=[]
    def w(name,value):return m.write(tmp_path/name,value)
    donor_source=w('donor_source.json', {key:w(key+'.json',{'complete':True}) for key in
        ('independent_A_expected','independent_B_expected','geometry','stability') }|
        {'financial_audits':[w('donor_audit.json',{'passed':True})]})
    donor_ref=w('donor_ref.json',{'passed':True})
    for i in range(1,6):
        pair=f'R2-{i:02d}'
        cert=w(pair+'cert.json',{'private_winner':'DO_NOT_EXPOSE'})
        sf=w(pair+'sf.json',{'certificate':cert,'public_contract':w(pair+'policy.json',{'mandates':[{'local_profile_id':'L360-P01'}]}),
            'donors':[{'source_manifest':donor_source,'reference':donor_ref}],**{key:w(pair+key+'.json',{'passed':True})
                for key in ('local_composition','report_plan','report_expected','cold_audit')}})
        source=w(pair+'source.json',{'preparation':sf,'records':{'source1_audit':w(pair+'audit.json',{'passed':True})}})
        pairtasks=[]
        for mode,suf in [('financial_modeling','FM'),('debugging','DBG')]:
            d=tmp_path/pair/mode
            for n,v in [('environment/input.xlsx',b'PUBLIC_INPUT'),('tests/reference.xlsx',b'PRIVATE_GOAL'),('instruction.md',b'PUBLIC_BRIEF')]:
                p=d/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(v)
            t={'task_id':pair+suf,'variant_id':pair+'-'+suf,'mode':mode,'task_directory':str(d),
                'individual_engineering':w(pair+suf+'engineering.json',{'passed':True,'complete_primary_difference':['x!A1']}),
                'plan_freeze':w(pair+suf+'plan.json',{'private_fault':'HIDDEN'})}
            tasks.append(t);pairtasks.append(t)
        batches.append(w(pair+'batch.json',{'tasks':pairtasks,'selected_task_ids':[t['task_id'] for t in pairtasks],'source':source}))
    fake=SimpleNamespace(cohort_tasks=lambda values:(batches,tasks,{'retained':True}),
                         p=SimpleNamespace(_N={'check_task':lambda task:None}))
    return batches,fake


def test_all_five_public_cases_are_isolated_from_all_private_maps(monkeypatch,tmp_path):
    m=load();batches,fake=make_toy_cohort(m,tmp_path/'evidence')
    monkeypatch.setattr(m,'load',lambda *a:fake)
    result=m.read(m._prepare(batches,tmp_path/'review'))
    assert result['model_calls_started']==0 and result['model_calls_permitted']==4
    assert len(result['tasks'])==10 and result['all_five_pairs_in_both_role_views'] is True
    for mode in m._N['MODES']:
        public=tmp_path/'review/workspaces'/mode/'public'
        files=list(public.rglob('*'));assert len([p for p in files if p.is_file()])==10
        assert {p.parent.name for p in files if p.name=='input.xlsx'}=={f'R2-{i:02d}' for i in range(1,6)}
        assert all(b'PRIVATE' not in p.read_bytes() and b'HIDDEN' not in p.read_bytes() for p in files if p.is_file())
        reference=tmp_path/'review/workspaces'/mode/'reference'
        assert len(list(reference.rglob('reference.xlsx')))==5
        assert len(list(reference.rglob('independent_A_expected.private.json')))==1
        assert len(list(reference.rglob('independent_B_expected.private.json')))==1
    assert result['outer_retries']==0 and result['whole_family_qualified'] is False


def test_panel_starts_before_any_frozen_case_admission(monkeypatch,tmp_path):
    m=load();events=[]
    @contextmanager
    def monitor(*args):
        events.append('panel');yield SimpleNamespace(update_run=lambda **k:None)
    fake=SimpleNamespace(p=SimpleNamespace(_N={'monitor':monitor}))
    monkeypatch.setattr(m,'load',lambda *a:fake)
    monkeypatch.setattr(m,'_prepare',lambda *a:events.append('admission') or {'prepared':True})
    assert m.prepare([],tmp_path/'review')=={'prepared':True}
    assert events==['panel','admission']


def test_review_dependency_change_is_rejected_before_workspace_write(monkeypatch,tmp_path):
    m=load();monkeypatch.setattr(m,'ENTRY_SHA','0'*64)
    with pytest.raises(ValueError,match='dependency changed'):m.prepare([],tmp_path/'review')
    assert not (tmp_path/'review').exists()

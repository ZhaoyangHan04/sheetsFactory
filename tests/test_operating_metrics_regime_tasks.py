"""Task8 pure construction and mocked lifecycle; never source admission or LO."""
import importlib.util
from pathlib import Path
import shutil

import openpyxl
import pytest

from sheets_factory.workbook.operating_metrics_regime import excel

ROOT=Path(__file__).resolve().parents[1]


def module():
    description=importlib.util.spec_from_file_location('_test_operating_tasks',ROOT/'scripts/validate_operating_metrics_regime_tasks.py')
    m=importlib.util.module_from_spec(description);description.loader.exec_module(m);return m


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    m=module();candidate=excel.build_views(tmp_path/'candidate')
    source_ref=m.source.prepare(candidate,tmp_path/'source');sf=m.read(source_ref);goal=m.read(candidate)['goal']
    # Deliberate test-only admission substitute; production validates all three actual receipts.
    mocked=m.write(tmp_path/'mock_source_terminal.json',{'kind':'independently_checked_operating_metrics_regime_source','version':1,
        'passed':True,'preparation':source_ref,'source':goal,'specification_sha256':sf['specification_sha256'],
        'actual_calls':[{'output':goal}],'test_only_no_actual_native_calls':True})
    monkeypatch.setattr(m.source,'validate_source',lambda value:m.read(value))
    lineage={k:m.write(tmp_path/(k+'.mock.json'),{'test_only_no_actual_native_calls':True}) for k in ('source_manifest','failure_audit','owned_cleanup')}
    lineage['model_score_inferred']=False
    monkeypatch.setattr(m,'prior_source_failure',lambda _:lineage)
    out=tmp_path/'tasks';ref=m.prepare(mocked,out)
    return m,out,m.read(ref),candidate,mocked


def grid(path):
    book=openpyxl.load_workbook(path,data_only=False)
    try:return {(s.title,c.coordinate):c.value for s in book for c in s._cells.values() if c.value is not None}
    finally:book.close()


def test_prepare_only_freezes_complete_roles_and_no_actual_start(prepared):
    m,out,f,_,_=prepared
    assert m.validate_prepared(out)==f
    assert f['kind']==m.KIND and f['actual_LO_calls']==f['model_calls']==0
    assert f['required_actual_LO_calls']==8 and len(f['planned_inputs'])==6
    assert f['stage_order']==['FM_input1','FM_input2','DBG_input1','DBG_input2','equivalent','FM_missed_root','DBG_missed_root','extra_change']
    assert f['independent_business_field_count']==2052 and f['financial_target_count']==1368
    assert not (out/'started.json').exists()
    assert m.execute_prepared.__globals__ is m._ns


def test_fm_retains_599_historical_formulas_and_85_literal_na(prepared):
    m,_,f,_,_=prepared;definition=m.read(f['definition'])
    book=openpyxl.load_workbook(f['planned_inputs']['FM_input']['path'],data_only=False)
    try:
        assert sum(c.data_type=='f' for s in book for c in s._cells.values())==599
        assert sum(c.value=='n/a (no comparative)' for s in book for c in s._cells.values())==85
        for point in definition['FM_mask_points']:
            sheet,cell=point.rsplit('!',1);assert book[sheet][cell].value is None
    finally:book.close()
    m.verify_definitions(f['planned_inputs']['FM_input']['path'],definition,blank=True)


def test_dbg_retains_exact_four_original_families_and_all_given_literals(prepared):
    m,_,f,_,_=prepared;binding=m.read(f['bindings']);original=grid(f['genuine_goal']['path']);dbg=grid(f['planned_inputs']['DBG_input']['path'])
    roots=binding['DBG_root_edits']
    assert len(roots)==4 and {r['mechanism'] for r in roots}=={'associate_sign','growth_ratio_without_minus_one','money_unit','wrong_comparison_quarter'}
    assert {p for p in original if original.get(p)!=dbg.get(p)}=={(r['sheet'],r['cell']) for r in roots}
    assert m.read(f['DBG_definition'])['literals']==m.read(f['definition'])['literals']
    for r in roots:assert dbg[r['sheet'],r['cell']]==r['after']


def test_correct_instruction_bytes_missed_root_and_outside_extra(prepared):
    m,_,f,candidate,_=prepared;raw=m.read(candidate)
    for mode,r in f['instruction_bytes'].items():assert Path(r['path']).read_bytes()==Path(raw['views'][mode]['instruction']['path']).read_bytes()
    root=f['exact_edits']['FM_missed_root']['edits']
    assert len(root)==1 and root[0]['kind']=='blank'
    point=root[0]['sheet']+'!'+root[0]['cell'];assert m.read(f['expected'])[point]=={'type':'number','value':'27.75'}
    extra=f['exact_edits']['extra_change']['edits'];assert extra[0]['sheet']=='Read Me' and extra[0]['cell']=='A1'
    assert 'Read Me!A1' not in m.read(f['expected'])


def test_typed_input_guards_accept_history_na_boolean_and_reject_coercion(prepared,tmp_path):
    m,_,f,_,_=prepared;definition=m.read(f['definition']);expected=m.read(f['expected'])
    edits={}
    for point in definition['FM_mask_points']:
        sheet,cell=point.rsplit('!',1);edits.setdefault(sheet,{})[cell]=excel._blank
    fm=tmp_path/'fm_cached_history.xlsx';excel._rewrite(f['genuine_goal']['path'],fm,edits)
    m.verify_input_caches(fm,expected,blank=True,definition=definition)
    m.verify_input_caches(f['genuine_goal']['path'],expected,blank=False,definition=definition)
    binding=next(r for r in m.read(f['bindings'])['bindings'] if r['key']=='ALDER/FY2027/distribution_eligible')
    def numeric(cell):cell.set('t','n');cell.find('{*}v').text='1'
    bad=tmp_path/'numeric_boolean.xlsx';excel._rewrite(f['genuine_goal']['path'],bad,{binding['sheet']:{binding['cell']:numeric}})
    with pytest.raises(ValueError):m.verify_input_caches(bad,expected,blank=False,definition=definition)
    with pytest.raises(ValueError):m.verify_input_caches(f['planned_inputs']['FM_input']['path'],expected,blank=True,definition=definition)


def test_primary_compare_is_unchanged_all_numeric_two_decimals(prepared,tmp_path):
    m,_,_,_,_=prepared
    def book(name,value,rate,boolean=False):
        b=openpyxl.Workbook();s=b.active;s['A1']=value;s['B1']=rate;s['C1']=boolean;p=tmp_path/name;b.save(p);b.close();return p
    inp=book('input.xlsx',1,.04);goal=book('goal.xlsx',2,.04)
    equivalent=book('equiv.xlsx',2,.041)
    assert m.compare_complete(inp,goal,equivalent,set())['reward']==1
    extra=book('extra.xlsx',2,1.04)
    assert m.compare_complete(inp,goal,extra,set())['reward']==0
    numeric=book('wrongtype.xlsx',2,.04,0)
    assert m.compare_complete(inp,goal,numeric,set())['reward']==0


def test_old_family_and_scope_mutation_are_rejected(prepared,tmp_path,monkeypatch):
    m,out,f,_,mocked=prepared
    with pytest.raises(ValueError):m.prepare(mocked,out)
    original=m.read(mocked);original['kind']='independently_checked_equity_income_group_iterative_source'
    wrong=m.write(tmp_path/'old_family.json',original)
    with pytest.raises(ValueError):m.prepare(wrong,tmp_path/'old_task')
    expected=m.read(f['definition']);expected['FM_mask_points']=expected['FM_mask_points'][:-1]
    with pytest.raises(ValueError):m.verify_definitions(f['planned_inputs']['FM_input']['path'],expected,blank=True)


def services(monkeypatch,m,f,*,fail_at=None):
    calls=[];receipts=[]
    class Engine:
        def __init__(self,*args,**kwargs):pass
        def ensure_image(self):pass
        def recalculate(self,original,output):
            calls.append(m.reference(original))
            if len(calls)==fail_at:raise RuntimeError('test-only native failure')
            shutil.copyfile(f['genuine_goal']['path'],output)
            receipts.append(m.write(Path(output).with_suffix('.mockresource.json'),{'source':m.reference(original),'container_id':f'{len(calls):064x}'}))
            return output
        def metadata(self):return {'actual_resource_receipts':receipts}
    class Server:
        def __init__(self,*args,**kwargs):pass
        def start(self):return 'test://no-network'
        def stop(self):pass
    def validate(call,record,freeze):return {'container_id':m.read(record)['container_id'],'terminal':record}
    def absence(actual):return {'all_owned_containers_absent':True,'daemon_reachable':True,'owned':[{'full_id':c['actual_resource_evidence']['container_id'],'absent':True} for c in actual]}
    def compare(inp,goal,output,_):
        name=Path(output).name;reward=int(str(output)==str(goal) or name=='equivalent.xlsx')
        return {'reward':reward,'reason':'test-only lifecycle score fixture','expected_change_count':1368,'actual_change_count':1368,'missing_changes':[],'extra_changes':[],'wrong_values':[]}
    monkeypatch.setitem(m._ns,'ThreadCappedResourceLibreOfficeEngine',Engine);monkeypatch.setitem(m._ns,'DashboardServer',Server)
    monkeypatch.setitem(m._ns,'verify_definitions',lambda *a,**k:None);monkeypatch.setitem(m._ns,'verify_input_caches',lambda *a,**k:None)
    monkeypatch.setitem(m._ns,'compare_complete',compare)
    monkeypatch.setattr(m.source,'validate_call',validate);monkeypatch.setattr(m.source,'owned_absence',absence)
    return calls


def test_mocked_eight_call_sequence_cold_validation_and_no_retry(prepared,monkeypatch):
    m,out,f,_,_=prepared;calls=services(monkeypatch,m,f)
    terminal=m.execute_prepared(out);t=m.validate_completed(terminal)
    assert t['kind']==m.TERMINAL_KIND and t['actual_LO_calls_started']==t['actual_LO_calls_completed']==len(calls)==8
    assert calls[0]==f['planned_inputs']['FM_input'] and calls[2]==f['planned_inputs']['DBG_input']
    assert t['records']['modes']['financial_modeling']['controls']=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}
    assert t['qualified'] is t['normal_all12_QA_passed'] is t['difficulty_claimed'] is False
    with pytest.raises(ValueError):m.execute_prepared(out)


def test_mocked_failure_keeps_terminal_and_stops_remaining_calls(prepared,monkeypatch):
    m,out,f,_,_=prepared;calls=services(monkeypatch,m,f,fail_at=3)
    with pytest.raises(RuntimeError):m.execute_prepared(out)
    t=m.read(out/'terminal.json')
    assert t['passed'] is False and len(calls)==3 and t['actual_LO_calls_completed']==2
    assert (out/'failure.json').exists() and t['retry']==0
    with pytest.raises(ValueError):m.validate_completed(out/'terminal.json')

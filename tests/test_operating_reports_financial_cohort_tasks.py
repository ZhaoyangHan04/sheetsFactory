from contextlib import contextmanager
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile, ZIP_DEFLATED
import xml.etree.ElementTree as ET

from openpyxl import Workbook, load_workbook
import pytest

ROOT=Path(__file__).resolve().parents[1]


def module():
    path=ROOT/'scripts/validate_operating_reports_financial_cohort_tasks.py'
    loader=importlib.util.spec_from_file_location('_cohort_FM_task_test',path)
    m=importlib.util.module_from_spec(loader);loader.loader.exec_module(m);return m


def cached(source,destination,expected):
    """Unit artifact builder, not financial evaluation or native evidence."""
    ns='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    with ZipFile(source) as zin,ZipFile(destination,'x',ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            raw=zin.read(item.filename)
            if item.filename=='xl/worksheets/sheet2.xml':
                tree=ET.fromstring(raw)
                for cell in tree.iter(ns+'c'):
                    point='Report!'+cell.get('r')
                    if cell.find(ns+'f') is None:continue
                    for old in list(cell):
                        if old.tag==ns+'v':cell.remove(old)
                    value=expected[point]
                    if value['type']=='boolean':cell.set('t','b');text='1' if value['value'] else '0'
                    else:cell.attrib.pop('t',None);text=value['value']
                    ET.SubElement(cell,ns+'v').text=text
                raw=ET.tostring(tree)
            zout.writestr(item,raw)


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    m=module();book=Workbook();book.active.title='ReadMe';book.active['A1']='Toy public policy'
    report=book.create_sheet('Report')
    for cell,value in {'A1':'Historical sales','B1':'=10','A2':'Forecast sales','B2':'=20',
        'A3':'Forecast portfolio sales','B3':'=20','A4':'Forecast distribution eligibility','B4':'=FALSE()',
        'A5':'Unavailable comparative','B5':'n/a (no comparative)'}.items():report[cell]=value
    report['B4'].number_format='General';seed=tmp_path/'seed.xlsx';book.save(seed);book.close()
    expected={'Report!B1':{'type':'number','value':'10'},'Report!B2':{'type':'number','value':'20'},
        'Report!B3':{'type':'number','value':'20'},'Report!B4':{'type':'boolean','value':False},
        'Report!B5':{'type':'text','value':'n/a (no comparative)'}}
    goal=tmp_path/'source3.xlsx';cached(seed,goal,expected)
    points=[('E001/2025Q1/revenue','number'),('E001/2026Q1/revenue','number'),
        ('PORTFOLIO/2026Q1/revenue','number'),('E001/FY2027/distribution_eligible','boolean'),('E001/2025Q1/yoy_percent','text')]
    rows={key:{'sheet':'Report','cell':'B'+str(i),'role':'given_NA' if kind=='text' else 'report'}
        for i,(key,kind) in enumerate(points,1)}
    bindings=m.write(tmp_path/'bindings.json',{'financial':rows})
    mask=[key for key,kind in points if kind!='text' and key.split('/')[1].startswith(('2026','FY2027'))]
    plans=m.write(tmp_path/'view_plans.json',{'FM_mask':mask})
    brief=tmp_path/'instruction.md';brief.write_text('Complete the forecast reports. Preserve history and supplied facts.\n')
    public=m.write(tmp_path/'public.json',{'seed':202711201,'dimension_mode':'toy'})
    candidate=m.write(tmp_path/'candidate.json',{'kind':'prepared_unverified_operating_reports_financial_cohort_fm_emission',
        'version':1,'candidate_id':'FM-C01','view_plans':plans,'views':{'financial_modeling':{'instruction':m.reference(brief)}}})
    wb=load_workbook(goal);native=m.base.source
    definition={'sheetnames':wb.sheetnames,'formulas':{s.title+'!'+c.coordinate:c.value for s in wb for c in s._cells.values() if c.data_type=='f'},
        'literals':{s.title+'!'+c.coordinate:native.typed(c.value) for s in wb for c in s._cells.values() if c.value is not None and c.data_type!='f'}}
    wb.close();definition=m.write(tmp_path/'definition.json',definition);expected_ref=m.write(tmp_path/'expected.json',expected)
    runtime=m.write(tmp_path/'runtime.json',{'cpus':2,'memory_gib':32});inventory=m.write(tmp_path/'raw_inventory.json',{'case_id':'FM-C01'})
    sf={'candidate_manifest':candidate,'specification':public,'bindings':bindings,'definition':definition,'expected':expected_ref,
        'raw_inventory':inventory,'case_id':'FM-C01','runtime_profile':runtime,'runtime_profile_value':{'cpus':2,'memory_gib':32}}
    sf_ref=m.write(tmp_path/'source_preparation.json',sf)
    actual={'kind':m.SOURCE_KIND,'version':1,'passed':True,'preparation':sf_ref,'source':m.reference(goal),'actual_calls':[{'output':m.reference(goal)}]}
    manifest=m.write(tmp_path/'source_manifest.json',actual);cold=[];calls=[];fake=SimpleNamespace(**vars(native))
    fake.SOURCE_KIND=m.SOURCE_KIND
    fake.schema=SimpleNamespace(points=lambda p:iter(points),validate_spec=lambda p:p,
        candidate=lambda seed:{'candidate_id':'FM-C01'} if seed==202711201 else (_ for _ in ()).throw(ValueError('unknown case')))
    fake.validate_source=lambda value:(cold.append(value) or deepcopy(actual))
    fake.validate_prepared=lambda output:deepcopy(sf)
    fake.recipes=lambda:{manifest['path']:manifest}
    fake._formula_cache_count=lambda path:sum(c.find('{*}f') is not None and c.find('{*}v') is not None
        for name,data in _xml_parts(path) for c in ET.fromstring(data).iter('{*}c'))
    fake.now=lambda:'2026-11-01T00:00:00+00:00'
    @contextmanager
    def stage(*args,**kwargs):yield
    fake.stage=stage
    class Audit:
        def __init__(self,*args,**kwargs):self.db=SimpleNamespace(close=lambda:None)
        def update_run(self,**kwargs):pass
        def export(self):pass
        def snapshot(self):return {}
        def events(self,*args):return []
    class Dashboard:
        def __init__(self,*args,**kwargs):pass
        def start(self):return 'http://unit.invalid/'
        def stop(self):pass
    class Lease:
        def __init__(self,*args):pass
        def acquire(self):return self
        def release(self):pass
    class Engine:
        def __init__(self,*args,receipt_directory,**kwargs):self.receipts=[];self.folder=receipt_directory;self.folder.mkdir()
        def ensure_image(self):pass
        def recalculate(self,original,output):
            cached(original,output,expected);index=len(self.receipts)+1;calls.append(str(output))
            self.receipts.append(m.write(self.folder/(str(index)+'.json'),{'container_id':format(index,'064x')}));return output
        def metadata(self):return {'actual_resource_receipts':self.receipts}
    fake.AuditStore,fake.DashboardServer,fake.ProducerLease,fake.ThreadCappedResourceLibreOfficeEngine=Audit,Dashboard,Lease,Engine
    fake.validate_call=lambda call,record,f:{'terminal':record,'container_id':m.read(record)['container_id']}
    fake.owned_absence=lambda calls:{'all_owned_containers_absent':True,'daemon_reachable':True,
        'owned':[{'full_id':c['actual_resource_evidence']['container_id'],'absent':True} for c in calls]}
    fake.compare_typed=lambda *args:{'passed':True}
    def activate():
        m.source=fake;m._N.update(source=fake,AuditStore=Audit,DashboardServer=Dashboard,ProducerLease=Lease,
            ThreadCappedResourceLibreOfficeEngine=Engine);return fake
    monkeypatch.setattr(m,'_activate',activate)
    monkeypatch.setattr(m,'COUNTS',{'business':5,'formulas':4,'forecast':3,'NA':1})
    return m,tmp_path,manifest,actual,sf,expected,cold,calls,fake


def _xml_parts(path):
    with ZipFile(path) as z:
        return [(name,z.read(name)) for name in z.namelist() if name.startswith('xl/worksheets/sheet') and name.endswith('.xml')]


def test_prepare_freezes_only_FM_and_all_four_plans_without_services(prepared):
    m,p,manifest,_,_,_,cold,calls,_=prepared;f=m.read(m.prepare(manifest,p/'task'))
    assert cold==[manifest] and calls==[]
    assert f['mode_order']==['financial_modeling'] and f['stage_order']==list(m.STAGES)
    assert f['required_actual_LO_calls']==5 and set(f['planned_inputs'])=={'FM_input','equivalent','FM_missed_root','extra_change'}
    assert f['financial_target_count']==3 and f['formula_count']==4 and f['report_NA_count']==1
    assert f['historical_formula_count']==1 and f['independent_business_field_count']==5
    assert f['actual_LO_calls']==f['new_financial_forwards']==f['model_calls']==0
    assert m.validate_prepared(p/'task')==f


def test_real_generic_full_D_five_controls_and_five_owned_calls_with_mock_engine(prepared):
    m,p,manifest,_,_,_,cold,calls,_=prepared;m.prepare(manifest,p/'task')
    t=m.read(m.execute_prepared(p/'task'))
    assert t['kind']==m.TERMINAL_KIND and t['passed'] and len(calls)==5
    assert t['actual_LO_calls_started']==t['actual_LO_calls_completed']==5
    assert set(t['records']['modes'])=={'financial_modeling'}
    mode=t['records']['modes']['financial_modeling']
    assert mode['complete_D_count']==3 and mode['controls']=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}
    assert m.validate_completed(p/'task/terminal.json')==t
    assert m._N['compare_complete'].__code__ is m.base.compare_complete.__code__
    assert len(cold)==3 and t['qualified'] is False and t['difficulty_claimed'] is False
    with pytest.raises(ValueError,match='No retries'):m.execute_prepared(p/'task')
    assert len(calls)==5


def test_genuine_source_rejection_not_a_passed_JSON_header(prepared):
    m,p,manifest,_,_,_,_,calls,fake=prepared
    def reject(*args):raise ValueError('genuine source proof unavailable')
    fake.validate_source=reject
    with pytest.raises(ValueError,match='genuine source proof'):m.prepare(manifest,p/'task')
    assert calls==[] and not (p/'task').exists()


def test_foreign_source_family_rejected_before_any_plans(prepared):
    m,p,manifest,actual,_,_,_,_,fake=prepared;wrong=deepcopy(actual);wrong['kind']='independently_checked_old_case'
    fake.validate_source=lambda value:wrong
    with pytest.raises(ValueError,match='genuine completed'):m.prepare(manifest,p/'task')
    assert not (p/'task').exists()


def test_forecast_history_NA_and_input_typed_checks(prepared,monkeypatch):
    m,p,manifest,_,_,expected,_,_,_=prepared;f=m.read(m.prepare(manifest,p/'task'));d=m.read(f['definition'])
    wb=load_workbook(f['planned_inputs']['FM_input']['path'])
    try:
        assert wb['Report']['B1'].value=='=10' and wb['Report']['B5'].value=='n/a (no comparative)'
        assert all(wb['Report'][c].value is None for c in ('B2','B3','B4'))
    finally:wb.close()
    retained={k:v for k,v in expected.items() if k not in d['FM_mask_points']}
    monkeypatch.setitem(m._N,'snapshot',lambda *args:{'values':retained})
    m.verify_input_caches(None,expected,blank=True,definition=d)
    wrong=deepcopy(retained);wrong['Report!B5']={'type':'text','value':'changed'}
    monkeypatch.setitem(m._N,'snapshot',lambda *args:{'values':wrong})
    with pytest.raises(ValueError,match='historical/NA'):m.verify_input_caches(None,expected,blank=True,definition=d)
    wrong=deepcopy(retained);wrong['Report!B2']=expected['Report!B2']
    monkeypatch.setitem(m._N,'snapshot',lambda *args:{'values':wrong})
    with pytest.raises(ValueError,match='forecast cache'):m.verify_input_caches(None,expected,blank=True,definition=d)


def test_no_mode_scope_case_or_control_changes(prepared):
    m,p,manifest,_,_,_,_,_,_=prepared;f=m.read(m.prepare(manifest,p/'task'))
    for key,value in [('case_id','FM-C02'),('forecast_mask_count',2),('required_actual_LO_calls',8)]:
        bad={**f,key:value};(p/'task/preparation.json').write_text(json.dumps(bad))
        with pytest.raises(ValueError):m.validate_prepared(p/'task')
    (p/'task/preparation.json').write_text(json.dumps(f))
    bad=deepcopy(f);bad['control_target']['semantic_key']='not-a-target';(p/'task/preparation.json').write_text(json.dumps(bad))
    with pytest.raises(ValueError,match='control target'):m.validate_prepared(p/'task')


def test_source_pin_pending_and_exact_counted_AST_removal():
    m=module()
    assert m.ADAPTATION_COUNTS=={'stability':1,'mode':2,'DBG_branch':2,'DBG_read':2,'cache':2,'calls':3,'previous':1,'initial':1,'title':1}
    assert m._N['_execute_prepared_FM'].__globals__ is m._N
    assert m._N['_validate_completed_FM'].__globals__ is m._N
    if m.SOURCE_SHA=='PENDING_COHORT_SOURCE_PIN':
        with pytest.raises(ValueError,match='pinned'):m.prepare({'passed':True},ROOT/'outputs/unspent_cohort_test')
    else:
        support=m._activate()
        assert support.SOURCE_KIND==m.SOURCE_KIND and m._N['source'] is support
        assert support.recipes()[str(m.SOURCE_SCRIPT)]['sha256']==m.SOURCE_SHA
        for name in ('_book','typed','formula_signature','_formula_cache_count','validate_source','validate_call','owned_absence'):
            assert callable(getattr(support,name))


def test_CLI_cannot_prepare_and_run_in_one_call(prepared):
    m,p,_,_,_,_,_,calls,_=prepared
    with pytest.raises(ValueError,match='separate actual run'):
        m.main(['--source-manifest',str(p/'source_manifest.json'),'--output',str(p/'task'),'--run'])
    assert calls==[] and not (p/'task').exists()


def test_actual_resource_failure_stops_first_call_and_retains_failure(prepared):
    m,p,manifest,_,_,_,_,calls,fake=prepared;m.prepare(manifest,p/'task')
    def reject(*args):raise ValueError('actual resource evidence unavailable')
    fake.validate_call=reject
    with pytest.raises(RuntimeError,match='preserve original terminal'):m.execute_prepared(p/'task')
    terminal=m.read(p/'task/terminal.json')
    assert terminal['passed'] is False and len(calls)==1 and terminal['qualified'] is False
    assert terminal['failure']['message']=='actual resource evidence unavailable'
    assert (p/'task/FM_input1.xlsx').exists()
    with pytest.raises(ValueError):m.validate_completed(p/'task/terminal.json')


def test_owned_cleanup_failure_cannot_become_a_completed_admission(prepared):
    m,p,manifest,_,_,_,_,calls,fake=prepared;m.prepare(manifest,p/'task')
    fake.owned_absence=lambda calls:{'all_owned_containers_absent':False,'daemon_reachable':True,'owned':[]}
    with pytest.raises(RuntimeError,match='preserve original terminal'):m.execute_prepared(p/'task')
    terminal=m.read(p/'task/terminal.json')
    assert len(calls)==5 and terminal['passed'] is False and terminal['qualified'] is False
    assert 'cleanup' in terminal['failure']['message'].lower()

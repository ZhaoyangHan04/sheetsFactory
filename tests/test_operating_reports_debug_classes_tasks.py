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
    path=ROOT/'scripts/validate_operating_reports_debug_classes_tasks.py'
    loader=importlib.util.spec_from_file_location('_whole_class_DBG_test',path)
    m=importlib.util.module_from_spec(loader);loader.loader.exec_module(m);return m


def cached(original,output,*,error=False):
    """Fixture cache transport, never native or business-finance evidence."""
    values={'10':('n','10'),'5':('n','5'),'-3':('n','-3'),'0.1':('n','0.1'),
        'FALSE()':('b','0'),'0-5':('n','-5'),'0-(-3)':('n','3'),'1.1':('n','1.1'),
        '0+(5)':('n','5'),'0+(-3)':('n','-3')}
    ns='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    with ZipFile(original) as zin,ZipFile(output,'x',ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            raw=zin.read(item.filename)
            if item.filename=='xl/worksheets/sheet2.xml':
                tree=ET.fromstring(raw)
                for cell in tree.iter(ns+'c'):
                    f=cell.find(ns+'f')
                    if f is None:continue
                    kind,text=values[f.text]
                    if error and cell.get('r')=='B2':kind,text='e','#NUM!'
                    for old in list(cell):
                        if old.tag==ns+'v':cell.remove(old)
                    cell.set('t',kind);ET.SubElement(cell,ns+'v').text=text
                raw=ET.tostring(tree)
            zout.writestr(item,raw)


@pytest.fixture
def prepared(tmp_path,monkeypatch):
    m=module();book=Workbook();book.active.title='ReadMe';book.active['A1']='Toy public policy'
    report=book.create_sheet('Report')
    for cell,value in {'A1':'History','B1':'=10','A2':'Forecast associate profit','B2':'=5',
        'A3':'Forecast associate loss','B3':'=-3','A4':'Forecast growth','B4':'=0.1',
        'A5':'Unavailable comparison','B5':'n/a (no comparative)','A6':'Distribution eligibility','B6':'=FALSE()'}.items():report[cell]=value
    report['B6'].number_format='General';seed=tmp_path/'seed.xlsx';book.save(seed);book.close()
    goal=tmp_path/'source3.xlsx';cached(seed,goal)
    expected={f'Report!B{i}':value for i,value in enumerate([
        {'type':'number','value':'10.00'},{'type':'number','value':'5.00'},
        {'type':'number','value':'-3.00'},{'type':'number','value':'0.10'},
        {'type':'text','value':'n/a (no comparative)'},{'type':'boolean','value':False}],1)}
    keys=['E001/2025Q1/revenue','E001/2026Q1/reported_associate_line','E001/2026Q2/reported_associate_line',
        'E001/2026Q1/yoy_percent','E001/2025Q1/yoy_percent','E001/FY2027/distribution_eligible']
    rows={key:{'sheet':'Report','cell':'B'+str(i),'role':'given_NA' if i==5 else 'report'} for i,key in enumerate(keys,1)}
    bindings=m.write(tmp_path/'bindings.json',{'financial':rows})
    brief=tmp_path/'instruction.md';brief.write_text('Audit the forecast reports. Preserve supplied facts and history.\n')
    public=m.write(tmp_path/'public.json',{'TEST_ONLY':'toy'})
    candidate=m.write(tmp_path/'candidate.json',{'views':{'debugging':{'instruction':m.reference(brief)}},
        'historical_provenance':{'path':'/historical/code/no_longer_current.py','sha256':'0'*64,'bytes':1}})
    native=m.base.source;wb=load_workbook(goal)
    definition={'sheetnames':wb.sheetnames,'formulas':{s.title+'!'+c.coordinate:c.value for s in wb for c in s._cells.values() if c.data_type=='f'},
        'literals':{s.title+'!'+c.coordinate:native.typed(c.value) for s in wb for c in s._cells.values() if c.value is not None and c.data_type!='f'}}
    wb.close();definition_ref=m.write(tmp_path/'definition.json',definition);expected_ref=m.write(tmp_path/'expected.json',expected)
    runtime=m.write(tmp_path/'runtime.json',{'cpus':2,'memory_gib':32})
    sf={'candidate_manifest':candidate,'specification':public,'bindings':bindings,'definition':definition_ref,'expected':expected_ref,
        'runtime_profile':runtime,'runtime_profile_value':{'cpus':2,'memory_gib':32}}
    sf_ref=m.write(tmp_path/'source_preparation.json',sf)
    actual={'kind':m.SOURCE_KIND,'version':1,'passed':True,'preparation':sf_ref,'source':m.reference(goal),'actual_calls':[{'output':m.reference(goal)}]}
    manifest=m.write(tmp_path/'source_manifest.json',actual)
    plans={}
    for variant in ('S800','SG4000'):
        faults={keys[i-1]:{'family':'associate_presentation_sign' if i in (2,3) else 'ratio_as_quarterly_change',
            'sheet':'Report','cell':'B'+str(i),'healthy_formula':definition['formulas']['Report!B'+str(i)],
            'faulty_formula':{2:'=0-5',3:'=0-(-3)',4:'=1.1'}[i]} for i in ((2,3) if variant=='S800' else (2,3,4))}
        plans[variant]={'view_plans':m.write(tmp_path/(variant+'_plan.json'),{'variant_id':variant,'DBG_faults':faults}),
            'proof':m.write(tmp_path/(variant+'_proof.json'),{'all_roots_exact_nonzero_primary_impact':True})}
    envelope_value={'variant_order':['S800','SG4000'],'variants':plans,'lineage':{'source_manifest':manifest,
        'genuine_healthy_goal':actual['source'],'source_preparation':sf_ref,'original_candidate':candidate,
        'specification':public,'bindings':bindings,'healthy_definition':definition_ref}}
    envelope=m.write(tmp_path/'envelope.json',envelope_value)
    fake=SimpleNamespace(**vars(native));fake.SOURCE_KIND=m.SOURCE_KIND;cold=[];calls=[];events=[]
    fake.validate_source=lambda value:(cold.append(value) or deepcopy(actual))
    fake.validate_prepared=lambda out:deepcopy(sf)
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
        force_error=False
        def __init__(self,*args,receipt_directory,**kwargs):self.receipts=[];self.folder=receipt_directory;self.folder.mkdir()
        def ensure_image(self):pass
        def recalculate(self,original,output):
            cached(original,output,error=self.force_error);index=len(self.receipts)+1;calls.append(str(output))
            self.receipts.append(m.write(self.folder/(str(index)+'.json'),{'container_id':format(index,'064x'),'source':m.reference(original)}));return output
        def metadata(self):return {'actual_resource_receipts':self.receipts}
    fake.AuditStore,fake.DashboardServer,fake.ProducerLease,fake.ThreadCappedResourceLibreOfficeEngine=Audit,Dashboard,Lease,Engine
    fake.validate_call=lambda call,record,f:{'terminal':record,'container_id':m.read(record)['container_id']}
    fake.owned_absence=lambda calls:{'all_owned_containers_absent':True,'daemon_reachable':True,
        'owned':[{'full_id':c['actual_resource_evidence']['container_id'],'absent':True} for c in calls]}
    fake.compare_typed=lambda *args:{'passed':True}
    variants=SimpleNamespace(validate_frozen=lambda ref:deepcopy(m.read(ref)),recipes=lambda:{})
    def activate():
        m.source=fake;m.variants=variants;m._N.update(source=fake,AuditStore=Audit,DashboardServer=Dashboard,
            ProducerLease=Lease,ThreadCappedResourceLibreOfficeEngine=Engine);return fake,variants
    monkeypatch.setattr(m,'_activate',activate);monkeypatch.setattr(m,'ENVELOPE_SHA',envelope['sha256'])
    monkeypatch.setattr(m,'COUNTS',{'business':6,'formulas':5,'NA':1,'S800':2,'SG4000':3,'growth':1})
    return SimpleNamespace(m=m,p=tmp_path,envelope=envelope,source=fake,actual=actual,sf=sf,
        expected=expected,cold=cold,calls=calls,Engine=Engine,events=events)


def _xml_parts(path):
    with ZipFile(path) as z:return [(name,z.read(name)) for name in z.namelist() if name.startswith('xl/worksheets/sheet') and name.endswith('.xml')]


@pytest.mark.parametrize('variant,count',[('S800',2),('SG4000',3)])
def test_real_generic_five_controls_complete_D_with_mock_native_boundary(prepared,variant,count):
    f=prepared;m=f.m;out=f.p/'task';p=m.read(m.prepare(f.envelope,variant,out))
    assert f.calls==[] and f.cold==[m.read(f.envelope)['lineage']['source_manifest']]
    assert p['mode_order']==['debugging'] and p['required_actual_LO_calls']==5
    assert set(p['planned_inputs'])=={'DBG_input','equivalent','DBG_missed_root','extra_change'}
    assert p['new_source_LO_calls']==p['new_financial_forwards']==p['model_calls']==0
    assert m.validate_prepared(out)==p
    t=m.read(m.execute_prepared(out));assert t['passed'] and len(f.calls)==5
    assert set(t['records']['modes'])=={'debugging'}
    mode=t['records']['modes']['debugging']
    assert mode['complete_D_count']==count and mode['controls']=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}
    assert m.validate_completed(out/'terminal.json')==t and len(f.cold)==3
    assert t['source_LO_calls_reused']==3 and t['qualified'] is t['normal_all12_QA_passed'] is t['difficulty_claimed'] is False
    assert m._N['compare_complete'].__code__ is m.base.compare_complete.__code__
    with pytest.raises(ValueError,match='No retries'):m.execute_prepared(out)
    assert len(f.calls)==5


def test_exact_production_pins_and_private_counted_adaptation():
    m=module();s,v=m._activate()
    assert m.ENVELOPE_SHA=='de584267929f5d9f3d7abd71efb566a97b69aa191f7814266f6fd7a6eee5b95b'
    assert m.reference(m.SOURCE_SCRIPT)['sha256']==m.SOURCE_SHA
    assert m.reference(m.DESIGN)['sha256']==m.DESIGN_SHA and v.__file__==str(m.DESIGN)
    assert s.SOURCE_KIND==m.SOURCE_KIND
    assert m.ADAPTATION_COUNTS=={'stability':1,'mode':2,'FM_branch':2,'cache':2,'calls':3,'previous':1,'initial':1,'title':1,'D':1,'cleanup':2}
    assert m._N['_execute_prepared_DBG'].__globals__ is m._N
    assert m._N['_validate_completed_DBG'].__globals__ is m._N
    assert m.base.STAGES==('FM_input1','FM_input2','DBG_input1','DBG_input2','equivalent','FM_missed_root','DBG_missed_root','extra_change')


@pytest.mark.parametrize('count,variant,ok',[(800,'S800',True),(4000,'SG4000',True),(799,'S800',False),
    (4001,'SG4000',False),(3999,'SG4000',False),(True,'S800',False),(0,'SG4000',False)])
def test_both_variants_require_exact_complete_D(count,variant,ok):
    assert module()._actual_D_policy({'variant_id':variant},count) is ok


@pytest.mark.parametrize('problem',['envelope','genuine_source','source_kind','source_goal','partial_roots'])
def test_reject_before_any_workbook_allocation_or_native(prepared,problem):
    f=prepared;m=f.m
    if problem=='envelope':m.ENVELOPE_SHA='0'*64
    elif problem=='genuine_source':
        def reject(*args):raise ValueError('genuine proof unavailable')
        f.source.validate_source=reject
    elif problem=='source_kind':f.actual['kind']='foreign source'
    elif problem=='source_goal':f.actual['source']={**f.actual['source'],'sha256':'0'*64}
    else:
        e=m.read(f.envelope);plan=m.read(e['variants']['S800']['view_plans']);plan['DBG_faults'].pop(next(iter(plan['DBG_faults'])))
        e['variants']['S800']['view_plans']=m.write(f.p/'partial_plan.json',plan)
        f.envelope=m.write(f.p/'partial_envelope.json',e);m.ENVELOPE_SHA=f.envelope['sha256']
    with pytest.raises(ValueError):m.prepare(f.envelope,'S800',f.p/'task')
    assert not (f.p/'task').exists() and f.calls==[]


def test_history_NA_facts_and_all_controls_preserved_and_missed_root_is_bad_formula(prepared):
    f=prepared;m=f.m;p=m.read(m.prepare(f.envelope,'S800',f.p/'task'))
    for name,row in p['planned_inputs'].items():
        book=load_workbook(row['path'])
        try:
            assert book['Report']['B1'].value=='=10' and book['Report']['B5'].value=='n/a (no comparative)'
            assert book['Report']['B6'].value=='=FALSE()' and book['Report']['B6'].number_format=='General'
            if name=='DBG_missed_root':
                assert book['Report']['B2'].value=='=0-5' and book['Report']['B3'].value=='=-3'
        finally:book.close()
        assert f.source._formula_cache_count(row['path'])==0
    assert p['control_target']['semantic_key']=='E001/2026Q1/reported_associate_line'


@pytest.mark.parametrize('problem',['native_error','missing_root','wrong_type'])
def test_input_native_cache_errors_or_missing_nonzero_root_reject(prepared,monkeypatch,problem):
    f=prepared;m=f.m;p=m.read(m.prepare(f.envelope,'S800',f.p/'task'));definition=m.read(p['definition'])
    values=deepcopy(f.expected);values['Report!B2']={'type':'number','value':'-5.00'};values['Report!B3']={'type':'number','value':'3.00'}
    if problem=='native_error':values['elsewhere!A1']={'type':'error','value':'#DIV/0!'}
    elif problem=='missing_root':values['Report!B3']=f.expected['Report!B3']
    else:values['Report!B5']={'type':'number','value':'0.00'}
    monkeypatch.setitem(m._N,'snapshot',lambda *args:{'values':values})
    with pytest.raises(ValueError):m.verify_input_caches(None,f.expected,blank=False,definition=definition)


@pytest.mark.parametrize('problem',['control_plan','root','calls','mode','mask','provided'])
def test_cold_preparation_rejects_modified_control_or_scope(prepared,problem):
    f=prepared;m=f.m;out=f.p/'task';p=m.read(m.prepare(f.envelope,'S800',out))
    if problem=='control_plan':p['exact_edits']['DBG_missed_root']['edits'][0]['kind']='blank'
    elif problem=='root':p['control_target']['cell']='B3'
    elif problem=='calls':p['required_actual_LO_calls']=8
    elif problem=='mode':p['mode_order']=['financial_modeling','debugging']
    elif problem=='mask':p['DBG_formula_root_count']=1
    else:
        book=load_workbook(p['planned_inputs']['equivalent']['path']);book['Report']['B5']='changed NA';changed=f.p/'changed.xlsx';book.save(changed);book.close()
        p['planned_inputs']['equivalent']=m.reference(changed)
        p['all_formula_cache_clearances']['equivalent']['output']=p['planned_inputs']['equivalent']
    (out/'preparation.json').write_text(json.dumps(p))
    with pytest.raises(ValueError):m.validate_prepared(out)


@pytest.mark.parametrize('problem',['resource','native_error','cleanup_unknown','cleanup_duplicate'])
def test_failure_stops_preserves_original_and_never_retries(prepared,problem):
    f=prepared;m=f.m;out=f.p/'task';m.prepare(f.envelope,'S800',out)
    if problem=='resource':
        def reject(*args):raise ValueError('actual resources unavailable')
        f.source.validate_call=reject
    elif problem=='native_error':f.Engine.force_error=True
    elif problem=='cleanup_unknown':f.source.owned_absence=lambda calls:{'all_owned_containers_absent':False,'daemon_reachable':True,'owned':[]}
    else:
        f.source.owned_absence=lambda calls:{'all_owned_containers_absent':True,'daemon_reachable':True,
            'owned':[{'full_id':'0'*64,'absent':True}]*5}
    with pytest.raises(RuntimeError,match='preserve original terminal'):m.execute_prepared(out)
    t=m.read(out/'terminal.json');assert not t['passed'] and len(f.calls)==(1 if problem in ('resource','native_error') else 5)
    assert t['qualified'] is False and t['failure']
    with pytest.raises(ValueError):m.validate_completed(out/'terminal.json')
    before=len(f.calls)
    with pytest.raises(ValueError,match='No retries'):m.execute_prepared(out)
    assert len(f.calls)==before


def test_CLI_panel_starts_before_slow_admission_and_prepare_cannot_run(prepared,monkeypatch):
    f=prepared;m=f.m;events=[]
    @contextmanager
    def monitor(*args):events.append('panel');yield;events.append('closed')
    monkeypatch.setattr(m,'admission_monitor',monitor)
    monkeypatch.setattr(m,'prepare',lambda *args:(events.append('cold') or {'TEST_ONLY':True}))
    assert m.main(['--envelope',f.envelope['path'],'--variant','S800','--output',str(f.p/'task')])==0
    assert events==['panel','cold','closed']
    with pytest.raises(ValueError,match='separate actual run'):
        m.main(['--envelope',f.envelope['path'],'--variant','S800','--output',str(f.p/'task'),'--run'])
    assert f.calls==[]


def test_completed_terminal_cannot_change_source_reuse_count_or_add_another_mode(prepared):
    f=prepared;m=f.m;out=f.p/'task';m.prepare(f.envelope,'S800',out)
    terminal=m.read(m.execute_prepared(out))
    for problem in ('source_reuse','mode'):
        changed=deepcopy(terminal)
        if problem=='source_reuse':changed['source_LO_calls_reused']=0
        else:changed['records']['modes']['financial_modeling']=deepcopy(changed['records']['modes']['debugging'])
        row=m.write(f.p/(problem+'.json'),changed)
        with pytest.raises(ValueError,match='selected DBG changed set'):m.validate_completed(row)


def test_cleanup_requires_five_distinct_case_normalized_full_owned_ids():
    m=module()
    ids=['a'*64,'A'*64]+[format(index,'064x') for index in (1,2,3)]
    calls=[{'actual_resource_evidence':{'container_id':cid}} for cid in ids]
    cleanup={'all_owned_containers_absent':True,'daemon_reachable':True,
        'owned':[{'full_id':cid,'absent':True} for cid in ids]}
    assert not m._owned_cleanup_ok(cleanup,calls)
    calls[1]['actual_resource_evidence']['container_id']='b'*64
    cleanup['owned'][1]['full_id']='B'*64
    assert m._owned_cleanup_ok(cleanup,calls)
    calls[0]['actual_resource_evidence']['container_id']=None
    assert not m._owned_cleanup_ok(cleanup,calls)

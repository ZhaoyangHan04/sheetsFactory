"""Toy physical workbooks and mocked source/native proofs; no actual services."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as X
from zipfile import ZipFile,ZIP_DEFLATED

import openpyxl
import pytest

ROOT=Path(__file__).resolve().parents[1]
NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'


@pytest.fixture
def m():
    spec=importlib.util.spec_from_file_location('_test_precision_v2_FM_task',ROOT/'scripts/validate_operating_reports_financial_cohort_tasks_revision2.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def store(m,path,value):return m.write(path,value)


def cache(source,destination,values):
    """TEST ONLY cached formula results; never an engine or source certificate."""
    with ZipFile(source)as old,ZipFile(destination,'x',ZIP_DEFLATED)as new:
        for item in old.infolist():
            body=old.read(item.filename)
            if item.filename=='xl/worksheets/sheet2.xml':
                tree=X.fromstring(body)
                for cell in tree.iter(NS+'c'):
                    if cell.find(NS+'f')is None:continue
                    for child in list(cell):
                        if child.tag in (NS+'v',NS+'is'):cell.remove(child)
                    wanted=values['Report!'+cell.attrib['r']];cell.set('t','b'if wanted['type']=='boolean'else'n')
                    X.SubElement(cell,NS+'v').text=('1'if wanted['value']else'0')if wanted['type']=='boolean'else wanted['value']
                body=X.tostring(tree)
            new.writestr(item,body)


@pytest.fixture
def sample(m,tmp_path,monkeypatch):
    actual_provider=m._activate();events=[]
    # A typing/layout fixture only, not a financial oracle or genuine source.
    keys=[('E001/2025Q4/net_income','number','A1'),('E001/FY2025/distribution_eligible','boolean','A2'),
        ('E001/2025Q4/yoy_percent','text','A3'),('E001/2026Q1/net_income','number','B1'),
        ('E001/FY2026/distribution_eligible','boolean','B2'),('E001/2026Q1/prior_year_multiple','text','B3')]
    independent={'Report!A1':{'type':'number','value':'-6290.87'},'Report!A2':{'type':'boolean','value':True},
        'Report!A3':{'type':'text','value':'n/a - prior period'},'Report!B1':{'type':'number','value':'14.52'},
        'Report!B2':{'type':'boolean','value':True},'Report!B3':{'type':'text','value':'n/a - provided'}}
    primary=deepcopy(independent);primary['Report!A1']['value']='-6290.86'
    counts={'business':6,'formulas':4,'forecast':2,'NA':2};monkeypatch.setattr(m,'COUNTS',counts);m._P['COUNTS']=counts
    book=openpyxl.Workbook();book.active.title='ReadMe';book['ReadMe']['A1']='TEST_ONLY supplied policy'
    sheet=book.create_sheet('Report')
    for point,formula in {'A1':'=-6290.865','A2':'=TRUE()','B1':'=14.52','B2':'=TRUE()'}.items():sheet[point]=formula
    sheet['A3']=primary['Report!A3']['value'];sheet['B3']=primary['Report!B3']['value'];book.calculation.iterate=False
    uncached=tmp_path/'TEST_ONLY_uncached.xlsx';book.save(uncached);book.close()
    goal=tmp_path/'TEST_ONLY_goal.xlsx';cache(uncached,goal,primary)
    formula_book=openpyxl.load_workbook(goal,data_only=False)
    definition={'sheetnames':formula_book.sheetnames,'formulas':{},'literals':{}}
    for ws in formula_book:
        for c in ws._cells.values():
            if c.value is None:continue
            point=ws.title+'!'+c.coordinate
            if c.data_type=='f':definition['formulas'][point]=c.value
            else:definition['literals'][point]=actual_provider.typed(c.value)
    formula_book.close()
    public={'seed':202711202,'TEST_ONLY':True};raw=store(m,tmp_path/'raw.json',public)
    bindings={'financial':{k:{'sheet':'Report','cell':cell}for k,kind,cell in keys}}
    plans=store(m,tmp_path/'plans.json',{'FM_mask':[keys[3][0],keys[4][0]]})
    brief=tmp_path/'brief.md';brief.write_bytes(b'TEST_ONLY business brief.\n')
    candidate=store(m,tmp_path/'candidate.json',{'kind':'prepared_unverified_operating_reports_financial_cohort_fm_emission',
        'version':1,'candidate_id':'FM-C02','view_plans':plans,'views':{'financial_modeling':{'instruction':m.reference(brief)}}})
    independent_ref=store(m,tmp_path/'independent_expected.json',independent)
    profile,profile_value=actual_provider.runtime(actual_provider.PROFILE)
    sf={'kind':actual_provider.KIND,'version':2,'case_id':'FM-C02','candidate_manifest':candidate,'specification':raw,
        'bindings':store(m,tmp_path/'bindings.json',bindings),'definition':store(m,tmp_path/'definition.json',definition),
        'expected':independent_ref,'raw_inventory':store(m,tmp_path/'raw_inventory.json',{'TEST_ONLY':True}),
        'runtime_profile':profile,'runtime_profile_value':profile_value,'source_only_policy_sha256':m.POLICY_SHA}
    sfref=store(m,tmp_path/'source_preparation.json',sf)
    actual={'kind':m.SOURCE_KIND,'version':2,'passed':True,'preparation':sfref,'source':m.reference(goal),
        'actual_calls':[{'output':m.reference(goal)}]}
    source_manifest=store(m,tmp_path/'source_manifest.json',actual)
    facade=SimpleNamespace(**vars(actual_provider))
    def validate_source(value):
        events.append('TEST_ONLY_source_cold_validation')
        if m.reference(value['path']if isinstance(value,dict)else value)!=source_manifest:raise ValueError('Foreign source')
        return deepcopy(actual)
    facade.validate_source=validate_source;facade.validate_prepared=lambda path:deepcopy(sf)
    facade.schema=SimpleNamespace(points=lambda public:((k,kind)for k,kind,cell in keys),validate_spec=lambda p:p,candidate=lambda seed:{'candidate_id':'FM-C02'})
    class Panel:
        def __init__(self,*args,**kwargs):pass
        def start(self):return 'http://TEST_ONLY_NO_SERVER/'
        def stop(self):pass
    facade.DashboardServer=Panel
    monkeypatch.setattr(m,'source',facade);m._activate()
    return {'manifest':source_manifest,'sf':sf,'actual':actual,'primary':primary,'independent':independent,
        'definition':definition,'facade':facade,'goal':goal,'events':events,'independent_ref':independent_ref}


def test_real_source_facade_exposes_frozen_original_helpers_without_mutating_old_namespaces(m):
    s=m._activate()
    assert s.schema is s.base.schema and callable(s._book)and callable(s.clear_all_formula_caches)
    assert s.SOURCE_KIND==m.SOURCE_KIND and s.VERSION==2
    assert m.previous.source is None and m.previous._N is not m._N
    assert m.previous._N['KIND']==m.previous.KIND and m._N['KIND']==m.KIND
    assert m.ADAPTATION_COUNTS==dict.fromkeys(m.ADAPTATION_COUNTS,1)
    assert m.WORKFLOW_COUNTS==m.previous.ADAPTATION_COUNTS
    assert m._N['compare_complete'].__code__ is m.previous._N['compare_complete'].__code__
    assert m.STAGES==('FM_input1','FM_input2','equivalent','FM_missed_root','extra_change')


def test_primary_map_reads_actual_goal_preserves_boundary_and_exact_types(m,sample):
    before=sample['goal'].read_bytes();independent=Path(sample['independent_ref']['path']).read_bytes()
    primary=m._primary_expected(m.reference(sample['goal']),sample['independent_ref'])
    assert primary==sample['primary'] and primary['Report!A1']['value']=='-6290.86'
    assert sample['independent']['Report!A1']['value']=='-6290.87'
    assert primary['Report!A2']=={'type':'boolean','value':True}
    assert primary['Report!A3']=={'type':'text','value':'n/a - prior period'}
    assert sample['goal'].read_bytes()==before and Path(sample['independent_ref']['path']).read_bytes()==independent


def test_prepare_writes_task_only_primary_file_and_preserves_all_original_source_refs(m,sample,tmp_path,monkeypatch):
    monkeypatch.setitem(m._N,'ThreadCappedResourceLibreOfficeEngine',lambda *a,**k:pytest.fail('No native task in prepare'))
    before=sample['goal'].read_bytes();independent=Path(sample['independent_ref']['path']).read_bytes()
    out=tmp_path/'prepared';ref=m.prepare(sample['manifest'],out);f=m.validate_prepared(out)
    assert f['kind']==m.KIND and f['version']==2 and f['required_actual_LO_calls']==5
    assert f['source_independent_expected']==sample['sf']['expected']
    assert f['actual_primary_expected_from_genuine_goal_ref']==sample['actual']['source']
    assert f['expected']!=sample['sf']['expected'] and m.read(f['expected'])==sample['primary']
    assert m.read(f['source_independent_expected'])==sample['independent']
    assert f['forecast_mask_count']==2 and f['report_NA_count']==2
    assert sample['goal'].read_bytes()==before and Path(sample['independent_ref']['path']).read_bytes()==independent
    with pytest.raises(ValueError):m.prepare(sample['manifest'],out)


@pytest.mark.parametrize('fault',['kind','version','policy'])
def test_foreign_or_legacy_source_provider_never_activates(m,sample,fault):
    if fault=='kind':sample['facade'].SOURCE_KIND='old_source'
    elif fault=='version':sample['facade'].VERSION=1
    else:sample['facade'].POLICY_SHA='other'
    with pytest.raises(ValueError):m._activate()


@pytest.mark.parametrize('fault',['number_for_bool','wrong_text','error','missing'])
def test_goal_map_rejects_wrong_types_NA_errors_or_partial_scope(m,sample,monkeypatch,fault):
    snapshot=deepcopy(sample['primary'])
    if fault=='number_for_bool':snapshot['Report!A2']={'type':'number','value':'1'}
    elif fault=='wrong_text':snapshot['Report!A3']={'type':'text','value':'wrong NA'}
    elif fault=='error':snapshot['ReadMe!Z99']={'type':'error','value':'#DIV/0!'}
    else:snapshot.pop('Report!A1')
    monkeypatch.setitem(m._N,'snapshot',lambda *a,**k:{'values':snapshot})
    with pytest.raises(ValueError):m._primary_expected(sample['actual']['source'],sample['independent_ref'])


@pytest.mark.parametrize('fault',['fake_primary','Boolean_as_integer','numeric_as_boolean','extra_typed_field','independent_ref','goal_ref','source_kind','source_version','policy'])
def test_prepared_lineage_cannot_substitute_goal_or_original_independent_expectation(m,sample,tmp_path,fault):
    out=tmp_path/'prepared';ref=m.prepare(sample['manifest'],out);f=m.read(ref)
    if fault=='fake_primary':
        primary=deepcopy(sample['primary']);primary['Report!A1']['value']='-6290.87';f['expected']=store(m,tmp_path/'fake_primary.json',primary)
    elif fault in ('Boolean_as_integer','numeric_as_boolean','extra_typed_field'):
        primary=deepcopy(sample['primary'])
        if fault=='Boolean_as_integer':primary['Report!A2']['value']=1
        elif fault=='numeric_as_boolean':primary['Report!A1']['value']=True
        else:primary['Report!A1']['extra']='unknown'
        f['expected']=store(m,tmp_path/'maltyped_primary.json',primary)
    elif fault=='independent_ref':f['source_independent_expected']=f['expected']
    elif fault=='goal_ref':f['actual_primary_expected_from_genuine_goal_ref']=sample['independent_ref']
    elif fault=='policy':f['source_precision_policy_sha256']='other'
    else:
        actual=deepcopy(sample['actual']);actual['kind'if fault=='source_kind'else'version']='legacy'if fault=='source_kind'else 1
        f['source_manifest']=store(m,tmp_path/'fake_source.json',actual)
    Path(ref['path']).unlink();m.write(ref['path'],f)
    with pytest.raises((ValueError,KeyError)):m.validate_prepared(out)


def test_historical_boundary_input_uses_actual_goal_primary_map(m,sample,tmp_path):
    out=tmp_path/'prepared';m.prepare(sample['manifest'],out);f=m.read(out/'preparation.json')
    actual=tmp_path/'TEST_ONLY_input_after_mock_recalc.xlsx';cache(f['planned_inputs']['FM_input']['path'],actual,sample['primary'])
    m.verify_input_caches(actual,m.read(f['expected']),blank=True,definition=m.read(f['definition']))
    with pytest.raises(ValueError):m.verify_input_caches(actual,m.read(f['source_independent_expected']),blank=True,definition=m.read(f['definition']))


def test_five_original_stages_full_D_controls_stability_and_no_retry(m,sample,tmp_path,monkeypatch):
    out=tmp_path/'prepared';m.prepare(sample['manifest'],out);events=[]
    class Engine:
        def __init__(self,*args,**kwargs):self.history=[]
        def ensure_image(self):events.append('TEST_ONLY_image')
        def recalculate(self,source,destination):
            cache(source,destination,sample['primary']);events.append(Path(destination).stem)
            self.history.append(store(m,out/f'TEST_ONLY_resource{len(self.history)+1}.json',{'TEST_ONLY':True,'index':len(self.history)+1}))
            return destination
        def metadata(self):return {'actual_resource_receipts':self.history}
    monkeypatch.setitem(m._N,'ThreadCappedResourceLibreOfficeEngine',Engine)
    def resource(call,receipt,f):return {'terminal':receipt,'container_id':str(m.read(receipt)['index'])*64}
    sample['facade'].validate_call=resource
    sample['facade'].owned_absence=lambda calls:{'all_owned_containers_absent':True,'daemon_reachable':True,
        'owned':[{'full_id':c['actual_resource_evidence']['container_id'],'absent':True}for c in calls]}
    # _activate refreshes the workflow engine from this private test facade.
    sample['facade'].ThreadCappedResourceLibreOfficeEngine=Engine
    ref=m.execute_prepared(out);terminal=m.validate_completed(ref)
    assert terminal['kind']==m.TERMINAL_KIND and terminal['version']==2 and terminal['passed']is True
    assert terminal['actual_LO_calls_started']==terminal['actual_LO_calls_completed']==5
    assert [c['role']for c in terminal['actual_calls']]==list(m.STAGES)
    mode=terminal['records']['modes']['financial_modeling']
    assert mode['complete_D_count']==2 and mode['controls']=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}
    assert m.read(terminal['records']['FM_stability'])['comparison']['passed']is True
    assert events==['TEST_ONLY_image',*m.STAGES]
    with pytest.raises(ValueError):m.execute_prepared(out)
    with pytest.raises(ValueError):m.previous.validate_completed(ref)

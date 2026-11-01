from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as X
from zipfile import ZipFile,ZIP_DEFLATED

import openpyxl
import pytest

from sheets_factory.workbook.linear_capital_ringfenced_pairs import task_views as v

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def entry():
    path=ROOT/'scripts/validate_ringfenced_pair_tasks.py'
    spec=importlib.util.spec_from_file_location('_test_pair_tasks',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def toy():
    rows=[];donors=[]
    for i in (1,2):
        prefix=f'M{i} - ';mapping={'Facts':prefix+'Facts','Portfolio':prefix+'Portfolio','Forecast':prefix+'Forecast'}
        fm={'mode':'financial_modeling','sheetnames':list(mapping),
            'masked_targets':[{'sheet':s,'cell':p,'before':None} for s,p in
                [('Portfolio','B2'),('Portfolio','B3'),('Forecast','B1'),('Forecast','B2')]]}
        dbg={'mode':'debugging','sheetnames':list(mapping),
            'formula_edits':[{'sheet':'Forecast','cell':'B1','before':"='Facts'!B1*'Portfolio'!B2",
                'after':"='Facts'!B1+'Portfolio'!B2",'before_kind':'formula','family':'original_toy_fault'}],
            'choice_edits':[{'sheet':'Portfolio','cell':'B2','before':1,'after':0}]}
        rows.append({'financial_modeling':fm,'debugging':dbg,'control_primary':{'sheet':'Forecast','cell':'B1'}})
        donors.append({'id':f'M{i:02}','sheet_map':mapping})
    report={'sheet':'Group','financial':{'B1':{},'B2':{}}}
    return rows,{'donors':donors},report


@pytest.fixture
def material(tmp_path):
    rows,composition,report=toy();plan=v.compile_views(rows,composition,report,toy=True)
    book=openpyxl.Workbook();book.remove(book.active)
    for name in plan['sheetnames']:book.create_sheet(name)
    book.calculation.iterate=False
    for i in (1,2):
        prefix=f'M{i} - '
        book[prefix+'Facts']['A1']='Annual assumptions';book[prefix+'Facts']['B1']=10*i
        book[prefix+'Facts']['B2']=True
        book[prefix+'Portfolio']['A1']='Choice';book[prefix+'Portfolio']['B2']=1
        book[prefix+'Portfolio']['B3']='=AND(B2=1)'
        book[prefix+'Forecast']['B1']=f"='{prefix}Facts'!B1*'{prefix}Portfolio'!B2"
        book[prefix+'Forecast']['B2']='=B1*2';book[prefix+'Forecast']['B1'].number_format='0.00'
    book['Group']['A1']='Management reporting';book['Group']['B1']="=SUM('M1 - Forecast'!B1,'M2 - Forecast'!B1)"
    book['Group']['B2']="=AND('M1 - Portfolio'!B3,'M2 - Portfolio'!B3)"
    goal=tmp_path/'goal.xlsx';book.save(goal);book.close();plan['genuine_goal']=v.c.reference(goal)
    return plan,goal


def test_complete_toy_mask_choices_gates_and_group():
    rows,composition,report=toy();p=v.compile_views(rows,composition,report,toy=True)
    assert p['FM_target_count']==10 and p['DBG_choice_count']==2 and p['DBG_formula_root_count']==2
    for i in (1,2):assert p['FM_mask'][f'M{i} - Portfolio']==['B2','B3']
    assert p['FM_mask']['Group']==['B1','B2']
    assert p['control_root']['sheet']=='M1 - Forecast'


def test_remapped_fault_is_original_business_expression():
    rows,composition,report=toy();p=v.compile_views(rows,composition,report,toy=True)
    assert "'M1 - Facts'!B1" in p['DBG_faults'][0]['after']
    assert "'M1 - Portfolio'!B2" in p['DBG_faults'][0]['after']
    assert {r['after'] for r in p['DBG_choices']}=={0}


@pytest.mark.parametrize('mutation',['duplicate_target','overlap','missing_control','wrong_mode','omit_donor'])
def test_incomplete_or_ambiguous_local_plan_rejected(mutation):
    rows,composition,report=toy()
    if mutation=='duplicate_target':rows[0]['financial_modeling']['masked_targets'].append(rows[0]['financial_modeling']['masked_targets'][0])
    if mutation=='overlap':rows[0]['debugging']['choice_edits'][0].update(sheet='Forecast',cell='B1')
    if mutation=='missing_control':rows[0]['control_primary']['cell']='Z99'
    if mutation=='wrong_mode':rows[0]['financial_modeling']['mode']='debugging'
    if mutation=='omit_donor':rows.pop()
    with pytest.raises(ValueError):v.compile_views(rows,composition,report,toy=True)


def test_production_geometry_is_fail_closed():
    rows,composition,report=toy()
    with pytest.raises(ValueError,match='census'):v.compile_views(rows,composition,report)


@pytest.mark.parametrize('mode',v.MODES)
def test_materialization_preserves_context_and_full_original_faults(material,tmp_path,mode):
    plan,goal=material;output=tmp_path/(mode+'.xlsx')
    receipt=v.transform(goal,output,v.actions(plan,mode))
    assert receipt['all_formula_caches_absent'] and receipt['all_other_member_bytes_preserved']
    assert v.verify(output,plan,blank=mode=='financial_modeling',check_caches=True)['passed']
    b=openpyxl.load_workbook(output,data_only=False)
    try:
        assert b['M1 - Facts']['B1'].value==10 and b['M1 - Facts']['B2'].value is True
        assert b['M1 - Forecast']['B1'].number_format=='0.00'
        assert b['M1 - Portfolio']['B2'].value==(None if mode=='financial_modeling' else 0)
        assert b['M1 - Portfolio']['B3'].value==(None if mode=='financial_modeling' else '=AND(B2=1)')
    finally:b.close()
    with ZipFile(output) as z:
        for name in z.namelist():
            if name.startswith('xl/worksheets/'):
                for cell in X.fromstring(z.read(name)).iter('{'+v.S+'}c'):
                    if cell.find('{'+v.S+'}f')is not None:
                        assert cell.find('{'+v.S+'}v')is None and cell.find('{'+v.S+'}is')is None
    assert v.cold_cache_census(output)==receipt['formulas']


@pytest.mark.parametrize('point,value',[('M1 - Facts!B1',11),('M1 - Facts!A1','changed'),
    ('M1 - Portfolio!B2',1),('Group!C10',99)])
def test_given_changes_leaked_choice_and_extra_cells_rejected(material,tmp_path,point,value):
    plan,goal=material;output=tmp_path/'input.xlsx';v.transform(goal,output,v.actions(plan,'financial_modeling'))
    b=openpyxl.load_workbook(output);sheet,cell=point.rsplit('!',1);b[sheet][cell]=value;b.save(output);b.close()
    with pytest.raises(ValueError):v.verify(output,plan,blank=True)


def test_undeclared_healthy_formula_change_rejected(material,tmp_path):
    plan,goal=material;output=tmp_path/'input.xlsx';v.transform(goal,output,v.actions(plan,'debugging'))
    b=openpyxl.load_workbook(output);b['M1 - Forecast']['B2']='=B1*3';b.save(output);b.close()
    with pytest.raises(ValueError,match='healthy source formula'):v.verify(output,plan)


def test_missing_declared_physical_cell_rejected(material,tmp_path):
    plan,goal=material
    with pytest.raises(ValueError,match='did not exist'):
        v.transform(goal,tmp_path/'bad.xlsx',{'M1 - Forecast':{'Z999':('blank',None)}})


def test_unknown_edit_and_nonbinary_provisional_choice_rejected(material,tmp_path):
    plan,goal=material
    for value in (2,True,0.0):
        with pytest.raises(ValueError):v.transform(goal,tmp_path/(str(value)+'.xlsx'),{'M1 - Portfolio':{'B2':('number',value)}})


def test_workflow_is_exact_private_eight_stage_body(entry):
    for name in ('execute_prepared','validate_completed','_stage_source'):
        assert entry._N[name].__code__ is getattr(entry.base,name).__code__
        assert entry._N[name].__globals__ is entry._N
        assert entry._N[name].__globals__ is not vars(entry.base)
    assert entry.STAGES==entry.base.STAGES
    assert entry._N['source'] is entry.source and entry.source is not entry.base.source


def test_all_numeric_primary_grader_is_unchanged(entry):
    assert entry._N['compare_complete'].__code__ is entry.base.compare_complete.__code__
    assert entry.base.streaming_verifier is v.sparse
    assert v.sparse.normalize(.014)==('number','0.01')


def test_genuine_completed_gate_is_required_before_materialization(entry,tmp_path,monkeypatch):
    called=[]
    monkeypatch.setattr(entry.source,'validate_source',lambda r:(_ for _ in ()).throw(ValueError('genuine proof rejected')))
    monkeypatch.setattr(entry.views,'plan',lambda *a:called.append('plan'))
    with pytest.raises(ValueError,match='genuine proof rejected'):entry.prepare('fake','fake',tmp_path/'out')
    assert not called and not (tmp_path/'out').exists()


def test_no_pass_flag_can_replace_genuine_source_gate(entry,tmp_path,monkeypatch):
    record=entry.write(tmp_path/'fake.json',{'kind':entry.SOURCE_KIND,'version':1,'passed':True,
        'actual_calls_started':3,'actual_calls_completed':2,'LO_calls':3})
    monkeypatch.setattr(entry.session,'validate_completed',lambda *a,**k:pytest.fail('invalid source reached provider'))
    with pytest.raises(ValueError,match='genuine completed'):entry._genuine(record)


def test_real_root_pinned_cache_REF_passed_to_genuine_provider(entry,tmp_path,monkeypatch):
    folder=tmp_path/'source';folder.mkdir();cache=entry.write(tmp_path/'cache.json',{'not':'authority'})
    preparation=entry.write(folder/'preparation.json',{'kind':'test'})
    entry.write(tmp_path/'session_preparation.json',{'source_preparation':preparation,
        'genuine_local_reference_validations':2,'genuine_original_source_validations':2,'root_pinned_prior_preflight':cache})
    ref=entry.write(folder/'terminal.json',{'kind':entry.SOURCE_KIND,'version':1,'passed':True,
        'actual_calls_started':3,'actual_calls_completed':3,'LO_calls':3,'preparation':preparation})
    expected=object();calls=[]
    monkeypatch.setattr(entry.session,'validate_completed',lambda *a,**k:(calls.append((a,k)),expected)[1])
    assert entry._genuine(ref)is expected
    assert calls==[((ref,),{'parse_cache':cache,'expected_cache_sha256':cache['sha256']})]


def test_cli_cannot_prepare_and_run(entry,tmp_path,monkeypatch):
    monkeypatch.setattr(entry,'prepare',lambda *a:pytest.fail('preparation was started'))
    with pytest.raises(ValueError,match='separate actual run'):
        entry.main(['--source-manifest','x','--whole-views-contract','y','--output',str(tmp_path/'z'),'--run'])


def test_actual_ten_donor_small_metadata_contract_without_cold_or_workbooks(entry,monkeypatch):
    prospective=ROOT/'outputs/research/ringfenced_pair_zero_service_preparation_20261101T010044Z/pool/prospective.json'
    if not prospective.exists():pytest.skip('retained research metadata unavailable')
    monkeypatch.setattr(entry.session,'validate_completed',lambda *a,**k:pytest.fail('no genuine cold call authorized'))
    value=v._pool_value(prospective)
    assert len(value['donors'])==len(value['pairs'])==10
    assert value['pair_order'][0]=='R2-01' and value['counts']['choices']==720
    assert value['task_materials_emitted']==value['new_source_calls']==value['new_financial_forwards']==0
    assert all(set(r['views'])==set(v.MODES) for r in value['donors'])


def cached_copy(source,destination,values):
    """Test-only explicit toy caches; this is never native evidence."""
    with ZipFile(source) as zin,ZipFile(destination,'x',ZIP_DEFLATED) as zout:
        parts=v._parts(zin);reverse={part:s for s,part in parts.items()}
        for info in zin.infolist():
            raw=zin.read(info.filename)
            if info.filename in reverse:
                sheet=reverse[info.filename];tree=X.fromstring(raw)
                for cell in tree.iter('{'+v.S+'}c'):
                    if cell.find('{'+v.S+'}f')is None:continue
                    value=values[(sheet,cell.get('r'))]
                    for old in list(cell.findall('{'+v.S+'}v')):cell.remove(old)
                    if type(value)is bool:cell.set('t','b');value=int(value)
                    X.SubElement(cell,'{'+v.S+'}v').text=str(value)
                raw=X.tostring(tree)
            zout.writestr(info,raw)


def test_all_five_controls_use_complete_generic_union_for_both_modes(material,tmp_path):
    plan,seed=material;values={}
    for i in (1,2):
        values[f'M{i} - Portfolio','B3']=True
        values[f'M{i} - Forecast','B1']=10*i;values[f'M{i} - Forecast','B2']=20*i
    values['Group','B1']=30;values['Group','B2']=True
    goal=tmp_path/'cached_goal.xlsx';cached_copy(seed,goal,values)
    paths={}
    for mode in v.MODES:
        cold=tmp_path/(mode+'_cold.xlsx');v.transform(goal,cold,v.actions(plan,mode))
        if mode=='financial_modeling':paths[mode]=cold
        else:
            changed=dict(values)
            for i in (1,2):changed[f'M{i} - Portfolio','B3']=False
            changed['Group','B2']=False
            paths[mode]=tmp_path/'cached_DBG.xlsx';cached_copy(cold,paths[mode],changed)
    root=plan['control_root'];point=root['sheet'],root['cell'];controls={}
    for label,actions in {
        'equivalent':{point[0]:{point[1]:('formula','=0+('+root['before'].lstrip('=')+')')}},
        'missed_root':{point[0]:{point[1]:('formula',root['after'])}},
        'extra_change':{'Group':{'A1':('text','Changed public label')}}}.items():
        cold=tmp_path/(label+'_cold.xlsx');v.transform(goal,cold,actions)
        cached=tmp_path/(label+'.xlsx');changed=dict(values)
        if label=='missed_root':changed[point]=11;changed['M1 - Forecast','B2']=22;changed['Group','B1']=31
        cached_copy(cold,cached,changed);controls[label]=cached
    for mode,inp in paths.items():
        candidates={'oracle':goal,'nop':inp,**controls}
        reports={k:v.sparse.compare_files(inp,goal,out) for k,out in candidates.items()}
        assert {k:r['reward'] for k,r in reports.items()}=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}
        assert len({r['expected_change_count'] for r in reports.values()})==1
        assert reports['oracle']['expected_change_count']==(10 if mode=='financial_modeling' else 5)


def test_cache_header_is_not_an_authority(material,tmp_path):
    plan,goal=material;values={}
    for i in (1,2):
        values[f'M{i} - Portfolio','B3']=True
        values[f'M{i} - Forecast','B1']=10*i;values[f'M{i} - Forecast','B2']=20*i
    values['Group','B1']=30;values['Group','B2']=True
    output=tmp_path/'seeded.xlsx';cached_copy(goal,output,values)
    with pytest.raises(ValueError,match='cache must be absent'):v.cold_cache_census(output)

"""Own-family task engineering, with explicit mocked native/resource boundary."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import openpyxl
import pytest

ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def setup(tmp_path,monkeypatch):
    p=ROOT/'scripts/validate_equity_income_group_tasks.py';s=importlib.util.spec_from_file_location('_equity_tasks_test',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
    def forbidden(*a,**k):raise AssertionError('No actual Docker/LO/process services in tiny tests')
    monkeypatch.setattr(m.source.subprocess,'run',forbidden)
    candidate=m.source.excel.build_views(tmp_path/'candidate',m.source.spec.build_spec(entities=2,quarters=2,scenarios=1))
    source_preparation=m.source.prepare(candidate,tmp_path/'source');sf=m.read(source_preparation);cm=m.read(candidate)
    # Explicit test-only genuine-source boundary. Production calls the complete source3 validator.
    stub={'kind':m.source.SOURCE_KIND,'version':1,'passed':True,'source':cm['goal'],'preparation':source_preparation,
        'actual_calls':[{'output':cm['goal']}],'TEST_ONLY':True}
    manifest=m.write(tmp_path/'source/source_manifest.TEST_ONLY.json',stub)
    checks=[]
    def admit(value):
        assert m.reference(value['path'] if isinstance(value,dict) else value)==manifest
        checks.append(value);return stub
    monkeypatch.setattr(m.source,'validate_source',admit)
    return SimpleNamespace(m=m,root=tmp_path,source=manifest,source_value=stub,source_preparation=sf,candidate=candidate,checks=checks)

def fill(source,destination,expected,*,wrong_point=None):
    with ZipFile(source) as zin,ZipFile(destination,'x',ZIP_DEFLATED) as zout:
        sheets=ET.fromstring(zin.read('xl/workbook.xml')).find('{*}sheets');names={f'xl/worksheets/sheet{i+1}.xml':n.get('name') for i,n in enumerate(sheets)}
        for item in zin.infolist():
            raw=zin.read(item.filename)
            if item.filename in names:
                root=ET.fromstring(raw)
                for cell in root.findall('{*}sheetData/{*}row/{*}c'):
                    key=names[item.filename]+'!'+cell.get('r')
                    if cell.find('{*}f') is not None and key in expected:
                        for child in list(cell):
                            if child.tag.rsplit('}',1)[-1]=='v':cell.remove(child)
                        cell.attrib.pop('t',None);value=expected[key]['value']
                        if key==wrong_point:value=str(money(value)+1)
                        ET.SubElement(cell,'{'+root.tag.split('}')[0].lstrip('{')+'}v').text=value
                raw=ET.tostring(root)
            zout.writestr(item,raw)

def money(value):
    from decimal import Decimal
    return Decimal(value)

def test_prepare_freezes_both_modes_eight_actual_plans_and_original_instruction_bytes(setup,monkeypatch):
    c=setup;m=c.m
    monkeypatch.setattr(m,'ThreadCappedResourceLibreOfficeEngine',lambda *a,**k:pytest.fail('prepare cannot create an engine'))
    ref=m.prepare(c.source,c.root/'tasks');f=m.read(ref)
    assert len(c.checks)==1
    assert f['required_actual_LO_calls']==8 and f['actual_LO_calls']==0
    assert f['mode_order']==['financial_modeling','debugging'] and f['stage_order']==list(m.STAGES)
    assert f['all_modes_and_controls_frozen_before_first_actual_call'] and f['reuse_genuine_source3_goal_and_two_stabilities']
    assert f['financial_target_count']==144 and f['DBG_formula_root_count']==4
    original=m.read(c.candidate)
    for mode,ref in f['instruction_bytes'].items():
        assert Path(ref['path']).read_bytes()==Path(original['views'][mode]['instruction']['path']).read_bytes()
    for name,r in f['planned_inputs'].items():
        book=openpyxl.load_workbook(r['path'],data_only=True)
        try:assert all(book[p.rsplit('!',1)[0]][p.rsplit('!',1)[1]].value is None for p in m.read(f['expected']))
        finally:book.close()
    assert m.validate_prepared(c.root/'tasks')==f

def test_source_gate_rejection_cannot_be_overridden_by_passed_json(setup,monkeypatch):
    c=setup;m=c.m
    def reject(*a):raise ValueError('Missing real source resources/convergence')
    monkeypatch.setattr(m.source,'validate_source',reject)
    with pytest.raises(ValueError,match='real source'):m.prepare(c.source,c.root/'tasks')
    assert not (c.root/'tasks').exists()

def test_declared_faults_mask_and_equivalent_transform_preserve_every_other_cell_and_style(setup):
    c=setup;m=c.m;m.prepare(c.source,c.root/'tasks');f=m.validate_prepared(c.root/'tasks')
    for edit in f['exact_edits'].values():
        with ZipFile(edit['source']['path']) as a,ZipFile(edit['output']['path']) as b:
            assert a.namelist()==b.namelist()
            assert [n for n in a.namelist() if a.read(n)!=b.read(n)]==edit['changed_members']
        before=openpyxl.load_workbook(edit['source']['path']);after=openpyxl.load_workbook(edit['output']['path'])
        points={(r['sheet'],r['cell']) for r in edit['edits']}
        try:
            for s in before:
                for x in s._cells.values():
                    y=after[s.title][x.coordinate]
                    assert x._style==y._style
                    if (s.title,x.coordinate) not in points:assert x.value==y.value
        finally:before.close();after.close()

def install_mock(c,monkeypatch,*,failure=None):
    m=c.m;engines=[];f=m.read(c.root/'tasks/preparation.json');expected=m.read(f['expected'])
    first=m.read(f['bindings'])['DBG_root_edits'][0];bad=first['sheet']+'!'+first['cell']
    class Engine:
        def __init__(self,*a,**k):self.history=[];engines.append(self)
        def ensure_image(self):pass
        def recalculate(self,source,destination):
            name=Path(destination).stem;assert name==m.STAGES[len(self.history)]
            if name==failure:raise RuntimeError('Explicit mocked task failure')
            fill(source,destination,expected,wrong_point=bad if name.startswith('DBG_input') or name=='DBG_missed_root' else None)
            runtime=m.write(Path(destination).with_suffix('.mock.json'),{'source':m.reference(source),'container_id':f'{len(self.history)+1:064x}','TEST_ONLY':True})
            self.history.append(runtime);return Path(destination)
        def metadata(self):return {'actual_resource_receipts':self.history}
    class Server:
        def __init__(self,*a,**k):pass
        def start(self):return 'mock://no-socket'
        def stop(self):pass
    monkeypatch.setattr(m,'ThreadCappedResourceLibreOfficeEngine',Engine);monkeypatch.setattr(m,'DashboardServer',Server)
    monkeypatch.setattr(m.source,'validate_call',lambda call,r,f:{'terminal':r,'container_id':m.read(r)['container_id'],'TEST_ONLY':True})
    monkeypatch.setattr(m.source,'owned_absence',lambda calls:{'all_owned_containers_absent':True,'daemon_reachable':True,
        'owned':[{'full_id':r['actual_resource_evidence']['container_id'],'absent':True} for r in calls],'TEST_ONLY':True})
    return engines

def test_mock_eight_call_lifecycle_complete_D_both_five_controls_and_cold_validation(setup,monkeypatch):
    c=setup;m=c.m;m.prepare(c.source,c.root/'tasks');engines=install_mock(c,monkeypatch)
    ref=m.execute_prepared(c.root/'tasks');t=m.read(ref)
    assert t['passed'] and t['actual_LO_calls_completed']==8 and len(engines[0].history)==8
    assert t['source_LO_calls_reused']==3 and t['qualified'] is False and t['normal_all12_QA_passed'] is False
    assert t['model_calls']==t['solver_calls']==t['Harbor_calls']==0
    assert t['records']['modes']['financial_modeling']['complete_D_count']==144
    assert t['records']['modes']['debugging']['complete_D_count']==1  # Mocked numeric boundary, not a claimed real business result.
    assert all(p['controls']=={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0} for p in t['records']['modes'].values())
    assert m.validate_completed(ref)==t
    with pytest.raises(ValueError,match='No retries'):m.execute_prepared(c.root/'tasks')
    Path(t['records']['modes']['financial_modeling']['full_D_controls']['equivalent']['path']).write_text('{}')
    with pytest.raises(ValueError):m.validate_completed(ref)

def test_failure_retains_exact_call_and_no_later_calculations_or_retry(setup,monkeypatch):
    c=setup;m=c.m;m.prepare(c.source,c.root/'tasks');engines=install_mock(c,monkeypatch,failure='DBG_input1')
    with pytest.raises(RuntimeError,match='preserve'):m.execute_prepared(c.root/'tasks')
    t=m.read(c.root/'tasks/terminal.json')
    assert not t['passed'] and t['actual_LO_calls_started']==3 and t['actual_LO_calls_completed']==2
    assert len(engines[0].history)==2 and (c.root/'tasks/DBG_input1_terminal.json').is_file()
    with pytest.raises(ValueError):m.validate_completed(c.root/'tasks/terminal.json')
    with pytest.raises(ValueError,match='No retries'):m.execute_prepared(c.root/'tasks')

def test_complete_comparison_reuses_generic_all_numeric_2dp_and_visible_extra_change(setup):
    c=setup;m=c.m;m.prepare(c.source,c.root/'tasks');f=m.validate_prepared(c.root/'tasks');expected=m.read(f['expected'])
    output=c.root/'answer.xlsx';fill(f['planned_inputs']['equivalent']['path'],output,expected)
    comparison=m.compare_complete(f['planned_inputs']['FM_input']['path'],f['genuine_goal']['path'],output,expected)
    assert comparison['reward']==1 and comparison['expected_change_count']==144
    assert comparison==m.streaming_verifier.compare_files(f['planned_inputs']['FM_input']['path'],f['genuine_goal']['path'],output)
    changed=c.root/'changed.xlsx';m.transform(output,changed,{('Read Me','A1'):('text','Wrong protected title')})
    result=m.compare_complete(f['planned_inputs']['FM_input']['path'],f['genuine_goal']['path'],changed,expected)
    assert result['reward']==0 and result['extra_changes']==['Read Me!A1']

def test_primary_reward_rounds_even_rates_while_construction_preservation_remains_exact(setup):
    c=setup;m=c.m;m.prepare(c.source,c.root/'tasks');f=m.validate_prepared(c.root/'tasks');expected=m.read(f['expected'])
    answer=c.root/'answer.xlsx';fill(f['genuine_goal']['path'],answer,expected)
    changed=c.root/'sub_cent_rate.xlsx'
    with ZipFile(answer) as zin,ZipFile(changed,'x',ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            raw=zin.read(item.filename)
            if item.filename=='xl/worksheets/sheet2.xml':
                tree=ET.fromstring(raw);cell=next(n for n in tree.findall('{*}sheetData/{*}row/{*}c') if n.get('r')=='C2')
                cell.find('{*}v').text=str(money(cell.find('{*}v').text)+money('.001'));raw=ET.tostring(tree)
            zout.writestr(item,raw)
    result=m.compare_complete(f['planned_inputs']['FM_input']['path'],f['genuine_goal']['path'],changed,expected)
    assert result['reward']==1  # E05/E06 applies two decimals to every numeric cell.
    with pytest.raises(ValueError,match='Provided task inputs'):
        m.verify_definitions(changed,m.read(f['definition']))

def test_frozen_source_identity_instruction_and_plan_bytes_are_rechecked(setup):
    c=setup;m=c.m;m.prepare(c.source,c.root/'tasks');f=m.validate_prepared(c.root/'tasks')
    Path(f['instruction_bytes']['financial_modeling']['path']).write_text('Different instruction')
    with pytest.raises(ValueError,match='Frozen reference'):m.validate_prepared(c.root/'tasks')

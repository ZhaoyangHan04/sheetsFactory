"""Tiny pure books and explicitly mocked lifecycle; never actual Docker or LO."""
from copy import deepcopy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import openpyxl
import pytest

ROOT=Path(__file__).resolve().parents[1]
S='http://schemas.openxmlformats.org/spreadsheetml/2006/main'

@pytest.fixture
def setup(tmp_path,monkeypatch):
    p=ROOT/'scripts/build_equity_income_group_source.py'
    s=importlib.util.spec_from_file_location('_equity_income_source_test',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
    def forbidden(*a,**kw):raise AssertionError('Actual Docker/LO/process services forbidden in pure tests')
    monkeypatch.setattr(m.subprocess,'run',forbidden)
    candidate=m.excel.build_views(tmp_path/'candidate',m.spec.build_spec(entities=2,quarters=2,scenarios=1))
    return SimpleNamespace(m=m,root=tmp_path,candidate=candidate)

def seed(source,destination,expected,*,bad_point=None,change_literal=None):
    """Only a test engine: put declared two-decimal expectations into formula caches."""
    with ZipFile(source) as zin,ZipFile(destination,'x',ZIP_DEFLATED) as zout:
        sheets=ET.fromstring(zin.read('xl/workbook.xml')).find('{*}sheets')
        names={f'xl/worksheets/sheet{i+1}.xml':s.get('name') for i,s in enumerate(sheets)}
        for item in zin.infolist():
            raw=zin.read(item.filename)
            if item.filename in names:
                sheet=names[item.filename];tree=ET.fromstring(raw)
                for cell in tree.findall('{*}sheetData/{*}row/{*}c'):
                    point=sheet+'!'+cell.get('r')
                    if point in expected:
                        for child in list(cell):
                            if child.tag.rsplit('}',1)[-1]=='v':cell.remove(child)
                        cell.attrib.pop('t',None)
                        ET.SubElement(cell,'{'+S+'}v').text=expected[point]['value']
                        if point==bad_point:cell.set('t','b');cell.find('{*}v').text='1'
                    if point==change_literal:
                        node=cell.find('{*}is/{*}t');assert node is not None;node.text='Altered public policy'
                raw=ET.tostring(tree)
            zout.writestr(item,raw)

def test_default_prepare_is_cold_zero_service_complete_scope(setup,monkeypatch):
    c=setup;m=c.m
    monkeypatch.setattr(m,'ThreadCappedResourceLibreOfficeEngine',lambda *a,**k:pytest.fail('Prepare must not instantiate an engine'))
    original=m.read(c.candidate)['goal'];before=m.reference(original['path'])
    ref=m.prepare(c.candidate,c.root/'source');f=m.read(ref)
    assert f['kind']==m.KIND and f['required_actual_LO_calls']==3 and f['actual_LO_calls']==0
    assert f['stage_order']==['source1','source2','source3'] and f['cold_start_is_unseeded']
    assert f['cache_clearance']['all_formula_caches_cleared']==144
    assert m.read(f['independent_comparison'])['complete_AB_financial_fields']==160
    assert m.read(f['independent_comparison'])['provided_operating_input_fields']==16
    assert m.reference(original['path'])==before
    assert m.validate_prepared(c.root/'source')==f
    book=openpyxl.load_workbook(f['cold_start']['path'],data_only=True)
    try:
        assert all(book[p.rsplit('!',1)[0]][p.rsplit('!',1)[1]].value is None for p in m.read(f['expected']))
    finally:book.close()

def test_cache_clearance_preserves_all_formula_literal_style_and_other_member_bytes(setup):
    c=setup;m=c.m;m.prepare(c.candidate,c.root/'source');f=m.validate_prepared(c.root/'source')
    original=m.read(c.candidate)['goal']['path']
    with ZipFile(original) as a,ZipFile(f['cold_start']['path']) as b:
        assert a.namelist()==b.namelist()
        for name in a.namelist():
            if name not in f['cache_clearance']['changed_members']:assert a.read(name)==b.read(name)
            elif name.startswith('xl/worksheets/'):
                left,right=ET.fromstring(a.read(name)),ET.fromstring(b.read(name))
                aa={x.get('r'):x for x in left.findall('{*}sheetData/{*}row/{*}c')}
                bb={x.get('r'):x for x in right.findall('{*}sheetData/{*}row/{*}c')}
                assert set(aa)==set(bb)
                for key,cell in aa.items():
                    if cell.find('{*}f') is None:assert ET.tostring(cell)==ET.tostring(bb[key])
                    else:
                        for child in list(cell):
                            if child.tag.rsplit('}',1)[-1]=='v':cell.remove(child)
                        assert ET.tostring(cell)==ET.tostring(bb[key])

def test_clear_cache_handles_empty_cells_without_swallowing_a_later_formula(tmp_path):
    p=ROOT/'scripts/build_equity_income_group_source.py';s=importlib.util.spec_from_file_location('_equity_clear',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
    before=tmp_path/'a.xlsx';after=tmp_path/'b.xlsx'
    raw=b'<worksheet xmlns="'+S.encode()+b'"><sheetData><row r="1"><c r="A1"/><c r="B1"><f>1+1</f><v>2</v></c><c r="C1"/><c r="D1"><f>B1+1</f><v>3</v></c></row></sheetData></worksheet>'
    with ZipFile(before,'x') as z:z.writestr('xl/worksheets/sheet1.xml',raw);z.writestr('untouched',b'abc')
    report=m.clear_all_formula_caches(before,after);assert report['all_formula_caches_cleared']==2
    with ZipFile(after) as z:
        assert z.read('untouched')==b'abc'
        assert z.read('xl/worksheets/sheet1.xml')==raw.replace(b'<v>2</v>',b'').replace(b'<v>3</v>',b'')

def test_full_financial_audit_rejects_boolean_and_changed_policy_without_numeric_tolerance(setup):
    c=setup;m=c.m;m.prepare(c.candidate,c.root/'source');f=m.validate_prepared(c.root/'source')
    d,e=m.read(f['definition']),m.read(f['expected']);correct=c.root/'correct.xlsx'
    seed(f['cold_start']['path'],correct,e)
    report=m.audit_workbook(correct,d,e)
    assert report['passed'] and report['all_financial_fields_checked']==160
    assert report['all_derived_values_checked']==144 and report['provided_financial_input_fields_checked']==16
    bad=c.root/'bool.xlsx';seed(f['cold_start']['path'],bad,e,bad_point=next(iter(e)))
    assert not m.audit_workbook(bad,d,e)['passed']
    changed=c.root/'policy.xlsx';seed(f['cold_start']['path'],changed,e,change_literal='Read Me!A1')
    assert not m.audit_workbook(changed,d,e)['passed']
    assert m.typed(True)!=m.typed(1)

def test_given_operating_fields_are_bound_to_public_spec_not_merely_to_self_inventory(setup):
    c=setup;m=c.m;manifest=m.read(c.candidate);bindings=m.read(manifest['bindings']);public=m.read(manifest['specification'])
    book=openpyxl.load_workbook(manifest['goal']['path']);sheet=book['S01 Entities']
    # Revenue and cash opex move equally, so derived earnings alone would not detect this.
    sheet['C6']=sheet['C6'].value+1;sheet['C7']=sheet['C7'].value+1
    path=c.root/'shifted_inputs.xlsx';book.save(path);book.close()
    with pytest.raises(ValueError,match='supplied operating'):m.source_definition(path,bindings,public)

def test_independent_oracle_disagreement_cannot_be_replaced_by_seeded_goal_caches(setup,monkeypatch):
    c=setup;m=c.m;original=m.decimal_oracle.solve
    def altered(public):
        result=deepcopy(original(public));result['scenarios'][0]['periods'][0]['entities']['E01']['current_tax']+=1
        return result
    monkeypatch.setattr(m.decimal_oracle,'solve',altered)
    with pytest.raises(ValueError,match='independent Decimal/Fraction'):m.prepare(c.candidate,c.root/'source')

def install_mock(c,monkeypatch,*,fail_stage=None,seed_values=True):
    m=c.m;engines=[]
    class Engine:
        def __init__(self,*a,**kw):self.history=[];engines.append(self)
        def ensure_image(self):pass
        def recalculate(self,source,destination):
            index=len(self.history);assert Path(destination).stem==m.STAGES[index]
            if Path(destination).stem==fail_stage:raise RuntimeError('Explicit mocked calculation failure')
            if index==0:
                book=openpyxl.load_workbook(source,data_only=True)
                try:assert all(book[p.rsplit('!',1)[0]][p.rsplit('!',1)[1]].value is None for p in m.read(c.root/'source/expected.private.json'))
                finally:book.close()
            if seed_values:seed(source,destination,m.read(c.root/'source/expected.private.json'))
            else:Path(destination).write_bytes(Path(source).read_bytes())
            runtime=m.write(Path(destination).with_suffix('.mock.json'),{'source':m.reference(source),'container_id':f'{index+1:064x}','TEST_ONLY':True})
            self.history.append(runtime);return Path(destination)
        def metadata(self):return {'actual_resource_receipts':self.history}
    class Server:
        def __init__(self,*a,**k):pass
        def start(self):return 'mock://no-dashboard-socket'
        def stop(self):pass
    monkeypatch.setattr(m,'ThreadCappedResourceLibreOfficeEngine',Engine);monkeypatch.setattr(m,'DashboardServer',Server)
    monkeypatch.setattr(m,'validate_call',lambda call,r,f:{'terminal':r,'container_id':m.read(r)['container_id'],'TEST_ONLY':True})
    monkeypatch.setattr(m,'owned_absence',lambda calls:{'all_owned_containers_absent':True,'daemon_reachable':True,
        'owned':[{'full_id':c['actual_resource_evidence']['container_id'],'absent':True} for c in calls],'TEST_ONLY':True})
    return engines

def test_mock_three_native_calls_chain_full_audit_two_stabilities_and_cold_gate(setup,monkeypatch):
    c=setup;m=c.m;m.prepare(c.candidate,c.root/'source');engines=install_mock(c,monkeypatch)
    ref=m.execute_prepared(c.root/'source');terminal=m.read(ref)
    assert terminal['passed'] and terminal['actual_LO_calls_completed']==3 and len(engines[0].history)==3
    assert terminal['qualified'] is False and terminal['normal_all12_QA_passed'] is False
    assert terminal['model_calls']==terminal['solver_calls']==terminal['Harbor_calls']==0
    for stage in m.STAGES:
        assert m.read(terminal['records'][stage+'_audit'])['all_financial_fields_checked']==160
    assert m.validate_source(ref)==terminal
    with pytest.raises(ValueError,match='No retries'):m.execute_prepared(c.root/'source')
    Path(terminal['records']['source1_to_source2']['path']).write_text('{}')
    with pytest.raises(ValueError):m.validate_source(ref)

@pytest.mark.parametrize('failure',['source2','uncomputed'])
def test_actual_failure_or_missing_native_caches_retains_first_attempt_and_stops(setup,monkeypatch,failure):
    c=setup;m=c.m;m.prepare(c.candidate,c.root/'source')
    install_mock(c,monkeypatch,fail_stage='source2' if failure=='source2' else None,seed_values=failure!='uncomputed')
    with pytest.raises(RuntimeError,match='preserve'):m.execute_prepared(c.root/'source')
    t=m.read(c.root/'source/source_manifest.json')
    assert not t['passed'] and t['actual_LO_calls_started']==(2 if failure=='source2' else 1)
    assert (c.root/'source/failure.json').is_file()
    with pytest.raises(ValueError,match='genuine'):m.validate_source(c.root/'source/source_manifest.json')
    with pytest.raises(ValueError,match='No retries'):m.execute_prepared(c.root/'source')

def test_prepared_cold_bytes_and_foreign_source_kind_cannot_be_admitted(setup):
    c=setup;m=c.m;m.prepare(c.candidate,c.root/'source');f=m.validate_prepared(c.root/'source')
    Path(f['cold_start']['path']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='Frozen reference'):m.validate_prepared(c.root/'source')
    with pytest.raises(ValueError):m.validate_source({'path':c.candidate['path'],'sha256':c.candidate['sha256'],'bytes':c.candidate['bytes']})

@pytest.mark.parametrize('message,expected', [('error: no such object: {cid}',True),('Error: No such container: {cid}',True),
    ('permission denied: {cid}',False),('error: no such object: '+'f'*64,False)])
def test_owned_absence_accepts_only_exact_full_id_and_reachable_daemon(setup,monkeypatch,message,expected):
    c=setup;m=c.m;cid='1'*64
    def run(command,**kw):
        assert command[:2] in (['docker','inspect'],['docker','version'])
        return SimpleNamespace(returncode=1,stdout='',stderr=message.format(cid=cid)) if command[1]=='inspect' else SimpleNamespace(returncode=0,stdout='28.5.0\n',stderr='')
    monkeypatch.setattr(m.subprocess,'run',run)
    result=m.owned_absence([{'actual_resource_evidence':{'container_id':cid}}])
    assert result['all_owned_containers_absent'] is expected and result['daemon_reachable']

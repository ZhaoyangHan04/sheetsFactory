"""Pure fixtures/retained metadata only; no cold providers, native or models."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from xml.etree import ElementTree as E
from zipfile import ZipFile,ZIP_DEFLATED

from openpyxl import Workbook
import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def m():
    path=ROOT/'scripts/run_ringfenced_pair_session_revision3.py';s=importlib.util.spec_from_file_location('_test_pair_revision3',path)
    module=importlib.util.module_from_spec(s);s.loader.exec_module(module);return module


def styles(identity='0',formats=()):
    root=E.Element('styleSheet');f=E.SubElement(root,'numFmts')
    for key,value in formats:E.SubElement(f,'numFmt',numFmtId=key,formatCode=value)
    E.SubElement(E.SubElement(root,'cellXfs'),'xf',numFmtId=identity);return root


@pytest.mark.parametrize('identity,formats,wanted',[
    ('0',[],True),('164',[('164','General')],True),('164',[('165','General')],False),
    ('164',[('164','0.00')],False),('164',[('164','general')],False),
    ('164',[('164','General'),('164','General')],False),
    ('164',[('164','General'),('164','0')],False),('0',[('0','0.00')],False)])
def test_only_exact_existing_general_semantics(m,identity,formats,wanted):
    assert m._general_zero(styles(identity,formats)) is wanted


def rewrite(source,destination,change):
    with ZipFile(source) as zin,ZipFile(destination,'x',ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            raw=zin.read(info.filename)
            if info.filename.endswith('.xml'):
                root=E.fromstring(raw)
                if change(info.filename,root):raw=E.tostring(root)
            zout.writestr(info,raw)
    return destination


@pytest.fixture
def real_audit_fixture(m,tmp_path):
    c=m.c;stream=m.stream;S='{'+stream.S+'}';donors=[];reports=[]
    for i in (1,2):
        b=Workbook();s=b.active;s.title='GroupSummary';s['A1']='Supplied cash / GBP pence';s['A2']=True;s['A3']='n/a (provided)'
        scenarios={}
        for si,sid in enumerate(c.SCENARIOS):
            annual=[]
            for year in c.YEARS:
                row={'year':year,'fiscal_year':2026+year}
                for fi,field in enumerate(c.GROUP_FIELDS,3):
                    value=i*100000+si*10000+year*100+fi
                    if field=='net_lp_cashflow':value=-value
                    row[field]=value;s.cell(4+si*20+year,fi,value)
                annual.append(row)
            scenarios[sid]={'annual':annual}
        s['H1']='=C5*2';p=b.create_sheet('Portfolio');p['B3']=1;p['B369']=1;p['B370']=1000*i
        plain=tmp_path/f'plain{i}.xlsx';b.save(plain);b.close()
        def seed(name,root,i=i):
            if name!='xl/worksheets/sheet1.xml':return False
            node=next(n for n in root.iter(S+'c') if n.get('r')=='H1');node.find(S+'v').text=str(2*(i*100000+103));return True
        goal=rewrite(plain,tmp_path/f'donor{i}.xlsx',seed)
        donors.append({'id':f'M0{i}','prefix':f'P0{i} - ','display_name':f'Mandate {i}','workbook':c.reference(goal)});reports.append(scenarios)
    original=stream.compose_toy(donors,tmp_path/'locals_builtin.xlsx')
    def make_custom_general(name,root):
        if name!='xl/styles.xml':return False
        formats=root.find(S+'numFmts')
        if formats is None:formats=E.SubElement(root,S+'numFmts')
        E.SubElement(formats,S+'numFmt',numFmtId='164',formatCode='General');formats.set('count',str(len(formats)))
        root.find(S+'cellXfs')[0].set('numFmtId','164');return True
    custom=rewrite(Path(original['output']['path']),tmp_path/'locals_custom_general.xlsx',make_custom_general)
    local={**original,'output':c.reference(custom)}
    contexts=[{'profile_id':p,'specification':{'path':'/toy','sha256':'0'*64,'bytes':0}} for p in c.PROFILE_ORDER]
    public=c.public_contract(contexts,'R2-01')
    reject=lambda *a,**k:pytest.fail('fixture is not a genuine source admission')
    ns=m._source(SimpleNamespace(checked_certificate=reject),m._N['_pilot']())
    # Real append_report executes its actual custom-General guard and Boolean formula.
    emitted=ns['group_report'].append_report(local,public,tmp_path/'cold.xlsx')
    plan=ns['group_report'].plan(public,local)
    combined={sid:{'annual':[{'year':year,'fiscal_year':2026+year,**{
        field:sum(r[sid]['annual'][year-1][field] for r in reports) for field in c.GROUP_FIELDS}}
        for year in c.YEARS]} for sid in c.SCENARIOS}
    certificate={'mathematical_composition_certified':True,'new_group_source_admitted':False,
        'composition':{'unique_best':True,'winner_objective_pence':3000,'winner_report':combined}}
    expected=ns['group_report'].expectations(certificate,plan)
    frozen={'local_composition':c.write(tmp_path/'local.json',local),'donors':donors,
        'report_plan':c.write(tmp_path/'plan.json',plan),'report_expected':c.write(tmp_path/'expected.json',expected),
        'defined_names':[],'geometry':emitted['geometry']}
    def cache(name,root):
        changed=False
        for node in root.iter(S+'c'):
            if node.find(S+'f')is None:continue
            if name.endswith('ringfenced_group_reporting.xml'):
                value=expected[node.get('r')]
                if value['type']=='boolean':node.set('t','b');text='1'
                else:text=value['value']
            else:
                identity=name.split('/')[2];i=int(identity[-1]);text=str(2*(i*100000+103))
            E.SubElement(node,S+'v').text=text;changed=True
        return changed
    # Explicit test caches exercise typed auditing, never claim a native calculation.
    cached=rewrite(tmp_path/'cold.xlsx',tmp_path/'cached_fixture.xlsx',cache)
    return ns,frozen,tmp_path/'cold.xlsx',cached,custom


def test_actual_append_boolean_and_frozen_formula_audit_branch(m,real_audit_fixture):
    ns,frozen,cold,cached,original=real_audit_fixture
    first=ns['audit_workbook'](cold,frozen,cold=True);second=ns['audit_workbook'](cached,frozen)
    assert first['passed'] and second['passed']
    assert first['formulas_checked']==second['formulas_checked']==304
    assert ns['stream_composition'].syntax is m.stream._N['syntax']
    assert not hasattr(m.stream,'syntax')
    with ZipFile(cold) as a,ZipFile(original) as b:
        assert a.read('xl/styles.xml')==b.read('xl/styles.xml')
    assert ns['audit_workbook'].__code__.co_code==m._N['_pilot']()._N['audit_workbook'].__code__.co_code
    assert ns['audit_workbook'].__globals__ is ns


@pytest.mark.parametrize('change',['formula','given','boolean_type','extra_formula'])
def test_complete_real_audit_keeps_all_rejection_boundaries(m,real_audit_fixture,tmp_path,change):
    ns,frozen,cold,cached,_=real_audit_fixture;S='{'+m.stream.S+'}';changed=False
    def mutate(name,root):
        nonlocal changed
        if changed:return False
        for node in root.iter(S+'c'):
            if change=='formula' and node.get('r')=='H1' and node.find(S+'f')is not None:node.find(S+'f').text='C5*3'
            elif change=='given' and node.get('r')=='A1' and '/funds/' in name:
                node.set('t','inlineStr');node.find(S+'is').find(S+'t').text='changed'
            elif change=='boolean_type' and name.endswith('ringfenced_group_reporting.xml') and node.get('r')=='B6':node.attrib.pop('t')
            elif change=='extra_formula' and node.get('r')=='A2' and '/funds/' in name:
                for child in list(node):node.remove(child)
                node.attrib.pop('t',None);E.SubElement(node,S+'f').text='TRUE()';E.SubElement(node,S+'v').text='1'
            else:continue
            changed=True;return True
        return False
    altered=rewrite(cached,tmp_path/(change+'.xlsx'),mutate)
    assert changed
    try:assert ns['audit_workbook'](altered,frozen)['passed'] is False
    except ValueError:pass


def retained(m):
    base=ROOT/'outputs/research/ringfenced_pair_R2_01_same_process_source_revision2_20261101T021000Z'
    if not (base/'composition.json').exists():pytest.skip('completed original pure emission unavailable')
    return m.c.reference(base/'certificate.json'),m.c.reference(base/'composition.json')


def test_actual_retained_metadata_is_bound_without_any_cold_provider(m,monkeypatch):
    cert,local=retained(m)
    monkeypatch.setitem(m._N,'_mint',lambda *a,**k:pytest.fail('no real cold call authorized in tests'))
    result=m._checked_inputs(cert,cert['sha256'],local,local['sha256'])
    assert result['original_workbook']['sha256']=='ca83a345844fbdea57a7e76af0a998dcb90f66e0a5a54d036663fb723000a093'
    assert result['failed_attempt']['sha256']==m.FAILED_SHA


@pytest.mark.parametrize('which',[0,1])
def test_separate_root_SHA_is_mandatory(m,which):
    cert,local=retained(m);hashes=[cert['sha256'],local['sha256']];hashes[which]='0'*64
    with pytest.raises(ValueError,match='separate Root pin'):m._checked_inputs(cert,hashes[0],local,hashes[1])


def test_reuse_never_rewrites_or_requalifies_original_bytes(m,tmp_path):
    cert,local=retained(m);refs=m._checked_inputs(cert,cert['sha256'],local,local['sha256'])
    old=m.c.read(cert);fresh={**old,'created_at':'new pure fixture timestamp'};fresh_ref=m.c.write(tmp_path/'fresh.json',fresh)
    before=m.c.reference(refs['original_workbook']['path']);token=m._REUSE.set(refs)
    try:
        got=m._reuse_composition(old['donors'],tmp_path/'not_written.xlsx',mode='goal',target_count=3044376,
            expected_census={'sheets':740,'formulas':2494656,'nonempty':3547132},
            ancestry={'composition_certificate':fresh_ref,'native_source_or_quality_inherited':False})
    finally:m._REUSE.reset(token)
    assert got['output']==before==m.c.reference(before['path']) and not (tmp_path/'not_written.xlsx').exists()
    assert got['old_source_pass_inherited'] is False and got['full_fresh_cold_audit_still_required'] is True
    assert got['pure_emission_reuse']['composition']==local


@pytest.mark.parametrize('change',['gap','pair','pool','donor','census'])
def test_changed_fresh_genuine_proof_or_geometry_rejected(m,tmp_path,change):
    cert,local=retained(m);refs=m._checked_inputs(cert,cert['sha256'],local,local['sha256']);fresh=deepcopy(m.c.read(cert))
    donors=deepcopy(fresh['donors']);census={'sheets':740,'formulas':2494656,'nonempty':3547132}
    if change=='gap':fresh['composition']['gap_pence']+=1
    if change=='pair':fresh['pair_id']='R2-02'
    if change=='pool':fresh['prospective']={**fresh['prospective'],'sha256':'0'*64}
    if change=='donor':donors.reverse()
    if change=='census':census['formulas']-=1
    f=m.c.write(tmp_path/'fresh.json',fresh);token=m._REUSE.set(refs)
    try:
        with pytest.raises(ValueError,match='fresh genuine whole proof'):
            m._reuse_composition(donors,tmp_path/'no.xlsx',mode='goal',target_count=3044376,expected_census=census,
                ancestry={'composition_certificate':f,'native_source_or_quality_inherited':False})
    finally:m._REUSE.reset(token)


def test_new_kind_and_private_namespace_do_not_mutate_frozen_files(m):
    assert m.KIND.endswith('_revision3') and m.TERMINAL_KIND.endswith('_revision3')
    assert m.c.reference(m.UPSTREAM)['sha256']==m.UPSTREAM_SHA and m.c.reference(m.FROZEN)['sha256']==m.FROZEN_SHA
    assert m._N['_source'] is m._source
    assert m._N['execute_prepared'].__globals__ is m._N
    assert m._N['validate_completed'].__globals__ is m._N

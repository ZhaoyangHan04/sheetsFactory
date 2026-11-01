from copy import deepcopy
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
from sheets_factory.workbook.operating_reports_200 import factory_debug_scaling as f


@pytest.fixture(scope='module')
def retained():
    ancestry, values, core = f._context()
    plans, comparison = f.plan_all(values[0],values[1],values[2],core,values[3],values[4])
    return ancestry, values, core, plans, comparison


def test_all_twenty_different_full_entity_plans_keep_all_core_and_boundary_roots(retained):
    ancestry, values, core, plans, comparison = retained
    assert comparison['passed'] and comparison['points']==93510
    assert len(plans)==20 and [p['case_id'] for p in plans]==list(f.CASE_IDS)
    assert len({f.schema.canonical_sha256(p['DBG_faults']) for p in plans})==20
    assert ancestry['genuine_healthy_goal']['sha256']==f.core.GOAL_SHA256
    for i,plan in enumerate(plans):
        assert plan['seed']==202711301+i
        assert len(plan['selected_extra_entities'])==25+5*i
        assert plan['extra_root_count']==36*(25+5*i)
        assert plan['root_count']==4000+36*(25+5*i)
        assert plan['predicted_complete_D_count']==plan['root_count']
        assert all(plan['DBG_faults'][k]==r for k,r in core['DBG_faults'].items())
        assert all(k in plan['DBG_faults'] for k in f.SENTINELS)
        extras=set(plan['DBG_faults'])-set(core['DBG_faults'])
        assert {k.split('/')[0] for k in extras}==set(plan['selected_extra_entities'])
        assert all(sum(k.startswith(e+'/') for k in extras)==36 for e in plan['selected_extra_entities'])
        assert all(w['healthy_primary']!=w['wrong_primary'] for w in plan['extra_root_witnesses'].values())
        assert any('/2025' in k or '/FY2025/' in k for k in extras)
        assert plan['native_calls']==plan['new_financial_forwards']==plan['model_calls']==0
        assert not plan['qualified'] and plan['actual_D_unknown']


def test_extra_formulas_are_real_business_alternatives_without_common_factor_wrapper(retained):
    _, values, core, plans, _ = retained
    plan=plans[-1];bindings=values[1]['financial'];definition=values[2]
    for key,w in plan['extra_root_witnesses'].items():
        row=plan['DBG_faults'][key];point=row['sheet']+'!'+row['cell']
        assert row['healthy_formula']==definition['formulas'][point]
        assert row['faulty_formula']!=row['healthy_formula']
        assert bindings[key]['role']=='report'
        if key.endswith('/net_margin_percent'):
            d=w['dependency_values'];scale=d['rate_scale']
            assert Fraction(w['healthy_exact'])==Fraction(d['net_income'])/Fraction(d['positive_sales'])*scale
            assert Fraction(w['wrong_exact'])==Fraction(d['positive_sales'])/(Fraction(d['positive_direct_cost'])+Fraction(d['operating_expense']))*scale
            assert Fraction(d['positive_direct_cost'])>0
        else:
            d=w['dependency_values']
            current,base=Fraction(d['positive_current_revenue']),Fraction(d['positive_comparative_revenue'])
            assert current>0 and base>0
            assert Fraction(w['healthy_exact'])==current-base
            assert Fraction(w['wrong_exact'])==current+base


def test_supplied_fact_NA_and_core_overlap_are_not_candidate_extras(retained):
    _,values,core,plans,_=retained
    b=values[1]
    protected={f._point(r) for name in ('provided_facts','provided_context') for r in b[name].values()}
    for plan in plans:
        assert all(f._point(r) not in protected for r in plan['DBG_faults'].values())
        assert all(b['financial'][k]['role']=='report' for k in plan['DBG_faults'])


@pytest.mark.parametrize('problem',['core_missing_boundary','core_wrong_healthy','duplicate_physical','given_overlap','wrong_spec'])
def test_scope_integrity_rejects_drift_before_any_output(retained,problem):
    _,values,core,_,_=retained
    public,b,d,A,B=values
    b=deepcopy(b);core=deepcopy(core)
    if problem=='core_missing_boundary':core['DBG_faults'].pop(next(iter(f.SENTINELS)))
    elif problem=='core_wrong_healthy':next(iter(core['DBG_faults'].values()))['healthy_formula']='=123'
    elif problem=='duplicate_physical':
        keys=list(b['financial']);b['financial'][keys[1]]=deepcopy(b['financial'][keys[0]])
    elif problem=='given_overlap':b['provided_context']['forged']=deepcopy(next(iter(b['financial'].values())))
    else:public=deepcopy(public);public['entities'][0]['name']='Changed company'
    with pytest.raises(ValueError):f.plan_all(public,b,d,core,A,B)


def _book(path):
    ns=f.NS
    with ZipFile(path,'x',ZIP_DEFLATED) as z:
        z.writestr('xl/workbook.xml',f'<workbook xmlns="{ns[1:-1]}" xmlns:r="{f.REL[1:-1]}"><sheets><sheet name="Owner\'s report" sheetId="1" r:id="r1"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Target="worksheets/sheet1.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml',f'<worksheet xmlns="{ns[1:-1]}"><sheetData><row r="1"><c r="A1" s="2"><f>B1/C1</f><v>0.25</v></c><c r="B1" s="3"><v>20</v></c><c r="C1"><v>80</v></c><c r="D1" t="inlineStr"><is><t>n/a</t></is></c><c r="E1" t="b"><v>1</v></c><c r="F1" t="b"><f>B1&gt;0</f><v>1</v></c></row></sheetData></worksheet>')
        z.writestr('xl/styles.xml',b'original styles bytes')
        z.writestr('custom/notes.xml',b'original notes bytes')


def test_OOXML_surgery_only_fault_formulas_all_caches_cold_literals_styles_objects_preserved(tmp_path):
    source=tmp_path/'goal.xlsx';_book(source);before=source.read_bytes()
    faults={'margin':{'sheet':"Owner's report",'cell':'A1','healthy_formula':'=B1/C1','faulty_formula':'=B1/(C1+B1)'}}
    output=tmp_path/'input.xlsx';result=f._emit_workbook(source,output,faults)
    assert source.read_bytes()==before
    assert result['changed_formula_count']==1 and result['formula_count']==2 and result['formula_cache_count']==0
    with ZipFile(source) as old,ZipFile(output) as new:
        assert old.namelist()==new.namelist()
        assert all(old.read(n)==new.read(n) for n in old.namelist() if n!='xl/worksheets/sheet1.xml')
        tree=ET.fromstring(new.read('xl/worksheets/sheet1.xml'));cells={c.attrib['r']:c for c in tree.iter(f.NS+'c')}
        assert cells['A1'].find(f.NS+'f').text=='B1/(C1+B1)'
        assert cells['A1'].attrib['s']=='2'
        assert cells['E1'].attrib['t']=='b' and cells['E1'].find(f.NS+'v').text=='1'
        assert cells['D1'].find(f.NS+'is').find(f.NS+'t').text=='n/a'
        assert all(c.find(f.NS+'v') is None and 't' not in c.attrib for c in cells.values() if c.find(f.NS+'f') is not None)
    with pytest.raises(FileExistsError):f._emit_workbook(source,output,faults)


@pytest.mark.parametrize('point,healthy',[('B1','=20'),('A1','=WRONG'),('Z99','=1')])
def test_surgery_rejects_fact_replacement_changed_healthy_or_missing_cell(tmp_path,point,healthy):
    source=tmp_path/'goal.xlsx';_book(source)
    faults={'bad':{'sheet':"Owner's report",'cell':point,'healthy_formula':healthy,'faulty_formula':'=1'}}
    with pytest.raises(ValueError):f._emit_workbook(source,tmp_path/'input.xlsx',faults)


def test_public_brief_covers_all_reports_without_root_or_algorithm_tutorial():
    assert 'all management reports' in f.BRIEF
    assert all(word not in f.BRIEF.lower() for word in ('4000','margin','root','formula','associate','growth','seed'))
    assert f.CASE_IDS[0]=='DBG-S01' and f.CASE_IDS[-1]=='DBG-S20'


def test_import_has_no_financial_forward_calls():
    import ast
    tree=ast.parse(Path(f.__file__).read_text())
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in ('solve','build_spec','forward') for n in ast.walk(tree))


def test_factory_API_exact_original_inputs_and_all20_returned(retained):
    ancestry, values, core, existing, _ = retained
    public,bindings,definition,A,B=values
    original=f.read(ancestry['original_view_plans'])
    assert f.design_all(public,bindings,definition,original)==existing
    changed=deepcopy(original);changed['FM_mask'].pop()
    with pytest.raises(ValueError,match='exact original'):
        f.design_all(public,bindings,definition,changed)


def test_factory_emit_rejects_wrong_goal_before_creating_directory(retained,tmp_path):
    ancestry,values,core,plans,_=retained
    public,bindings,definition,A,B=values
    fake=tmp_path/'wrong_goal.xlsx';fake.write_bytes(b'not the original goal')
    out=tmp_path/'never_created'
    with pytest.raises(ValueError,match='exact healthy goal'):
        f.emit(fake,public,bindings,definition,f.read(ancestry['original_view_plans']),plans[0],out)
    assert not out.exists()

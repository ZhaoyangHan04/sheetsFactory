"""Pure small business/proof/package fixtures; never native or financial forwards."""
from copy import deepcopy
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import openpyxl
import pytest

from sheets_factory.workbook.linear_capital_ringfenced_pairs import contract as c, composition as m
from sheets_factory.workbook.linear_capital_ringfenced_pairs import stream_composition as s, group_report as g
from sheets_factory.workbook.linear_capital_ringfenced_group import stream_composition as old_stream
from sheets_factory.workbook import heterogeneous_native_merge as old_syntax


def contexts():
    return [{'profile_id':p,'specification':{'toy':p}} for p in c.PROFILE_ORDER]


def locals_(gaps=(7,3)):
    rows=[]
    for i,(identity,gap) in enumerate(zip(c.MANDATE_ORDER,gaps,strict=True),1):
        def report(offset):
            return {sid:{'annual':[{'year':y,'fiscal_year':2026+y,
                **{f:(i*10000+k*1000+y*10+j+offset)*(-1 if f=='net_lp_cashflow' else 1)
                for j,f in enumerate(c.GROUP_FIELDS)}} for y in c.YEARS]} for k,sid in enumerate(c.SCENARIOS)}
        rows.append({'id':identity,'profile_id':c.PROFILE_ORDER[i-1],'gap_pence':gap,
            'best':{'objective_pence':1000*i,'plan':{'P001':1,'P002':0},'report_A':report(0),'report_B':report(0)},
            'runner':{'objective_pence':1000*i-gap,'plan':{'P001':0,'P002':1},'report_A':report(3),'report_B':report(3)}})
    return rows


@pytest.mark.parametrize('gaps',[(7,3),(2,2),(1,9)])
def test_exact_cartesian_best_runner_and_ties(gaps):
    rows=locals_(gaps);a=m.compose_values_a(rows);assert a==m.compose_values_b(rows)
    ranked=sorted((sum(r['best' if k==0 else 'runner']['objective_pence']-(11 if k==2 else 0)
        for r,k in zip(rows,bits,strict=True)),bits) for bits in product(range(3),repeat=2))
    assert ranked[-1]==(a['winner_objective_pence'],(0,0)) and ranked[-2][0]==a['runner_objective_pence']
    assert a['minimum_gap_mandates']==[c.MANDATE_ORDER[i] for i,gap in enumerate(gaps) if gap==min(gaps)]
    assert a['gap_pence']==min(gaps) and a['unique_best']
    assert sum(a['canonical_runner_plan'][k]!=a['winner_plan'][k] for k in c.MANDATE_ORDER)==1
    for sid in c.SCENARIOS:
        for yi in range(20):
            for f in c.GROUP_FIELDS:assert a['winner_report'][sid]['annual'][yi][f]==sum(r['best']['report_B'][sid]['annual'][yi][f] for r in rows)


@pytest.mark.parametrize('bad',[0,-1,True,.5])
def test_nonpositive_or_noninteger_gap_is_not_a_certificate(bad):
    rows=locals_();rows[0]['gap_pence']=bad
    for fn in (m.compose_values_a,m.compose_values_b):
        with pytest.raises(ValueError):fn(rows)


def test_noninteger_aggregate_or_identical_runner_rejects():
    for fn in (m.compose_values_a,m.compose_values_b):
        rows=locals_();rows[0]['runner']['plan']=deepcopy(rows[0]['best']['plan'])
        with pytest.raises(ValueError):fn(rows)
        rows=locals_()
        for r in rows:
            for side in ('report_A','report_B'):r['best'][side]['S01']['annual'][0]['asset_nbv']=2**52
        with pytest.raises(ValueError,match='exact integers'):fn(rows)


def test_fixed_ten_pairs_have_original_contexts_twice_and_no_fungibility():
    assert len(c.PAIRS)==10 and c.PAIRS[0]==('R2-01','L360-P01','L360-P02')
    assert len({frozenset(p[1:]) for p in c.PAIRS})==10
    assert all(sum(p in pair[1:] for pair in c.PAIRS)==2 for p in c.PROFILE_ORDER)
    public=c.public_contract(contexts(),'R2-01')
    assert public['group_projects']==720 and public['group_local_integer_rows']==1882
    assert public['policies']['cross_mandate_binding_constraints']==[]
    assert not public['policies']['capital_fungible_between_mandates']
    assert not public['policies']['intermandate_tax_or_loss_netting']
    assert not public['coupled_720_project_MIP_claimed']
    with pytest.raises(ValueError):c.public_contract(contexts()[::-1],'R2-01')
    with pytest.raises(ValueError):c.public_contract(contexts(),'unknown')


F='IF((Portfolio!$B$3=1),SUMPRODUCT(Portfolio!$B$6:$B$365,Portfolio!$N$6:$N$365,--((Projects!$C$2:$C$361="R01"))),"")'
D={'sheet_map':{'Projects':'P01 - Projects','Portfolio':'P01 - Portfolio'},'names':{}}


@pytest.mark.parametrize('column,code',[('C',f'R{i:02d}') for i in range(1,7)]+[('D',f'C{i:02d}') for i in range(1,9)])
def test_actual_failed_formula_and_only_declared_category_leaves_roundtrip(column,code):
    formula=F.replace('$C$2:$C$361',f'${column}$2:${column}$361').replace('R01',code)
    with pytest.raises(old_syntax.UnsupportedWorkbook):old_stream._formula(formula,D,'Constraints')
    rewritten=s._formula(formula,D,'Constraints')
    assert '"'+code+'"' in rewritten and "'P01 - Projects'!" in rewritten
    assert 'P01 - Portfolio' in rewritten


@pytest.mark.parametrize('formula',[
    F.replace('R01','R07'),F.replace('R01','C01'),F.replace('Projects!$C$2:$C$361','Projects!$D$2:$D$361'),
    F.replace('Projects!$C$2:$C$361','Portfolio!$C$2:$C$361'),F.replace('"R01"','"R01"&"x"'),
    'INDIRECT("R01")','ADDRESS(1,1)','IF(TRUE(),"R01","")','"R01"',
    F.replace('Projects!','[external.xlsx]Projects!'),F.replace('SUMPRODUCT(','SUM(')])
def test_unknown_context_dynamic_or_external_address_remains_closed(formula):
    with pytest.raises((ValueError,old_syntax.UnsupportedWorkbook)):s._formula(formula,D,'Constraints')


def test_whole_ten_preflight_is_before_any_cold_provider_or_output(tmp_path,monkeypatch):
    visits=[];frozen={'contexts':contexts(),'contracts':{'R2-01':{'toy':'contract'}},'_reference':{'toy':'prospective'}}
    monkeypatch.setattr(c,'validate_prospective',lambda _:frozen)
    monkeypatch.setattr(c,'ROOT',tmp_path)
    def preflight(_):visits.append('all10');return {'all_ten_donors_checked_before_hydration':True}
    monkeypatch.setattr(s,'preflight_all',preflight)
    def fail():visits.append('cold');raise ValueError('genuine provider rejected')
    monkeypatch.setattr(m,'_providers',fail)
    out=tmp_path/'outputs/certificate'
    with pytest.raises(ValueError,match='genuine provider'):m.build_certificate({'passed':True},out)
    assert visits==['all10','cold'] and not out.exists()
    monkeypatch.setattr(s,'preflight_all',lambda _:(_ for _ in ()).throw(ValueError('tenth donor syntax held')))
    visits.clear()
    with pytest.raises(ValueError,match='tenth donor'):m.build_certificate({'passed':True},out)
    assert visits==[] and not out.exists()


def test_preflight_visits_all_ten_in_fixed_order_and_never_returns_partial_success(monkeypatch):
    rows=[{**r,'workbook':{'fixture':r['profile_id']}} for r in contexts()];seen=[]
    monkeypatch.setattr(c,'validate_prospective',lambda _:{'contexts':rows})
    monkeypatch.setattr(c,'read',lambda _:{'region_ids':[f'R{i:02d}' for i in range(1,7)],'sector_ids':[f'C{i:02d}' for i in range(1,9)]})
    monkeypatch.setattr(c,'recipes',lambda:{'fixture':'no_services'})
    monkeypatch.setattr(s,'_load',lambda donors:donors)
    def scan(donor):
        seen.append(donor['profile_id'])
        return {'profile_id':donor['profile_id'],'sheets':370,'physical_formulas':1247328,'business_criterion_sites':280}
    monkeypatch.setattr(s,'_scan',scan)
    report=s.preflight_all({'fixture':'prospective'})
    assert seen==list(c.PROFILE_ORDER) and report['total_physical_formulas']==12473280
    assert report['all_ten_donors_checked_before_hydration']
    def failed(donor):
        if donor['profile_id']==c.PROFILE_ORDER[-1]:raise ValueError('last syntax hold')
        return scan(donor)
    monkeypatch.setattr(s,'_scan',failed)
    with pytest.raises(ValueError,match='last syntax'):s.preflight_all({'fixture':'prospective'})


def test_no_old_module_globals_changed_and_whole_evidence_gate_stays_genuine():
    assert old_stream.syntax is old_syntax and old_stream.LIMITS['formulas']==5200000
    called=[]
    def fail(_):called.append('reference');raise ValueError('strict original reference required')
    with pytest.raises(ValueError,match='strict original'):
        m._N['_hydrate']({'reference':{'passed':True}},SimpleNamespace(validate_completed=fail),
            SimpleNamespace(validate_source=lambda _:pytest.fail('Source must follow the complete reference')))
    assert called==['reference']


def toy_donors(tmp_path):
    donors=[]
    for identity,prefix in [('M01','P01 - '),('M02','P02 - ')]:
        book=openpyxl.Workbook();book.active.title='Projects';book.create_sheet('Portfolio');book.create_sheet('Constraints');book.create_sheet('GroupSummary')
        book['Projects']['C2']='R01';book['Projects']['D2']='C01';book['Projects']['A1']='N/A (provided)'
        book['Portfolio']['B3']=1;book['Portfolio']['B369']=1;book['Portfolio']['B370']=100
        book['Portfolio']['B6']=True;book['Constraints']['B303']='='+F
        path=tmp_path/(identity+'.xlsx');book.save(path);book.close()
        donors.append({'id':identity,'prefix':prefix,'workbook':c.reference(path)})
    return donors


def test_real_toy_package_preserves_facts_styles_and_clears_all_formula_caches(tmp_path):
    donors=toy_donors(tmp_path);before=deepcopy(donors);out=tmp_path/'combined.xlsx'
    result=s.compose_toy(donors,out)
    assert before==donors and result['sheet_count']==8 and result['geometry']['formulas']==2
    book=openpyxl.load_workbook(out,data_only=False);values=openpyxl.load_workbook(out,data_only=True)
    for prefix in ('P01 - ','P02 - '):
        assert book[prefix+'Projects']['C2'].value=='R01'
        assert book[prefix+'Projects']['A1'].value=='N/A (provided)'
        assert book[prefix+'Portfolio']['B6'].value is True
        assert '"R01"' in book[prefix+'Constraints']['B303'].value
        assert values[prefix+'Constraints']['B303'].value is None
    book.close();values.close()
    with ZipFile(out) as archive:
        for name in archive.namelist():
            if '/worksheets/' in name and name.endswith('.xml'):
                from xml.etree import ElementTree as X
                for node in X.fromstring(archive.read(name)).iter('{'+s.S+'}c'):
                    if node.find('{'+s.S+'}f') is not None:assert node.find('{'+s.S+'}v') is None and node.find('{'+s.S+'}is') is None


def test_complete_two_donor_report_has302_independent_targets():
    public=c.public_contract(contexts(),'R2-01')
    composed={'donors':[{'id':r['id'],'prefix':r['sheet_prefix'],
        'sheet_map':{name:r['sheet_prefix']+name for name in ('Portfolio','GroupSummary')}} for r in public['mandates']]}
    plan=g.plan(public,composed);assert len(plan['formulas'])==len(plan['financial'])==302
    assert plan['added_geometry']=={'sheets':1,'formulas':302,'nonempty':439,'targets':302}
    cert={'mathematical_composition_certified':True,'new_group_source_admitted':False,'composition':m.compose_values_a(locals_())}
    expected=g.expectations(cert,plan);assert len(expected)==302 and expected['B6']=={'type':'boolean','value':True}
    assert plan['formulas']['B7'].count('B370')==2
    assert plan['formulas']['C10'].count('GroupSummary')==2


def test_appended_two_donor_report_preserves_every_original_local_part(tmp_path):
    local=s.compose_toy(toy_donors(tmp_path),tmp_path/'locals.xlsx')
    public=c.public_contract(contexts(),'R2-01')
    result=g.append_report(local,public,tmp_path/'reported.xlsx')
    assert result['sheet_count']==9 and result['geometry']['formulas']==304
    assert result['geometry']['nonempty']==local['geometry']['nonempty']+439
    assert result['all_local_sheet_parts_byte_identical'] and result['report_formulas_uncached']
    assert not result['private_expected_values_embedded']
    with ZipFile(tmp_path/'locals.xlsx') as before,ZipFile(tmp_path/'reported.xlsx') as after:
        for name in before.namelist():
            if name.startswith('xl/worksheets/'):assert before.read(name)==after.read(name)

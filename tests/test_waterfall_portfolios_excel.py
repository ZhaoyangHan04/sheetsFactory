"""Small complete expression graphs; no native spreadsheet or network calls."""
import ast
from collections import Counter
from datetime import date
from fractions import Fraction
import json
from pathlib import Path

from openpyxl import load_workbook
import pytest

from sheets_factory.workbook.waterfall_portfolios_v1 import excel, oracle_a, raw, schema


def _read(ref):return json.loads(Path(ref['path']).read_text())


@pytest.fixture(scope='module')
def emitted(tmp_path_factory):
    root=tmp_path_factory.mktemp('waterfall_native_toy')
    public=raw.build_spec(dimension_mode='toy',fund_numbers=[2,5,10,13],years=[2026,2027],scenario_ids=['BASE','DOWN'])
    # Explicit mathematical toy: at least one future paid-preference state alongside shortfalls.
    for scenario in public['funds'][0]['scenarios']:
        scenario['periods'][1]['realization_receipts_pence']=2*public['funds'][0]['commitment_pence']
    receipt=_read(excel.emit(public,root/'emission'))
    return public,receipt,_read(receipt['bindings']),_read(receipt['definition'])


def _round(x,places=0):
    value=Fraction(x)*10**places;sign=-1 if value<0 else 1;value=abs(value)
    integer=(2*value.numerator+value.denominator)//(2*value.denominator)
    return Fraction(sign*integer,10**places)


def _evaluator(bindings):
    memo={p:r['value'] for p,r in bindings['provided'].items()};active=set()
    def get(point):
        if point in memo:return memo[point]
        assert point not in active,('cyclic native definition',point)
        active.add(point);value=calc(bindings['financial'][point]['expression']);active.remove(point);memo[point]=value
        return value
    def calc(x):
        if type(x) is int:return Fraction(x)
        if isinstance(x,str):return get(x)
        op,*items=x
        if op=='if':return calc(items[1]) if calc(items[0]) else calc(items[2])
        v=[calc(y) for y in items]
        if op=='add':return sum(v,Fraction())
        if op=='sub':return v[0]-v[1]
        if op=='mul':return v[0]*v[1]
        if op=='div':return v[0]/v[1]
        if op=='round':return _round(v[0],int(v[1]))
        if op=='min':return min(v)
        if op=='max':return max(v)
        if op=='quotient':return Fraction(int(v[0]/v[1]))
        if op=='date':return Fraction((date(*map(int,v))-date(1899,12,30)).days)
        if op=='gt':return v[0]>v[1]
        if op=='or':return any(v)
        raise AssertionError(op)
    return get


def _expected(record,result):
    r=result['rows'][record['row_key']] if 'row_key' in record else result['aggregates'][record['aggregate_key']]
    value=r[record['field']];projection=record['projection']
    if projection=='bool':return value
    if projection=='ratio2dp':return _round(Fraction(value['numerator'],value['denominator']),2)
    out=Fraction(value)*record['sign']
    if projection=='GBP' or record.get('unit')=='GBP':out/=100
    return out


def test_all_small_native_financial_expressions_match_independent_A(emitted):
    public,receipt,binding,definition=emitted
    result=oracle_a.solve(public);evaluate=_evaluator(binding)
    assert len(binding['financial'])==2240
    for point,record in binding['financial'].items():
        actual=evaluate(point);expected=_expected(record,result)
        assert actual==expected,(point,record,actual,expected)
        if record['projection']=='bool':assert type(actual) is bool
    assert result['proof']['state_counts']['preference_paid']>0


def test_real_four_layouts_roundtrip_and_exact_geometry(emitted):
    public,receipt,binding,definition=emitted
    assert {f['layout'] for f in public['funds']}==set(schema.LAYOUTS)
    assert receipt['sheet_count']==20 and receipt['formula_count']==2240
    assert receipt['FM_mask_count']==1120 and receipt['DBG_root_count']==8
    assert len(definition['formulas'])==2240 and len(definition['sheetnames'])==20
    source=load_workbook(receipt['source']['path'],data_only=False)
    assert source.sheetnames==definition['sheetnames']
    for p,r in binding['financial'].items():
        sheet,cell=p.rsplit('!',1);assert source[sheet][cell].value==r['formula']==definition['formulas'][p]
    assert source.calculation.iterate is False
    source.close()


def test_each_row_has_all130_and_aggregate_has40_distinct_projections(emitted):
    _,_,binding,_=emitted;rows={};aggregates={}
    for point,r in binding['financial'].items():
        assert point==r['sheet']+'!'+r['cell']
        target=rows.setdefault(r['row_key'],[]) if 'row_key' in r else aggregates.setdefault(r['aggregate_key'],[])
        target.append(r)
    assert len(rows)==16 and len(aggregates)==4
    for records in rows.values():
        assert len(records)==130
        assert Counter(r['projection'] for r in records)=={'pence':56,'GBP':56,'presentation_sign':16,'ratio2dp':1,'bool':1}
        for unit in ('pence','GBP'):
            uses=[r for r in records if r['projection']=='presentation_sign' and r['unit']==unit]
            assert {r['metric'] for r in uses}==set(excel.USES) and len(uses)==8
    for records in aggregates.values():assert Counter(r['projection'] for r in records)=={'pence':20,'GBP':20}


def test_every_raw_fact_and_context_literal_is_exact_in_all_three_books(emitted):
    public,receipt,binding,definition=emitted
    def path_value(path):
        current=public
        for key in path:current=current[key]
        return current
    for r in binding['provided'].values():
        if 'path' in r:assert path_value(r['path'])==r['value']
        else:assert r['contextkind'] in ('label','layout','policy')
    sources=[receipt['source'],*(v['input'] for v in receipt['views'].values())]
    for file in sources:
        wb=load_workbook(file['path'],data_only=False)
        for point,r in binding['provided'].items():
            sheet,addr=point.rsplit('!',1);value=wb[sheet][addr].value
            assert value==r['value'] and type(value) is type(r['value']),(point,value,r)
            assert definition['literals'][point]['value']==value
        wb.close()
    required_paths=[]
    for fi,f in enumerate(public['funds']):
        for name,value in f.items():
            if name=='scenarios':continue
            if isinstance(value,list):required_paths.extend([['funds',fi,name,j] for j in range(len(value))])
            else:required_paths.append(['funds',fi,name])
        for si,s in enumerate(f['scenarios']):
            for yi,period in enumerate(s['periods']):required_paths.extend([['funds',fi,'scenarios',si,'periods',yi,name] for name in period])
    observed={tuple(r['path']) for r in binding['provided'].values() if 'path' in r}
    assert all(tuple(p) in observed for p in required_paths)


def test_FM_masks_every_forecast_helper_use_alias_GBP_ratio_and_bool(emitted):
    _,receipt,binding,definition=emitted
    wb=load_workbook(receipt['views']['financial_modeling']['input']['path'],data_only=False)
    masked=set(definition['FM_mask_points']);assert len(masked)==1120
    for point,r in binding['financial'].items():
        sheet,addr=point.rsplit('!',1);year=int((r.get('row_key') or r['aggregate_key']).rsplit('/',1)[1])
        assert (point in masked)==(year==2027)
        assert wb[sheet][addr].value==(None if point in masked else r['formula'])
    assert excel._cache_census(receipt['views']['financial_modeling']['input']['path'])==1120
    wb.close()


def test_DBG_only_flips_all_fixed_forecast_preference_use_operators(emitted):
    public,receipt,binding,definition=emitted
    wb=load_workbook(receipt['views']['debugging']['input']['path'],data_only=False)
    roots={r['sheet']+'!'+r['cell']:r for r in binding['DBG_root_edits']}
    assert len(roots)==8
    for point,r in binding['financial'].items():
        sheet,addr=point.rsplit('!',1)
        assert wb[sheet][addr].value==(roots[point]['after'] if point in roots else r['formula'])
    for edit in roots.values():
        row_key=edit['row_key'];fid=row_key.split('/')[0]
        f=next(f for f in public['funds'] if f['id']==fid)
        aliases=[(p,r) for p,r in binding['financial'].items() if r.get('row_key')==row_key and r.get('metric')=='preference_cash_use' and r.get('unit')=='pence']
        assert len(aliases)==1;point,alias=aliases[0]
        assert alias['sign']==(-1 if f['fund_ledger_sign']=='signed_cash_uses' else 1)
        assert edit['before']!=edit['after'] and "'"+point.rsplit('!',1)[0]+"'!"+point.rsplit('!',1)[1] in edit['before']
        assert binding['financial'][edit['sheet']+'!'+edit['cell']]['field']=='after_preference_cash'
    wb.close()


def test_goal_and_both_inputs_have_no_formula_caches_or_financial_result_seed(emitted):
    _,receipt,_,_=emitted
    assert excel._cache_census(receipt['source']['path'])==2240
    assert excel._cache_census(receipt['views']['debugging']['input']['path'])==2240
    for file in [receipt['source'],*(r['input'] for r in receipt['views'].values())]:
        wb=load_workbook(file['path'],data_only=True)
        assert not any(c.data_type=='e' for ws in wb for row in ws for c in row)
        wb.close()
    assert receipt['all_formula_caches_absent'] and receipt['independent_financial_expected_in_workbook'] is False
    assert receipt['qualified'] is False and receipt['model_LO_solver_calls']==0 and receipt['actual_D_unknown'] is True
    tree=ast.parse(Path(excel.__file__).read_text())
    assert not any('oracle' in ast.unparse(n) for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom)))


def test_ratio_and_boolean_display_never_drive_postings_and_have_correct_formats(emitted):
    _,receipt,binding,_=emitted
    only_reports={p for p,r in binding['financial'].items() if r['projection'] in ('ratio2dp','bool')}
    def refs(x):
        if isinstance(x,str):return {x}
        if isinstance(x,(list,tuple)):return set().union(*(refs(v) for v in x[1:]))
        return set()
    wb=load_workbook(receipt['source']['path'],data_only=False)
    for point,r in binding['financial'].items():
        assert not refs(r['expression'])&only_reports
        sheet,addr=point.rsplit('!',1);fmt=wb[sheet][addr].number_format
        if r['projection']=='bool':assert fmt=='General'
        if r['projection']=='ratio2dp':assert r['formula'].startswith('=ROUND(') and fmt==excel.MONEY_FORMAT
        if r['projection']=='GBP' or r.get('unit')=='GBP':assert fmt==excel.MONEY_FORMAT
        assert 'DATEVALUE' not in r['formula']
    assert any('DATE(' in r['formula'] for r in binding['financial'].values())
    wb.close()


def test_public_brief_has_ordinary_business_scope_and_scenario_history_clarification(emitted):
    _,receipt,binding,_=emitted
    policy=' '.join(r['value'] for r in binding['provided'].values() if r.get('contextkind')=='policy')
    assert 'Each scenario is an independent cash path' in policy and 'provided scenario reports' in policy
    for mode in receipt['views']:
        text=Path(receipt['views'][mode]['instruction']['path']).read_text()
        assert '/app/output.xlsx' in text
        assert all(s not in text for s in ('1296','after_preference_cash','double allocation','official','source code','root coordinates'))


def test_no_overwrite_and_formula_cap_fail_closed(tmp_path):
    public=raw.build_spec(dimension_mode='toy',years=[2027])
    with pytest.raises(ValueError,match='formula geometry'):excel.emit(public,tmp_path/'capped',max_formulas=1)
    with pytest.raises(ValueError,match='fresh real'):excel.emit(public,tmp_path/'capped')


def test_native_graph_leap_year_opening_unpaid_compounding_rollforward(tmp_path):
    public=raw.build_spec(dimension_mode='toy',fund_numbers=[2],years=[2027,2028])
    receipt=_read(excel.emit(public,tmp_path/'leap_compound'))
    binding=_read(receipt['bindings']);evaluate=_evaluator(binding);result=oracle_a.solve(public)
    first=result['rows']['F002/BASE/2027'];second=result['rows']['F002/BASE/2028']
    assert first['closing_unpaid_preference']>0
    assert second['opening_unpaid_preference']==first['closing_unpaid_preference']
    for point,record in binding['financial'].items():assert evaluate(point)==_expected(record,result)
    assert any('DATE(' in record['formula'] and record.get('row_key')=='F002/BASE/2028'
               for record in binding['financial'].values())


def test_declared_production_counts_are_arithmetic_not_a_production_emission():
    assert 24*20*3*130+20*3*40==189600
    assert 24*18*3*130+18*3*40==170640
    assert 24*18*3==1296

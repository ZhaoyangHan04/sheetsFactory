from copy import deepcopy
from fractions import Fraction as F
import importlib.util
import json
from pathlib import Path
import pytest
from sheets_factory.workbook.operating_reports_200 import schema as s
from sheets_factory.workbook.operating_reports_200 import oracle_a as a
from sheets_factory.workbook.operating_reports_200 import audit, excel, raw

ROOT=Path(__file__).resolve().parents[1]


def toy(layout='quarter_columns'):
    public={'kind':s.KIND,'version':1,'dimension_mode':'toy','seed':s.SEED,'years':list(s.YEARS),'base_currency':'GBP','provenance':'new hypothetical service businesses; no official workbook seed','public_policy':raw.design()['public_policy'],'distribution':{'year':2027,'profit_percent':'20','cagr_percent':'8','q4_yoy_percent':'5'},'divisions':['Advisory'],'entities':[{'id':'E001','name':'Amberwick Advisory','division':'Advisory','line_order':'statement_first'}]}
    e=public['entities'][0]
    e.update(layout=layout,money_unit='GBP',rate_unit='percent_units',statement_sign='positive_deductions',forecast_reference='same_quarter_last_year',driver_form_by_year={'2026':'level_multiple','2027':'level_multiple'},opening={'cash':'1000','investment':'200','debt':'100','capital':'1000','retained_earnings':'100'},actual_sales=dict(zip(s.QUARTERS[:4],('100','110','120','130'))),forecast_sales={p:'1.1'for p in s.QUARTERS[4:]},direct_cost_rate='50',cash_opex={p:'10'for p in s.QUARTERS},annual_interest_rate='8',parent_tax_rate='25',associate_results=dict(zip(s.QUARTERS,['0']*4+['5','-3','7','-2']*2)))
    return public


@pytest.fixture(scope='module')
def production():
    # Deterministic regeneration for tests, never a new case/seed or selection.
    return raw.build_spec()


@pytest.fixture(scope='module')
def production_result(production):
    return a.solve(production)


def test_hand_cash_tax_associate_and_balance():
    public=toy();r=a.solve(public)
    expected={'revenue':'110','direct_cost':'55','operating_expense':'10','interest':'2','pretax_before_associate':'43','current_tax':'43/4','core_net_income':'129/4','associate_income':'5','net_income':'149/4','operating_cash_flow':'129/4','closing_cash':'4675/4','closing_investment':'205','closing_retained_earnings':'1095/4','total_assets':'5495/4','total_liabilities_equity':'5495/4'}
    for field,value in expected.items():assert F(r['economic_exact_values']['E001/2026Q1/'+field]['value'])==F(value)
    assert r['typed_2dp_values']['E001/FY2027/distribution_eligible']=={'type':'boolean','value':True}
    assert r['typed_2dp_values']['E001/FY2027/dividend']=={'type':'number','value':'35.95'}
    assert r['typed_2dp_values']['E001/FY2027/cagr_percent']['value']=='10.00'
    assert r['reconciliation_checks']['passed']
    assert len(r['typed_2dp_values'])==1230


def test_no_tax_credit_and_associate_stays_exempt():
    public=toy();e=public['entities'][0];e['cash_opex']={p:'100'for p in s.QUARTERS}
    r=a.solve(public)
    assert r['economic_exact_values']['E001/2026Q1/current_tax']['value']=='0'
    assert r['economic_exact_values']['E001/2026Q1/net_income']['value']=='-42'
    assert r['economic_exact_values']['E001/2026Q1/operating_cash_flow']['value']=='-47'
    assert r['typed_2dp_values']['E001/FY2027/dividend']['value']=='0.00'


@pytest.mark.parametrize('value,expected',[('1.005','1.01'),('-1.005','-1.01'),('0.004999','0.00'),('-0.0001','0.00')])
def test_half_away_and_zero(value,expected):assert a.rounded(F(value))==expected


def test_independent_physical_units_leave_economic_ledger_identical():
    public=toy();baseline=a.solve(public);other=deepcopy(public);e=other['entities'][0]
    e['money_unit']='GBP_millions';e['rate_unit']='fraction'
    for name in ('opening','actual_sales','cash_opex','associate_results'):
        e[name]={p:raw.decimal(F(v)/1000000)for p,v in e[name].items()}
    for name in ('direct_cost_rate','annual_interest_rate','parent_tax_rate'):e[name]=raw.decimal(F(e[name])/100)
    result=a.solve(other)
    assert baseline['economic_exact_values']==result['economic_exact_values']
    assert result['raw_cell_exact_values']['E001/2026Q1/revenue']['value']=='11/100000'
    assert result['typed_2dp_values']['E001/2026Q1/yoy_percent']['value']=='0.10'
    assert result['typed_2dp_values']['PORTFOLIO/2026Q1/revenue']['value']=='110.00'


def test_schema_rejects_unknown_inputs_nonfinite_and_repeated_identity():
    for mutate in (lambda p:p.update(hidden_gold={}),lambda p:p['entities'][0].update(direct_cost_rate='NaN'),lambda p:p['entities'].append(deepcopy(p['entities'][0]))):
        public=toy();mutate(public)
        with pytest.raises(ValueError):s.validate_spec(public)


def test_real_schema_and_full_production_result(production,production_result):
    import jsonschema
    public=production;r=production_result
    jsonschema.Draft202012Validator(json.loads((ROOT/'config/operating_reports_200_public_spec_schema_v1.json').read_text())).validate(public)
    jsonschema.Draft202012Validator(json.loads((ROOT/'config/operating_reports_200_oracle_result_schema_v1.json').read_text())).validate(r)
    assert len(dict(s.points(public)))==93510
    assert len(r['cagr_proofs'])==418
    # Exercise comparator integrity without presenting a same-oracle copy as B.
    assert audit.compare(public,r,deepcopy(r))['passed']
    bad=deepcopy(r);bad['raw_cell_exact_values'].pop(next(iter(bad['raw_cell_exact_values'])))
    with pytest.raises(ValueError):audit.compare(public,r,bad)
    bad=deepcopy(r);bad['typed_2dp_values']['E001/2026Q1/revenue']['value']='0.00'
    with pytest.raises(ValueError,match='rounding proof'):audit.compare(public,r,bad)
    bad=deepcopy(r);bad['reconciliation_checks']['cash_bridge_residuals'].pop('E001/2025Q1')
    with pytest.raises(ValueError,match='quarterly bridge'):audit.compare(public,r,bad)
    bad=deepcopy(r);key=next(iter(bad['cagr_proofs']));bad['cagr_proofs'][key]['upper_raw']='-1000000'
    with pytest.raises(ValueError):audit.compare(public,r,bad)


def test_raw_single_reservation_and_input_representations(tmp_path):
    # An existing output always blocks before regeneration; no replacement.
    folder=tmp_path/'once';folder.mkdir()
    with pytest.raises(FileExistsError):raw.freeze_spec(folder)
    assert raw.decimal(F(123,1000))=='0.123'
    assert raw.decimal(F(-1,8))=='-0.125'
    with pytest.raises(ValueError):raw.decimal(F(1,3))


@pytest.mark.parametrize('layout',s.LAYOUTS)
def test_six_layouts_full_bindings_native_formulas_NA_and_view_identity(tmp_path,layout):
    from openpyxl import load_workbook
    public=toy(layout);out=tmp_path/layout
    receipt=excel.emit(public,out);census=audit.census(public,out)
    assert census['passed']and census['formula_caches']==0
    assert census['report_positions']==1230
    assert census['DBG_roots']==1
    binding=json.loads((out/'private_bindings.json').read_text())
    source=load_workbook(out/'source_uncalculated.xlsx',data_only=False)
    for key,kind in s.points(public):
        b=binding['financial'][key];cell=source[b['sheet']][b['cell']]
        if kind=='boolean':assert cell.number_format=='General'
        if kind=='text':assert cell.value in(s.NA,s.GROUP_NA)
    for fact in binding['provided_facts'].values():
        cell=source[fact['sheet']][fact['cell']]
        assert cell.value is not None
        if not isinstance(cell.value,str):assert cell.number_format=='0.###############'
    source.close()


def test_emitter_has_no_oracle_import_or_global_financial_caches():
    import ast
    tree=ast.parse(Path(excel.__file__).read_text())
    imports=[n for n in ast.walk(tree)if isinstance(n,(ast.Import,ast.ImportFrom))]
    assert all('oracle'not in ast.unparse(n)for n in imports)
    assert not any(isinstance(n,ast.Global)for n in ast.walk(tree))


def test_declared_production_masks_and_given_NA(production):
    public=production
    types=dict(s.points(public))
    assert sum(v=='text'for v in types.values())==4834
    assert sum(v!='text'and(k.split('/')[1].startswith(('2026','2027'))or k.split('/')[1]in('FY2026','FY2027'))for k,v in types.items())==62322


def test_exact_input_fact_census_and_eligibility_policy(tmp_path):
    from openpyxl import load_workbook
    public=toy();public['entities'][0]['direct_cost_rate']='8.62'
    out=tmp_path/'exact';excel.emit(public,out)
    binding=json.loads((out/'private_bindings.json').read_text())
    workbook=load_workbook(out/'source_uncalculated.xlsx',data_only=False)
    eligible=binding['financial']['E001/FY2027/distribution_eligible']
    formula=workbook[eligible['sheet']][eligible['cell']].value
    assert '*625>='in formula and'*729'in formula and'*20>='in formula and'*21'in formula
    assert 'ROUND'not in formula and'0.000'not in formula
    workbook.close()
    assert audit.census(public,out)['passed']
    first=next(v for v in binding['provided_facts'].values()if v['value']=='8.62')
    first['value']='8.620000000000001'
    (out/'private_bindings.json').write_text(json.dumps(binding))
    with pytest.raises(ValueError,match='exact approved decimal'):audit.census(public,out)


def test_predeclared_sentinels_and_every_fault_has_primary_root_impact(production,production_result):
    design=raw.design();addendum=design['artifacts']['numeric_generation_addendum.json']['value']
    values=production_result['raw_cell_exact_values'];typed=production_result['typed_2dp_values']
    for sentinel in addendum['sentinels']:
        assert typed[sentinel['entity_id']+'/FY2027/distribution_eligible']['value'] is sentinel['expected_growth_gate']
    axes={e['id']:e for e in design['artifacts']['axis_assignment.json']['value']['entities']}
    seen=set()
    for e in production['entities']:
        identity=e['id'];family=axes[identity]['fault_family'];period='2027Q4'if family=='ratio_as_change'else'2026Q1'
        def number(p,f):return F(values[f'{identity}/{p}/{f}']['value'])
        rate={'fraction':F(100),'percent_units':F(1),'basis_points':F(1,100)}[e['rate_unit']]
        if family=='associate_sign':field='net_income';wrong=number(period,'core_net_income')-number(period,'associate_income')
        elif family=='ratio_as_change':field='yoy_percent';wrong=number(period,'revenue')/number('2026Q4','revenue')*100/rate
        elif family=='money_scale':field='revenue';wrong=number(period,'revenue')/1000
        else:
            field='revenue';reference='2025Q1'if e['forecast_reference']=='previous_calendar_quarter'else'2025Q4'
            base=number(reference,'revenue');driver=F(e['forecast_sales'][period]);form=e['driver_form_by_year']['2026']
            wrong=base+driver if form=='money_delta'else base*(1+driver*rate/100)if form=='change_rate'else base*driver if form=='level_multiple'else base*driver/100
        assert a.rounded(wrong)!=typed[f'{identity}/{period}/{field}']['value']
        seen.add((family,e['layout']))
    assert len(seen)==4*6

"""Tiny native formula DAGs checked against both independent financial journals."""
import ast
from copy import deepcopy
from fractions import Fraction
import importlib.util
from pathlib import Path
import re

import openpyxl
from openpyxl.utils import column_index_from_string
import pytest

from sheets_factory.workbook.linear_capital_portfolio import candidate_a, excel, ledger, spec

ROOT=Path(__file__).resolve().parents[1]
loader=importlib.util.spec_from_file_location('linear_excel_hand_primitives',ROOT/'tests/test_linear_capital_portfolio_ledger.py')
inputs=importlib.util.module_from_spec(loader);loader.loader.exec_module(inputs)
REF=re.compile(r"^'((?:[^']|'')+)'!\$([A-Z]+)\$([1-9][0-9]*)(?::\$([A-Z]+)\$([1-9][0-9]*))?$")


def lookup(value,path):
    for part in path:value=value[part]
    return value


def expected(row,result):
    value=lookup(result,row['expected_path'])
    if 'vintage_year' in row:
        matches=[v for v in value if v['year']==row['vintage_year'] and v['origin_year']==row['origin_year']]
        assert len(matches)<=1
        value=matches[0][row['vintage_field']] if matches else 0
    if 'constraint_id' in row:
        matches=[v for v in value if v['id']==row['constraint_id']];assert len(matches)==1
        value=matches[0][row['constraint_field']]
    if value is None:return ''
    return Fraction(int(value)) if isinstance(value,(int,bool)) else value


def evaluate(bindings,public,plan):
    """Test-only exact interpreter; it imports no emitter calculation helper."""
    values={};formulas={(x['sheet'],x['cell']):x for x in bindings['arithmetic_bindings']};visiting=set()
    for row in bindings['input_bindings']:
        value=lookup(public,row['path']);values[row['sheet'],row['cell']]=Fraction(value) if type(value) is int else value
    for row in bindings['literal_bindings']:
        value=row['value'];values[row['sheet'],row['cell']]=Fraction(value) if type(value) is int else value
    for row in bindings['decision_bindings']:
        value=None if plan is None else plan[row['project_id']]
        values[row['sheet'],row['cell']]=None if value is None else Fraction(value)
    def cell(key):
        if key in values:return values[key]
        assert key in formulas, ('unbound physical reference',key)
        assert key not in visiting, ('formula cycle',key)
        visiting.add(key);value=run(formulas[key]['expression']);visiting.remove(key);values[key]=value;return value
    def flatten(value):
        if isinstance(value,list):return [v for item in value for v in flatten(item)]
        return [value]
    def binary(a,b,fn):
        if isinstance(a,list):
            if isinstance(b,list):assert len(a)==len(b);return [binary(x,y,fn) for x,y in zip(a,b)]
            return [binary(x,b,fn) for x in a]
        if isinstance(b,list):return [binary(a,y,fn) for y in b]
        return fn(a,b)
    def numeric(value):return Fraction(0) if value in (None,'') else value
    def run(expr):
        if type(expr) is int:return Fraction(expr)
        if isinstance(expr,str):
            match=REF.fullmatch(expr)
            if not match:return expr
            sheet,a,r,b,z=match.groups();sheet=sheet.replace("''", "'")
            if b:
                return [cell((sheet,openpyxl.utils.get_column_letter(c)+str(y)))
                    for y in range(int(r),int(z)+1) for c in range(column_index_from_string(a),column_index_from_string(b)+1)]
            return cell((sheet,a+r))
        op,*args=expr
        if op=='if':return run(args[1] if run(args[0]) else args[2])
        items=[run(x) for x in args]
        if op in ('eq','lt','le','ge','gt'):
            fn={'eq':lambda a,b:a==b,'lt':lambda a,b:a<b,'le':lambda a,b:a<=b,'ge':lambda a,b:a>=b,'gt':lambda a,b:a>b}[op]
            return binary(items[0],items[1],lambda a,b:Fraction(int(fn(a,b))))
        if op=='flag':return binary(items[0],0,lambda a,_:Fraction(int(bool(a))))
        if op=='and':return Fraction(int(all(flatten(items))))
        if op=='or':return Fraction(int(any(flatten(items))))
        if op=='count':return Fraction(sum(isinstance(v,Fraction) for v in flatten(items)))
        if op=='countif':return Fraction(sum(v==items[1] for v in flatten(items[0])))
        if op=='sumproduct':
            vectors=[flatten(i) for i in items];assert all(len(v)==len(vectors[0]) for v in vectors)
            return sum((__import__('functools').reduce(lambda a,b:a*numeric(b),xs,Fraction(1)) for xs in zip(*vectors)),Fraction())
        nums=[numeric(v) for v in items]
        if op=='sum':return sum((numeric(v) for v in flatten(items)),Fraction())
        if op=='min':return min(nums)
        if op=='max':return max(nums)
        if op in ('sub','mul','div','power'):
            return binary(items[0],items[1],{'sub':lambda a,b:numeric(a)-numeric(b),'mul':lambda a,b:numeric(a)*numeric(b),
                'div':lambda a,b:numeric(a)/numeric(b),'power':lambda a,b:numeric(a)**int(b)}[op])
        if op=='round':
            assert nums[1]==0;v=nums[0];amount=(2*abs(v.numerator)+v.denominator)//(2*v.denominator)
            return Fraction(-amount if v<0 else amount)
        raise AssertionError(op)
    for key in formulas:cell(key)
    return values


def compare_all(bindings,public,plan):
    a=candidate_a.simulate(public,plan);b=ledger.simulate(public,plan);values=evaluate(bindings,public,plan)
    for row in bindings['financial_bindings']:
        want_a=expected(row,a);want_b=expected(row,b)
        assert want_a==want_b, ('independent journal disagreement',row['semantic_role'])
        assert values[row['sheet'],row['cell']]==want_a, (row['sheet'],row['cell'],row['semantic_role'],values[row['sheet'],row['cell']],want_a)
    return a,b,values


def test_all_tiny_formula_fields_three_scenarios_and_joint_constraints_match_both_journals(tmp_path):
    public=inputs.fixture(projects=3,scenarios=3,years=5)
    public['projects'][1].update(debt_policy='BULLET',operating_start_year=2,depreciation_years=20,
        revenue_growth_factor_bp=10500,opex_growth_factor_bp=10250,discount_rate_bp=750)
    public['projects'][2].update(bank_rate_bp=700,t0_ltv_bp=3500,debt_maturity_year=4)
    public['scenarios'][1]['revenue_factors_bp']={str(y):8000 for y in public['years']}
    public['scenarios'][2]['interest_spread_bp']={str(y):250 for y in public['years']}
    public['exclusivity_groups']=[{'id':'SITE','description':'Two mutually exclusive installations','project_ids':['P001','P002']}]
    public['prerequisites']=[{'id':'ENABLE','dependent':'P003','prerequisite':'P001','business_reason':'Access connection'}]
    plan={'P001':1,'P002':0,'P003':1}
    bindings=excel.emit_workbook(tmp_path/'tiny.xlsx',public,plan=plan)
    compare_all(bindings,public,plan)
    assert bindings['constraint_count']==1+2*3*5+3*5+2*5+2


@pytest.mark.parametrize('policy',['LEVEL_PRINCIPAL','BULLET'])
def test_actual_fixed_principal_interest_residual_tax_FIFO_and_final_sale(tmp_path,policy):
    public=inputs.fixture(years=5);p=public['projects'][0]
    p.update(asset_cost_pence=101,depreciation_years=3,debt_policy=policy,debt_maturity_year=3,
        base_annual_opex_pence=20,base_annual_revenue_pence=20,bank_rate_bp=1000,terminal_sale_proceeds_pence=80)
    c=public['scenarios'][0];c['revenue_factors_bp']={str(y):0 if y<4 else 15000 for y in public['years']}
    c['opex_factors_bp']={str(y):10000 if y<3 else 0 for y in public['years']}
    plan={'P001':1};bindings=excel.emit_workbook(tmp_path/'fifo.xlsx',public,plan=plan)
    a,b,_=compare_all(bindings,public,plan)
    assert any(v['expired']>0 for v in a['projects']['P001']['scenarios']['S01']['tax_vintages'])
    assert any(v['used']>0 for v in b['projects']['P001']['scenarios']['S01']['tax_vintages'])


@pytest.mark.parametrize('cost,sale,posted',[(1,3,2),(3,3,-1)])
def test_t0_is_inside_one_positive_or_negative_half_tie_NPV_round(tmp_path,cost,sale,posted):
    public=inputs.fixture(years=1);p=inputs.simple(public)
    p.update(asset_cost_pence=cost,terminal_sale_proceeds_pence=sale,discount_rate_bp=2000)
    plan={'P001':1};bindings=excel.emit_workbook(tmp_path/'half.xlsx',public,plan=plan)
    a,_,_=compare_all(bindings,public,plan)
    assert a['projects']['P001']['scenarios']['S01']['npv_pence']==posted


def test_gap_stays_infeasible_and_nullable_NPV_is_not_fabricated(tmp_path):
    public=inputs.fixture();p=inputs.simple(public);p['lp_commitment_pence']=10
    plan={'P001':1};bindings=excel.emit_workbook(tmp_path/'gap.xlsx',public,plan=plan)
    a,_,values=compare_all(bindings,public,plan)
    assert a['feasible'] is False and a['objective_pence'] is None
    npvs=[r for r in bindings['financial_bindings'] if r['expected_path'][-1]=='npv_pence']
    assert npvs and all(values[r['sheet'],r['cell']]=='' for r in npvs)


def test_zero_plan_keeps_full_candidate_values_but_zeroes_every_selected_group(tmp_path):
    public=inputs.fixture(projects=2,scenarios=3)
    plan={'P001':0,'P002':0};bindings=excel.emit_workbook(tmp_path/'zero.xlsx',public,plan=plan)
    a,_,values=compare_all(bindings,public,plan)
    assert a['objective_pence']==0
    assert any(values[r['sheet'],r['cell']]>0 for r in bindings['financial_bindings']
        if r['semantic_role']['schedule']=='portfolio_candidate_alias' and r['semantic_role']['field']=='lp_call')
    assert all(values[r['sheet'],r['cell']]==0 for r in bindings['financial_bindings'] if r['semantic_role']['schedule']=='selected_group')


def test_blank_choices_do_not_preseed_an_answer_or_claim_a_complete_portfolio(tmp_path):
    public=inputs.fixture(projects=2,scenarios=2);before=deepcopy(public)
    path=tmp_path/'blank.xlsx';bindings=excel.emit_workbook(path,public)
    assert public==before and bindings['plan_supplied'] is False
    book=openpyxl.load_workbook(path,data_only=False)
    assert len(bindings['decision_bindings'])==2
    assert all(book[x['sheet']][x['cell']].value is None and x['value'] is None for x in bindings['decision_bindings'])
    values=evaluate(bindings,public,None)
    assert values['Portfolio','B3']==0
    assert all(values[r['sheet'],r['cell']]=='' for r in bindings['financial_bindings'] if r.get('requires_complete_plan'))
    assert sum(c.data_type=='f' for sheet in book for row in sheet for c in row)==bindings['formula_count']
    assert all(sheet.sheet_state=='visible' for sheet in book)
    assert 'ContractNotes' in book.sheetnames and 'P001' in book.sheetnames and 'P002' in book.sheetnames
    book.close()


def test_every_physical_formula_and_literal_has_disjoint_complete_private_binding(tmp_path):
    public=inputs.fixture(projects=2,years=5);path=tmp_path/'coverage.xlsx'
    bindings=excel.emit_workbook(path,public,plan={'P001':1,'P002':0})
    book=openpyxl.load_workbook(path,data_only=False)
    arith={(r['sheet'],r['cell']):r for r in bindings['arithmetic_bindings']}
    financial={(r['sheet'],r['cell']):r for r in bindings['financial_bindings']}
    assert len(arith)==len(bindings['arithmetic_bindings'])==bindings['formula_count']
    assert set(arith)-set(financial)=={('Portfolio','B3')}
    for key,row in financial.items():
        if row['formula'] is not None:assert arith[key]==row
        else:assert row['expression']==0 or row['semantic_role']['schedule']=='capacity'
    physical={(sheet.title,cell.coordinate):cell for sheet in book for row in sheet for cell in row if cell.value is not None}
    formula={key:cell for key,cell in physical.items() if cell.data_type=='f'}
    assert set(formula)==set(arith)
    assert all(formula[key].value==row['formula'] for key,row in arith.items())
    categories=[set((r['sheet'],r['cell']) for r in bindings[name]) for name in ['arithmetic_bindings','input_bindings','literal_bindings','decision_bindings']]
    assert len(set.union(*categories))==sum(map(len,categories))
    assert set(physical)==set.union(*categories)
    assert all(row['worksheet_scale']==1 for name in ['financial_bindings','input_bindings'] for row in bindings[name])
    assert max(len(cell.value) for cell in formula.values())<=8192
    assert not any('expected_path' in str(cell.value) or 'specification_sha256' in str(cell.value) for cell in physical.values())
    assert bindings['financial_expected_values_embedded'] is False
    book.close()


def test_public_contract_includes_all_twelve_business_rules_and_unambiguous_candidate_units(tmp_path):
    p=tmp_path/'notes.xlsx';bindings=excel.emit_workbook(p,inputs.fixture())
    book=openpyxl.load_workbook(p);notes=[cell.value for row in book['ContractNotes'] for cell in row if cell.value]
    assert all(rule in notes for rule in spec.RULES) and len(spec.RULES)==12
    combined=' '.join(notes).lower()
    assert 'standalone' in combined and 'gbp pence' in combined and 'not selected' in combined
    assert 'same choice in all scenarios' in combined
    assert not any(word in combined for word in ['oracle','difficulty','quality gate','reference correctness'])
    assert bindings['public_rules']==list(excel.PUBLIC_RULES)
    assert any(cell.value=='FY1 / 2027' for row in book['P001'] for cell in row)
    book.close()


def test_sparse_vintage_window_covers_every_independent_event_and_does_not_make_N_squared_grid(tmp_path):
    public=inputs.fixture(years=20);plan={'P001':1};bindings=excel.emit_workbook(tmp_path/'window.xlsx',public,plan=plan)
    result=ledger.simulate(public,plan)
    rows=[r for r in bindings['financial_bindings'] if 'vintage_year' in r]
    expected_events={(v['year'],v['origin_year'],field) for v in result['projects']['P001']['scenarios']['S01']['tax_vintages'] for field in spec.VINTAGE_FIELDS}
    covered={(r['vintage_year'],r['origin_year'],r['vintage_field']) for r in rows}
    assert expected_events<=covered
    assert len(rows)==sum(min(y,5) for y in public['years'])*5==450
    assert all(0<=r['vintage_year']-r['origin_year']<=4 for r in rows)
    compare_all(bindings,public,plan)


def test_unshocked_growth_once_and_terminal_sale_of_undepreciated_NBV(tmp_path):
    public=inputs.fixture(years=4,scenarios=3);p=inputs.simple(public)
    p.update(asset_cost_pence=100,operating_start_year=2,depreciation_years=20,
        base_annual_revenue_pence=101,revenue_growth_factor_bp=10500,terminal_sale_proceeds_pence=80)
    for c in public['scenarios']:
        c['revenue_factors_bp'].update({'2':5000,'3':15000,'4':10000})
    plan={'P001':1};bindings=excel.emit_workbook(tmp_path/'growth.xlsx',public,plan=plan)
    a,_,_=compare_all(bindings,public,plan);rows=a['projects']['P001']['scenarios']['S01']['annual']
    assert [r['revenue_base'] for r in rows]==[0,101,106,111]
    assert [r['revenue'] for r in rows]==[0,51,159,111]
    assert rows[-1]['sale_carrying']==85 and rows[-1]['asset_nbv_close']==0


def test_portfolio_budget_failure_preserves_real_flows_but_no_objective(tmp_path):
    public=inputs.fixture(projects=2);public['shared_limits']['annual_new_lp_pence']['S01']['1']=199
    plan={'P001':1,'P002':1};bindings=excel.emit_workbook(tmp_path/'limited.xlsx',public,plan=plan)
    a,_,values=compare_all(bindings,public,plan)
    assert a['all_standalone_feasible'] is True and a['feasible'] is False and a['objective_pence'] is None
    row=next(r for r in bindings['financial_bindings'] if r.get('constraint_id')=='annual_new_lp:S01:1' and r['constraint_field']=='slack')
    assert values[row['sheet'],row['cell']]==-1


def test_all_four_binary_plans_and_last_toy_project_are_fully_evaluated(tmp_path):
    public=inputs.fixture(projects=2,scenarios=2);public['projects'][1]['base_annual_revenue_pence']=301
    for mask in range(4):
        plan={'P001':mask&1,'P002':(mask>>1)&1}
        bindings=excel.emit_workbook(tmp_path/f'plan-{mask}.xlsx',public,plan=plan)
        compare_all(bindings,public,plan)
    public=inputs.fixture(projects=4,scenarios=3,years=20)
    public['projects'][-1]['base_annual_revenue_pence']=307
    plan={pid:int(pid=='P004') for pid in public['project_ids']}
    bindings=excel.emit_workbook(tmp_path/'last.xlsx',public,plan=plan)
    a,_,_=compare_all(bindings,public,plan)
    assert a['projects']['P004']['scenarios']['S03']['annual'][-1]['revenue']==307
    # Extrapolate only this identical per-project static geometry; no production
    # book or financial path is constructed by this sizing check.
    per_project=sum(row['sheet']=='P004' for row in bindings['arithmetic_bindings'])
    aliases=sum(row['semantic_role']['schedule']=='portfolio_candidate_alias' for row in bindings['financial_bindings'])//4
    complete_production_upper=(per_project+aliases)*240+881*4+3*20*5+4
    assert complete_production_upper<1_000_000


@pytest.mark.parametrize('plan',[{'P001':True},{},{'P001':2}])
def test_invalid_or_partial_plan_never_creates_a_workbook(tmp_path,plan):
    path=tmp_path/'invalid.xlsx'
    with pytest.raises(ValueError):excel.emit_workbook(path,inputs.fixture(),plan=plan)
    assert not path.exists()


def test_complete_scope_cap_fails_before_saving_and_existing_file_is_preserved(tmp_path):
    path=tmp_path/'cap.xlsx'
    with pytest.raises(ValueError,match='no truncation'):excel.emit_workbook(path,inputs.fixture(),max_formulas=3)
    assert not path.exists()
    path.write_bytes(b'old source')
    with pytest.raises(ValueError,match='Preserve'):excel.emit_workbook(path,inputs.fixture())
    assert path.read_bytes()==b'old source'


def test_public_text_is_literal_even_when_its_first_character_is_equals(tmp_path):
    public=inputs.fixture();public['projects'][0]['name']='=A provided project name'
    path=tmp_path/'text.xlsx';bindings=excel.emit_workbook(path,public,plan={'P001':1})
    book=openpyxl.load_workbook(path,data_only=False)
    name=next(row for row in bindings['input_bindings'] if row['path']==['projects',0,'name'])
    assert book[name['sheet']][name['cell']].value=='=A provided project name'
    assert book[name['sheet']][name['cell']].data_type=='s'
    assert sum(cell.data_type=='f' for sheet in book for row in sheet for cell in row)==bindings['formula_count']
    book.close()


def test_emitter_has_no_financial_or_optimization_imports_or_cache_writer():
    text=Path(excel.__file__).read_text();tree=ast.parse(text)
    modules=[n.module or '' for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert not any(any(tag in module for tag in ['candidate_a','ledger','model_a','model_b','solver','optimizer']) for module in modules)
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in
        ('simulate','simulate_project','simulate_universe','solve','solve_cp_sat') for n in ast.walk(tree))
    assert 'data_only=True' not in text and 'cached_value' not in text

"""Pure small AST graphs; no workbook, ledger, cache, or production run."""
from copy import deepcopy
import ast
from pathlib import Path

import pytest

from sheets_factory.workbook.heterogeneous_contracts import policy_specialization as p
from sheets_factory.workbook.heterogeneous_contracts.excel import expression_formula


def ref(sheet,cell):return p._reference({'sheet':sheet,'cell':cell})


@pytest.fixture
def bindings():
    tags=[('loans',0,'type','BULLET_MONTHLY'),('entities',0,'tax_policy','ACCRUAL_MONTHLY'),
          ('entities',0,'dscr_policy','MONTHLY_CURRENT')]
    inputs=[]
    for i,(collection,index,field,value) in enumerate(tags,1):
        inputs.append({'sheet':'Policies','cell':f'B{i}','path':[collection,index,field],
            'kind':'text','worksheet_scale':1,'stored_value':value})
    # Deliberately not interpretable financial/date values: copying and hashing
    # preserve them without treating them as specialization facts.
    inputs.extend([{'sheet':'Assumptions','cell':'B1','path':['opening_money'],
        'kind':'money_pence','worksheet_scale':100,'stored_value':'opaque-money'},
        {'sheet':'Assumptions','cell':'B2','path':['rate'], 'kind':'rate_p12',
         'worksheet_scale':10**12,'stored_value':'opaque-rate'},
        {'sheet':'Assumptions','cell':'B3','path':['date'], 'kind':'date',
         'worksheet_scale':1,'stored_value':'opaque-date'}])
    data={'binding_version':1,'formula_count':0,'sheetnames':['Policies','Assumptions','Contract Notes','Calculations','Reports'],
          'input_bindings':inputs,'literal_bindings':[{'sheet':'Contract Notes','cell':'A1','value':'Keep all legal policy notes','kind':'text'}],
          'arithmetic_bindings':[],'financial_bindings':[], 'implementation':{'path':'frozen-upstream.py','sha256':'a'*64},
          'public_notes':['Essential policies remain provided'],'phases':['close'],'specification_sha256':'b'*64}
    def add(cell,expression,*,financial=False,kind='money_pence',owner=None):
        row={'sheet':'Calculations','cell':cell,'expression':expression,
             'formula':'='+expression_formula(expression),'semantic_owner':owner or ['account',cell],
             'is_complete_answer':financial}
        data['arithmetic_bindings'].append(row)
        data['literal_bindings'].append({'sheet':'Calculations','cell':'A'+cell[1:],'value':'label '+cell,'kind':'text'})
        if financial:data['financial_bindings'].append({**deepcopy(row),'expected_path':['account',cell],
            'kind':kind,'worksheet_scale':100 if kind=='money_pence' else 1})
        data['formula_count']+=1
        return ref('Calculations',cell)
    return data,add


def test_default_off_and_input_immutable(bindings):
    data,add=bindings;add('B1',['if',['eq',ref('Policies','B2'),'ACCRUAL_MONTHLY'],ref('Assumptions','B1'),7],financial=True)
    before=p.canonical(data)
    with pytest.raises(ValueError,match='opt-in'):p.specialize_bindings(data)
    with pytest.raises(ValueError):p.specialize_bindings(data,enabled=1)
    new,report=p.specialize_bindings(data,enabled=True)
    assert p.canonical(data)==before
    assert new['arithmetic_bindings'][0]['expression']==ref('Assumptions','B1')
    assert new['input_bindings']==data['input_bindings']
    assert report['all_native_primitives_preserved']
    assert not report['financial_equivalence_or_source_qualification_claimed']


def test_policy_alias_and_boolean_known_propagation_prune_complete_dead_helpers(bindings):
    data,add=bindings
    tag=add('B1',ref('Policies','B1'))
    quarter=add('B2',['eq',tag,'BULLET_QUARTERLY_ACCRUAL'])
    calendar=add('B3',['ge',ref('Assumptions','B3'),ref('Assumptions','B3')])
    dormant=add('B4',['if',calendar,ref('Assumptions','B1'),999])
    add('B5',['if',quarter,dormant,ref('Assumptions','B1')],financial=True)
    new,report=p.specialize_bindings(data,enabled=True)
    assert [(r['cell'],r['expression']) for r in new['arithmetic_bindings']]==[('B5',ref('Assumptions','B1'))]
    assert {r['cell'] for r in new['literal_bindings'] if r['sheet']=='Calculations'}=={'A5'}
    assert next(r for r in new['literal_bindings'] if r['sheet']=='Contract Notes')==data['literal_bindings'][0]
    assert report['pruned_arithmetic_count']==4 and report['pruned_literal_helper_count']==4
    assert report['all_retained_references_closed']
    assert not any(key in report for key in ('old_formulas','old_expressions','template_archive'))


def test_unknown_amount_rate_date_join_future_state_never_fold(bindings):
    data,add=bindings
    expressions=[['sum',1,2],['round_product',ref('Assumptions','B1'),ref('Assumptions','B2')],
        ['ge',ref('Assumptions','B3'),ref('Assumptions','B3')],
        ['if',['eq',ref('Assumptions','B1'),0],1,1],
        ['if',['ge',ref('Assumptions','B3'),ref('Assumptions','B3')],ref('Assumptions','B2'),ref('Assumptions','B1')]]
    for i,expression in enumerate(expressions,1):add(f'B{i}',expression,financial=True)
    new,report=p.specialize_bindings(data,enabled=True)
    assert [r['expression'] for r in new['arithmetic_bindings']]==expressions
    assert report['rewritten_definitions']==[]
    assert report['numeric_rate_date_join_or_financial_arithmetic_evaluated'] is False
    assert report['unknown_state_conditions_evaluated'] is False


def test_money_zero_selected_by_policy_is_not_a_boolean_fact(bindings):
    data,add=bindings
    amount=add('B1',['if',['eq',ref('Policies','B2'),'ACCRUAL_MONTHLY'],0,ref('Assumptions','B1')],financial=True)
    branch=['if',['eq',amount,0],ref('Assumptions','B1'),ref('Assumptions','B2')]
    add('B2',branch,financial=True)
    new,_=p.specialize_bindings(data,enabled=True)
    assert new['arithmetic_bindings'][0]['expression']==0
    assert new['arithmetic_bindings'][1]['expression']==branch


@pytest.mark.parametrize('op,policy,expected',[
    ('and','BULLET_QUARTERLY_ACCRUAL',0),('or','BULLET_MONTHLY',1)])
def test_decisive_boolean_policy_does_not_evaluate_unknown_operand(bindings,op,policy,expected):
    data,add=bindings
    add('B1',[op,['eq',ref('Policies','B1'),policy],['ge',ref('Assumptions','B1'),0]],financial=True,kind='flag')
    new,_=p.specialize_bindings(data,enabled=True)
    assert new['arithmetic_bindings'][0]['expression']==expected


def test_neutral_boolean_policy_preserves_unknown_operand(bindings):
    data,add=bindings;unknown=['ge',ref('Assumptions','B1'),0]
    add('B1',['and',['eq',ref('Policies','B1'),'BULLET_MONTHLY'],unknown],financial=True,kind='flag')
    new,_=p.specialize_bindings(data,enabled=True)
    assert new['arithmetic_bindings'][0]['expression']==unknown


def test_all_financial_aliases_and_nullable_vintage_identities_are_roots(bindings):
    data,add=bindings
    add('B1',ref('Assumptions','B1'),financial=True)
    add('B2',['if',['eq',ref('Policies','B3'),'MONTHLY_CURRENT'],'',1],financial=True,kind='nullable_flag')
    add('B3',['sub',ref('Assumptions','B1'),1],financial=True,owner=['vintage','origin','2027-01-01'])
    data['financial_bindings'][-1].update(vintage_origin='2027-01-01',vintage_field='closing')
    old=[p._identity(r) for r in data['financial_bindings']]
    new,report=p.specialize_bindings(data,enabled=True)
    assert len(new['financial_bindings'])==3
    assert [p._identity(r) for r in new['financial_bindings']]==old
    assert report['financial_physical_alias_count']==3
    assert new['financial_bindings'][1]['expression']==''
    assert new['financial_bindings'][2]['vintage_origin']=='2027-01-01'


def test_unknown_active_test_alias_keeps_state_branches_and_reports_limit(bindings):
    data,add=bindings
    active=['eq',ref('Assumptions','B1'),0]
    due=add('B1',['if',['and',active,['or',['eq',ref('Policies','B3'),'MONTHLY_CURRENT'],0]],1,0])
    branch=['if',due,ref('Assumptions','B1'),ref('Assumptions','B2')]
    add('B2',branch,financial=True)
    new,report=p.specialize_bindings(data,enabled=True)
    assert new['arithmetic_bindings'][0]['expression']==['if',active,1,0]
    assert new['arithmetic_bindings'][1]['expression']==branch
    assert 'Unknown active/closed' in report['limitations'][0]


def test_referenced_literal_helper_is_not_pruned_with_dead_formula(bindings):
    data,add=bindings
    add('B1',['sum',1,2])
    add('B2',ref('Calculations','A1'),financial=True,kind='text')
    new,_=p.specialize_bindings(data,enabled=True)
    assert [r['cell'] for r in new['arithmetic_bindings']]==['B2']
    assert any(r['sheet']=='Calculations' and r['cell']=='A1' for r in new['literal_bindings'])


@pytest.mark.parametrize('corruption',['duplicate_formula','formula_mismatch','unclosed','cycle','bad_seed_type',
    'bad_seed_text','duplicate_input','overlap','financial_mismatch','duplicate_financial','wrong_count','version_bool'])
def test_structural_corruption_fails_closed(bindings,corruption):
    data,add=bindings;add('B1',ref('Assumptions','B1'),financial=True)
    if corruption=='duplicate_formula':data['arithmetic_bindings'].append(deepcopy(data['arithmetic_bindings'][0]));data['formula_count']+=1
    elif corruption=='formula_mismatch':data['arithmetic_bindings'][0]['formula']='=999'
    elif corruption in {'unclosed','cycle'}:
        value=ref('No such sheet','B99') if corruption=='unclosed' else ref('Calculations','B1')
        for row in data['arithmetic_bindings']+data['financial_bindings']:row.update(expression=value,formula='='+expression_formula(value))
    elif corruption=='bad_seed_type':data['input_bindings'][0]['stored_value']=1
    elif corruption=='bad_seed_text':data['input_bindings'][0]['stored_value']='annuity'
    elif corruption=='duplicate_input':data['input_bindings'].append(deepcopy(data['input_bindings'][0]))
    elif corruption=='overlap':data['literal_bindings'].append({'sheet':'Policies','cell':'B1','value':'duplicate'})
    elif corruption=='financial_mismatch':data['financial_bindings'][0]['expression']=7
    elif corruption=='duplicate_financial':data['financial_bindings'].append(deepcopy(data['financial_bindings'][0]))
    elif corruption=='wrong_count':data['formula_count']=0
    else:data['binding_version']=True
    with pytest.raises(ValueError):p.specialize_bindings(data,enabled=True)


def test_forbidden_numeric_input_truthiness_not_used(bindings):
    data,add=bindings
    # Non-policy input values are intentionally opaque strings, not numbers.
    add('B1',['if',['eq',ref('Policies','B2'),'ACCRUAL_MONTHLY'],['sum',ref('Assumptions','B1'),1],0],financial=True)
    new,_=p.specialize_bindings(data,enabled=True)
    assert new['arithmetic_bindings'][0]['expression']==['sum',ref('Assumptions','B1'),1]
    assert new['input_bindings']==data['input_bindings']


def test_financial_metadata_and_all_physical_formula_text_sync(bindings):
    data,add=bindings
    add('B1',['if',['eq',ref('Policies','B3'),'MONTHLY_CURRENT'],1,0],financial=True,kind='flag')
    new,report=p.specialize_bindings(data,enabled=True)
    physical={(r['sheet'],r['cell']):r for r in new['arithmetic_bindings']}
    for row in new['financial_bindings']:
        assert row['expression']==physical[(row['sheet'],row['cell'])]['expression']
        assert row['formula']==physical[(row['sheet'],row['cell'])]['formula']=='='+expression_formula(row['expression'])
    assert new['formula_count']==len(physical)
    assert report['financial_identity_metadata_sha256']==p.canonical([p._identity(r) for r in data['financial_bindings']])


def test_module_has_no_workbook_execution_or_financial_oracle_import():
    tree=ast.parse(Path(p.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node,ast.ImportFrom):
            assert not any(word in (node.module or '') for word in ('ledger','validate','engine','openpyxl'))
        if isinstance(node,ast.Attribute):assert node.attr not in {'simulate','save','recalculate','Popen'}


def test_legitimate_different_policy_survives_without_dormant_monthly_template(bindings):
    data,add=bindings
    data['input_bindings'].append({'sheet':'Policies','cell':'B4','path':['loans',1,'type'],
        'kind':'text','worksheet_scale':1,'stored_value':'BULLET_QUARTERLY_ACCRUAL'})
    future_calendar=['ge',ref('Assumptions','B3'),ref('Assumptions','B1')]
    quarter_rule=add('B1',future_calendar)
    monthly=add('B2',['if',['eq',ref('Policies','B1'),'BULLET_QUARTERLY_ACCRUAL'],quarter_rule,1],financial=True,kind='flag')
    quarterly=add('B3',['if',['eq',ref('Policies','B4'),'BULLET_QUARTERLY_ACCRUAL'],quarter_rule,1],financial=True,kind='flag')
    new,report=p.specialize_bindings(data,enabled=True)
    bycell={r['cell']:r for r in new['arithmetic_bindings']}
    assert bycell['B2']['expression']==1
    assert bycell['B3']['expression']==quarter_rule
    assert bycell['B1']['expression']==future_calendar
    assert quarter_rule not in p._refs(bycell['B2']['expression'])
    assert quarter_rule in p._refs(bycell['B3']['expression'])
    assert len(new['financial_bindings'])==2
    assert report['all_financial_paths_units_and_semantic_owners_preserved']


def test_policy_seed_bool_unit_is_not_integer_one(bindings):
    data,add=bindings;add('B1',ref('Assumptions','B1'),financial=True)
    data['input_bindings'][0]['worksheet_scale']=True
    with pytest.raises(ValueError,match='exact provided policy text'):p.specialize_bindings(data,enabled=True)

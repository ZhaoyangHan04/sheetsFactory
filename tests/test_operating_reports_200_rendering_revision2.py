from copy import deepcopy
from fractions import Fraction as F
from pathlib import Path
import ast
import hashlib
import json
import pytest
from sheets_factory.workbook.operating_reports_200 import raw,schema,oracle_a,oracle_b,excel,audit
from sheets_factory.workbook.operating_reports_200 import excel_revision2 as revision


def toy(form='level_multiple',given='1.045'):
    p=raw.build_spec();p['dimension_mode']='toy';p['entities']=p['entities'][:1];e=p['entities'][0];p['divisions']=[e['division']]
    e.update(layout='quarter_columns',money_unit='GBP',rate_unit='fraction',forecast_reference='same_quarter_last_year',driver_form_by_year={'2026':form,'2027':form},opening={'cash':'1000','investment':'200','debt':'100','capital':'1000','retained_earnings':'100'},actual_sales=dict(zip(schema.QUARTERS[:4],('10','11','12','13'))),forecast_sales={q:given for q in schema.QUARTERS[4:]},direct_cost_rate='0.5',cash_opex={q:'0.1'for q in schema.QUARTERS},annual_interest_rate='0.08',parent_tax_rate='0.25',associate_results={q:'0'if q.startswith('2025')else'0.02'for q in schema.QUARTERS})
    return p


@pytest.mark.parametrize('form,given,expected',[('level_multiple','1.045','9/200'),('level_multiple','1.025','1/40'),('base100_index','104.5','9/200'),('change_rate','0.045','9/200'),('money_delta','0.45','9/200')])
def test_given_decimal_decode_and_hand_growth(form,given,expected):
    public=toy(form,given);rule=revision.rules(public)['E001/2026Q1/yoy_percent'];N,D,K=rule['N'],rule['D'],rule['K']
    assert F(N,D)==F(given)
    assert abs(F.from_float(float(given)*D)-N)<=F(rule['absolute_decode_error_bound'])<F(1,2)
    value=F((N-D)*K,D)if form=='level_multiple'else F((N-100*D)*K,100*D)if form=='base100_index'else F(N,D)if form=='change_rate'else F(N*K,D)/10
    assert value==F(expected)
    assert all(abs(i)<2**53 for i in rule['integer_terms'])


def test_guard_before_output_allocation(tmp_path):
    public=toy(given='1.0000000000000001');out=tmp_path/'reject'
    with pytest.raises(ValueError,match='integer range'):revision.emit(public,out)
    assert not out.exists()


def test_private_clone_no_mutation_fulltoy_proof_and_plan_identity(tmp_path):
    public=toy();old=tmp_path/'old';new=tmp_path/'new'
    original_formula=excel._formula;original_emit=excel.emit
    excel.emit(public,old);receipt=revision.emit(public,new)
    assert excel._formula is original_formula and excel.emit is original_emit
    assert hashlib.sha256(Path(excel.__file__).read_bytes()).hexdigest()==revision.FROZEN_SHA256
    A,B=oracle_a.solve(public),oracle_b.solve(public)
    result=revision.prove(public,A,B,old,new)
    assert result['passed']and result['matching_growth_exact_and_primary_checked']==8
    assert result['complete_original_A_B_points_unchanged']==1230
    assert result['original_DBG_roots_primary_impact_proved']==1
    assert result['all_provided_facts_context_and_NA_unchanged']
    assert receipt['kind']==revision.KIND and receipt['version']==2
    assert result['original_emission_receipt']['sha256']==result['base_emission_receipt']['sha256']
    proof=json.loads((new/'rendering_proof.json').read_text())
    for rule in proof['rules'].values():
        assert rule['provided_binding']['role']=='provided_fact'
        assert '/forecast_sales/'in rule['entity']+'/forecast_sales/'+rule['period']
    assert audit.census(public,new)['formula_caches']==0


def test_proof_rejects_rule_tamper_and_missing_class(tmp_path):
    public=toy();old=tmp_path/'old';new=tmp_path/'new';excel.emit(public,old);revision.emit(public,new)
    A,B=oracle_a.solve(public),oracle_b.solve(public)
    proof_path=new/'rendering_proof.json';proof=json.loads(proof_path.read_text());key=next(iter(proof['rules']));proof['rules'][key]['N']+=1;proof_path.write_text(json.dumps(proof))
    with pytest.raises(ValueError):revision.prove(public,A,B,old,new)


def test_no_hidden_epsilon_or_financial_import():
    tree=ast.parse(Path(revision.__file__).read_text())
    assert not any(isinstance(n,ast.Constant)and type(n.value)is float for n in ast.walk(tree))
    assert not any(isinstance(n,ast.Global)for n in ast.walk(tree))
    imports=[ast.unparse(n)for n in ast.walk(tree)if isinstance(n,(ast.Import,ast.ImportFrom))]
    assert all('oracle'not in item for item in imports)


def test_complete_fixed_rules_algebra_and_bound_without_native_calls():
    public=raw.build_spec();left=oracle_a.solve(public);right=oracle_b.solve(public)
    assert audit.compare(public,left,right)['passed']
    rules=revision.rules(public)
    assert len(rules)==1600
    counts={name:sum(r['driver_form']==name for r in rules.values())for name in schema.DRIVER_FORMS}
    assert set(counts.values())=={400}
    for key,r in rules.items():
        N,D,K=r['N'],r['D'],r['K'];form=r['driver_form']
        value=F((N-D)*K,D)if form=='level_multiple'else F((N-100*D)*K,100*D)if form=='base100_index'else F(N,D)if form=='change_rate'else F(N*K,D)/F(left['raw_cell_exact_values'][r['comparison_revenue_key']]['value'])
        assert left['raw_cell_exact_values'][key]==right['raw_cell_exact_values'][key]=={'kind':'rational','value':str(value)}
        assert left['typed_2dp_values'][key]['value']==revision._quant(value)
        assert max(map(abs,r['integer_terms']))<2**53
        assert F(r['distance_to_nearest_half_integer_lower_bound'])>F(49,100)

"""Toy arithmetic and mocked durable generation; no new production forwards."""
import ast
from collections import Counter
from copy import deepcopy
import dis
from fractions import Fraction
import hashlib
import importlib.util
import json
from pathlib import Path
from types import CodeType

import pytest

from sheets_factory.workbook.operating_reports_financial_cohort_v1 import schema as s,raw,oracles

ROOT=Path(__file__).resolve().parents[1]


def toy(seed=202711201):
    spec=importlib.util.spec_from_file_location('_cohort_hand_arithmetic_fixtures',ROOT/'tests/test_operating_reports_200_oracle_b.py')
    fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
    public=fixtures.public();public.update(kind=s.KIND,seed=seed)
    return public


def read(record):
    return json.loads(Path(record['path']).read_text())


def rewrite(path,value):
    Path(path).write_text(json.dumps(value,indent=2)+'\n')
    return s.reference(path)


def test_contract_is_predeclared_nine_new_cases_and_spent_C00_is_excluded():
    value=s.contract()
    assert s.reference(s.CONTRACT)['sha256']==s.CONTRACT_SHA256
    assert [row['seed'] for row in value['entries'][1:]]==list(s.ALLOWED_SEEDS)
    assert [row['candidate_id'] for row in value['entries'][1:]]==[f'FM-C{i:02d}' for i in range(1,10)]
    assert value['entries'][0]['new_development_attempt_allowed'] is False
    for identity in ('FM-C00',202711200,'FM-C10',202711210,True):
        with pytest.raises(ValueError):s.candidate(identity)


def test_existing_C00_read_only_vocabulary_census_retains_all_93510_fields():
    record=s.contract()['entries'][0]['raw'];assert s.reference(record['path'])==record
    existing=read(record);points=list(s.points(existing))
    assert len(points)==93510 and len({key for key,_ in points})==93510
    assert Counter(kind for _,kind in points)=={'boolean':600,'number':88076,'text':4834}
    forecast=[key for key,kind in points if kind!='text' and key.split('/')[1].removeprefix('FY')[:4] in ('2026','2027')]
    assert len(forecast)==62322
    assert s.reference(record['path'])==record  # No raw generation, arithmetic or source recalculation.


@pytest.mark.parametrize('seed',s.ALLOWED_SEEDS)
def test_identity_only_projection_returns_real_object_and_hashes_real_seed(seed):
    public=toy(seed);before=deepcopy(public)
    assert s.validate_spec(public) is public and public==before
    projected=s.shape_projection(public)
    assert projected['kind']==s.BASE_KIND and projected['seed']==s.BASE_SEED
    changed={key for key in public if projected[key]!=public[key]}
    assert changed=={'kind','seed'}
    assert s.canonical_sha256(public)!=s.canonical_sha256(projected)
    facade=s.for_seed(seed)
    assert facade.KIND==s.KIND and facade.SEED==seed and facade.validate_spec(public) is public
    other=deepcopy(public);other['seed']=202711202 if seed!=202711202 else 202711201
    with pytest.raises(ValueError,match='another candidate'):facade.validate_spec(other)
    assert not hasattr(facade,'_BASE')


@pytest.mark.parametrize('fault',['old_kind','old_seed','unknown_seed','bad_rate','missing_field','old_result_kind'])
def test_original_shape_and_new_identity_gates_remain_strict(fault):
    public=toy()
    if fault=='old_kind':public['kind']=s.BASE_KIND
    elif fault=='old_seed':public['seed']=s.BASE_SEED
    elif fault=='unknown_seed':public['seed']=0
    elif fault=='bad_rate':public['entities'][0]['direct_cost_rate']='not a finite decimal'
    elif fault=='missing_field':public['entities'][0].pop('opening')
    else:
        result=oracles.solve_A(public);result['kind']=s.BASE_RESULT_KIND
        with pytest.raises(ValueError):s.validate_result(public,result)
        return
    with pytest.raises(ValueError):s.validate_spec(public)


@pytest.mark.parametrize('identity',[f'FM-C{i:02d}' for i in range(1,10)])
def test_exact_axis_rotation_preserves_all_conventions_and_six_sentinels(identity):
    original=json.loads(s.checked_source('design').read_text())
    axes=original['artifacts']['axis_assignment.json']['value']['entities'];entry=s.candidate(identity)
    selected=raw.axis_assignment(identity)
    assert len(selected)==200 and [row['id'] for row in selected]==[row['id'] for row in axes]
    for index,row in enumerate(selected):
        expected=deepcopy(axes[index] if index<6 else axes[6+(index-6+entry['axis_rotation_offset'])%194])
        expected['id']=axes[index]['id'];expected['name']=entry['company_brand_prefix']+' '+expected['name']
        assert row==expected
    def conventions(rows):
        return Counter(tuple((key,value) for key,value in sorted(row.items()) if key not in ('id','name')) for row in rows)
    assert conventions(selected)==conventions(axes)
    assert Counter(row['division'] for row in selected)==Counter({division:25 for division in s.DIVISIONS})
    namespace=raw._namespace(identity)
    assert namespace['s'].SEED==entry['seed']
    assert namespace['design']()['artifacts']['axis_assignment.json']['value']['entities']==selected
    assert namespace['design']()['artifacts']['numeric_generation_addendum.json']==original['artifacts']['numeric_generation_addendum.json']
    expected=int.from_bytes(hashlib.sha256(f"{entry['seed']}|E049|R_GBP|all".encode()).digest(),'big')
    assert namespace['_hash']('E049','R_GBP','all')==expected
    assert json.loads(s.checked_source('design').read_text())==original


@pytest.mark.parametrize('seed',[202711201,202711209])
def test_frozen_A_and_B_independently_cover_hand_calculated_toy_union(seed):
    public=toy(seed);before=deepcopy(public)
    left=oracles.solve_A(public);right=oracles.solve_B(public)
    assert public==before
    assert left['kind']==right['kind']==s.RESULT_KIND
    assert left['specification_sha256']==right['specification_sha256']==s.canonical_sha256(public)
    for layer in ('economic_exact_values','raw_cell_exact_values','typed_2dp_values'):
        assert left[layer]==right[layer]
        assert set(left[layer])=={key for key,_ in s.points(public)}
    expected={'revenue':100,'direct_cost':25,'operating_expense':10,'interest':1,
        'current_tax':Fraction(64,5),'core_net_income':Fraction(256,5),
        'associate_income':5,'net_income':Fraction(281,5),'closing_cash':1256,
        'closing_investment':205,'total_assets':1461,'total_liabilities_equity':1461}
    for field,amount in expected.items():
        assert Fraction(left['economic_exact_values']['E001/2026Q1/'+field]['value'])==amount
    assert left['typed_2dp_values']['PORTFOLIO/FY2027/distribution_eligible']=={'type':'text','value':s.GROUP_NA}
    assert left['typed_2dp_values']['E001/FY2027/distribution_eligible']=={'type':'boolean','value':False}
    assert all(value=='0' for key,rows in left['reconciliation_checks'].items() if key.endswith('_residuals') for value in rows.values())


def test_oracle_namespaces_are_separate_fresh_and_only_schema_import_changes():
    def operations(code):
        return [(item.opname,operations(item.argval) if isinstance(item.argval,CodeType) else item.argval)
            for item in dis.get_instructions(code)]
    left=oracles._namespace('A',202711201);right=oracles._namespace('B',202711201);again=oracles._namespace('A',202711201)
    assert left is not right and left is not again
    assert left['solve'].__globals__ is left and right['solve'].__globals__ is right
    assert left['s'] is not right['schema'] and left['s'] is not again['s']
    assert 'schema' not in left and 's' not in right
    for key,namespace in [('oracle_A',left),('oracle_B',right),('raw',raw._namespace('FM-C01'))]:
        source=s.checked_source(key);original=ast.parse(source.read_bytes())
        frozen_code=compile(original,str(source),'exec')
        for node in original.body:
            if isinstance(node,ast.FunctionDef):
                if key=='raw' and node.name=='design':continue  # Only the declared metadata provider is rebound.
                expected=next(value for value in frozen_code.co_consts
                    if isinstance(value,CodeType) and value.co_name==node.name)
                assert operations(namespace[node.name].__code__)==operations(expected),(key,node.name)
    left['TEST_ONLY_mutable']={'value':1}
    assert 'TEST_ONLY_mutable' not in right and 'TEST_ONLY_mutable' not in again


def test_imports_and_raw_reservation_do_not_import_or_invoke_financial_implementations(monkeypatch,tmp_path):
    calls=[]
    def fail(identity):
        all_ids=[row['candidate_id'] for row in s.contract()['entries'][1:]]
        assert all((tmp_path/'failed'/name/'generation_started.json').exists() for name in all_ids)
        calls.append(identity);raise ValueError('TEST_ONLY retained raw-generation failure')
    monkeypatch.setattr(raw,'build_spec',fail)
    monkeypatch.setattr(oracles,'solve_A',lambda *a,**k:pytest.fail('No financial forward during raw freeze'))
    monkeypatch.setattr(oracles,'solve_B',lambda *a,**k:pytest.fail('No financial forward during raw freeze'))
    inventory=raw.freeze_all(tmp_path/'failed');value=read(inventory)
    assert calls==[f'FM-C{i:02d}' for i in range(1,10)] and value['passed'] is False
    assert len(value['cases'])==9 and all(not row['passed'] and Path(row['failure']['path']).is_file() for row in value['cases'])
    assert value['financial_forwards']==value['services']==0 and value['new_raw_attempts']==9
    with pytest.raises(ValueError,match='complete unchanged all-nine'):raw.validate_all(inventory)
    with pytest.raises(FileExistsError):raw.freeze_all(tmp_path/'failed')
    assert len(calls)==9


@pytest.fixture
def synthetic_inventory(tmp_path,monkeypatch):
    # These are tiny protocol fixtures, not the frozen numeric generator or
    # production financial inputs. Shape checks are tested independently above.
    def generate(identity):
        entry=s.candidate(identity);public=toy(entry['seed']);public['dimension_mode']='production'
        axis=raw.axis_assignment(identity)[0];entity=public['entities'][0]
        for key in ('id','name','division','layout','line_order','money_unit','rate_unit','statement_sign','forecast_reference'):
            entity[key]=axis[key]
        entity['driver_form_by_year']={str(year):axis['FY'+str(year)+'_driver_form'] for year in (2026,2027)}
        return public
    monkeypatch.setattr(raw,'build_spec',generate)
    monkeypatch.setattr(s,'validate_spec',lambda public:public)
    inventory=raw.freeze_all(tmp_path/'synthetic_nine_protocol_only')
    return inventory,raw.validate_all(inventory)


def test_complete_inventory_and_corresponding_public_are_required_before_production_call(synthetic_inventory,monkeypatch):
    inventory,all_raw=synthetic_inventory;public=all_raw['specifications']['FM-C01'];calls=[]
    sentinel={'TEST_ONLY':'no financial calculation'}
    monkeypatch.setattr(oracles,'_namespace',lambda name,seed:{'solve':lambda data:calls.append((name,seed,data)) or sentinel})
    monkeypatch.setattr(s,'validate_result',lambda public,result:result)
    with pytest.raises(ValueError,match='complete nine-case'):oracles.solve_A(public)
    assert not calls
    assert oracles.solve_A(public,raw_inventory=inventory) is sentinel
    assert oracles.solve_B(public,raw_inventory=inventory) is sentinel
    assert [row[0] for row in calls]==['A','B']
    other=deepcopy(public);other['entities'][0]['opening']['cash']='1001'
    with pytest.raises(ValueError,match='exact corresponding frozen'):oracles.solve_A(other,raw_inventory=inventory)
    assert len(calls)==2


@pytest.mark.parametrize('fault',['partial','duplicate','reordered','failed_case','changed_raw','wrong_seed',
    'changed_recipe','changed_contract','changed_receipt','changed_axis','wrong_common_reservation'])
def test_inventory_rejects_missing_changed_or_substituted_case(synthetic_inventory,fault):
    inventory,_=synthetic_inventory;value=read(inventory);first=value['cases'][0]
    if fault=='partial':value['cases'].pop()
    elif fault=='duplicate':value['cases'][1]=deepcopy(first)
    elif fault=='reordered':value['cases'].reverse()
    elif fault=='failed_case':first['passed']=False
    elif fault=='changed_raw':Path(first['specification']['path']).write_bytes(b'changed')
    elif fault=='wrong_seed':first['seed']+=1
    elif fault=='changed_recipe':value['recipe']={}
    elif fault=='changed_contract':value['contract']['sha256']='0'*64
    elif fault=='changed_receipt':
        record=read(first['generation_receipt']);record['raw_forwards']=2
        first['generation_receipt']=rewrite(first['generation_receipt']['path'],record)
    elif fault=='changed_axis':
        public=read(first['specification']);public['entities'][0]['name']='TEST_ONLY substituted brand'
        first['specification']=rewrite(first['specification']['path'],public)
        receipt=read(first['generation_receipt']);receipt.update(specification=first['specification'],canonical_specification_sha256=s.canonical_sha256(public))
        first['generation_receipt']=rewrite(first['generation_receipt']['path'],receipt)
    else:
        record=read(first['generation_started']);record['cohort_start']=deepcopy(record['cohort_start']);record['cohort_start']['sha256']='0'*64
        first['generation_started']=rewrite(first['generation_started']['path'],record)
    changed=rewrite(inventory['path'],value)
    with pytest.raises((ValueError,OSError)):raw.validate_all(changed)


def test_ancestor_hash_drift_rejects_before_generator_or_financial_forward(monkeypatch):
    row=deepcopy(s.contract());row['frozen_ancestors']['raw']['sha256']='0'*64
    monkeypatch.setattr(s,'contract',lambda:deepcopy(row))
    with pytest.raises(ValueError,match='ancestor changed'):raw._namespace('FM-C01')


def test_old_modules_and_real_case_C00_are_not_mutated_by_toy_wrapper_calls():
    from sheets_factory.workbook.operating_reports_200 import schema as original,raw as original_raw
    old_seed,old_kind=original.SEED,original.KIND;axes=deepcopy(original_raw.design())
    assert s.reference(s.contract()['entries'][0]['raw']['path'])==s.contract()['entries'][0]['raw']
    oracles.solve_A(toy());oracles.solve_B(toy())
    assert (original.SEED,original.KIND)==(old_seed,old_kind)
    assert original_raw.design()==axes

from copy import deepcopy
import ast
import json
from pathlib import Path
import sys

import pytest

from sheets_factory.workbook.waterfall_portfolios_v1 import raw, schema


def toy():
    return raw.build_spec(dimension_mode='toy',fund_numbers=[1,6],years=[2025,2026,2027,2028],scenario_ids=['BASE','DOWN'])


def test_complete_frozen_vocabulary_and_toy_geometry():
    value=toy(); assert len(value['funds'])==2
    assert len(schema.ROW_FIELDS)==56 and len(schema.AGGREGATE_FIELDS)==20
    assert set(schema.INVARIANT_FIELDS)<=set(schema.ROW_FIELDS)
    assert schema.validate_spec(value)==value
    assert value['funds'][0]['preferred_rate_bp']==600
    assert value['funds'][1]['lp1_share_bp']==6000
    assert value['funds'][1]['layout']=='transaction_rows'
    assert value['funds'][0]['fund_ledger_sign']=='signed_cash_uses'
    assert value['funds'][1]['fund_ledger_sign']=='positive_deduction_uses'


def test_raw_module_has_no_oracle_or_financial_forward_dependency():
    tree=ast.parse(Path(raw.__file__).read_text())
    imports=[n for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))]
    assert all('oracle' not in ast.unparse(n) for n in imports)
    calls={ast.unparse(n.func) for n in ast.walk(tree) if isinstance(n,ast.Call)}
    assert not any(name.rsplit('.',1)[-1] in {'solve','simulate','forward','optimize'} for name in calls)
    source=Path(raw.__file__).read_text()
    assert 'failure_research_reference' not in source


def test_hash_only_raw_is_deterministic_and_scenarios_retained():
    a=toy(); b=toy(); assert a==b and schema.canonical_sha256(a)==schema.canonical_sha256(b)
    a['funds'][0]['scenarios'][0]['periods'][0]['lp_call_pence']+=1
    assert schema.canonical_sha256(a)!=schema.canonical_sha256(b)
    assert [s['id'] for s in b['funds'][1]['scenarios']]==['BASE','DOWN']


def test_external_recipe_is_not_seed_oracle_resampling():
    p=toy();f=p['funds'][0]; commitment=f['commitment_pence']
    assert 100000000<=commitment<=1500000000 and commitment%1000000==0
    assert f['opening_investment_book_cost_pence']+f['opening_cash_pence']==f['opening_cumulative_lp_paid_in_pence']
    assert all(s['periods'][0]['realization_receipts_pence']==0 for s in f['scenarios'])
    assert all(s['periods'][1]['realization_receipts_pence']==0 for s in f['scenarios'])
    assert all(s['periods'][2]['realization_receipts_pence']>0 for s in f['scenarios'])
    assert raw._post(1,2)==1 and raw._post(3,2)==2


@pytest.mark.parametrize('mutation',[
    lambda p:p.update(version=True),
    lambda p:p.update(dimension_mode='production'),
    lambda p:p.update(private_answer=0),
    lambda p:p['funds'][0].update(preferred_rate_bp=0.08),
    lambda p:p['funds'][0].update(lp1_share_bp=True),
    lambda p:p['funds'][0]['scenarios'][0]['periods'][0].update(lp_call_pence=-1),
    lambda p:p['funds'][0]['scenarios'][0]['periods'][0].update(call_date='2025-01-02'),
    lambda p:p['funds'][0]['scenarios'][0]['periods'].pop(),
    lambda p:p['funds'][0]['scenarios'].pop(),
    lambda p:p['funds'].append(deepcopy(p['funds'][0])),
    lambda p:p.update(contract_sha256='0'*64),
])
def test_strict_raw_shape_refuses_missing_extra_and_coerced_values(mutation):
    p=toy();mutation(p)
    with pytest.raises((ValueError,KeyError)):schema.validate_spec(p)


def test_reservation_precedes_generation_and_survives_failure(tmp_path,monkeypatch):
    monkeypatch.setattr(raw,'RESERVATIONS',tmp_path/'reservations')
    real=raw.build_spec; seen=[]
    def fail(**kwargs):
        reservations=list(raw.RESERVATIONS.glob('*.json')); assert len(reservations)==1
        value=json.loads(reservations[0].read_text()); assert value['financial_forward_calls']==0
        assert (tmp_path/'raw/prospective.json').is_file()
        assert value['declared_future_debug_roots']==['F001/BASE/2027/after_preference_cash']
        seen.append(True);raise RuntimeError('deliberate pre-forward failure')
    monkeypatch.setattr(raw,'build_spec',fail)
    with pytest.raises(RuntimeError):raw.freeze_spec(tmp_path/'raw',dimension_mode='toy',years=[2027])
    assert seen and (tmp_path/'raw/failure.json').is_file()
    monkeypatch.setattr(raw,'build_spec',real)
    with pytest.raises(FileExistsError):raw.freeze_spec(tmp_path/'renamed',dimension_mode='toy',years=[2027])


def test_one_frozen_toy_has_hashes_prospective_and_no_score(tmp_path,monkeypatch):
    monkeypatch.setattr(raw,'RESERVATIONS',tmp_path/'private_reservations')
    r=raw.freeze_spec(tmp_path/'first',dimension_mode='toy',fund_numbers=[2],years=[2027],scenario_ids=['UP'])
    value=json.loads(Path(r['path']).read_text()); p=json.loads(Path(value['specification']['path']).read_text())
    assert value['specification_sha256']==schema.canonical_sha256(p)
    assert value['debug_root_count']==1 and value['financial_forward_calls']==value['model_LO_solver_calls']==0
    assert value['qualified'] is False
    assert len(value['recipe'])==4
    assert json.loads(Path(value['prospective']['path']).read_text())['declared_future_debug_roots']==['F002/UP/2027/after_preference_cash']
    with pytest.raises(FileExistsError):raw.freeze_spec(tmp_path/'changed_zip_name',dimension_mode='toy',fund_numbers=[2],years=[2027],scenario_ids=['UP'])


def test_original_production_pool_cannot_change_seed_or_axes():
    with pytest.raises(ValueError):raw.build_spec(dimension_mode='production',fund_numbers=[2])
    with pytest.raises(ValueError):raw.build_spec(dimension_mode='toy',years=[2027,2029])
    with pytest.raises(ValueError):raw.build_spec(dimension_mode='toy',fund_numbers=[1,2,3,4,5])

"""Aggregate scales need explicit consistent units; old diagnosis stays intact."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from sheets_factory.evaluation import business_failure_evidence_revision2 as currencies

ROOT = Path(__file__).resolve().parents[1]


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def bindings():
    return {'financial':{
        'E001/2027Q1/net_income':{'sheet':'Entity','cell':'B2','money_unit':'GBP_thousands'},
        'DIV_ADVISORY/2027Q1/net_income':{'sheet':'Division','cell':'B2','money_unit':'GBP'},
        'DIV_ADVISORY/FY2027/closing_cash':{'sheet':'Division','cell':'B3','money_unit':'GBP'},
        'PORTFOLIO/2027Q1/net_income':{'sheet':'Portfolio','cell':'B2','money_unit':'GBP'}}}


def test_public_entities_preserved_and_only_explicit_GBP_aggregates_completed():
    public={'E001':1000};before=deepcopy(public);record=bindings()
    result=currencies.complete_money_scales(record,public)
    assert result=={'E001':1000,'DIV_ADVISORY':1,'PORTFOLIO':1}
    assert public==before and record==bindings()


@pytest.mark.parametrize('fault',['missing_unit','wrong_aggregate_unit','conflicting_units','unknown_prefix',
    'entity_mismatch','preasserted_aggregate','missing_entity','invalid_entity_scale','empty_bindings'])
def test_missing_or_inconsistent_units_cannot_be_guessed(fault):
    record=bindings();public={'E001':1000}
    if fault=='missing_unit':record['financial']['DIV_ADVISORY/2027Q1/net_income'].pop('money_unit')
    elif fault=='wrong_aggregate_unit':
        for key,binding in record['financial'].items():
            if key.startswith('DIV_'):binding['money_unit']='GBP_millions'
    elif fault=='conflicting_units':record['financial']['DIV_ADVISORY/FY2027/closing_cash']['money_unit']='GBP_thousands'
    elif fault=='unknown_prefix':record['financial']['UNKNOWN/2027Q1/net_income']=record['financial'].pop('PORTFOLIO/2027Q1/net_income')
    elif fault=='entity_mismatch':public['E001']=1
    elif fault=='preasserted_aggregate':public['DIV_ADVISORY']=1
    elif fault=='missing_entity':public={'E002':1000}
    elif fault=='invalid_entity_scale':public['E001']='not-a-scale'
    else:record['financial']={}
    with pytest.raises(ValueError):currencies.complete_money_scales(record,public)


def test_real_economic_aggregate_witness_uses_original_unchanged_business_math(tmp_path):
    original_tests=load(ROOT/'tests/test_business_failure_evidence.py','_currency_original_business_fixture')
    make=original_tests.bundle.__wrapped__(tmp_path)
    record=make(goal=100,output=90)
    record['bindings']={'DIV_ADVISORY/2027Q1/net_income':{'sheet':'Report','cell':'B2','role':'report','money_unit':'GBP'}}
    record['entity_money_scales']=currencies.complete_money_scales(record['bindings'],{'E001':1000})
    record['provenance']['bindings']=record['put']('aggregate-bindings.json',record['bindings'])
    record['provenance']['entity_money_scales']=record['put']('aggregate-scales.json',record['entity_money_scales'])
    report=original_tests.run(record)
    assert report['state']=='diagnosed' and report['business_failure_evidence'] is True
    witness,=report['economic_witnesses']
    assert witness['entity_id']=='DIV_ADVISORY' and witness['money_scale_to_gbp']=='1'
    assert witness['absolute_difference_gbp']=='10' and report['original_reward']==0


def test_new_driver_changes_only_scale_assignment_and_protocol_identity():
    new=load(ROOT/'scripts/diagnose_associate_bridge_business_attempts_revision2.py','_currency_driver_revision2')
    old=load(new.BASE,'_currency_immutable_original_driver')
    assert new._N is not old.run.__globals__
    assert new._N['_complete_money_scales'] is currencies.complete_money_scales
    for name in ('_admit','_maps','owned_absence'):
        assert new._N[name].__code__.co_code==getattr(old,name).__code__.co_code
        assert new._N[name].__code__.co_consts==getattr(old,name).__code__.co_consts
    assert new._N['PINS']==old.PINS
    recipe=new._N['recipes']()
    assert any(r['path']==str(new.BASE) and r['sha256']==new.BASE_SHA for r in recipe)
    assert any(r['path']==currencies.__file__ and r['sha256']==new.CURRENCY_SHA for r in recipe)
    assert currencies.base.reference(new.BASE)['sha256']==new.BASE_SHA
    assert currencies.base.reference(currencies.base.__file__)['sha256']==currencies.BASE_SHA


def test_actual_B04_all209_prefixes_have_complete_consistent_declared_scales():
    path=ROOT/'outputs/research/associate_bridge_B04_engineering_20261101T063500Z/engineered_batch.json'
    if not path.exists():pytest.skip('Retained actual B04 evidence not installed')
    base=currencies.base
    batch=base._read(base.reference(path));source=base._read(batch['source'])
    public=base._read(source['specification']);record=base._read(source['bindings'])
    entity={e['id']:currencies.UNITS[e['money_unit']]for e in public['base']['entities']}
    completed=currencies.complete_money_scales(record,entity)
    assert len(entity)==200 and len(completed)==209
    aggregates=set(completed)-set(entity)
    assert len(aggregates)==9 and 'PORTFOLIO'in aggregates and all(completed[k]==1 for k in aggregates)
    assert all(key.split('/',1)[0]in completed for key in record['financial'])
    assert base.reference(path)['sha256']=='07bf6043ee08902534a1637384ed7491226008ccec26c58d34af3147828cbcfe'


@pytest.mark.parametrize('invalid', ['sNaN', 'Infinity', '-Infinity'])
def test_nonfinite_scale_is_rejected_as_invalid_evidence(invalid):
    with pytest.raises(ValueError, match='scale is unsupported'):
        currencies.complete_money_scales(bindings(), {'E001': invalid})

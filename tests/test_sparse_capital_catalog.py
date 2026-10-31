"""Deterministic raw-input extensions; no optimizer or financial forward."""
from copy import deepcopy
import json
import pytest

from sheets_factory.workbook.capital_allocation_sparse import catalog,spec,ledger
from sheets_factory.workbook.capital_allocation_scaled import constrained_catalog as parent


@pytest.mark.parametrize('identity',catalog.ORDER)
def test_complete_public_extensions_preserve_every_parent_project_scenario_and_policy(identity,monkeypatch):
    monkeypatch.setattr(ledger,'simulate',lambda *a,**k:pytest.fail('Catalog must not evaluate plans'))
    config=catalog.load_catalog();p=next(p for p in config['profiles'] if p['id']==identity)
    original=parent.build_spec(p['parent_profile']);value=catalog.build_spec(identity)
    assert len(value['projects'])==p['project_count'] and value['projects'][:30]==original['projects']
    assert [x['id'] for x in value['projects']]==list(spec.project_ids(p['project_count']))
    assert value['scenarios']==original['scenarios']
    assert {k:v for k,v in value.items() if k not in (*catalog.MONEY_FIELDS,'projects')}=={k:v for k,v in original.items() if k not in (*catalog.MONEY_FIELDS,'projects')}
    assert all(value[k]==catalog._quantized(original[k],p['project_count'],30,1000000) for k in catalog.MONEY_FIELDS)
    assert value==catalog.build_spec(identity) and config==catalog.load_catalog()
    assert spec.plan_space_count_string(value)==str(1<<p['project_count'])


def test_all_descriptions_are_unconfirmed_and_no_quality_hardness_or_financial_results():
    rows=[catalog.describe_profile(pid) for pid in catalog.ORDER]
    assert len({r['public_spec_sha256'] for r in rows})==13
    assert all(not r['confirmation_frozen'] and not r['financial_feasibility_or_optimum_certified']
               and not r['source_quality_or_difficulty_certified'] for r in rows)
    assert all(r['actual_searches']==r['actual_workbooks']==r['actual_LO_calls']==r['actual_model_calls']=='0' for r in rows)
    assert [r['profile']['role'] for r in rows[:3]]==['first_development','engineering_only','engineering_only']


@pytest.mark.parametrize('key,value',[('confirmation_frozen',True),('model_difficulty_claimed',True),('selection_uses_new_model_outcomes',True),('parent_catalog_sha256','0'*64)])
def test_unknown_or_prospective_status_cannot_be_silently_relabeled(key,value):
    config=catalog.load_catalog();config[key]=value
    with pytest.raises(ValueError):catalog.load_catalog(config)


def test_reordering_truncation_changed_seeds_and_unsupported_dimensions_reject():
    for change in ('order','truncate','seed','dimension','scale'):
        config=catalog.load_catalog()
        if change=='order':config['profile_order'].reverse()
        elif change=='truncate':config['profiles'].pop()
        elif change=='seed':config['profiles'][0]['extension_seed']+=1
        elif change=='dimension':config['profiles'][0]['project_count']=41
        else:config['profiles'][0]['root_money_scale_denominator']=29
        with pytest.raises(ValueError):catalog.load_catalog(config)
    with pytest.raises(ValueError):catalog.build_spec('unknown')


def test_positive_money_quantization_is_exact_at_half_penny_and_large_values():
    assert catalog._quantized(1,1,2,1)==1
    assert catalog._quantized(3,1,2,1)==2
    assert catalog._quantized(1,1,3,1)==0
    assert catalog._quantized(100000000000,56,30,1000000)==186667000000


def test_duplicate_catalog_keys_and_parent_recipe_drift_fail_closed(tmp_path,monkeypatch):
    p=tmp_path/'bad.json';p.write_text('{"kind":1,"kind":2}')
    with pytest.raises(ValueError,match='Duplicate'):catalog.load_catalog(p)
    monkeypatch.setattr(catalog,'PARENT_SHA','0'*64)
    with pytest.raises(ValueError,match='parent primitive catalog'):catalog.load_catalog()

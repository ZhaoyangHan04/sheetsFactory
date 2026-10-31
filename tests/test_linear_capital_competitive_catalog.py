"""Raw assumptions only: no financial implementation or optimizer executes."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import random

import pytest

from sheets_factory.workbook.linear_capital_portfolio import catalog, catalog_competitive as competitive, catalog_correlated, spec

ROOT=Path(__file__).resolve().parents[1]
loader=importlib.util.spec_from_file_location('_competitive_prepare_test',ROOT/'scripts/prepare_competitive_linear_capital.py')
entry=importlib.util.module_from_spec(loader);loader.loader.exec_module(entry)


@pytest.mark.parametrize('profile',['C02','C03'])
def test_predeclared_formula_changes_only_raw_revenue_opex_and_provenance(profile):
    policy=competitive.PROFILES[profile];base=catalog_correlated.build_spec(policy['seed']);actual=competitive.build_spec(profile)
    assert spec.canonical_sha256(actual)==spec.canonical_sha256(competitive.build_spec(profile))
    rng=random.Random(policy['seed']);spread=policy['revenue_jitter_pence']
    for old,new in zip(base['projects'],actual['projects']):
        wanted=old['asset_cost_pence']*3000//spec.BP+rng.randint(-spread,spread)
        assert new['base_annual_revenue_pence']==wanted
        assert new['base_annual_opex_pence']==wanted*6500//spec.BP
        assert {k:v for k,v in old.items() if k not in ('base_annual_revenue_pence','base_annual_opex_pence')}=={
            k:v for k,v in new.items() if k not in ('base_annual_revenue_pence','base_annual_opex_pence')}
    assert {k:v for k,v in base.items() if k not in ('projects','provenance')}=={
        k:v for k,v in actual.items() if k not in ('projects','provenance')}
    assert actual['provenance']['ancestor_sha256']==[] and profile in actual['provenance']['description']
    plans=catalog.diagnostic_plans(actual,seed=policy['seed'])
    assert len(plans)==len({r['id'] for r in plans})==18
    assert all(spec.validate_plan(actual,row['plan'])==row['plan'] for row in plans)


@pytest.mark.parametrize('bad',[None,True,{},'C01','C04',20261102])
def test_no_undeclared_profile_or_seed_override(bad):
    with pytest.raises(ValueError):competitive.build_spec(bad)


def test_both_sources_freeze_together_without_forward_before_existing_finance_api(tmp_path):
    output=tmp_path/'pair';reference=entry.prepare(output);manifest=entry.validate_prepared(output)
    assert entry.reference(reference['path'])==reference
    assert manifest['profile_order']==['C02','C03'] and len(manifest['profiles'])==2
    assert manifest['financial_forward_implementation_calls']==manifest['optimizer_calls']==manifest['LO_calls']==manifest['model_calls']==0
    for row in manifest['profiles']:
        raw=json.loads(Path(row['raw_preparation']['path']).read_text())
        assert raw['kind']=='prepared_linear_240_project_raw_assumptions'
        assert len(raw['paired_specifications_frozen_before_finance'])==2 and len(raw['diagnostic_plans'])==18
        assert str(Path(competitive.__file__).resolve()) in raw['recipe_sha256']
        assert str(Path(catalog_correlated.__file__).resolve()) in raw['recipe_sha256']
    with pytest.raises(ValueError):entry.prepare(output)
    changed=json.loads(Path(manifest['profiles'][1]['specification']['path']).read_text())
    changed['projects'][0]['base_annual_revenue_pence']+=1
    Path(manifest['profiles'][1]['specification']['path']).write_text(json.dumps(changed))
    with pytest.raises(ValueError,match='artifact changed'):entry.validate_prepared(output)

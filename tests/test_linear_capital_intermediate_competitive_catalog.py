"""Only raw generation and fixed plans; no financial implementation executes."""
import importlib.util
import json
from pathlib import Path
import random

import pytest

from sheets_factory.workbook.linear_capital_portfolio import (
    catalog, catalog_correlated, catalog_intermediate_competitive as intermediate, spec)

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.util.spec_from_file_location('_intermediate_raw_prepare',
    ROOT / 'scripts/prepare_intermediate_competitive_linear_capital.py')
entry = importlib.util.module_from_spec(loader)
loader.loader.exec_module(entry)


@pytest.mark.parametrize('pid,seed,spread', [('M01', 20261104, 100000),
    ('M02', 20261105, 150000), ('M03', 20261106, 250000)])
def test_exact_prospective_raw_recipe_and_other_contracts_preserved(pid, seed, spread):
    assert intermediate.PROFILES[pid] == {'seed': seed, 'revenue_jitter_pence': spread}
    public = intermediate.build_spec(pid)
    base = catalog_correlated.build_spec(seed)
    rng = random.Random(seed)
    assert public == intermediate.build_spec(pid)
    for original, actual in zip(base['projects'], public['projects']):
        revenue = original['asset_cost_pence'] * 3000 // spec.BP + rng.randint(-spread, spread)
        assert actual['base_annual_revenue_pence'] == revenue
        assert actual['base_annual_opex_pence'] == revenue * 6500 // spec.BP
        changed = {'base_annual_revenue_pence', 'base_annual_opex_pence'}
        assert {k:v for k,v in actual.items() if k not in changed} == {
            k:v for k,v in original.items() if k not in changed}
    assert {k:v for k,v in public.items() if k not in ('projects', 'provenance')} == {
        k:v for k,v in base.items() if k not in ('projects', 'provenance')}
    assert public['provenance']['hypothetical'] is True and public['provenance']['ancestor_sha256'] == []
    assert pid in public['provenance']['description'] and 'No NPV' in public['provenance']['description']
    plans = catalog.diagnostic_plans(public, seed=seed)
    assert len(plans) == len({p['id'] for p in plans}) == 18
    assert all(spec.validate_plan(public, p['plan']) == p['plan'] for p in plans)


@pytest.mark.parametrize('bad', [None, True, {}, 'C02', 'M04', 20261104])
def test_no_profile_override(bad):
    with pytest.raises(ValueError):
        intermediate.build_spec(bad)


def test_complete_triple_frozen_before_existing_finance_entry_can_consume(tmp_path):
    output = tmp_path / 'triple'
    receipt = entry.prepare(output)
    manifest = entry.validate_prepared(output)
    assert entry.reference(receipt['path']) == receipt
    assert manifest['profile_order'] == ['M01', 'M02', 'M03'] and len(manifest['profiles']) == 3
    assert all(manifest[k] == 0 for k in entry.ZERO_FIELDS)
    for row in manifest['profiles']:
        raw = json.loads(Path(row['raw_preparation']['path']).read_text())
        assert raw['kind'] == 'prepared_linear_240_project_raw_assumptions'
        assert len(raw['all_specifications_frozen_before_finance']) == 3
        assert len(raw['diagnostic_plans']) == 18
        assert str(Path(intermediate.__file__).resolve()) in raw['recipe_sha256']
        assert raw['reference_policy']['retries'] == 0
        assert raw['reference_policy']['private_solver_seconds_per_job'] == 3600
    with pytest.raises(ValueError):
        entry.prepare(output)


@pytest.mark.parametrize('tamper', ['order', 'omit', 'specification', 'plan', 'zero_claim'])
def test_complete_inventory_and_raw_bytes_fail_closed(tmp_path, tamper):
    output = tmp_path / tamper
    entry.prepare(output)
    p = output / 'catalog_manifest.json'
    m = json.loads(p.read_text())
    if tamper == 'order':
        m['profiles'].reverse()
    elif tamper == 'omit':
        m['profiles'].pop()
    elif tamper == 'zero_claim':
        m['optimizer_calls'] = True
    else:
        row = m['profiles'][1]
        q = Path(row['specification' if tamper == 'specification' else 'raw_preparation']['path'])
        raw = json.loads(q.read_text())
        if tamper == 'specification':
            raw['projects'][0]['base_annual_revenue_pence'] += 1
        else:
            raw['diagnostic_plans'].pop()
        q.write_text(json.dumps(raw))
    p.write_text(json.dumps(m))
    with pytest.raises(ValueError):
        entry.validate_prepared(output)

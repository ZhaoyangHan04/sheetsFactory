from collections import Counter

import pytest

from sheets_factory.workbook.linear_capital_portfolio import catalog,spec


def test_full_production_data_is_deterministic_before_any_finance_or_optimizer():
    first=catalog.build_spec();second=catalog.build_spec()
    assert spec.canonical_sha256(first)==spec.canonical_sha256(second)
    assert len(first['projects'])==240 and len(first['years'])==20 and len(first['scenarios'])==3
    assert set(p['debt_policy'] for p in first['projects'])=={'LEVEL_PRINCIPAL','BULLET'}
    assert set(p['operating_start_year'] for p in first['projects'])=={1,2,3}
    assert first['provenance']['ancestor_sha256']==[]
    assert all(p['lp_commitment_pence']==100*p['asset_cost_pence'] for p in first['projects'])


def test_site_alternatives_and_prerequisites_allow_substantial_selection_without_hidden_count():
    s=catalog.build_spec();members={pid for g in s['exclusivity_groups'] for pid in g['project_ids']}
    assert len(members)==120 and len(s['exclusivity_groups'])==40
    # Max160 possible choices under the public site rules; neither a secret
    # cardinality row nor a dense but structurally impossible target.
    assert 240-len(members)+len(s['exclusivity_groups'])==160
    independent=set(s['project_ids'][:40]);dependents=[e['dependent'] for e in s['prerequisites']]
    assert len(dependents)==len(set(dependents))==80
    assert all(e['prerequisite'] in independent and e['dependent'] not in independent for e in s['prerequisites'])
    assert all(e['prerequisite'] not in members for e in s['prerequisites'])


def test_dated_capacity_units_and_memberships_cover_all_public_scopes():
    s=catalog.build_spec();limits=s['shared_limits']
    assert set(p['region'] for p in s['projects'])==set(s['region_ids'])
    assert set(p['sector'] for p in s['projects'])==set(s['sector_ids'])
    for sid in s['scenario_ids']:
        assert limits['annual_debt_close_pence'][sid]['20']==0
        for resource in s['resource_ids']:
            assert all(limits['resource_capacity_units'][resource][sid][str(y)]>0 for y in s['years'])
    assert Counter(s['projects'][int(pid[1:])-1]['region'] for pid in s['exclusivity_groups'][0]['project_ids']).most_common(1)[0][1]==3


@pytest.mark.parametrize('seed',[True,-1,2**32,'20261031'])
def test_invalid_seed_types_or_ranges_reject(seed):
    with pytest.raises(ValueError,match='bounded integer'):
        catalog.build_spec(seed)


def test_a_new_seed_is_a_new_raw_assumption_universe():
    assert spec.canonical_sha256(catalog.build_spec(20261031))!=spec.canonical_sha256(catalog.build_spec(20261032))


def test_all_predeclared_diagnostics_are_complete_binary_plans_not_selected_winners():
    s=catalog.build_spec();plans=catalog.diagnostic_plans(s)
    assert len(plans)==len({p['id'] for p in plans})==18
    assert all(spec.validate_plan(s,p['plan'])==p['plan'] for p in plans)
    assert sum(plans[0]['plan'].values())==0 and sum(plans[1]['plan'].values())==240
    assert all(sum(p['plan'].values())==80 for p in plans[4:7])

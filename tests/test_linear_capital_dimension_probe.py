"""Pure dimension/frozen-kernel/complete-census tests; all services are forbidden."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import socket,subprocess
import pytest

from sheets_factory.workbook import linear_capital_dimension_probe as k
from sheets_factory.workbook.linear_capital_portfolio import candidate_a,ledger
from sheets_factory.workbook.linear_capital_scaled import catalog as catalog360
from test_linear_capital_portfolio_ledger import fixture as old_toy

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('dimension_probe_cli',ROOT/'scripts/prepare_linear_capital_dimension_probe.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)

@pytest.fixture(autouse=True)
def no_services(monkeypatch):
 def forbidden(*a,**kw):raise AssertionError('No service, native optimizer or process in pure tests')
 monkeypatch.setattr(subprocess,'run',forbidden);monkeypatch.setattr(subprocess,'Popen',forbidden)
 monkeypatch.setattr(socket,'create_connection',forbidden)


def toy(n=720):
 b=k.bundle(n);s=old_toy();s.update(kind=b.spec.SPEC_KIND,version=3);return b,s


@pytest.mark.parametrize('n,sites,links,rows',[(720,120,240,1121),(1080,180,360,1301)])
def test_fresh_full_dimensions_and_global_raw_capacities(n,sites,links,rows):
 b=k.bundle(n);s=b.catalog.build_spec();assert b.spec.load_spec(s)==s
 assert len(s['projects'])==n and len(s['exclusivity_groups'])==sites and len(s['prerequisites'])==links
 assert b.spec.PRODUCTION_ROW_COUNT==rows and len(b.catalog.diagnostic_plans(s))==18
 assert len({tuple(g['project_ids']) for g in s['exclusivity_groups']})==sites
 assert all(e['prerequisite'] in s['project_ids'][:sites] and e['dependent'] not in s['project_ids'][:sites] for e in s['prerequisites'])
 assert any(int(e['dependent'][1:])>360 for e in s['prerequisites'])
 old=catalog360.build_competitive_spec(b.catalog.SEED,150000)
 assert s['projects'][:360]!=old['projects']
 assert s['projects'][0]['resource_usage_units']!=s['projects'][360]['resource_usage_units']
 total=sum(p['asset_cost_pence'] for p in s['projects'])
 assert s['shared_limits']['annual_new_lp_pence']['S01']['1']==total*500//10000
 raw_equity=sum(p['asset_cost_pence']*4000//10000 for p in s['projects'])
 assert s['shared_limits']['initial_sponsor_equity_pence']==raw_equity*4500//10000
 for pid in ('P001',f'P{n:03d}'):
  assert all(pid in p['plan'] for p in b.catalog.diagnostic_plans(s))


def test_declared_schema_cannot_admit_other_dimension_or_old_N360():
 a=k.bundle(720);s=a.catalog.build_spec()
 with pytest.raises(ValueError):k.bundle(1080).spec.load_spec(s)
 with pytest.raises(ValueError):a.spec.load_spec(catalog360.build_spec())
 for n in (360,721,True,'720'):
  with pytest.raises(ValueError):k.bundle(n)


def test_original_financial_function_bytecode_and_old_globals_are_unchanged():
 originals=(candidate_a.simulate_project,candidate_a.simulate_universe,ledger.simulate_project,ledger.simulate_universe)
 for n in (720,1080):
  b=k.bundle(n)
  for frozen,adapted in zip(originals,(b.A.simulate_project,b.A.simulate_universe,b.B.simulate_project,b.B.simulate_universe)):
   assert adapted.__code__.co_code==frozen.__code__.co_code and adapted.__code__.co_consts==frozen.__code__.co_consts
   assert adapted.__globals__ is not frozen.__globals__
  assert b.A.simulate_universe.__globals__ is not b.B.simulate_universe.__globals__
  assert 'Decimal' not in b.A.__dict__ and 'Fraction' not in b.B.__dict__
  assert not hasattr(b.model_A,'solve_scip') and not hasattr(b.model_B,'solve_cp_sat')
 assert originals==(candidate_a.simulate_project,candidate_a.simulate_universe,ledger.simulate_project,ledger.simulate_universe)


def test_independent_hand_arithmetic_and_full_typed_matrix_scope():
 b,s=toy();a=b.A.simulate_universe(s);c=b.B.simulate_universe(s)
 for u in (a,c):
  r=u['projects']['P001']['scenarios']['S01'];assert r['t0']['lp_call']==500
  assert [x['bank_interest'] for x in r['annual']]==[50,25,0]
  assert r['annual'][-1]['current_tax']==131 and r['npv_pence']==394
 comp=cli.checked_financial_comparison(b,s,a,c)
 assert comp['passed'] and comp['counts']=={'project_scenarios':1,'t0_fields':11,'annual_fields':126,'vintage_fields':30,'posted_NPV':1}
 ma=b.model_A.build_model(s,a);mb=b.model_B.build_model(s,c)
 result=k.compare_matrices(ma,mb);assert result['passed'] and result['coefficients_compared']==len(ma['rows'])
 assert ma['kind'].endswith('_n720') and ma['version']==3
 for model in (ma,mb):assert model['objective_pence']==[394]


def test_full_historical_vintage_census_after_five_years_and_expired_loss_arithmetic():
 b=k.bundle(720);s=old_toy(years=7);s.update(kind=b.spec.SPEC_KIND,version=3)
 a=b.A.simulate_universe(s);c=b.B.simulate_universe(s)
 report=cli.checked_financial_comparison(b,s,a,c)
 # The comparison covers all historical origins, including implicit zeroes
 # absent from sparse events. The physical workbook has a last-five grid.
 assert report['passed'] and report['counts']['vintage_fields']==28*5
 assert report['counts']['vintage_fields']!=(1+2+3+4+5+5+5)*5
 for u in (a,c):
  r=u['projects']['P001']['scenarios']['S01']
  assert len(r['tax_vintages'])==9 and r['annual'][5]['loss_expired']==75
  assert r['annual'][5]['current_tax']==50 and r['annual'][6]['current_tax']==300
  assert r['npv_pence']==975


def test_supplied_universe_cannot_bypass_each_compilers_own_financial_forward():
 b,s=toy()
 for forward,model in ((b.A,b.model_A),(b.B,b.model_B)):
  u=forward.simulate_universe(s);u['projects']['P001']['scenarios']['S01']['annual'][0]['revenue']+=1
  with pytest.raises(ValueError):model.build_model(s,u)


@pytest.mark.parametrize('n',[720,1080])
def test_both_full_production_matrix_validators_reject_an_omitted_business_row(n):
 b=k.bundle(n);rows=[]
 for family,count in b.spec.PRODUCTION_COUNTS.items():
  for i in range(count):rows.append({'id':f'{family}:{i:04d}','family':family,'scenario_id':None,'year':None,'coefficients':[0]*n,'limit':0})
 rows.sort(key=lambda r:r['id'])
 model={'kind':b.model_A.KIND,'version':3,'project_ids':list(b.spec.PROJECT_IDS),'objective_pence':[0]*n,
  'rows':rows,'specification_sha256':'0'*64,'universe_sha256':'1'*64}
 for validator in (b.model_A.validate_model,b.model_B.validate_model):
  validator(model)
  bad={**model,'rows':rows[:-1]}
  with pytest.raises(ValueError):validator(bad)


@pytest.mark.parametrize('change',['missing_field','bool_money','vintage','NPV','duplicate_year','bounds'])
def test_every_typed_financial_tamper_is_retained_and_rejected(change):
 b,s=toy();a=b.A.simulate_universe(s);c=b.B.simulate_universe(s);r=c['projects']['P001']['scenarios']['S01']
 if change=='missing_field':del r['annual'][0]['revenue']
 elif change=='bool_money':r['annual'][0]['cash_close']=False
 elif change=='vintage':r['tax_vintages'][0]['created']+=1
 elif change=='NPV':r['npv_pence']+=1
 elif change=='duplicate_year':r['annual'][1]['year']=1
 else:r['arithmetic_bounds']['maximum_absolute_posted_value']=2**53
 report=b.comparison.compare_universes(s,a,c)
 assert not report['passed'] and (report['differences'] or report['schema_issues'])


@pytest.mark.parametrize('change',['last_coefficient','last_limit','objective_type','missing_row'])
def test_full_matrix_comparison_detects_last_position_and_type_changes(change):
 b,s=toy();a=b.model_A.build_model(s);c=b.model_B.build_model(s)
 if change=='last_coefficient':c['rows'][-1]['coefficients'][-1]+=1
 elif change=='last_limit':c['rows'][-1]['limit']+=1
 elif change=='objective_type':a['objective_pence'][0]=1;c['objective_pence'][0]=True
 else:c['rows'].pop()
 report=k.compare_matrices(a,c)
 assert report['passed'] is False and report['differences'] and report['differences_truncated'] is False


def test_frozen_upstream_change_fails_even_when_namespace_is_warm(tmp_path,monkeypatch):
 k.bundle(720);bad=tmp_path/'spec.py';bad.write_text('# wrong upstream')
 monkeypatch.setitem(k.UPSTREAMS,'spec',(bad,k.UPSTREAMS['spec'][1]))
 with pytest.raises(ValueError,match='Frozen upstream'):k.bundle(720)


@pytest.fixture
def prepared(tmp_path,monkeypatch):
 def forbidden(*a,**kw):raise AssertionError('Preparation/cold validation must run zero finance')
 for n in (720,1080):
  b=k.bundle(n);monkeypatch.setattr(b.A,'simulate_universe',forbidden);monkeypatch.setattr(b.B,'simulate_universe',forbidden)
 out=tmp_path/'probe';cli.prepare(out);return out


def test_both_raw_contracts_and_18_plans_are_frozen_before_finance(prepared):
 value=cli.validate_prepared(prepared)
 assert [r['id'] for r in value['profiles']]==['L720-D01','L1080-D01']
 assert all(len(cli.read(r['diagnostic_plans']))==18 for r in value['profiles'])
 assert not (prepared/'started.json').exists()
 for key in cli.ZERO:assert value[key]==0


def test_changed_peer_contract_blocks_every_financial_call_before_reservation(prepared):
 frozen=cli.read(prepared/'preparation.json');Path(frozen['profiles'][1]['specification']['path']).write_text('{}')
 with pytest.raises(ValueError,match='changed'):cli.execute_prepared(prepared)
 assert not (prepared/'started.json').exists()


def test_one_shot_pure_audit_preserves_both_failures_and_rejects_repeat(prepared):
 result=cli.read(cli.execute_prepared(prepared))
 assert result['passed'] is False and len(result['profile_terminals'])==2
 for r in result['profile_terminals']:
  case=cli.read(r);assert case['failure'] and case['qualified'] is False
  assert case['stages'][0]['status']=='failed' and case['financial_entry_attempts']['A']==1
 assert result['host_usage_at_end']['process_lifetime_peak_RSS_KiB']>0
 with pytest.raises(FileExistsError):cli.execute_prepared(prepared)


def test_two_launches_race_to_exactly_one_durable_start(prepared):
 def attempt(_):
  try:cli.execute_prepared(prepared);return True
  except FileExistsError:return False
 with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(attempt,range(2)))
 assert sorted(result)==[False,True] and (prepared/'terminal.json').exists()


def test_rejected_raw_candidate_is_retained_without_finance_or_replacement(tmp_path,monkeypatch):
 b=k.bundle(720)
 def rejected(*a,**kw):raise ValueError('Explicit raw rejection fixture')
 monkeypatch.setattr(b.catalog,'build_competitive_spec',rejected)
 out=tmp_path/'raw-rejection';frozen=cli.read(cli.prepare(out))
 assert frozen['all_raw_candidates_valid'] is False and len(frozen['raw_rejections'])==1
 assert frozen['raw_rejections'][0]['id']=='L720-D01' and frozen['profiles'][0]['id']=='L1080-D01'
 with pytest.raises(ValueError):cli.execute_prepared(out)
 assert not (out/'started.json').exists()

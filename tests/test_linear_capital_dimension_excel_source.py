"""Enlarged pure geometry, full tiny arithmetic and prospective resource gates."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import dis,json,socket,subprocess
from pathlib import Path

import openpyxl
import pytest

from sheets_factory.workbook import linear_capital_dimension_excel as excel
from sheets_factory.workbook import linear_capital_dimension_probe as probe
from sheets_factory.workbook import linear_capital_dimension_source_support as support
from sheets_factory.workbook import resource_engine,thread_capped_resource_engine
from sheets_factory.workbook.linear_capital_portfolio import excel as old_excel
from sheets_factory.workbook.linear_capital_scaled import excel as scaled_excel
from test_linear_capital_portfolio_ledger import fixture as hand_toy
from test_linear_capital_portfolio_excel import evaluate,expected


@pytest.fixture(autouse=True)
def no_services(monkeypatch):
 def forbidden(*args,**kwargs):raise AssertionError('Pure enlarged tests cannot call a native process or service')
 monkeypatch.setattr(subprocess,'run',forbidden);monkeypatch.setattr(subprocess,'Popen',forbidden)
 monkeypatch.setattr(socket,'create_connection',forbidden)


def toy(n,*,projects=1,years=3,scenarios=1):
 public=hand_toy(projects=projects,years=years,scenarios=scenarios)
 public.update(kind=probe.bundle(n).spec.SPEC_KIND,version=3)
 return public


@pytest.mark.parametrize('n',[720,1080])
def test_complete_nontrivial_toy_formulas_and_geometry_match_independent_A_B(n,tmp_path):
 b=probe.bundle(n);e=excel.for_dimension(n);s=support.for_dimension(n)
 public=toy(n,projects=3,years=7,scenarios=3)
 public['projects'][0].update(depreciation_years=3,revenue_growth_factor_bp=10500,opex_growth_factor_bp=10250,discount_rate_bp=750)
 public['projects'][1].update(debt_policy='BULLET',operating_start_year=2,base_annual_revenue_pence=30,base_annual_opex_pence=200)
 public['scenarios'][1]['revenue_factors_bp']['3']=8500
 public['exclusivity_groups']=[{'id':'SITE','description':'Alternative developments','project_ids':['P001','P002']}]
 public['prerequisites']=[{'id':'LINK','dependent':'P003','prerequisite':'P001','business_reason':'Separate access connection'}]
 plan={'P001':1,'P002':0,'P003':1};path=tmp_path/'uncached_toy_not_gold.xlsx'
 binding=e.emit_workbook(path,public,plan=plan)
 a,c=b.A.simulate(public,plan),b.B.simulate(public,plan);values=evaluate(binding,public,plan)
 for row in binding['financial_bindings']:
  assert values[row['sheet'],row['cell']]==expected(row,a)==expected(row,c)
 wanted=s.expected_values(public,a,c,binding,plan)
 literals,geometry=s.raw_geometry(path,public,binding,wanted,support.load_runtime_profile(s.profile_path))
 count=excel.count_geometry(n,public,plan=plan)
 assert wanted['formula_count']==binding['formula_count']==geometry['physical_formula_count']==count['source_physical_formulas']
 assert len(wanted['values'])==geometry['nonempty_cells']==count['max_profile_cells']
 assert len(binding['financial_bindings'])+3==count['full_target_cells']
 assert geometry['complete_business_field_coverage']['missing']==geometry['complete_business_field_coverage']['extra']==0
 assert binding['kind']==e.BINDING_KIND and binding['constraint_count']==count['complete_business_rows']
 assert binding['financial_implementation_executed'] is binding['optimization_executed'] is False
 assert e.emit_workbook.__globals__ is not old_excel.emit_workbook.__globals__
 report=s.audit_workbook(path,public,a,c,binding,plan,literals)
 assert report['passed'] is False and report['mismatch_count']>0  # Uncalculated input is never cache evidence.
 assert report['money_quantization_applied'] is False and report['additional_financial_forwards']==0
 changed=deepcopy(c);changed['projects']['P003']['scenarios']['S03']['annual'][-1]['cash_close']+=1
 with pytest.raises(ValueError,match='disagree'):s.expected_values(public,a,changed,binding,plan)
 incomplete=deepcopy(binding);incomplete['financial_bindings'].pop()
 with pytest.raises(ValueError,match='census'):s.financial_locator_coverage(public,incomplete)


@pytest.mark.parametrize('n',[720,1080])
def test_production_counts_without_a_workbook_have_small_explicit_headroom(n,monkeypatch):
 b=probe.bundle(n);public=b.catalog.build_spec();plan={pid:0 for pid in public['project_ids']}
 def forbidden(*args,**kwargs):raise AssertionError('Production count must not allocate a workbook or execute finance')
 monkeypatch.setattr(openpyxl,'Workbook',forbidden)
 monkeypatch.setattr(b.A,'simulate_universe',forbidden);monkeypatch.setattr(b.B,'simulate_universe',forbidden)
 count=excel.count_geometry(n,public,plan=plan)
 exact={720:(2491308,3540326,3041027,1121,730),1080:(3735288,5307086,4559867,1301,1090)}[n]
 assert (count['source_physical_formulas'],count['max_profile_cells'],count['full_target_cells'],count['complete_business_rows'],count['sheet_count'])==exact
 assert count['workbooks_allocated']==count['financial_forwards']==count['optimizer_calls']==count['LO_calls']==0
 profile=support.load_runtime_profile(support.profile_path(n),dimension=n)
 counts={k:count[k]for k in support.COUNT_KEYS}
 assert support.validate_workload_counts(profile,counts,dimension=n)['truncation_allowed'] is False
 assert all(counts[k]<profile['limits'][k]<=counts[k]*1.1 for k in counts)
 assert count['qualified'] is count['native_runtime_memory_or_financial_equivalence_measured'] is False


@pytest.mark.parametrize('n',[720,1080])
@pytest.mark.parametrize('damage',['bool_cpu','agent_memory','PID','file_timeout','verifier_timeout','tool_budget','parallel_wall','limit','truncate','old_id','image'])
def test_only_dimension_identity_and_frozen_explicit_ceiling_changes_allowed(n,damage):
 p=support.load_runtime_profile(support.profile_path(n));p=deepcopy(p)
 if damage=='bool_cpu':p['docker_resources']['source']['cpus']=True
 elif damage=='agent_memory':p['docker_resources']['agent']['memory_bytes']*=2
 elif damage=='PID':p['docker_resources']['source']['pids_limit']=512
 elif damage=='file_timeout':p['timeouts']['workbook_file_seconds']=601
 elif damage=='verifier_timeout':p['timeouts']['verifier_total_seconds']=2401
 elif damage=='tool_budget':p['solver_tool_budget']['seconds']=1801
 elif damage=='parallel_wall':p['solver_tool_budget']['parallel_executions']='wall'
 elif damage=='limit':p['limits']['source_physical_formulas']+=1
 elif damage=='truncate':p['limits']['truncate']=True
 elif damage=='old_id':p['id']='entity_group_large_v2'
 else:p['image']['id']='sha256:'+'0'*64
 with pytest.raises(ValueError):support.load_runtime_profile(p,dimension=n)


@pytest.mark.parametrize('n',[720,1080])
def test_caps_scope_no_truncation_namespace_and_old_limits_unchanged(n,tmp_path):
 e=excel.for_dimension(n);p=toy(n)
 assert e.emit_workbook.__kwdefaults__['max_formulas']==excel.FORMULA_CAPS[n]
 for bad in (True,0,excel.FORMULA_CAPS[n]+1):
  with pytest.raises(ValueError,match='cap'):e.emit_workbook(tmp_path/'invalid.xlsx',p,max_formulas=bad)
  assert not (tmp_path/'invalid.xlsx').exists()
 with pytest.raises(ValueError,match='no truncation'):e.emit_workbook(tmp_path/'too_small.xlsx',p,max_formulas=1)
 assert not (tmp_path/'too_small.xlsx').exists()
 with pytest.raises(ValueError):excel.for_dimension(1080 if n==720 else 720).emit_workbook(tmp_path/'wrong.xlsx',p)
 profile=support.load_runtime_profile(support.profile_path(n))
 with pytest.raises(ValueError):support.load_runtime_profile(profile,dimension=1080 if n==720 else 720)
 counts=dict(zip(support.COUNT_KEYS,support.LIMITS[n]));counts['full_target_cells']+=1
 with pytest.raises(ValueError,match='no truncation'):support.validate_workload_counts(profile,counts)
 assert old_excel.emit_workbook.__kwdefaults__['max_formulas']==1_000_000
 assert scaled_excel.emit_workbook.__kwdefaults__['max_formulas']==1_500_000
 assert resource_engine.load_runtime_profile(support.BASE_PROFILE)['limits']['source_physical_formulas']==2_000_000
 with pytest.raises(ValueError):resource_engine.load_runtime_profile(support.profile_path(n))
 assert support.for_dimension(n).NO_SOURCE_ADMISSION and not hasattr(support.for_dimension(n),'execute_prepared')


@pytest.mark.parametrize('n',[720,1080])
def test_private_resource_classes_preserve_original_calculation_cleanup_and_cap_algorithms(n,tmp_path):
 s=support.for_dimension(n);cls=s.ResourceLibreOfficeEngine;private_base=cls.__bases__[0]
 engine=cls(tmp_path,s.profile_path,role='source',receipt_directory=tmp_path/'receipts')
 assert engine.profile['id']==f'linear_capital_n{n}_native_engineering_v1'
 assert engine.timeout_seconds==600 and engine.image_id is None
 assert engine.profile['docker_resources']['source']=={'cpus':2,'memory_bytes':32*1024**3,'pids_limit':256}
 for name in ('__init__','ensure_image','_run','recalculate','metadata'):
  a,b=getattr(private_base,name).__code__,getattr(resource_engine.ResourceLibreOfficeEngine,name).__code__
  assert a.co_consts==b.co_consts and a.co_names==b.co_names
  assert [(i.opname,i.argval)for i in dis.get_instructions(a)]==[(i.opname,i.argval)for i in dis.get_instructions(b)]
 for name in ('__init__','_run','_inspect_cap'):
  a,b=getattr(cls,name).__code__,getattr(thread_capped_resource_engine.ThreadCappedResourceLibreOfficeEngine,name).__code__
  assert a.co_consts==b.co_consts and a.co_names==b.co_names
  assert [(i.opname,i.argval)for i in dis.get_instructions(a)]==[(i.opname,i.argval)for i in dis.get_instructions(b)]
 assert cls is not thread_capped_resource_engine.ThreadCappedResourceLibreOfficeEngine
 assert private_base.recalculate.__globals__ is not resource_engine.ResourceLibreOfficeEngine.recalculate.__globals__
 assert private_base.recalculate.__globals__['__file__']==support.__file__


def synthetic_resource_receipt(tmp_path,n):
 s=support.for_dimension(n);ref=s.reference
 src=tmp_path/'input.xlsx';src.write_bytes(b'unit mock only; no native execution')
 dst=tmp_path/'output.xlsx';dst.write_bytes(b'unit mock only; no native execution')
 call={'input':ref(src),'output':ref(dst)};profile=support.load_runtime_profile(s.profile_path)
 frozen={'runtime_profile':ref(s.profile_path),'runtime_profile_value':profile};cid='a'*64
 start=datetime(2026,10,31,tzinfo=timezone.utc);call_id='synthetic_only'
 record={'kind':'resource_bound_libreoffice_call','status':'completed','role':'source','actual_resources_verified':True,
  'source':call['input'],'output':call['output'],'destination':str(dst),'image_id':profile['image']['id'],
  'profile':frozen['runtime_profile'],'requested_resources':profile['docker_resources']['source'],
  'implementation':ref(support.__file__),'upstream_engine':ref(resource_engine.original_engine.__file__),
  'workbook_file_timeout_seconds':600,'actual_resources':{'cpus_nanoseconds':2*10**9,'memory_bytes':32*1024**3,'pids_limit':256},
  'container_id':cid,'create_command':['docker','create','--network','none','--cap-drop','ALL','--security-opt','no-new-privileges','--env','MAX_CONCURRENCY=2'],
  'started_at':start.isoformat(),'finished_at':(start+timedelta(seconds=3)).isoformat(),'call_id':call_id,
  'thread_cap_adapter':ref(support.__file__),'thread_cap_verified':True}
 for i,stage in enumerate(('before','after'),1):
  record['thread_cap_'+stage]={'stage':stage,'container_id':cid,'variable':'MAX_CONCURRENCY','values':['MAX_CONCURRENCY=2'],
   'inspect_command':thread_capped_resource_engine._inspect_command(cid),'inspected_at':(start+timedelta(seconds=i)).isoformat()}
 record['thread_cap_after']['exit_code_observed']='0'
 started=tmp_path/(call_id+'.started.json');s.write(started,{'call_id':call_id,'source':call['input'],'started_at':start.isoformat()})
 return s,call,frozen,record


@pytest.mark.parametrize('n',[720,1080])
@pytest.mark.parametrize('damage',[None,'old_implementation','old_cap','wrong_CID','missing_after','profile_drift'])
def test_complete_resource_proof_requires_new_identity_and_unchanged_full_cap_evidence(n,damage,tmp_path):
 s,call,frozen,record=synthetic_resource_receipt(tmp_path,n)
 if damage=='old_implementation':record['implementation']=s.reference(resource_engine.__file__)
 elif damage=='old_cap':record['thread_cap_adapter']=s.reference(thread_capped_resource_engine.__file__)
 elif damage=='wrong_CID':record['thread_cap_after']['container_id']='b'*64
 elif damage=='missing_after':del record['thread_cap_after']
 elif damage=='profile_drift':frozen['runtime_profile_value']['docker_resources']['source']['cpus']=4
 receipt=s.write(tmp_path/'synthetic_only.terminal.json',record)
 if damage is None:
  checked=s.validate_actual_call(call,receipt,frozen);assert checked['thread_cap_verified'] and checked['container_id']=='a'*64
 else:
  with pytest.raises((ValueError,resource_engine.WorkbookEngineError)):s.validate_actual_call(call,receipt,frozen)


def test_typed_stability_keeps_text_boolean_and_full_union(tmp_path):
 a=tmp_path/'a.xlsx';b=tmp_path/'b.xlsx';book=openpyxl.Workbook();book.active['A1']=False;book.save(a);book.close()
 book=openpyxl.Workbook();book.active['A1']=False;book.save(b);book.close()
 s=support.for_dimension(720);assert s.compare_typed_caches(a,b)['passed'] is True
 book=openpyxl.load_workbook(b);book.active['A1']=0;book.active['Z9']='extra';book.save(b);book.close()
 result=s.compare_typed_caches(a,b);assert result['passed'] is False and result['union_cells_checked']==2


def test_upstream_drift_fails_even_when_private_namespaces_are_warm(tmp_path,monkeypatch):
 support.for_dimension(720);bad=tmp_path/'excel.py';bad.write_text('# changed')
 monkeypatch.setattr(excel,'UPSTREAM',bad)
 with pytest.raises(ValueError,match='Frozen'):support.for_dimension(720)

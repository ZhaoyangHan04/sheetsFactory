#!/usr/bin/env python3
"""Freeze both enlarged raw candidates, then explicitly run host-only A/B audits.

No workbook/resource/solver/normal-quality or model entry is used. Peak RSS is
the host process lifetime high-water mark, not measured container headroom.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib,json,os,resource,sys,time,traceback
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.workbook import linear_capital_dimension_probe as kernel
DEFAULT_CONFIG=ROOT/'config/research/linear_capital_dimension_probe_v1.json'
PREPARED='prepared_linear_capital_dimension_pure_probe'
TERMINAL='completed_linear_capital_dimension_pure_probe'
PROFILES=[{'id':'L720-D01','projects':720,'seed':202710720,'revenue_jitter_pence':150000},
 {'id':'L1080-D01','projects':1080,'seed':202711080,'revenue_jitter_pence':150000}]
ZERO=('optimizer_calls','LO_calls','model_calls','Harbor_calls','network_calls','workbook_emission_calls')
require=kernel.require


def reference(path):
 p=Path(path).absolute();require(p==p.resolve() and p.is_file(),'A real artifact is required')
 before=p.stat()
 with p.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
 after=p.stat();require((before.st_ino,before.st_size,before.st_mtime_ns)==(after.st_ino,after.st_size,after.st_mtime_ns),'Artifact changed while hashing')
 return {'path':str(p),'sha256':digest,'bytes':after.st_size}


def read(value):
 r=value if isinstance(value,dict) else reference(value)
 require(reference(r['path'])==r,'A frozen artifact changed')
 def unique(rows):
  result={}
  for k,v in rows:require(k not in result,'Duplicate JSON key');result[k]=v
  return result
 return json.loads(Path(r['path']).read_text(),object_pairs_hook=unique,
  parse_constant=lambda _:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def write(path,value):
 p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:json.dump(value,f,indent=2,allow_nan=False);f.write('\n')
 return reference(p)


def recipes():
 return {str(Path(p).resolve()):reference(p) for p in [__file__,DEFAULT_CONFIG,*kernel.source_files().values()]}


def configuration(path=DEFAULT_CONFIG):
 value=read(path)
 require(value.get('kind')=='fixed_linear_capital_dimension_pure_probe' and value.get('version')==1
  and value.get('profiles')==PROFILES and value.get('diagnostic_plans_per_profile')==18
  and value.get('all_contracts_and_plans_frozen_before_any_financial_forward') is True
  and value.get('retain_all_results_without_replacement') is True
  and all(type(value.get(k)) is int and value[k]==0 for k in ZERO)
  and value.get('container_resource_claimed') is False
  and value.get('source_or_quality_or_difficulty_certified') is False,'The complete fixed pure-probe declaration changed')
 return value


def prepare(output,*,config_path=DEFAULT_CONFIG):
 config=configuration(config_path);out=Path(output).absolute()
 require(out==out.resolve() and not out.exists(),'Use a fresh real preparation; preserve prior outcomes')
 out.mkdir(parents=True);rows=[];failures=[]
 for policy in config['profiles']:
  folder=out/policy['id'];folder.mkdir()
  try:
   b=kernel.bundle(policy['projects']);public=b.catalog.build_competitive_spec(policy['seed'],policy['revenue_jitter_pence'])
   plans=b.catalog.diagnostic_plans(public,seed=policy['seed']);require(len(plans)==18,'All fixed diagnostics required')
   rows.append({**policy,'specification':write(folder/'specification.json',public),
    'diagnostic_plans':write(folder/'diagnostic_plans.json',plans),'specification_sha256':b.spec.canonical_sha256(public)})
  except Exception as error:
   failures.append({**policy,'failure':write(folder/'raw_rejection.json',{'error_type':type(error).__name__,'error':str(error),'no_financial_computation_started':True})})
 return write(out/'preparation.json',{'kind':PREPARED,'version':1,'prepared_at':datetime.now(timezone.utc).isoformat(),
  'configuration':reference(config_path),'recipe':recipes(),'profiles':rows,'raw_rejections':failures,
  'all_raw_candidates_valid':not failures,'all_peers_frozen_before_finance':not failures,
  'all_results_retained':True,'source_or_quality_or_difficulty_certified':False,**{k:0 for k in ZERO}})


def validate_prepared(output):
 frozen=read(Path(output)/'preparation.json');config=configuration(frozen['configuration'])
 require(frozen.get('kind')==PREPARED and frozen.get('version')==1 and frozen.get('recipe')==recipes()
  and frozen.get('all_raw_candidates_valid') is True and frozen.get('all_peers_frozen_before_finance') is True
  and frozen.get('raw_rejections')==[] and len(frozen['profiles'])==2
  and frozen.get('source_or_quality_or_difficulty_certified') is False
  and all(type(frozen.get(k)) is int and frozen[k]==0 for k in ZERO),'Complete frozen pure preparation required')
 for row,policy in zip(frozen['profiles'],config['profiles']):
  require({k:row[k] for k in policy}==policy,'The common candidate inventory changed')
  b=kernel.bundle(policy['projects']);public=b.spec.load_spec(read(row['specification']));plans=read(row['diagnostic_plans'])
  require(public==b.catalog.build_competitive_spec(policy['seed'],policy['revenue_jitter_pence'])
   and row['specification_sha256']==b.spec.canonical_sha256(public)
   and plans==b.catalog.diagnostic_plans(public,seed=policy['seed']),'Frozen contracts/plans changed or were replaced')
 return frozen


def host_usage():
 r=resource.getrusage(resource.RUSAGE_SELF)
 return {'process_cpu_seconds':time.process_time(),'user_cpu_seconds':r.ru_utime,'system_cpu_seconds':r.ru_stime,
  'process_lifetime_peak_RSS_KiB':r.ru_maxrss,'peak_scope':'Linux RUSAGE_SELF process-lifetime high-water; not stage-local nor container memory'}


def checked_financial_comparison(b,public,a,c):
 value=b.comparison.compare_universes(public,a,c);n=len(public['project_ids']);s=len(public['scenario_ids']);y=len(public['years'])
 expected={'project_scenarios':n*s,'t0_fields':n*s*len(b.spec.T0_FIELDS),
  'annual_fields':n*s*y*(len(b.spec.ANNUAL_FIELDS)+2),
  'vintage_fields':n*s*sum(min(i,5) for i in range(1,y+1))*len(b.spec.VINTAGE_FIELDS),'posted_NPV':n*s}
 complete=value['counts']==expected
 return {**value,'expected_complete_field_counts':expected,'complete_typed_field_census_passed':complete,
  'passed':value['passed'] and complete}


def execute_prepared(output):
 out=Path(output).absolute();frozen=validate_prepared(out)
 # Exclusive durable reservation guards concurrent calls and survives failure.
 fd=os.open(out/'started.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
 with os.fdopen(fd,'w') as f:json.dump({'preparation':reference(out/'preparation.json'),'started_at':datetime.now(timezone.utc).isoformat(),'pid':os.getpid(),'outer_retries':0},f)
 started=time.perf_counter();cpu=time.process_time();start_usage=host_usage();outcomes=[]
 for row in frozen['profiles']:
  folder=out/row['id'];stages=[];records={};tick=time.perf_counter();ct=time.process_time();b=kernel.bundle(row['projects'])
  public=b.spec.load_spec(read(row['specification']));plans=read(row['diagnostic_plans']);a=c=ma=mb=None;failure=None
  def stage(name,operation):
   wall=time.perf_counter();cpu_tick=time.process_time();status='failed'
   try:
    v=operation();records[name]=write(folder/(name+'.json'),v);status='completed';return v
   finally:
    stats={'stage':name,'status':status,'wall_seconds':time.perf_counter()-wall,'cpu_seconds':time.process_time()-cpu_tick,**host_usage(),'artifact':records.get(name)};stages.append(stats)
    print(json.dumps({'profile':row['id'],**stats}),flush=True)
  try:
   a=stage('universe_A',lambda:b.A.simulate_universe(public))
   c=stage('universe_B',lambda:b.B.simulate_universe(public))
   comparison=stage('complete_typed_financial_comparison',lambda:checked_financial_comparison(b,public,a,c))
   require(comparison['passed'] is True,'Complete independent typed postings rejected')
   plancheck=stage('all_18_diagnostic_plans',lambda:b.comparison.compare_plans(public,a,c,plans,require_feasible=False))
   require(plancheck['passed'] is True and plancheck['plan_count']==18,'Complete diagnostic comparison rejected')
   ma=stage('model_A',lambda:b.model_A.build_model(public,a))
   mb=stage('model_B',lambda:b.model_B.build_model(public,c))
   matrix=stage('complete_matrix_comparison',lambda:kernel.compare_matrices(ma,mb))
   require(matrix['passed'] is True and matrix['row_count']==b.spec.PRODUCTION_ROW_COUNT
    and matrix['coefficients_compared']==row['projects']*b.spec.PRODUCTION_ROW_COUNT,'Complete matrix comparison rejected')
  except Exception as error:
   failure=write(folder/'failure.json',{'error_type':type(error).__name__,'error':str(error),'traceback':traceback.format_exc(),'all_partial_evidence_retained':True})
  result={'id':row['id'],'passed':failure is None,'specification':row['specification'],'diagnostic_plans':row['diagnostic_plans'],
   'records':records,'stages':stages,'wall_seconds':time.perf_counter()-tick,'cpu_seconds':time.process_time()-ct,
   'host_usage_at_end':host_usage(),'failure':failure,
   'financial_forward_completions_lower_bound':{'A':int(a is not None)+int(ma is not None),'B':int(c is not None)+int(mb is not None)},
   'financial_entry_attempts':{'A':sum(s['stage'] in ('universe_A','model_A') for s in stages),'B':sum(s['stage'] in ('universe_B','model_B') for s in stages)},
   'forward_counts_exact_on_pass':failure is None,'each_model_compiler_resimulates_own_financial_forward':True,
   'fixed_plan_group_capacity_violations_are_expected_diagnostics':True,'container_resource_claimed':False,
   'actual32GiB_or_600second_source_feasibility_established':False,'qualified':False,**{k:0 for k in ZERO}}
  outcomes.append(write(folder/'terminal.json',result));a=c=ma=mb=None
 validate_prepared(out)
 terminal={'kind':TERMINAL,'version':1,'passed':all(read(r)['passed'] for r in outcomes),'preparation':reference(out/'preparation.json'),
  'completed_at':datetime.now(timezone.utc).isoformat(),'profile_terminals':outcomes,'wall_seconds':time.perf_counter()-started,
  'cpu_seconds':time.process_time()-cpu,'host_usage_at_start':start_usage,'host_usage_at_end':host_usage(),
  'container_resource_claimed':False,'actual32GiB_or_600second_source_feasibility_established':False,
  'source_or_quality_or_difficulty_certified':False,'qualified':False,**{k:0 for k in ZERO}}
 return write(out/'terminal.json',terminal)


def main(argv=None):
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--run',action='store_true');p.add_argument('--prepared',action='store_true');a=p.parse_args(argv)
 if a.prepared:result=execute_prepared(a.output) if a.run else reference(a.output/'preparation.json');validate_prepared(a.output)
 else:
  result=prepare(a.output)
  if a.run:result=execute_prepared(a.output)
 print(json.dumps(result));return 0

if __name__=='__main__':raise SystemExit(main())

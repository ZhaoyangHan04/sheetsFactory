#!/usr/bin/env python3
"""Prepare audited mode-specific seeds; explicitly run the normal quality factory."""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.dashboard import DashboardServer
from sheets_factory.llm import CodexCLI
from sheets_factory.pipelines import FactoryPipeline
from sheets_factory.resume import ProducerLease, prepare_resume
from sheets_factory.workbook.engine import LibreOfficeEngine

IMAGE='sheetsfactory-lo:24.2-iterative-openpyxl315-v1'
IMAGE_ID='sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
MODES=('financial_modeling','debugging')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def ref(path):return {'path':str(Path(path).resolve()),'sha256':sha(path)}
def write(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('x') as stream:stream.write(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def require(value,message):
 if not value:raise ValueError(message)
def checked(reference):
 path=Path(reference['path']).resolve()
 require(path.is_file() and sha(path)==reference['sha256'],'Changed or missing audited artifact: '+str(path))
 return path

def track_references(value,bindings):
 if isinstance(value,dict):
  if 'path' in value and 'sha256' in value:
   path=checked(value);bindings[str(path)]=value['sha256']
  for child in value.values():track_references(child,bindings)
 elif isinstance(value,list):
  for child in value:track_references(child,bindings)

def build_attempt(batch,entry,bindings):
 matches=[a for a in batch.get('attempts',[]) if a.get('stage')=='build' and a.get('id')==entry.get('profile_id')]
 require(len(matches)==1 and matches[0].get('status')=='verified','Source has no unique original verified build attempt')
 attempt=matches[0]
 require(attempt['source_manifest']['path']==entry['source_manifest']['path']
         and attempt['source_manifest']['sha256']==entry['source_manifest']['sha256'],'Build attempt source manifest differs')
 track_references(attempt,bindings)
 return attempt

def validate_batch(batch,bindings):
 selected=batch.get('selected')
 require(batch.get('status')=='independently_verified_composed_financial_seed_batch' and batch.get('mode')=='build'
  and batch.get('recipe_unchanged') is True and isinstance(selected,list)
  and batch.get('verified_derived_workbook_count')==len(selected)==batch.get('target_derived_workbook_count')
  and batch.get('model_scores_consulted') is False,'A complete unchanged actually verified source build batch is required')
 for name in ('source_selection','plan','scenario_config'):track_references(batch[name],bindings)
 selection=read(checked(batch['source_selection']))
 require(selection.get('profiles')==[e.get('profile_id') for e in selected]
  and selection.get('model_results_consulted') is False,'The declared frozen source order changed')
 return selected


def validate_seed(entry,attempt=None):
 """Resolve normalization only from a complete, hash-bound financial proof."""
 source_manifest=checked(entry['source_manifest']);source=read(source_manifest)
 book=Path(source['local_path']).resolve()
 identity=entry['sha256']
 require(book.is_file() and sha(book)==identity==source['derived_workbook_sha256'], 'Audited source workbook SHA differs')
 require(Path(entry['local_path']).resolve()==book,'Seed points outside its audited source workbook')
 require(source.get('financial_audit_passed') is True,'Source has no passing financial audit')
 require(source['runtime']['image']==IMAGE and source['runtime']['image_id']==IMAGE_ID,'Source runtime is not the pinned image')
 provided_path=checked(source['provided_context_audit']);provided=read(provided_path)
 require(provided.get('passed') is True and not provided.get('mismatches') and not provided.get('missing_sheets'),
         'Provided upstream data audit did not pass')
 require(Path(provided['completed']['path']).resolve()==book and provided['completed']['sha256']==identity,
         'Provided-data audit does not bind the exact source workbook')
 scenarios_path=checked(source['public_scenarios'])
 summary_path=checked(source['financial_audit']);summary=read(summary_path)
 stable_path=checked(source['stability']);stable=read(stable_path)
 require(stable.get('stable') is True and all(stable.get(k,{}).get('reward')==1 for k in ('first_against_goal','second_against_goal')),
         'Source lacks two actual stable recalculations')
 audits={}
 if attempt is None:
  batch_ref=entry.get('finance_evidence',{}).get('source_batch_manifest')
  require(isinstance(batch_ref,dict),'Admitted source lacks its original batch binding')
  attempt=build_attempt(read(checked(batch_ref)),entry,{})
 verification=attempt['verification']
 old_audits=verification.get('component_audits',verification.get('four_audits',{}))
 require(set(old_audits)==set(source['financial_audits']),'Original component audit coverage differs')
 require(set(source['financial_audits'])>= {'lease','programme','operating','holding'}, 'Missing required financial modules')
 for name,declared in source['financial_audits'].items():
  path=source_manifest.parent/'private'/(name+'_financial_audit.json');audit=read(path)
  require(checked(old_audits[name])==path.resolve(),'Financial audit differs from the original verified build')
  require(Path(audit['workbook']['path']).resolve()==book and audit['workbook']['sha256']==identity,
          'Financial audit does not bind the exact source workbook: '+name)
  require(audit.get('passed') is True and audit.get('checked_cells')==declared.get('checked_cells')
          and summary.get(name)==declared,'Incomplete actual financial audit: '+name)
  for key in ('mismatches','control_mismatches','uncovered','uncovered_formulas','native_errors','invalid_formula_values'):
   require(not audit.get(key),'Financial audit contains unresolved findings: '+name)
  audits[name]={**ref(path),'passed':True,'checked_cells':audit['checked_cells']}
 return {'workbook':ref(book),'source_manifest':ref(source_manifest),'provided_context_audit':ref(provided_path),
         'public_scenarios':ref(scenarios_path),'financial_audit_summary':ref(summary_path),
         'stability':ref(stable_path),'independent_financial_audits':audits,
         'original_build_verification_sha256':hashlib.sha256(json.dumps(verification,sort_keys=True).encode()).hexdigest()}


def prepare_cohort(source_manifest,output,*,mode='financial_modeling',count=10,project_root=ROOT):
 root=Path(project_root).resolve();source_manifest=Path(source_manifest).resolve();output=Path(output).resolve()
 require(mode in MODES and type(count) is int and count==10,'A cohort admission contains exactly ten sources in one mode')
 require(not output.exists(),'Preparation output already exists; frozen preparations are never overwritten')
 raw=source_manifest.read_bytes();batch=json.loads(raw)
 entries=[];identities=set();task_ids=set();bindings={str(source_manifest):hashlib.sha256(raw).hexdigest()}
 selected=validate_batch(batch,bindings)
 require(len(selected)==count,'A mode cohort must admit the complete ten-source frozen selection')
 for candidate in selected:
  entry=deepcopy(candidate);attempt=build_attempt(batch,entry,bindings);proof=validate_seed(entry,attempt)
  require(entry['sha256'] not in identities,'Duplicate audited source identity');identities.add(entry['sha256'])
  task_id=('fm-' if mode=='financial_modeling' else 'dbg-')+entry['sha256'][:12]
  require(task_id not in task_ids,'Source prefixes produce duplicate task IDs');task_ids.add(task_id)
  evidence={**entry.get('finance_evidence',{}),'financial_seed_verified':True,'financial_modeling_eligible':True,
   'source_batch_manifest':ref(source_manifest),'source_manifest':proof['source_manifest'],
   'independent_financial_audits':proof['independent_financial_audits'],
   'complete_independent_reference_audits':proof['independent_financial_audits'],
   'provided_context_audit':proof['provided_context_audit'],'public_scenarios':proof['public_scenarios'],
   'source_stability':proof['stability'],'audited_source_binding':proof}
  entry.update(modes=[mode],variant=0,finance_evidence=evidence,
               survey={'normalized_path':proof['workbook']['path'],'source_sha256':entry['sha256'],'status':'ok','error_count':0})
  entries.append(entry)
  def record(value):
   if isinstance(value,dict):
    if 'path' in value and 'sha256' in value:bindings[value['path']]=value['sha256']
    else:
     for item in value.values():record(item)
  record(proof)
 config_path=root/'config/pipelines/composite_quality20.yaml'
 config=yaml.safe_load(config_path.read_text());llm=yaml.safe_load((root/'config/llm.yaml').read_text())
 agent=yaml.safe_load((root/'config/agents.yaml').read_text())
 config['agents']={**llm,**config['agents'],'roles':{**agent.get('roles',{}),**config['agents'].get('roles',{})}}
 config['prompt_overrides']={**agent.get('prompts',{}),**config.get('prompt_overrides',{})}
 config.update(project_root=str(root),run_dir=str(output));config['run']['seed_manifest']=str(output/'seed_manifest.json')
 for p,h in bindings.items():require(sha(p)==h,'Original source evidence changed during preflight: '+p)
 output.mkdir(parents=True)
 prepared={'schema_version':1,'kind':'audited_mode_specific_factory_sources','qualified':False,'task_count':0,
  'selected':entries,'unique_workbooks_inspected':len(entries),'download_url':'private-audited-composite-batch:'+sha(source_manifest),
  'archive_sha256':None,'source_batch_manifest':ref(source_manifest),'source_ancestor_unique_count':batch.get('source_ancestor_unique_count'),
  'derived_scenarios_are_independent_observed_companies':False}
 write(output/'seed_manifest.json',prepared)
 (output/'resolved_config.yaml').write_text(yaml.safe_dump(config,sort_keys=False))
 recipe_paths=[Path(__file__).resolve(),config_path,root/'src/sheets_factory/pipelines/factory.py',
  root/'src/sheets_factory/nodes/construction.py',root/'src/sheets_factory/nodes/quality.py',
  root/'src/sheets_factory/checkers/runner.py',root/'src/sheets_factory/checkers/reference_evidence.py',
  root/'prompts/diagnosis_reference.md',root/'config/nodes.yaml',root/'config/checkers.yaml',root/'config/routes.yaml']
 recipe_paths.extend(root/'src/sheets_factory/pipelines/templates'/(name+'.yaml') for name in MODES)
 for directory in ('nodes','checkers','llm'):
  recipe_paths.extend((root/'src/sheets_factory'/directory).glob('*.py'))
 for directory in ('composite_finance','lease_finance','derived_regulatory','derived_gold','holding_treasury','contingent_recovery','partner_waterfall'):
  recipe_paths.extend((root/'src/sheets_factory/workbook'/directory).glob('*.py'))
 recipe_paths.extend(root/'src/sheets_factory/workbook'/name for name in ('engine.py','compare.py','uno_recalculate.py'))
 recipe_paths.extend((root/'prompts').glob('*.md'))
 recipe_paths.extend(root/'config'/name for name in ('agents.yaml','llm.yaml'))
 frozen={'kind':'prepared_normal_quality_cohort','prepared_at':utcnow(),'mode':mode,'source_count':count,
  'targets':config['run']['targets'],'source_artifacts_sha256':bindings,'source_batch_manifest':ref(source_manifest),
  'prepared_seed_manifest':ref(output/'seed_manifest.json'),'resolved_config':ref(output/'resolved_config.yaml'),
  'recipe_sha256':{str(p):sha(p) for p in recipe_paths},'normal_factory_routing':True,
  'actual_model_calls':0,'qualified':False,'final_cohort_confirmation_pending':True,
  'private_diagnostic_timeout_seconds':2400,'trajectory_timeout_seconds':600}
 write(output/'preflight_manifest.json',frozen)
 return frozen


class AuditedSourceFactory(FactoryPipeline):
 def load_seeds(self):
  seeds=super().load_seeds()
  for seed in seeds:
   proof=validate_seed(seed)
   require(seed.get('finance_evidence',{}).get('audited_source_binding')==proof,'Changed admitted source binding')
   # Factory's EUSES survey lookup overwrites seed survey; restore only this
   # freshly rechecked audited path, never an arbitrary supplied normalized path.
   seed['survey']={**seed.get('survey',{}),'normalized_path':proof['workbook']['path'],
                   'source_sha256':seed['sha256'],'status':'ok','error_count':0}
  return seeds
 def run_phase(self,context,phase):
  result=super().run_phase(context,phase)
  if context.data.get('baseline'):
   require(sha(context.data['baseline'])==context.data['source_id'],'Normalized baseline differs from the audited source bytes')
  return result


class CohortCodex(CodexCLI):
 def complete(self,prompt,role='',**kwargs):
  # DiagnoseNode supplies a common timeout explicitly. Keep a narrow, audited
  # private-role override while leaving all normal node/routing logic intact.
  if role=='reference_diagnostician':kwargs['timeout']=2400
  return super().complete(prompt,role=role,**kwargs)


def execute_prepared(output,*,resume=None,port=0):
 output=Path(output).resolve();frozen=read(output/'preflight_manifest.json')
 for group in ('source_artifacts_sha256','recipe_sha256'):
  for p,h in frozen[group].items():require(sha(p)==h,'Frozen cohort artifact changed: '+p)
 checked(frozen['prepared_seed_manifest']);checked(frozen['resolved_config'])
 root=Path(yaml.safe_load((output/'resolved_config.yaml').read_text())['project_root'])
 revision=subprocess.run(['git','rev-parse','HEAD'],cwd=root,capture_output=True,text=True,check=True).stdout.strip()
 session=None
 if resume:
  session=prepare_resume(Path(resume).resolve(),extra_manifest=output/'seed_manifest.json',current_code_revision=revision,
                         reason='Add the predeclared debugging-only audited sources to the fixed 10+10 quality cohort')
  config,audit,lease=session.config,session.audit,session.lease;run=Path(config['run_dir'])
 else:
  config=yaml.safe_load((output/'resolved_config.yaml').read_text());run=output
  require(not (run/'run.sqlite').exists(),'A producer already started this prepared run; use explicit resume')
  lease=ProducerLease(run).acquire()
  audit=AuditStore(run,{'id':run.name,'target_count':20,'financial_target':10,'debugging_target':10,
    'model':'gpt-6-sol','reasoning_effort':'high','difficulty_status':'pending','status':'preflight'})
 server=None;started=time.monotonic();status=1;previous_wall=audit.run.get('wall_seconds',0) or 0
 try:
  server=DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=port);url=server.start()
  audit.update_run(dashboard_url=url,producer_pid=os.getpid(),producer_active=True,code_revision=revision)
  dashboard=run/('dashboard_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json');write(dashboard,{'url':url})
  llm=CohortCodex(root,run,audit,config['agents']);llm._credentials()
  engine=LibreOfficeEngine(root,IMAGE,config['engine']['timeout_seconds']);runtime=engine.metadata()
  require(runtime['image_id']==IMAGE_ID,'The execution runtime differs from the audited source runtime')
  audit.emit('run.preflight',frozen_preparation=ref(output/'preflight_manifest.json'),runtime=runtime,
             private_diagnostic_timeout_seconds=2400,trajectory_timeout_seconds=600)
  print(json.dumps({'run_dir':str(run),'dashboard_url':url,'prepared_manifest':str(output/'preflight_manifest.json')}),flush=True)
  status=0 if AuditedSourceFactory(config,audit,llm,engine).run() else 2
  for p,h in frozen['recipe_sha256'].items():require(sha(p)==h,'Frozen cohort recipe changed during execution: '+p)
  return status
 finally:
  phase_wall=round(time.monotonic()-started,3)
  audit.update_run(producer_active=False,finished_at=utcnow(),last_phase_wall_seconds=phase_wall,
                   wall_seconds=round(previous_wall+phase_wall,3),exit_code=status)
  audit.export()
  if server:server.stop()
  if session:session.close()
  else:lease.release()


def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--source-manifest','--extra-manifest',dest='source_manifest',type=Path)
 parser.add_argument('--mode',choices=MODES,default='financial_modeling');parser.add_argument('--count',type=int,default=10)
 parser.add_argument('--output',type=Path);parser.add_argument('--prepared',type=Path)
 parser.add_argument('--run',action='store_true',help='Explicitly run models and the complete normal FactoryPipeline')
 parser.add_argument('--resume',type=Path);parser.add_argument('--port',type=int,default=0)
 args=parser.parse_args(argv)
 if args.prepared:
  if args.source_manifest or args.output:parser.error('--prepared cannot be combined with source preparation arguments')
  output=args.prepared
 else:
  if not args.source_manifest or not args.output:parser.error('Preparation requires --source-manifest and --output')
  frozen=prepare_cohort(args.source_manifest,args.output,mode=args.mode,count=args.count)
  output=args.output;print(json.dumps({'prepared':str(output),'source_count':frozen['source_count'],'models_started':False}),flush=True)
 if args.run:return execute_prepared(output,resume=args.resume,port=args.port)
 return 0

if __name__=='__main__':raise SystemExit(main())

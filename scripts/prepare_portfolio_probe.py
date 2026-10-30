#!/usr/bin/env python3
"""Build a development-only portfolio probe through normal construction controls."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid

import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.core.audit import AuditStore,utcnow
from sheets_factory.core.node import TaskContext
from sheets_factory.dashboard.server import DashboardServer
from sheets_factory.evaluation.harbor import export_harbor,inspect_export
from sheets_factory.nodes.construction import ConstructNode,InstructionNode,ControlsNode,compile_mask_ranges
from sheets_factory.workbook.derived_gold.portfolio_tasks import propose_portfolio_task
from sheets_factory.workbook.engine import LibreOfficeEngine


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2,default=str)+'\n')


class NoModelCalls:
    def __getattr__(self,name):raise RuntimeError('Probe preparation cannot invoke a model: '+name)


def prepare(source_manifest,output,mode='financial_modeling'):
    source_manifest,output=Path(source_manifest).resolve(),Path(output).resolve()
    source=json.loads(source_manifest.read_text())
    if source.get('status')!='financially_verified_planning_seed' or source.get('financial_audit_passed') is not True or len(source.get('selected',[]))!=1:
        raise ValueError('A genuinely LO-verified and independently audited portfolio source is required')
    entry=source['selected'][0];baseline=Path(entry['local_path']);identity=entry['sha256']
    if sha(baseline)!=identity:raise ValueError('Selected source SHA mismatch')
    for key in ('financial_audit','stability','public_scenario','group_ledger','independent_expectations'):
        ref=source[key]
        if sha(ref['path'])!=ref['sha256']:raise ValueError('Source evidence SHA mismatch: '+key)
    if json.loads(Path(source['financial_audit']['path']).read_text()).get('passed') is not True:
        raise ValueError('Source audit is not passing')
    output.mkdir(parents=True,exist_ok=False)
    audit=AuditStore(output,{'id':'portfolio-probe-'+uuid.uuid4().hex[:12],'kind':'prequality_development_probe',
        'source_kind':'prequality_development_probe','status':'preparing','llm_calls_permitted':False,
        'financial_target':int(mode=='financial_modeling'),'debugging_target':int(mode=='debugging')})
    server=DashboardServer(audit.snapshot,audit.events,port=0);url=server.start();audit.update_run(dashboard_url=url)
    print(json.dumps({'preparation_directory':str(output),'dashboard_url':url}),flush=True)
    task_id=('fm-' if mode=='financial_modeling' else 'dbg-')+identity[:12]
    tracked={source_manifest:sha(source_manifest),baseline:identity}
    try:
        snapshot=output/'source_snapshot';snapshot.mkdir()
        isolated=snapshot/'baseline.xlsx';shutil.copy2(baseline,isolated)
        config=yaml.safe_load((ROOT/'config/pipelines/derived_hard20.yaml').read_text())
        config.update(project_root=str(ROOT),run_dir=str(output))
        config['run'].update(name='portfolio-prequality-probe',source_kind='prequality_development_probe',seed_manifest=str(source_manifest))
        config['construction'].update(authoring_backend='portfolio_template',instruction_style='business_brief',
            max_edit_count={'financial_modeling':100000,'debugging':5000},root_impact_validation='separated_roots',
            analysis_limits={'max_dependency_closure_cells':500000,'max_profile_cells':500000,
                             'per_formula_reference_cells':5000,'max_mask_ranges':256})
        (output/'resolved_config.yaml').write_text(yaml.safe_dump(config,sort_keys=False))
        proposal=propose_portfolio_task(isolated,mode)
        write(output/'planning_proposal.json',proposal)
        plan=compile_mask_ranges(deepcopy(proposal),isolated,mode,config)
        write(output/'before_assertions.json',{'before_assertions_compiled_from_baseline':True,'edit_count':len(plan['edits']),
            'baseline_sha256':sha(isolated),'mask_range_count':len(proposal.get('mask_ranges',[])),
            'all_construct_controls_pending':True})
        audit.task(task_id,mode=mode,source_id=identity,source=baseline.name,status='preparing',
            difficulty_status='prequality_development_probe',source_kind='prequality_development_probe')
        engine=LibreOfficeEngine(ROOT,image=config['engine']['image'],timeout_seconds=config['engine']['timeout_seconds'])
        ctx=TaskContext(run_id=audit.run['id'],task_id=task_id,mode=mode,source=baseline,
            directory=output/'tasks'/task_id,config=config,audit=audit,llm=NoModelCalls(),engine=engine,
            data={'plan':plan,'baseline':isolated,'source_id':identity,'source_cache':snapshot,
                  'source_business_issues':entry['finance_evidence'].get('source_business_issues',[]),
                  'engine_report':{'engine':engine.metadata()}})
        for node in (ConstructNode(),InstructionNode(),ControlsNode()):
            node.run(ctx);audit.export()
        rewards={name:ctx.data['controls'][name]['reward'] for name in ('oracle','nop','equivalent','missed_root','extra_change')}
        if rewards!={'oracle':1,'nop':0,'equivalent':1,'missed_root':0,'extra_change':0}:
            raise ValueError('Actual local controls differ from the required rewards')
        metadata={'task_id':task_id,'mode':mode,'source_id':identity,'revision':ctx.revision,
                  'revision_hash':ctx.data['revision_hash'],'difficulty_status':'prequality_development_probe',
                  'source_kind':'prequality_development_probe','base_image':config['engine']['image']}
        export=output/'SpreadsheetEval'/task_id
        export_harbor(ctx.revision_dir,export,metadata=metadata,project_root=ROOT)
        binding=inspect_export(export)
        if any(binding.get(key)!=metadata[key] for key in ('task_id','revision','revision_hash')):
            raise ValueError('Actual Harbor export differs from the constructed revision')
        if any(sha(path)!=digest for path,digest in tracked.items()):raise ValueError('Original verified source changed')
        manifest={'schema_version':1,'kind':'prequality_development_probe','source_kind':'prequality_development_probe',
            'quality_status':'construction_and_five_local_controls_verified; independent_recovery_and_full_diagnosis_pending',
            'frozen_at':utcnow(),'selection_policy':'One verified portfolio source and all financial formula families fixed before model evaluation; development only.',
            'selected_task_ids':[task_id],'tasks':[{**metadata,'harbor_export_binding':binding,'task_directory':str(export),'local_controls':rewards}],
            'planning_origin':{'path':str(output/'planning_proposal.json'),'sha256':sha(output/'planning_proposal.json'),'authoring_backend':'portfolio_template'},
            'baseline_origin':{'path':str(baseline),'sha256':identity},'source_manifest':{'path':str(source_manifest),'sha256':sha(source_manifest)},
            'local_controls':rewards,'llm_calls':0,'model_evaluation_performed':False,'qualified':False,'task_count':0}
        write(output/'probe_manifest.json',manifest)
        audit.task(task_id,status='probe_prepared',node='probe_prepared',revision=ctx.revision,revision_hash=ctx.data['revision_hash'],
                   local_controls=rewards,harbor_export_binding=binding)
        audit.update_run(status='prepared',prepared_probe_count=1,qualified=0,probe_manifest=str(output/'probe_manifest.json'))
        audit.emit('probe.prepared',task_id=task_id,revision_hash=ctx.data['revision_hash'])
        return manifest
    except Exception as exc:
        write(output/'preparation_failure.json',{'kind':'development_probe_preparation_failed','timestamp':utcnow(),
            'source_manifest':str(source_manifest),'error_type':type(exc).__name__,'error':str(exc)})
        audit.task(task_id,status='failed',error=str(exc));audit.update_run(status='failed',error=str(exc),qualified=0)
        raise
    finally:
        audit.export();server.stop();audit.db.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--mode',choices=['financial_modeling','debugging'],default='financial_modeling')
    args=parser.parse_args(argv)
    result=prepare(args.source_manifest,args.output,args.mode)
    print(json.dumps({'status':'prepared','probe_manifest':str(args.output.resolve()/'probe_manifest.json'),
                      'selected_task_ids':result['selected_task_ids'],'llm_calls':0}),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())

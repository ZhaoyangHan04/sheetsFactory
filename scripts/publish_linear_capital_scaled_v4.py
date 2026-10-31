#!/usr/bin/env python3
"""Freeze the whole normal-qualified N360 set and its once-only v4 confirmation.

Preparation and validation are service-free. Actual confirmation, payload
publication and finalization are separate explicit commands. Earlier development
scores and reservations are retained and never migrated into this phase.
"""
from __future__ import annotations
import argparse
import ast
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
from types import ModuleType

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'));sys.path.insert(0,str(ROOT/'scripts'))
from sheets_factory.evaluation import linear_capital_scaled_publication_v4 as publication
from sheets_factory.evaluation import linear_capital_scaled_frontier_v4 as runner
from sheets_factory.evaluation import clock_resource_publication as template
from sheets_factory.reporting import read_run

require, reference, checked, read = publication.require, publication.reference, publication.checked, publication.read
IDENTITY_KEYS=('mode','input_definitions','input_values','goal_values','instruction_sha256')
HISTORY_ROOTS=(ROOT/'outputs/difficulty',ROOT/'outputs/research')


def canonical(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as stream:json.dump(value,stream,indent=2,ensure_ascii=False,allow_nan=False);stream.write('\n')
    return reference(path)


def history_helper():
    template._frozen_ast(ROOT/'scripts/prepare_linear_capital_development.py','5bafc37a217545fe96d79a97c834c1439b6b1b859f38efeaa95223e941d51ba4')
    return publication.support(ROOT,'prepare_linear_capital_development.py')


def material_identity(directory,mode):
    return publication.material_identity(directory,mode)


def _historical_material(selection,task,h):
    source=selection.get('source_manifest')
    if isinstance(source,dict):
        h._historical_reference(source);value=read(source['path'])
        rows=value.get('tasks',[])
        matches=[r.get('material_task_version') for r in rows if r.get('task_id')==task.get('task_id')]
        if len(matches)==1 and matches[0] is not None:
            identity=matches[0]
            require(identity.get('sha256')==canonical({k:v for k,v in identity.items() if k!='sha256'}),'Malformed historical logical material identity')
            return identity
        previous=h._historical_identity(selection,task)
        if previous is not None:return previous
    return None


def selection_history(rows,roots):
    """Preserve every selection; reject same-phase material, even if renamed."""
    h=history_helper();records=[];seen=set()
    for root in roots:
        root=Path(root).absolute();require(root==root.resolve(),'History roots must be real paths')
        paths=[root] if root.is_file() else sorted(root.rglob('selection_manifest.json')) if root.exists() else []
        for path in paths:
            if str(path) in seen:continue
            seen.add(str(path));selection=read(path);model,tasks=h._history_tasks(selection)
            for task in tasks if model else ():
                # Source identities must remain available even for development
                # records. Their outcomes do not select confirmation membership.
                previous=_historical_material(selection,task,h)
                if selection.get('phase')!='confirmation':continue
                for row in rows:
                    require(not (task.get('revision_hash')==row['revision_hash'] or
                        (task.get('task_id')==row['task_id'] and task.get('revision')==row['revision'])),
                        'This revision already belongs to a confirmation; no resampling')
                    if task.get('mode')!=row['mode']:continue
                    identity=row['material_task_version']
                    if previous is not None and all(k in previous for k in IDENTITY_KEYS):
                        require(any(previous[k]!=identity[k] for k in IDENTITY_KEYS),'This logical material already has a confirmation, regardless of packaging or name')
                    else:
                        folder=Path(task.get('task_directory',''))
                        instruction=folder/'instruction.md'
                        require(instruction.is_file(),'A historical confirmation payload is missing')
                        if reference(instruction)['sha256']==identity['instruction_sha256']:
                            candidate=material_identity(folder,task['mode'])
                            require(candidate!=identity,'This unchanged material already has a confirmation')
            records.append(reference(path))
    return records


def _complete_declaration(sources):
    require(isinstance(sources,list) and sources,'Declare all normal directories and all their tasks')
    runs={row.get('source_run') for row in sources}
    require(all(isinstance(p,str) and Path(p).is_absolute() for p in runs),'Every normal directory must be explicit and absolute')
    declared={(r.get('source_run'),r.get('task_id')) for r in sources}
    require(len(declared)==len(sources),'Duplicate declared task')
    complete=set()
    for run in runs:
        tasks=read_run(Path(run))['tasks']
        require(tasks and all(t.get('status')=='qualified' for t in tasks),'Every task of every declared normal directory must be qualified; do not filter failures')
        complete.update((run,t['id']) for t in tasks)
    require(complete==declared,'Include every task from every declared normal directory before outcomes')
    return sorted(runs)


def _augment_cohort(cohort,sources,root,history_roots=()):
    runs=_complete_declaration(sources)
    require(len(cohort['tasks'])==20 and all(sum(r['mode']==m for r in cohort['tasks'])==10
        for m in ('financial_modeling','debugging')),'Freeze the full twenty: ten FM and ten DBG')
    for row in cohort['tasks']:
        row['material_task_version']=material_identity(Path(row['source_run'])/'SpreadsheetEval'/row['task_id'],row['mode'])
    identities=[r['material_task_version']['sha256'] for r in cohort['tasks']]
    require(len(set(identities))==20,'The cohort repeats a logical material')
    cohort.update(version=4,tool_time_policy_version=4,tool_time_policy=dict(runner.POLICY_V4),
        native_transport_profile=runner.transport_profile(),declared_normal_directories=runs,
        confirmation_cohort_identity=canonical(sorted(identities)),execution_concurrency=4,
        history_roots=list(dict.fromkeys(str(Path(p).absolute()) for p in [root/'outputs/difficulty',*history_roots])),
        effective_infrastructure_retries=0,confirmation_phase_once_per_material=True,
        reference_evidence_policy='reference_review',public_solver_required=False,final20_qualified=False)
    return cohort


def _freeze_namespace():
    tree=template.cli_ast();tree.body=[n for n in tree.body if not (isinstance(n,ast.If) and ast.unparse(n.test)=="__name__ == '__main__'")]
    counts={'backend':0,'publisher':0,'reference':0,'augment':0,'history':0}
    class Adapt(ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            if node.module=='sheets_factory.evaluation.clock_resource_publication':
                node.module='sheets_factory.evaluation.linear_capital_scaled_publication_v4'
                if any(n.name=='ResourcePublicationBackend' for n in node.names):counts['backend']+=1
                else:counts['publisher']+=1
            return node
        def visit_Call(self,node):
            if ast.unparse(node.func)=='backend.release._validate_task':
                node.keywords.append(ast.keyword(arg='reference_policy',value=ast.Constant('reference_review')));counts['reference']+=1
            if isinstance(node.func,ast.Name) and node.func.id=='_confirmation_history':node.func.id='_all_selection_history';counts['history']+=1
            return self.generic_visit(node)
        def visit_Expr(self,node):
            if isinstance(node.value,ast.Call) and ast.unparse(node.value.func)=='backend.validate_cohort_shape':
                counts['augment']+=1
                return [ast.parse('_augment_cohort(cohort,sources,root,history_roots)').body[0],self.generic_visit(node)]
            return self.generic_visit(node)
    tree=Adapt().visit(tree)
    require(counts=={'backend':1,'publisher':1,'reference':1,'augment':1,'history':2},'The exact generic cohort-freeze call sites changed: '+str(counts))
    module=ModuleType('_N360_v4_generic_cohort');module.__file__=str(ROOT/'scripts/publish_resource_dataset.py')
    module.__dict__.update(_augment_cohort=_augment_cohort,_all_selection_history=selection_history)
    exec(compile(ast.fix_missing_locations(tree),module.__file__,'exec'),module.__dict__)
    return module


def freeze_cohort(task_sources,output,*,project_root=ROOT,history_roots=()):
    sources=read(task_sources) if isinstance(task_sources,(str,Path)) else task_sources
    _complete_declaration(sources)
    return _freeze_namespace().freeze_cohort(task_sources,output,project_root=project_root,
        history_roots=[*HISTORY_ROOTS,*history_roots])


def validate_cohort(path):
    backend=publication.ResourcePublicationBackend(path);cohort=backend.cohort
    require(cohort['tool_time_policy']==runner.POLICY_V4 and cohort['native_transport_profile']==runner.transport_profile()
        and cohort['reference_evidence_policy']=='reference_review' and cohort['effective_infrastructure_retries']==0
        and cohort['execution_concurrency']==4 and cohort['final20_qualified'] is False,'The complete prospective confirmation contract changed')
    sources=[{k:r[k] for k in ('source_run','task_id','family')} for r in cohort['tasks']]
    require(_complete_declaration(sources)==cohort['declared_normal_directories'],'The complete declared normal set changed')
    tracked={};private_scopes={}
    for row in cohort['tasks']:
        run=Path(row['source_run']);task=next(t for t in read_run(run)['tasks'] if t['id']==row['task_id'])
        state=backend._run(run,row['family'],tracked);config=state['config']
        private=Path(config['diagnosis']['execution']['private_evidence_directory'])
        if not private.is_absolute():private=backend.root/private
        backend.release._validate_task(run,task,tracked,backend.publisher._credential_values(backend.root),
            project_root=backend.root,registry_path=config.get('native_risks',{}).get('registry_path'),reference_policy='reference_review',
            private_evidence_root=private,private_evidence_tracked=private_scopes.setdefault(str(private),{}),backend=backend)
        require(backend.inspect_export(row['task_directory'])==row['harbor_export_binding'],'The frozen complete seventeen-file copy changed')
        require(material_identity(row['task_directory'],row['mode'])==row['material_task_version'],'The logical confirmation material changed')
    require(cohort['confirmation_cohort_identity']==canonical(sorted(r['material_task_version']['sha256'] for r in cohort['tasks'])),
        'The common cohort identity changed')
    require(cohort.get('history_roots') and cohort['history_roots'][0]==str(backend.root/'outputs/difficulty'),
        'The permanent shared reservation/history root changed')
    current=selection_history(cohort['tasks'],cohort['history_roots'])
    require(all(r in current for r in cohort['prior_selection_inventory']),'A frozen history artifact is missing or changed')
    backend.recheck_tracked(tracked);backend.recheck_payloads()
    return backend


def reserve_confirmation(cohort_path,evaluation_output,*,validator=validate_cohort,history_roots=None):
    backend=validator(cohort_path);cohort=backend.cohort
    roots=cohort.get('history_roots',HISTORY_ROOTS) if history_roots is None else history_roots
    require(roots,'Complete model-history roots are required');root=Path(roots[0]).absolute()
    directory=root/'.linear_scaled_confirmation_reservations';require(directory==directory.resolve(),'A real reservation directory is required')
    directory.mkdir(parents=True,exist_ok=True);descriptor=os.open(directory/'launch.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'a') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:raise ValueError('A confirmation reservation is already in progress') from error
        require(validator(cohort_path).cohort==cohort,'The complete frozen cohort changed before reservation')
        current=selection_history(cohort['tasks'],roots)
        require(all(r in current for r in cohort['prior_selection_inventory']),'A frozen selection disappeared or changed')
        destination=Path(evaluation_output).absolute();require(destination==destination.resolve() and not destination.exists(),'Use one fresh evaluation destination')
        common=directory/('cohort_'+cohort['confirmation_cohort_identity']+'.json')
        paths=[directory/('material_'+r['material_task_version']['sha256']+'.json') for r in cohort['tasks']]
        require(not any(p.exists() or p.is_symlink() for p in [common,*paths]),'A cohort/material confirmation is already reserved; no repeat or rename')
        h=history_helper();partition=h.history_partition(current)
        value={'kind':'linear_capital_scaled_v4_confirmation_reservation','version':1,'phase':'confirmation',
            'cohort':reference(cohort_path),'cohort_identity':cohort['confirmation_cohort_identity'],
            'evaluation_output':str(destination),'started_at':datetime.now(timezone.utc).isoformat(),
            'selection_history_inventory':current,**partition,'effective_infrastructure_retries':0,'final20_qualified':False}
        # Exclusive creates deliberately survive any later partial failure.
        receipt=write(common,value)
        for path,row in zip(paths,cohort['tasks']):write(path,{**value,'common_reservation':receipt,'material_task_version':row['material_task_version']})
        return receipt,value


def run_confirmation(cohort_path,evaluation_output,*,port=0):
    reservation,value=reserve_confirmation(cohort_path,evaluation_output)
    from sheets_factory.evaluation.resource_observer import ResourceObserver
    import yaml
    config_path=ROOT/'config/llm.yaml';config=yaml.safe_load(config_path.read_text()) if config_path.is_file() else {}
    config.update(model=runner.MODEL,reasoning_effort=runner.EFFORT,
        roles={'trace_agent':{'model':runner.MODEL,'reasoning_effort':runner.EFFORT}})
    with ResourceObserver(evaluation_output) as observer:
        result=runner.run_evaluation(cohort_path,evaluation_output,phase='confirmation',concurrency=4,
            project_root=ROOT,backend_config=config,port=port,
            prior_selections=[r['path'] for r in value['model_selections']])
    write(Path(evaluation_output)/'confirmation_wrapper_terminal.json',{'reservation':reservation,
        'selection':reference(Path(evaluation_output)/'selection_manifest.json'),
        'evaluation':reference(Path(evaluation_output)/'evaluation_manifest.json'),
        'resource_observation':observer.receipt,'final20_qualified':False})
    return result


def publish(cohort,selection,evaluation,*,publish_files=False,project_root=ROOT):
    backend=publication.ResourcePublicationBackend(cohort,project_root=project_root)
    return backend.publisher.publish_dataset(run_dir=backend.cohort['tasks'][0]['source_run'],selection_manifest=selection,
        evaluation_manifest=evaluation,project_root=project_root,dry_run=not publish_files,backend=backend)


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
    freeze=sub.add_parser('freeze-cohort');freeze.add_argument('--task-sources',type=Path,required=True);freeze.add_argument('--output',type=Path,required=True)
    valid=sub.add_parser('validate-cohort');valid.add_argument('--cohort',type=Path,required=True)
    run=sub.add_parser('run-confirmation');run.add_argument('--cohort',type=Path,required=True);run.add_argument('--output',type=Path,required=True);run.add_argument('--port',type=int,default=0)
    pub=sub.add_parser('publish');pub.add_argument('--cohort',type=Path,required=True);pub.add_argument('--selection',type=Path,required=True);pub.add_argument('--evaluation',type=Path,required=True);pub.add_argument('--publish',action='store_true')
    final=sub.add_parser('finalize');final.add_argument('--cohort',type=Path,required=True);final.add_argument('--selection',type=Path,required=True);final.add_argument('--evaluation',type=Path,required=True)
    final.add_argument('--oracle-command-receipt',type=Path,required=True);final.add_argument('--nop-command-receipt',type=Path,required=True)
    final.add_argument('--output',type=Path,required=True);final.add_argument('--write-receipt',action='store_true')
    args=parser.parse_args(argv)
    if args.command=='freeze-cohort':result=freeze_cohort(args.task_sources,args.output)
    elif args.command=='validate-cohort':result={'validated':str(args.cohort),'task_count':len(validate_cohort(args.cohort).cohort['tasks']),'final20_qualified':False}
    elif args.command=='run-confirmation':return run_confirmation(args.cohort,args.output,port=args.port)
    elif args.command=='publish':result=publish(args.cohort,args.selection,args.evaluation,publish_files=args.publish)
    else:
        from sheets_factory.evaluation.linear_capital_scaled_finalization_v4 import finalize
        result=finalize(args.cohort,args.selection,args.evaluation,
            {'oracle':reference(args.oracle_command_receipt),'nop':reference(args.nop_command_receipt)},
            args.output,write_receipt=args.write_receipt)
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0


if __name__=='__main__':raise SystemExit(main())

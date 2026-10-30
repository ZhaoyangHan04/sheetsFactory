#!/usr/bin/env python3
"""Prospective joint-control phase over an immutable V2 or V3 preparation."""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import yaml

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sheets_factory.task_adapters.public_input_priority import checked,read,ref,require,sha,write

PHASE_FIELD='prospective_joint_controls_phase'
CONTROL_NODE='sheets_factory.nodes.joint_controls:JointObservableControlsNode'
BACKENDS={
    'prepared_full_graph_joint_quality':('v2','run_full_graph_factory_compat.py','FullGraphFactoryCompat'),
    'prepared_separate_semantic_graph_v3_normal_quality':('v3','run_semantic_graph_quality.py','SemanticGraphFactory'),
}


def controls_contract():
    from sheets_factory.nodes import joint_controls
    return joint_controls


def backend_for(kind):
    require(kind in BACKENDS,'Only the validated V2-compatible or separate V3 base preparation is supported')
    name,filename,factory_name=BACKENDS[kind]
    location=ROOT/'scripts'/filename
    spec=importlib.util.spec_from_file_location('_joint_controls_frozen_'+name,location)
    require(spec is not None and spec.loader is not None,'The existing base entry cannot be loaded')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return name,module,getattr(module,factory_name)


def _expected_config(base,output,host,registry,contract):
    result=deepcopy(base)
    result['run_dir']=str(output);result['host_runtime']=deepcopy(host)
    result['run']['seed_manifest']=str(output/'seed_manifest.json')
    result['pipeline']={**result.get('pipeline',{}),'node_registry':str(registry)}
    result[contract.SETTING]=contract.setting()
    return result


def _host_settings(base,output,cohort):
    if 'host_runtime'in base:
        settings=deepcopy(base['host_runtime']);settings['temporary_directory']=str(output/'temporary')
        cohort.validate_host_runtime(output,settings)
        return settings
    return cohort.host_runtime_settings(output)


def prepare(output,base_prepared):
    output=Path(output).resolve();base_prepared=Path(base_prepared).resolve()
    require(not output.exists(),'Prospective controls require a fresh directory')
    old=read(ref(base_prepared/'preflight_manifest.json'))
    require(PHASE_FIELD not in old,'A prospective controls phase cannot silently wrap another controls phase')
    name,backend,_=backend_for(old.get('kind'))
    old=backend.validate_prepared(base_prepared)
    base_config=yaml.safe_load(checked(old['resolved_config']).read_text())
    control=controls_contract();new_setting=control.setting();control.validate_setting(new_setting)
    require(control.SETTING not in base_config,'The base already has an observable-controls opt-in')
    registry_path=Path(base_config['pipeline']['node_registry'])
    if not registry_path.is_absolute():registry_path=Path(base_config['project_root'])/registry_path
    base_registry=yaml.safe_load(registry_path.read_text())
    require(isinstance(base_registry,dict)and isinstance(base_registry.get('nodes'),dict)
            and base_registry['nodes'].get('precheck')=='sheets_factory.nodes.construction:ControlsNode',
            'The base must retain the ordinary control node before this explicit new phase')
    new_registry=deepcopy(base_registry);new_registry['nodes']['precheck']=CONTROL_NODE
    output.mkdir(parents=True);cohort=backend.cohort;host=_host_settings(base_config,output,cohort)
    with cohort.host_temporary_environment(output,host)as setup:
        shutil.copy2(checked(old['prepared_seed_manifest']),output/'seed_manifest.json')
        shutil.copy2(checked(old['resolved_config']),output/'base_resolved_config_snapshot.yaml')
        registry=output/'joint_controls_node_registry.yaml'
        registry.write_text(yaml.safe_dump(new_registry,sort_keys=False))
        config=_expected_config(base_config,output,host,registry,control)
        (output/'resolved_config.yaml').write_text(yaml.safe_dump(config,sort_keys=False))
        addendum={'kind':'prospective_observable_joint_controls_phase','version':1,
            'created_at':datetime.now(timezone.utc).isoformat(),'backend':name,'base_kind':old['kind'],
            'base_preparation':ref(base_prepared/'preflight_manifest.json'),
            'base_resolved_config':old['resolved_config'],'base_seed_manifest':old['prepared_seed_manifest'],
            'base_node_registry':ref(registry_path),'new_node_registry':ref(registry),
            'new_resolved_config':ref(output/'resolved_config.yaml'),
            'control_setting_name':control.SETTING,'control_setting':new_setting,
            'old_precheck':base_registry['nodes']['precheck'],'new_precheck':CONTROL_NODE,
            'source_goal_provider_edits_models_and_all_budgets_unchanged':True,
            'all_other_normal_nodes_unchanged':True,'old_base_or_result_files_modified':False,
            'quality_recovery_difficulty_certified':False,'actual_LO_calls':0,'actual_model_calls':0}
        write(output/'prospective_joint_controls_phase.json',addendum)
        frozen=deepcopy(old)
        frozen.update(prepared_at=datetime.now(timezone.utc).isoformat(),
            prepared_seed_manifest=ref(output/'seed_manifest.json'),resolved_config=ref(output/'resolved_config.yaml'),
            host_runtime=host,preparation_host_runtime=setup)
        frozen[PHASE_FIELD]=ref(output/'prospective_joint_controls_phase.json')
        # Preserve every old source and recipe binding; add new code and the
        # explicit registry/config phase instead of editing historical receipts.
        for record in (ref(Path(__file__).resolve()),new_setting['implementation'],
                       ref(Path(backend.__file__).resolve())):
            checked(record);frozen['recipe_sha256'][record['path']]=record['sha256']
        for record in (addendum['base_preparation'],old['resolved_config'],old['prepared_seed_manifest'],
                       addendum['base_node_registry'],ref(registry),ref(output/'base_resolved_config_snapshot.yaml'),
                       frozen[PHASE_FIELD]):
            checked(record);frozen['source_artifacts_sha256'][record['path']]=record['sha256']
        frozen.update(actual_LO_calls=0,actual_model_calls=0,qualified=False)
        write(output/'preflight_manifest.json',frozen)
        backend.validate_prepared(base_prepared)
        return ref(output/'preflight_manifest.json')


def validate_prepared(output):
    output=Path(output).resolve();header=read(ref(output/'preflight_manifest.json'))
    require(PHASE_FIELD in header,'The explicit prospective controls phase is missing')
    name,backend,factory=backend_for(header.get('kind'))
    frozen=backend.validate_prepared(output)
    phase=read(frozen[PHASE_FIELD]);control=controls_contract()
    require(phase.get('kind')=='prospective_observable_joint_controls_phase'and phase.get('version')==1
            and phase.get('backend')==name and phase.get('base_kind')==frozen['kind'],
            'Prospective controls phase identity differs')
    base_prepared=checked(phase['base_preparation']).parent
    old=backend.validate_prepared(base_prepared)
    require(PHASE_FIELD not in old,'An unexpected nested controls phase was admitted')
    require(phase['base_resolved_config']==old['resolved_config']
            and phase['base_seed_manifest']==old['prepared_seed_manifest']
            and phase.get('new_resolved_config')==frozen['resolved_config'],
            'The prospective phase no longer binds the original immutable base')
    base_config=yaml.safe_load(checked(old['resolved_config']).read_text())
    config=yaml.safe_load(checked(frozen['resolved_config']).read_text())
    old_registry=Path(base_config['pipeline']['node_registry'])
    if not old_registry.is_absolute():old_registry=Path(base_config['project_root'])/old_registry
    require(phase['base_node_registry']==ref(old_registry),
            'The phase cannot substitute a different original node registry')
    control.validate_setting(config.get(control.SETTING))
    require(phase.get('control_setting_name')==control.SETTING
            and phase.get('control_setting')==config[control.SETTING]==control.setting(),
            'The control policy or frozen implementation changed')
    host=_host_settings(base_config,output,backend.cohort)
    registry=checked(phase['new_node_registry'])
    expected=_expected_config(base_config,output,host,registry,control)
    require(config==expected and frozen.get('host_runtime')==host,
            'The prospective phase changed source/provider settings, models, budgets or other configuration')
    base_registry=yaml.safe_load(checked(phase['base_node_registry']).read_text())
    actual_registry=yaml.safe_load(registry.read_text());expected_registry=deepcopy(base_registry)
    require(base_registry.get('nodes',{}).get('precheck')=='sheets_factory.nodes.construction:ControlsNode',
            'The original base control node changed')
    expected_registry['nodes']['precheck']=CONTROL_NODE
    require(actual_registry==expected_registry and phase.get('new_precheck')==CONTROL_NODE,
            'A prospective controls phase may replace only the precheck implementation')
    require(sha(checked(frozen['prepared_seed_manifest']))==sha(checked(old['prepared_seed_manifest'])),
            'Source, financial goal, mutation provider or seed selection changed')
    require(all(frozen['recipe_sha256'].get(p)==h for p,h in old['recipe_sha256'].items())
            and all(frozen['source_artifacts_sha256'].get(p)==h for p,h in old['source_artifacts_sha256'].items()),
            'The new phase dropped or rewrote an immutable old recipe/source binding')
    require(phase.get('source_goal_provider_edits_models_and_all_budgets_unchanged')is True
            and phase.get('all_other_normal_nodes_unchanged')is True
            and phase.get('old_base_or_result_files_modified')is False
            and phase.get('quality_recovery_difficulty_certified')is False
            and phase.get('actual_LO_calls')==phase.get('actual_model_calls')==0,
            'Prospective preparation cannot claim or rewrite quality, runtime or historical results')
    return frozen


def startup_smoke(output,smoke_directory,*,port=0):
    """Actual constructor and load_seeds only; no node, model or LO execution."""
    output=Path(output).resolve();directory=Path(smoke_directory).resolve()
    require(not directory.exists(),'Startup validation needs a fresh directory')
    frozen=validate_prepared(output);_,backend,factory_class=backend_for(frozen['kind'])
    config=yaml.safe_load(checked(frozen['resolved_config']).read_text())
    directory.mkdir(parents=True);config=deepcopy(config);config['run_dir']=str(directory)
    host=_host_settings(config,directory,backend.cohort);config['host_runtime']=host
    return _startup_or_execute(directory,config,frozen,backend,factory_class,host,port=port,smoke=True)


def _startup_or_execute(run,config,frozen,backend,factory_class,host,*,port,smoke):
    cohort=backend.cohort;adapted=backend.adapted;lease=None;audit=None;server=None
    started=time.monotonic();status=1
    with cohort.host_temporary_environment(run,host)as setup:
        try:
            require(not(run/'run.sqlite').exists(),'This prospective execution directory already started')
            lease=cohort.ProducerLease(run).acquire()
            targets=config['run']['targets']
            audit=cohort.AuditStore(run,{'id':run.name,'target_count':sum(targets.values()),
                'financial_target':targets.get('financial_modeling',0),'debugging_target':targets.get('debugging',0),
                'development_only':frozen.get('development_only',False),'difficulty_status':'pending',
                'status':'startup_smoke'if smoke else'preflight','model':config['agents']['model'],
                'reasoning_effort':config['agents']['reasoning_effort'],'producer_kind':'prospective_joint_controls'})
            server=cohort.DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=port);url=server.start()
            revision=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,text=True,capture_output=True,check=True).stdout.strip()
            audit.update_run(producer_active=True,producer_pid=os.getpid(),dashboard_url=url,code_revision=revision,
                host_runtime_receipt=setup,host_temporary_directory=setup['temporary_directory'])
            llm=cohort.CohortCodex(ROOT,run,audit,config['agents'])
            engine=cohort.LibreOfficeEngine(ROOT,cohort.IMAGE,config['engine']['timeout_seconds'])
            runtime=engine.metadata();require(runtime['image_id']==cohort.IMAGE_ID,'The pinned control runtime differs')
            print(json.dumps({'run_dir':str(run),'dashboard_url':url,'startup_only':smoke}),flush=True)
            pipeline=factory_class(config,audit,llm,engine)
            if smoke:
                seeds=pipeline.load_seeds();require(audit.snapshot()['nodes']==[],'A startup smoke executed a pipeline node')
                receipt={'kind':'prospective_joint_controls_actual_startup_smoke','passed':True,
                    'prepared_phase':frozen[PHASE_FIELD],'actual_Factory_class':factory_class.__module__+'.'+factory_class.__name__,
                    'actual_seed_count':len(seeds),'registered_nodes':pipeline.node_registry,
                    'actual_node_executions':0,'actual_LO_calls':0,'actual_model_calls':0,
                    'elapsed_seconds':time.monotonic()-started,'qualified':False,'task_count':0}
                write(run/'startup_smoke_receipt.json',receipt);status=0;return ref(run/'startup_smoke_receipt.json')
            llm._credentials()
            status=0 if pipeline.run()else 2
            for p,h in frozen['recipe_sha256'].items():require(sha(p)==h,'Prospective controls recipe changed during execution')
            return status
        finally:
            if audit is not None:
                adapted.finalize_execution(audit,server,None,lease,phase_wall=round(time.monotonic()-started,3),previous_wall=0,status=status)
            elif lease:lease.release()


def execute_prepared(output,*,port=0):
    output=Path(output).resolve();frozen=validate_prepared(output);_,backend,factory=backend_for(frozen['kind'])
    config=yaml.safe_load(checked(frozen['resolved_config']).read_text())
    return _startup_or_execute(output,config,frozen,backend,factory,frozen['host_runtime'],port=port,smoke=False)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--base-prepared',type=Path)
    p.add_argument('--output',type=Path);p.add_argument('--prepared',type=Path)
    p.add_argument('--startup-smoke',type=Path);p.add_argument('--run',action='store_true');p.add_argument('--port',type=int,default=0)
    a=p.parse_args(argv)
    if a.run and a.startup_smoke:p.error('Startup-only validation cannot start normal quality')
    if a.prepared:
        if a.base_prepared or a.output:p.error('--prepared cannot be combined with new phase inputs')
        output=a.prepared
    else:
        if not a.base_prepared or not a.output:p.error('A new phase requires --base-prepared and --output')
        output=a.output;print(json.dumps(prepare(output,a.base_prepared)),flush=True)
    if a.startup_smoke:print(json.dumps(startup_smoke(output,a.startup_smoke,port=a.port)),flush=True)
    if a.run:raise SystemExit(execute_prepared(output,port=a.port))

if __name__=='__main__':main()

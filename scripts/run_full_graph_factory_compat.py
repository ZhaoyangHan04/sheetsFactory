#!/usr/bin/env python3
"""New complete-DBG compatibility phase; execute only with explicit --run."""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.pipelines.full_graph_factory_compat import FullGraphFactoryCompat, SETTING, setting, validate_setting
from sheets_factory.task_adapters.public_workbook_scope import reference, write_new

def load_script(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result

base = load_script('_compat_frozen_full_graph_entry', ROOT / 'scripts/run_full_graph_quality.py')
probe = load_script('_compat_scoped_preparation', ROOT / 'scripts/prepare_full_graph_development_probe.py')
cohort, adapted = base.cohort, base.adapted
require, ref, sha, write = base.require, base.ref, base.sha, base.write
JOINT_SETTING, PROTECTED_BUDGETS = base.JOINT_SETTING, base.PROTECTED_BUDGETS
JOINT_PROMPT = base.JOINT_PROMPT


def prepare(output, base_prepared):
    output = probe.fresh_output(output)
    staged = output / 'scope_preparation'
    probe.prepare_scoped_factory(base_prepared, staged)
    old = probe.read(staged / 'preflight_manifest.json')
    config = yaml.safe_load((staged / 'resolved_config.yaml').read_text())
    shutil.copy2(staged / 'resolved_config.yaml', output / 'resolved_config_before_compatibility.yaml')
    shutil.copy2(staged / 'seed_manifest.json', output / 'seed_manifest.json')
    host = cohort.host_runtime_settings(output)
    config.update(run_dir=str(output), host_runtime=host)
    config['run']['seed_manifest'] = str(output / 'seed_manifest.json')
    config[SETTING] = setting()
    with cohort.host_temporary_environment(output, host) as host_receipt:
        (output / 'resolved_config.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        phase = write_new(output / 'compatibility_phase_addendum.json', {
            'kind': 'prospective_complete_DBG_empty_range_compatibility_phase',
            'created_at': datetime.now(timezone.utc).isoformat(),
            'base_preparation': reference(Path(base_prepared) / 'preflight_manifest.json'),
            'staged_scope_preparation': reference(staged / 'preflight_manifest.json'),
            'config_before': reference(output / 'resolved_config_before_compatibility.yaml'),
            'config_after': reference(output / 'resolved_config.yaml'),
            'config_before_hash_is_historical': True, 'compatibility': setting(),
            'factory_class': 'sheets_factory.pipelines.full_graph_factory_compat:FullGraphFactoryCompat',
            'old_runs_sources_goals_edits_public_scope_and_scores_modified': False,
            'normal_all_nodes_five_controls_recovery_all12QA_and_actual_Harbor_required': True,
            'actual_models': 0, 'actual_LO_calls': 0, 'qualified': False})
        frozen = deepcopy(old)
        frozen.update(prepared_at=datetime.now(timezone.utc).isoformat(),
            prepared_seed_manifest=ref(output / 'seed_manifest.json'),
            resolved_config=ref(output / 'resolved_config.yaml'),
            host_runtime=host, preparation_host_runtime=host_receipt,
            compatibility_phase_addendum=phase)
        for path in (Path(__file__).resolve(), Path(setting()['implementation']['path'])):
            frozen['recipe_sha256'][str(path)] = sha(path)
        for path in (staged / 'preflight_manifest.json', staged / 'resolved_config.yaml',
                     output / 'resolved_config_before_compatibility.yaml', output / 'compatibility_phase_addendum.json'):
            frozen['source_artifacts_sha256'][str(path)] = sha(path)
        write_new(output / 'preflight_manifest.json', frozen)
        return reference(output / 'preflight_manifest.json')


def validate_prepared(output):
    frozen = base.validate_prepared(output)
    require(frozen.get('count') == 1 and frozen.get('development_only') is True,
            'Compatibility entry currently supports the first development candidate only')
    config = yaml.safe_load(Path(frozen['resolved_config']['path']).read_text())
    validate_setting(config)
    require('compatibility_phase_addendum' in frozen, 'Missing explicit new compatibility phase')
    return frozen


def execute_prepared(output,*,resume=None,port=0):
    output=Path(output).resolve();frozen=validate_prepared(output)
    require((frozen['count']==10)==bool(resume),'One-candidate development runs are separate; DBG10 requires terminal main continuation')
    run=Path(resume).resolve() if resume else output
    continuation=adapted.validate_continuation(run) if resume else None
    settings,legacy=cohort.prepared_host_runtime(run)
    with cohort.host_temporary_environment(run,settings,legacy_preparation=legacy) as host:
        prepared=yaml.safe_load((output/'resolved_config.yaml').read_text())
        revision=subprocess.run(['git','rev-parse','HEAD'],cwd=ROOT,capture_output=True,text=True,check=True).stdout.strip()
        session=None
        if continuation:
            old=yaml.safe_load((run/'resolved_config.yaml').read_text())
            patch={'pipeline':prepared['pipeline'],JOINT_SETTING:prepared[JOINT_SETTING],
                'construction':{'max_edit_count':{'debugging':100000}},
                'prompt_overrides':{'diagnosis.md':JOINT_PROMPT.name},
                'run':{'max_parallel_sources':frozen['parallelism']},'agents':{'max_parallel_calls':frozen['parallelism']}}
            session=cohort.prepare_resume(run,extra_manifest=output/'seed_manifest.json',config_patch=patch,
                current_code_revision=revision,reason='Append full-graph joint DBG10; preserve original 10+10 and every task budget')
            config,audit,lease=session.config,session.audit,session.lease
        else:
            config=prepared;require(not (run/'run.sqlite').exists(),'Prepared development run already started')
            lease=cohort.ProducerLease(run).acquire()
            try:
                audit=cohort.AuditStore(run,{'id':run.name,'target_count':1,'financial_target':0,'debugging_target':1,
                    'model':config['agents']['model'],'reasoning_effort':config['agents']['reasoning_effort'],
                    'development_only':True,'difficulty_status':'pending','status':'preflight'})
            except BaseException:
                lease.release();raise
        server,status,started=None,1,time.monotonic();previous=audit.run.get('wall_seconds',0) or 0
        try:
            if continuation:
                require(config['run']['targets']=={'financial_modeling':10,'debugging':10}
                    and all(config['run'].get(k)==old['run'].get(k) for k in PROTECTED_BUDGETS), 'Continuation changed targets or repair budgets')
                cid=config['run']['continuation_id'];private=run/'private/resume'
                addendum={'kind':'immutable_full_graph_joint_continuation','admission':ref(output/'preflight_manifest.json'),
                    'config_before':ref(private/f'resolved_config_before_{cid}.yaml'),
                    'config_after':ref(private/f'resolved_config_after_{cid}.yaml'),
                    'current_resolved_config':ref(run/'resolved_config.yaml'),'old_config_hashes_are_historical':True,
                    'original_preflight':continuation['original_preflight'],'new_recipe_sha256':frozen['recipe_sha256'],
                    'old_recipe_unchanged':True,'old_task_and_content_evidence_infrastructure_budgets_preserved':True,
                    'prospective_parallel_sources':config['run']['max_parallel_sources'],
                    'prospective_parallel_calls':config['agents']['max_parallel_calls'],'qualified':False}
                path=run/'runtime_supplements'/('full_graph_joint_'+cid+'.json');write(path,addendum)
                audit.emit('run.full_graph_joint_continuation',addendum=ref(path))
            server=cohort.DashboardServer(audit.snapshot,audit.events,host='127.0.0.1',port=port);url=server.start()
            audit.update_run(dashboard_url=url,producer_pid=os.getpid(),producer_active=True,code_revision=revision,
                host_temporary_directory=host['temporary_directory'],host_runtime_receipt=host)
            llm=cohort.CohortCodex(ROOT,run,audit,config['agents']);llm._credentials()
            engine=cohort.LibreOfficeEngine(ROOT,cohort.IMAGE,config['engine']['timeout_seconds'])
            require(engine.metadata()['image_id']==cohort.IMAGE_ID,'Full-graph quality runtime differs')
            print(json.dumps({'run_dir':str(run),'dashboard_url':url,'development_only':frozen['development_only']}),flush=True)
            status=0 if FullGraphFactoryCompat(config,audit,llm,engine,legacy_validator=cohort.validate_seed).run() else 2
            for path,expected in frozen['recipe_sha256'].items():require(sha(path)==expected,'Full-graph recipe changed during execution')
            if continuation:
                for path,expected in continuation['original_recipe_sha256'].items():require(sha(path)==expected,'Original main recipe changed')
            return status
        finally:
            adapted.finalize_execution(audit,server,session,lease,phase_wall=round(time.monotonic()-started,3),previous_wall=previous,status=status)



def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-prepared', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.prepared:
        require(not args.base_prepared and not args.output, 'Use a single preparation source')
        if args.run:
            return execute_prepared(args.prepared, port=args.port)
        result = validate_prepared(args.prepared)
        print(json.dumps({'prepared': str(args.prepared), 'models_started': 0, 'LO_calls': 0}))
        return 0
    require(args.base_prepared and args.output and not args.run, 'Prepare a fresh phase before explicit execution')
    result = prepare(args.output, args.base_prepared)
    print(json.dumps({'preparation': result, 'models_started': 0, 'LO_calls': 0}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

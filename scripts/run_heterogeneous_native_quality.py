#!/usr/bin/env python3
"""Prepare and run the normal twelve-check factory for scoped native tasks."""
from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from sheets_factory.pipelines import heterogeneous_native_quality as pipeline
from sheets_factory.workbook.thread_capped_resource_engine import ThreadCappedResourceLibreOfficeEngine
from sheets_factory.evaluation.resource_observer import ResourceObserver
from sheets_factory.resume import PROTECTED_BUDGETS

KIND = 'prepared_scoped_native_business_normal_quality'
DEFAULT_CONFIG = ROOT/'config/pipelines/heterogeneous_native_quality_v1.yaml'
reference, require = pipeline.reference, pipeline.require
_SESSIONS = {}


def support():
    path = ROOT/'scripts/run_linear_capital_quality.py'
    spec = importlib.util.spec_from_file_location('_native_normal_runtime_support', path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


runtime = support()


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write('\n')
    return reference(path)


def recipes(config, admissions):
    from sheets_factory.task_adapters import heterogeneous_native_quality as nodes
    files = [Path(__file__), Path(pipeline.__file__), Path(nodes.__file__), pipeline.BOUNDARY,
        pipeline.REGISTRY, DEFAULT_CONFIG, ROOT/'scripts/run_linear_capital_quality.py']
    result = {**runtime.recipes(config, []), **{str(p.resolve()): reference(p)['sha256'] for p in files}}
    for value in admissions:
        result.update(value.recipe)
    return result


def configure(path, output, proofs):
    config = yaml.safe_load(Path(path).read_text())
    llm = yaml.safe_load((ROOT/'config/llm.yaml').read_text())
    agents = yaml.safe_load((ROOT/'config/agents.yaml').read_text())
    config['agents'] = {**llm, **config['agents'],
        'roles': {**agents.get('roles', {}), **config['agents'].get('roles', {})}}
    config['prompt_overrides'] = {**agents.get('prompts', {}), **config.get('prompt_overrides', {})}
    config.update(project_root=str(ROOT), run_dir=str(output))
    config[pipeline.SETTING] = pipeline.setting()
    config['pipeline'] = {**config.get('pipeline', {}), 'node_registry': str(pipeline.REGISTRY)}
    source_count = len({proof['workbook']['sha256'] for proof in proofs})
    require(type(config['run']['max_parallel_sources']) is int and config['run']['max_parallel_sources'] > 0,
        'Configure positive source concurrency')
    config['run'].update(targets={mode: sum(proof['mode'] == mode for proof in proofs)
        for mode in ('financial_modeling', 'debugging')}, seed_manifest=str(output/'seed_manifest.json'),
        max_sources=source_count, max_parallel_sources=min(source_count, config['run']['max_parallel_sources']))
    config['host_runtime'] = runtime.cohort.host_runtime_settings(output)
    pipeline.validate_configuration(config)
    return config


def prepare(terminals, output, *, config_path=DEFAULT_CONFIG):
    out = Path(output).absolute()
    require(out == out.resolve() and not out.exists(), 'Use a fresh real normal quality directory')
    require(type(terminals) is list and terminals, 'Declare the actual task terminals explicitly')
    out.mkdir(parents=True)
    write(out/'preparation_started.json', {'kind': KIND, 'model_calls': 0, 'LO_calls': 0,
        'Harbor_calls': 0, 'qualified': False, 'selected_actual_tasks': len(terminals)})
    try:
        admissions = tuple(pipeline.NativeScopeAdmission(value) for value in terminals)
        proofs = [pipeline.admission(value) for value in admissions]
        require(len({(p['workbook']['sha256'], p['mode']) for p in proofs}) == len(proofs),
            'A native source/mode view was duplicated')
        config = configure(config_path, out, proofs)
        seeds = {}
        for proof in proofs:
            sha = proof['workbook']['sha256']
            seed = seeds.setdefault(sha, {'local_path': proof['workbook']['path'], 'sha256': sha,
                'source_kind': pipeline.NORMAL_SOURCE_KIND, 'variant': 0, 'modes': [],
                'finance_evidence': {'financial_modeling_eligible': True, 'debugging_eligible': True,
                    'financial_seed_verified': False, 'financial_evidence_scope': '766 audited task outputs',
                    'scoped_task_admissions': {}}})
            seed['modes'].append(proof['mode']); seed['finance_evidence']['scoped_task_admissions'][proof['mode']] = proof
        mapping = {(p['workbook']['sha256'], p['mode']): a for p, a in zip(proofs, admissions)}
        for seed in seeds.values():
            pipeline.validate_seed(seed, mapping)
        seed_ref = write(out/'seed_manifest.json', {'selected': list(seeds.values()),
            'unique_workbooks_inspected': len(seeds), 'download_url': 'local:scoped-native-business-views',
            'archive_sha256': None, 'qualified': False, 'task_count': 0})
        (out/'resolved_config.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        frozen = {'kind': KIND, 'version': 1, 'declared_actual_terminals': [p['actual_validation'] for p in proofs],
            'scoped_admissions': [write(out/'private'/f'admission_{i}.json', p) for i, p in enumerate(proofs)],
            'prepared_seed_manifest': seed_ref, 'configuration_input': reference(config_path),
            'resolved_config': reference(out/'resolved_config.yaml'), 'targets': config['run']['targets'],
            'protected_task_budgets': {k: config['run'].get(k) for k in PROTECTED_BUDGETS},
            'host_runtime': config['host_runtime'], 'count': len(proofs),
            'recipe_sha256': recipes(config, admissions), 'reference_evidence_policy': 'reference_review',
            'independent_public_solver_attempted': False, 'whole_source_financial_certificate': False,
            'existing_development_score_transferred': False, 'qualified': False, 'task_count': 0,
            'actual_models': 0, 'actual_LO_calls': 0, 'actual_Harbor_jobs': 0}
        receipt = write(out/'preflight_manifest.json', frozen)
        refs = pipeline.References(); refs.walk(frozen)
        _SESSIONS[(str(out), receipt['sha256'])] = (deepcopy(frozen), deepcopy(config), admissions, refs)
        return receipt
    except BaseException as error:
        write(out/'preparation_failure.json', {'error_type': type(error).__name__, 'error': str(error),
            'qualified': False, 'model_calls': 0, 'LO_calls': 0, 'Harbor_calls': 0})
        raise


def validate_prepared(output):
    out = Path(output).absolute(); frozen_ref = reference(out/'preflight_manifest.json')
    key = (str(out), frozen_ref['sha256'])
    if key in _SESSIONS:
        frozen, config, admissions, refs = _SESSIONS[key]
        refs.guard(); runtime.guard_recipes(frozen['recipe_sha256'])
        for value in admissions:
            pipeline.admission(value)
        return deepcopy(frozen), deepcopy(config), admissions
    refs = pipeline.References(); frozen = refs.read(frozen_ref); refs.walk(frozen)
    require(frozen['kind'] == KIND and type(frozen['version']) is int and frozen['version'] == 1
        and frozen['qualified'] is False and frozen['task_count'] == 0
        and all(type(frozen[k]) is int and frozen[k] == 0 for k in ('actual_models', 'actual_LO_calls', 'actual_Harbor_jobs')),
        'A genuine zero-service normal quality preparation is required')
    runtime.guard_recipes(frozen['recipe_sha256'])
    admissions = tuple(pipeline.NativeScopeAdmission(value) for value in frozen['declared_actual_terminals'])
    config = yaml.safe_load(Path(frozen['resolved_config']['path']).read_text()); pipeline.validate_configuration(config)
    require(config['run_dir'] == str(out) and config['run']['targets'] == frozen['targets']
        and config['run']['seed_manifest'] == str(out/'seed_manifest.json') and config['host_runtime'] == frozen['host_runtime']
        and {k: config['run'].get(k) for k in PROTECTED_BUDGETS} == frozen['protected_task_budgets']
        and len(admissions) == frozen['count'] == len(frozen['scoped_admissions']), 'The inventory or normal budgets changed')
    for value, record in zip(admissions, frozen['scoped_admissions']):
        require(pipeline.admission(value) == refs.read(record), 'An actual scoped proof changed')
    _SESSIONS[key] = (deepcopy(frozen), deepcopy(config), admissions, refs)
    return deepcopy(frozen), deepcopy(config), admissions


def execute_prepared(output, *, port=0):
    out = Path(output).absolute(); frozen, config, admissions = validate_prepared(out)
    cohort = runtime.cohort; settings, legacy = cohort.prepared_host_runtime(out)
    with cohort.host_temporary_environment(out, settings, legacy_preparation=legacy) as host:
        require(not (out/'started.json').exists() and not (out/'run.sqlite').exists(), 'Preserve the first normal execution')
        lease = cohort.ProducerLease(out).acquire(); audit = server = None; status = 1; tick = time.monotonic()
        try:
            write(out/'started.json', {'preflight': reference(out/'preflight_manifest.json'),
                'producer_pid': os.getpid(), 'target_count': frozen['count']})
            audit = cohort.AuditStore(out, {'id': out.name, 'target_count': frozen['count'],
                'financial_target': frozen['targets']['financial_modeling'], 'debugging_target': frozen['targets']['debugging'],
                'status': 'preflight', 'model': config['agents']['model'], 'reasoning_effort': config['agents']['reasoning_effort']})
            server = cohort.DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port); url = server.start()
            audit.update_run(dashboard_url=url, producer_pid=os.getpid(), producer_active=True, host_runtime_receipt=host)
            print(json.dumps({'run_dir': str(out), 'dashboard_url': url, 'models_started': False}), flush=True)
            engine = ThreadCappedResourceLibreOfficeEngine(ROOT, pipeline.PROFILE, role='source', receipt_directory=out/'resource_receipts')
            engine.ensure_image()
            llm = runtime.LinearCohortCodex(ROOT, out, audit, config['agents']); llm._credentials()
            with ResourceObserver(out, job_dirs=[out/'harbor_jobs']) as observer:
                status = 0 if pipeline.NativeQualityFactory(config, audit, llm, engine, admissions=admissions).run() else 2
            if observer.receipt:
                write(out/'normal_Harbor_resource_observation.json', {'receipt': observer.receipt})
            for value in admissions:
                pipeline.admission(value)
            runtime.guard_recipes(frozen['recipe_sha256'])
            return status
        finally:
            if audit is not None:
                runtime.support('run_adapted_debug_quality.py').finalize_execution(audit, server, None, lease,
                    phase_wall=round(time.monotonic()-tick, 3), previous_wall=0, status=status)
                audit.db.close()
            else:
                lease.release()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--actual-terminal', type=Path, action='append')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args()
    require(0 <= args.port <= 65535, 'Use a valid local dashboard port')
    if args.prepared:
        require(not args.actual_terminal and args.output is None and args.config == DEFAULT_CONFIG,
            'Prepared executions cannot replace the selected inputs or configuration')
        if args.run:
            return execute_prepared(args.prepared, port=args.port)
        result = validate_prepared(args.prepared)[0]
    else:
        require(args.actual_terminal and args.output is not None, 'Provide actual task terminals and a fresh output')
        result = prepare(args.actual_terminal, args.output, config_path=args.config)
        if args.run:
            return execute_prepared(args.output, port=args.port)
    print(json.dumps(result)); return 0


if __name__ == '__main__':
    raise SystemExit(main())

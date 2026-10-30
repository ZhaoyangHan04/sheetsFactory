#!/usr/bin/env python3
"""Prepare explicit adapted DBG sources; run the full Factory only with --run."""
from __future__ import annotations

import argparse
import fcntl
from copy import deepcopy
import importlib.util
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.pipelines.adapted_factory import (
    ADAPTER, SOURCE_KIND, AdaptedSourceFactory, HistoricalRecipeUnavailable, canonical, checked, collect_references,
    read, reference, require, sha, validate_activity_probe, validate_presentation_seed,
)
from sheets_factory.reporting import read_run
from sheets_factory.resume import assert_resume_allowed

spec = importlib.util.spec_from_file_location('_frozen_composite_quality_entry', ROOT / 'scripts/run_composite_quality_cohort.py')
cohort = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cohort)


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def _snapshot_map(directory, recipe):
    result = {}
    for path, expected in recipe.items():
        original = Path(path)
        if original.is_file() and sha(original) == expected:
            continue
        require(directory is not None, 'Changed historical source recipe requires --source-recipe-snapshot')
        snapshot = Path(directory) / original.name
        require(snapshot.is_file() and sha(snapshot) == expected, 'Historical recipe snapshot differs: ' + path)
        result[path] = reference(snapshot)
    return result


def recipe_files(root=ROOT):
    """Freeze added routing and the unchanged mandatory quality implementation."""
    root = Path(root)
    paths = {Path(__file__).resolve(), Path(cohort.__file__).resolve(),
             root / 'config/pipelines/composite_quality20.yaml', root / 'config/agents.yaml', root / 'config/llm.yaml'}
    paths.update((root / 'src/sheets_factory').rglob('*.py'))
    paths.update((root / 'src/sheets_factory/pipelines/templates').glob('*.yaml'))
    paths.update((root / 'config').glob('*.yaml'))
    paths.update((root / 'prompts').glob('*.md'))
    return {str(p.resolve()): sha(p) for p in sorted(paths)}


def snapshot_ancestor_recipe(record, output):
    """Recover only an exact approved historical Python leaf from local Git."""
    from sheets_factory.pipelines.adapted_factory import HISTORICAL_CODE_ROOT
    original = Path(record['path']).resolve()
    require(original.suffix == '.py' and original.is_relative_to(HISTORICAL_CODE_ROOT)
            and original.is_relative_to(ROOT), 'Historical recipe resolver accepts approved source Python leaves only')
    relative = original.relative_to(ROOT).as_posix()
    history = subprocess.run(['git', 'log', '--all', '--format=%H', '--', relative], cwd=ROOT,
                             capture_output=True, check=True, text=True, timeout=10).stdout.splitlines()
    for revision in dict.fromkeys(history):
        content = subprocess.run(['git', 'show', revision + ':' + relative], cwd=ROOT,
                                 capture_output=True, timeout=10)
        if content.returncode or hashlib.sha256(content.stdout).hexdigest() != record['sha256']:
            continue
        directory = Path(output) / 'ancestor_recipe_snapshots'
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / (record['sha256'] + '.py')
        if not path.exists():
            with path.open('xb') as stream:
                stream.write(content.stdout)
        require(sha(path) == record['sha256'], 'Recovered ancestor source snapshot differs')
        return {'original_reference': deepcopy(record), 'exact_snapshot': reference(path),
                'git_commit': revision, 'repository_path': relative,
                'scope': 'Historical ancestor recipe Python leaf only; no data or financial-audit substitution'}
    raise ValueError('No exact Git blob for historical ancestor source: ' + str(record))


def prepare_adapted(source_manifest, output, *, count=1, activity_probes=(), source_recipe_snapshot=None,
                    host_temp_min_free_bytes=cohort.DEFAULT_TEMP_MIN_FREE_BYTES):
    require(type(count) is int and count in {1, 10}, 'Prepare exactly one probe source or ten DBG sources')
    output = Path(output).resolve()
    require(not output.exists(), 'Preparation output exists; use a fresh output directory')
    host = cohort.host_runtime_settings(output, host_temp_min_free_bytes)
    source_manifest = Path(source_manifest).resolve()
    manifest = json.loads(source_manifest.read_text())
    selected = manifest.get('selected')
    require(isinstance(selected, list) and len(selected) == count, 'Admit the complete declared source selection in its frozen order')
    require(manifest.get('model_scores_consulted', False) is False, 'Source selection may not consult model scores')
    probes = {}
    for path in activity_probes:
        record = reference(path)
        probe = read(record)
        identity = probe.get('baseline', {}).get('sha256')
        require(identity is not None and identity not in probes, 'Duplicate or unbound activity probe')
        probes[identity] = record
    entries, bindings, identities, task_ids = [], {str(source_manifest): sha(source_manifest)}, set(), set()
    ancestor_resolutions = []
    output.mkdir(parents=True)
    for item in selected:
        entry = deepcopy(item)
        require(entry.get('source_kind') == SOURCE_KIND, 'Only explicit presentation sources use this preparation entry')
        if 'source_manifest' not in entry:
            require(count == 1 and manifest.get('status') == 'actually_verified_active_schedule_source',
                    'Every source in a batch requires its own complete source manifest')
            entry['source_manifest'] = reference(source_manifest)
        source = read(entry['source_manifest'])
        from sheets_factory.task_adapters import lease_family
        entry['task_adapter'] = {'id': ADAPTER, 'policy': deepcopy(source['presentation_policy']),
            'policy_sha256': canonical(source['presentation_policy']),
            'implementation': reference(lease_family.__file__), 'source_manifest': deepcopy(entry['source_manifest'])}
        entry.update(modes=['debugging'], variant=0)
        evidence = deepcopy(entry.get('finance_evidence', {}))
        evidence['source_recipe_snapshots'] = _snapshot_map(source_recipe_snapshot, source.get('recipe', {}))
        entry['finance_evidence'] = evidence
        evidence['ancestor_recipe_snapshots'] = {}
        while True:
            try:
                proof = validate_presentation_seed(entry, bindings)
                break
            except HistoricalRecipeUnavailable as missing:
                resolution = snapshot_ancestor_recipe(missing.reference, output)
                ancestor_resolutions.append(resolution)
                evidence['ancestor_recipe_snapshots'][str(Path(missing.reference['path']).resolve())] = resolution['exact_snapshot']
        identity = entry['sha256']
        task_id = 'dbg-' + identity[:12]
        require(identity not in identities and task_id not in task_ids, 'Duplicate source SHA or task ID prefix')
        identities.add(identity)
        task_ids.add(task_id)
        if identity in probes:
            validation = validate_activity_probe(entry, probes[identity], bindings)
            evidence['adapter_activity_admission'] = validation
        evidence.update(financial_seed_verified=True, source_business_issues=[],
            task_adapter=deepcopy(entry['task_adapter']), audited_source_binding=proof,
            source_manifest=deepcopy(entry['source_manifest']), public_scenarios=proof['public_scenarios'],
            independent_financial_audits=proof['independent_financial_audits'],
            complete_independent_reference_audits=proof['independent_financial_audits'])
        entry['survey'] = {'normalized_path': proof['workbook']['path'], 'source_sha256': identity,
                           'status': 'ok', 'error_count': 0}
        entries.append(entry)
    require(set(probes) <= identities, 'Activity probe does not belong to the frozen source selection')
    config = yaml.safe_load((ROOT / 'config/pipelines/composite_quality20.yaml').read_text())
    llm = yaml.safe_load((ROOT / 'config/llm.yaml').read_text())
    agents = yaml.safe_load((ROOT / 'config/agents.yaml').read_text())
    config['agents'] = {**llm, **config['agents'], 'roles': {**agents.get('roles', {}), **config['agents'].get('roles', {})}}
    config['prompt_overrides'] = {**agents.get('prompts', {}), **config.get('prompt_overrides', {})}
    config.update(project_root=str(ROOT), run_dir=str(output), host_runtime=host)
    config['run']['seed_manifest'] = str(output / 'seed_manifest.json')
    require(config['run']['targets'] == {'financial_modeling': 10, 'debugging': 10}, 'Fixed 10+10 targets changed')
    recipes = recipe_files()
    for path, expected in bindings.items():
        require(sha(path) == expected, 'Source evidence changed during preparation: ' + path)
    if ancestor_resolutions:
        history_receipt = output / 'ancestor_recipe_snapshots/manifest.json'
        write(history_receipt, {'kind': 'exact_historical_ancestor_python_snapshots', 'resolutions': ancestor_resolutions,
              'original_manifests_and_references_modified': False})
        bindings[str(history_receipt)] = sha(history_receipt)
    seed = {'schema_version': 1, 'kind': 'explicit_adapted_debugging_factory_sources',
        'selected': entries, 'unique_workbooks_inspected': count, 'download_url': 'private-adapted-source:' + sha(source_manifest),
        'archive_sha256': None, 'source_manifest': reference(source_manifest),
        'qualified': False, 'task_count': 0, 'derived_scenarios_are_independent_observed_companies': False}
    write(output / 'seed_manifest.json', seed)
    (output / 'resolved_config.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
    frozen = {'kind': 'prepared_adapted_debugging_quality_admission', 'prepared_at': cohort.utcnow(),
        'source_count': count, 'selected_source_sha256': [e['sha256'] for e in entries],
        'source_artifacts_sha256': bindings, 'recipe_sha256': recipes,
        'prepared_seed_manifest': reference(output / 'seed_manifest.json'),
        'resolved_config': reference(output / 'resolved_config.yaml'), 'host_runtime': host,
        'targets': config['run']['targets'], 'normal_factory_routing': True,
        'actual_model_calls': 0, 'qualified': False, 'quality_recovery_difficulty_certified': False,
        'execution_requires_passing_bound_activity_probe': True,
        'activity_probe_bindings': {key: value for key, value in probes.items()}}
    write(output / 'preflight_manifest.json', frozen)
    return frozen


def validate_prepared(output, *, require_activity=True):
    output = Path(output).resolve()
    frozen = json.loads((output / 'preflight_manifest.json').read_text())
    require(frozen.get('kind') == 'prepared_adapted_debugging_quality_admission', 'Unexpected prepared admission kind')
    for group in ('source_artifacts_sha256', 'recipe_sha256'):
        for path, expected in frozen[group].items():
            require(sha(path) == expected, 'Frozen adapted admission artifact changed: ' + path)
    checked(frozen['prepared_seed_manifest'])
    checked(frozen['resolved_config'])
    seeds = read(frozen['prepared_seed_manifest'])['selected']
    require([e['sha256'] for e in seeds] == frozen['selected_source_sha256'], 'Prepared source order differs')
    for seed in seeds:
        validate_presentation_seed(seed)
        if require_activity:
            probe = frozen['activity_probe_bindings'].get(seed['sha256'])
            require(probe is not None, 'No actual passing source/policy/edit-bound probe; execution is blocked')
            validate_activity_probe(seed, probe)
    return frozen


def validate_continuation(run):
    """Preserve the existing 10+10 recipe and all existing task budgets."""
    run = Path(run).resolve()
    frozen = json.loads((run / 'preflight_manifest.json').read_text())
    config = yaml.safe_load((run / 'resolved_config.yaml').read_text())
    require(config['run']['targets'] == {'financial_modeling': 10, 'debugging': 10}, 'Continuation requires fixed original 10+10 targets')
    for group in ('recipe_sha256', 'source_artifacts_sha256'):
        for path, expected in frozen.get(group, {}).items():
            require(sha(path) == expected, 'Existing main recipe/source changed: ' + path)
    if 'prepared_seed_manifest' in frozen:
        checked(frozen['prepared_seed_manifest'])
    assert_resume_allowed(run, read_run(run))
    return {'original_preflight': reference(run / 'preflight_manifest.json'),
            'resolved_config_before': reference(run / 'resolved_config.yaml'),
            'original_recipe_sha256': deepcopy(frozen['recipe_sha256']),
            'existing_targets': deepcopy(config['run']['targets'])}


def execute_prepared(output, *, resume=None, port=0):
    output = Path(output).resolve()
    run = Path(resume).resolve() if resume else output
    continuation = validate_continuation(run) if resume else None
    settings, legacy = cohort.prepared_host_runtime(run)
    # Enter before AuditStore, dashboard, engine, Codex, or any workbook work.
    with cohort.host_temporary_environment(run, settings, legacy_preparation=legacy) as host_receipt:
        frozen = validate_prepared(output)
        return _execute_prepared(output, frozen, run, continuation, host_receipt, port=port)


def _execute_prepared(output, frozen, run, continuation, host_receipt, *, port=0):
    revision = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    session = None
    if continuation:
        session = cohort.prepare_resume(run, extra_manifest=output / 'seed_manifest.json', current_code_revision=revision,
            reason='Append explicit hash-bound adapted DBG sources; retain original 10+10 targets, recipe and task budgets')
        config, audit, lease = session.config, session.audit, session.lease
    else:
        config = yaml.safe_load((output / 'resolved_config.yaml').read_text())
        require(not (run / 'run.sqlite').exists(), 'Prepared run already started; use explicit terminal continuation')
        lease = cohort.ProducerLease(run).acquire()
        try:
            audit = cohort.AuditStore(run, {'id': run.name, 'target_count': 20, 'financial_target': 10, 'debugging_target': 10,
                'model': config['agents']['model'], 'reasoning_effort': config['agents']['reasoning_effort'],
                'difficulty_status': 'pending', 'status': 'preflight'})
        except BaseException:
            lease.release()
            raise
    server, status, started = None, 1, time.monotonic()
    previous_wall = audit.run.get('wall_seconds', 0) or 0
    try:
        if continuation:
            addendum = {**continuation, 'kind': 'immutable_adapted_factory_continuation', 'created_at': cohort.utcnow(),
                'new_admission': reference(output / 'preflight_manifest.json'),
                'adapter_recipe_sha256': deepcopy(frozen['recipe_sha256']), 'host_runtime_receipt': host_receipt,
                'original_recipe_unchanged': True, 'original_tasks_and_budgets_preserved': True,
                'source_proof_is_fresh_lease_plus_explicit_transitive_coverage': True,
                'quality_recovery_difficulty_certified': False}
            path = run / 'runtime_supplements' / ('adapted_continuation_' + config['run']['continuation_id'] + '.json')
            write(path, addendum)
            audit.emit('run.adapter_continuation', addendum=reference(path))
        server = cohort.DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port)
        url = server.start()
        audit.update_run(dashboard_url=url, producer_pid=os.getpid(), producer_active=True, code_revision=revision,
                         host_temporary_directory=host_receipt['temporary_directory'], host_runtime_receipt=host_receipt)
        llm = cohort.CohortCodex(ROOT, run, audit, config['agents'])
        llm._credentials()
        engine = cohort.LibreOfficeEngine(ROOT, cohort.IMAGE, config['engine']['timeout_seconds'])
        require(engine.metadata()['image_id'] == cohort.IMAGE_ID, 'Execution runtime differs from audited runtime')
        audit.emit('run.adapter_preflight', admission=reference(output / 'preflight_manifest.json'),
                   normal_factory_quality_routing=True, activity_is_not_quality=True)
        print(json.dumps({'run_dir': str(run), 'dashboard_url': url}), flush=True)
        status = 0 if AdaptedSourceFactory(config, audit, llm, engine, legacy_validator=cohort.validate_seed).run() else 2
        for path, expected in frozen['recipe_sha256'].items():
            require(sha(path) == expected, 'Adapted admission recipe changed during execution: ' + path)
        if continuation:
            for path, expected in continuation['original_recipe_sha256'].items():
                require(sha(path) == expected, 'Main recipe changed during continuation: ' + path)
        return status
    finally:
        phase_wall = round(time.monotonic() - started, 3)
        finalize_execution(audit, server, session, lease, phase_wall=phase_wall,
                           previous_wall=previous_wall, status=status)


def finalize_execution(audit, server, session, lease, *, phase_wall, previous_wall, status):
    """Release process resources even if persistence or dashboard shutdown fails."""
    try:
        audit.update_run(producer_active=False, finished_at=cohort.utcnow(), last_phase_wall_seconds=phase_wall,
                         wall_seconds=round(previous_wall + phase_wall, 3), exit_code=status)
        audit.export()
    finally:
        try:
            if server:
                server.stop()
        finally:
            try:
                if session:
                    session.close()
            finally:
                try:
                    lease.release()
                finally:
                    # ProducerLease writes a final status before unlocking. A
                    # failed status write must not keep the actual lock open.
                    stream = getattr(lease, 'stream', None)
                    if stream is not None:
                        try:
                            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
                        finally:
                            stream.close()
                            lease.stream = None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--count', type=int, choices=(1, 10), default=1)
    parser.add_argument('--activity-probe', type=Path, action='append', default=[])
    parser.add_argument('--source-recipe-snapshot', type=Path)
    parser.add_argument('--prepared', type=Path)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--run', action='store_true', help='Explicitly execute normal model/quality/Harbor stages')
    parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.prepared:
        require(args.source_manifest is None and args.output is None and not args.activity_probe
                and args.source_recipe_snapshot is None, 'Prepared execution cannot replace frozen inputs')
        output = args.prepared.resolve()
        validate_prepared(output, require_activity=False)
    else:
        require(args.source_manifest is not None and args.output is not None, 'Preparation requires --source-manifest and fresh --output')
        output = args.output.resolve()
        prepare_adapted(args.source_manifest, output, count=args.count, activity_probes=args.activity_probe,
                        source_recipe_snapshot=args.source_recipe_snapshot)
    require(args.resume is None or args.run, '--resume requires explicit --run')
    if args.run:
        return execute_prepared(output, resume=args.resume, port=args.port)
    print(json.dumps({'prepared': str(output), 'models_started': 0, 'qualified': 0}), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

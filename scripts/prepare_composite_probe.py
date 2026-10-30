#!/usr/bin/env python3
"""Prepare a development probe with ordinary construction and five controls."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import uuid
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.core.node import TaskContext
from sheets_factory.dashboard import DashboardServer
from sheets_factory.evaluation.harbor import export_harbor, inspect_export
from sheets_factory.nodes.construction import ProfileNode, PlanNode, ConstructNode, InstructionNode, ControlsNode, compile_mask_ranges
from sheets_factory.workbook.composite_finance.build import RUNTIME, RUNTIME_ID
from sheets_factory.workbook.composite_finance.tasks import propose_task
from sheets_factory.workbook.engine import LibreOfficeEngine


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, default=str) + '\n')


class NoModelCalls:
    def __getattr__(self, name):
        raise RuntimeError('Deterministic probe preparation cannot call a model: ' + name)


CONTROL_REWARDS = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}


def validate_source_manifest(source_manifest):
    """Read and bind existing source evidence without running an engine."""
    source_manifest = Path(source_manifest).resolve()
    source_raw = source_manifest.read_bytes()
    source = json.loads(source_raw)
    if (source.get('status') != 'independently_verified_composed_financial_seed'
            or source.get('financial_audit_passed') is not True or len(source.get('selected', [])) != 1):
        raise ValueError('A complete independently audited composed seed is required')
    entry = source['selected'][0]
    baseline, identity = Path(entry['local_path']), entry['sha256']
    if sha(baseline) != identity:
        raise ValueError('Changed composed financial seed')
    for key in ('financial_audit', 'stability', 'public_scenarios'):
        if sha(source[key]['path']) != source[key]['sha256']:
            raise ValueError('Changed composed financial proof: ' + key)
    if not all(item['passed'] is True for item in source['financial_audits'].values()):
        raise ValueError('An independent component financial audit did not pass')
    if json.loads(Path(source['stability']['path']).read_text())['stable'] is not True:
        raise ValueError('Source does not have passing actual stability evidence')
    tracked = {source_manifest: hashlib.sha256(source_raw).hexdigest(), baseline: identity}
    tracked.update({Path(source[key]['path']).resolve(): source[key]['sha256']
                    for key in ('financial_audit', 'stability', 'public_scenarios')})
    return source, entry, tracked


def validate_preparation_options(mode, root_impact_validation='strict', composite_activity=False):
    if mode not in {'financial_modeling', 'debugging'}:
        raise ValueError('Composite preparation mode must be financial_modeling or debugging')
    if root_impact_validation not in {'strict', 'shadow_roots'}:
        raise ValueError('Composite preparation root_impact_validation must be strict or shadow_roots')
    if type(composite_activity) is not bool:
        raise ValueError('composite_activity must be an explicit boolean')
    if mode != 'debugging' and (composite_activity or root_impact_validation != 'strict'):
        raise ValueError('Activity screening and shadow_roots are available only for debugging')


def prepare(source_manifest, output, mode='financial_modeling', *,
            root_impact_validation='strict', composite_activity=False, progress=None):
    validate_preparation_options(mode, root_impact_validation, composite_activity)
    source_manifest, output = Path(source_manifest).resolve(), Path(output).resolve()
    source, entry, tracked = validate_source_manifest(source_manifest)
    baseline, identity = Path(entry['local_path']), entry['sha256']
    output.mkdir(parents=True, exist_ok=False)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-composite-' + uuid.uuid4().hex[:6]
    audit = AuditStore(output, {'id': run_id, 'kind': 'prequality_development_probe',
        'status': 'preparing', 'target_count': 1, 'llm_calls_permitted': False})
    server = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=0)
    url = server.start()
    audit.update_run(dashboard_url=url, producer_active=True)
    print(json.dumps({'run': str(output), 'dashboard_url': url}), flush=True)
    task_id = ('fm-' if mode == 'financial_modeling' else 'dbg-') + identity[:12]
    try:
        config = yaml.safe_load((ROOT / 'config/pipelines/portfolio_scale.yaml').read_text())
        llm = yaml.safe_load((ROOT / 'config/llm.yaml').read_text())
        agents = yaml.safe_load((ROOT / 'config/agents.yaml').read_text())
        config['agents'] = {**llm, 'roles': agents.get('roles', {}), **config.get('agents', {})}
        config.update(project_root=str(ROOT), run_dir=str(output))
        config['run'].update(name='composed-financial-prequality-probe', seed_manifest=str(source_manifest))
        config['engine'].update(image=RUNTIME, timeout_seconds=300)
        config['construction'].update(authoring_backend='llm', root_impact_validation=root_impact_validation,
            max_edit_count={'financial_modeling': 100000, 'debugging': 5000},
            analysis_limits={'max_dependency_closure_cells': 500000, 'max_profile_cells': 500000,
                             'per_formula_reference_cells': 50000, 'max_mask_ranges': 1024})
        if composite_activity:
            config['construction'].update(authoring_backend='composite_template', planning_scope='per_mode',
                                           composite_activity={'enabled': True})
        (output / 'resolved_config.yaml').write_text(yaml.safe_dump(config, sort_keys=False))
        cache = output / 'sources' / identity[:12]
        cache.mkdir(parents=True)
        isolated = cache / 'baseline.xlsx'
        shutil.copy2(baseline, isolated)
        plan_data = {}
        if not composite_activity:
            proposal = propose_task(isolated, mode=mode)
            planning_path = cache / ('task_plans_v0_' + mode + '.json')
            write(planning_path, {mode: proposal})
            plan_data['plan'] = compile_mask_ranges(deepcopy(proposal), isolated, mode, config)
        engine = LibreOfficeEngine(ROOT, image=RUNTIME, timeout_seconds=300)
        metadata = engine.metadata()
        if metadata['image_id'] != RUNTIME_ID:
            raise ValueError('Unexpected development probe runtime')
        ctx = TaskContext(run_id, task_id, mode, baseline, output / 'tasks' / task_id,
            config, audit, NoModelCalls(), engine, data={**plan_data, 'baseline': isolated,
                'source_cache': cache, 'source_id': identity, 'finance_evidence': entry['finance_evidence'],
                'source_business_issues': [], 'engine_report': {'normalization_ok': True,
                    'recalculation_ok': True, 'stable': True, 'engine': metadata}})
        audit.task(task_id, source_id=identity, source=baseline.name, mode=mode, status='preparing')

        def run_node(node):
            started = time.monotonic()
            if progress:
                progress(task_id=task_id, node=node.node_id, status='running')
            try:
                node.run(ctx)
            except BaseException as exc:
                if progress:
                    progress(task_id=task_id, node=node.node_id, status='failed',
                             duration_ms=round((time.monotonic() - started) * 1000), error=str(exc))
                raise
            if progress:
                progress(task_id=task_id, node=node.node_id, status='completed',
                         duration_ms=round((time.monotonic() - started) * 1000))
            audit.export()

        run_node(ProfileNode())
        if composite_activity:
            run_node(PlanNode())
            ctx.data['plan'] = compile_mask_ranges(deepcopy(ctx.data['plan']), isolated, mode, config)
            planning_path = cache / ('prepared_plan_v0_' + mode + '.json')
            write(planning_path, {mode: ctx.data['plan']})
        plan = ctx.data['plan']
        for node in (ConstructNode(), InstructionNode(), ControlsNode()):
            run_node(node)
        rewards = {name: ctx.data['controls'][name]['reward']
                   for name in ('oracle', 'nop', 'equivalent', 'missed_root', 'extra_change')}
        if rewards != CONTROL_REWARDS:
            raise ValueError('Actual construction controls failed')
        task_meta = {'task_id': task_id, 'mode': mode, 'source_id': identity,
            'revision': ctx.revision, 'revision_hash': ctx.data['revision_hash'],
            'difficulty_status': 'prequality_development_probe',
            'source_kind': 'prequality_development_probe', 'base_image': RUNTIME}
        export = output / 'SpreadsheetEval' / task_id
        export_harbor(ctx.revision_dir, export, task_meta, ROOT)
        binding = inspect_export(export)
        if any(sha(path) != digest for path, digest in tracked.items()):
            raise ValueError('Verified source or manifest changed during preparation')
        manifest = {'schema_version': 1, 'kind': 'prequality_development_probe',
            'source_kind': 'prequality_development_probe', 'frozen_at': utcnow(),
            'quality_status': 'Independent source audit and five local controls passed; public-only recovery and full task diagnosis pending.',
            'selection_policy': 'The complete new financial schedules were selected before observing this revision model result.',
            'selected_task_ids': [task_id],
            'tasks': [{**task_meta, 'harbor_export_binding': binding, 'task_directory': str(export), 'local_controls': rewards}],
            'planning_origin': {'path': str(planning_path), 'sha256': sha(planning_path)},
            'source_manifest': {'path': str(source_manifest), 'sha256': sha(source_manifest)},
            'local_controls': rewards, 'model_evaluation_performed': False,
            'qualified': False, 'task_count': 0, 'llm_calls': 0}
        if composite_activity:
            proposal_path = cache / ('task_plans_v0_' + mode + '_composite_template.json')
            manifest['proposal_origin'] = {'path': str(proposal_path), 'sha256': sha(proposal_path)}
            manifest['planning_origin']['kind'] = 'final_screened_composite_template_plan'
            activity_file = ctx.revision_dir / 'private/composite_activity_result.json'
            manifest['activity_origin'] = {'path': str(activity_file), 'sha256': sha(activity_file)}
            manifest['composite_activity'] = True
        if root_impact_validation != 'strict':
            manifest['root_impact_validation'] = root_impact_validation
        write(output / 'probe_manifest.json', manifest)
        audit.task(task_id, status='probe_prepared', revision_hash=ctx.data['revision_hash'])
        audit.update_run(status='prepared', qualified=0)
        print(json.dumps({'probe_manifest': str(output / 'probe_manifest.json'),
                          'masks_or_bugs': len(plan['edits']),
                          'expected_changes': ctx.data['delta']['expected_change_count']}), flush=True)
        return manifest
    except BaseException as exc:
        write(output / 'preparation_failure.json', {'type': type(exc).__name__, 'error': str(exc)})
        audit.update_run(status='failed', error=str(exc), qualified=0)
        raise
    finally:
        audit.update_run(producer_active=False)
        audit.export()
        server.stop()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=['financial_modeling', 'debugging'], default='financial_modeling')
    parser.add_argument('--root-impact-validation', choices=['strict', 'shadow_roots'], default='strict')
    parser.add_argument('--composite-activity', action='store_true', help='Run the normal verified-source DBG activity planner')
    args = parser.parse_args()
    prepare(args.source_manifest, args.output, args.mode,
            root_impact_validation=args.root_impact_validation, composite_activity=args.composite_activity)

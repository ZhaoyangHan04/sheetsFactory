#!/usr/bin/env python3
"""Build one audited active-schedule source and a donor-complete DBG probe.

This command runs no model. It preserves failed outputs. Source certification
uses real LibreOffice; optional task construction uses ordinary nodes and five
controls, including the existing two-context shadow activity certificate.
"""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sheets_factory.core.audit import AuditStore, utcnow
from sheets_factory.core.node import TaskContext
from sheets_factory.dashboard import DashboardServer
from sheets_factory.evaluation.harbor import export_harbor, inspect_export
from sheets_factory.evaluation.tool_time_bounds import POLICY_V2
from sheets_factory.nodes.construction import ProfileNode, ConstructNode, InstructionNode, ControlsNode
from sheets_factory.task_adapters.lease_family import propose_debugging_task, ref, sha
from sheets_factory.task_adapters.presentation_source import build_presentation_source, IMAGE, IMAGE_ID
from sheets_factory.workbook.engine import LibreOfficeEngine


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, ensure_ascii=False, default=str) + '\n')


class NoModels:
    def __getattr__(self, name):
        raise RuntimeError('Donor-complete preparation cannot call a model: ' + name)


class ObservedEngine(LibreOfficeEngine):
    def recalculate(self, source, destination):
        began = time.monotonic()
        self.audit.emit('adapter.recalculation.started', source=str(source), destination=str(destination))
        try:
            result = super().recalculate(source, destination)
        except Exception as error:
            self.audit.emit('adapter.recalculation.failed', error=str(error), duration_ms=round((time.monotonic()-began)*1000))
            raise
        self.audit.emit('adapter.recalculation.completed', source=ref(source), result=ref(result),
                        duration_ms=round((time.monotonic()-began)*1000))
        return result


def prepare_probe(source, output, policy, audit, engine):
    goal = Path(source['local_path'])
    identity = source['derived_workbook_sha256']
    task_id = 'dbg-' + identity[:12]
    config = yaml.safe_load((ROOT / 'config/pipelines/composite_quality20.yaml').read_text())
    config.update(project_root=str(ROOT), run_dir=str(output))
    config['construction'].update(authoring_backend='llm', root_impact_validation='shadow_roots')
    config['construction']['max_edit_count']['debugging'] = policy.get('max_roots', 100000)
    cache = output / 'sources' / identity[:12]
    cache.mkdir(parents=True)
    baseline = cache / 'baseline.xlsx'
    shutil.copy2(goal, baseline)
    plan = propose_debugging_task(baseline, policy)
    write(cache / 'adapter_plan.json', plan)
    context = TaskContext(output.name, task_id, 'debugging', goal, output / 'tasks' / task_id,
        config, audit, NoModels(), engine, data={
            'source_id': identity, 'baseline': baseline, 'source_cache': cache, 'plan': plan,
            'finance_evidence': source['selected'][0]['finance_evidence'], 'source_business_issues': [],
            'source_assessment': {'financial_evidence': source['selected'][0]['finance_evidence'],
                                  'authoring_backend': 'lease_monetary_complete_v1', 'known_risks': []},
            'engine_report': {'normalization_ok': True, 'recalculation_ok': True, 'stable': True,
                'engine': source['runtime'], 'normalization_artifact': ref(goal),
                'stability_artifact': source['stability']}})
    audit.task(task_id, source_id=identity, mode='debugging', status='constructing', revision=0)
    for node in (ProfileNode(), ConstructNode(), InstructionNode(), ControlsNode()):
        node.run(context)
        audit.export()
    actual = {k: context.data['controls'][k]['reward'] for k in ('oracle', 'nop', 'equivalent', 'missed_root', 'extra_change')}
    if actual != {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}:
        raise ValueError('Actual five local controls failed')
    budget = {'version': 1, 'elapsed_policy': 'operational_guard',
              'elapsed_guard_seconds': 10800, 'tool_budget_seconds': 1800}
    meta = {'task_id': task_id, 'mode': 'debugging', 'source_id': identity, 'revision': 0,
            'revision_hash': context.data['revision_hash'], 'base_image': IMAGE,
            'source_kind': 'prequality_development_probe', 'difficulty_status': 'prequality_development_probe'}
    export = output / 'SpreadsheetEval' / task_id
    export_harbor(context.revision_dir, export, meta, ROOT)
    binding = inspect_export(export)
    task = {**meta, 'task_directory': str(export), 'harbor_export_binding': binding,
            'local_controls': actual, 'execution_budget': budget,
            'timeout_seconds': 10800, 'tool_time_policy': POLICY_V2}
    manifest = {'schema_version': 1, 'kind': 'prequality_development_probe',
        'source_kind': 'prequality_development_probe', 'frozen_at': utcnow(),
        'selected_task_ids': [task_id], 'tasks': [task], 'execution_budget': budget,
        'source_manifest': ref(output / 'verified_source/seed_manifest.json'),
        'planning_origin': ref(cache / 'adapter_plan.json'), 'local_controls': actual,
        'root_impact_validation': 'shadow_roots', 'expected_change_count': context.data['delta']['expected_change_count'],
        'root_count': len(plan['edits']), 'family_adapter': plan['family_adapter'],
        'quality_status': 'Actual source proof, whole-family donor audit, root activity and five local controls only; diagnosis, public recovery and real Harbor controls pending.',
        'qualified': False, 'task_count': 0, 'model_evaluation_performed': False, 'llm_calls': 0}
    write(output / 'probe_manifest.json', manifest)
    certificate_path = context.revision_dir / 'private/shadow_roots_certificate.json'
    certificate = json.loads(certificate_path.read_text())
    policy_sha = hashlib.sha256(json.dumps(policy, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    write(output / 'adapter_probe_receipt.json', {
        'schema_version': 1, 'passed': True, 'qualified': False,
        'scope': 'Actual construction, complete shadow activity, full D and five local controls; no model, final quality or actual Harbor control certification.',
        'baseline': ref(baseline), 'source_manifest': ref(output / 'verified_source/seed_manifest.json'),
        'policy': policy, 'policy_canonical_sha256': policy_sha,
        'adapter_implementation': ref(ROOT / 'src/sheets_factory/task_adapters/lease_family.py'),
        'source_build_recipe_snapshot': ref(output / 'frozen_adapter_recipe/manifest.json'),
        'actual_plan': ref(context.revision_dir / 'private/plan.json'),
        'shadow_certificate': ref(certificate_path), 'shadow_passed': certificate['passed'],
        'actual_shadow_LO_executions': certificate['actual_LO_execution_count'],
        'root_count': len(plan['edits']), 'expected_delta': ref(context.revision_dir / 'private/expected_delta.json'),
        'expected_change_count': context.data['delta']['expected_change_count'],
        'local_control_receipt': ref(context.revision_dir / 'private/local_controls.json'),
        'local_controls': actual, 'public_input': ref(context.revision_dir / 'public/input.xlsx'),
        'public_instruction': ref(context.revision_dir / 'public/instruction.md'),
        'goal': ref(context.revision_dir / 'private/goal.xlsx'),
        'revision_hash': context.data['revision_hash'], 'probe_manifest': ref(output / 'probe_manifest.json'),
        'llm_calls': 0, 'difficulty_measured': False})
    audit.task(task_id, status='probe_prepared', revision_hash=context.data['revision_hash'])
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-manifest', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--policy', type=Path, default=ROOT / 'config/task_adapters/lease_family_v1.json')
    parser.add_argument('--prepare-probe', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    temporary = output / 'temporary'
    temporary.mkdir()
    if Path(os.environ.get('TMPDIR', '')).absolute() != temporary:
        raise ValueError('Launch with TMPDIR explicitly set to OUTPUT/temporary')
    tempfile.tempdir = None
    policy = json.loads(args.policy.read_text())
    audit = AuditStore(output, {'id': output.name, 'kind': 'donor_complete_lease_prototype',
        'status': 'source_validation', 'target_count': 1, 'qualified': 0, 'llm_calls_permitted': False})
    panel = DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=0)
    url = panel.start()
    audit.update_run(producer_active=True, producer_pid=os.getpid(), dashboard_url=url)
    write(output / 'dashboard.json', {'url': url, 'run_id': output.name})
    recipe = {str(p): sha(p) for p in (Path(__file__), args.policy,
        ROOT / 'src/sheets_factory/task_adapters/lease_family.py',
        ROOT / 'src/sheets_factory/task_adapters/presentation_source.py')}
    write(output / 'recipe_start.json', recipe)
    snapshot = output / 'frozen_adapter_recipe'
    snapshot.mkdir()
    snapshot_refs = {}
    for name, expected in recipe.items():
        original = Path(name)
        if sha(original) != expected:
            raise ValueError('Adapter recipe changed before source snapshot')
        copied = snapshot / original.name
        shutil.copy2(original, copied)
        snapshot_refs[name] = ref(copied)
    write(snapshot / 'manifest.json', snapshot_refs)
    print(json.dumps({'output': str(output), 'dashboard_url': url, 'pid': os.getpid(), 'temporary_directory': str(temporary)}), flush=True)
    start = time.monotonic()
    try:
        engine = ObservedEngine(ROOT, IMAGE, 300)
        engine.audit = audit
        source = build_presentation_source(args.source_manifest, output / 'verified_source',
                                          policy=policy, project_root=ROOT, engine=engine)
        audit.update_run(status='source_verified_planning')
        plan = propose_debugging_task(source['local_path'], policy)
        write(output / 'proposed_plan.json', plan)
        audit.emit('adapter.family_planned', **plan['family_adapter'])
        if args.prepare_probe:
            audit.update_run(status='task_construction')
            prepare_probe(source, output, policy, audit, engine)
        if any(sha(p) != h for p, h in recipe.items()):
            raise ValueError('Prototype adapter recipe changed during execution')
        audit.update_run(status='probe_prepared' if args.prepare_probe else 'source_verified_plan_only')
        print(json.dumps({'source_manifest': str(output / 'verified_source/seed_manifest.json'),
                          'root_count': len(plan['edits']), 'probe_prepared': args.prepare_probe}), flush=True)
    except BaseException as error:
        write(output / 'prototype_rejection.json', {'type': type(error).__name__, 'reason': str(error),
                                                   'qualified': False, 'task_count': 0})
        audit.update_run(status='rejected', error=str(error))
        raise
    finally:
        audit.update_run(producer_active=False, finished_at=utcnow(), elapsed_seconds=time.monotonic()-start)
        audit.export()
        panel.stop()


if __name__ == '__main__':
    main()

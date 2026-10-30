#!/usr/bin/env python3
"""Prepare a bounded, instruction-only Q02 capital reporting-schema repair."""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import inspect
import json
from pathlib import Path
import subprocess
import sys
import time
import textwrap

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import yaml

from sheets_factory.task_adapters import capital_public_schema as policy
from sheets_factory.task_adapters.public_workbook_scope import checked_bytes, read, reference, require, write_new
from sheets_factory.reporting import read_run
from sheets_factory.resume import PROTECTED_BUDGETS, assert_resume_allowed, plan_external_repairs, prepare_resume
from sheets_factory.checkers import DiagnosisRunner
from sheets_factory.core.node import TaskRejected
from sheets_factory.pipelines.factory import FactoryPipeline, diagnostic_action

_spec = importlib.util.spec_from_file_location('_capital_schema_original_phase', ROOT / 'scripts/run_capital_allocation_quality.py')
phase = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(phase)
REGISTRY = ROOT / 'config/task_adapters/capital_public_schema_nodes.yaml'
KIND = 'prepared_capital_public_schema_Q02_continuation'
FORENSIC_SHA = '466378e21ec49ede3756582da79fc185db11fcb88366d90042be247e10fe736f'
COMPLETION_SHA = 'be2d7bc7cafbcfb1439a8c7360dd3f7e824145251dbfd22759b9286bbff2eff1'
DISPLAY_TITLE = 'Capital allocation common-plan forecast'


def validate_controller_copy():
    """Compare syntax only; never compile or mutate the original controller."""
    before = ast.parse(textwrap.dedent(inspect.getsource(FactoryPipeline._execute_context)))
    after = ast.parse(textwrap.dedent(inspect.getsource(CapitalSchemaFactory._execute_context)))
    needle = ast.dump(ast.parse("context.data['plan']['title']", mode='eval').body)
    replacement = ast.parse("context.data['plan'].get('title', DISPLAY_TITLE)", mode='eval').body
    class OneDisplayLookup(ast.NodeTransformer):
        count = 0
        def visit_Subscript(self, node):
            if ast.dump(node) == needle:
                self.count += 1
                return deepcopy(replacement)
            return self.generic_visit(node)
    transform = OneDisplayLookup(); before = transform.visit(before)
    require(transform.count == 1 and ast.dump(before) == ast.dump(after),
            'The continuation controller may differ only in its display-title fallback')


class CapitalSchemaFactory(phase.admission.CapitalAllocationFactory):
    def __init__(self, *args, **kwargs):
        validate_controller_copy()
        super().__init__(*args, **kwargs)

    def _execute_context(self, context, phase='revision', evidence_rounds=0, infrastructure_retries=0):
        max_steps = int(self.config['run']['max_steps'])
        while True:
            self._checkpoint()
            context.data.pop('construction_error', None)
            try:
                if phase == 'revision':
                    self._claim_targets(context)
                    context.data.pop('diagnosis', None)
                self.run_phase(context, phase)
            except TaskRejected as exc:
                self._checkpoint()
                context.data['construction_error'] = str(exc)
                context.data['diagnosis'] = self._construction_report(context, exc)
            report = context.data.get('diagnosis')
            self._checkpoint()
            if report is None:
                raise TaskRejected('UNRESOLVED: pipeline phase did not produce a diagnosis')
            action, routes = diagnostic_action(report)
            self.audit.emit('task.route', task_id=context.task_id, revision=context.revision,
                            action=action, issue_ids=[route['issue_id'] for route in routes])
            if action == 'export':
                self.run_phase(context, 'export')
                self.audit.task(context.task_id, status='ready', node='harbor_pending',
                                title=context.data['plan'].get('title', DISPLAY_TITLE), revision=context.revision,
                                export_dir=str(context.data['export_dir']),
                                independent_recovery=context.data.get('recovery', {}).get('verified') is True,
                                reference_validation_method=self.reference_validation_method, error=None,
                                harbor_controls=None)
                self.audit.emit('task.ready', task_id=context.task_id, mode=context.mode, revision=context.revision)
                break
            if action == 'infrastructure_retry':
                budget = self.config['run'].get('infrastructure_retries_per_stage', 2)
                if infrastructure_retries >= budget:
                    raise TaskRejected('INFRA_FAILED: same-revision infrastructure retry budget exhausted')
                infrastructure_retries += 1
                issues = {issue['issue_id']: issue for issue in report.get('issues', [])}
                diagnosis_only = bool(routes) and all(
                    issues.get(route['issue_id'], {}).get('fault_stage') == 'diagnose' for route in routes)
                phase = 'diagnosis_retry' if diagnosis_only else 'infrastructure_retry'
            elif action == 'evidence':
                budget = self.config['run'].get('max_evidence_rounds_per_revision', 2)
                if evidence_rounds >= budget:
                    raise TaskRejected('UNRESOLVED: same-revision evidence budget exhausted')
                evidence_rounds += 1
                phase = 'evidence'
            else:
                if context.revision >= max_steps:
                    raise TaskRejected('EXHAUSTED: content repair budget exhausted')
                self._apply_repair(context, routes)
                evidence_rounds = infrastructure_retries = 0
                phase = 'revision'
                self.audit.emit('task.revised', task_id=context.task_id, next_revision=context.revision)
            self.audit.task(context.task_id, evidence_rounds=evidence_rounds,
                            infrastructure_retries=infrastructure_retries, content_repairs=context.revision)


def collect(value, result):
    if isinstance(value, dict):
        if 'path' in value and 'sha256' in value:
            actual = reference(value['path'])
            require(actual['sha256'] == value['sha256']
                    and ('bytes' not in value or actual['bytes'] == value['bytes']), 'A schema-review artifact changed')
            require(actual['path'] not in result or result[actual['path']] == actual['sha256'], 'Conflicting review artifacts')
            result[actual['path']] = actual['sha256']
        for child in value.values(): collect(child, result)
    elif isinstance(value, list):
        for child in value: collect(child, result)


def validate_forensic_basis(forensic, completion, *, task_id, revision, revision_hash, input_ref, goal_ref, instruction_ref):
    require(forensic['sha256'] == FORENSIC_SHA and completion['sha256'] == COMPLETION_SHA,
            'Only the reviewed actual machine forensic and completion receipts authorize this repair')
    first, final = read(forensic), read(completion)
    require(first.get('kind') == 'capital_K01_first_development_independent_readonly_forensic'
            and type(first.get('version')) is int and first['version'] == 1
            and first.get('same_plan') is True and first.get('prior_proof_best_plan_matches') is True
            and first.get('annual_financial_mismatches') == [] and first.get('selected_project_mismatches') == [],
            'The actual independent machine comparison basis differs')
    require(final.get('kind') == 'capital_K01_first_development_forensic_completion'
            and type(final.get('version')) is int and final['version'] == 1
            and final.get('original_forensic_receipt') == forensic
            and final.get('public_summary_roles_not_labelled') is True
            and final.get('public_unweighted_candidate_project_convention_not_explicit') is True
            and final.get('public_contract_clarity_blocks_release_difficulty_claim') is True
            and final.get('tax_actual_mismatches') == [] and final.get('tax_gold_mismatches') == []
            and final.get('filled_outside_authorized_targets') == [], 'The completed public-schema finding is absent')
    for item in (first, final):
        require(item.get('frozen_files_modified') is False
                and all(type(item.get(key)) is int and item[key] == 0 for key in ('new_model_calls', 'new_LO_calls')),
                'This authorization requires the actual read-only forensic evidence')
    selection = read(first['selection_manifest'])
    require(len(selection.get('tasks', [])) == 1, 'The actual first development selection changed')
    task = selection['tasks'][0]
    require(task.get('task_id') == task_id and type(task.get('revision')) is int and task['revision'] == revision
            and task.get('revision_hash') == revision_hash and task.get('source_id') == goal_ref['sha256'],
            'No forensic finding transfers to another task or public revision')
    for actual, declared in ((input_ref, first['original_files']['input']),
                             (goal_ref, first['original_files']['goal']), (instruction_ref, first['public_instruction'])):
        checked_bytes(declared)
        require(actual['sha256'] == declared['sha256'] and actual['bytes'] == declared['bytes'],
                'The reviewed public workbook, instruction or reference differs')
    artifacts = {}; collect([forensic, completion, first, final], artifacts)
    return artifacts


def issue_for(task_id, revision, revision_hash, forensic, completion, instruction):
    return {'issue_id': task_id + '-Q02-PUBLIC-REPORTING-SCHEMA', 'task_id': task_id,
        'revision': revision, 'revision_hash': revision_hash, 'problem_id': 'Q02', 'route_id': 'R02',
        'certainty': 'confirmed', 'severity': 'blocker', 'attribution': 'task_defect',
        'claim': 'The public contract omits Summary column/total roles and the unweighted, all-candidate Projects reporting basis. Clarify these output semantics without changing financial policies, source, reference, targets or grader.',
        'evidence': [forensic, completion, instruction], 'depends_on_issue_ids': []}


def prepare(run, forensic_receipt, forensic_completion, output):
    run, output = Path(run).absolute(), Path(output).absolute()
    require(run == run.resolve() and output == output.resolve() and not output.exists(), 'Use a fresh non-symlink continuation directory')
    validate_controller_copy()
    snapshot = read_run(run)
    assert_resume_allowed(run, snapshot)
    original, config, proof = phase.validate_prepared(run)
    require(config['run']['targets'] == {'financial_modeling': 1, 'debugging': 0}
            and len(snapshot['tasks']) == 1, 'Only the original one-source capital pilot is supported')
    task = snapshot['tasks'][0]; task_id, revision = task['id'], task['revision']
    require(type(revision) is int and revision < config['run']['max_steps']
            and task['source_id'] == proof['workbook']['sha256'], 'The normal content-repair budget or original source changed')
    diagnoses = [n for n in snapshot['nodes'] if n.get('task_id') == task_id
                 and n.get('revision') == revision and n.get('node') == 'diagnose']
    require(diagnoses and diagnoses[-1].get('status') == 'completed', 'Wait for the actual current diagnosis to finish; do not synthesize twelve findings')
    directory = run / 'tasks' / task_id / 'revisions' / f'{revision:03d}'
    artifacts = {key: reference(path) for key, path in {
        'input': directory / 'public/input.xlsx', 'instruction': directory / 'public/instruction.md',
        'goal': directory / 'private/goal.xlsx', 'plan': directory / 'private/plan.json',
        'diagnosis': directory / 'private/diagnosis.json',
        'baseline': run / 'sources' / task['source_id'][:12] / 'baseline.xlsx'}.items()}
    revision_hash = hashlib.sha256(checked_bytes(artifacts['input']) + checked_bytes(artifacts['instruction'])).hexdigest()
    require(artifacts['goal']['sha256'] == artifacts['baseline']['sha256'] == task['source_id']
            and read(artifacts['diagnosis']).get('task_revision_hash') == revision_hash,
            'The numeric reference, baseline or actual diagnosis belongs to another public revision')
    forensic, completion = reference(forensic_receipt), reference(forensic_completion)
    safeguards = validate_forensic_basis(forensic, completion, task_id=task_id, revision=revision,
        revision_hash=revision_hash, input_ref=artifacts['input'], goal_ref=artifacts['goal'], instruction_ref=artifacts['instruction'])
    seeds = read(original['prepared_seed_manifest'])['selected']
    require(len(seeds) == 1 and seeds[0]['sha256'] == task['source_id'], 'The original admitted seed changed')
    evidence = seeds[0]['finance_evidence']
    require(evidence['audited_source_binding'] == proof, 'Complete original financial evidence is required')
    checker_plan = DiagnosisRunner(ROOT).resolve(config)
    require(set(checker_plan['enabled_check_ids']) == {f'Q{i:02d}' for i in range(1, 13)}, 'All twelve normal checks remain required')
    base_registry = reference(config['pipeline']['node_registry'])
    nodes = policy.registry_nodes(yaml.safe_load(checked_bytes(base_registry))['nodes'])
    require(yaml.safe_load(REGISTRY.read_text())['nodes'] == nodes, 'The new registry may change only the exact repair route')
    old_plan = read(artifacts['plan']); policy.append_schema(old_plan)
    issue = issue_for(task_id, revision, revision_hash, forensic, completion, artifacts['instruction'])
    output.mkdir(parents=True)
    program = write_new(output / 'program_review.json', {'kind': 'numbered_actual_capital_public_schema_review',
        'task_id': task_id, 'revision': revision, 'revision_hash': revision_hash, 'issues': [issue],
        'actual_machine_forensic': forensic, 'actual_forensic_completion': completion,
        'LLM_assessments_synthesized': False, 'old_quality_findings_overwritten': False,
        'quality_or_difficulty_certified': False})
    # Exercise the actual existing route/issue/revision validator in plan-only
    # mode, without calling prepare_resume or changing the old audit database.
    proposed_repairs = plan_external_repairs(run, snapshot, config, [task_id], [program['path']])
    require(len(proposed_repairs) == 1 and proposed_repairs[0]['revision'] == revision,
            'The normal finite external-repair controller rejected this exact task')
    manifest = write_new(output / 'policy_manifest.json', {'kind': policy.KIND, 'version': policy.VERSION,
        'clause': policy.CLAUSE, 'sources': {task['source_id']: {'source': proof['workbook'],
            'financial_evidence': evidence}}, 'tasks': {task_id: {'source_sha256': task['source_id'],
            'revision': revision, 'revision_hash': revision_hash, **artifacts,
            'program_review': program, 'authorized_issue_ids': [issue['issue_id']]}},
        'forensic_receipts': [forensic, completion], 'quality_or_difficulty_certified': False})
    patch = write_new(output / 'config_patch.json', {'pipeline': {**config['pipeline'], 'node_registry': str(REGISTRY)},
        policy.SETTING: policy.setting(manifest)})
    proof_ref = write_new(output / 'source_admission.json', proof)
    before = reference(run / 'resolved_config.yaml')
    (output / 'resolved_config_before.yaml').write_bytes(checked_bytes(before))
    collect([artifacts, program, manifest, patch, proof_ref, original['source_manifest'], base_registry], safeguards)
    phase.bind_transitive(proof, safeguards)
    recipe = {**original['recipe_sha256'], **{str(path.resolve()): reference(path)['sha256'] for path in
        (Path(__file__), Path(policy.__file__), REGISTRY)}}
    phase.verify_files(recipe); phase.verify_files(safeguards)
    require(reference(run / 'resolved_config.yaml') == before, 'The terminal configuration changed during preparation')
    return write_new(output / 'preflight_manifest.json', {'kind': KIND, 'version': 1,
        'prepared_at': datetime.now(timezone.utc).isoformat(), 'run_directory': str(run),
        'original_preflight': reference(run / 'preflight_manifest.json'), 'resolved_config_before': before,
        'archived_config_before': reference(output / 'resolved_config_before.yaml'),
        'source_admission': proof_ref, 'policy_manifest': manifest, 'config_patch': patch,
        'review_files': [program], 'repair_task_ids': [task_id], 'before_revision': revision,
        'before_revision_hash': revision_hash, 'safeguard_sha256': safeguards, 'recipe_sha256': recipe,
        'targets': deepcopy(config['run']['targets']), 'agents': deepcopy(config['agents']),
        'diagnosis_configuration': deepcopy(config['diagnosis']), 'recovery_configuration': deepcopy(config['recovery']),
        'protected_budgets': {key: config['run'].get(key) for key in PROTECTED_BUDGETS},
        'changed_plan_fields': ['public_instruction'], 'target_count': 19049,
        'old_run_modified_by_preparation': False, 'old_scores_and_quality_reports_unchanged': True,
        'actual_models': 0, 'actual_LO_calls': 0, 'prepare_resume_called': False,
        'qualified': False, 'task_count': 0})


def validate_prepared(output):
    validate_controller_copy()
    output = Path(output).absolute(); frozen = read(reference(output / 'preflight_manifest.json'))
    require(frozen.get('kind') == KIND and type(frozen.get('version')) is int and frozen['version'] == 1
            and frozen.get('changed_plan_fields') == ['public_instruction'] and frozen.get('target_count') == 19049,
            'Unexpected bounded capital public-schema preparation')
    for key in ('original_preflight', 'resolved_config_before', 'archived_config_before', 'source_admission', 'policy_manifest', 'config_patch'):
        checked_bytes(frozen[key])
    phase.verify_files(frozen['recipe_sha256']); phase.verify_files(frozen['safeguard_sha256'])
    manifest = read(frozen['policy_manifest'])
    require(type(manifest.get('version')) is int and manifest['version'] == policy.VERSION
            and manifest.get('kind') == policy.KIND and manifest.get('clause') == policy.CLAUSE,
            'The exact reviewed public wording changed')
    config = yaml.safe_load(checked_bytes(frozen['resolved_config_before']))
    expected = {'pipeline': {**config['pipeline'], 'node_registry': str(REGISTRY)},
        policy.SETTING: policy.setting(frozen['policy_manifest'])}
    require(read(frozen['config_patch']) == expected, 'The continuation patch changed protected configuration')
    return frozen


def execute(output, *, port=0):
    output = Path(output).absolute(); frozen = validate_prepared(output)
    run = Path(frozen['run_directory']); snapshot = read_run(run)
    assert_resume_allowed(run, snapshot)
    require({t['id']: t['revision'] for t in snapshot['tasks']} == {frozen['repair_task_ids'][0]: frozen['before_revision']},
            'The actual terminal task revision changed after preparation')
    settings, legacy = phase.cohort.prepared_host_runtime(run)
    with phase.cohort.host_temporary_environment(run, settings, legacy_preparation=legacy) as host:
        code = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        session = prepare_resume(run, config_patch=read(frozen['config_patch']),
            repair_tasks=frozen['repair_task_ids'], review_files=[record['path'] for record in frozen['review_files']],
            current_code_revision=code, reason='Resolve the actual confirmed Q02 public reporting-schema omission through a new normal revision; preserve all financial inputs, reference, targets, agents and budgets')
        audit, config, lease = session.audit, session.config, session.lease
        server, status, started = None, 1, time.monotonic()
        previous = audit.run.get('previous_wall_seconds')
        if previous is None: previous = audit.run.get('wall_seconds', 0) or 0
        try:
            require(config['run']['targets'] == frozen['targets'] and config['agents'] == frozen['agents']
                    and config['diagnosis'] == frozen['diagnosis_configuration']
                    and config['recovery'] == frozen['recovery_configuration']
                    and all(config['run'].get(key) == value for key, value in frozen['protected_budgets'].items()),
                    'The normal agents, quotas, quality routes or finite budgets changed')
            cid = config['run']['continuation_id']; private = run / 'private/resume'
            addendum = write_new(run / 'runtime_supplements' / ('capital_public_schema_' + cid + '.json'), {
                'kind': 'capital_public_schema_normal_continuation', 'preparation': reference(output / 'preflight_manifest.json'),
                'config_before': reference(private / f'resolved_config_before_{cid}.yaml'),
                'config_after': reference(private / f'resolved_config_after_{cid}.yaml'),
                'current_config': reference(run / 'resolved_config.yaml'), 'clause': policy.CLAUSE,
                'old_preparation_configuration_hash_is_historical': True, 'old_scores_unchanged': True,
                'new_revision_consumes_normal_content_repair_budget': True,
                'all_five_controls_public_recovery_all12_diagnostics_actual_Harbor_required': True,
                'quality_or_difficulty_certified': False})
            server = phase.cohort.DashboardServer(audit.snapshot, audit.events, host='127.0.0.1', port=port)
            url = server.start(); audit.update_run(dashboard_url=url, host_runtime_receipt=host,
                host_temporary_directory=host['temporary_directory'])
            llm = phase.cohort.CohortCodex(ROOT, run, audit, config['agents']); llm._credentials()
            engine = phase.cohort.LibreOfficeEngine(ROOT, phase.cohort.IMAGE, config['engine']['timeout_seconds'])
            require(engine.metadata()['image_id'] == phase.admission.IMAGE_ID, 'The continuation runtime differs')
            print(json.dumps({'run_dir': str(run), 'dashboard_url': url, 'phase_addendum': addendum}), flush=True)
            status = 0 if CapitalSchemaFactory(config, audit, llm, engine,
                admitted_proof=read(frozen['source_admission'])).run() else 2
            phase.verify_files(frozen['recipe_sha256']); phase.verify_files(frozen['safeguard_sha256'])
            return status
        finally:
            phase.finalization.finalize_execution(audit, server, session, lease,
                phase_wall=round(time.monotonic() - started, 3), previous_wall=previous, status=status)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('run-directory', 'forensic-receipt', 'forensic-completion', 'output', 'prepared'):
        parser.add_argument('--' + name, type=Path)
    parser.add_argument('--run', action='store_true'); parser.add_argument('--port', type=int, default=0)
    args = parser.parse_args(argv)
    if args.prepared:
        require(not any((args.run_directory, args.forensic_receipt, args.forensic_completion, args.output)), 'Choose one frozen preparation')
        if args.run: return execute(args.prepared, port=args.port)
        result = validate_prepared(args.prepared)
    else:
        require(not args.run and all((args.run_directory, args.forensic_receipt, args.forensic_completion, args.output)),
                'Prepare a terminal, reviewed task before explicit --prepared --run')
        result = prepare(args.run_directory, args.forensic_receipt, args.forensic_completion, args.output)
    print(json.dumps({'preparation': result, 'models_started': 0, 'LO_calls': 0}, indent=2)); return 0


if __name__ == '__main__': raise SystemExit(main())

#!/usr/bin/env python3
"""Append a fixed P01 evidence certificate; never rerun or mutate the old run."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from types import FunctionType, SimpleNamespace

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
from sheets_factory import reporting
from sheets_factory.checkers import DiagnosisRunner
from sheets_factory.evaluation.harbor import matched_controls
from sheets_factory.evaluation.resource_harbor import inspect_resource_export
from sheets_factory.evaluation.resource_observer import validate_trial_observations
from sheets_factory.pipelines.linear_capital_quality import reference, require
from sheets_factory.task_adapters import linear_capital_scaled_reference_review as reference_nodes
from sheets_factory.task_adapters import reference_receipt_diagnosis

RUN = ROOT/'outputs/research/linear_scaled_P01_reference_receipt_normal_prepared_20261031T195500Z/prepared'
TASKS = ('fm-08f2adb105de', 'dbg-08f2adb105de')
BATCH = '2ca1afeb342b'
PROPOSAL = {'path': str(ROOT/'outputs/research/P01_normal_append_only_recovery_proposal_20261101T001007Z/prospective.json'),
    'sha256': '7902bcf57087da4f2b202ce17801076f19abce1b6f7b9341715d6f33178fda47', 'bytes': 5881}
STRICT_ENTRY = ROOT/'scripts/run_operating_reports_200_quality_revision2.py'
STRICT_ENTRY_SHA = 'bbcdbe4d4aee43fa7897c744fa24218c499a41c4eb4971b0d83b1da79ea8670b'
KIND = 'prepared_fixed_P01_normal_append_only_evidence_recovery'


def write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as handle:
        json.dump(value, handle, indent=2, ensure_ascii=False); handle.write('\n')
    return reference(path)


def _proposal():
    require(reference(PROPOSAL['path']) == PROPOSAL, 'The approved fixed-run recovery proposal changed')
    value = json.loads(Path(PROPOSAL['path']).read_text())
    require(value['original_run'] == str(RUN), 'Only the original fixed P01 normal run may be considered')
    return value


def strict_entry():
    require(reference(STRICT_ENTRY)['sha256'] == STRICT_ENTRY_SHA, 'The reviewed strict trial-identity helper changed')
    spec = importlib.util.spec_from_file_location('_P01_normal_recovery_strict_identity', STRICT_ENTRY)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def recipes():
    entry = strict_entry()
    paths = {str(Path(__file__)), str(STRICT_ENTRY), str(Path(entry.nodes.__file__)), *entry.nodes.ANCESTORS,
        str(entry.FROZEN_ENTRY), str(entry.UPSTREAM), str(Path(entry.pipeline.base.__file__)), str(Path(entry.nodes.base.__file__)),
        reporting.__file__, reference_nodes.__file__, reference_receipt_diagnosis.__file__,
        *reference_receipt_diagnosis.DEPENDENCIES, str(ROOT/'config/checkers.yaml'), str(ROOT/'config/routes.yaml'),
        str(ROOT/'src/sheets_factory/evaluation/resource_observer.py'),
        str(ROOT/'src/sheets_factory/evaluation/resource_harbor.py'),
        str(ROOT/'src/sheets_factory/evaluation/harbor.py'),
        str(ROOT/'src/sheets_factory/evaluation/resource_streaming_verifier.py'),
        str(ROOT/'src/sheets_factory/workbook/resource_engine.py'),
        str(entry.pipeline.PROFILE)}
    return {path: reference(path) for path in sorted(paths)}


class Access:
    """Record complete bytes of interpreted files and reject changes on exit."""
    def __init__(self):
        self.records = {}; self.roles = {}

    def checked(self, record, role):
        require(reference(record['path']) == record, 'A retained recovery artifact changed')
        self.record(Path(record['path']), record, role)
        return Path(record['path'])

    def record(self, path, record, role):
        key = str(Path(path).absolute())
        require(key not in self.records or self.records[key] == record, 'One read artifact changed during validation')
        self.records[key] = deepcopy(record); self.roles.setdefault(key, set()).add(role)

    def file(self, path, role):
        row = reference(path); self.record(path, row, role); return row

    def read(self, path, role):
        before = self.file(path, role); raw = Path(path).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == before['sha256'] and len(raw) == before['bytes'],
            'A recovery artifact changed while reading')
        return raw

    def json(self, path, role):
        return json.loads(self.read(path, role))

    def guard(self):
        for record in self.records.values(): self.checked(record, 'unchanged_at_exit')

    def inventory(self):
        return [{'reference': self.records[path], 'uses': sorted(self.roles[path])} for path in sorted(self.records)]


def _output(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_relative_to(ROOT/'outputs/research')
        and not path.is_relative_to(RUN), 'Use a fresh separate research directory; never write into the original run')
    return path


def prepare(output):
    out = _output(output); require(not out.exists(), 'Preserve every previous recovery preparation')
    proposal = _proposal(); access = Access(); access.checked(PROPOSAL, 'approved_prospective')
    for row in proposal['anchors'].values(): access.checked(row, 'frozen_original_anchor')
    access.checked(proposal['actual_resource_diagnostic'], 'retained_resource_diagnostic')
    frozen = {'kind': KIND, 'version': 1, 'proposal': deepcopy(PROPOSAL), 'original_run': str(RUN),
        'task_ids': list(TASKS), 'batch_id': BATCH, 'anchors': deepcopy(proposal['anchors']),
        'resource_diagnostic': deepcopy(proposal['actual_resource_diagnostic']), 'recipe': recipes(),
        'prepared_at': datetime.now(timezone.utc).isoformat(), 'preparation_access_inventory': access.inventory(),
        'permitted_new_calls': {'model': 0, 'LO': 0, 'Harbor': 0, 'Docker': 0},
        'original_status_or_export_mutation_permitted': False, 'qualified': False, 'formal_release': False}
    access.guard(); out.mkdir(parents=True)
    return write(out/'prospective.json', frozen)


def validate_prepared(output):
    out = _output(output); frozen = json.loads((out/'prospective.json').read_text()); proposal = _proposal()
    require(frozen['kind'] == KIND and frozen['version'] == 1 and frozen['proposal'] == PROPOSAL
        and frozen['original_run'] == str(RUN) and frozen['task_ids'] == list(TASKS) and frozen['batch_id'] == BATCH
        and frozen['anchors'] == proposal['anchors'] and frozen['resource_diagnostic'] == proposal['actual_resource_diagnostic']
        and frozen['permitted_new_calls'] == {'model':0,'LO':0,'Harbor':0,'Docker':0}
        and frozen['original_status_or_export_mutation_permitted'] is frozen['qualified'] is frozen['formal_release'] is False,
        'The fixed-run scope or zero-call recovery contract changed')
    require(frozen['recipe'] == recipes(), 'The prospective recovery implementation changed')
    access = Access()
    access.checked(PROPOSAL, 'approved_prospective')
    for row in frozen['recipe'].values(): access.checked(row, 'causal_recovery_implementation')
    for row in frozen['anchors'].values(): access.checked(row, 'frozen_original_anchor')
    access.checked(frozen['resource_diagnostic'], 'retained_resource_diagnostic')
    return frozen, access


def _tasks(access):
    database = RUN/'run.sqlite'; access.file(database, 'original_authoritative_task_database')
    require(not database.with_name(database.name+'-wal').exists(), 'A stable closed original database is required')
    connection = sqlite3.connect(database.as_uri()+'?mode=ro&immutable=1', uri=True)
    try:
        rows = connection.execute('SELECT id,payload FROM tasks ORDER BY id').fetchall()
    finally: connection.close()
    require({key for key, _ in rows} == set(TASKS) and len(rows) == 2, 'The fixed original two-task inventory changed')
    tasks = [json.loads(raw) for key, raw in rows]
    require(all(task['id'] == key for task, (key, _) in zip(tasks, rows)), 'A database key differs from its task payload')
    return tasks


def _review(task, config, access):
    # The complete existing reporter body stays unchanged. Only its file reader
    # is wrapped to retain a precise read-access inventory.
    namespace = dict(vars(reporting))
    def read_file(path, base):
        raw = reporting._reference_file(path, base)
        row = {'path': str(Path(path).absolute()), 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        access.record(path, row, 'unchanged_reference_review_read')
        return raw
    namespace['_reference_file'] = read_file
    review = FunctionType(reporting._reference_review.__code__, namespace)(RUN, task)
    quality = reporting._quality_diagnosis(RUN, task)
    require(review['verified'] is True and quality['verified'] is True and quality['enabled_check_count'] == 12,
        'The original current all-twelve quality/reference evidence is incomplete')
    base = RUN/'tasks'/task['id']/'revisions/000'
    diagnosis = access.json(base/'private/diagnosis.json', 'current_all_twelve_diagnosis')
    plan = DiagnosisRunner(ROOT).resolve(config)
    require(diagnosis['check_plan_hash'] == plan['check_plan_hash'], 'The current checker plan differs from the original review')
    instruction = access.read(base/'public/instruction.md', 'current_public_instruction').decode()
    context = SimpleNamespace(task_id=task['id'], revision=0, config=config,
        data={'input':base/'public/input.xlsx','goal':base/'private/goal.xlsx', 'instruction':instruction,
              'revision_hash':diagnosis['task_revision_hash'],'diagnosis':diagnosis})
    supported = reference_nodes.validate_reference_export(context)
    return {'quality':quality,'reference_review':review,'supported_export_review':supported,
        'states':{key:row['state'] for key,row in diagnosis['assessments'].items()}}, review['binding']


def _export(task, binding, batch, access):
    task_id = task['id']; staged = RUN/'harbor_batches'/BATCH/'SpreadsheetEval'/task_id
    quarantine = RUN/'quarantined_exports'/(task_id+'-resource-observation')
    require(not (RUN/'SpreadsheetEval'/task_id).exists(), 'The original quarantined export was moved or replaced')
    expected = task['historical_harbor_export_binding']
    require(inspect_resource_export(staged) == inspect_resource_export(quarantine) == expected
        and batch['export_bindings'][expected['task_name']] == expected
        and expected['revision'] == 0 and expected['revision_hash'] == binding['task_revision_hash'],
        'The original revision and immutable complete export binding differ')
    manifest = access.json(staged/'export_manifest.json', 'original_staged_export_manifest')
    names = set(manifest['files']) | {'export_manifest.json'}
    require(len(names) == 17, 'The original complete seventeen-file resource export is required')
    rows = []
    for name in sorted(names):
        left = access.file(staged/name, 'original_actual_staged_export')
        right = access.file(quarantine/name, 'unchanged_quarantined_export')
        require((left['sha256'],left['bytes']) == (right['sha256'],right['bytes']), 'The original staged and quarantined bytes differ')
        rows.append({'relative':name,'staged':left,'quarantined':right})
    revision = RUN/'tasks'/task_id/'revisions/000'
    for exported, original in [('environment/input.xlsx','public/input.xlsx'), ('tests/original_input.xlsx','public/input.xlsx'),
        ('solution/reference.xlsx','private/goal.xlsx'), ('tests/reference.xlsx','private/goal.xlsx'), ('instruction.md','public/instruction.md')]:
        left = access.file(staged/exported, 'reviewed_material_in_actual_export')
        right = access.file(revision/original, 'current_hash_bound_reviewed_material')
        require((left['sha256'],left['bytes']) == (right['sha256'],right['bytes']),
            'The actual exported input/goal/instruction differs from the currently reviewed revision')
    return staged, expected, rows


def _recover(frozen, access):
    diagnostic = access.json(frozen['resource_diagnostic']['path'], 'prior_readonly_resource_diagnostic')
    observer = diagnostic['original_resource_observer']; access.checked(observer, 'same_original_stopped_observer')
    session = access.json(observer['path'], 'same_original_stopped_observer')
    for key in ('observations','observation_errors'):
        for row in session[key]:
            require(Path(row['path']).is_relative_to(RUN/'resource_observations'), 'An original observation escaped its run')
            access.checked(row, 'original_resource_observer_'+key)
    gate = access.json(RUN/'normal_actual_control_resource_gate.json', 'sole_original_failed_resource_gate')
    require(gate['passed'] is False and gate['qualified_tasks_checked'] == 2
        and set(gate['infrastructure_task_ids']) == set(TASKS) and gate['observer'] == observer
        and len(gate['task_validations']) == 2,
        'Only the original two-task resource gate failure may be supplemented')
    failed_ids = []
    for row in gate['task_validations']:
        report = access.json(access.checked(row,'original_task_resource_gate'), 'original_task_resource_gate')
        require(report['passed'] is False and report['error'] == "'agent'" and report['trials'] == [] and report['observer'] == observer,
            'The original failure is not solely the known sparse-config agent KeyError')
        failed_ids.append(report['task_id'])
    require(set(failed_ids) == set(TASKS), 'A fixed original task failure is duplicated or missing')
    config = yaml.safe_load(access.read(RUN/'resolved_config.yaml', 'original_resolved_quality_configuration'))
    batch = access.json(RUN/'harbor_batches'/BATCH/'batch_manifest.json', 'original_exact_Harbor_batch')
    summary = access.json(RUN/'harbor_jobs'/BATCH/'control_summary.json', 'original_actual_control_summary')
    require(batch['complete'] is True and not batch['errors'] and set(batch['task_ids']) == set(TASKS)
        and batch['staging'] == str(RUN/'harbor_batches'/BATCH/'SpreadsheetEval')
        and batch['jobs_dir'] == str(RUN/'harbor_jobs'/BATCH), 'The original actual Harbor batch is incomplete')
    helper = strict_entry(); identity = helper._trial_agent_identity
    prior = {(row['task_name'],row['agent']):row for row in diagnostic['trials']}
    require(len(prior) == len(diagnostic['trials']) == 4, 'Exactly four original actual control trials are required')
    from dirhash import dirhash
    recovered = []
    for task in _tasks(access):
        require(task['status'] == 'infrastructure_failed' and task['node'] == 'actual_control_resources'
            and task['error'] == "'agent'" and task['revision'] == 0
            and task['harbor_controls'] is task['harbor_export_binding'] is None
            and task['harbor_summary_path'] == str(RUN/'harbor_jobs'/BATCH/'control_summary.json'),
            'The original task status or failure lineage changed')
        review, binding = _review(task,config,access)
        staged, export, files = _export(task,binding,batch,access)
        controls = task['historical_harbor_controls']; name = export['task_name']
        require(summary['per_task'][name] == controls and matched_controls(controls, task_name=name),
            'The original oracle/nop results are incomplete or belong to another task')
        trials = []
        for agent, reward in (('oracle',1),('nop',0)):
            entry = controls[agent]; prior_trial = prior[(name,agent)]
            result_ref, config_ref = prior_trial['original_result'], prior_trial['original_sparse_config']
            result_path = access.checked(result_ref,'original_actual_'+agent+'_result')
            access.checked(config_ref,'original_actual_'+agent+'_config')
            require(result_path == Path(entry['result_file']) and result_path.is_relative_to(RUN/'harbor_jobs'/BATCH)
                and Path(config_ref['path']) == result_path.with_name('config.json'), 'An original trial result/config binding changed')
            result = access.json(result_path,'original_actual_'+agent+'_result')
            thin = access.json(config_ref['path'],'original_actual_'+agent+'_config')
            require(identity(thin,result,config_ref['path'],staged,agent) == agent
                and result['task_name'] == name and result.get('exception_info') is None
                and type(result['verifier_result']['rewards']['reward']) in (int,float)
                and result['verifier_result']['rewards']['reward'] == reward
                and result['task_checksum'] == dirhash(staged,'sha256'), 'The original trial identity/reward/checksum differs')
            observed = validate_trial_observations(config_ref,result_ref,receipts=[observer],
                expected_profile=helper.pipeline.PROFILE, expected_task_directory=staged)
            require(observed.get('passed') is True and observed.get('complete') is True,
                'The original actual both-role resource/image evidence is incomplete')
            trials.append({'agent':agent,'original_config':config_ref,'original_result':result_ref,'resource_validation':observed})
        recovered.append({'task_id':task['id'],'original_status':task['status'],'review':review,
            'original_export_binding':export,'identical_original_exports':files,'same_original_trials':trials})
    access.guard()
    return {'kind':'fixed_P01_normal_append_only_evidence_recovery_certificate','version':1,'evidence_recovered':True,
        'original_run':str(RUN),'tasks':recovered,'read_only_access_inventory':access.inventory(),
        'new_calls':{'model':0,'LO':0,'Harbor':0,'Docker':0},'original_statuses_changed':False,
        'quarantined_exports_moved_or_copied':False,'raw_rewards_modified':False,'opaque_source_or_view_admission_created':False,
        'formal_release':False,'qualified':False}


def certify(output):
    out = _output(output); frozen, access = validate_prepared(out)
    require(not (out/'started.json').exists(), 'Preserve the first certificate validation and any failure')
    write(out/'started.json',{'kind':KIND,'prospective':reference(out/'prospective.json'),'new_calls':frozen['permitted_new_calls']})
    try:
        certificate = _recover(frozen,access)
        certificate['prospective'] = reference(out/'prospective.json')
        return write(out/'certificate.json',certificate)
    except BaseException as error:
        write(out/'failure.json',{'kind':KIND,'error_type':type(error).__name__,'read_only_access_inventory':access.inventory(),
            'new_calls':frozen['permitted_new_calls'],'qualified':False,'original_statuses_changed':False})
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path); parser.add_argument('--prepared',type=Path); parser.add_argument('--certify',action='store_true')
    args = parser.parse_args(argv)
    require((args.output is not None) != (args.prepared is not None), 'Select a fresh preparation or its frozen prepared directory')
    require(not args.certify or args.prepared is not None, 'Review the frozen prospective before separate certification')
    target = _output(args.output if args.output is not None else args.prepared)
    with strict_entry().admission_monitor(target,'P01_evidence_prepare' if args.output else 'P01_evidence_certify' if args.certify else 'P01_evidence_validate') as state:
        result = prepare(target) if args.output else certify(target) if args.certify else validate_prepared(target)[0]
        state['passed'] = True
    print(json.dumps(result)); return 0


if __name__ == '__main__': raise SystemExit(main())

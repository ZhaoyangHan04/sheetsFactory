"""Explicit resource-task publication adapter; no execution or score migration.

The existing publisher supplies its original quality, control, confidentiality,
timing and atomic-copy gates. This adapter supplies only the resource contract,
family-specific witnesses and the prospectively frozen mapping to source runs.
It requires the source checkout and original evidence; it makes no portability
claim for external evidence paths. The published oracle itself is standalone.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from types import SimpleNamespace

import yaml

from . import resource_frontier as runner
from .resource_harbor import inspect_resource_export
from .streaming_delta import compare_workbooks
from ..reporting import read_run

ROOT = Path(__file__).resolve().parents[3]
KIND = 'frozen_resource_quality_cohort_for_fresh_confirmation'
MIN_PER_MODE = 10
MODES = ('financial_modeling', 'debugging')
BUDGET = {'version': 1, 'elapsed_policy': 'operational_guard',
          'elapsed_guard_seconds': 14400, 'tool_budget_seconds': 1800}
IMMUTABLE_IMAGE = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
CONTROL_REWARDS = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
STANDARD_BINDING_KEYS = frozenset({'task_id', 'task_name', 'revision', 'revision_hash', 'export_manifest_sha256'})
RECIPE_FILES = (
    'scripts/publish_resource_dataset.py', 'scripts/package_release.py', 'scripts/publish_dataset.py',
    'scripts/prepare_resource_development_probe.py',
    'src/sheets_factory/evaluation/resource_publication.py',
    'src/sheets_factory/evaluation/resource_frontier.py', 'src/sheets_factory/evaluation/frontier.py',
    'src/sheets_factory/evaluation/resource_observer.py', 'src/sheets_factory/evaluation/resource_harbor.py',
    'src/sheets_factory/evaluation/resource_streaming_verifier.py', 'src/sheets_factory/evaluation/streaming_verifier.py',
    'src/sheets_factory/evaluation/streaming_delta.py', 'src/sheets_factory/evaluation/tool_time.py',
    'src/sheets_factory/evaluation/tool_time_bounds.py', 'src/sheets_factory/evaluation/budget.py')


def publication_recipe(root=ROOT):
    return {name: reference(Path(root) / name) for name in RECIPE_FILES}


class ResourcePublicationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise ResourcePublicationError(message)


def reference(path):
    """Hash complete regular files with bounded memory and reject concurrent edits."""
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file(), 'Publication evidence must be a real regular file')
    before = path.stat(); digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024**2), b''):
            digest.update(block)
    after = path.stat()
    fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
    require(all(getattr(before, field) == getattr(after, field) for field in fields),
            'Publication evidence changed while it was hashed')
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': after.st_size}


def read(path):
    return json.loads(Path(path).read_bytes())


def checked(record):
    actual = reference(record['path'])
    require(actual['sha256'] == record.get('sha256')
            and ('bytes' not in record or actual['bytes'] == record['bytes']), 'Publication receipt changed')
    return read(actual['path'])


def support(root, name):
    location = root / 'scripts' / name
    spec = importlib.util.spec_from_file_location('_resource_publication_' + location.stem, location)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def _stamp(value):
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(stamp.tzinfo is not None, 'Publication cohort timestamps must include a timezone')
    return stamp


def audit_binding_matches(complete, recorded):
    """The normal H node records five fields; its manifest SHA binds all 17 files.

    This accepts exactly that existing schema or the complete resource schema.
    It never accepts an arbitrary subset. Resource inspection still verifies the
    entire contract and all bytes before this compatibility check is reached.
    """
    if not isinstance(complete, dict) or set(complete) != STANDARD_BINDING_KEYS | {'required_controls', 'resource_runtime'}:
        return False
    return (recorded == complete or (isinstance(recorded, dict) and set(recorded) == STANDARD_BINDING_KEYS
            and recorded == {key: complete[key] for key in STANDARD_BINDING_KEYS}))


class ResourcePublicationBackend:
    """A separate backend instance owns its checked runs and evidence tables."""

    export_files = runner.TASK_FILES
    runner = runner
    audit_binding_matches = staticmethod(audit_binding_matches)
    agent_import_path = 'sheets_factory.evaluation.resource_frontier:LocalCodex'
    compare_workbooks = staticmethod(compare_workbooks)

    def __init__(self, cohort_manifest=None, *, project_root=ROOT):
        self.root = Path(project_root).resolve()
        self.cohort_path = Path(cohort_manifest).absolute() if cohort_manifest else None
        self.cohort = checked(reference(self.cohort_path)) if self.cohort_path else None
        self.release = support(self.root, 'package_release.py')
        self.publisher = support(self.root, 'publish_dataset.py')
        self.probe = support(self.root, 'prepare_resource_development_probe.py')
        self.runs, self.tasks, self.extra_tracked = {}, {}, {}
        self.payloads = {}
        self.confirmation_observation = None
        if self.cohort is not None:
            self.validate_cohort_shape(self.cohort)
            require(self.cohort['publication_recipe'] == publication_recipe(self.root),
                    'The actually loaded checkout publication/observer/runner recipe differs from the frozen cohort')
            self._bind(self.cohort['publication_recipe'], self.extra_tracked)

    @staticmethod
    def validate_cohort_shape(cohort):
        require(isinstance(cohort, dict) and cohort.get('kind') == KIND
                and type(cohort.get('version')) is int and cohort['version'] == 1
                and cohort.get('status') == 'frozen_for_fresh_confirmation'
                and cohort.get('selection_uses_confirmation_outcomes') is False
                and cohort.get('execution_budget') == BUDGET
                and cohort.get('tool_time_policy_version') == 2,
                'Require the explicit prospectively frozen resource cohort contract')
        require(isinstance(cohort.get('publication_recipe'), dict)
                and set(cohort['publication_recipe']) == set(RECIPE_FILES),
                'Freeze the complete publication, resource observer, runner and timing implementation recipe')
        tasks = cohort.get('tasks'); ids = cohort.get('selected_task_ids')
        require(isinstance(tasks, list) and isinstance(ids, list) and ids
                and [row.get('task_id') for row in tasks] == ids and len(ids) == len(set(ids)),
                'The complete ordered source mapping must bind every task exactly once')
        counts = Counter(row.get('mode') for row in tasks)
        require(set(counts) == set(MODES) and all(counts[mode] >= MIN_PER_MODE for mode in MODES),
                'The frozen cohort requires at least ten tasks per mode')
        for row in tasks:
            require(isinstance(row['task_id'], str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', row['task_id'])
                    and row.get('family') in self_families()
                    and row.get('mode') == self_families()[row['family']]
                    and type(row.get('revision')) is int and row['revision'] >= 0
                    and isinstance(row.get('revision_hash'), str) and re.fullmatch(r'[0-9a-f]{64}', row['revision_hash'])
                    and isinstance(row.get('source_run'), str) and Path(row['source_run']).is_absolute(),
                    'Unsafe or inconsistent task-to-source-run mapping')
            require(audit_binding_matches(row.get('harbor_export_binding'), row.get('audited_harbor_export_binding')),
                    'The original audited binding must match the complete resource export or its exact standard schema')
        _stamp(cohort['frozen_at'])

    def _bind(self, value, tracked):
        """Bind declared receipt leaves without parsing enormous financial tables."""
        records = {}
        def collect(item):
            if isinstance(item, dict):
                if 'path' in item and 'sha256' in item:
                    path = str(Path(item['path']).absolute())
                    old = records.setdefault(path, item)
                    require(old['sha256'] == item['sha256']
                            and ('bytes' not in old or 'bytes' not in item or old['bytes'] == item['bytes']),
                            'Conflicting resource artifact identities')
                    if 'bytes' in item: records[path] = item
                for child in item.values(): collect(child)
            elif isinstance(item, list):
                for child in item: collect(child)
        collect(value)
        # Deduplicate only this one complete proof. Each later call hashes the
        # bytes again: same-size writes can share filesystem timestamp ticks.
        for path, record in records.items():
            ref = reference(path)
            require(ref['sha256'] == record['sha256']
                    and ('bytes' not in record or ref['bytes'] == record['bytes']), 'A bound resource artifact changed')
            require(tracked.setdefault(ref['path'], ref['sha256']) == ref['sha256'],
                    'Conflicting resource artifact identities')

    def inspect_export(self, directory):
        binding = inspect_resource_export(directory)
        path = str(Path(directory).absolute())
        previous = self.payloads.setdefault(path, binding)
        require(previous == binding, 'A resource export binding changed during validation')
        return binding

    def _run(self, run, family, tracked):
        run = Path(run).absolute()
        require(run == run.resolve() and run.is_dir(), 'A mapped original source run must be available without symlinks')
        key = str(run)
        if key not in self.runs:
            phase, frozen, config, seed, proof = self.probe.validate_preparation(run, family)
            require(proof['runtime_profile'] == config[phase.adapter.SETTING]['runtime_profile'],
                    'Source and task runtime profiles differ')
            profile = phase.adapter.load_runtime_profile(proof['runtime_profile']['path'])
            require(profile['image']['id'] == IMMUTABLE_IMAGE, 'The approved immutable base image is required')
            self.runs[key] = {'family': family, 'phase': phase, 'frozen': frozen, 'config': config,
                              'seed': seed, 'proof': proof, 'profile': profile}
            self._bind([reference(run / 'preflight_manifest.json'), reference(run / 'resolved_config.yaml'),
                        reference(run / 'seed_manifest.json'), proof,
                        *[{'path': path, 'sha256': digest} for field in ('recipe_sha256', 'source_artifacts_sha256')
                          for path, digest in frozen[field].items()]], self.extra_tracked)
        require(self.runs[key]['family'] == family, 'A source run cannot change its explicit family')
        for path, digest in self.extra_tracked.items():
            require(tracked.setdefault(path, digest) == digest, 'A previously bound source dependency changed')
        return self.runs[key]

    def _mapping(self, task_id):
        require(self.cohort is not None, 'A frozen source-run mapping is required')
        matches = [row for row in self.cohort['tasks'] if row['task_id'] == task_id]
        require(len(matches) == 1, 'Task is absent from the complete frozen source mapping')
        return matches[0]

    def validate_task(self, run, task, tracked):
        """Add strict family/source/resource gates before the unchanged legacy gates."""
        row = self._mapping(task['id'])
        require(str(Path(run).absolute()) == row['source_run'] and task.get('status') == 'qualified'
                and task.get('mode') == row['mode'] and task.get('revision') == row['revision']
                and task.get('source_id') == row['source_id']
                and task.get('revision_hash') == row['revision_hash']
                and task.get('harbor_export_binding') == row['audited_harbor_export_binding']
                and audit_binding_matches(row['harbor_export_binding'], task.get('harbor_export_binding')),
                'The currently quality-qualified task differs from its frozen source mapping')
        state = self._run(run, row['family'], tracked); phase, config, proof = state['phase'], state['config'], state['proof']
        run = Path(run); base = run / 'tasks' / task['id'] / 'revisions' / f"{task['revision']:03d}"
        private, public = base / 'private', base / 'public'
        latest = self.probe.require_completed_nodes(read_run(run), task['id'], task['revision'])
        for name in ('independent_recovery', 'diagnose', 'export'):
            require(latest.get(name, {}).get('status') == 'completed', 'A mandatory normal quality node is incomplete: ' + name)
        require(reference(private / 'goal.xlsx')['sha256'] == proof['workbook']['sha256'] == task['source_id'],
                'The task goal differs from the admitted financial source')
        plan = read(private / 'plan.json'); delta = read(private / 'expected_delta.json')
        scope = delta if row['family'] == 'entity' else read(private / 'scaled_capital_actual_input_scope.json')
        application = read(private / self.probe.FAMILIES[row['family']][2])
        helpers = self.probe.validate_family_plan(row['family'], phase, plan, application, scope,
                                                 proof, private / 'goal.xlsx', private)
        controls = read(private / 'local_controls.json')
        require(set(controls) == set(CONTROL_REWARDS), 'All five actual local controls are required')
        pairs = [('normal_input', private / 'mutated_unrecalculated.xlsx', public / 'input.xlsx')]
        for name, reward in CONTROL_REWARDS.items():
            candidate = private / 'goal.xlsx' if name == 'oracle' else public / 'input.xlsx' if name == 'nop' else private / 'controls' / (name + '.xlsx')
            actual = compare_workbooks(public / 'input.xlsx', private / 'goal.xlsx', candidate)
            require(actual == controls[name] and type(actual.get('reward')) is int and actual['reward'] == reward,
                    'An actual complete local control is inconsistent: ' + name)
            if name not in ('oracle', 'nop'):
                pairs.append((name, private / 'controls' / (name + '_raw.xlsx'), candidate))
        require(delta == controls['oracle'] and delta.get('structure_ok') is True
                and type(delta.get('expected_change_count')) is int and delta['expected_change_count'] > 0
                and len(delta['expected_changes']) == len(set(delta['expected_changes'])) == delta['expected_change_count'],
                'The complete required value delta is missing or reduced')
        if row['family'] == 'scaled_capital':
            require(scope.get('complete_required_D_count') == delta['expected_change_count']
                    and scope.get('changed_helper_count') == len(helpers & set(delta['expected_changes']))
                    and {item['sheet'] + '!' + item['cell'] for item in plan['edits']} <= set(delta['expected_changes']),
                    'The full delta must include all decisions, financial targets and changed helpers')
        else:
            certificate = read(private / 'joint_repair_certificate.json')
            for index, call in enumerate(certificate['engine_calls']):
                pairs.append(('joint_' + str(index), Path(call['input']['path']), Path(call['output']['path'])))
            self.probe.bind_receipt_references([certificate, read(private / 'joint_control_selection.json')], tracked)
        actual_resources = self.probe.resource_receipts(run, base, proof['runtime_profile'], pairs)
        diagnosis = read(private / 'diagnosis.json')
        require(diagnosis.get('releasable') is True and len(diagnosis.get('enabled_check_ids', [])) == 12
                and set(diagnosis['enabled_check_ids']) == {f'Q{n:02d}' for n in range(1, 13)},
                'All twelve normal diagnostic checks must cover this revision')
        recovery = read(private / 'independent_recovery.json')
        ctx = SimpleNamespace(config=config, revision_dir=base, task_id=task['id'], revision=task['revision'],
            data={'input': public / 'input.xlsx', 'goal': private / 'goal.xlsx',
                  'instruction': (public / 'instruction.md').read_text(), 'revision_hash': row['revision_hash'],
                  'public_profile': read(public / 'profile.json')})
        if row['family'] == 'entity':
            from ..workbook.entity_group_public_recovery import valid_entity_group_recovery_witness as witness
        else:
            from ..workbook.capital_allocation_scaled.public_recovery import valid_scaled_capital_recovery_witness as witness
        require(witness(ctx, recovery), 'The strict current family public-only recovery witness failed')
        batches = diagnosis.get('llm_batches', [])
        require(batches and all(batch.get('status') == 'completed' for batch in batches)
                and {batch.get('visibility') for batch in batches} == {'public_only', 'review'}
                and set().union(*(set(batch.get('assigned_check_ids', [])) for batch in batches))
                    >= {f'Q{n:02d}' for n in range(1, 13)},
                'The complete real public/private diagnostic batch receipts are required')
        require(read(private / 'native_risk_guard.json')['blocking'] is False
                and read(private / 'native_error_probe.json')['blocking'] is False, 'A native guard remains blocking')
        self._bind([actual_resources, recovery], tracked)
        control_resources = self.validate_control_observations(row, task, state['profile'], tracked)
        # The original validator also reopens all these artifacts and checks the
        # original reviewer payload/digest, exact exports and real H1/n0 results.
        for path in (private / 'local_controls.json', private / 'plan.json', private / 'expected_delta.json',
                     private / 'native_error_probe.json', private / 'native_risk_guard.json',
                     public / 'profile.json'):
            ref = reference(path); tracked[ref['path']] = ref['sha256']
        self.tasks[task['id']] = {'source_run': str(run), 'family': row['family'], 'task': deepcopy(task),
            'runtime_profile': proof['runtime_profile'], 'runtime': state['profile'],
            'actual_calculation_resource_bindings': actual_resources,
            'actual_harbor_resource_bindings': control_resources,
            'source_admission': reference(run / 'preflight_manifest.json'),
            'libreoffice_version': None, 'version_probe_performed': False}

    def task_metadata(self, run, task):
        return {'source_run_directory': str(run), 'resource_publication': deepcopy(self.tasks[task['id']])}

    def validate_control_observations(self, row, task, profile, tracked):
        """Require real role inspection; a TOML request is not enforcement proof."""
        from .resource_observer import validate_trial_observations
        receipts = row.get('control_observation_receipts', {})
        supplemental = row.get('supplemental_resource_controls', {})
        require(isinstance(receipts, dict) and set(receipts) <= {'oracle', 'nop'}
                and isinstance(supplemental, dict) and set(supplemental) <= {'oracle', 'nop'},
                'Use explicit actual oracle/nop observation receipts or supplementary controls')
        observations = []
        for agent in ('oracle', 'nop'):
            canonical = reference(task['harbor_controls'][agent]['result_file'])
            supplement = supplemental.get(agent)
            if supplement is None:
                result = canonical; config = reference(Path(result['path']).parent / 'config.json')
                sessions = receipts.get(agent)
            else:
                require(isinstance(supplement, dict) and set(supplement) == {'result', 'config', 'observation_receipts'},
                        'A supplementary actual control must bind its exact result, config and observation receipts')
                result, config = supplement['result'], supplement['config']
                sessions = supplement['observation_receipts']
            require(isinstance(sessions, list) and sessions,
                    'An actual immutable observer receipt is required for each control')
            actual = checked(result)
            configuration = checked(config)
            directory = Path(actual['config']['task']['path'])
            reward = actual.get('verifier_result', {}).get('rewards', {}).get('reward')
            require(actual.get('exception_info') is None
                    and actual.get('agent_info', {}).get('name') == agent
                    and actual.get('config', {}).get('agent', {}).get('name') == agent
                    and configuration.get('agent', {}).get('name') == agent
                    and type(reward) in (int, float) and reward == (1 if agent == 'oracle' else 0)
                    and (actual.get('task_id') or {}).get('path') == str(directory)
                    and configuration.get('task', {}).get('path') == str(directory),
                    'The resource-evidenced control must be an actual successful oracle/nop trial')
            binding = self.release._check_payload(directory, directory, tracked, backend=self)
            from dirhash import dirhash
            require(binding == row['harbor_export_binding'] and actual.get('task_name') == binding['task_name']
                    and actual.get('task_checksum') == dirhash(directory, 'sha256'),
                    'A resource-evidenced control used another exact export or revision')
            observation = validate_trial_observations(config, result, receipts=sessions,
                expected_profile=profile, expected_task_directory=Path(actual['config']['task']['path']))
            require(observation.get('passed') is True and observation.get('complete') is True,
                    'Actual Harbor role resource coverage is incomplete: ' + agent)
            self._bind([sessions, observation, config, result, canonical], tracked)
            observations.append({'agent': agent, 'canonical_quality_result': canonical,
                'resource_evidenced_result': result,
                'evidence_source': 'same_actual_control' if supplement is None else 'explicit_additional_same_export_control',
                'canonical_job_or_reward_overwritten': False, 'observation': observation})
        return observations

    def load_selection(self, root, run_dir, release_dir, selection_path, tracked, secrets, private_scopes):
        require(release_dir is None and selection_path is not None, 'Resource publication requires its frozen selection and original runs')
        selection_path = Path(selection_path).absolute(); frozen = self.release._json(selection_path, selection_path.parent, tracked)
        require(self.cohort is not None and len(frozen.get('selected_task_ids', [])) == len(self.cohort['selected_task_ids'])
                and frozen.get('selected_task_ids') == [row.get('task_id') for row in frozen.get('tasks', [])]
                and set(frozen.get('selected_task_ids', [])) == set(self.cohort['selected_task_ids'])
                and len(frozen.get('tasks', [])) == len(self.cohort['tasks']), 'Publish the entire frozen cohort without selecting a subset')
        selected = {row['task_id']: row for row in frozen['tasks']}; validated, sources, tasks = [], {}, []
        require(set(selected) == set(self.cohort['selected_task_ids']), 'Duplicate or missing confirmation task')
        for row in self.cohort['tasks']:
            run = Path(row['source_run']); task = next((item for item in read_run(run)['tasks'] if item['id'] == row['task_id']), None)
            require(task is not None, 'A mapped source task is missing')
            state = self._run(run, row['family'], tracked); config = state['config']
            private_root = Path(config.get('diagnosis', {}).get('execution', {}).get(
                'private_evidence_directory', root / 'outputs/diagnostic_private_evidence'))
            if not private_root.is_absolute(): private_root = root / private_root
            private_root = private_root.absolute()
            require(private_root != Path(private_root.anchor), 'Private evidence root cannot be the filesystem root')
            private_table = private_scopes.setdefault(str(private_root), {})
            item = self.release._validate_task(run, task, tracked, secrets, project_root=root,
                registry_path=config.get('native_risks', {}).get('registry_path'),
                private_evidence_root=private_root, private_evidence_tracked=private_table, backend=self)
            require(self.publisher._task_contract(run / 'SpreadsheetEval' / row['task_id'], run,
                    tracked, secrets, backend=self) == item['harbor_export_binding'],
                    'The exact resource publication payload differs from its verified export')
            record = selected[row['task_id']]
            require(all(record.get(key) == row.get(key) for key in ('revision', 'revision_hash', 'mode', 'harbor_export_binding')),
                    'The confirmation revision differs from the prospective task mapping')
            validated.append(item); tasks.append(task); sources[row['task_id']] = run / 'SpreadsheetEval' / row['task_id']
        self._bind([reference(self.cohort_path), self.cohort.get('publication_recipe', [])], tracked)
        return Path(self.cohort['tasks'][0]['source_run']), selection_path, frozen, validated, sources, {
            'run': {'id': self.cohort_path.parent.name}, 'tasks': tasks}

    def validate_confirmation_source(self, frozen_path, frozen, evaluation, tracked):
        require(frozen.get('source_manifest') == {'path': str(self.cohort_path), 'sha256': reference(self.cohort_path)['sha256']},
                'Confirmation must bind the original complete cohort mapping')
        require(_stamp(self.cohort['frozen_at']) <= _stamp(frozen['frozen_at']) <= _stamp(evaluation['started_at']),
                'The source mapping and selection must precede all confirmation attempts')
        require(frozen.get('phase') == 'confirmation' and frozen.get('execution_budget') == BUDGET,
                'Use a fresh complete resource confirmation with the explicit execution budget')
        from .resource_observer import validate_observation_receipt
        self.confirmation_observation = validate_observation_receipt(Path(frozen_path).parent, frozen, evaluation)
        if not (self.confirmation_observation.get('passed') is True
                and self.confirmation_observation.get('complete') is True):
            infra = {str(Path(row['result_file']).absolute()) for row in evaluation.get('infra_history', [])
                     if row.get('result_file')}
            failed = [trial for trial in self.confirmation_observation.get('trials', [])
                      if trial.get('passed') is not True or trial.get('complete') is not True]
            old_infra_only = bool(failed) and all((trial.get('result') or {}).get('path') in infra for trial in failed)
            category = ('missing_old_infrastructure_resource_evidence' if old_infra_only
                        else 'missing_or_mismatched_counted_confirmation_resource_evidence')
            require(False, category + ': all confirmation agent/verifier roles require complete actual coverage; '
                    'the observer and all rewards/retry classifications remain unchanged')
        self._bind(self.confirmation_observation, tracked)

    def prepare_runtime(self, root, run_dir, tasks, tracked, secrets):
        recipe_dir = root / 'src/sheets_factory/workbook'
        files = {name: self.release._file(recipe_dir / name, recipe_dir, tracked) for name in self.release.RUNTIME_FILES}
        self.release._runtime_copy_sources(files['Dockerfile'])
        identities = set(); records = []
        for item in tasks:
            state = self.tasks[item['task_id']]; profile = state['runtime']; image = profile['image']
            require(image['id'] == IMMUTABLE_IMAGE, 'Every task must retain the approved immutable runtime identity')
            for relative in ('environment/Dockerfile', 'tests/Dockerfile'):
                source = Path(state['source_run']) / 'SpreadsheetEval' / item['task_id'] / relative
                require(source.read_text().splitlines()[0] == 'FROM ' + image['tag'], 'The actual export base tag differs')
            identities.add((image['tag'], image['id']))
            records.append({'image': image['tag'], 'image_id': image['id'], 'libreoffice_version': None,
                'version_probe_performed': False, 'task_ids': [item['task_id']],
                'evidence': 'SHA-bound source, actual calculation receipts and strict public replay resource witness'})
        require(len(identities) == 1, 'A publication requires one actual immutable runtime identity')
        tag, _ = next(iter(identities))
        metadata = {'image_tag': tag, 'recorded_run_images': records,
            'original_external_evidence_required_for_revalidation': True, 'portable_evidence_inspection_claimed': False}
        # The caller creates the same honest preload/rebuild script as the old
        # publisher. It records the exact image ID; a rebuild does not promise it.
        return {f'runtime/{name}': raw for name, raw in files.items()}, metadata

    def recheck_tracked(self, tracked):
        for path, digest in tracked.items():
            require(reference(path)['sha256'] == digest, 'Resource publication evidence changed during staging')

    def current_tasks(self):
        result = []
        for row in self.cohort['tasks']:
            tasks = read_run(Path(row['source_run']))['tasks']
            matches = [task for task in tasks if task['id'] == row['task_id']]
            require(len(matches) == 1, 'A mapped task disappeared during publication')
            result.extend(matches)
        return result

    def final_recheck(self):
        require(read(self.cohort_path) == self.cohort, 'The frozen source mapping changed')
        self.recheck_tracked(self.extra_tracked)
        self.recheck_payloads()

    def recheck_payloads(self):
        for directory, binding in list(self.payloads.items()):
            path = Path(directory)
            require({file.relative_to(path).as_posix() for file in path.rglob('*') if file.is_file()} == self.export_files
                    and not any(file.is_symlink() for file in path.rglob('*'))
                    and inspect_resource_export(path) == binding,
                    'A complete resource task inventory changed during staging')

    def publication_metadata(self):
        return {'version': 1, 'cohort_manifest_sha256': reference(self.cohort_path)['sha256'],
            'source_run_count': len({row['source_run'] for row in self.cohort['tasks']}),
            'source_run_mapping_frozen_before_confirmation': True,
            'original_checkout_and_external_evidence_required_for_revalidation': True,
            'portable_evidence_inspection_claimed': False, 'published_oracle_is_standalone': True,
            'libreoffice_version_probe_performed': False,
            'all_confirmation_roles_observed': self.confirmation_observation is not None
                and self.confirmation_observation.get('passed') is True
                and self.confirmation_observation.get('complete') is True}


def self_families():
    return {'entity': 'debugging', 'scaled_capital': 'financial_modeling'}

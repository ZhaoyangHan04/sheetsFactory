"""Cold source/projection admission and normal scheduling for one business view."""
from __future__ import annotations

from copy import deepcopy
import importlib
from pathlib import Path

from .factory import FactoryPipeline
from ..task_adapters import heterogeneous_financial_view as base
from ..workbook.resource_engine import load_runtime_profile
from ..workbook.heterogeneous_contracts.validate import compare_typed_caches
from ..evaluation.streaming_delta import compare_workbooks
from ..evaluation.streaming_verifier import compare_files
from ..evaluation.resource_harbor import inspect_resource_export
from ..checkers.unsafe_regions import evaluate_native_risk_guard

ROOT = base.ROOT
VIEW_NAME = 'sheets_factory.task_adapters.heterogeneous_financial_view_v3'
TARGETS = {'financial_modeling': 1, 'debugging': 0}
METHOD = 'audited_native_Excel_DAG_to_complete_public_business_value_projection_v3'
SOURCE_KIND = 'audited_heterogeneous_native_source_with_business_projection'
REWARDS = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}
require, reference, read = base.require, base.reference, base._read


class ProjectionAdmission:
    """Opaque process-local admission; persisted booleans never confer trust."""
    def __init__(self, projection_manifest):
        view = importlib.import_module(VIEW_NAME)
        self.refs = base._References()
        original = projection_manifest if isinstance(projection_manifest, dict) else reference(projection_manifest)
        directory = self.refs.check(original).parent
        snapshot = read(original['path'])
        require(snapshot.get('kind') == 'prequality_heterogeneous_business_view_v3_development'
            and type(snapshot.get('version')) is int and snapshot['version'] == 1,
            'A completed version-three actual business projection is required')
        self.plan = view.build_view_plan(snapshot['source_manifest'], enabled=True)
        view_plan_ref = reference(directory / 'private_plan.json')
        self.refs.check(view_plan_ref)
        require(read(view_plan_ref['path']) == self.plan, 'The actual private projection plan changed')
        native = self.plan['source_admission']
        require(snapshot['source_admission'] == native and snapshot['plan_sha256'] == self.plan['plan_sha256']
            and snapshot['declared_business_slots'] == self.plan['declared_slot_count'],
            'The current complete source admission and business projection differ')
        self.refs.walk(native)
        for path, digest in snapshot['recipe'].items():
            actual = reference(path); require(actual['sha256'] == digest, 'The actual projection recipe changed')
            self.refs.check(actual)
        input_ref, goal_ref, instruction_ref = (reference(directory / path) for path in
            ('task/public/input.xlsx', 'task/private/goal.xlsx', 'task/public/instruction.md'))
        require(Path(instruction_ref['path']).read_text() == view.public_brief(), 'The actual public brief changed')
        for record in (input_ref, goal_ref, instruction_ref): self.refs.check(record)
        view.validate_view(self.plan, input_ref['path'], goal_ref['path'])
        profile = load_runtime_profile(native['runtime_profile']['path'])
        helper = base._builder()
        runtime = {'runtime_profile': native['runtime_profile'], 'runtime_profile_value': profile}
        calls = snapshot['actual_engine_calls']
        labels = ['normalize_input', 'repeat_input', 'normalize_goal', 'repeat_goal',
            'actual_control_equivalent', 'actual_control_missed_root', 'actual_control_extra_change']
        require(len(calls) == 7 and [c.get('label') for c in calls] == labels,
            'All seven actual projection and control calculations are required')
        for index, call in enumerate(calls, 1):
            require(type(call.get('index')) is int and call['index'] == index and call.get('completed') is True,
                'An actual projection calculation is incomplete')
            self.refs.walk(call)
            evidence = call['actual_resource_evidence']
            require(helper.validate_actual_call(call, evidence['terminal'], runtime) == evidence,
                'An actual projection calculation lacks its resource/file chain')
            terminal = reference(directory / f'LO{index}_terminal.json')
            started = reference(directory / f'LO{index}_started.json')
            self.refs.check(terminal); self.refs.check(started)
            require(read(terminal['path']) == call and read(started['path'])['completed'] is False
                and read(started['path'])['input'] == call['input'], 'An actual projection attempt receipt changed')
        require(calls[0]['output'] == input_ref and calls[2]['output'] == goal_ref
            and calls[1]['input'] == input_ref and calls[3]['input'] == goal_ref,
            'The selected projection is not the actual normalized calculation chain')
        for first, repeated in ((input_ref, calls[1]['output']), (goal_ref, calls[3]['output'])):
            require(compare_typed_caches(first['path'], repeated['path'])['passed'] is True,
                'The complete actual projection typed stability failed')
        controls = snapshot['local_controls']
        self.refs.walk(controls)
        require(controls['rewards'] == REWARDS and controls['actual_LO_calls'] == 7,
            'The complete actual five-control receipt is required')
        for name, reward in REWARDS.items():
            report = compare_files(input_ref['path'], goal_ref['path'], controls['workbooks'][name]['path'])
            require(report == read(controls['reports'][name]['path']) and report.get('reward') == reward,
                'An actual local control differs from its full current value comparison')
        require(controls['workbooks']['oracle'] == goal_ref and controls['workbooks']['nop'] == input_ref
            and all(controls['workbooks'][name] == calls[i + 4]['output'] for i, name in
                enumerate(('equivalent', 'missed_root', 'extra_change'))), 'The actual control workbooks changed')
        self.delta = compare_workbooks(input_ref['path'], goal_ref['path'], goal_ref['path'])
        delta_ref = reference(directory / 'complete_delta.json')
        self.refs.check(delta_ref)
        require(read(delta_ref['path']) == self.delta, 'The original complete actual value delta changed')
        require(self.delta['reward'] == 1 and self.delta['expected_change_count'] > 0
            and self.delta['expected_change_count'] == snapshot['complete_changed_value_set_count'],
            'The complete projected changed-value set differs')
        self.refs.walk(snapshot['resource_task_inventory'])
        export = Path(snapshot['tasks'][0]['task_directory'])
        require(inspect_resource_export(export) == snapshot['tasks'][0]['harbor_export_binding'],
            'The engineering export is not the original complete seventeen-file version')
        self.refs.finish()
        self.proof = {'kind': 'checked_heterogeneous_business_projection_admission', 'version': 1,
            'reference_method': METHOD, 'source_manifest': native['source_manifest'],
            'native_source': native['workbook'], 'workbook': native['workbook'],
            'native_source_admission': native, 'projection_manifest': original,
            'view_module': reference(view.__file__), 'view_version': 3, 'view_plan_sha256': self.plan['plan_sha256'],
            'view_plan_ref': view_plan_ref, 'full_D': delta_ref,
            'runtime_profile': native['runtime_profile'], 'input': input_ref, 'goal': goal_ref,
            'instruction': instruction_ref, 'declared_business_slots': self.plan['declared_slot_count'],
            'full_D_count': self.delta['expected_change_count'], 'actual_projection_engine_calls': calls,
            'actual_projection_five_controls': controls, 'verified_artifacts': deepcopy(self.refs.files),
            'native_and_projection_are_distinct_artifacts': True,
            'ordinary_Factory_nodes_previously_executed': False, 'prior_difficulty_transferred': False,
            'quality_or_difficulty_certified': False}

    def guard(self):
        self.refs.finish()
        return self.proof


def validate_configuration(config):
    from ..task_adapters import heterogeneous_business_modeling as adapter
    require(adapter.validate_setting(config.get(adapter.SETTING)), 'The explicit business family route is required')
    run = config['run']; agents = config['agents']; diagnosis = config['diagnosis']
    require(run['targets'] == TARGETS and all(type(run['targets'][m]) is int for m in TARGETS)
        and all(type(run[key]) is int for key in ('max_sources','max_parallel_sources','max_candidates_per_seed'))
        and run['max_sources'] == run['max_parallel_sources'] == run['max_candidates_per_seed'] == 1
        and run['source_ordering'] == 'manifest' and not run.get('continuation_id'), 'A fresh first business-view task is required')
    require(diagnosis['selection'] == {'include': 'all', 'exclude': []}
        and diagnosis.get('reference_evidence_policy') == 'independent_public_recovery'
        and diagnosis.get('execution', {}).get('reference_evidence_transport') == 'audited_summary'
        and diagnosis.get('difficulty_deferred') is False and config['harbor']['execute_controls'] is True,
        'All twelve checks, strict public recovery and actual Harbor controls remain mandatory')
    require(agents['model'] == 'gpt-6-sol' and agents['reasoning_effort'] == 'high'
        and agents['trajectory_timeout_seconds'] == 600 and agents['max_parallel_calls'] == 1
        and all(agents.get('roles', {}).get(role, {}).get('model') == 'gpt-6-sol'
            and agents['roles'][role]['reasoning_effort'] == 'high' for role in
                ('public_diagnostician', 'reference_diagnostician'))
        and agents['roles']['reference_diagnostician']['timeout_seconds'] == 2400,
        'The original normal quality models, visibility roles and budgets changed')
    require(config['recovery'].get('compiler_backend') == adapter.BACKEND
        and type(config['recovery'].get('replay_timeout_seconds')) is int
        and config['recovery']['replay_timeout_seconds'] == 7200, 'The explicit public-only replay route is required')
    profile = load_runtime_profile(config[adapter.SETTING]['runtime_profile']['path'])
    require(agents.get('container_cpus') == 2 and agents.get('container_memory') == '32g'
        and config['engine']['image'] == profile['image']['tag'] and config['engine']['timeout_seconds'] == 600,
        'The actual source and quality roles require their explicit profile resources')
    return profile


def validate_seed(seed, proof):
    require(seed.get('source_kind') == SOURCE_KIND and seed.get('modes') == ['financial_modeling']
        and type(seed.get('variant')) is int and seed['variant'] == 0
        and reference(seed['local_path']) == proof['native_source']
        and seed['sha256'] == proof['native_source']['sha256']
        and seed.get('finance_evidence', {}).get('business_projection_admission') == proof,
        'The native source identity and explicit business projection admission changed')


class HeterogeneousBusinessFactory(FactoryPipeline):
    def __init__(self, config, *args, admission, **kwargs):
        require(isinstance(admission, ProjectionAdmission), 'A fresh opaque process-local source admission is required')
        validate_configuration(config); admission.guard()
        self.admission = admission
        super().__init__(config, *args, **kwargs)

    def load_seeds(self):
        seeds = super().load_seeds()
        require(len(seeds) == 1, 'Exactly one fixed first source is supported')
        validate_seed(seeds[0], self.admission.guard())
        return seeds

    def run_phase(self, context, phase):
        context.data['_heterogeneous_admission'] = self.admission
        self.admission.guard()
        return super().run_phase(context, phase)

    def _claim_targets(self, context):
        require('mask_ranges' not in context.data['plan'] and not context.data['plan'].get('scenario_inputs'),
            'A business projection cannot become formula-range masking or change raw assumptions')
        return super()._claim_targets(context)

    def _preharbor_native_risks(self, task, binding):
        # Preserve the ordinary final projected-D check. The native source has
        # a different worksheet coordinate space; separately map only actual
        # nonblank projected D to its exact source aliases, never all ancestry.
        result = super()._preharbor_native_risks(task, binding)
        proof = self.admission.guard()
        native = evaluate_native_risk_guard(
            [r['source']['sheet']+'!'+r['source']['cell'] for r in self.admission.plan['forecast_targets']
                if r['reference_value'][0] != 'empty'], proof['native_source']['sha256'],
            project_root=self.config['project_root'],
            sheet_names=sorted({r['source']['sheet'] for r in self.admission.plan['forecast_targets']}),
            registry_path=self.config.get('native_risks',{}).get('registry_path'))
        original = dict(result)
        for key in ('receipt_id','receipt_path','receipt_sha256','checked_at'):
            result.pop(key, None)
        result = {**result, 'projected_D_guard_receipt':original,
            'native_financial_alias_projection_guard':native,
            'blocking':result['blocking'] or native['blocking'],
            'state':('flagged' if result['blocking'] or native['blocking'] else
                'unknown' if 'unknown' in (result['state'],native['state']) else 'clear'),
            'issues':result['issues']+native['issues'],
            'evidence_requests':result['evidence_requests']+native['evidence_requests']}
        from ..core.audit import utcnow
        result['checked_at'] = utcnow()
        path = Path(self.config['run_dir'])/'private/business_preharbor_native_checks'/task['id']
        path.mkdir(parents=True,exist_ok=True)
        digest = base.canonical(result); record = path/(digest+'.json')
        if not record.exists():
            with record.open('x') as stream:
                import json
                json.dump(result,stream,ensure_ascii=False,indent=2);stream.write('\n')
        result.update(receipt_id=digest,receipt_path=str(record),receipt_sha256=reference(record)['sha256'])
        self.audit.task(task['id'],preharbor_native_risk_guard=result)
        return result

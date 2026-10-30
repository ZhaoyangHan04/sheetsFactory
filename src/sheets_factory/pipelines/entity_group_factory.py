"""Normal Factory scheduling for one fully admitted fixed-plan G01 DBG source."""
from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from .factory import FactoryPipeline
from . import entity_group_admission as admission
from ..nodes.joint_controls import SETTING as CONTROL_SETTING, validate_setting as validate_controls
from ..task_adapters import entity_group as adapter
from ..task_adapters.public_workbook_scope import reference, require

TARGETS = {'financial_modeling': 0, 'debugging': 1}
REFERENCE_METHOD = 'independent_fixed_plan_integer_journal_complete_actual_Excel_field_audit_and_two_further_typed_stability_checks'


def validate_configuration(config):
    """Require the prospective family policy without changing global routing."""
    require(adapter.enabled(SimpleNamespace(config=config, mode='debugging')),
            'The explicit complete entity family policy is required')
    profile = adapter.load_runtime_profile(config[adapter.SETTING]['runtime_profile']['path'])
    run = config['run']
    require(run.get('targets') == TARGETS and all(type(run['targets'].get(mode)) is int for mode in TARGETS)
            and type(run.get('max_sources')) is int and run['max_sources'] == 1
            and type(run.get('max_parallel_sources')) is int and run['max_parallel_sources'] == 1
            and type(run.get('max_candidates_per_seed')) is int and run['max_candidates_per_seed'] == 1
            and run.get('source_ordering') == 'manifest'
            and not any(run.get(key) for key in ('seed_path', 'source_filter', 'additional_seed_manifests',
                                                'continuation_id', 'resume_existing_task_ids')),
            'Only a fresh predeclared first G01 debugging source is supported')
    validate_controls(config[CONTROL_SETTING])
    require(config['diagnosis'].get('selection') == {'include': 'all', 'exclude': []}
            and config['diagnosis'].get('reference_evidence_policy') == 'independent_public_recovery'
            and config['diagnosis'].get('execution', {}).get('reference_evidence_transport') == 'audited_summary'
            and config['diagnosis'].get('difficulty_deferred') is False
            and config['harbor'].get('execute_controls') is True,
            'All normal quality checks, exact public recovery and actual Harbor controls are required')
    agents = config['agents']
    require(agents.get('model') == 'gpt-6-sol' and agents.get('reasoning_effort') == 'high'
            and type(agents.get('max_parallel_calls')) is int and agents['max_parallel_calls'] == 1
            and agents.get('trajectory_timeout_seconds') == 600
            and all(agents.get('roles', {}).get(role, {}).get('model') == 'gpt-6-sol'
                    and agents['roles'][role].get('reasoning_effort') == 'high'
                    for role in ('public_diagnostician', 'reference_diagnostician'))
            and agents['roles']['reference_diagnostician'].get('timeout_seconds') == 2400,
            'The original high-reasoning quality roles and explicit private/trace budgets are required')
    expected_memory = str(profile['docker_resources']['agent']['memory_bytes'] // 1024**3) + 'g'
    require(agents.get('container_memory') == expected_memory
            and agents.get('container_cpus') == profile['docker_resources']['agent']['cpus']
            and config['engine'].get('image') == profile['image']['tag']
            and config['engine'].get('timeout_seconds') == profile['timeouts']['workbook_file_seconds'],
            'The requested quality resources must derive from the exact runtime profile')
    adapter.construction_contract('debugging', config)
    return profile


def validate_seed(seed, proof):
    """No generic source-kind bypass: the complete local admission is explicit."""
    actual = reference(seed['local_path'])
    evidence = seed.get('finance_evidence', {})
    require(seed.get('source_kind') == admission.SOURCE_KIND and seed.get('profile_id') == 'G01'
            and seed.get('modes') == ['debugging'] and type(seed.get('variant')) is int and seed['variant'] == 0
            and actual == proof['workbook'] and seed.get('sha256') == actual['sha256']
            and seed.get('source_manifest') == proof['source_manifest']
            and evidence.get('source_manifest') == proof['source_manifest']
            and evidence.get('audited_source_binding') == proof
            and evidence.get('financial_seed_verified') is True
            and evidence.get('debugging_eligible') is True
            and evidence.get('reference_method') == REFERENCE_METHOD,
            'The exact G01 financial source and its complete independent reference admission are required')
    return actual


class EntityGroupFactory(FactoryPipeline):
    """Keep the original quota, repair, evidence, control and export machinery."""

    def __init__(self, config, *args, admitted_proof, **kwargs):
        validate_configuration(config)
        require(isinstance(admitted_proof, dict)
                and config[adapter.SETTING]['runtime_profile'] == admitted_proof.get('runtime_profile'),
                'The source and task must bind the same explicit resource profile')
        self.admitted_proof = deepcopy(admission.verify_admitted_proof(admitted_proof))
        super().__init__(config, *args, **kwargs)

    def load_seeds(self):
        seeds = super().load_seeds()
        require(self.targets == TARGETS and len(seeds) == 1,
                'The first development run admits exactly one G01 debugging seed')
        seed = seeds[0]
        actual = validate_seed(seed, self.admitted_proof)
        admission.verify_references(self.admitted_proof)
        seed['survey'] = {**seed.get('survey', {}), 'normalized_path': actual['path'],
            'source_sha256': actual['sha256'], 'status': 'ok', 'error_count': 0}
        return seeds

    def run_phase(self, context, phase):
        result = super().run_phase(context, phase)
        require(reference(context.source) == self.admitted_proof['workbook'],
                'The source workbook changed after complete admission')
        if context.data.get('baseline'):
            require(reference(context.data['baseline'])['sha256']
                    == context.data.get('source_id') == self.admitted_proof['workbook']['sha256'],
                    'Normalization changed the exact independently audited financial source')
        return result

    def _claim_targets(self, context):
        require(context.mode == 'debugging' and 'mask_ranges' not in context.data['plan']
                and not context.data['plan'].get('scenario_inputs'),
                'The entity debugging plan cannot become an FM mask or change supplied primitives')
        return super()._claim_targets(context)

"""Normal Factory with explicit financial-source admission for each mode."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import time

import openpyxl

from ..core.node import TaskRejected
from ..task_adapters import full_state_joint_cohort as dispatch
from ..task_adapters.public_workbook_scope import canonical, require, reference
from .factory import FactoryPipeline
from . import scc_activity_admission as v2, semantic_graph_admission as v3
from ..task_adapters.lease_family import compare_exact_typed

FM_KIND = 'derived_composed_financial_model'
MODES = ('financial_modeling', 'debugging')


def _definition_state(path):
    book = openpyxl.load_workbook(path, keep_links=False)
    try:
        formulas, formats = [], []
        for sheet in book:
            for cell in sheet._cells.values():
                if cell.data_type == 'f':
                    value = cell.value
                    if not isinstance(value, str):
                        value = {'kind': type(value).__name__, 'attributes': vars(value)}
                    formulas.append([sheet.title, cell.coordinate, value])
                if cell.value is not None:
                    formats.append([sheet.title, cell.coordinate, cell.number_format])
        metadata = {'epoch': book.epoch.isoformat(), 'calculation': vars(book.calculation) if book.calculation else None,
            'sheets': [{'name': sheet.title, 'state': sheet.sheet_state,
                        'merged_ranges': sorted(str(item) for item in sheet.merged_cells.ranges)} for sheet in book],
            'defined_names': {key: vars(value) for key, value in book.defined_names.items()}}
        return {'formula_definitions_sha256': canonical(sorted(formulas)),
            'number_formats_sha256': canonical(sorted(formats)), 'metadata': metadata}
    finally:
        book.close()


def audit_pilot_equivalence(revision_dir, probe_reference, *, development_selection=None):
    """Read-only semantic relay. It never imports a score into a new task DB."""
    from ..task_adapters.public_workbook_scope import read as read_ref, checked_bytes
    probe = read_ref(probe_reference)
    require(probe.get('kind') == 'prequality_development_probe' and len(probe.get('tasks', [])) == 1,
            'The actual first-source development probe is required')
    prior = probe['tasks'][0]
    require(prior.get('mode') == 'financial_modeling' and probe.get('physical_missing_formula_count') == 60193,
            'The pilot is not the full-state FM development candidate')
    old = Path(prior['task_directory'])
    new = Path(revision_dir)
    before_input, after_input = old / 'environment/input.xlsx', new / 'public/input.xlsx'
    before_goal, after_goal = old / 'tests/reference.xlsx', new / 'private/goal.xlsx'
    before_instruction, after_instruction = old / 'instruction.md', new / 'public/instruction.md'
    from ..evaluation.harbor import inspect_export
    require(inspect_export(old) == prior['harbor_export_binding'], 'The original actual pilot export changed')
    typed = compare_exact_typed(before_input, after_input)
    first, second = _definition_state(before_input), _definition_state(after_input)
    instruction_equal = before_instruction.read_bytes() == after_instruction.read_bytes()
    goal_equal = reference(before_goal)['sha256'] == reference(after_goal)['sha256'] == prior['source_id']
    selection_ref = None
    if development_selection is not None:
        selection_ref = reference(development_selection)
        selected = json.loads(checked_bytes(selection_ref))
        require(selected.get('phase') == 'development' and any(
            task.get('revision_hash') == prior['revision_hash'] for task in selected.get('tasks', [])),
            'The observation relay does not refer to the original development selection')
    return {'kind': 'read_only_full_state_C01_development_observation_equivalence', 'version': 1,
        'passed': typed['passed'] and first == second and instruction_equal and goal_equal,
        'pilot_probe': probe_reference, 'original_development_selection': selection_ref,
        'old_input': reference(before_input), 'new_input': reference(after_input),
        'old_goal': reference(before_goal), 'new_goal': reference(after_goal),
        'old_instruction': reference(before_instruction), 'new_instruction': reference(after_instruction),
        'exact_typed_values_equal': typed['passed'], 'typed_mismatch_count': len(typed['mismatches']),
        'typed_mismatch_examples': typed['mismatches'][:5], 'definition_state_equal': first == second,
        'old_definition_state': first, 'new_definition_state': second,
        'instruction_bytes_equal': instruction_equal, 'goal_bytes_equal': goal_equal,
        'ZIP_bytes_alone_do_not_define_a_new_development_task': True,
        'new_development_call_permitted': False, 'new_QA_nodes_or_scores_imported': False,
        'new_LO_calls': 0, 'new_model_calls': 0, 'quality_or_difficulty_certified': False}


def validate_seed(seed, config, fm_validator):
    """Call the selected original validator, retaining its complete proof."""
    backend = dispatch.validate_setting(config)
    require(type(seed.get('variant', 0)) is int and seed.get('variant', 0) == 0,
            'The fixed mixed cohort requires new source identities without variants')
    modes = seed.get('modes')
    evidence = seed.get('finance_evidence', {})
    if modes == ['financial_modeling']:
        require(seed.get('source_kind') == FM_KIND and callable(fm_validator)
                and not seed.get('task_adapter') and not evidence.get('task_adapter')
                and not evidence.get('mutation_provider'), 'An original FM admission is required for FM-only seeds')
        proof = fm_validator(seed)
    elif modes == ['debugging']:
        if backend == 'full_graph_v2':
            require(seed.get('source_kind') == v2.SOURCE_KIND, 'V2 debugging requires its own presented-source admission')
            proof = v2.validate_joint_seed(seed, config.get(v2.JOINT_SETTING))
            require(evidence.get('task_adapter') == seed.get('task_adapter')
                    and evidence.get('full_graph_financial_admission') == seed['scc_activity_binding']['financial_admission'],
                    'V2 source evidence differs from its complete financial admission')
        else:
            require(seed.get('source_kind') == v3.SOURCE_KIND, 'V3 debugging requires its separate provider admission')
            proof = v3.validate_seed(seed, config.get(v3.SETTING))
            require(evidence.get('mutation_provider') == seed.get('mutation_provider')
                    and evidence.get('full_graph_financial_admission') == seed['semantic_graph_binding']['financial_admission']
                    and evidence.get('source_presentation_adapter') == v3.SOURCE_ADAPTER
                    and not evidence.get('task_adapter'), 'V3 source/provider context is incomplete or relabelled')
    else:
        raise ValueError('Every mixed-cohort seed must be explicitly FM-only or DBG-only')
    require(canonical(evidence.get('audited_source_binding')) == canonical(proof),
            'The complete admitted financial source proof changed')
    actual = reference(seed['local_path'])
    require(actual['sha256'] == seed.get('sha256') == proof.get('workbook', {}).get('sha256')
            and Path(proof['workbook']['path']).resolve() == Path(actual['path']),
            'The normalized source must be the exact independently admitted workbook')
    return proof


def normalize_debug_claim(context, backend):
    """Validate repaired plans too, before the unchanged Factory claim path."""
    plan = context.data['plan']
    evidence = context.data['finance_evidence']
    if backend == 'full_graph_v2':
        binding = evidence.get('full_state_joint_source_binding')
        require(isinstance(binding, dict), 'The V2 claim lacks its original source binding')
        inventory = v2.read(binding['scope_inventory'])
        v2.validate_plan_binding(binding, inventory, plan)
        identity = v2.ADAPTER
    else:
        binding = evidence.get('semantic_graph_binding')
        require(isinstance(binding, dict), 'The V3 claim lacks its separate mutation-source binding')
        v3.validate_plan_binding(binding, plan)
        identity = v3.PROVIDER_ID
    require(plan.get('family_adapter', {}).get('id') == identity, 'The actual claimed mutation provider changed')
    if 'mask_ranges' in plan:
        if type(plan['mask_ranges']) is not list or plan['mask_ranges']:
            raise TaskRejected('Q06: joint debugging cannot declare financial-modeling mask ranges')
        normalized = deepcopy(plan)
        normalized.pop('mask_ranges')
        context.data['plan'] = normalized
        context.save('mixed_cohort_empty_DBG_mask_compatibility.json', {
            'backend': backend, 'removed_field': 'mask_ranges', 'removed_value': [],
            'before_plan_sha256': canonical(plan), 'after_plan_sha256': canonical(normalized),
            'edits_sha256': canonical(normalized['edits']), 'physical_edit_count': len(normalized['edits']),
            'public_rules_inputs_and_edits_changed': False, 'quality_or_difficulty_certified': False})


class FullStateJointFactory(FactoryPipeline):
    """Preserve normal scheduling, controls, recovery, diagnosis, and export."""

    def __init__(self, config, *args, fm_validator=None, **kwargs):
        self.backend = dispatch.validate_setting(config)
        require(callable(fm_validator), 'The frozen original FM source validator is required')
        self.fm_validator = fm_validator
        self._admitted_paths = {}
        super().__init__(config, *args, **kwargs)

    def load_seeds(self):
        seeds = super().load_seeds()
        require(self.targets == {'financial_modeling': 10, 'debugging': 10}
                and len(seeds) == 20 and len({seed['sha256'] for seed in seeds}) == 20,
                'The fixed mixed cohort requires ten original FM and ten separately admitted DBG sources')
        counts = {mode: 0 for mode in MODES}
        for seed in seeds:
            started = time.monotonic()
            proof = validate_seed(seed, self.config, self.fm_validator)
            mode = seed['modes'][0]
            counts[mode] += 1
            source = str(Path(seed['local_path']).resolve())
            self._admitted_paths[source] = seed['sha256']
            # The extra V2 claim binding is a complete immutable admission,
            # not a new source kind, mutation provider, or financial result.
            if mode == 'debugging' and self.backend == 'full_graph_v2':
                existing = seed['finance_evidence'].get('full_state_joint_source_binding')
                require(existing is None or canonical(existing) == canonical(seed['scc_activity_binding']),
                        'The V2 claim binding differs from its original source proof')
                seed['finance_evidence']['full_state_joint_source_binding'] = deepcopy(seed['scc_activity_binding'])
            seed['survey'] = {**seed.get('survey', {}), 'normalized_path': proof['workbook']['path'],
                'source_sha256': seed['sha256'], 'status': 'ok', 'error_count': 0}
            self.audit.emit('source.mixed_financial_admission', source_id=seed['sha256'], mode=mode,
                source_kind=seed['source_kind'], duration_ms=round((time.monotonic() - started) * 1000),
                model_calls=0, LO_calls=0)
        require(counts == self.targets, 'The complete fixed ten sources are required in each mode')
        return seeds

    def run_phase(self, context, phase):
        result = super().run_phase(context, phase)
        actual = reference(context.source)
        expected = self._admitted_paths.get(actual['path'])
        require(expected == actual['sha256'], 'The actual financial source changed after admission')
        if context.data.get('baseline'):
            require(reference(context.data['baseline'])['sha256'] == expected == context.data.get('source_id'),
                    'Normalization changed the exact independently admitted financial source')
        return result

    def _claim_targets(self, context):
        dispatch.validate_setting(self.config)
        if context.mode == 'debugging':
            normalize_debug_claim(context, self.backend)
        else:
            require(context.mode == 'financial_modeling', 'Unsupported mixed-cohort claim mode')
        return super()._claim_targets(context)

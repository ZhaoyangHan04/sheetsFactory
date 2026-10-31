"""Normal quality for independently audited regions of native business models.

An opaque admission binds actual recalculated task bytes and the complete
changed-value set. It does not certify unrelated parts of the donor models.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import weakref

from .linear_capital_quality import ROOT, References, reference, require
from .factory import FactoryPipeline

SETTING = 'heterogeneous_native_quality'
REGISTRY = ROOT/'config/task_adapters/heterogeneous_native_quality_nodes.yaml'
PROFILE = ROOT/'config/runtime_profiles/entity_group_large_v2.yaml'
BOUNDARY = ROOT/'scripts/prepare_heterogeneous_native_development.py'
NORMAL_SOURCE_KIND = 'scoped_native_business_task_views'
_LIVE = weakref.WeakSet()


def setting():
    return {'version': 1, 'scope': 'independently_checked_task_outputs',
        'pipeline': reference(__file__),
        'nodes': reference(ROOT/'src/sheets_factory/task_adapters/heterogeneous_native_quality.py'),
        'registry': reference(REGISTRY), 'runtime_profile': reference(PROFILE),
        'actual_task_boundary': reference(BOUNDARY)}


def validate_configuration(config):
    from ..checkers import DiagnosisRunner
    from ..nodes.quality import validate_reference_policy_selection
    from ..workbook.resource_engine import load_runtime_profile
    require(config.get(SETTING) == setting(), 'The explicit scoped native quality route changed')
    require(validate_reference_policy_selection(config) == 'reference_review',
        'This family requires supported public sufficiency and independent reference review')
    resolved = DiagnosisRunner(config['project_root']).resolve(config)
    require(set(resolved['enabled_check_ids']) == {f'Q{i:02d}' for i in range(1, 13)},
        'All twelve ordinary quality checks are mandatory for this reference policy')
    require(config['pipeline']['node_registry'] == str(REGISTRY)
        and config['diagnosis']['execution']['reference_evidence_transport'] == 'audited_summary'
        and config['harbor']['execute_controls'] is True,
        'Use normal numbered diagnostics, complete private evidence and actual Harbor controls')
    require(config['run']['max_candidates_per_seed'] == 1
        and config['run']['source_ordering'] == 'manifest'
        and not any(config['run'].get(k) for k in
            ('continuation_id', 'seed_path', 'source_filter', 'additional_seed_manifests')),
        'Only the explicitly admitted task inventory may enter this fresh run')
    profile = load_runtime_profile(PROFILE)
    require(profile['image']['id'] == 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
        and all(profile['docker_resources'][r] == {'cpus': 2, 'memory_bytes': 32*1024**3, 'pids_limit': 256}
            for r in ('source', 'agent', 'verifier'))
        and config['agents']['container_cpus'] == 2 and config['agents']['container_memory'] == '32g'
        and config['engine']['image'] == profile['image']['tag'], 'Retain the actual task resource profile')
    limits = config['construction']['analysis_limits']
    require(limits['max_profile_cells'] == profile['limits']['max_profile_cells']
        and limits['max_dependency_closure_cells'] == profile['limits']['max_dependency_closure_cells'],
        'Profile and dependency analysis must remain complete')
    return profile


class NativeScopeAdmission:
    def __init__(self, validation_terminal):
        self.references = References()
        self.boundary = reference(BOUNDARY)
        self.references.check(self.boundary)
        spec = importlib.util.spec_from_file_location('_native_scoped_quality_boundary_'+self.boundary['sha256'], BOUNDARY)
        self.helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.helper)
        self.evidence = self.helper.checked_material(validation_terminal)
        self.evidence_sha256 = hashlib.sha256(json.dumps(self.evidence, sort_keys=True).encode()).hexdigest()
        self.references.check(self.boundary)
        self.recipe = self.helper.recipes()
        for path, digest in self.recipe.items():
            record = reference(path)
            require(record['sha256'] == digest, 'The actual task recipe changed during admission')
            self.references.check(record)
        self.references.discover(self.evidence['actual_ref'])
        a = self.evidence['actual']
        self.proof = {'kind': 'opaque_native_scoped_quality_admission', 'version': 1,
            'mode': a['mode'], 'workbook': self.evidence['source_ref'],
            'input': a['input'], 'goal': a['goal'], 'instruction': a['instruction'],
            'actual_validation': self.evidence['actual_ref'],
            'material': self.evidence['material_ref'], 'plan': self.evidence['material']['review_scope'],
            'full_D': a['complete_actual_D'], 'independent_scope': a['independent_scope_coverage'],
            'independent_scope_count': 766, 'runtime_profile': self.evidence['profile_ref'],
            'source_financially_verified_in_full': False, 'qualified': False}
        self.identity = deepcopy(self.proof)
        _LIVE.add(self)
        self.guard()

    def guard(self):
        require(type(self) is NativeScopeAdmission and self in _LIVE and self.proof == self.identity,
            'A genuine current opaque scoped admission is required')
        self.references.guard()
        require(hashlib.sha256(json.dumps(self.evidence, sort_keys=True).encode()).hexdigest() == self.evidence_sha256,
            'The admitted financial plan or evidence changed in memory')
        require(self.helper.recipes() == self.recipe, 'The scoped financial/task validation code changed')
        return deepcopy(self.proof)


def admission(value):
    require(type(value) is NativeScopeAdmission and value in _LIVE,
        'Persisted JSON, fabricated objects and another task family cannot supply scoped admission')
    return value.guard()


def validate_seed(seed, admissions):
    require(seed.get('source_kind') == NORMAL_SOURCE_KIND and seed.get('variant') == 0,
        'This family requires explicit scoped native task views')
    source = reference(seed['local_path'])
    require(seed['sha256'] == source['sha256'] and seed['modes']
        and len(set(seed['modes'])) == len(seed['modes']), 'The source or selected modes changed')
    for mode in seed['modes']:
        proof = admission(admissions.get((source['sha256'], mode)))
        require(proof['workbook'] == source
            and seed['finance_evidence']['scoped_task_admissions'][mode] == proof,
            'The persisted seed differs from its actual scoped task proof')


class NativeQualityFactory(FactoryPipeline):
    def __init__(self, config, *args, admissions, **kwargs):
        validate_configuration(config)
        self.admissions = {}
        for value in admissions:
            proof = admission(value)
            key = (proof['workbook']['sha256'], proof['mode'])
            require(key not in self.admissions, 'A source/mode task was duplicated')
            self.admissions[key] = value
        require(self.admissions, 'At least one independently scoped actual task is required')
        require(config['run']['targets'] == {m: sum(k[1] == m for k in self.admissions)
            for m in ('financial_modeling', 'debugging')}, 'Quotas must equal the declared actual task inventory')
        super().__init__(config, *args, **kwargs)

    def load_seeds(self):
        seeds = super().load_seeds()
        for seed in seeds:
            validate_seed(seed, self.admissions)
        require({(s['sha256'], m) for s in seeds for m in s['modes']} == set(self.admissions),
            'The exact admitted source/mode inventory changed')
        return seeds

    def run_phase(self, context, phase):
        key = (reference(context.source)['sha256'], context.mode)
        value = self.admissions.get(key)
        admission(value)
        context.data['_native_scope_admission'] = value
        return super().run_phase(context, phase)

    def _claim_targets(self, context):
        admission(context.data.get('_native_scope_admission'))
        require(not context.data['plan'].get('scenario_inputs') and 'mask_ranges' not in context.data['plan'],
            'The admitted task cannot change public financial assumptions or physical scope')
        return super()._claim_targets(context)

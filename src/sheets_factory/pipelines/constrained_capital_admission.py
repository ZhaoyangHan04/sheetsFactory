"""Explicit first-D02 admission using unchanged financial/source checks.

The source proof is canonical within an isolated live session. Existing D01
admission and all running task recipes remain unchanged.
"""
from __future__ import annotations
from copy import deepcopy
import importlib.util
from pathlib import Path
from . import scaled_capital_admission as shared
from .factory import FactoryPipeline
from ..workbook.capital_allocation_scaled import constrained_catalog as catalog
from ..workbook.capital_allocation_scaled import ledger,spec,validate

ROOT=Path(__file__).resolve().parents[3]
SOURCE_KIND='independently_audited_constrained_capital_allocation_source'
METHOD='complete_independent_constrained_AB_search_and_Decimal_actual_formula_audit_v1'
PROFILE_ID='30-D02'
FORMULA_COUNT=77513
PLAN_COUNT=1<<30
IMAGE_ID=shared.IMAGE_ID
SHARED_HELPER_SHA256='f2d9028993026e61832920d2f1efc6d139dcc2a67328aa16dd37216058b2c0e8'
BUILDER_SHA256='d83b7f95cff63278e38e5ef99dbb502a18dd482e75ac1322022d19dbc68dc419'
require=shared.require
reference=shared.reference
ReferenceSession=shared.ReferenceSession
verify_references=shared.verify_references
compare_exact_typed=shared.compare_exact_typed
_actual_calls=shared._actual_calls


def _builder(session):
    path=ROOT/'scripts/build_constrained_capital_source.py'
    require(session.ref(path)['sha256']==BUILDER_SHA256,'The frozen constrained source builder changed')
    definition=importlib.util.spec_from_file_location('_checked_constrained_source_builder',path)
    module=importlib.util.module_from_spec(definition);definition.loader.exec_module(module)
    return module



def validate_source(source_manifest, *, session=None):
    """Validate the full source, without executing search kernels, LO or models."""
    require(session is None or isinstance(session, ReferenceSession), 'An internal reference validation session is required')
    # A caller may already have checked entry/config/task artifacts. They are
    # not source dependencies and must never affect the canonical source proof.
    # Only successful source validation is merged back into that live cache.
    source_session = ReferenceSession()
    proof = _validate_source(source_manifest, session=source_session)
    if session is not None:
        session._merge_validated_source(source_session)
    return proof


def _validate_source(source_manifest, *, session):
    require(session.ref(shared.__file__)['sha256'] == SHARED_HELPER_SHA256,
            'The corrected shared source-reference/resource helpers changed')
    if isinstance(source_manifest, (str, Path)):
        source_manifest = session.ref(source_manifest)
    source = session.read(source_manifest)
    require(source.get('kind') == 'independently_verified_constrained_capital_allocation_source'
            and type(source.get('version')) is int and source['version'] == 1
            and source.get('status') == 'source_verified_not_task_quality_or_difficulty_qualified'
            and source.get('profile_id') == PROFILE_ID and source.get('project_count') == 30
            and source.get('physical_formula_count') == FORMULA_COUNT
            and source.get('financial_audit_passed') is True
            and type(source.get('actual_LO_recalculations')) is int and source['actual_LO_recalculations'] == 3
            and type(source.get('model_calls')) is int and source['model_calls'] == 0
            and type(source.get('new_enumeration_calls')) is int and source['new_enumeration_calls'] == 0
            and source.get('quality_or_difficulty_certified') is False
            and source.get('qualified') is False and type(source.get('task_count')) is int and source['task_count'] == 0,
            'Only the actual complete first scaled source is admitted')
    require(source.get('raw_ancestors') == spec.RAW_ANCESTORS and source.get('source_original_ancestors') == 2
            and source.get('raw_ancestry_is_provenance_only') is True
            and source.get('hypothetical_forecasts_and_policy') is True,
            'Retain both original ancestors without an unchanged-source claim')
    for flag in ('task_input_and_complete_D_not_built', 'gold_decisions_and_financials_require_normal_task_masking',
                 'plan_dependent_helper_caches_require_clearing_and_actual_input_recalculation',
                 'complete_required_D_must_include_changed_arithmetic_helpers',
                 'full_public_sidecar_contract_must_be_transferred_to_task',
                 'five_controls_recovery_all12_quality_Harbor_and_difficulty_pending'):
        require(source.get(flag) is True, 'A required downstream source boundary is missing: ' + flag)
    builder = _builder(session)
    preparation_ref = source['source_preparation']
    preparation_path = session.check(preparation_ref)
    # This is the sole complete dual-proof validation in this admission. The
    # frozen builder re-hashes every actual binary chunk; it never enumerates.
    frozen = builder.validate_prepared(preparation_path.parent)
    require(frozen == session.read(preparation_ref)
            and source.get('source_recipe_sha256') == frozen['recipe_sha256'] == builder.recipes(),
            'The source preparation or its entire financial implementation recipe differs')
    dual = session.read(source['validated_dual_proof'])
    require(source['validated_dual_proof'] == frozen['validated_dual_proof']
            and source['dual_search_proof'] == frozen['dual_search_proof'], 'The source optimisation proof changed')
    session._adopt_builder_checked(dual['verified_artifacts'])
    require(dual['terminal']['records_equal_complete'] is True and dual['terminal']['plan_count'] == PLAN_COUNT
            and dual['rank']['unique_best'] is True and dual['rank']['gap_pence'] >= 1,
            'Both complete independent searches and a unique one-penny gap are required')
    for path, digest in source['source_recipe_sha256'].items():
        require(session.ref(path)['sha256'] == digest, 'A source calculation or public schema implementation changed')
    artifacts = source['public_contract_artifacts']
    require(artifacts == frozen['copied_public_contract_artifacts']
            and source['public_specification'] == artifacts['spec'], 'The full public sidecar contract is incomplete')
    public = spec.load_spec(session.read(source['public_specification']))
    require(session.read(artifacts['candidate_contract']) == catalog.public_contract(PROFILE_ID)
            and session.check(artifacts['candidate_contract_markdown']).read_text()
                == catalog.contract_markdown(catalog.public_contract(PROFILE_ID)), 'Public candidate or summary semantics changed')
    plan = ledger.validate_plan(public, dual['rank']['best_plan'])
    forward = ledger.simulate(public, plan)
    require(forward == session.read(source['independent_ledger']) == session.read(dual['best_ledger'])
            and forward['feasible'] is True and forward['objective_pence'] == dual['rank']['objective_pence'],
            'The winning forward financial journal differs from the complete raw public primitives')
    bindings = session.read(source['bindings'])
    require(bindings.get('formula_count') == FORMULA_COUNT and bindings.get('gold_plan_supplied') is True
            and bindings.get('optimisation_performed') is False
            and len(bindings.get('financial_bindings', [])) == 25511
            and len(bindings.get('decision_bindings', [])) == 30
            and len(bindings.get('arithmetic_bindings', [])) == 51972
            and bindings.get('arithmetic_support_values_are_protected') is False
            and bindings.get('plan_dependent_caches_must_be_cleared_before_task_input') is True
            and bindings.get('task_input_requires_actual_recalculation_and_audit') is True
            and bindings.get('complete_required_D_includes_changed_arithmetic_helpers') is True,
            'The entire financial, decision and unprotected plan-dependent support scope is required')
    _actual_calls(source, frozen, session)
    for call, audit_ref in zip(source['engine_calls'], source['financial_audits']):
        report = session.read(audit_ref)
        expected = {'workbook': call['output'], **validate.audit_capital_allocation_workbook(
            session.check(call['output']), public, plan, forward, bindings)}
        require(expected == report and report.get('passed') is True
                and report.get('formula_count') == report.get('checked_cells') == FORMULA_COUNT
                and report.get('all_formula_cells_independently_covered') is True
                and report.get('all_scenarios_feasible') is True and report.get('all_journals_balance') is True
                and report.get('mismatches') == [] and report.get('control_mismatches') == [],
                'A complete actual 77,513-formula audit cannot be reproduced')
    workbook = source['workbook']
    require(source.get('derived_workbook_sha256') == workbook['sha256']
            and Path(source['local_path']).absolute() == Path(workbook['path']), 'The financial workbook identity changed')
    stability = {'first_against_goal': compare_exact_typed(workbook['path'], source['engine_calls'][1]['output']['path']),
                 'second_against_goal': compare_exact_typed(workbook['path'], source['engine_calls'][2]['output']['path'])}
    stability['stable'] = all(row['passed'] is True for row in stability.values())
    require(stability['stable'] is True and stability == session.read(source['stability']),
            'The entire financial source is not exact typed stable over both further actual passes')
    verify_references(source, session=session)
    result = {'kind': 'checked_first_constrained_capital_source_admission', 'validation_method': METHOD,
        'profile_id': PROFILE_ID, 'project_count': 30, 'physical_formula_count': FORMULA_COUNT,
        'workbook': deepcopy(workbook), 'source_manifest': deepcopy(source_manifest),
        'public_specification': deepcopy(source['public_specification']), 'bindings': deepcopy(source['bindings']),
        'independent_ledger': deepcopy(source['independent_ledger']), 'dual_search_proof': deepcopy(source['dual_search_proof']),
        'validated_dual_proof': deepcopy(source['validated_dual_proof']), 'catalog_manifest': deepcopy(frozen['catalog_manifest']),
        'public_candidate_contract': deepcopy(artifacts['candidate_contract']), 'public_contract_artifacts': deepcopy(artifacts),
        'financial_audits': deepcopy(source['financial_audits']), 'stability': deepcopy(source['stability']),
        'runtime_profile': deepcopy(source['runtime_profile']), 'runtime': deepcopy(source['runtime']),
        'source_recipe_sha256': deepcopy(source['source_recipe_sha256']),
        'source_builder': session.ref(ROOT / 'scripts/build_constrained_capital_source.py'),
        'admission_implementation': session.ref(__file__),
        'shared_admission_helpers': session.ref(shared.__file__),
        'agent_and_verifier_resources_actually_verified': False,
        'quality_or_difficulty_certified': False}
    verify_references(result, session=session)
    result['verified_artifacts'] = {path: dict(record) for path, (record, _) in session._checked.items()}
    result['artifact_sha256'] = {path: record['sha256'] for path, (record, _) in session._checked.items()}
    session._proofs.add(spec.canonical_sha(result))
    return result


def verify_admitted_proof(proof, *, session=None):
    """Reuse only a proof validated in this live session; otherwise validate fully."""
    session = session or ReferenceSession()
    require(isinstance(proof, dict) and proof.get('kind') == 'checked_first_constrained_capital_source_admission'
            and proof.get('validation_method') == METHOD and proof.get('profile_id') == PROFILE_ID
            and proof.get('quality_or_difficulty_certified') is False, 'A complete scaled source admission is required')
    identity = spec.canonical_sha(proof)
    if identity not in session._proofs:
        require(validate_source(proof['source_manifest'], session=session) == proof,
                'The supplied source admission cannot be independently reproduced')
    verify_references(proof, session=session)
    require(session.ref(__file__) == proof['admission_implementation']
            and session.ref(ROOT / 'scripts/build_constrained_capital_source.py') == proof['source_builder'],
            'The admission or full-source builder implementation changed')
    return proof


class ConstrainedCapitalFactory(FactoryPipeline):
    """One first-source FM with ordinary scheduling, task budgets and gates."""
    def __init__(self, *args, admitted_proof=None, admission_session=None, **kwargs):
        self.admission_session = admission_session or ReferenceSession()
        verify_admitted_proof(admitted_proof, session=self.admission_session)
        self.admitted_proof = deepcopy(admitted_proof)
        super().__init__(*args, **kwargs)

    def load_seeds(self):
        seeds = super().load_seeds()
        require(self.targets == {'financial_modeling': 1, 'debugging': 0} and len(seeds) == 1,
                'Only first-development thirty-project FM is admitted')
        verify_admitted_proof(self.admitted_proof, session=self.admission_session)
        seed = seeds[0]
        source = self.admission_session.ref(seed['local_path'])
        evidence = seed.get('finance_evidence', {})
        require(seed.get('source_kind') == SOURCE_KIND and seed.get('profile_id') == PROFILE_ID
                and seed.get('modes') == ['financial_modeling']
                and type(seed.get('variant', 0)) is int and seed.get('variant', 0) == 0
                and seed.get('sha256') == source['sha256'] and source == self.admitted_proof['workbook']
                and evidence.get('audited_source_binding') == self.admitted_proof
                and evidence.get('source_manifest') == self.admitted_proof['source_manifest'],
                'The exact prospectively declared, independently audited source is required')
        seed['survey'] = {**seed.get('survey', {}), 'normalized_path': source['path'], 'status': 'ok', 'error_count': 0}
        return seeds

    def run_phase(self, context, phase):
        context.data['_constrained_admission_session'] = self.admission_session
        verify_admitted_proof(self.admitted_proof, session=self.admission_session)
        require(self.admission_session.ref(context.source) == self.admitted_proof['workbook'],
                'The admitted source changed before a task phase')
        result = super().run_phase(context, phase)
        require(self.admission_session.ref(context.source) == self.admitted_proof['workbook'],
                'The admitted source changed during a task phase')
        if context.data.get('baseline'):
            require(self.admission_session.ref(context.data['baseline'])['sha256']
                    == context.data.get('source_id') == self.admitted_proof['workbook']['sha256'],
                    'Normalization changed the exact independently audited financial source')
        return result

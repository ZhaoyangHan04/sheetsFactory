"""Admit one complete scaled financial source without another enumeration.

Large files are hashed in blocks. A live validation session deduplicates those
reads; it never becomes a persisted substitute for source validation.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import re

from .factory import FactoryPipeline
from ..task_adapters.lease_family import compare_exact_typed
from ..workbook.capital_allocation_scaled import catalog, ledger, spec, validate
from ..workbook import resource_engine

ROOT = Path(__file__).resolve().parents[3]
SOURCE_KIND = 'independently_audited_scaled_capital_allocation_source'
METHOD = 'complete_independent_scaled_AB_search_and_Decimal_actual_formula_audit_v1'
BUILDER_SHA256 = 'c864e88708ed4a492917457d8dc74a2b613215b576d688ec87e403987f94ebf0'
FORMULA_COUNT = 77513
PLAN_COUNT = 1 << 30
PROFILE_ID = '30-D01'
IMAGE_ID = 'sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _path(path):
    path = Path(path).absolute()
    require(path == path.resolve() and path.is_file(), 'Use a real absolute artifact without symlink components')
    return path


def _identity(path):
    value = path.stat()
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def reference(path):
    path = _path(path)
    before = _identity(path)
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    require(_identity(path) == before, 'An artifact changed during its complete streaming hash')
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': before[2]}


def _reference_shape(record):
    require(isinstance(record, dict) and set(record) == {'path', 'sha256', 'bytes'}
            and type(record['path']) is str and type(record['sha256']) is str
            and re.fullmatch('[0-9a-f]{64}', record['sha256'])
            and type(record['bytes']) is int and record['bytes'] >= 0,
            'A complete SHA256/byte-count artifact reference is required')


class ReferenceSession:
    """One-process cache for immutable, fully checked source artifacts.

    Small artifacts are re-hashed at each guard. A changed inode, size, mtime or
    ctime forces another complete large-file hash and must still match the
    original digest. Fresh processes have no admitted-proof cache.
    """
    def __init__(self):
        self._checked = {}
        self._proofs = set()

    def check(self, record):
        _reference_shape(record)
        path = _path(record['path'])
        previous = self._checked.get(str(path))
        require(previous is None or previous[0] == record, 'Conflicting source artifact references')
        # Source identities, code and small receipts are cheap to re-hash and
        # must not depend on timestamp granularity on a shared filesystem.
        if previous is None or record['bytes'] <= 16 * 1024**2 or previous[1] != _identity(path):
            require(reference(path) == record, 'A bound source artifact changed: ' + str(path))
            self._checked[str(path)] = (dict(record), _identity(path))
        return path

    def ref(self, path):
        path = _path(path)
        previous = self._checked.get(str(path))
        if previous is not None:
            self.check(previous[0])
            return dict(previous[0])
        record = reference(path)
        self._checked[str(path)] = (record, _identity(path))
        return dict(record)

    def read(self, record):
        with self.check(record).open(encoding='utf-8') as stream:
            value = json.load(stream, object_pairs_hook=_unique,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite evidence JSON')))
        require(isinstance(value, dict), 'Evidence JSON must contain an object')
        return value

    def _adopt_builder_checked(self, records):
        # Called only immediately after the frozen builder independently
        # streams and validates its complete actual proof in this process.
        for path, record in records.items():
            _reference_shape(record)
            require(path == record['path'] and _path(path).stat().st_size == record['bytes'],
                    'A just-verified builder artifact changed')
            previous = self._checked.get(path)
            require(previous is None or previous[0] == record, 'Conflicting checked builder artifacts')
            self._checked[path] = (dict(record), _identity(Path(path)))

    def _merge_validated_source(self, source_session):
        """Adopt a completed source validation without importing caller state.

        Check every overlap before changing this cache. Large artifacts retain
        their just-validated identities, so later node guards do not read both
        complete record streams again when those files remain unchanged.
        """
        require(isinstance(source_session, ReferenceSession), 'Merge only an internal source validation session')
        for path, (record, _) in source_session._checked.items():
            previous = self._checked.get(path)
            require(previous is None or previous[0] == record, 'Conflicting source artifact references during session merge')
        for path, (record, identity) in list(source_session._checked.items()):
            if _identity(_path(path)) != identity:
                source_session.check(record)
        self._checked.update({path: (dict(record), identity)
            for path, (record, identity) in source_session._checked.items()})
        self._proofs.update(source_session._proofs)


def _unique(pairs):
    value = {}
    for name, item in pairs:
        require(name not in value, 'Duplicate evidence JSON key')
        value[name] = item
    return value


def verify_references(value, *, session=None):
    """Deduplicate a traversal and reuse checked large files in this live session."""
    session = session or ReferenceSession()
    require(isinstance(session, ReferenceSession), 'An internal reference validation session is required')
    seen = set()

    def walk(item):
        if isinstance(item, dict):
            if 'path' in item and 'sha256' in item:
                _reference_shape(item)
                previous = session._checked.get(item['path'])
                require(previous is None or previous[0] == item, 'Conflicting source artifact references')
                if item['path'] not in seen:
                    session.check(item)
                    seen.add(item['path'])
            else:
                for child in item.values(): walk(child)
        elif isinstance(item, list):
            for child in item: walk(child)

    walk(value)
    return {path: record['sha256'] for path, (record, _) in session._checked.items()}


def _builder(session):
    path = ROOT / 'scripts/build_scaled_capital_source.py'
    require(session.ref(path)['sha256'] == BUILDER_SHA256, 'The frozen scaled source builder changed')
    module_spec = importlib.util.spec_from_file_location('_checked_scaled_source_builder', path)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def _stamp(value):
    require(type(value) is str, 'Actual execution timestamps are required')
    stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(stamp.tzinfo is not None, 'Execution timestamps need an explicit timezone')
    return stamp


def _actual_calls(source, frozen, session):
    calls, reports = source['engine_calls'], source['financial_audits']
    profile = resource_engine.load_runtime_profile(session.check(source['runtime_profile']))
    require(profile == frozen['runtime_profile_value'] and profile['id'] == 'entity_group_large_v2',
            'The source must use the explicit 32-GiB resource profile')
    runtime = source['runtime']
    require(runtime.get('image_id') == IMAGE_ID and runtime.get('backend') == 'libreoffice_uno_docker'
            and runtime.get('network') == 'none' and runtime.get('macro_execution') == 'never'
            and runtime.get('external_updates') == 'never' and runtime.get('role') == 'source'
            and runtime.get('runtime_profile') == profile
            and runtime.get('runtime_profile_binding') == source['runtime_profile']
            and runtime.get('actual_calculation_calls_recorded') == 3
            and source.get('agent_and_verifier_resources_actually_verified') is False,
            'Source execution cannot certify unexecuted agent/verifier roles')
    require(len(calls) == len(reports) == 3 and [c.get('index') for c in calls] == [1, 2, 3]
            and len(runtime.get('actual_resource_receipts', [])) == 3,
            'The normalization and both further actual LO passes are required')
    require(calls[0]['output'] == source['workbook'] and calls[1]['input'] == calls[0]['output']
            and calls[2]['input'] == calls[1]['output'], 'The three actual recalculation outputs are not chained')
    for call, resource_ref in zip(calls, runtime['actual_resource_receipts']):
        require(type(call['index']) is int and call.get('completed') is True
                and call.get('resource_receipt') == resource_ref
                and call.get('destination') == call['output']['path'], 'An actual source call is incomplete')
        directory = session.check(call['output']).parent
        started = session.read(session.ref(directory / f"LO_pass{call['index']}_started.json"))
        terminal = session.read(session.ref(directory / f"LO_pass{call['index']}_terminal.json"))
        require(started == {key: call[key] for key in ('index', 'input', 'destination', 'started_at')}
                | {'completed': False}
                and terminal == {key: value for key, value in call.items() if key != 'resource_receipt'},
                'The actual LO started/terminal receipt differs from its manifest call')
        resource = session.read(resource_ref)
        expected_resources = profile['docker_resources']['source']
        require(resource.get('kind') == 'resource_bound_libreoffice_call' and resource.get('status') == 'completed'
                and resource.get('role') == 'source' and resource.get('actual_resources_verified') is True
                and resource.get('source') == call['input'] and resource.get('output') == call['output']
                and resource.get('profile') == source['runtime_profile']
                and resource.get('image_id') == IMAGE_ID
                and resource.get('implementation') == session.ref(resource_engine.__file__)
                and resource.get('requested_resources') == expected_resources
                and resource.get('actual_resources') == {'cpus_nanoseconds': 2 * 10**9,
                    'memory_bytes': 32 * 1024**3, 'pids_limit': expected_resources['pids_limit']}
                and all(type(v) is int for v in resource['actual_resources'].values())
                and resource.get('workbook_file_timeout_seconds') == 600
                and resource.get('verifier_total_timeout_seconds') == 2400
                and resource.get('solver_tool_budget') == profile['solver_tool_budget'],
                'The actual source CPU/memory/PID/image/input enforcement evidence differs')
        require(_stamp(call['started_at']) <= _stamp(resource['started_at'])
                <= _stamp(resource['finished_at']) <= _stamp(call['finished_at']),
                'Actual calculation timestamps are inconsistent')
    return profile


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
    if isinstance(source_manifest, (str, Path)):
        source_manifest = session.ref(source_manifest)
    source = session.read(source_manifest)
    require(source.get('kind') == 'independently_verified_scaled_capital_allocation_source'
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
    result = {'kind': 'checked_first_scaled_capital_source_admission', 'validation_method': METHOD,
        'profile_id': PROFILE_ID, 'project_count': 30, 'physical_formula_count': FORMULA_COUNT,
        'workbook': deepcopy(workbook), 'source_manifest': deepcopy(source_manifest),
        'public_specification': deepcopy(source['public_specification']), 'bindings': deepcopy(source['bindings']),
        'independent_ledger': deepcopy(source['independent_ledger']), 'dual_search_proof': deepcopy(source['dual_search_proof']),
        'validated_dual_proof': deepcopy(source['validated_dual_proof']), 'catalog_manifest': deepcopy(frozen['catalog_manifest']),
        'public_candidate_contract': deepcopy(artifacts['candidate_contract']), 'public_contract_artifacts': deepcopy(artifacts),
        'financial_audits': deepcopy(source['financial_audits']), 'stability': deepcopy(source['stability']),
        'runtime_profile': deepcopy(source['runtime_profile']), 'runtime': deepcopy(source['runtime']),
        'source_recipe_sha256': deepcopy(source['source_recipe_sha256']),
        'source_builder': session.ref(ROOT / 'scripts/build_scaled_capital_source.py'),
        'admission_implementation': session.ref(__file__),
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
    require(isinstance(proof, dict) and proof.get('kind') == 'checked_first_scaled_capital_source_admission'
            and proof.get('validation_method') == METHOD and proof.get('profile_id') == PROFILE_ID
            and proof.get('quality_or_difficulty_certified') is False, 'A complete scaled source admission is required')
    identity = spec.canonical_sha(proof)
    if identity not in session._proofs:
        require(validate_source(proof['source_manifest'], session=session) == proof,
                'The supplied source admission cannot be independently reproduced')
    verify_references(proof, session=session)
    require(session.ref(__file__) == proof['admission_implementation']
            and session.ref(ROOT / 'scripts/build_scaled_capital_source.py') == proof['source_builder'],
            'The admission or full-source builder implementation changed')
    return proof


class ScaledCapitalFactory(FactoryPipeline):
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
        require(seed.get('source_kind') == SOURCE_KIND and seed.get('modes') == ['financial_modeling']
                and type(seed.get('variant', 0)) is int and seed.get('variant', 0) == 0
                and seed.get('sha256') == source['sha256'] and source == self.admitted_proof['workbook']
                and evidence.get('audited_source_binding') == self.admitted_proof
                and evidence.get('source_manifest') == self.admitted_proof['source_manifest'],
                'The exact prospectively declared, independently audited source is required')
        seed['survey'] = {**seed.get('survey', {}), 'normalized_path': source['path'], 'status': 'ok', 'error_count': 0}
        return seeds

    def run_phase(self, context, phase):
        context.data['_scaled_admission_session'] = self.admission_session
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

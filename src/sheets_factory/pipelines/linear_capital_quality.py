"""Explicit native linear-portfolio source admission.

Source validators execute once in a cold process. Later nodes use an opaque
in-process object and content-bound file guards, never a persisted pass flag.
This module does not start engines, models, optimizers or Harbor services.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import stat
import sys
import weakref

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROVIDERS = ROOT / 'config/task_adapters/linear_capital_source_providers_v1.json'
_ACTIVE_SOURCES = weakref.WeakSet()
_MODULES = {}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def _fingerprint(path):
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and not path.is_symlink()
        and path == path.resolve(), 'A real nonsymlink artifact is required')
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns,
        info.st_ctime_ns, info.st_mode, info.st_nlink)


def reference(value):
    path = Path(value).absolute()
    before = _fingerprint(path)
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(4 * 1024**2), b''):
            digest.update(block)
    require(_fingerprint(path) == before, 'An artifact changed while hashing')
    return {'path': str(path), 'sha256': digest.hexdigest(), 'bytes': before[2]}


class References:
    """Content-check once, then rehash any changed filesystem identity."""
    def __init__(self):
        self.files = {}
        self.fingerprints = {}
        self._json_seen = set()
        self.large_json_leaves = []
        self.container_artifact_bindings = []
        self._container_json_contexts = {}

    def check(self, record):
        require(type(record) is dict and set(record) == {'path', 'sha256', 'bytes'}
            and type(record['path']) is str and type(record['bytes']) is int and record['bytes'] >= 0
            and type(record['sha256']) is str and re.fullmatch('[0-9a-f]{64}', record['sha256']),
            'A complete SHA256/bytes/path reference is required')
        path = Path(record['path'])
        require(path.is_absolute(), 'Artifact references must use absolute paths')
        current = _fingerprint(path)
        prior = self.files.get(str(path))
        require(prior is None or prior == record, 'Conflicting references name one physical file')
        # Some filesystems can preserve ctime within one clock tick after a
        # same-length write plus mtime restoration. Always hash small code,
        # configuration and receipts; metadata caching is only a performance
        # guard for large controlled workbook/financial payloads. A fresh cold
        # admission still hashes every complete large artifact.
        if record['bytes'] <= 2 * 1024**2 or self.fingerprints.get(str(path)) != current:
            require(reference(path) == record, 'A bound artifact changed: ' + str(path))
            self.fingerprints[str(path)] = current
        self.files[str(path)] = deepcopy(record)
        return path

    def walk(self, value):
        if isinstance(value, dict):
            if set(value) == {'path', 'sha256', 'bytes'}:
                self.check(value)
            else:
                for item in value.values():
                    self.walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                self.walk(item)

    def guard(self):
        for record in tuple(self.files.values()):
            self.check(record)

    def discover(self, record):
        """Follow small evidence records; large financial payloads stay opaque.

        Large tables are guarded by their complete byte SHA. A consumer that
        interprets references inside such a payload must also walk that parsed
        object. No large financial table is decoded just to guard its bytes.
        """
        path = self.check(record)
        if path.suffix.lower() != '.json' or str(path) in self._json_seen:
            return
        self._json_seen.add(str(path))
        if record['bytes'] > 2 * 1024**2:
            self.large_json_leaves.append(deepcopy(record))
            return
        value = self.read(record)
        def descend(item, aliases=None):
            if isinstance(item, dict):
                if set(item) == {'path', 'sha256', 'bytes'}:
                    if str(item['path']).startswith('/app/'):
                        key = (item['path'], item['sha256'], item['bytes'])
                        require(aliases is not None and key in aliases,
                            'An unmapped container-local artifact is not a host reference')
                        self.check(aliases[key])
                    else:
                        self.discover(item)
                else:
                    local = self._solver_artifact_aliases(item)
                    context = local if local is not None else aliases
                    for nested in item.values():
                        descend(nested, context)
            elif isinstance(item, (tuple, list)):
                for nested in item:
                    descend(nested, aliases)
        descend(value, self._container_json_contexts.get(str(path)))

    def _solver_artifact_aliases(self, value):
        """Map only the frozen native-result descriptor schema to actual files.

        Source validation already checked the complete native execution. This
        repeats the exact host/mount/file identities needed for recursive file
        guards; it does not accept arbitrary missing paths or self-reported flags.
        """
        fields = {'preparation','terminal','host_before','host_after','cleanup',
            'solver_result','runtime_result','checked_optimal','solver','matrix_result_check'}
        if set(value) != fields:
            return None
        require(value['checked_optimal'] is True, 'A container artifact map requires a completed checked native result')
        preparation, terminal = self.read(value['preparation']), self.read(value['terminal'])
        kinds = {'prepared_private_linear_capital_integer_solver':
            ('private_linear_capital_integer_solver_execution',2),
            'prepared_private_linear_capital_producer16_solver':
            ('private_linear_capital_producer16_solver_execution',16)}
        require(preparation.get('kind') in kinds, 'Unknown native solver preparation for container artifacts')
        terminal_kind, cpus = kinds[preparation['kind']]
        require(type(preparation.get('version')) is int and preparation['version']==1
            and terminal.get('kind')==terminal_kind and type(terminal.get('version')) is int and terminal['version']==1
            and terminal.get('status')=='reference_optimal_checked'
            and terminal.get('preparation')==value['preparation'] and terminal.get('solver_result')==value['solver_result']
            and terminal.get('runtime_result')==value['runtime_result'] and terminal.get('cleanup')==value['cleanup'],
            'The complete native host preparation/execution chain changed')
        bundle = Path(preparation['bundle'])
        require(bundle.is_absolute() and bundle==bundle.resolve()
            and bundle==Path(value['preparation']['path']).parent/'job_bundle',
            'The container artifact bundle is not the exact prepared host directory')
        before, after = self.read(value['host_before']), self.read(value['host_after'])
        identifier = terminal['container_id']
        require(type(identifier) is str and re.fullmatch('[0-9a-f]{64}',identifier)
            and before.get('Id')==after.get('Id')==identifier
            and terminal.get('actual_resources_verified') is True
            and preparation['image_id']==before.get('Image')==after.get('Image')==terminal.get('image_id')
                =='sha256:b3a295b1ea8e88931893a96d8e5f1af97a998333a02189103bef5d223d13e043'
            and preparation.get('resources')=={'cpus':cpus,'memory_bytes':32*1024**3,'pids_limit':256},
            'The actual container identity/resources differ from its prepared host bundle')
        for actual, state in ((before,'created'),(after,'exited')):
            mounts=actual.get('Mounts',[]);status=actual.get('State',{})
            require(actual.get('NanoCpus')==cpus*10**9 and actual.get('Memory')==32*1024**3
                and actual.get('PidsLimit')==256 and actual.get('NetworkMode')=='none'
                and len(mounts)==1 and mounts[0].get('Type')=='bind' and mounts[0].get('RW') is True
                and mounts[0].get('Source')==str(bundle) and mounts[0].get('Destination')=='/app'
                and status.get('Status')==state and status.get('Running') is False
                and status.get('OOMKilled') is False and type(status.get('ExitCode')) is int and status['ExitCode']==0,
                'The actual container mount or normal lifecycle does not justify a host artifact map')
        solver = self.read(value['solver_result'])
        require(solver==value['solver'], 'An inline native result differs from its exact host JSON')
        backend=preparation['request']['backend']
        require(solver.get('checked_optimal') is True
            and ((backend=='scip' and solver.get('kind')=='independent_A_SCIP_single_attempt'
                and type(solver.get('version')) is int and solver['version']==1 and solver.get('completed') is True)
                or (backend=='cp_sat' and solver.get('backend')=='ortools_cp_sat'
                    and solver.get('solver_version')=='9.14.6206')),
            'Unknown native result descriptor schema')
        names=({'log_artifact':'solver.log','model_artifact':'native_model.cip'} if backend=='scip' else
            {'log_reference':'solver.log','model_reference':'native_model.pbtxt',
             'parameters_reference':'native_model.pbtxt.parameters.pbtxt'} if backend=='cp_sat' else None)
        require(names is not None, 'Unknown native solver artifact names')
        inventory=terminal['retained_job_inventory']
        require(inventory==terminal['complete_job_inventory']
            and inventory.get('solver_result.json')==value['solver_result'], 'The actual native host output inventory changed')
        aliases={}
        for field, name in names.items():
            local=solver[field];host=inventory[name]
            require(type(local) is dict and set(local)=={'path','sha256','bytes'}
                and local['path']=='/app/'+name and host['path']==str(bundle/name)
                and local['sha256']==host['sha256'] and type(local['bytes']) is int and local['bytes']==host['bytes'],
                'A container-local solver descriptor differs from the exact host artifact')
            self.check(host);aliases[local['path'],local['sha256'],local['bytes']]=host
            self.container_artifact_bindings.append({'container':deepcopy(local),'host':deepcopy(host),
                'preparation':deepcopy(value['preparation']),'terminal':deepcopy(value['terminal'])})
        owner=str(Path(value['solver_result']['path']))
        prior=self._container_json_contexts.get(owner)
        require(prior is None or prior==aliases, 'Conflicting container artifact contexts name one native result')
        self._container_json_contexts[owner]=aliases
        return aliases

    def read(self, value):
        record = value if isinstance(value, dict) else reference(value)
        path = self.check(record)
        result = json.loads(path.read_text(encoding='utf-8'))
        self.check(record)
        return result


def _load_provider(record, references):
    path = references.check(record)
    require(path.suffix == '.py' and path.is_relative_to(ROOT),
        'A provider must be an explicitly frozen local Python module')
    key = (str(path), record['sha256'])
    if key not in _MODULES:
        name = '_linear_quality_provider_' + record['sha256']
        definition = importlib.util.spec_from_file_location(name, path)
        require(definition is not None and definition.loader is not None, 'The provider cannot be loaded')
        module = importlib.util.module_from_spec(definition)
        sys.modules[name] = module
        definition.loader.exec_module(module)
        references.check(record)
        _MODULES[key] = module
    return _MODULES[key]


def _configured_module(record):
    require(type(record) is dict and set(record) == {'path', 'sha256', 'bytes'}
        and type(record['path']) is str, 'An explicit project-relative provider module is required')
    name = record['path']
    require(name and '\\' not in name and not Path(name).is_absolute()
        and all(part not in ('', '.', '..') for part in name.split('/')),
        'Provider modules must use canonical project-relative paths without traversal')
    path = ROOT / name
    require(path == path.resolve() and path.is_relative_to(ROOT),
        'Provider modules cannot escape the checkout or use symlinks')
    return {**record, 'path': str(path)}


class SourceProviders:
    """A frozen registry is the only way to add a source-validator provider."""
    def __init__(self, value=DEFAULT_PROVIDERS):
        self.references = References()
        self.reference = value if isinstance(value, dict) else reference(value)
        registry = self.references.read(self.reference)
        require(type(registry) is dict and registry.get('kind') == 'linear_capital_source_provider_registry'
            and type(registry.get('version')) is int and registry['version'] == 1,
            'The explicit linear source-provider registry is required')
        rows = registry.get('providers')
        require(type(rows) is list and bool(rows), 'At least one explicit provider is required')
        self.providers = {}
        for row in rows:
            require(type(row) is dict and set(row) == {'id', 'module', 'source_kind', 'api_version', 'functions'}
                and type(row['id']) is str and re.fullmatch('[a-z][a-z0-9_]*', row['id'])
                and row['id'] not in self.providers and type(row['source_kind']) is str and row['source_kind']
                and type(row['api_version']) is int and row['api_version'] == 1
                and row['functions'] == {'validate_source': 'validate_source',
                    'validate_actual_call': 'validate_actual_call', 'runtime': 'runtime'},
                'An explicit unique provider with the version-one source API is required')
            row = {**row, 'module': _configured_module(row['module'])}
            self.references.check(row['module'])
            self.providers[row['id']] = deepcopy(row)

    def load(self, provider_id):
        self.references.guard()
        require(type(provider_id) is str and provider_id in self.providers,
            'Unknown provider; freeze a new explicit registry before extending it')
        row = self.providers[provider_id]
        module = _load_provider(row['module'], self.references)
        require(getattr(module, 'SOURCE_KIND', None) == row['source_kind']
            and all(callable(getattr(module, name, None)) for name in row['functions'].values()),
            'The frozen provider does not implement its declared source API/kind')
        return deepcopy(row), module


class LinearSourceAdmission:
    """One real cold source validation; guard calls never repeat that validation."""
    def __init__(self, source_manifest, *, provider_id, provider_registry=DEFAULT_PROVIDERS):
        self.providers = provider_registry if isinstance(provider_registry, SourceProviders) else SourceProviders(provider_registry)
        self.provider, self.helper = self.providers.load(provider_id)
        self.provider_id = provider_id
        self.references = References()
        self.source_manifest = source_manifest if isinstance(source_manifest, dict) else reference(source_manifest)
        self.references.check(self.source_manifest)
        # The provider is trusted code only after its exact module SHA and API
        # were checked. No manifest flag or caller-supplied proof bypasses it.
        source = self.helper.validate_source(deepcopy(self.source_manifest))
        require(type(source) is dict and source.get('kind') == self.provider['source_kind']
            and type(source.get('version')) is int and source['version'] == 1
            and source.get('source_financially_verified') is True,
            'The actual provider did not validate a complete financial source')
        for name in ('workbook', 'public_specification', 'bindings', 'runtime_profile'):
            require(type(source.get(name)) is dict, 'The complete source lacks ' + name)
        self.references.walk(source)
        for record in tuple(self.references.files.values()):
            self.references.discover(record)
        self.references.check(self.source_manifest)
        self.references.check(self.provider['module'])
        for path, digest in source.get('source_recipe_sha256', {}).items():
            record = reference(path)
            require(record['sha256'] == digest, 'A financial source recipe changed')
            self.references.check(record)
        self.proof = deepcopy(source)
        self.cold_source_validation_count = 1
        _ACTIVE_SOURCES.add(self)

    def guard(self):
        require(self in _ACTIVE_SOURCES, 'A live opaque source admission is required')
        self.providers.references.guard()
        self.references.guard()
        return deepcopy(self.proof)


def require_source_admission(value):
    require(type(value) is LinearSourceAdmission and value in _ACTIVE_SOURCES,
        'Persisted JSON flags cannot replace a live cold source admission')
    return value.guard()


_ACTIVE_VIEWS = weakref.WeakSet()
TASK_VALIDATOR = ROOT / 'scripts/validate_linear_capital_task_view.py'
TASK_VALIDATOR_SHA256 = '24decf5b019f1183ef6c7538c4947e9757cd160d1f11c54d9e3fce36582ae974'
REWARDS = {'oracle': 1, 'nop': 0, 'equivalent': 1, 'missed_root': 0, 'extra_change': 0}


def _task_validator(references):
    record = reference(TASK_VALIDATOR)
    require(record['sha256'] == TASK_VALIDATOR_SHA256,
        'The explicitly frozen actual task-validation protocol changed')
    references.check(record)
    name = '_linear_quality_frozen_actual_validator_' + record['sha256']
    if name not in _MODULES:
        definition = importlib.util.spec_from_file_location(name, TASK_VALIDATOR)
        module = importlib.util.module_from_spec(definition)
        definition.loader.exec_module(module)
        _MODULES[name] = module
    return _MODULES[name]


def _current_view_recipe(helper):
    from ..workbook.linear_capital_portfolio import task_views
    paths = [TASK_VALIDATOR, Path(task_views.__file__),
        ROOT/'src/sheets_factory/evaluation/streaming_delta.py',
        ROOT/'src/sheets_factory/evaluation/streaming_verifier.py',
        ROOT/'src/sheets_factory/workbook/compare.py']
    return {**helper.recipes(), **{str(p.resolve()): reference(p)['sha256'] for p in paths}}


def _completed_without_source_reexecution(module, prepared, value, provider_id, helper):
    """Reuse frozen protocol bytecode in a new private dependency namespace.

    The original module globals and functions are never patched. Only its
    preparation dependency is supplied by an already admitted source session.
    All complete-call, scope, counterfactual and control checks are unchanged.
    """
    from types import FunctionType
    namespace = dict(vars(module))
    def provider(record):
        result = helper.read(record)
        require(result.get('source_provider') == provider_id, 'The actual source provider changed')
        return provider_id
    def support(name):
        require(name == provider_id, 'A validation call selected another provider')
        return helper
    namespace.update(validate_prepared=lambda output: prepared,
        _record_provider=provider, source_support=support)
    for name in ('_require_complete_delta', '_require_typed_stability', 'validate_completed'):
        original = getattr(module, name)
        namespace[name] = FunctionType(original.__code__, namespace, name,
            original.__defaults__, original.__closure__)
    return namespace['validate_completed'](value)


class LinearViewAdmission:
    """Complete actual task ancestry with one opaque cold source admission."""
    def __init__(self, source_manifest, validation_terminal, *, provider_id,
                 provider_registry=DEFAULT_PROVIDERS):
        from ..workbook.linear_capital_portfolio import task_views
        self.source = (source_manifest if type(source_manifest) is LinearSourceAdmission else
            LinearSourceAdmission(source_manifest, provider_id=provider_id, provider_registry=provider_registry))
        require(self.source.provider_id == provider_id, 'The live source provider differs')
        source = require_source_admission(self.source)
        self.references = References()
        self.terminal = (validation_terminal if isinstance(validation_terminal, dict)
            else reference(validation_terminal))
        result = self.references.read(self.terminal)
        require(result.get('kind') == 'linear_capital_task_view_actual_validation'
            and type(result.get('version')) is int and result['version'] == 1
            and result.get('passed') is True and result.get('source_provider') == provider_id,
            'A completed source-bound actual view validation is required')
        frozen = self.references.read(result['preparation'])
        self.view_manifest = frozen['materialized_view']
        view = self.references.read(self.view_manifest)
        self.plan_ref = view['plan']; self.plan = self.references.read(self.plan_ref)
        task_views._check_plan(self.plan)
        require(view.get('kind') == 'materialized_unverified_linear_capital_task_view'
            and type(view.get('version')) is int and view['version'] == 1
            and view['mode'] in ('financial_modeling', 'debugging')
            and frozen['source_admission'] == self.source.source_manifest
            and view['source'] == self.plan['source'] == source['workbook']
            and self.plan['bindings'] == source['bindings'],
            'The complete material view is not bound to this independently admitted source')
        # These canonical identities were recomputed by the one cold source
        # validator. Reuse those checked audit facts without reading/canonicalizing
        # the very large bindings payload a second time.
        audits = [self.source.references.read(record) for record in source['financial_audits']]
        require(len(audits) == 3 and all(a.get('passed') is True
            and a.get('bindings_sha256') == self.plan['bindings_canonical_sha256']
            and a.get('specification_sha256') == self.plan['specification_sha256'] for a in audits),
            'The task plan differs from all three actual independent financial source audits')
        require(self.plan['sheetnames'] == view['sheetnames']
            and self.plan['specification_sha256'] == view['specification_sha256']
            and self.plan['mode'] == view['mode'] and self.plan['plan_sha256'] == view['plan_sha256']
            and self.plan['recipe'] == view['recipe'] == task_views._recipe(),
            'The current complete view scope, business recipe or canonical plan changed')
        for key in ('input', 'goal', 'instruction'):
            self.references.check(view[key])
        require(Path(view['instruction']['path']).read_text() == self.plan['instruction']
            and (view['goal']['sha256'], view['goal']['bytes']) ==
                (source['workbook']['sha256'], source['workbook']['bytes']),
            'The original public brief or exact source-goal copy changed')
        if view['mode'] == 'debugging':
            require(list(view['family_inputs']) == list(task_views.FAMILIES),
                'Every predeclared debugging family and same-plan counterfactual is required')
            self.references.check(view['temporary_plan_only'])
            self.references.walk(view['family_inputs'])
        else:
            require(view['family_inputs'] == {} and view['temporary_plan_only'] is None,
                'A modeling view cannot inherit a debugging counterfactual')
        module = _task_validator(self.references)
        profile = self.source.helper.runtime(source['runtime_profile']['path'])[1]
        require(frozen.get('kind') == 'prepared_linear_capital_task_view_actual_validation'
            and type(frozen.get('version')) is int and frozen['version'] == 1
            and frozen.get('source_provider') == provider_id
            and all(type(frozen.get(k)) is int and frozen[k] == 0 for k in ('model_calls','LO_calls'))
            and frozen.get('qualified') is False and frozen['recipe'] == _current_view_recipe(self.source.helper)
            and frozen['mode'] == view['mode']
            and frozen['required_stage_roles'] == module.required_roles(view['mode'], view['family_inputs'])
            and frozen['runtime_profile'] == source['runtime_profile']
            and frozen['runtime_profile_value'] == profile,
            'The complete actual validation preparation, limits or recipe changed')
        for path, digest in frozen['recipe'].items():
            record = reference(path); require(record['sha256'] == digest, 'A view-validation recipe changed')
            self.references.check(record)
        prepared = (frozen, source, view, self.plan)
        completed = _completed_without_source_reexecution(module, prepared, self.terminal,
            provider_id, self.source.helper)
        require(completed == result, 'The complete actual task terminal changed during validation')
        self.references.walk(result)
        for record in tuple(self.references.files.values()):
            self.references.discover(record)
        self.delta = self.references.read(result['complete_D'])
        self._recheck_values(result, view, module)
        self.source.guard(); self.references.guard()
        self.view = view
        self.proof = {'kind':'admitted_complete_native_linear_capital_task_view', 'version':1,
            'source_manifest':self.source.source_manifest, 'source_provider':provider_id,
            'provider_registry':self.source.providers.reference, 'provider_module':self.source.provider['module'],
            'source_financial_evidence':source, 'workbook':source['workbook'],
            'runtime_profile':source['runtime_profile'], 'public_specification':source['public_specification'],
            'bindings':source['bindings'], 'view_manifest':self.view_manifest, 'view_plan':self.plan_ref,
            'view_plan_sha256':self.plan['plan_sha256'], 'actual_validation_terminal':self.terminal,
            'mode':view['mode'], 'input':result['input'], 'goal':result['goal'],
            'instruction':result['instruction'], 'full_D':result['complete_D'],
            'full_D_count':self.delta['expected_change_count'],
            'actual_prequality_calls':result['actual_LO_calls'], 'actual_prequality_controls':result['controls_evidence'],
            'actual_prequality_family_effects':result['individual_effects'],
            'cold_source_validation_count':self.source.cold_source_validation_count,
            'normal_factory_nodes_previously_executed':False, 'prior_difficulty_transferred':False,
            'all_twelve_quality_checks_passed':False, 'recovery_certified':False,
            'Harbor_certified':False, 'difficulty_certified':False, 'qualified':False}
        _ACTIVE_VIEWS.add(self)

    def _recheck_values(self, result, view, module):
        from ..evaluation.streaming_delta import compare_workbooks
        from ..evaluation.streaming_verifier import compare_files
        from ..workbook.heterogeneous_contracts.validate import compare_typed_caches
        source, goal = result['input'], result['goal']
        binding = module._workbook_binding
        def delta(left, right, output):
            report = compare_workbooks(left['path'], right['path'], output['path'])
            report['workbook_binding'] = binding(left, right, output)
            return report
        require(delta(source, goal, goal) == self.delta,
            'The current entire input/goal delta differs from its actual terminal')
        calls = {c['role']:c for c in result['actual_LO_calls']}
        stable = self.references.read(result['goal_stability'])
        require(stable == {**compare_typed_caches(view['goal']['path'],goal['path']),
            'left':view['goal'], 'right':goal}, 'The complete source-to-goal typed stability changed')
        for index, record in enumerate(result['typed_stabilities'], 2):
            pair = self.references.read(record)
            require(pair == {'left':source, 'right':calls['input_pass'+str(index)]['output'],
                'comparison':compare_typed_caches(source['path'],calls['input_pass'+str(index)]['output']['path'])},
                'The complete actual input typed stability changed')
        controls = self.references.read(result['controls_evidence'])
        for name, reward in REWARDS.items():
            output = controls['workbooks'][name]
            observed = compare_files(source['path'],goal['path'],output['path'])
            observed['workbook_binding'] = binding(source,goal,output)
            require(observed == self.references.read(controls['reports'][name])
                and observed['reward'] == reward, 'A complete actual five-control value comparison changed')
        if view['mode'] == 'debugging':
            baseline = result['temporary_plan_baseline']
            for family, record in result['individual_effects'].items():
                effect = self.references.read(record); counter = calls['isolated_'+family]['output']
                require(effect['complete_delta'] == delta(baseline,counter,counter),
                    'An isolated family effect changed against the same provisional-plan baseline')

    def guard(self):
        require(self in _ACTIVE_VIEWS, 'A genuine opaque admitted view is required')
        self.source.guard(); self.references.guard()
        return deepcopy(self.proof)


def require_view_admission(value):
    require(type(value) is LinearViewAdmission and value in _ACTIVE_VIEWS,
        'Persisted pass flags cannot replace an actual cold source/view admission')
    return value.guard()


NORMAL_SOURCE_KIND = 'audited_native_linear_capital_source_with_actual_task_views'


def validate_configuration(config):
    from ..task_adapters import linear_capital_portfolio as adapter
    from ..nodes.quality import validate_reference_policy_selection
    from ..checkers import DiagnosisRunner
    from ..workbook.resource_engine import load_runtime_profile
    adapter.validate_setting(config.get(adapter.SETTING))
    require(validate_reference_policy_selection(config)=='independent_public_recovery',
        'The normal family requires isolated public-only reconstruction')
    recovery_config=config['recovery']
    require(recovery_config.get('compiler_backend')==adapter.recovery.BACKEND
        and type(recovery_config.get('replay_timeout_seconds')) is int
        and recovery_config['replay_timeout_seconds']==7200,
        'The public recovery backend and operational guard changed')
    adapter.recovery.validate_offline_configuration(recovery_config['offline_public_recovery'])
    adapter.recovery.validate_public_runtime(recovery_config['public_runtime_preparation'])
    require(config['pipeline']['node_registry']==str(adapter.REGISTRY)
        and config['diagnosis'].get('execution',{}).get('reference_evidence_transport')=='audited_summary'
        and config['harbor'].get('execute_controls') is True,
        'All normal routes, complete private evidence transport and actual Harbor controls are mandatory')
    # Resolve the ordinary pluggable registry rather than inventing a second QA
    # selection mechanism. The provided default configuration enables all 12.
    DiagnosisRunner(config['project_root']).resolve(config)
    run=config['run'];targets=run['targets']
    require(set(targets)=={'financial_modeling','debugging'}
        and all(type(v) is int and v>=0 for v in targets.values()) and sum(targets.values())>0
        and run.get('source_ordering')=='manifest' and not run.get('continuation_id')
        and all(type(run.get(k)) is int and run[k]>=1 for k in ('max_sources','max_parallel_sources','max_candidates_per_seed'))
        and run['max_candidates_per_seed']==1,
        'Use explicit fresh source/mode quotas with one audited physical view per source and mode')
    profile=load_runtime_profile(config[adapter.SETTING]['runtime_profile']['path'])
    limits=config['construction']['analysis_limits']
    require(limits.get('max_profile_cells')==profile['limits']['max_profile_cells']
        and limits.get('max_dependency_closure_cells')==profile['limits']['max_dependency_closure_cells']
        and all(config['construction']['max_edit_count'][m]==profile['limits']['full_target_cells'] for m in targets),
        'Complete analysis and target capacities must remain explicit and untruncated')
    agents=config['agents']
    require(agents.get('container_cpus')==2 and agents.get('container_memory')=='32g'
        and config['engine']['image']==profile['image']['tag'] and config['engine']['timeout_seconds']==600,
        'The model/source runtime profile must remain separate from the offline recovery resources')
    return profile


def validate_seed(seed, admissions):
    require(seed.get('source_kind')==NORMAL_SOURCE_KIND and type(seed.get('variant')) is int and seed['variant']==0,
        'A seed must identify an explicitly admitted native-linear source')
    source=reference(seed['local_path'])
    require(seed.get('sha256')==source['sha256'] and type(seed.get('modes')) is list
        and len(seed['modes'])==len(set(seed['modes'])) and seed['modes'], 'An exact source identity and distinct modes are required')
    evidence=seed.get('finance_evidence',{})
    require(evidence.get('financial_seed_verified') is True and evidence.get('financial_modeling_eligible') is True,
        'Complete financial source evidence is required')
    for mode in seed['modes']:
        key=(source['sha256'],mode)
        require(key in admissions,'A declared mode has no completed opaque source/view admission')
        proof=require_view_admission(admissions[key])
        require(proof['workbook']==source and evidence['linear_view_admissions'].get(mode)==proof,
            'Persisted seed evidence differs from its actual current source/view admission')


from .factory import FactoryPipeline


class LinearCapitalQualityFactory(FactoryPipeline):
    """Original scheduler and state machine with only admitted family providers."""
    def __init__(self,config,*args,admissions,**kwargs):
        validate_configuration(config)
        require(type(admissions) in (list,tuple) and admissions,'At least one opaque source/view admission is required')
        self.admissions={}
        for item in admissions:
            proof=require_view_admission(item);key=(proof['workbook']['sha256'],proof['mode'])
            require(key not in self.admissions,'A source/mode admission was duplicated')
            require(proof['runtime_profile']==config['linear_capital_portfolio']['runtime_profile']
                and proof['provider_registry']==config['linear_capital_portfolio']['provider_registry'],
                'Every selected source/view must use the same explicit quality registry and task resource profile')
            self.admissions[key]=item
        counts={mode:sum(m==mode for _,m in self.admissions) for mode in config['run']['targets']}
        require(all(config['run']['targets'][mode]<=count for mode,count in counts.items()),
            'A requested task quota exceeds the complete admitted source/mode inventory')
        super().__init__(config,*args,**kwargs)

    def load_seeds(self):
        seeds=super().load_seeds()
        for seed in seeds:validate_seed(seed,self.admissions)
        represented={(seed['sha256'],mode) for seed in seeds for mode in seed['modes']}
        require(represented==set(self.admissions),'The exact selected source/mode inventory changed')
        return seeds

    def run_phase(self,context,phase):
        identity=reference(context.source)['sha256'];key=(identity,context.mode)
        require(key in self.admissions,'This normal task has no admitted actual view')
        context.data['_linear_admission']=self.admissions[key]
        self.admissions[key].guard()
        return super().run_phase(context,phase)

    def _claim_targets(self,context):
        from ..workbook.resource_engine import load_runtime_profile
        proof=require_view_admission(context.data.get('_linear_admission'))
        plan=context.data['plan']
        require('mask_ranges' not in plan and not plan.get('scenario_inputs'),
            'The complete native view cannot change supplied assumptions or become formula-only range masking')
        cap=load_runtime_profile(proof['runtime_profile']['path'])['limits']['full_target_cells']
        edits=plan.get('edits',[])
        require(0<len(edits)<=cap and len({(e['sheet'],e['cell']) for e in edits})==len(edits),
            'The full physical target inventory must be nonempty, unique and within its declared capacity')
        return super()._claim_targets(context)
